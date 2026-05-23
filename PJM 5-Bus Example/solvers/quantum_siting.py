"""
Quantum Siting Solver — hybrid quantum-classical siting optimization.

Implements a quantum sieve stage (Qiskit VQA or D-Wave SA) over the joint
(generator commitment, battery placement) space, followed by classical
refinement via ED or UC.

Reference: arXiv:2505.00145 (IonQ/ORNL, Aboumrad et al., 2025)
"""

from __future__ import annotations

import time
from typing import Callable

import numpy as np


# ---------------------------------------------------------------------------
# Proxy cost function (lazy classical evaluation from bitstring)
# ---------------------------------------------------------------------------

def build_proxy_cost_fn(
    generators: list[dict],
    batteries: list[dict],
    n_buses: int,
    demand_ref: float,
    T: int = 1,
) -> tuple[Callable[[str], float], float, float]:
    """Return (proxy_fn, lambda1, lambda2) for lazy Q(u,s) evaluation.

    proxy_fn(bitstring: str) -> float
        Bitstring layout: u_0..u_{G-1} s_0..s_{N-1} (index 0 = leftmost char).
        Returns Q(u, s) = c_min(u) + lambda1*P_budget(s) + lambda2*P_infeas(u,s).

    lambda1, lambda2 are the BQM lambdas (D-Wave path, per-hour scaling).
    proxy_fn uses T-scaled lambdas with a one-sided infeasibility penalty so that
    over-capacity combinations are not penalised (only shortfall is penalised).
    """
    G = len(generators)
    B = len(batteries)
    P_bat = batteries[0]["power_mw"]

    c_min_coeffs = [
        g["cost_a"] * g["p_min"] ** 2 + g["cost_b"] * g["p_min"] + g["cost_c"]
        for g in generators
    ]
    p_max_vals = [g["p_max"] for g in generators]

    # BQM lambdas (returned for D-Wave path, per-hour scaling, symmetric P_infeas)
    c_min_typical = sum(c_min_coeffs)
    lambda1 = c_min_typical * 2.0
    lambda2 = c_min_typical / (demand_ref ** 2 + 1e-6)

    # Proxy-function lambdas (Qiskit path): scale by T so proxy estimates total-
    # horizon cost; multiply lambda2 by 20 so shortfall is penalised strongly
    # enough to rank infeasible generator combos above feasible ones.
    c_min_total = c_min_typical * T
    _lam1 = c_min_total * 2.0
    _lam2 = c_min_total * 20.0 / (demand_ref ** 2 + 1e-6)

    def proxy_fn(bitstring: str) -> float:
        u = [int(bitstring[g]) for g in range(G)]
        s = [int(bitstring[G + i]) for i in range(n_buses)]

        c_min_val = sum(u[g] * c_min_coeffs[g] for g in range(G)) * T

        p_budget = (sum(s) - B) ** 2

        # One-sided: penalise shortfall only (surplus capacity is fine)
        shortfall = max(
            0.0,
            demand_ref
            - sum(u[g] * p_max_vals[g] for g in range(G))
            - sum(s[i] * P_bat for i in range(n_buses)),
        )
        p_infeas = shortfall ** 2

        return c_min_val + _lam1 * p_budget + _lam2 * p_infeas

    return proxy_fn, lambda1, lambda2


# ---------------------------------------------------------------------------
# BQM builder for D-Wave path
# ---------------------------------------------------------------------------

