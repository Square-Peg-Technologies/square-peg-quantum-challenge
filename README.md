# square-peg-quantum-challenge

Hybrid quantum-classical solver for battery energy storage system (BESS) siting
on power system test grids, developed for the PQIC Phase 2 challenge.

Implements the IonQ/ORNL algorithm (arXiv:2505.00145) extended with congestion
relief-aware battery placement, a Benders decomposition siting solver, and a
Gradio browser dashboard.

Full documentation: quantum-storage-siting/README.md


## What is in this repo

    quantum-storage-siting/   Main Python package — solvers, use cases, dashboard, tests.


## What has been built

Four levels of power system optimization, all with battery storage dynamics:

1. Economic Dispatch (ED) — convex QP via HiGHS. Runs in under 1 second.
2. Unit Commitment (UC) — MIQP via SCIP. Adds binary generator on/off decisions.
3. Battery Siting (MIP/Benders) — finds the optimal battery placement without
   exhaustive enumeration. Uses Benders decomposition with parallel UC subproblem
   solves and integer L-shaped optimality cuts.
4. Quantum Siting — hybrid VQA/SA sieve + classical UC/ED refinement. Three backends:
   - Qiskit VQA: butterfly ansatz (arXiv:2505.00145), COBYLA, GPU statevector.
   - Aer Tensor Network: MPS simulator, scales to 36+ qubits.
   - D-Wave Simulated Annealing: QUBO formulation, no QPU connection required.

A Gradio browser dashboard (dashboard.py) wraps all four solvers with result
caching, run history, per-candidate power flow diagrams, and runtime breakdown
charts.

Three test-case grids:

- pjm5: PJM 5-bus system, 3 generators, 2 batteries, 8 qubits for quantum siting.
- ieee14: IEEE 14-bus system with optional 200 MW AI datacenter load, 5 generators,
  4 batteries, 19 qubits for quantum siting.
- ieee30: IEEE 30-bus system, larger network for scaling experiments.

The quantum proxy cost function includes a P_loc congestion relief term: a
no-battery DC-OPF is run before the quantum sieve to extract line shadow prices
and PTDF-weighted per-bus congestion signals. This steers the quantum optimizer
toward batteries that relieve binding transmission constraints.


## Quick start

    cd quantum-storage-siting
    pyenv local 3.11.12
    python -m venv .venv
    .venv/bin/pip install -r requirements.txt
    .venv/bin/pip install -r requirements-gpu.txt   # GPU machines only (CUDA 12)

    # Interactive CLI
    .venv/bin/python main.py

    # Browser dashboard
    .venv/bin/python dashboard.py
    # then open http://127.0.0.1:7860

    # Quality gate
    .venv/bin/ruff check main.py solvers/ tests/ plots.py
    .venv/bin/mypy main.py solvers/ --ignore-missing-imports
    .venv/bin/pytest tests/ -m "not slow" -v


## Key reference

Aboumrad et al., "A New Hybrid Quantum-Classical Algorithm for Solving the Unit
Commitment Problem," arXiv:2505.00145, IonQ/ORNL, 2025.
PDF: quantum-storage-siting/Formulation/IonQ_ORNL_Unit_Commitment_2505.00145.pdf
