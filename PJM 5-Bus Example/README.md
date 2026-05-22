# PJM 5-Bus Quantum-Classical Siting Solver

Hybrid quantum-classical solver for battery siting on the PJM 5-bus test grid.
Implements four levels of power system optimization — Economic Dispatch, Unit
Commitment, Battery Siting, and Quantum Siting — all including battery storage.

Based on the IonQ/ORNL hybrid quantum-classical algorithm (arXiv:2505.00145) and
the MATPOWER case5 network (Li & Bo, 2010 IEEE PES General Meeting).


## What It Does

The tool runs one of four optimizations on the PJM 5-bus grid over 1 to 24 hours:

1. Economic Dispatch (ED): All generators stay on. Finds the least-cost output
   for each generator each hour, subject to line flow limits and battery storage
   dynamics. Solved as a convex quadratic program (QP) using HiGHS.

2. Unit Commitment (UC): Adds binary on/off decisions for each generator each
   hour. More realistic than ED — generators can be shut down in cheap hours.
   Solved as a mixed-integer quadratic program (MIQP) using SCIP.

3. Battery Siting: Tries every combination of 2 buses out of 5 for placing the
   two batteries (10 combinations total). Runs a full UC solve for each placement
   and ranks all combinations by total system cost.

4. Quantum Siting: Hybrid quantum-classical algorithm. A quantum sieve searches
   the joint (generator commitment, battery placement) space using a cheap proxy
   cost function, producing a ranked shortlist of candidates. Each candidate is
   then evaluated with a classical solver (ED or UC) to find the true best
   solution. Implements the approach from arXiv:2505.00145.

   Two quantum backends are supported:
   - Qiskit VQA: Butterfly ansatz circuit optimized with COBYLA on a local
     statevector simulator. Compatible with IonQ Forte gate hardware.
   - D-Wave Simulated Annealing: QUBO formulation sampled with
     SimulatedAnnealingSampler. No QPU connection required.

All modes use a DC power flow approximation (no reactive power, no losses).


## The Grid

PJM 5-bus system (MATPOWER case5), a standard academic test network with 5 buses,
6 transmission lines, and 3 load buses.

Network topology:

    Bus 1 (gen) ---[1-2]--- Bus 2 (load 300 MW)
       |  \                      |
      [1-4] [1-5]              [2-3]
       |      \                  |
    Bus 4     Bus 5 (gen)     Bus 3 (gen, load 300 MW)
    (load       |               |
    400 MW)   [4-5]           [3-4]
                \_______________/
                    Bus 4

Lines and flow limits (MW):

    Line    From-To    Limit
    ------  -------    -----
    1       1-2        500 MW  (constrained)
    2       1-4        unconstrained
    3       1-5        unconstrained
    4       2-3        unconstrained
    5       3-4        unconstrained
    6       4-5        350 MW  (constrained)

Lines 1-2 and 4-5 are the only constrained lines. The limits were increased from
the original MATPOWER values so that congestion occurs only under high-output
scenarios, keeping the siting results informative.

Demand profile: 24-hour load shape calibrated to match the IonQ/ORNL paper demand
range (arXiv:2505.00145 Table IV: loads 170-1100 MW). Total system load spans
170 MW (deep night, hour 0) to 1100 MW (midday peak, hour 11). Bus split is
30%/30%/40% across Buses 2/3/4.

    Hours 0-5:   170-300 MW  (Unit 2 only — Units 0 and 1 off)
    Hours 6-8:   450-800 MW  (Units 1+2 — Unit 0 still off)
    Hours 9-19: 800-1100 MW  (all 3 units on)
    Hours 20-23: 400-600 MW  (Units 1+2 — Unit 0 off again)


## Generators

Three units from Table I of the IonQ/ORNL paper (arXiv:2505.00145).
Quadratic cost function: F(p) = a*p^2 + b*p + c (USD per hour when on).

    Unit    Bus    p_min    p_max    a ($/MW2h)    b ($/MWh)    c ($)    Startup ($)
    ------  ---    -----    -----    ----------    ---------    -----    -----------
    Unit 0   1     100 MW   600 MW    0.002          10          500          0
    Unit 1   3     100 MW   400 MW    0.0025          8          300          0
    Unit 2   5      50 MW   200 MW    0.005           6          100          0

Unit 2 is cheapest per MWh and always runs at its ceiling. Unit 0 is the swing unit.
No-load cost c is paid whenever the unit is committed ON in UC. Startup costs are
zero for this dataset.


## Batteries

Two utility-scale Li-ion batteries (NREL ATB 2024 standard specs).

    Parameter              Value
    ---------              -----
    Power rating           50 MW each
    Energy capacity        200 MWh each
    Round-trip efficiency  85%
    Initial SOC            100 MWh (50% of capacity)
    Min SOC                0 MWh
    Max SOC                200 MWh

