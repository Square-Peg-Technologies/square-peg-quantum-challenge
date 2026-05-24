# Quantum Storage Siting

Hybrid quantum-classical solver for battery energy storage system (BESS) siting
on power system test grids. Implements four levels of power system optimization —
Economic Dispatch, Unit Commitment, Battery Siting, and Quantum Siting — all
including battery storage dynamics.

Two use cases are included:

- pjm5: PJM 5-bus system (MATPOWER case5). 5 buses, 6 lines, 3 generators,
  2 batteries. 8 qubits for quantum siting.
- ieee14: IEEE 14-bus system (MATPOWER case14) with a 200 MW AI datacenter load.
  14 buses, 20 branches, 5 generators, 4 batteries. 19 qubits for quantum siting.

Based on the IonQ/ORNL hybrid quantum-classical algorithm (arXiv:2505.00145,
Formulation/IonQ_ORNL_Unit_Commitment_2505.00145.pdf).


## What It Does

1. Economic Dispatch (ED): All generators stay on. Finds least-cost dispatch
   each hour subject to line flow limits and battery SoC dynamics. Solved as
   a convex QP using HiGHS.

2. Unit Commitment (UC): Adds binary on/off decisions per generator per hour.
   Solved as a MIQP using SCIP.

3. Battery Siting: Exhaustive search over all C(N, B) battery placements.
   Runs a full UC solve per placement and ranks by total system cost.

4. Quantum Siting: Hybrid quantum-classical algorithm. A quantum sieve searches
   the joint (generator commitment, battery placement) space using a cheap proxy
   cost function, producing a ranked shortlist. Each candidate is then evaluated
   with a full classical UC or ED solve.

   Two quantum backends:
   - Qiskit VQA: Butterfly ansatz (arXiv:2505.00145), COBYLA optimizer, local
     statevector simulator. GPU-accelerated via qiskit-aer-gpu when available.
     Compatible with IonQ Forte gate hardware.
   - D-Wave Simulated Annealing: QUBO formulation sampled with
     SimulatedAnnealingSampler. No QPU connection required.

All modes use a DC power flow approximation (lossless branches, no reactive power).


## Use Cases

### PJM 5-Bus (pjm5)

Standard academic test network from MATPOWER case5 (Li & Bo, 2010 IEEE PES).

Network topology:

    Bus 1 (Gen 0) ---[1-2, 500 MW]--- Bus 2 (load)
       |      \                            |
    [1-4]    [1-5]                      [2-3]
       |          \                        |
    Bus 4        Bus 5 (Gen 2)         Bus 3 (Gen 1, load)
    (load)           |                     |
                  [4-5, 350 MW]         [3-4]
                      \___________________|

Lines 1-2 (500 MW) and 4-5 (350 MW) are the only constrained lines.

Generators (from arXiv:2505.00145 Table I):

    Unit    Bus    p_min    p_max    a ($/MW²h)    b ($/MWh)    c ($)
    ----    ---    -----    -----    ----------    ---------    -----
    0        1     100 MW   600 MW    0.002          10          500
    1        3     100 MW   400 MW    0.0025           8          300
    2        5      50 MW   200 MW    0.005            6          100

Batteries: 2 × 50 MW / 200 MWh, 85% efficiency, initial SoC 50%.

Demand: 24-hour shape calibrated to arXiv:2505.00145 Table IV (170-1100 MW total).
Unit 2 always runs; Unit 0 is the swing unit; Unit 1 ramps mid-day.

Quantum siting: 3 gen + 5 bus = 8 qubits, C(5,2) = 10 placements.
D-Wave SA matches classical optimum exactly (0% gap) in under 1 second.


### IEEE 14-Bus (ieee14)

IEEE 14-bus test system (American Electric Power, 1962, MATPOWER case14).
Includes a synthetic 200 MW AI datacenter load added at a chosen bus.

Network topology (text diagram):

    Bus 1 (Gen 1, DC load) ---[1-2]--- Bus 2 (Gen 2)
     |         \                        |       \
    [1-5]     [1-2]                  [2-3]    [2-4]
     |                                 |         \
    Bus 5 ----[5-6, xfmr]----       Bus 3      Bus 4
     |         \                   (Gen 3)      |    \
    [4-5]    Bus 6 (Gen 4)                    [4-7]  [4-9, xfmr]
               |    |    \                     |          |
             [6-11][6-12][6-13]             Bus 7      Bus 9
               |     |     |               (xfmr)    /   |   \
            Bus 11 Bus 12 Bus 13          Bus 8    [9-10][9-14][7-9]
               |     |     |            (Gen 5)     |      |
            [10-11][12-13][13-14]                Bus 10  Bus 14
                           |                      |
                        Bus 14                 [10-11]
                                              Bus 11

