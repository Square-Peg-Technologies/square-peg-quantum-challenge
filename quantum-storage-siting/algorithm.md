# Quantum Siting Algorithm

## 1. The problem

Given a power grid with G generators and N candidate buses, decide:

- which generators to commit (turn on), and
- on which B buses to place batteries,

so that total system operating cost over a T-hour horizon is minimized, subject to
generation limits, DC power flow line limits, and battery state-of-charge dynamics. Quantum Siting replaces the exhaustive search with a quantum sieve that produces a short ranked list of promising candidates using a cheap analytical proxy cost, then evaluates only those candidates with a full classical solve.

Decision variables are encoded as one bitstring:

    [ u_0 ... u_{G-1}   s_0 ... s_{N-1} ]
    
    u_g = 1  generator g is committed (on)
    s_i = 1  a battery is placed at bus i

Total qubits = G + N. 

parker@squarepegtech.com

## 2. Pipeline overview

    run_quantum_siting(grid, generators, batteries, T, backend, n_candidates,
                       second_stage, warm_start, ...)
    
    ┌──────────────────────────────────────────────────────────────┐
    │  A. CLASSICAL SETUP                                            │
    │     A1. No-battery DC-OPF → line shadow prices                 │
    │     A2. PTDF-weighted per-bus congestion signal               │
    │     A3. Build proxy cost function Q(u, s)                      │
    ├──────────────────────────────────────────────────────────────┤
    │  B. QUANTUM SIEVE  (one of three backends)                     │
    │     B-qiskit / B-aer_tn : VQA (butterfly / linear-chain HEA)   │ │
    │     → ranked shortlist of candidate bitstrings                 │
    ├──────────────────────────────────────────────────────────────┤
    │  C. CLASSICAL REFINEMENT                                       │
    │     C1. Decode + deduplicate candidates                       │
    │     C2. Full ED or UC solve per candidate (parallel)          │
    │     C3. Pick lowest true-cost placement                       │
    └──────────────────────────────────────────────────────────────┘
    
    → QuantumSitingResult (best placement, all evaluated candidates,
      runtime breakdown, convergence trace)

Steps A and C are classical. Step B is the quantum part (VQA on a simulator, or
simulated annealing of a QUBO). The proxy cost Q(u, s) built in A3 is the bridge:
it is evaluated analytically inside the quantum stage with no solver call, which is
what makes the sieve cheap.

## 3. Classical part — setup (Step A)

This runs before any quantum work. Function: run_quantum_siting, lines that call
_compute_shadow_prices, compute_congestion_signal, and build_proxy_cost_fn.

### A1. No-battery DC-OPF → shadow prices

    _compute_shadow_prices(grid, generators, T)

Solve a battery-free DC optimal power flow over the full horizon as a convex QP in
CVXPY (Clarabel first; HiGHS with a 30 s time limit as fallback). Per hour t:

    minimize   Σ_g ( a_g p_{g,t}² + b_g p_{g,t} + c_g )
    subject to Σ_g p_{g,t} = Σ_i demand_{i,t}          (power balance)
               −fbar ≤ PTDF (inj_t − demand_t) ≤ fbar   (line limits)
               p_min,g ≤ p_{g,t} ≤ p_max,g

The dual values of the line-limit constraints give the line shadow prices:

    shadow_price[l, t] = μ_up[l, t] − μ_dn[l, t]

positive when the line's upper flow limit binds. If the solve fails for any reason,
the shadow-price array is zeroed and the rest of the pipeline degrades gracefully
(the congestion term simply drops out).

### A2. PTDF-weighted congestion signal

    compute_congestion_signal(ptdf, shadow_prices, p_bat)

Collapse the shadow prices to a per-bus dollar signal. Let μ_mean,l be the
time-averaged shadow price on line l:

    signal_i = P_bat × Σ_l ( −PTDF[l, i] × μ_mean,l )
             = −P_bat × (PTDFᵀ μ_mean)_i        (units: $/h)

Positive signal_i means a battery injecting at bus i tends to reduce flow on binding
lines (relieves congestion); negative means it worsens congestion. P_bat is the
battery power rating, which puts the signal in dollar-per-hour units.

### A3. Proxy cost function Q(u, s)

    build_proxy_cost_fn(generators, batteries, n_buses, demand_ref, T,
                        congestion_signal)

Returns proxy_fn(bitstring) -> float, evaluated analytically (no solver) for every
sampled bitstring in the quantum stage:

    Q(u, s) = c_min(u) + λ1 · P_budget(s) + λ2 · P_infeas(u) − P_loc(s)
    
    c_min(u)    = T · Σ_g u_g (a_g p_min,g² + b_g p_min,g + c_g)
                  lower-bound committed-generation cost
    P_budget(s) = (Σ_i s_i − B)²
                  penalises placing a number of batteries ≠ B
    P_infeas(u) = max(0, D_peak − Σ_g u_g P_max,g)²
                  one-sided generator shortfall penalty
    P_loc(s)    = T · Σ_i s_i · signal_i
                  congestion-relief reward (subtracted → lowers cost)
    
    demand_ref = D_peak = peak total demand over the horizon