Batteries can only charge or discharge in a given hour, not both simultaneously.
SOC evolves each hour: SOC[t] = SOC[t-1] + efficiency * charge[t] - discharge[t].

Default placements (used by ED and UC): Bus 2 and Bus 4.
Battery Siting and Quantum Siting search for optimal placements automatically.


## Running the Tool

    .venv/bin/python main.py

The program prompts for inputs, then runs and prints results.

### Selection Menu

Step 1 — choose the optimization:

    Select optimization to run:
      1. Economic Dispatch (ED)
      2. Unit Commitment (UC)
      3. Battery Siting (exhaustive search)
      4. Quantum Siting (Hybrid VQA + Classical)
    Enter number:

For option 4, three additional sub-prompts appear before the hours/assets prompts:

    Select quantum backend:
      1. Qiskit (VQA, local simulator)
      2. D-Wave (Simulated Annealing)
    Enter number:

    How many candidates to evaluate classically? [default: 10]:

    Second-stage solver:
      1. ED dispatch (fix commitment and placement)
      2. Full UC re-solve (fix placement only)
    Enter number:

Step 2 — choose the number of hours (1-24):

    How many hours to simulate? (1-24):

Step 3 — choose the assets file (scanned from the current directory):

    Available assets files:
      1. assets.py
    Select a file (enter number):

All prompts loop on invalid input. The program never crashes on bad input.

### Example Session (Quantum Siting)

    Select optimization to run: 4
    Select quantum backend: 2
    How many candidates to evaluate classically? [default: 10]: 10
    Second-stage solver: 2
    How many hours to simulate? (1-24): 4
    Select a file (enter number): 1

    Quantum Siting Results (D-Wave SA + UC refinement)
    Quantum candidates found:   10
    Candidates evaluated:       7
    Runtime — quantum sieve:    0.4s
    Runtime — classical stage:  2.1s

    Rank   Bat Placement        True Cost ($)
    --------------------------------------------
    1      (1, 2)                      14,430
    ...

    Best placement: buses (1, 2), cost $14,430

    Commitment schedule (UC re-optimised per hour):
      Hour |   Unit 0 |   Unit 1 |   Unit 2
      ----------------------------------------
         1 |      OFF |       ON |       ON
         2 |      OFF |       ON |       ON
         3 |       ON |       ON |       ON
         4 |       ON |       ON |       ON

Note: evaluated count may be less than candidates requested. In UC mode,
candidates that decode to the same battery bus placement are collapsed to one
evaluation (UC re-optimises commitment freely, so the result is identical).
Infeasible placements caught by the solver are also skipped.


## Quantum Siting — How It Works

The proxy cost function Q(u, s) is evaluated lazily on the classical device from
a sampled bitstring, avoiding any Pauli Hamiltonian decomposition (see reference
[12] in arXiv:2505.00145):

    Q(u, s) = c_min(u) + λ1 × P_budget(s) + λ2 × P_infeas(u, s)

    c_min(u)      Lower-bound dispatch cost for committed generators.
    P_budget(s)   Penalises anything other than exactly B batteries placed.
    P_infeas(u,s) Penalises combinations that cannot meet peak demand.

Qubit encoding: [u_0 ... u_{G-1}  s_0 ... s_{N-1}]
  G = number of generators (3 for default assets)
  N = number of buses (5 for PJM 5-bus)
  Total qubits: G + N = 8

All counts (G, N, B) are read from the loaded assets at runtime — nothing is
hardcoded, so alternative asset files with different fleet sizes work automatically.

Qiskit VQA path:
  Butterfly ansatz (L=3 layers, O(L log N) depth), COBYLA optimization,
  512 shots per iteration, up to 300 iterations, 5000-shot final extraction.

D-Wave path:
  Full QUBO with all linear, u-u, s-s, and cross u-s interaction terms.
  SimulatedAnnealingSampler, num_reads = max(2000, 10 × n_candidates).

Classical second stage:
  ED mode: commitment is fixed from the sieve bitstring (u_bits). Generators
    marked OFF have their p_min/p_max zeroed before the ED solve.
  UC mode: commitment is ignored — UC re-optimises it freely per hour. Candidates
    sharing the same battery placement are deduplicated (one UC solve covers all
    of them). The displayed commitment schedule reflects what UC actually chose,
    not the sieve's u_bits.

Candidates evaluated may be fewer than requested when:
  - Multiple sieve candidates decode to the same battery bus assignment (UC mode)
  - A placement is infeasible given line limits at peak demand (both modes)


