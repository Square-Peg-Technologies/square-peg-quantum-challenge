# Quantum Storage Siting

Square Peg Technologies — PQIC Challenge

[<img src="https://qbraid-static.s3.amazonaws.com/logos/Launch_on_qBraid_white.png" width="150">](https://account.qbraid.com?gitHubUrl=https://github.com/Square-Peg-Technologies/square-peg-quantum-challenge.git)

Hybrid quantum-classical solver for battery energy storage system (BESS) siting
on power system test grids. Everything needed to install, run, and reproduce
results is in this one document — setup and usage come first, background and
results detail follow.


## Setup

Python 3.11.12 pinned via pyenv:

    pyenv local 3.11.12
    /home/<user>/.pyenv/versions/3.11.12/bin/python -m venv .venv
    .venv/bin/pip install -r requirements.txt
    .venv/bin/pip install -r requirements-gpu.txt  # GPU only, requires CUDA 12

Always activate the venv or use `.venv/bin/python` explicitly — never system python.

All dependencies are contained in this repo. There is no external setup step:
the grid-topology base classes formerly pulled from a separate local project
(via a `.pth` file pointing outside the repo) are now vendored in-repo at
`dcopf/` — nothing to install or path-hack, `pip install -r requirements.txt`
is the whole story.


## Running the Tool

Two ways to run: the browser dashboard (recommended) or the interactive CLI.

### Dashboard (Browser UI)

    .venv/bin/python dashboard.py

then open http://127.0.0.1:7860. Stop the server with Ctrl-C. Note the server
does not hot-reload: after pulling code changes, restart it.

One tab per problem, each with a compact control bar of inputs on top and
results below in sub-tabs:

    Economic Dispatch     use case, assets, hours T
    Unit Commitment       use case, assets, hours T
    Battery Siting (MIP)  + time limit (s)
    Quantum Siting        + backend, candidates, 2nd stage, warm start
    Power Flow            per-candidate network diagrams (read-only gallery)

Sub-tabs per problem: Results (quantum only — candidate ranking table),
Plots (all of the run's plots side by side, scaled to fit the window),
Runtime (quantum only — phase breakdown chart), and Terminal — the exact
CLI output including full tracebacks, with a copy button for easy debugging.

The quantum backend dropdown exposes all three backends: Qiskit (GPU),
Qiskit (CPU), Aer Tensor Network (MPS), and D-Wave SA. Selecting GPU on a
machine without one shows a dismissible error popup and nothing runs; any
mid-run failure pops a warning toast and the traceback lands in the Terminal
sub-tab.

Result caching — every run is recorded with its exact input settings.
Clicking Run with settings that were already run loads the stored results
instantly ("✅ Already run — loaded from <timestamp>") instead of re-solving.
Tick "Re-run even if cached" to force a fresh solve. Plots are snapshotted
per-run, so cached runs keep showing the correct images even after later runs
overwrite the shared filenames in `outputs/`.

Run history — a strip at the bottom of every problem tab lists all past runs
(any problem, newest first) and survives restarts.

Power Flow tab — after a Quantum Siting run, shows one network diagram per
evaluated candidate placement, ranked by true cost — committed/off
generators, battery buses, and per-line max loading (orange ≥70%, red ≥90%).

Comparing classical vs quantum — Battery Siting (MIP) and Quantum Siting
solve the same problem; the quantum tab generates the same grid +
dispatch-overview plots for its best placement (saved as `quantum_*.png` vs
`siting_*.png` so neither overwrites the other).

Files written by the dashboard:

    outputs/dashboard_settings.json   last-used inputs per tab (restored on launch)
    outputs/dashboard_history.json    run history index (cache keys, summaries)
    outputs/dashboard_runs/           per-run terminal logs + plot snapshots
    outputs/powerflow/                latest quantum run's candidate diagrams

### CLI

    .venv/bin/python main.py

Prompt flow — Step 1, choose the optimization:

    1. Economic Dispatch (ED)
    2. Unit Commitment (UC)
    3. Battery Siting (exhaustive search)
    4. Quantum Siting (Hybrid VQA + Classical)

For option 4 only, additional sub-prompts:

    Select quantum backend:
      1. Qiskit (VQA, statevector simulator)
      2. D-Wave (Simulated Annealing)
      3. Aer Tensor Network (VQA, MPS — scales to 36+ qubits)

    How many candidates to evaluate classically? [default: 10]:

    Second-stage solver:
      1. ED dispatch (fix commitment and placement)
      2. Full UC re-solve (fix placement only)

    Warm-start strategy (Qiskit and Aer TN backends only):
      1. zeros  — theta=0, paper simulation default [default]
      2. random — theta~Uniform[-2pi,2pi], paper IonQ hardware default
      3. sdp    — LP-relaxation warm start, paper Section III

Step 2 — use case (ieee14 / ieee30 / pjm5). Step 3 — assets file (scanned
from the use case directory, e.g. `assets_dc_bus4.py`). Step 4 — hours,
bounded by the loaded case's actual demand profile (all three use cases
build a one-week, 168-hour profile, so the prompt's max scales to whatever
the case supports):

    How many hours to simulate? (1-168):

Example output (Quantum Siting, ieee14, T=24h, `assets_dc_bus4.py`):

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

### Quality Gate

    .venv/bin/ruff check main.py solvers/ tests/ plots.py
    .venv/bin/mypy main.py solvers/ --ignore-missing-imports
    .venv/bin/pytest tests/ -m "not slow" -v
    .venv/bin/pytest tests/ -m slow -v        # Qiskit VQA path (~30s)


## Repo Layout

    main.py                 Entry point. Interactive CLI, dispatches to solvers.
    dashboard.py             Gradio browser dashboard.
    plots.py                 Network visualization + runtime breakdown charts (PNG per run).
    requirements.txt         Python dependencies, CPU-only (includes gradio for the dashboard).
    requirements-gpu.txt     Optional GPU extras: qiskit-aer-gpu + cuQuantum/CUDA wheels.

    dcopf/                   Vendored grid-topology base classes (BaseCase, BaseCaseDescription)
                              — PTDF/Btilde construction from MATPOWER-style case data.
                              Self-contained, numpy-only, no external project dependency.

    use_cases/
        pjm5/                 PJM 5-bus grid: 5 buses, 6 branches, 3 generators, 2 batteries.
        ieee14/                IEEE 14-bus grid: 14 buses, 20 branches, 5 generators, 4 batteries,
                              optional 200 MW AI datacenter load (assets_dc_bus{N}.py).
        ieee30/                IEEE 30-bus grid: 30 buses, 6 generators (335 MW total).

    solvers/
        results.py            EDResult, UCResult, SitingResult, QuantumSitingResult.
        ed.py                  Economic Dispatch (QP, HiGHS).
        uc.py                  Unit Commitment (MIQP, SCIP). Generic — works for any grid size.
        siting.py              Exhaustive battery siting loop.
        quantum_siting.py      VQA/SA sieve + classical refinement + debug logger.

    tests/                   Unit + integration tests (see Quality Gate above).

    Formulation/
        Siting_Formulation.pdf/.tex   Problem formulation document + LaTeX source.
        IonQ_ORNL_Unit_Commitment_2505.00145.pdf   Reference paper (Aboumrad et al., 2025).
        QUANTUM_FLOW.md         Quantum algorithm flow description.
        Test_Quantum_examples/  IonQ paper benchmark scripts.

    outputs/                 Generated plots and debug logs (gitignored).
    Constitution/             Internal planning docs (gitignored).


## What It Does

Four levels of power system optimization, all including battery storage dynamics:

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

   Three quantum backends:
   - Qiskit VQA: Butterfly ansatz (arXiv:2505.00145), COBYLA optimizer, local
     statevector simulator. GPU-accelerated via qiskit-aer-gpu when available.
     Compatible with IonQ Forte gate hardware.
   - Aer Tensor Network (MPS): Linear-chain HEA ansatz, matrix product state
     simulator. Scales to 36+ qubits (ieee30). No GPU required.
   - D-Wave Simulated Annealing: QUBO formulation sampled with
     SimulatedAnnealingSampler. No QPU connection required.

All modes use a DC power flow approximation (lossless branches, no reactive power).

Based on the IonQ/ORNL hybrid quantum-classical algorithm (arXiv:2505.00145,
`Formulation/IonQ_ORNL_Unit_Commitment_2505.00145.pdf`).


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

Demand: 24-hour shape calibrated to arXiv:2505.00145 Table IV (170-1100 MW total),
repeated over 7 days for a one-week (168h) horizon.
Unit 2 always runs; Unit 0 is the swing unit; Unit 1 ramps mid-day.

Quantum siting: 3 gen + 5 bus = 8 qubits, C(5,2) = 10 placements.
D-Wave SA matches classical optimum exactly (0% gap) in under 1 second.


### IEEE 14-Bus (ieee14)

IEEE 14-bus test system (American Electric Power, 1962, MATPOWER case14).
Includes a synthetic 200 MW AI datacenter load added at a chosen bus.

Network topology (text diagram — see `Formulation/Problem Formulation.png`
for a rendered version):

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

Base load: 259 MW across 11 buses. Demand shaped 0.45x (night) to 1.40x (peak),
repeated daily over a one-week (168h) horizon — battery SoC free-floats
continuously across the week, no reset between days.
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

Datacenter bus selection: buses 6-14 are infeasible (line limits violated).
Run `site_datacenter.py` to regenerate feasibility/cost rankings after any
change to line limits or datacenter size:

    cd use_cases/ieee14 && python site_datacenter.py

NOTE: the last regenerated ranking (T=24h) gives buses 1, 2, 3, and 4 an
identical $228,429 cost and bus 5 at $228,755 — this has drifted from an
older documented ranking that showed bus 4 and bus 5 as distinctly more
expensive with bus 3 infeasible. That older ranking predates the one-week
demand-horizon extension; it has not been root-caused yet and needs
re-verifying against the current case data before being treated as
authoritative. Re-run the script above and use its live output, not this note.

IMPORTANT — for meaningful congestion and a non-trivial P_loc(s) battery signal,
use `assets_dc_bus4.py` or `assets_dc_bus5.py`. With the datacenter at bus 1 or
bus 2 the network is uncongested: all buses price identically and the P_loc
term contributes zero to the proxy cost. Bus 4 and bus 5 force the optimizer
to route power through tight transformers and mid-network lines, creating
spatial LMP differentiation and a meaningful congestion relief signal for
battery siting.

Confirmed quantum siting result (Qiskit VQA + UC, T=24h, n=10):
Best placement buses (2, 4, 6, 7), cost $199,804 in ~2.5 min on GPU.

### LMP and Shadow Price Extraction

`use_cases/ieee14/extract_lmps.py` runs a no-battery DC-OPF on ieee14 and
extracts LMPs and shadow prices for analysis:

    .venv/bin/python use_cases/ieee14/extract_lmps.py

Outputs to `outputs/` (created automatically):

    lmps_14x24.csv           LMP at each bus for each of the 24 hours (14 × 24)
    shadow_prices_20x24.csv  Shadow price on each line for each hour (20 × 24)
    lmp_summary.csv          Per-bus LMP mean, variance, std, min, max

LMPs are the nodal marginal prices ($/MWh). Shadow prices on binding lines are
the congestion components — a bus with high PTDF exposure to a binding line has
high congestion relief value for battery placement.

The quantum solver computes these internally at runtime (see P_loc below).
`extract_lmps.py` is a standalone diagnostic tool for inspection and for
sharing data with external tools (e.g. PLEXOS baseline comparison).

Note: with the datacenter at bus 1 or bus 2 no lines bind and all shadow prices
are zero — `extract_lmps.py` will show uniform LMPs and an empty binding-lines
list. Use `assets_dc_bus4.py` or `assets_dc_bus5.py` for non-trivial output.


## Quantum Siting — How It Works

Proxy cost function (evaluated analytically per sampled bitstring, no solver call):

    Q(u, s) = c_min(u) + λ1 × P_budget(s) + λ2 × P_infeas(u) − P_loc(s)

    c_min(u)      Lower-bound dispatch cost: T × Σ_g u_g × (a×p_min² + b×p_min + c)
    P_budget(s)   (Σ s_i − B)² — penalises ≠ B batteries placed
    P_infeas(u)   max(0, D_peak − Σ_g u_g × P_max,g)² — generator shortfall penalty
    P_loc(s)      T × Σ_i s_i × signal_i — congestion relief reward

    Batteries are excluded from P_infeas: batteries shift energy across hours
    but cannot create new peak capacity. Generator commitment alone must cover
    peak demand.

    λ1 = 2 × c_min,total    (one-battery deviation costs more than max savings)
    λ2 = 20 × c_min,total / D_peak²    (any shortfall dominates c_min savings)

P_loc(s) — congestion relief battery location term:

    Before the quantum sieve, the solver runs a no-battery DC-OPF (CVXPY/HiGHS)
    on the loaded grid to extract line shadow prices μ_l,t (20 × 24 for ieee14).

    For each bus i:
        signal_i = P_bat × Σ_l (−PTDF[l,i] × μ_mean,l)

    where μ_mean,l is the time-averaged shadow price on line l ($/MWh), and
    P_bat is the battery power rating (MW). Units of signal_i are $/h.

    Positive signal_i means a battery injection at bus i tends to reduce flow
    on binding lines (congestion relief). Negative means it worsens congestion.

    P_loc(s) = T × Σ_i s_i × signal_i  ($/horizon)

    Subtracting P_loc from Q steers the quantum sieve toward buses with high
    congestion relief value without changing the feasibility structure. The term
    is in the same dollar units as c_min so no additional λ3 scaling is required.

    The P_loc term is zero when no lines bind (e.g. datacenter at bus 1 or 2).
    With the datacenter at bus 4, lines 1-5 and 2-4 bind at peak; buses 4-14
    receive signal values of ~160-302 $/h, with bus 4 highest at ~302 $/h.
    With the datacenter at bus 5, line 1-5 binds; buses 3-14 receive signal.

    If the no-battery OPF solve fails for any reason, signal defaults to zero
    and the proxy degrades gracefully to the original three-term form.

    D-Wave BQM path: the same signal is applied as a linear bias on each s_i
    variable (−signal_i added to the BQM linear coefficient for s_i).

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
    Simulator: qiskit-aer statevector (CPU or GPU)

Aer Tensor Network (MPS) path:
    Linear-chain HEA ansatz, L=4 layers
    Parameters: 2 × L × (G + N)  →  214 for ieee30 (36 qubits)
    Same COBYLA optimizer and shot counts as Qiskit VQA path
    Simulator: qiskit-aer matrix_product_state — memory scales with
    entanglement, not 2^n, enabling 36-qubit runs without GPU
    Warm-start strategies identical to Qiskit VQA path

D-Wave SA path:
    Full QUBO: linear u, linear s, u-u, s-s, and cross u-s interaction terms
    SimulatedAnnealingSampler, num_reads = max(2000, 10 × n_candidates)

Classical second stage:
    ED mode: commitment fixed from sieve bitstring. OFF generators have
             p_min/p_max zeroed before the ED solve.
    UC mode: commitment ignored — UC re-optimises freely per hour.
             Candidates sharing the same battery placement are deduplicated
             (one UC solve per unique placement).

Debug log: every run writes `outputs/quantum_siting_debug.log` with all
candidate pass/fail outcomes and error messages for post-run diagnosis.


## CPU vs GPU Support

The Qiskit VQA statevector simulation runs on either CPU or GPU. The Aer
Tensor Network (MPS) backend runs on CPU only — its memory advantage over
statevector makes GPU unnecessary for the qubit counts targeted here.
Everything else (ED, UC, Siting MIP, D-Wave SA, the dashboard) is CPU-only.

### CPU-only install (default)

    .venv/bin/pip install -r requirements.txt

Installs qiskit-aer (CPU statevector). Works on any machine, no CUDA needed.
The VQA runs correctly but slower — expect several times the GPU wall time on
ieee14-sized problems.

### GPU install (NVIDIA + CUDA 12)

    .venv/bin/pip install -r requirements.txt
    .venv/bin/pip install -r requirements-gpu.txt

`requirements-gpu.txt` installs qiskit-aer-gpu plus the cuQuantum/CUDA wheels.
qiskit-aer-gpu replaces the CPU qiskit-aer in place (same import name), so
install it second. Requires an NVIDIA GPU with CUDA 12.

Note: qiskit-aer-gpu 0.15.x is the latest GPU build. The CPU-only
qiskit-aer 0.17.x supports newer Qiskit versions but has no GPU equivalent yet.

### Selecting the device at runtime

CLI (main.py): auto-detects — uses GPU when qiskit-aer-gpu and a GPU are
present, otherwise CPU:

    Aer: GPU detected — using GPU statevector      (qiskit-aer-gpu + CUDA)
    Aer: no GPU — using CPU statevector            (qiskit-aer, CPU only)
    Aer: not installed — using Qiskit StatevectorSampler  (fallback)

Dashboard: the backend dropdown has explicit Qiskit (GPU) and Qiskit (CPU)
entries, so you always know which device is in use. Picking CPU forces CPU
even on a GPU machine (useful for timing comparisons — the runtime breakdown
chart is tagged with the backend so GPU and CPU charts coexist). Picking GPU
on a machine without one shows an error popup and nothing runs.

Programmatic: `run_quantum_siting(..., device="auto" | "GPU" | "CPU")`.

At 19 qubits (ieee14): 2¹⁹ × 4 bytes = 2 MB statevector — trivial for any
modern GPU. A typical consumer GPU runs the full VQA in ~2.5 minutes.

Always source the venv before running to ensure the venv's Qiskit build is
used rather than any system-level installation.


## Solver Performance

    Optimization       Backend          pjm5 (T=24)     ieee14 (T=24)    ieee30 (T=24)
    ------------       -------          -----------     -------------    -------------
    Economic Dispatch  HiGHS (QP)       < 1s            < 1s             < 1s
    Unit Commitment    SCIP (MIQP)      < 5s            < 5s             < 5s
    Battery Siting     Benders/SCIP     < 1 min         ~15s             ~30s
    Quantum Siting     Qiskit VQA+UC    ~10s            ~2.5 min (GPU)   —
    Quantum Siting     Aer TN (MPS)+UC  —               ~1.5 min         ~40-70s
    Quantum Siting     D-Wave SA+UC     ~5s             ~1 min           —

Quantum Siting quantum phase is independent of T; classical stage scales ~linearly
with T and n_candidates. Figures above are measured at T=24 (one day); all
three cases now support T up to 168 (one week) — expect the classical
stage/ED/UC timings to scale roughly 7x at T=168, since the quantum sieve
itself does not depend on T.


## Limitations

- DC power flow approximation only: lossless branches, no reactive power,
  no voltage magnitude/angle constraints. Line losses are a known, deliberately
  scoped-out gap (see repo TODO) — Plexos comparisons use resistance-based
  losses, this model does not.
- The quantum sieve is a proxy-cost pre-filter, not an end-to-end quantum
  optimizer: it narrows the search space analytically, then a classical
  UC/ED solve picks the winner. The quantum step's role is candidate
  generation/ranking, not final feasibility or cost evaluation.
- All "quantum" runs are simulated (statevector, tensor-network MPS, or
  classical simulated annealing) — no results here were produced on physical
  QPU hardware. Qiskit VQA is compatible with IonQ Forte gate hardware but has
  not yet been run there.
- ieee30 quantum siting currently has no confirmed Qiskit VQA benchmark
  (Solver Performance table above shows "—" for that cell) — only the Aer
  Tensor Network and classical paths have been timed at that scale. It runs
  but is unverified end-to-end and is not exercised by the fast test suite.
- Battery siting assumes exactly one battery per node (no co-located
  batteries) and a fixed battery count/spec per use case — battery sizing is
  not itself an optimization variable.
- The IEEE14 datacenter-bus cost ranking in this README currently has a
  documented discrepancy versus the code's live output (see the NOTE under
  IEEE 14-Bus above) that has not yet been root-caused.
- Contingency (generator trip) and weather-scaling scenarios referenced in
  the Phase 3 paper are not yet implemented in this codebase.


## References

Aboumrad et al., "A New Hybrid Quantum-Classical Algorithm for Solving the Unit
Commitment Problem," arXiv:2505.00145, IonQ/ORNL, 2025.
PDF: `Formulation/IonQ_ORNL_Unit_Commitment_2505.00145.pdf`

Zimmermann et al., "MATPOWER: Steady-State Operations, Planning, and Analysis
Tools for Power Systems Research and Education," IEEE Transactions on Power
Systems, 26(1), 2011.

Li & Bo, "MATPOWER 5-bus test case," 2010 IEEE PES General Meeting.
