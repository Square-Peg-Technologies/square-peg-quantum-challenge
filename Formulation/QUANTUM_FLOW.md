# Quantum Siting — Call Flow and Architecture

> Note: this diagram predates the congestion-signal (P_loc), Aer Tensor
> Network, and IonQ-via-qBraid additions, and its line numbers are stale.
> Only the backend/D-Wave references have been corrected here (D-Wave was
> removed entirely; the old single `backend` string is now the independent
> `sim_method` + `final_backend` pair). A full rewrite reflecting the
> current call flow is a separate, larger task.

## High-Level Data Flow

```
grid + assets (generators, batteries)
        |
        v
build_proxy_cost_fn()          -- cheap score function, no solver
        |
        v
quantum sieve                  -- samples 8-qubit space
  Qiskit VQA  or  Aer Tensor Network (VQA)
        |
        v
top N (u_bits, s_bits)         -- ranked bitstring candidates
        |
        v
evaluate_candidates()          -- runs real solver on each
  ED  or  UC
        |
        v
best = min(true_cost)
        |
        v
QuantumSitingResult            -- printed to terminal
```


## Full Call Chain

```
main()                                                [main.py]
  |
  |-- prompt_quantum_options()
  |     returns: sim_method, final_backend, n_candidates, second_stage
  |
  |-- run_quantum_siting(grid, generators, batteries,  [quantum_siting.py]
  |       T, sim_method, final_backend, n_candidates, second_stage)
  |
  |   STEP 1 — Proxy cost
  |   |-- build_proxy_cost_fn(generators, batteries,   [quantum_siting.py]
  |   |       n_buses, demand_ref)
  |   |     returns: (proxy_fn, lambda1, lambda2)
  |   |
  |   |   proxy_fn(bitstring) -> float
  |   |     Q(u,s) = c_min(u) + λ1*P_budget(s) + λ2*P_infeas(u,s)
  |   |
  |   STEP 2 — Quantum sieve (sim_method picks statevector vs tensor_network;
  |   |         final_backend picks local vs ionq_qbraid for the final shots)
  |   |-- run_vqa_qiskit(n_qubits_gen, n_qubits_bat,   [quantum_siting.py]
  |   |       proxy_fn, n_candidates, sim_method, final_backend)
  |   |     |
  |   |     |-- build_butterfly_ansatz / build_linear_chain_ansatz
  |   |     |     returns: (QuantumCircuit, params)
  |   |     |
  |   |     |-- AerSamplerV2 / BackendSamplerV2.run()  [Qiskit / Aer TN]
  |   |     |     512 shots per COBYLA iteration
  |   |     |
  |   |     |-- scipy COBYLA optimizer
  |   |     |     objective: mean Q(u,s) over sampled bitstrings
  |   |     |     up to 300 iterations
  |   |     |
  |   |     |-- local sampler (5000 shots) or IonQ via qBraid
  |   |     |     final_backend="ionq_qbraid" routes this one real job
  |   |     |
  |   |     returns: [(u_bits, s_bits, proxy_cost), ...]
  |   |
  |   STEP 3 — Classical refinement
  |   |-- evaluate_candidates(candidates, grid,        [quantum_siting.py:303]
  |   |       generators, batteries, T, second_stage)
  |   |     |
  |   |     |   for each (u_bits, s_bits, proxy_cost):
  |   |     |     decode s_bits -> bat_locs
  |   |     |       e.g. "01001" -> {0: 2, 1: 5}
  |   |     |     decode u_bits -> commitment
  |   |     |       e.g. "011"   -> [0, 1, 1]
  |   |     |
  |   |     |   [ED path]
  |   |     |-- run_ed(grid, gens_modified, batteries, [solvers/ed.py]
  |   |     |       gen_locs, bat_locs, T)
  |   |     |     zero p_min/p_max for OFF generators
  |   |     |     returns: EDResult
  |   |     |
  |   |     |   [UC path]
  |   |     |-- run_uc(grid, generators, batteries,    [solvers/uc.py]
  |   |     |       bat_locs, T)
  |   |     |     skip if bat_locs already evaluated
  |   |     |     commitment re-optimized freely per hour
  |   |     |     returns: UCResult
  |   |     |
  |   |     returns: [(bat_locs, commitment, true_cost, result_obj), ...]
  |   |
  |   |-- best = min(evaluated, key=true_cost)
  |   returns: QuantumSitingResult
  |
  |-- print_results()                                  [main.py:194]
        |-- print_quantum_results()                    [main.py:141]
              ranked table of evaluated candidates
              ED:  shows fixed commitment from sieve u_bits
              UC:  shows per-hour schedule from result_obj.commitment
```


## Bitstring Encoding

```
Position:  0   1   2   3   4   5   6   7
           |_______|   |_______________|
           u_0 u_1 u_2   s_0 s_1 s_2 s_3 s_4
           generator     bus presence
           commitment     (which buses get a battery)

Example:   0   1   1   0   1   0   0   1
           OFF ON  ON  .   B1  .   .   B2
           -> generators 1 and 2 committed
           -> batteries placed at buses 2 and 5
```


## Proxy Cost Function — Q(u, s)

```
Q(u, s) = c_min(u)  +  λ1 * P_budget(s)  +  λ2 * P_infeas(u, s)

c_min(u)       Lower-bound cost for committed generators.
               sum over g: u_g * (a_g * p_min_g^2 + b_g * p_min_g + c_g)
               Cheap estimate — assumes each ON generator runs at p_min.

P_budget(s)    Battery count penalty.
               (sum_i s_i  -  B)^2
               Zero only when exactly B buses selected.

P_infeas(u,s)  Capacity penalty.
               (demand_ref - sum_g u_g*p_max_g - sum_i s_i*P_bat)^2
               Penalises combinations that cannot serve peak demand.

λ1 = c_min_typical * 2.0
λ2 = c_min_typical / (demand_ref^2 + 1e-6)
     (scales penalties to same order as c_min)
```


## Result Dataclasses (results.py)

```
QuantumSitingResult
  sim_method         "statevector" | "tensor_network"
  final_backend      "local" | "ionq_qbraid"
  second_stage       "ed" | "uc"
  n_candidates       number requested
  quantum_candidates [(u_bits, s_bits, proxy_cost), ...]   -- from sieve
  evaluated          [(bat_locs, commitment, true_cost,     -- from classical stage
                        result_obj), ...]
  best               entry in evaluated with min true_cost
  runtime_quantum    seconds for sieve
  runtime_classical  seconds for classical stage

result_obj is EDResult (ED path) or UCResult (UC path)

UCResult.commitment  shape (n_generators, T)  -- per-hour binary schedule
EDResult.dispatch    shape (n_generators, T)  -- MW output per hour
```


## Why Evaluated Count Can Be Less Than Requested

```
Requested: 10 candidates
Evaluated: 7

Two reasons candidates are skipped:

1. UC deduplication
   Multiple sieve bitstrings may decode to the same bat_locs.
   Since UC re-optimizes commitment freely, the result is identical
   for any two candidates with matching battery bus assignments.
   Only the first is evaluated; the rest are dropped.

2. Solver infeasibility
   A placement may be infeasible at peak hours (line limits cannot
   be satisfied regardless of commitment). These are caught by the
   try/except in evaluate_candidates and skipped silently.

Check result.quantum_candidates vs result.evaluated to see the breakdown.
```
