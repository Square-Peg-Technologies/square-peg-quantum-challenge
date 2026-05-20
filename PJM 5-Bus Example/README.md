# PJM 5-Bus Classical Baseline

Classical baseline solver for a quantum battery siting problem on the PJM 5-bus
test grid. Implements three levels of power system optimization — Economic Dispatch,
Unit Commitment, and Battery Siting — all including battery storage. This is the
reference solution that a future quantum algorithm will partially replace.

Based on the IonQ/ORNL unit commitment paper (arXiv:2505.00145) and the MATPOWER
case5 network (Li & Bo, 2010 IEEE PES General Meeting).


## What It Does

The tool runs one of three optimizations on the PJM 5-bus grid over 1 to 24 hours:

1. Economic Dispatch (ED): All generators stay on. Finds the least-cost output
   for each generator each hour, subject to line flow limits and battery storage
   dynamics. Solved as a convex quadratic program (QP) using HiGHS.

2. Unit Commitment (UC): Adds binary on/off decisions for each generator each
   hour. More realistic than ED — generators can be shut down in cheap hours.
   Solved as a mixed-integer quadratic program (MIQP) using SCIP.

3. Battery Siting: Tries every combination of 2 buses out of 5 for placing the
   two batteries (10 combinations total). Runs a full UC solve for each placement
   and ranks all combinations by total system cost. This is the layer targeted for
   quantum acceleration in future work.

All three modes use a DC power flow approximation (no reactive power, no losses).


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
the original MATPOWER values (400 MW and 240 MW) so that congestion occurs only
under high-output scenarios, keeping the siting results informative.

Demand profile: 24-hour load shape calibrated to match the IonQ/ORNL paper demand
range (arXiv:2505.00145 Table IV: loads 170-1100 MW). Total system load spans 170 MW
(deep night, hour 0) to 1100 MW (midday peak, hour 11). Bus split is 30%/30%/40%
across Buses 2/3/4 (MATPOWER case5 proportions).

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
Battery Siting mode ignores the defaults and searches all 10 bus pair combinations.


## Running the Tool

    .venv/bin/python main.py

The program prompts for three inputs, then runs and prints results.

### Selection Menu

Step 1 — choose the optimization:

    Select optimization to run:
      1. Economic Dispatch (ED)
      2. Unit Commitment (UC)
      3. Battery Siting (exhaustive search)
    Enter number:

Step 2 — choose the number of hours (1-24):

    How many hours to simulate? (1-24):

Step 3 — choose the assets file (scanned from the current directory):

    Available assets files:
      1. assets.py
    Select a file (enter number):

All prompts loop on invalid input with a short error message. The program never
crashes on bad input.

### Example Session

    Select optimization to run:
      1. Economic Dispatch (ED)
      2. Unit Commitment (UC)
      3. Battery Siting (exhaustive search)
    Enter number: 2

    How many hours to simulate? (1-24): 8

    Available assets files:
      1. assets.py
    Select a file (enter number): 1

    =============================================
    Run: UC | Hours: 8 | Assets: assets.py
    Generators: {Unit 0 (Bus 1, 100-600 MW, a=0.002, b=$10, c=$500)}
                {Unit 1 (Bus 3, 100-400 MW, a=0.0025, b=$8, c=$300)}
                {Unit 2 (Bus 5,  50-200 MW, a=0.005, b=$6, c=$100)}
    Batteries:  {Bat 0 (50 MW / 200 MWh)}, {Bat 1 (50 MW / 200 MWh)}
    =============================================

    Running UC optimization for T=8 hours...

    UC Results:
    Hour |     Cost ($) |     Unit 0 |     Unit 1 |     Unit 2 | Commit | ... | Congested
    ...


## Input Files

    pjm5.py       Grid topology, PTDF matrix, line limits, and 24-hour demand profile.
                  Loaded at runtime by main.py and all solvers. Do not archive.

    assets.py     Generator and battery specifications. Defines GENERATORS and BATTERIES
                  lists. main.py scans the current directory for any file matching
                  assets*.py, so you can create alternative fleet configurations
                  (e.g. assets_large.py, assets_cheap.py) and select between them
                  at the prompt without modifying any source code.

    locations.py  Default bus assignments: GENERATOR_LOCATIONS = {0:1, 1:3, 2:5} and
                  BATTERY_LOCATIONS = {0:2, 1:4}. Used by ED and UC. Battery Siting
                  ignores this file and searches all combinations.