Key modelling choices:

- Batteries are excluded from P_infeas. Batteries shift energy across hours but do
  not create new peak capacity, so committed generation alone must cover peak demand.
- P_infeas is one-sided: only shortfall (too little capacity) is penalised, never
  over-capacity.
- P_loc is already in dollar units matching c_min, so it needs no extra weight.
- If congestion_signal is None (or the OPF failed), P_loc drops out and the proxy
  reverts to the three-term form.

Penalty weights (Qiskit / Aer VQA path, scaled to the full horizon):

    λ1 = 2  · c_min,total          (deviating one battery from B costs more than
                                     the largest achievable congestion saving)
    λ2 = 20 · c_min,total / D_peak² (any capacity shortfall dominates c_min savings)
    
    where c_min,total = T · Σ_g (a_g p_min,g² + b_g p_min,g + c_g)

The D-Wave path uses per-hour λ values (λ1, λ2 also returned by the same builder)
because the QUBO encodes the penalties directly rather than through a horizon-scaled
proxy call.

## 4. Quantum part — the sieve (Step B)

The sieve searches the joint (commitment, placement) bitstring space and returns a
ranked shortlist. Three backends select via the backend argument: "qiskit",
"aer_tn", or "dwave", all minimising the same Q(u, s) landscape. The two VQA
backends ("qiskit", "aer_tn") are the working paths; the D-Wave path (Section B-dwave)
is wired into the CLI and dashboard but is incomplete and not functional at present.

### B-qiskit / B-aer_tn — Variational Quantum Algorithm

    run_vqa_qiskit(n_qubits_gen=G, n_qubits_bat=N, proxy_fn, n_candidates,
                   warm_start, sim_method, device, ansatz, ...)

A VQA prepares a parameterised state on G+N qubits, measures it, and uses the
measured bitstrings' proxy costs as the objective for a classical optimizer, which
tunes the circuit parameters. Sub-steps:

1. Build the ansatz (parameterised circuit). Two options, chosen automatically by
   sim_method:
   
   - Butterfly ansatz (build_butterfly_ansatz) — arXiv:2505.00145. Per layer:
     RZX entanglers in a doubling-stride butterfly pattern, then an RY on every
     qubit. Default L=3 for statevector simulation. Used for the "qiskit" backend.
   - Linear-chain HEA (build_linear_chain_ansatz) — per layer: RY on every qubit,
     then nearest-neighbor RZX in an alternating even/odd brick-wall pattern. Only
     adjacent two-qubit gates, so the MPS bond dimension stays tractable. Default
     L=4. Used for the "aer_tn" backend (36+ qubits).
     Parameter count = 2 × L × (G + N) for butterfly (γ for RZX, β for RY).

2. Choose the warm start (initial parameters θ0):
   
   - "zeros"  — θ = 0. Paper simulation default (Section IV-A).
   
   - "random" — θ ~ Uniform[−2π, 2π]. Paper IonQ hardware default.
   
   - "sdp"    — LP-relaxation warm start (_solve_lp_relaxation solves the continuous
     
                [0,1]ⁿ relaxation of the proxy QUBO via SLSQP), then maps the optimum
                x* to RY angles β_j = 2·arcsin(√x_j*) so the circuit starts near the
                relaxed optimum (paper Section III).

3. Select the simulator backend:
   
   - statevector via qiskit-aer SamplerV2 — device "auto"/"GPU"/"CPU" (GPU used when
     qiskit-aer-gpu and a GPU are present).
   - tensor_network (MPS) via AerSimulator(method="matrix_product_state") — CPU-only;
     memory scales with entanglement, not 2ⁿ, enabling 36-qubit runs.
     Falls back to the pure-Qiskit StatevectorSampler if qiskit-aer is unavailable.

4. Optimize with COBYLA (scipy fmin_cobyla). Each objective evaluation:
   a. Bind θ into the circuit and sample (512 shots/iteration).
   b. Reverse each bitstring (Qiskit is little-endian) to the [u | s] layout.
   c. Objective = shot-probability-weighted average of proxy_fn over the counts.
   Budget: maxfun = max(150, 6 × n_params). Because the objective is stochastic,
   COBYLA's rhoend rarely triggers, so a plateau detector stops early when the best
   value has not improved by >1% within `patience` = max(50, n_params) evaluations;
   a wall-time cutoff (max_time_s) also stops it. The best θ seen is retained.