def build_bqm(
    generators: list[dict],
    batteries: list[dict],
    n_buses: int,
    demand_ref: float,
    lambda1: float,
    lambda2: float,
):
    """Build a dimod.BinaryQuadraticModel encoding Q(u, s).

    Variable naming: u_g for generator g, s_i for bus i.
    Returns the BQM (vartype=BINARY).
    """
    import dimod

    G = len(generators)
    B = len(batteries)
    P_bat = batteries[0]["power_mw"]
    D = demand_ref

    bqm = dimod.BinaryQuadraticModel(vartype="BINARY")

    # 1. c_min(u): linear term per generator
    for g, gen in enumerate(generators):
        h = gen["cost_a"] * gen["p_min"] ** 2 + gen["cost_b"] * gen["p_min"] + gen["cost_c"]
        bqm.add_variable(f"u_{g}", h)

    # 2. P_budget(s) = (sum_i s_i - B)^2
    #    Expansion: sum_i s_i - 2B*sum_i s_i + 2*sum_{i<j} s_i*s_j + B^2
    #    Linear: (1 - 2B) per s_i; Quadratic: 2 per pair; Offset: B^2
    for i in range(n_buses):
        bqm.add_variable(f"s_{i}", lambda1 * (1 - 2 * B))
    for i in range(n_buses):
        for j in range(i + 1, n_buses):
            bqm.add_interaction(f"s_{i}", f"s_{j}", lambda1 * 2.0)
    bqm.offset += lambda1 * B ** 2

    # 3. P_infeas(u, s) = (D - sum_g P_g*u_g - sum_i P_bat*s_i)^2
    #    Expand fully (using binary^2 = binary):
    #    Linear u_g: P_g^2 - 2*D*P_g
    #    Linear s_i: P_bat^2 - 2*D*P_bat
    #    Quadratic u_g,u_h (g<h): 2*P_g*P_h
    #    Quadratic s_i,s_j (i<j): 2*P_bat^2
    #    Cross u_g,s_i: 2*P_g*P_bat
    #    Offset: D^2
    p_max_vals = [gen["p_max"] for gen in generators]

    for g in range(G):
        Pg = p_max_vals[g]
        bqm.add_variable(f"u_{g}", lambda2 * (Pg ** 2 - 2 * D * Pg))

    for i in range(n_buses):
        bqm.add_variable(f"s_{i}", lambda2 * (P_bat ** 2 - 2 * D * P_bat))

    for g in range(G):
        for h in range(g + 1, G):
            bqm.add_interaction(f"u_{g}", f"u_{h}", lambda2 * 2 * p_max_vals[g] * p_max_vals[h])

    for i in range(n_buses):
        for j in range(i + 1, n_buses):
            bqm.add_interaction(f"s_{i}", f"s_{j}", lambda2 * 2 * P_bat ** 2)

    for g in range(G):
        for i in range(n_buses):
            bqm.add_interaction(f"u_{g}", f"s_{i}", lambda2 * 2 * p_max_vals[g] * P_bat)

    bqm.offset += lambda2 * D ** 2

    return bqm


# ---------------------------------------------------------------------------
# Qiskit VQA path
# ---------------------------------------------------------------------------

def build_butterfly_ansatz(n_qubits: int, n_layers: int):
    """Build the butterfly ansatz circuit.

    Returns (qc, params) where qc has measure_all() applied.
    Adapted from uc_10gen_benchmark.py lines 170-187.
    """
    from qiskit import QuantumCircuit
    from qiskit.circuit import ParameterVector

    gamma = ParameterVector("γ", n_layers * n_qubits)
    beta = ParameterVector("β", n_layers * n_qubits)
    qc = QuantumCircuit(n_qubits)

    for layer in range(n_layers):
        step = 0
        stride = 1
        while stride < n_qubits:
            for q in range(n_qubits):
                target = (q + stride) % n_qubits
                if q < target:
                    qc.rzx(gamma[layer * n_qubits + step % n_qubits], q, target)
                    step += 1
            stride *= 2
        for q in range(n_qubits):
            qc.ry(beta[layer * n_qubits + q], q)

    qc.measure_all()
    return qc, list(gamma) + list(beta)