## Output Files

All outputs are saved to the outputs/ folder (created automatically on first run).

    outputs/{opt}_{T}h_{assets}.png    Network plot for the run.
                                       Example: uc_8h_assets.png

The plot shows:
- Generator nodes sized by final-hour output (active) or greyed out (inactive, UC only)
- Battery nodes marked with a star, labeled with final-hour state of charge
- Transmission lines colored red if congested in any hour, black otherwise
- Legend identifying node and line types

For Battery Siting runs the plot shows the best-ranked placement.

The standalone network diagram (no solver results) can also be produced with:

    .venv/bin/python plots.py


## File Structure

    main.py                 Entry point. Interactive CLI, dispatches to chosen solver.
    assets.py               Generator and battery fleet (edit or add alternatives here).
    locations.py            Default bus-to-unit assignments for ED and UC.
    pjm5.py                 Grid topology, PTDF, line limits, 24-hour demand profile.
    plots.py                Network visualization. Extended for solver result display.
    requirements.txt        Pinned dependencies.

    solvers/
        __init__.py
        results.py          EDResult, UCResult, SitingResult dataclasses.
        ed.py               Economic Dispatch solver (QP, HiGHS).
        uc.py               Unit Commitment solver (MIQP, SCIP).
        siting.py           Battery Siting — exhaustive UC loop over all bus pairs.

    tests/
        test_ed.py          ED: feasibility, power balance, generator limits, SOC.
        test_battery.py     Battery: SOC dynamics, rate limits, no simultaneous charge/discharge.
        test_uc.py          UC: commitment logic, p_min/p_max with binary, power balance.
        test_siting.py      Siting: 10 combinations returned, sorted ascending by cost.
        test_cli.py         Input validation: rejects bad hours, bad file selection.

    Formulation/
        Siting_Formulation.tex    LaTeX source for the mathematical formulation (6 pages).
        Siting_Formulation.pdf    Compiled PDF covering all sets, variables, objectives,
                                  and constraints for ED, UC, and Siting.

    Archive/
        pjm5_cost.py        Original standalone ED script (reference only, superseded
                            by solvers/ed.py).


## Solver Details

    Optimization       Problem class    Solver    Typical runtime
    ---------------    ------------     ------    ---------------
    Economic Dispatch  Convex QP        HiGHS     < 1 second (any T)
    Unit Commitment    MIQP             SCIP      5-30 seconds (T=24)
    Battery Siting     10 x MIQP        SCIP      1-5 minutes (T=24)

Both solvers are called through CVXPY. HiGHS is bundled with CVXPY. SCIP requires
the pyscipopt package (included in requirements.txt).

Battery Siting runs 10 independent UC solves sequentially. They are fully
independent and could be parallelised with multiprocessing.Pool(10) to reduce
wall time to roughly 1 UC solve. Not implemented in the current baseline.


## Environment Setup

Python 3.11.12 is pinned via pyenv. A project-local venv is required.

    pyenv local 3.11.12
    python -m venv .venv
    .venv/bin/pip install -r requirements.txt

The dcopf package (used by pjm5.py) lives in the Tutorial subfolder and is wired
in via a .pth file:

    echo "<repo-root>/Tutorial/Quantum Network Flow Diagrams" \
      > .venv/lib/python3.11/site-packages/dcopf_local.pth

Always use .venv/bin/python, never system python.


## Quality Gate

Run before committing:

    .venv/bin/ruff check main.py solvers/ tests/ assets.py locations.py plots.py
    .venv/bin/pytest tests/ -v


## Background and Motivation

This tool is the classical baseline for a quantum battery siting project. The full
problem is: given a grid, find the optimal bus locations for 2 batteries, then
dispatch all assets at minimum cost. The three optimization layers correspond to
increasing problem complexity:

- ED gives a lower bound (no commitment decisions, all units always on).
- UC is the operationally realistic version (generators can be shut down).
- Siting is the combinatorial outer layer — it is the target for quantum acceleration.

The quantum approach will replace part of the siting search with a quantum
algorithm, using this classical solution as the reference cost to beat.

The DC power flow approximation (linear PTDF-based line flows, no reactive power,
no losses) is standard for unit commitment and siting studies at this scale.