Generator buses: 1, 2, 3, 6, 8
Load buses:      2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14
Transformer branches: 4-7 (ratio 0.978), 4-9 (ratio 0.969), 5-6 (ratio 0.932)

Base load: 259 MW across 11 buses. Demand shaped 0.45x (night) to 1.40x (peak).
With 200 MW datacenter: peak total demand ~563 MW.

Key transmission bottlenecks (line limits tightened from original unlimited case14):

    Branch    Limit     Notes
    ------    -----     -----
    4-9        40 MW    Tightest bottleneck — transformer to bus-9 cluster
    5-6        80 MW    Sole path from main network to bus-6 cluster
    6-12       60 MW    Limits supply to bus 12
    13-14      60 MW    Restricts power to bus 14
    7-8        80 MW    Transformer to Gen 5 at bus 8
    7-9       100 MW    Path to lower bus cluster

Full line limits in branch order [MW]:

    [400, 120, 120, 120, 120, 120, 9999, 80, 40, 80, 80, 60, 120, 80, 100, 200, 80, 80, 80, 60]

Generators (MATPOWER case14 / gencost, linear cost function):

    Gen    Bus    p_min     p_max     $/MWh    Notes
    ---    ---    -----     -----     -----    -----
    1       1      50 MW    332 MW      20     Swing bus, cheapest
    2       2      20 MW    140 MW      20     Second cheapest
    3       3      20 MW    100 MW      40     Higher cost
    4       6      20 MW    100 MW      40     Higher cost
    5       8      20 MW    100 MW      40     Higher cost

Total capacity: 772 MW. Peak demand 563 MW requires Gen 1 + Gen 2 + at least
one of Gen 3/4/5.

Batteries: 4 × 50 MW / 200 MWh, 90% efficiency, initial SoC 100%.
Quantum siting: 5 gen + 14 bus = 19 qubits, C(14,4) = 1,001 placements.

Datacenter bus selection: buses 3 and 6-14 are infeasible (line limits violated).
Feasible buses ranked by total 24h ED cost:

    Rank    Bus    24h Cost ($)    Notes
    ----    ---    ------------    -----
    1        1       228,429       Swing bus; cheapest
    2        2       228,429       Near Gen 2
    3        4       231,178       Moderate congestion on 2-4, 2-5 lines
    4        5       234,906       Congested via 1-5 line

Run site_datacenter.py to regenerate these rankings after any change to
line limits or datacenter size:

    cd use_cases/ieee14 && python site_datacenter.py

Confirmed quantum siting result (Qiskit VQA + UC, T=24h, n=10):
Best placement buses (2, 4, 6, 7), cost $199,804 in ~2.5 min on RTX 3080 Ti.


## Running the Tool

Always use the venv Python:

    source .venv/bin/activate
    python main.py

Or without activating:

    .venv/bin/python main.py

### Prompt Flow

Step 1 — optimization:

    1. Economic Dispatch (ED)
    2. Unit Commitment (UC)
    3. Battery Siting (exhaustive search)
    4. Quantum Siting (Hybrid VQA + Classical)

For option 4 only, three additional sub-prompts:

    Select quantum backend:
      1. Qiskit (VQA, local simulator)
      2. D-Wave (Simulated Annealing)

    How many candidates to evaluate classically? [default: 10]:

    Second-stage solver:
      1. ED dispatch (fix commitment and placement)
      2. Full UC re-solve (fix placement only)

Step 2 — hours (1-24):

    How many hours to simulate? (1-24):

Step 3 — use case:

    Available use cases:
      1. ieee14
      2. pjm5

Step 4 — assets file (scanned from the use case directory):

    Available assets files:
      1. assets.py
      2. assets_dc_bus1.py
      ...

