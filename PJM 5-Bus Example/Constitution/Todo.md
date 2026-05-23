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

## Open Questions / Research Tasks

[ ] OQ-1  Verify proxy cost data flow vs IonQ paper
          Current implementation evaluates Q(u,s) as a pure constants calculation:
            c_min(u)     — closed-form lower-bound cost from generator params
            P_budget(s)  — (sum(s) - B)^2, no solve
            P_infeas     — (demand_ref - gen_cap - bat_cap)^2, no solve
          The IonQ paper (arXiv:2505.00145) may intend the quantum circuit to
          minimise an expectation value of a cost Hamiltonian (i.e. the VQA IS
          the optimizer solve, not just a sampler over a pre-defined function).
          Questions to answer:
            - Does the paper encode Q(u,s) as a Pauli Hamiltonian and minimise
              ⟨ψ|H|ψ⟩, rather than sampling bitstrings and evaluating them classically?
            - If so, our current approach (sample bitstrings → evaluate proxy_fn
              classically) is a valid approximation but not identical to the paper.
            - Check whether butterfly ansatz + COBYLA on ⟨H⟩ vs on ⟨Q⟩_classical
              matters for solution quality at 8 qubits.
            - Confirm the correct role of proxy_fn: is it used only for post-sampling
              ranking, or should it drive the VQA objective differently?
          Reference: arXiv:2505.00145 Section III and uc_10gen_benchmark.py QAOA path

          Note: The IonQ paper likely constructs a cost Hamiltonian from Q(u,s) and runs the
          VQA to minimize ⟨ψ|H|ψ⟩ directly, which is the standard QAOA/VQA pattern. Our
          current implementation does something different: it samples bitstrings from the
          circuit and evaluates them through proxy_fn classically to compute the expected
          cost objective. Both approaches steer the circuit toward low-cost bitstrings, but
          the Hamiltonian approach is what the paper calls the "quantum sieve" — the quantum
          device is actually solving the optimization, not just sampling from an independently-
          defined function. Worth reading Section III of the paper carefully and cross-
          referencing with uc_10gen_benchmark.py QAOA path to see if there's a SparsePauliOp
          construction that should be driving the objective.

---

## IEEE 14-Bus Use Case — Completed Work Log

[x] IEEE14-1  Created use_cases/ieee14/ieee14.py — exact MATPOWER case14 data,
              14 buses, 20 branches, 5 generators, 24h demand shaped by factors.
              fbar set to create meaningful congestion for datacenter siting.

[x] IEEE14-2  Created use_cases/ieee14/assets.py — 5 generators, 4 batteries,
              DATACENTER_BUS=None base template.

[x] IEEE14-3  Created use_cases/ieee14/locations.py — fixed generator locations
              from case14 (buses 1,2,3,6,8), placeholder battery locations.

[x] IEEE14-4  Created use_cases/ieee14/site_datacenter.py — sweeps all 14 buses,
              ranks by ED cost, writes assets_dc_bus{N}.py for feasible buses.
              Result: buses 1,2,4,5 feasible; bus 1 cheapest ($228,429/24h).

[x] IEEE14-5  Modified main.py — injected DC load from assets DATACENTER_BUS/MW
              after grid construction; 3-line change in load_use_case().

[x] IEEE14-6  Added Aer GPU acceleration to solvers/quantum_siting.py — auto-detect
              GPU at import, use AerSamplerV2 with GPU statevector, fall back to CPU.
              Downgraded Qiskit to 1.4.5 and installed qiskit-aer-gpu 0.15.1 for
              GPU compatibility (qiskit-aer-gpu max is 0.15.x, requires Qiskit 1.x).

[x] IEEE14-7  Fixed proxy cost function — removed batteries from shortfall calculation.
              Batteries shift energy (finite capacity) and cannot create new peak capacity;
              generator commitment alone must cover peak demand. Fix resolved VQA producing
              single-generator solutions (u=10000) that all failed ED refinement.

[x] IEEE14-8  Verified full Qiskit+Aer GPU quantum siting run on ieee14 — 2m17s,
              20/20 candidates feasible, best placement buses (2,11,12,13) at $209,229.

---

## Future Tasks

[ ] FT-2  VQA/COBYLA speedup — COBYLA runs serially on CPU; GPU is underutilized.
          Options (in order of implementation effort):
            a) Batch circuits in each COBYLA iteration: submit multiple parameter
               sets to AerSamplerV2.run() in one GPU call instead of one at a time.
               Low effort; could halve wall time for the optimizer phase.
            b) Swap COBYLA for SPSA or Adam with parameter-shift gradients: evaluates
               ~2N circuits per step (N = n_params) in a single batched GPU call.
               Medium effort; estimated 10-50x speedup on optimizer step.
            c) Parallel independent VQA trials: run multiple COBYLA instances
               with different random seeds using multiprocessing.Pool, take best.
               Low effort; scales with CPU core count; orthogonal to a/b.
          Recommended starting point: (a) then (c).

