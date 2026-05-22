# Quantum Siting Solver — Feature Specification

## Overview

A fourth optimization option for the PJM 5-bus problem that combines binary generator commitment
and battery siting into a single quantum sieve stage, followed by classical refinement. Based on
the IonQ/ORNL hybrid quantum-classical algorithm (arXiv:2505.00145).

The quantum sieve uses a Variational Quantum Algorithm (VQA) or Simulated Annealing to search the
combined (generator commitment, battery placement) space using a cheap proxy cost function. The
top K candidates are then evaluated with a classical solver to find the true best solution.

---

## Problem Formulation

### Decision Variables

- u_g ∈ {0,1}: generator g is committed (on/off)
- s_i ∈ {0,1}: a battery is placed at bus i

### Qubit Encoding

Bitstring layout: [u_0, ..., u_{G-1}, s_0, ..., s_{N-1}]

- G = number of generators (from assets file)
- N = number of buses (from grid)
- B = number of batteries (from assets file)
- Total qubits: G + N

For default PJM 5-bus assets: G=3, N=5, B=2 → 8 qubits.
All counts are read at runtime — nothing hardcoded.

### Proxy Cost Function

Q(u, s) = c_min(u) + λ1 × P_budget(s) + λ2 × P_infeas(u, s)

c_min(u) = Σ_g u_g × (a_g × p_min_g² + b_g × p_min_g + c_g)
    Lower-bound dispatch cost for committed generators. Linear in u.
    Same formulation as IonQ paper equation (8).

P_budget(s) = (Σ_i s_i - B)²
    Penalises anything other than exactly B batteries placed.
    Expands to: (1 - 2B) × Σ_i s_i + 2 × Σ_{i<j} s_i s_j + B²

P_infeas(u, s) = (D_ref - Σ_g u_g × P_max_g - Σ_i s_i × P_bat_max)²
    D_ref = peak demand over the T-hour horizon.
    P_bat_max = rated power of one battery (from assets).
    Penalises combinations that cannot meet peak demand.
    Expands to u-u, s-s, and u-s cross terms.

λ1, λ2 are penalty weights scaled to the same order of magnitude as c_min values
(derived using the same approach as compute_lambda() in uc_10gen_benchmark.py).

Key property: Q(u, s) is evaluated lazily on the classical device from a sampled bitstring.
No Pauli Hamiltonian decomposition is needed. This matches the IonQ paper's approach
(see equation 12-13 and the discussion referencing [12]).

---

## Quantum Sieve Stage

### Backend A — Qiskit VQA (local statevector simulator, IonQ Forte compatible)

Circuit: Butterfly ansatz for (G + N) qubits, L layers (default L=3).
    Structure: alternating RZX entangling blocks and RY mixer layers.
    Same pattern as uc_10gen_benchmark.py lines 170-187.
    Depth: O(L log N), parameters: O(L × N).

COBYLA optimization loop:
    1. Bind current θ to ansatz.
    2. Sample 512 shots via Qiskit StatevectorSampler (shot-based to match hardware behavior).
    3. For each sampled bitstring, evaluate Q(u, s) classically.
    4. Return empirical average ⟨Q⟩ = Σ (count/512) × Q(bitstring) as COBYLA objective.
    5. Repeat up to 300 iterations.

Candidate extraction after convergence:
    Sample 5000 shots from optimised circuit.
    Filter to bitstrings where Σ s_i == B (exactly B batteries placed).
    Sort by Q(u, s). Return top n_candidates unique feasible bitstrings as C*.

### Backend B — D-Wave Simulated Annealing

Build dimod.BinaryQuadraticModel encoding Q(u, s):
    Linear terms from c_min(u), P_budget(s), P_infeas(u, s).
    Quadratic terms from P_budget and P_infeas expansions.
    Cross terms between u and s variables from P_infeas expansion.

Run SimulatedAnnealingSampler with num_reads = max(2000, 10 × n_candidates).
Filter samples to Σ s_i == B. Sort by energy. Return top n_candidates as C*.

---

## Classical Refinement Stage

For each candidate (u, s) in C*:

Decode battery locations:
    bat_locs = {battery_idx: bus_idx for bus_idx in sorted(buses where s_i == 1)}

Second-stage option ED (fix u and s):
    Call run_ed() with bat_locs from s.
    Generators with u_g = 0 have their p_min/p_max zeroed before the call.
    This uses a small wrapper — run_ed() itself is not modified.

Second-stage option UC (fix s, re-optimise u):
    Call run_uc() with bat_locs from s.
    UC freely re-optimises generator commitment and dispatch.
    run_uc() is called as-is with no modifications.

Pick the candidate with the lowest true total cost as the final solution.

---

## Result Structure: QuantumSitingResult

- backend: "qiskit" | "dwave"
- second_stage: "ed" | "uc"
- n_candidates: int
- quantum_candidates: list of (u_bits, s_bits, proxy_cost) — ranked output from sieve
- evaluated: list of (bat_locs, commitment, true_cost, result_obj) — after classical stage
- best: entry in evaluated with minimum true_cost
- runtime_quantum: float (seconds)
- runtime_classical: float (seconds)

---

## Files

New:
    solvers/quantum_siting.py — all quantum sieve and classical refinement logic
    solvers/results.py — add QuantumSitingResult dataclass

Modified:
    main.py — add option 4 with three sub-prompts

Unchanged:
    solvers/ed.py, solvers/uc.py, solvers/siting.py — zero modifications

---

## Runtime Menu Flow (Option 4)

Select optimization to run: ... 4. Quantum Siting (Hybrid VQA + Classical)
Select quantum backend: 1. Qiskit (VQA, local simulator)  2. D-Wave (Simulated Annealing)
How many candidates to evaluate classically? [default: 10]:
Second-stage solver: 1. ED dispatch (fix s and u)  2. Full UC re-solve (fix s only)
How many hours to simulate? (1-24):
[select assets file as usual]

---

## Dependencies

Already present in Test_Quantum_examples/requirements.txt:
    qiskit>=1.0.0
    qiskit-aer>=0.14.0
    dimod>=0.12.0
    dwave-samplers>=1.3.0

These must also be present in (or added to) the main requirements.txt.

---

## Key References

IonQ/ORNL paper: arXiv:2505.00145 — "A New Hybrid Quantum-Classical Algorithm for Solving the
Unit Commitment Problem", Aboumrad et al., 2025.

Lazy evaluation technique: reference [12] in the paper — Kaushik et al., 2025 (aircraft loading).

Butterfly Ansatz: reference [13] in the paper — Cherrat et al., 2024.