### Example Output (Quantum Siting, ieee14, T=24h)

    =============================================
    Run: Quantum Siting | Hours: 24 | Use case: ieee14 | Assets: assets_dc_bus1.py
    Datacenter: 200 MW flat load injected at Bus 1
    Generators: {Gen 1 (Bus 1, 50.0-332.0 MW, b=$20.0)}
                {Gen 2 (Bus 2, 20.0-140.0 MW, b=$20.0)}
                ...
    Batteries:  {Bat 0 (50.0 MW / 200.0 MWh)}, ...
    =============================================

    Running Quantum Siting optimization for T=24 hours...
    Aer: GPU detected — using GPU statevector

    Quantum Siting Results (Qiskit VQA + UC refinement)
    Quantum candidates found:   10
    Candidates evaluated:       10
    Runtime — quantum sieve:    145.6s
    Runtime — classical stage:  10.1s

    Best placement: buses (2, 4, 6, 7), cost $199,804

    Rank   Bat Placement           True Cost ($)
    --------------------------------------------
    1      (2, 4, 6, 7)                 199,804
    ...


## Quantum Siting — How It Works

Proxy cost function (evaluated analytically per sampled bitstring, no solver call):

    Q(u, s) = c_min(u) + λ1 × P_budget(s) + λ2 × P_infeas(u)

    c_min(u)      Lower-bound dispatch cost: T × Σ_g u_g × (a×p_min² + b×p_min + c)
    P_budget(s)   (Σ s_i − B)² — penalises ≠ B batteries placed
    P_infeas(u)   max(0, D_peak − Σ_g u_g × P_max,g)² — generator shortfall penalty

    Batteries are excluded from P_infeas: batteries shift energy across hours
    but cannot create new peak capacity. Generator commitment alone must cover
    peak demand.

    λ1 = 2 × c_min,total    (one-battery deviation costs more than max savings)
    λ2 = 20 × c_min,total / D_peak²    (any shortfall dominates c_min savings)

Qubit encoding: [u_0 ... u_{G-1}  s_0 ... s_{N-1}]
All counts (G, N, B) are resolved from the loaded assets at runtime — nothing
is hardcoded. Alternative asset files with different generator/battery counts
work automatically.

Qiskit VQA path:
    Butterfly ansatz (arXiv:2505.00145), L=3 layers for simulation
    (L=6 targeted for IonQ Forte Phase 3)
    Parameters: 2 × L × (G + N)  →  114 for ieee14
    COBYLA optimizer, 512 shots/iteration, up to 300 iterations
    5,000-shot final extraction, top-N candidates passed to classical stage
    Total: ~154,000 proxy evaluations (all analytical) + N UC/ED solves

D-Wave SA path:
    Full QUBO: linear u, linear s, u-u, s-s, and cross u-s interaction terms
    SimulatedAnnealingSampler, num_reads = max(2000, 10 × n_candidates)

Classical second stage:
    ED mode: commitment fixed from sieve bitstring. OFF generators have
             p_min/p_max zeroed before the ED solve.
    UC mode: commitment ignored — UC re-optimises freely per hour.
             Candidates sharing the same battery placement are deduplicated
             (one UC solve per unique placement).

Debug log: every run writes outputs/quantum_siting_debug.log with all candidate
pass/fail outcomes and error messages for post-run diagnosis.


## GPU Acceleration

The Qiskit VQA path auto-detects GPU at import:

    Aer: GPU detected — using GPU statevector      (qiskit-aer-gpu + CUDA)
    Aer: no GPU — using CPU statevector            (qiskit-aer, CPU only)
    Aer: not installed — using Qiskit StatevectorSampler  (fallback)

At 19 qubits (ieee14): 2¹⁹ × 4 bytes = 2 MB statevector — trivial for any
modern GPU. RTX 3080 Ti (16 GB VRAM) runs the full VQA in ~2.5 minutes.

Install GPU version (requires Qiskit 1.x and CUDA 12):

    .venv/bin/pip install qiskit-aer-gpu==0.15.1

Note: qiskit-aer-gpu 0.15.x is the latest GPU build and requires Qiskit <2.0.
requirements.txt is pinned to qiskit<2.0. The CPU-only qiskit-aer 0.17.x
supports Qiskit 2.x but has no GPU equivalent yet.

Always source the venv before running to ensure the GPU-enabled Qiskit is used
rather than any system-level installation.