[ ] FT-1  UC solver scalability for larger grids — currently uses brute-force MIP
          solving via CVXPY for each candidate. For larger grids (>50 buses), consider
          replacing with a proper MIP formulation (branch-and-bound via SCIP/HiGHS)
          or a Lagrangian relaxation approach to avoid O(2^G) search space. Assess
          whether CVXPY/HiGHS can scale or if a dedicated MILP solver wrapper is needed.

[ ] FT-3  Tests for ieee14 use case — test suite currently only covers pjm5.
          Needed:
            - ED/UC feasibility checks on ieee14 grid (base load + DC injection)
            - Datacenter load injection via DATACENTER_BUS/DATACENTER_MW in load_use_case()
            - site_datacenter.py: confirm feasible buses match expected set {1,2,4,5}
              and assets_dc_bus{N}.py files are written with correct content
            - Quantum siting on ieee14: at least one candidate survives classical
              refinement with the fixed proxy cost function (battery-excluded shortfall)

[ ] FT-4  Fix D-Wave SA path for ieee14 — SimulatedAnnealingSampler returns
          candidates committing only 1-2 generators (total capacity < 563 MW peak),
          so all candidates fail ED/UC refinement.
          Root cause: BQM lambda2 scaling is too weak relative to the c_min savings
          from leaving generators off — same imbalance fixed in the VQA proxy function.
          Fix options:
            a) Apply same battery-exclusion fix to BQM P_infeas term (exclude
               P_bat contribution from shortfall calculation in build_bqm).
            b) Increase lambda2 multiplier specifically for large grids where
               demand_ref is high relative to individual generator capacities.
          After fix, verify D-Wave SA produces feasible candidates on ieee14.

[ ] FT-5  Qiskit 2.x / qiskit-aer-gpu upgrade path — requirements.txt is pinned
          to qiskit<2.0 because qiskit-aer-gpu tops out at 0.15.x (Qiskit 1.x only).
          Track the qiskit-aer-gpu release page for a Qiskit 2.x-compatible GPU build.
          When available: bump qiskit and qiskit-aer-gpu pins, remove the <2.0 cap,
          re-run tests, and update requirements.txt and README GPU setup notes.
          Monitor: https://github.com/Qiskit/qiskit-aer/releases

[ ] FT-6  Network plot for quantum siting results — options 1-3 generate a PNG
          showing the grid with generator outputs, battery SOC, and congested lines;
          option 4 (quantum siting) currently prints results to terminal only.
          Add a topology diagram for the best quantum siting result: highlight
          winning battery buses, show committed generators, and mark congested lines.
          Should reuse the existing plots.py infrastructure where possible.

[ ] FT-7  IonQ hardware submission path — the butterfly ansatz and 512-shot
          sampling are designed for IonQ Forte gate hardware, but the tool currently
          only runs on a local statevector simulator.
          Task: wire up the Qiskit IonQ provider (qiskit-ionq or direct REST API)
          so run_vqa_qiskit() can target real hardware. Add a backend option (e.g.
          "ionq") alongside "qiskit" and "dwave" in the CLI. Gate count and
          connectivity constraints for Forte should be verified against the ansatz.

[ ] FT-8  Proxy cost lambda calibration — lambda1 and lambda2 are heuristic
          multipliers (2× and 20× c_min_total respectively). For ieee14 they work
          after the battery-exclusion fix, but scaling to larger grids (30+ buses,
          10+ generators) may require recalibration.
          Task: run a sweep over lambda multipliers on both pjm5 and ieee14, measure
          how solution quality (gap vs classical optimum) varies, and document
          recommended multiplier ranges per grid size. Consider making the multipliers
          configurable parameters in run_quantum_siting().

[ ] FT-9  Larger test case — IEEE 30-bus or IEEE 57-bus use case.
          IEEE 30-bus: 6 generators + 30 buses = 36 qubits. 2^36 amplitudes exceed
          CPU statevector memory (~512 GB); GPU (16 GB VRAM) can handle up to ~31
          qubits in single precision. Would require either fewer generator qubits,
          a reduced-variable encoding, or splitting the circuit.
          IEEE 57-bus: 7 generators + 57 buses = 64 qubits — beyond single-GPU
          statevector; would need tensor-network or matrix-product-state simulation.
          Recommended starting point: IEEE 30-bus with a subset of generator qubits
          (e.g. encode only the marginal generators, fix cheap baseload units ON).

---

## Constraints

- solvers/ed.py, solvers/uc.py, solvers/siting.py must not be modified
- All G, N, B counts resolved from loaded assets/grid at runtime — nothing hardcoded
- Shot counts: 512/iter during COBYLA, 5000 for final extraction (matches IonQ paper)
- D-Wave path: SimulatedAnnealingSampler only, no QPU connection
