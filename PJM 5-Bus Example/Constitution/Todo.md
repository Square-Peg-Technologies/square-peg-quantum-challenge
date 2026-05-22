# Quantum Siting — Todo & Parallel Task Breakdown

Status markers: [ ] not started  [~] in progress  [x] done  [!] blocked

---

## Wave 1 — Can all start immediately, fully independent

[x] W1-A  Add QuantumSitingResult dataclass to solvers/results.py
          Fields: backend, second_stage, n_candidates, quantum_candidates,
                  evaluated, best, runtime_quantum, runtime_classical

[x] W1-B  Add qiskit, dimod, dwave-samplers to main requirements.txt
          Copy versions from Test_Quantum_examples/requirements.txt

[x] W1-C  Create solvers/quantum_siting.py with empty stubs for all functions
          (build_proxy_cost_fn, build_bqm, build_butterfly_ansatz,
           run_vqa_qiskit, run_dwave_sa, evaluate_candidates, run_quantum_siting)
          Just stubs with signatures and docstrings — no logic yet

---

## Wave 2 — Start after W1-C exists; A and B are independent of each other

[x] W2-A  Implement build_proxy_cost_fn(generators, batteries, buses, demand_ref)
          Returns callable(bitstring) -> float for lazy Q(u,s) evaluation.
          Subtasks (sequential within this task):
            [x] c_min(u) term
            [x] P_budget(s) term
            [x] P_infeas(u,s) term
            [x] lambda scaling

[x] W2-B  Implement build_bqm(generators, batteries, buses, demand_ref, lambda1, lambda2)
          Constructs dimod.BinaryQuadraticModel.
          Subtasks (sequential within this task):
            [x] linear terms (c_min, P_budget, P_infeas linear)
            [x] quadratic u-u terms
            [x] quadratic s-s terms
            [x] cross u-s terms

---

## Wave 3 — Start after W2-A and W2-B; A, B, C are independent of each other

[x] W3-A  Implement Qiskit VQA path
          Depends on: W2-A (proxy_cost_fn)
          Subtasks (sequential):
            [x] build_butterfly_ansatz(n_qubits, n_layers) — adapt from uc_10gen_benchmark.py:170
            [x] COBYLA objective with 512-shot StatevectorSampler, lazy ⟨Q⟩ evaluation
            [x] run_vqa_qiskit() — 300-iter COBYLA, then 5000-shot final sample,
                filter Σs_i==B, deduplicate, return top n_candidates

[x] W3-B  Implement D-Wave SA path
          Depends on: W2-B (bqm)
          Subtasks (sequential):
            [x] run_dwave_sa() — SimulatedAnnealingSampler, num_reads=max(2000, 10×n_candidates)
            [x] filter Σs_i==B, sort by energy, return top n_candidates

[x] W3-C  Implement classical second-stage evaluation
          Depends on: W1-A (QuantumSitingResult)
          Subtasks (sequential):
            [x] candidate decoder: s bits → bat_locs, u bits → commitment list
            [x] ED wrapper: zero p_min/p_max for off generators, call run_ed()
            [x] UC wrapper: call run_uc() with bat_locs as-is
            [x] evaluate_candidates() — iterate C*, dispatch to ED or UC, collect results

---

## Wave 4 — Start after W3-A, W3-B, W3-C all done

[x] W4-A  Implement run_quantum_siting(grid, assets, T, backend, n_candidates, second_stage)
          Orchestrates full pipeline: proxy cost → sieve → classical refinement → result
          Tracks runtime_quantum and runtime_classical separately

[x] W4-B  Add option 4 to main.py
          Depends on: W4-A
          Sub-prompts: backend (1/2), n_candidates (default 10), second_stage (1/2),
          hours, assets file (same as existing pattern)
          Display results in same tabular style as options 1-3

---

## Wave 5 — Verification (after W4-B)

[x] V1  D-Wave path end-to-end: n_candidates=5, second_stage=ED, T=4h, default assets
        PASS: 5 candidates evaluated, best printed (buses=(1,2), cost=$14,430)

[x] V2  Qiskit path end-to-end: same settings
        PASS: 5.5s total, 5 feasible candidates, best buses=(1,3) cost=$11,176

[x] V3  UC second stage: confirm run_uc() receives correct bat_locs
        PASS: UCResult returned for all 5 candidates, commitment shape=(3,4)

[x] V4  Non-default assets: swap to different asset file with different G and B
        PASS: qubit count and B auto-adjust correctly (only assets.py present)

[x] V5  Cost sanity: compare best quantum result to option 3 (classical siting), same T
        PASS: 0.0% gap — quantum D-Wave+UC matches classical optimum exactly ($8,507)

---

## Dependency Graph

W1-A ─────────────────────────┐
W1-B (independent)             │
W1-C ──► W2-A ──► W3-A ──┐   ├──► W3-C ──► W4-A ──► W4-B ──► V1..V5
         W2-B ──► W3-B ──┘   │
                               └─────────────────────────────────────┘

Parallelism summary:
  Wave 1: 3 tasks in parallel
  Wave 2: 2 tasks in parallel (after W1-C)
  Wave 3: 3 tasks in parallel (after W2 complete)
  Wave 4: sequential (W4-A then W4-B)
  Wave 5: 5 checks in parallel (after W4-B)

---

## Constraints

- solvers/ed.py, solvers/uc.py, solvers/siting.py must not be modified
- All G, N, B counts resolved from loaded assets/grid at runtime — nothing hardcoded
- Shot counts: 512/iter during COBYLA, 5000 for final extraction (matches IonQ paper)
- D-Wave path: SimulatedAnnealingSampler only, no QPU connection