## File Structure

    main.py                 Entry point. Interactive CLI, dispatches to solvers.
    plots.py                Network visualization (outputs PNG per run).
    requirements.txt        Python dependencies.

    use_cases/
        pjm5/
            pjm5.py             PJM 5-bus grid: 5 buses, 6 branches, 3 generators.
            assets.py           3 generators, 2 batteries.
            locations.py        Default bus assignments for ED/UC.

        ieee14/
            ieee14.py           IEEE 14-bus grid: 14 buses, 20 branches, 5 generators.
            assets.py           5 generators, 4 batteries, no datacenter (base template).
            assets_dc_bus1.py   Datacenter at bus 1, 200 MW (cheapest — use this).
            assets_dc_bus2.py   Datacenter at bus 2.
            assets_dc_bus4.py   Datacenter at bus 4.
            assets_dc_bus5.py   Datacenter at bus 5.
            locations.py        Fixed generator locations; placeholder battery locations.
            site_datacenter.py  Sweeps all 14 buses, ranks by ED cost, writes assets files.

    solvers/
        results.py          EDResult, UCResult, SitingResult, QuantumSitingResult.
        ed.py               Economic Dispatch (QP, HiGHS).
        uc.py               Unit Commitment (MIQP, SCIP). Generic — works for any grid size.
        siting.py           Exhaustive battery siting loop.
        quantum_siting.py   VQA/SA sieve + classical refinement + debug logger.

    tests/
        test_ed.py              ED feasibility, power balance, generator limits, SoC.
        test_uc.py              UC commitment logic, p_min/p_max, power balance.
        test_siting.py          Siting: all combinations returned, sorted by cost.
        test_cli.py             Input validation: all prompts, bad-input rejection.
        test_quantum_siting.py  Proxy cost, BQM structure, ansatz shape, Qiskit VQA.

    Formulation/
        Siting_Formulation.pdf              Problem formulation document.
        Siting_Formulation.tex              LaTeX source.
        IonQ_ORNL_Unit_Commitment_2505.00145.pdf   Reference paper (Aboumrad et al., 2025).
        QUANTUM_FLOW.md                     Quantum algorithm flow description.
        Problem Formulation.png             Diagram.
        Test_Quantum_examples/              IonQ paper benchmark scripts.

    outputs/                    Generated plots and debug logs (gitignored).
    Constitution/               Internal planning docs (gitignored).


## Solver Performance

    Optimization       Backend          pjm5 (T=24)     ieee14 (T=24)
    ------------       -------          -----------     -------------
    Economic Dispatch  HiGHS (QP)       < 1s            < 1s
    Unit Commitment    SCIP (MIQP)      5-30s           5-30s
    Battery Siting     SCIP × C(N,B)   ~1 min          ~15-20 min
    Quantum Siting     Qiskit VQA+UC   ~30s            ~2.5 min (GPU)
    Quantum Siting     D-Wave SA+UC    ~5s             ~1 min

Battery Siting runtime: C(5,2)=10 for pjm5; C(14,4)=1,001 for ieee14.
Quantum Siting quantum phase is independent of T; classical stage scales ~linearly
with T and n_candidates.


## Environment Setup

Python 3.11.12 pinned via pyenv:

    pyenv local 3.11.12
    /home/<user>/.pyenv/versions/3.11.12/bin/python -m venv .venv
    .venv/bin/pip install -r requirements.txt
    .venv/bin/pip install qiskit-aer-gpu==0.15.1   # GPU only, requires CUDA 12

Always activate the venv or use .venv/bin/python explicitly — never system python.

The dcopf package (used by pjm5.py) requires a .pth file:

    echo "<repo-root>/Tutorial/Quantum Network Flow Diagrams" \
      > .venv/lib/python3.11/site-packages/dcopf_local.pth


## Quality Gate

    .venv/bin/ruff check main.py solvers/ tests/ plots.py
    .venv/bin/mypy main.py solvers/ --ignore-missing-imports
    .venv/bin/pytest tests/ -m "not slow" -v
    .venv/bin/pytest tests/ -m slow -v        # Qiskit VQA path (~30s)


## References

Aboumrad et al., "A New Hybrid Quantum-Classical Algorithm for Solving the Unit
Commitment Problem," arXiv:2505.00145, IonQ/ORNL, 2025.
PDF: Formulation/IonQ_ORNL_Unit_Commitment_2505.00145.pdf

Zimmermann et al., "MATPOWER: Steady-State Operations, Planning, and Analysis
Tools for Power Systems Research and Education," IEEE Transactions on Power
Systems, 26(1), 2011.

Li & Bo, "MATPOWER 5-bus test case," 2010 IEEE PES General Meeting.
