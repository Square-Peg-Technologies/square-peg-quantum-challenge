# Quantum Siting Feature — Roadmap & Task Tracking

Spec: constitution/quantum_solver_spec.md
Reference: arXiv:2505.00145 (IonQ/ORNL paper)

---

## Status Legend

[ ] Not started
[~] In progress
[x] Done
[!] Blocked / needs decision

---

## Phase 1 — Infrastructure

[ ] 1.1  Add QuantumSitingResult dataclass to solvers/results.py
[ ] 1.2  Add qiskit, dimod, dwave-samplers to main requirements.txt
[ ] 1.3  Create solvers/quantum_siting.py skeleton with function stubs and docstrings

---

## Phase 2 — Proxy Cost Function

[ ] 2.1  Implement build_proxy_cost_fn(generators, batteries, buses, demand_ref)
         Returns a callable(bitstring: str) -> float evaluating Q(u,s) classically.
         Sub-tasks:
         [ ] 2.1a  c_min(u) term — linear in u bits
         [ ] 2.1b  P_budget(s) term — penalise Σs_i != B
         [ ] 2.1c  P_infeas(u,s) term — peak demand coverage penalty
         [ ] 2.1d  Lambda scaling (adapt compute_lambda pattern from uc_10gen_benchmark.py)

[ ] 2.2  Implement build_bqm(generators, batteries, buses, demand_ref, lambda1, lambda2)
         Constructs dimod.BinaryQuadraticModel for the D-Wave path.
         Sub-tasks:
         [ ] 2.2a  Linear terms (c_min, P_budget linear, P_infeas linear)
         [ ] 2.2b  Quadratic u-u terms from P_infeas
         [ ] 2.2c  Quadratic s-s terms from P_budget and P_infeas
         [ ] 2.2d  Cross u-s terms from P_infeas

[ ] 2.3  Unit test: verify Q(u,s) from proxy_cost_fn and BQM energy agree on same bitstring

---

## Phase 3 — Qiskit VQA Path

[ ] 3.1  Implement build_butterfly_ansatz(n_qubits, n_layers)
         Adapt from uc_10gen_benchmark.py lines 170-187.
         Confirm RZX + RY structure, correct parameter count O(L × N).

[ ] 3.2  Implement COBYLA objective with shot-based lazy evaluation
         512 shots per iteration via StatevectorSampler.
         Empirical ⟨Q⟩ = Σ (count/512) × Q(bitstring).
         No Pauli conversion.

[ ] 3.3  Implement run_vqa_qiskit(n_qubits_gen, n_qubits_bat, proxy_fn, n_candidates, n_layers)
         Runs COBYLA (max 300 iter), then 5000-shot final sample.
         Filters to Σ s_i == B, deduplicates, returns top n_candidates by Q.

[ ] 3.4  Smoke test: run on 8-qubit PJM default assets, confirm COBYLA objective decreases.

---

## Phase 4 — D-Wave Simulated Annealing Path

[ ] 4.1  Implement run_dwave_sa(bqm, n_qubits_gen, n_qubits_bat, B, n_candidates)
         SimulatedAnnealingSampler, num_reads = max(2000, 10 × n_candidates).
         Filters to Σ s_i == B, returns top n_candidates by energy.

[ ] 4.2  Smoke test: run on PJM default assets, confirm feasible candidates returned.

---

## Phase 5 — Classical Second Stage

[ ] 5.1  Implement candidate decoder
         s bits → bat_locs dict {battery_idx: bus_idx}
         u bits → commitment list [0/1 per generator]

[ ] 5.2  Implement ED second-stage wrapper
         Zeros p_min/p_max for generators where u_g = 0 before calling run_ed().
         Does not modify run_ed() itself.

[ ] 5.3  Implement UC second-stage wrapper
         Calls run_uc() with bat_locs. No other changes.

[ ] 5.4  Implement evaluate_candidates(candidates, grid, assets, T, second_stage)
         Iterates over C*, calls appropriate second-stage, collects (bat_locs, commitment,
         true_cost, result_obj) for each. Returns full list and argmin.

---

## Phase 6 — Main Entry Point

[ ] 6.1  Implement run_quantum_siting(grid, assets, T, backend, n_candidates, second_stage)
         Orchestrates: proxy cost → quantum sieve → classical refinement → QuantumSitingResult.
         Tracks runtime_quantum and runtime_classical separately.

[ ] 6.2  Add option 4 to main.py menu
         Sub-prompts: backend, n_candidates (default 10), second_stage, hours, assets file.
         Call run_quantum_siting(), display results in same tabular style as options 1-3.

---

## Phase 7 — Verification

[ ] 7.1  D-Wave path end-to-end: n_candidates=5, second_stage=ED, T=4h, default assets.
         Confirm 5 candidates evaluated, winner printed with battery locations and cost.

[ ] 7.2  Qiskit path end-to-end: same settings.
         Confirm COBYLA converges, final sample produces valid candidates.

[ ] 7.3  UC second stage: confirm run_uc() called with correct bat_locs.

[ ] 7.4  Non-default assets: swap assets file with different G and B.
         Confirm qubit count and B adjust automatically.

[ ] 7.5  Cost comparison: compare best quantum result to classical siting (option 3) on same T.
         Expect within a few percent for the small PJM grid.

---

## Future / Out of Scope for This Phase

[ ] IBM Forte hardware integration (qiskit-ibm-runtime, real QPU submission)
[ ] Warm-start mixer initialisation (IonQ paper section III, semi-definite relaxation)
[ ] Ansatz layer count tuning / convergence study
[ ] Larger grid (IEEE 30-bus) scaling test
[ ] Battery value term P_bat(s) in proxy cost (noted as optional in original diagram)

---

## Notes

- run_ed(), run_uc(), run_siting() must not be modified.
- All asset-derived counts (G, N, B) resolved at runtime from the loaded assets object.
- Shot count (512 / 5000) matches the IonQ paper simulation experiments exactly.
- D-Wave path uses SimulatedAnnealingSampler only — no QPU connection required.