def run_vqa_qiskit(
    n_qubits_gen: int,
    n_qubits_bat: int,
    proxy_fn: Callable[[str], float],
    n_candidates: int,
    n_layers: int = 3,
) -> list[tuple]:
    """Run COBYLA VQA and return top n_candidates feasible bitstrings.

    Returns list of (u_bits, s_bits, proxy_cost) sorted ascending by proxy_cost.
    """
    from qiskit.primitives import StatevectorSampler
    from scipy.optimize import minimize as scipy_minimize

    n_qubits = n_qubits_gen + n_qubits_bat

    qc, params = build_butterfly_ansatz(n_qubits, n_layers)
    sampler = StatevectorSampler()
    n_shots_cobyla = 512
    theta0 = np.zeros(len(params))

    def objective(theta: np.ndarray) -> float:
        bound = qc.assign_parameters(dict(zip(params, theta)))
        job = sampler.run([bound], shots=n_shots_cobyla)
        counts = job.result()[0].data.meas.get_counts()
        total = sum(counts.values())
        avg_q = 0.0
        for bs, cnt in counts.items():
            # Qiskit bitstrings are little-endian (qubit 0 = rightmost)
            bs_ordered = bs[::-1]
            val = proxy_fn(bs_ordered)
            if np.isfinite(val):
                avg_q += (cnt / total) * val
        return avg_q if np.isfinite(avg_q) else 1e12

    result = scipy_minimize(
        fun=objective,
        x0=theta0,
        method="COBYLA",
        options={"maxiter": 300, "rhobeg": 1.0},
    )

    # Final 5000-shot sample
    final_qc = qc.assign_parameters(dict(zip(params, result.x)))
    job = sampler.run([final_qc], shots=5000)
    counts = job.result()[0].data.meas.get_counts()

    # Collect all unique bitstrings with their proxy costs
    seen: dict[str, float] = {}
    for bs in counts:
        bs_ordered = bs[::-1]
        if bs_ordered not in seen:
            seen[bs_ordered] = proxy_fn(bs_ordered)

    # Sort by proxy cost
    ranked = sorted(seen.items(), key=lambda x: x[1])

    candidates = []
    for bs_ordered, cost in ranked:
        u_bits = bs_ordered[:n_qubits_gen]
        s_bits = bs_ordered[n_qubits_gen:]
        if all(b == "0" for b in u_bits):
            continue
        candidates.append((u_bits, s_bits, cost))
        if len(candidates) >= n_candidates:
            break

    return candidates


# ---------------------------------------------------------------------------
# D-Wave simulated annealing path
# ---------------------------------------------------------------------------

def run_dwave_sa(
    bqm,
    n_qubits_gen: int,
    n_qubits_bat: int,
    B: int,
    n_candidates: int,
    num_reads: int | None = None,
) -> list[tuple]:
    """Run SimulatedAnnealingSampler and return top n_candidates feasible bitstrings.

    B is the number of batteries that must be placed (exact count filter).
    num_reads overrides the default max(2000, 10*n_candidates) — useful for tests.
    Returns list of (u_bits, s_bits, energy) sorted ascending by energy.
    """
    from dwave.samplers import SimulatedAnnealingSampler

    if num_reads is None:
        num_reads = max(2000, 10 * n_candidates)
    sampler = SimulatedAnnealingSampler()
    sampleset = sampler.sample(bqm, num_reads=num_reads)

    candidates = []
    seen: set[str] = set()

    for sample, energy in sampleset.data(["sample", "energy"]):
        # Extract u and s bit arrays in variable-name order
        u_bits = "".join(str(sample[f"u_{g}"]) for g in range(n_qubits_gen))
        s_bits = "".join(str(sample[f"s_{i}"]) for i in range(n_qubits_bat))

        # Feasibility: exactly B batteries placed
        if sum(int(b) for b in s_bits) != B:
            continue

        if all(b == "0" for b in u_bits):
            continue

        key = u_bits + s_bits
        if key in seen:
            continue
        seen.add(key)
        candidates.append((u_bits, s_bits, float(energy)))

        if len(candidates) >= n_candidates:
            break

    return candidates


# ---------------------------------------------------------------------------
# Classical second-stage evaluation
# ---------------------------------------------------------------------------

def evaluate_candidates(
    candidates: list[tuple],
    grid,
    generators: list[dict],
    batteries: list[dict],
    T: int,
    second_stage: str,
) -> list[tuple]:
    """Evaluate each (u_bits, s_bits, proxy_cost) candidate via ED or UC.

    Returns list of (bat_locs, commitment, true_cost, result_obj).
    second_stage: "ed" | "uc"
    """
    import copy
    from solvers.ed import run_ed
    from solvers.uc import run_uc

    results = []
    seen_bat_locs: set[tuple] = set()

    for u_bits, s_bits, _proxy_cost in candidates:
        # Decode battery locations: bus indices (1-indexed) where s_i == 1
        placed_buses = [i + 1 for i, b in enumerate(s_bits) if b == "1"]
        bat_locs = {bat_idx: bus for bat_idx, bus in enumerate(placed_buses)}

        # Decode generator commitment
        commitment = [int(b) for b in u_bits]

        # For UC, same bat_locs always produces the same result — skip duplicates
        bat_locs_key = tuple(bat_locs.values())
        if second_stage == "uc":
            if bat_locs_key in seen_bat_locs:
                continue
            seen_bat_locs.add(bat_locs_key)

        try:
            if second_stage == "ed":
                # Fix commitment: zero p_min/p_max for off generators
                gens_modified = copy.deepcopy(generators)
                for g, on in enumerate(commitment):
                    if not on:
                        gens_modified[g]["p_min"] = 0.0
                        gens_modified[g]["p_max"] = 0.0

                # gen_locs: each generator's bus (from the generator dict)
                gen_locs = {g: gen["bus"] for g, gen in enumerate(gens_modified)}
                result_obj = run_ed(grid, gens_modified, batteries, gen_locs, bat_locs, T)
                true_cost = result_obj.total_cost

            else:  # "uc"
                result_obj = run_uc(grid, generators, batteries, bat_locs, T)
                true_cost = result_obj.total_cost

            results.append((bat_locs, commitment, true_cost, result_obj))

        except (RuntimeError, Exception):
            # Skip infeasible candidates
            continue

    return results


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------