5. Final extraction. Sample the optimized circuit with 5,000 shots, collect every
   unique bitstring, and rank ascending by proxy cost. Drop all-OFF commitments
   (u = 0). Return the top n_candidates as (u_bits, s_bits, proxy_cost).

Back in the orchestrator, VQA results are post-filtered to keep only bitstrings with
exactly B batteries placed (P_budget = 0); if none are exactly feasible, it falls
back to all candidates sorted by proxy cost.

### B-dwave — QUBO + simulated annealing (incomplete / not functional)

Status: this path is not operational at present. The description below is the
intended design; it is selectable from the CLI and dashboard and the code is present,
but it is incomplete and should not be relied on until it is finished and validated.
Use the "qiskit" or "aer_tn" VQA backends for working runs.

    build_bqm(...)  then  run_dwave_sa(bqm, ..., B, n_candidates, num_reads)

1. Build a dimod BinaryQuadraticModel that encodes exactly the same Q(u, s), with
   each penalty term expanded into linear and quadratic biases:
   - c_min(u): linear bias per u_g.
   - P_budget(s) = (Σ s_i − B)²: linear (1 − 2B)·λ1 per s_i, quadratic 2·λ1 per
     s-pair, offset λ1·B².
   - P_infeas(u, s) = (D − Σ P_g u_g − Σ P_bat s_i)²: fully expanded into linear u_g,
     linear s_i, u–u, s–s, and cross u–s quadratic biases, offset λ2·D². (Note: the
     BQM includes batteries in the capacity balance, whereas the VQA proxy excludes
     them from the shortfall term.)
   - P_loc: −signal_i added to the linear bias of each s_i (congestion reward).
2. Sample with dwave.samplers.SimulatedAnnealingSampler, num_reads =
   max(2000, 10 × n_candidates) by default (overridable via _num_reads for tests).
3. Filter samples to exactly B batteries placed and non-all-OFF commitment,
   deduplicate, and return the top n_candidates by energy.

This path needs no QPU connection — it runs entirely on CPU.

## 5. Classical part — refinement (Step C)

The sieve's proxy cost is only a ranking heuristic; the shortlist is now scored with
true system-cost solves. Function: evaluate_candidates → _eval_one (parallel).

### C1. Decode and deduplicate

For each candidate bitstring:

    placed_buses = [ i+1 for i, b in enumerate(s_bits) if b == "1" ]
    bat_locs     = { battery_index : bus }
    commitment   = [ int(b) for b in u_bits ]

In UC mode, candidates that share the same battery placement are deduplicated (one
UC solve per unique placement), since UC re-optimises commitment anyway.

### C2. Full ED or UC solve per candidate (parallel)

Each surviving candidate is solved on all available CPU cores via a
ProcessPoolExecutor using the "spawn" start method (fork is unsafe while the parent
holds a CUDA context from GPU statevector sampling). second_stage selects:

- "ed" — Economic Dispatch (solvers.ed.run_ed). Commitment is fixed from the sieve
  bitstring: OFF generators have p_min and p_max zeroed, then ED finds least-cost
  dispatch. Fast, respects the quantum commitment decision.
- "uc" — Unit Commitment (solvers.uc.run_uc). Battery placement is fixed but
  commitment is ignored — UC re-optimises on/off freely per hour. More expensive,
  higher quality.

Each solve returns a true total cost; failures return None and are skipped.

### C3. Select the best

Pick the candidate with the lowest true cost:

    best = min(evaluated, key=total_cost)

If no candidate survived refinement, raise RuntimeError("No feasible candidates
found after classical refinement.").

## 6. Output

Returns a QuantumSitingResult with:

- best — (bat_locs, commitment, true_cost, result_obj) for the winning placement,
- quantum_candidates — the sieve shortlist,
- evaluated — every candidate's true cost,
- runtime_quantum / runtime_classical and a runtime_phases breakdown (setup OPF,
  sampling, COBYLA overhead, final extraction, classical refinement),
- convergence_trace — COBYLA objective per evaluation (if track_convergence),
- warm_start and backend metadata.

Every run also writes outputs/quantum_siting_debug.log with per-candidate pass/fail
outcomes and error messages for post-run diagnosis.

## 7. Why this is a sieve, not a solver

The quantum stage never computes a true system cost — it only ranks bitstrings by
the analytical proxy Q(u, s), which is cheap to evaluate (~154,000 proxy evaluations
for a full ieee14 Qiskit run, all analytical). The expensive UC/ED solves are run
only on the top n_candidates. This is the core hybrid trade-off from arXiv:2505.00145:
use the quantum optimizer to cheaply narrow C(N, B) placements down to a handful, and
spend classical solver time only on that handful.