## Input Files

    pjm5.py       Grid topology, PTDF matrix, line limits, and 24-hour demand profile.

    assets.py     Generator and battery specifications. Defines GENERATORS and BATTERIES
                  lists. main.py scans the current directory for any file matching
                  assets*.py, so you can create alternative fleet configurations
                  (e.g. assets_large.py) and select between them at the prompt.

    locations.py  Default bus assignments for ED and UC (not used by Quantum Siting).


## Output Files

All outputs are saved to the outputs/ folder (created automatically on first run).

    outputs/{opt}_{T}h_{assets}.png    Network plot for the run.

The plot shows generator nodes sized by output, battery nodes with SOC labels,
and transmission lines colored red if congested. Quantum Siting runs do not
generate a plot (best placement is printed in the terminal output).


## File Structure

    main.py                 Entry point. Interactive CLI, dispatches to chosen solver.
    assets.py               Generator and battery fleet.
    locations.py            Default bus-to-unit assignments for ED and UC.
    pjm5.py                 Grid topology, PTDF, line limits, 24-hour demand profile.
    plots.py                Network visualization.
    requirements.txt        Dependencies (classical + quantum).

    solvers/
        __init__.py
        results.py          EDResult, UCResult, SitingResult, QuantumSitingResult dataclasses.
        ed.py               Economic Dispatch solver (QP, HiGHS).
        uc.py               Unit Commitment solver (MIQP, SCIP).
        siting.py           Battery Siting — exhaustive UC loop over all bus pairs.
        quantum_siting.py   Quantum Siting — VQA/SA sieve + classical refinement.

    tests/
        conftest.py             pytest mark registration.
        test_ed.py              ED: feasibility, power balance, generator limits, SOC.
        test_battery.py         Battery: SOC dynamics, rate limits, no simultaneous charge/discharge.
        test_uc.py              UC: commitment logic, p_min/p_max with binary, power balance.
        test_siting.py          Siting: 10 combinations returned, sorted ascending by cost.
        test_cli.py             Input validation: all prompt functions, bad input rejection.
        test_quantum_siting.py  Quantum Siting: proxy cost, BQM structure, ansatz, Qiskit VQA.


## Solver Details

    Optimization       Problem class        Backend              Typical runtime
    ---------------    ----------------     -------              ---------------
    Economic Dispatch  Convex QP            HiGHS                < 1s (any T)
    Unit Commitment    MIQP                 SCIP                 5-30s (T=24)
    Battery Siting     10 x MIQP            SCIP                 1-5 min (T=24)
    Quantum Siting     VQA or SA + ED/UC    Qiskit / D-Wave SA   5-30s (T=4, n=10)

Quantum Siting runtime scales with n_candidates (classical stage) and n_layers
(Qiskit VQA circuit depth). D-Wave SA is significantly faster than Qiskit VQA
for the same n_candidates.


## Environment Setup

Python 3.11.12 is pinned via pyenv. A project-local venv is required.

    pyenv local 3.11.12
    python -m venv .venv
    .venv/bin/python -m pip install -r requirements.txt

The dcopf package (used by pjm5.py) lives in the Tutorial subfolder and is wired
in via a .pth file:

    echo "<repo-root>/Tutorial/Quantum Network Flow Diagrams" \
      > .venv/lib/python3.11/site-packages/dcopf_local.pth

Always use .venv/bin/python, never system python.


## Quality Gate

Run before committing:

    .venv/bin/ruff check main.py solvers/ tests/ assets.py locations.py plots.py
    .venv/bin/mypy main.py solvers/ --ignore-missing-imports
    .venv/bin/pytest tests/ -m "not slow" -v
    .venv/bin/pytest tests/ -m slow -v   # Qiskit VQA path (~30s)


## Background and Motivation

This tool is the classical and quantum baseline for a battery siting project. The
four optimization layers correspond to increasing problem complexity:

- ED gives a lower bound (no commitment decisions, all units always on).
- UC is the operationally realistic version (generators can be shut down).
- Siting is the combinatorial outer layer — exhaustive search over all bus pairs.
- Quantum Siting replaces the combinatorial search with a quantum sieve, using
  the classical solution as the reference cost to beat.

The quantum approach reduces the siting search from an exhaustive enumeration to
a heuristic sieve over the joint (commitment, placement) space. On the PJM 5-bus
grid with default assets, the D-Wave SA path matches the classical optimum exactly
(0% gap) in under 1 second. The Qiskit VQA path runs in ~5 seconds on a local
statevector simulator and is compatible with IonQ Forte gate hardware.

Reference: arXiv:2505.00145 — "A New Hybrid Quantum-Classical Algorithm for
Solving the Unit Commitment Problem", Aboumrad et al., IonQ/ORNL, 2025.