def run_quantum_siting(
    grid,
    generators: list[dict],
    batteries: list[dict],
    T: int,
    backend: str,
    n_candidates: int,
    second_stage: str,
    _num_reads: int | None = None,
):
    """Full hybrid quantum-classical siting pipeline.

    Parameters
    ----------
    grid         : PJM 5-bus Case object
    generators   : list of generator dicts from assets
    batteries    : list of battery dicts from assets
    T            : number of hours to simulate
    backend      : "qiskit" | "dwave"
    n_candidates : number of candidates to evaluate classically
    second_stage : "ed" | "uc"

    Returns
    -------
    QuantumSitingResult
    """
    from solvers.results import QuantumSitingResult

    demand = np.array(grid.power_demand)   # (n_buses, T)
    demand_ref = float(np.nanmax(demand.sum(axis=0)))  # peak total demand over horizon

    n_buses = demand.shape[0]
    G = len(generators)
    B = len(batteries)

    proxy_fn, lambda1, lambda2 = build_proxy_cost_fn(
        generators, batteries, n_buses, demand_ref, T
    )

    # ── Quantum sieve ────────────────────────────────────────────────────────
    t_q_start = time.perf_counter()

    if backend == "qiskit":
        # Qiskit VQA: we wrap proxy_fn with feasibility filter via the sieve
        # The sieve returns top candidates regardless of feasibility; we rely on
        # run_vqa_qiskit to return them sorted by proxy_cost (feasible first via P_budget)
        raw_candidates = run_vqa_qiskit(
            n_qubits_gen=G,
            n_qubits_bat=n_buses,
            proxy_fn=proxy_fn,
            n_candidates=n_candidates,
        )

        # Post-filter to exactly B batteries placed (P_budget == 0)
        feasible = [(u, s, c) for u, s, c in raw_candidates if sum(int(b) for b in s) == B]
        if not feasible:
            # Fall back to all candidates sorted by cost if none are exactly feasible
            feasible = sorted(raw_candidates, key=lambda x: x[2])
        quantum_candidates = feasible[:n_candidates]

    else:  # "dwave"
        bqm = build_bqm(generators, batteries, n_buses, demand_ref, lambda1, lambda2)
        quantum_candidates = run_dwave_sa(
            bqm=bqm,
            n_qubits_gen=G,
            n_qubits_bat=n_buses,
            B=B,
            n_candidates=n_candidates,
            num_reads=_num_reads,
        )

    runtime_quantum = time.perf_counter() - t_q_start

    # ── Classical refinement ─────────────────────────────────────────────────
    t_c_start = time.perf_counter()

    evaluated = evaluate_candidates(
        candidates=quantum_candidates,
        grid=grid,
        generators=generators,
        batteries=batteries,
        T=T,
        second_stage=second_stage,
    )

    runtime_classical = time.perf_counter() - t_c_start

    if not evaluated:
        raise RuntimeError("No feasible candidates found after classical refinement.")

    best = min(evaluated, key=lambda x: x[2])

    return QuantumSitingResult(
        backend=backend,
        second_stage=second_stage,
        n_candidates=n_candidates,
        quantum_candidates=quantum_candidates,
        evaluated=evaluated,
        best=best,
        runtime_quantum=runtime_quantum,
        runtime_classical=runtime_classical,
    )
