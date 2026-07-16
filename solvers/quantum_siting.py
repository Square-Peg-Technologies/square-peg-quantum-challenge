"""
Quantum Siting Solver — hybrid quantum-classical siting optimization.

Implements a quantum sieve stage (Qiskit VQA or D-Wave SA) over the joint
(generator commitment, battery placement) space, followed by classical
refinement via ED or UC.

Reference: arXiv:2505.00145 (IonQ/ORNL, Aboumrad et al., 2025)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Callable

import numpy as np

# ---------------------------------------------------------------------------
# Debug logger — writes to outputs/quantum_siting_debug.log
# ---------------------------------------------------------------------------
_log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs", "quantum_siting_debug.log")
os.makedirs(os.path.dirname(_log_path), exist_ok=True)
_dbg = logging.getLogger("quantum_siting")
if not _dbg.handlers:
    _fh = logging.FileHandler(_log_path, mode="w")
    _fh.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
    _dbg.addHandler(_fh)
    _dbg.setLevel(logging.DEBUG)

# ---------------------------------------------------------------------------
# Aer backend detection (optional — falls back to Qiskit StatevectorSampler)
# ---------------------------------------------------------------------------
try:
    from qiskit_aer.primitives import SamplerV2 as _AerSamplerV2
    from qiskit_aer import AerSimulator as _AerSimulator
    from qiskit.primitives import BackendSamplerV2 as _BackendSamplerV2
    _AER_AVAILABLE = True
    _aer_sim = _AerSimulator()
    _GPU_AVAILABLE = "GPU" in _aer_sim.available_devices()
    _AER_TN_AVAILABLE = "matrix_product_state" in _aer_sim.available_methods()
    del _aer_sim
except Exception:
    _AER_AVAILABLE = False
    _GPU_AVAILABLE = False
    _AER_TN_AVAILABLE = False


# ---------------------------------------------------------------------------
# PTDF-based congestion signal (Option 2 proxy enhancement)
# ---------------------------------------------------------------------------

def _compute_shadow_prices(grid, generators: list[dict], T: int) -> np.ndarray:
    """Run a no-battery DC-OPF and return line shadow prices (n_line x T).

    Shadow price[l,t] = mu_up[l,t] - mu_dn[l,t], positive when upper limit binds.
    Returns zeros array on solve failure so the proxy degrades gracefully.
    """
    try:
        import cvxpy as cp
    except ImportError:
        _dbg.warning("cvxpy not available — congestion signal skipped")
        n_line = np.array(grid.PTDF).shape[0]
        return np.zeros((n_line, T))

    PTDF   = np.array(grid.PTDF)             # (n_line, n_bus)
    fbar   = np.array(grid.fbar).flatten()   # (n_line,)
    demand = np.array(grid.power_demand)     # (n_bus, T)
    n_gen  = len(generators)
    n_bus  = PTDF.shape[1]
    n_line = PTDF.shape[0]
    gen_buses = [gen["bus"] - 1 for gen in generators]

    p = cp.Variable((n_gen, T), nonneg=True)
    constraints, balance_cons, flow_up_cons, flow_dn_cons = [], [], [], []
    obj_terms = []

    for t in range(T):
        inj = cp.Constant(np.zeros(n_bus))
        for g in range(n_gen):
            e = np.zeros(n_bus)
            e[gen_buses[g]] = 1.0
            inj = inj + e * p[g, t]
        d_t = demand[:, t]
        c_bal = cp.sum(inj) == float(d_t.sum())
        constraints.append(c_bal)
        balance_cons.append(c_bal)
        flow = PTDF @ (inj - d_t)
        c_up = flow <= fbar
        c_dn = flow >= -fbar
        constraints += [c_up, c_dn]
        flow_up_cons.append(c_up)
        flow_dn_cons.append(c_dn)
        for g, gen in enumerate(generators):
            constraints += [p[g, t] >= gen["p_min"], p[g, t] <= gen["p_max"]]
        for g, gen in enumerate(generators):
            a, b, c = gen["cost_a"], gen["cost_b"], gen["cost_c"]
            obj_terms.append(a * cp.sum_squares(p[g, t]) + b * p[g, t] + c)

    prob = cp.Problem(cp.Minimize(cp.sum(obj_terms)), constraints)
    # Clarabel first — HiGHS's QP path can hang on degenerate cases (see ed.py);
    # the time limit on the fallback guarantees this setup phase never blocks.
    try:
        prob.solve(solver="CLARABEL", verbose=False)
    except cp.error.SolverError:
        prob.solve(solver="HIGHS", verbose=False, time_limit=30.0)

    if prob.status not in ("optimal", "optimal_inaccurate"):
        _dbg.warning("No-battery OPF status=%s — congestion signal zeroed", prob.status)
        return np.zeros((n_line, T))

    shadow_prices = np.zeros((n_line, T))
    for t in range(T):
        mu_up = np.array(flow_up_cons[t].dual_value).flatten()
        mu_dn = np.array(flow_dn_cons[t].dual_value).flatten()
        shadow_prices[:, t] = mu_up - mu_dn
    return shadow_prices


def compute_congestion_signal(
    ptdf: np.ndarray,
    shadow_prices: np.ndarray,
    p_bat: float,
) -> np.ndarray:
    """Per-bus congestion relief signal from PTDF x shadow-price dot product.

    For each bus i: signal[i] = p_bat * sum_l (-PTDF[l,i] * mu_mean[l])

    Positive signal means placing a battery here tends to relieve congestion
    on binding lines; negative means it worsens congestion.

    Parameters
    ----------
    ptdf          : (n_line, n_bus) PTDF matrix
    shadow_prices : (n_line, T) shadow prices from no-battery DC-OPF
    p_bat         : battery power rating (MW) — scales signal to $/h units

    Returns
    -------
    signal : (n_bus,) array, units $/h
    """
    mu_mean = shadow_prices.mean(axis=1)          # (n_line,) time-average
    # signal[i] = p_bat * sum_l (-PTDF[l,i] * mu_mean[l])
    # = -p_bat * PTDF.T @ mu_mean
    signal = -p_bat * (ptdf.T @ mu_mean)          # (n_bus,)
    return signal


# ---------------------------------------------------------------------------
# Proxy cost function (lazy classical evaluation from bitstring)
# ---------------------------------------------------------------------------

def build_proxy_cost_fn(
    generators: list[dict],
    batteries: list[dict],
    n_buses: int,
    demand_ref: float,
    T: int = 1,
    congestion_signal: np.ndarray | None = None,
) -> tuple[Callable[[str], float], float, float]:
    """Return (proxy_fn, lambda1, lambda2) for lazy Q(u,s) evaluation.

    proxy_fn(bitstring: str) -> float
        Bitstring layout: u_0..u_{G-1} s_0..s_{N-1} (index 0 = leftmost char).
        Returns Q(u, s) = c_min(u) + lambda1*P_budget(s) + lambda2*P_infeas(u,s)
                        - P_loc(s)
        where P_loc(s) = T * sum_i s_i * congestion_signal[i] (congestion relief bonus).

    lambda1, lambda2 are the BQM lambdas (D-Wave path, per-hour scaling).
    proxy_fn uses T-scaled lambdas with a one-sided infeasibility penalty so that
    over-capacity combinations are not penalised (only shortfall is penalised).
    congestion_signal: optional (n_buses,) array from compute_congestion_signal();
        if None the P_loc term is omitted.
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

    # Precompute per-bus congestion bonus scaled to horizon ($/horizon)
    _cong = None
    if congestion_signal is not None:
        _cong = np.asarray(congestion_signal, dtype=float) * T

    def proxy_fn(bitstring: str) -> float:
        u = [int(bitstring[g]) for g in range(G)]
        s = [int(bitstring[G + i]) for i in range(n_buses)]

        c_min_val = sum(u[g] * c_min_coeffs[g] for g in range(G)) * T

        p_budget = (sum(s) - B) ** 2

        # One-sided: penalise generator shortfall only.
        # Batteries are excluded — they shift energy, not create capacity,
        # so generator commitment alone must cover peak demand.
        shortfall = max(
            0.0,
            demand_ref
            - sum(u[g] * p_max_vals[g] for g in range(G)),
        )
        p_infeas = shortfall ** 2

        # P_loc: subtract congestion relief bonus for each placed battery
        p_loc = 0.0
        if _cong is not None:
            p_loc = sum(s[i] * _cong[i] for i in range(n_buses))

        return c_min_val + _lam1 * p_budget + _lam2 * p_infeas - p_loc

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
    congestion_signal: np.ndarray | None = None,
):
    """Build a dimod.BinaryQuadraticModel encoding Q(u, s).

    Variable naming: u_g for generator g, s_i for bus i.
    congestion_signal: optional (n_buses,) array from compute_congestion_signal();
        adds a linear bias -signal[i] to each s_i (congestion relief bonus, $/h).
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

    # P_loc: congestion relief bonus — subtract signal[i] from linear bias of s_i
    if congestion_signal is not None:
        cong = np.asarray(congestion_signal, dtype=float)
        for i in range(n_buses):
            bqm.add_variable(f"s_{i}", -float(cong[i]))

    return bqm


# ---------------------------------------------------------------------------
# LP relaxation warm-start helper (paper Section III, arXiv:2505.00145)
# ---------------------------------------------------------------------------

def _solve_lp_relaxation(
    generators: list[dict],
    batteries: list[dict],
    n_buses: int,
    demand_ref: float,
    T: int,
) -> np.ndarray:
    """Solve the continuous relaxation of the proxy QUBO over [0,1]^n.

    Returns x* ∈ [0,1]^n ordered as [gen_0..gen_{G-1}, bus_0..bus_{N-1}].
    Maps to initial β angles via β_j = 2·arcsin(√(x_j*)) so the circuit
    starts in the state closest to the LP-relaxation optimum (paper Section III).
    """
    from scipy.optimize import minimize as scipy_minimize

    G = len(generators)
    B = len(batteries)
    n = G + n_buses

    c_min_coeffs = np.array([
        g["cost_a"] * g["p_min"] ** 2 + g["cost_b"] * g["p_min"] + g["cost_c"]
        for g in generators
    ])
    p_max_vals = np.array([g["p_max"] for g in generators])

    c_min_total = float(c_min_coeffs.sum()) * T
    _lam1 = c_min_total * 2.0
    _lam2 = c_min_total * 20.0 / (demand_ref ** 2 + 1e-6)

    def q_relax(x: np.ndarray) -> float:
        x_gen = x[:G]
        x_bat = x[G:]
        c_val = float(c_min_coeffs @ x_gen) * T
        p_budget = (x_bat.sum() - B) ** 2
        shortfall = max(0.0, demand_ref - float(p_max_vals @ x_gen))
        return c_val + _lam1 * p_budget + _lam2 * shortfall ** 2

    x0 = np.full(n, 0.5)
    bounds = [(0.0, 1.0)] * n
    res = scipy_minimize(q_relax, x0, method="SLSQP", bounds=bounds,
                         options={"ftol": 1e-9, "maxiter": 500})
    x_star = np.clip(res.x, 0.0, 1.0)
    _dbg.debug("LP relaxation x*: gen=%s bat=%s obj=%.4g",
               x_star[:G].round(3), x_star[G:].round(3), res.fun)
    return x_star


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


def build_linear_chain_ansatz(n_qubits: int, n_layers: int):
    """1D brick-wall HEA for MPS/TN-compatible simulation.

    Each layer: RY on every qubit, then nearest-neighbor RZX in alternating
    even/odd brick-wall pattern.  Only adjacent two-qubit gates — MPS bond
    dimension stays tractable regardless of qubit count.

    Returns (qc, params) where params = gamma_list + beta_list.
    """
    from qiskit import QuantumCircuit
    from qiskit.circuit import ParameterVector

    n_even = n_qubits // 2          # even pairs: (0,1),(2,3),...
    n_odd  = (n_qubits - 1) // 2   # odd  pairs: (1,2),(3,4),...
    # Count RZX params exactly: alternating even/odd per layer
    n_rzx = sum(n_even if l % 2 == 0 else n_odd for l in range(n_layers))

    gamma = ParameterVector("γ", n_rzx)
    beta  = ParameterVector("β", n_layers * n_qubits)
    qc    = QuantumCircuit(n_qubits)

    g_idx = 0
    for layer in range(n_layers):
        for q in range(n_qubits):
            qc.ry(beta[layer * n_qubits + q], q)
        pairs = range(0, n_qubits - 1, 2) if layer % 2 == 0 else range(1, n_qubits - 1, 2)
        for q in pairs:
            qc.rzx(gamma[g_idx], q, q + 1)
            g_idx += 1

    qc.measure_all()
    return qc, list(gamma) + list(beta)


def run_vqa_qiskit(
    n_qubits_gen: int,
    n_qubits_bat: int,
    proxy_fn: Callable[[str], float],
    n_candidates: int,
    n_layers: int = 3,
    warm_start: str = "zeros",
    track_convergence: bool = False,
    _sdp_ingredients: dict | None = None,
    phase_times: dict | None = None,
    device: str = "auto",
    sim_method: str = "statevector",
    max_time_s: float | None = None,
    ansatz: str = "auto",
    final_backend: str = "local",
    final_shots: int | None = None,
) -> tuple[list[tuple], list[float]]:
    """Run COBYLA VQA and return (candidates, convergence_trace).

    final_backend: "local" (default — final shots sampled on the same local
        Aer/Qiskit sampler used for training) or "ionq_qbraid" (COBYLA
        training still runs locally for speed/cost, but the final converged
        circuit is submitted to the qBraid-routed IonQ device — see
        solvers/ionq_qbraid_backend.py). final_shots is only used in the
        "ionq_qbraid" case; if None (default), resolves via
        ionq_qbraid_backend.default_shots(DEVICE_ID) — 5000 on the free
        simulator, 500 on billed real hardware, so switching DEVICE_ID to
        Forte 1 doesn't silently also switch to a 5000-shot bill. The local
        path always uses 5000 shots for the final extraction.

    candidates: list of (u_bits, s_bits, proxy_cost) sorted ascending by proxy_cost.
    convergence_trace: COBYLA objective value at each function evaluation (empty if
        track_convergence=False).
    phase_times: optional dict filled in-place with wall-time per phase:
        statevector sampling (accumulated sampler calls during COBYLA),
        COBYLA classical overhead, and the final 5000-shot extraction.
    device: "auto" (GPU if available), "GPU" (RuntimeError if unavailable),
        or "CPU" (forced even when a GPU exists).

    warm_start strategies (arXiv:2505.00145):
      "zeros"  — θ=0, paper simulation default (Section IV-A)
      "random" — θ~Uniform[-2π,2π], paper IonQ hardware default (Fig. 6/8)
      "sdp"    — LP-relaxation warm start, paper Section III mixer design;
                 requires _sdp_ingredients dict with keys:
                 generators, batteries, demand_ref, T
    """
    from scipy.optimize import fmin_cobyla

    n_qubits = n_qubits_gen + n_qubits_bat

    # ansatz selection: "auto" picks linear-chain for TN, butterfly otherwise.
    _use_linear = (ansatz == "linear_chain") or (ansatz == "auto" and sim_method == "tensor_network")
    if _use_linear:
        # Linear-chain HEA: MPS-compatible, nearest-neighbor gates only.
        # Use more layers than butterfly to compensate for reduced connectivity.
        _tn_layers = n_layers if n_layers != 3 else 2
        qc, params = build_linear_chain_ansatz(n_qubits, _tn_layers)
        n_layers = _tn_layers
        _ansatz_label = "linear-chain HEA"
    else:
        qc, params = build_butterfly_ansatz(n_qubits, n_layers)
        _ansatz_label = "butterfly ansatz"

    # n_gamma: size of γ (RZX) block — used for warm-start β indexing
    n_beta  = n_layers * n_qubits
    n_gamma = len(params) - n_beta

    _sim_display = "MPS (matrix_product_state)" if sim_method == "tensor_network" else sim_method

    if sim_method not in ("statevector", "tensor_network"):
        raise ValueError(f"Unknown sim_method: {sim_method!r} (use 'statevector' or 'tensor_network')")
    if sim_method == "tensor_network" and not (_AER_AVAILABLE and _AER_TN_AVAILABLE):
        raise RuntimeError(
            "sim_method='tensor_network' requested but not available — "
            "install qiskit-aer with matrix_product_state support."
        )
    if device not in ("auto", "GPU", "CPU"):
        raise ValueError(f"Unknown device: {device!r} (use 'auto', 'GPU', or 'CPU')")
    if device == "GPU" and not (_AER_AVAILABLE and _GPU_AVAILABLE):
        raise RuntimeError(
            "GPU statevector requested but not available — qiskit-aer-gpu is "
            "missing or no GPU was detected. Use device='CPU' or 'auto'."
        )
    use_gpu = _GPU_AVAILABLE if device == "auto" else device == "GPU"

    if _AER_AVAILABLE:
        if sim_method == "tensor_network":
            # CPU-native MPS: handles 36+ qubits without the memory requirements of
            # statevector.  cuTensorNet (GPU) fails on our 4-layer linear-chain circuits
            # with CUTENSORNET_STATUS_INTERNAL_ERROR regardless of qubit count, so we
            # use BackendSamplerV2 + AerSimulator(mps) which is reliable.
            sampler = _BackendSamplerV2(backend=_AerSimulator(method="matrix_product_state"))
        else:
            sampler = _AerSamplerV2()
            if use_gpu:
                sampler.options.backend_options = {
                    "method": "statevector", "device": "GPU", "precision": "single"
                }
            else:
                sampler.options.backend_options = {"method": "statevector", "device": "CPU"}
    else:
        from qiskit.primitives import StatevectorSampler
        sampler = StatevectorSampler()

    print(f"\n{'='*60}")
    print(f"  Quantum VQA starting")
    print(f"  Backend : {_sim_display}")
    print(f"  Ansatz  : {_ansatz_label}")
    print(f"  Qubits  : {n_qubits}  ({n_qubits_gen} gen + {n_qubits_bat} bus)")
    print(f"  Layers  : {n_layers}   Params : {len(params)}")
    print(f"  Warm start: {warm_start}   Max time: {max_time_s}s")
    print(f"{'='*60}\n")

    n_shots_cobyla = 512

    if warm_start == "zeros":
        theta0 = np.zeros(len(params))
    elif warm_start == "random":
        rng = np.random.default_rng()
        theta0 = rng.uniform(-2 * np.pi, 2 * np.pi, len(params))
    elif warm_start == "sdp":
        if _sdp_ingredients is None:
            raise ValueError("warm_start='sdp' requires _sdp_ingredients dict")
        x_star = _solve_lp_relaxation(
            generators=_sdp_ingredients["generators"],
            batteries=_sdp_ingredients["batteries"],
            n_buses=n_qubits_bat,
            demand_ref=_sdp_ingredients["demand_ref"],
            T=_sdp_ingredients["T"],
        )
        # x_star has shape (n_qubits,); β block has shape (n_layers * n_qubits,)
        # tile across layers so each layer's RY gates start at the warm-start angle
        x_star_tiled = np.tile(x_star, n_layers)
        theta0 = np.zeros(len(params))
        theta0[n_gamma:] = 2.0 * np.arcsin(np.sqrt(np.clip(x_star_tiled, 0.0, 1.0)))
    else:
        raise ValueError(f"Unknown warm_start strategy: {warm_start!r}")

    _dbg.debug("warm_start=%s theta0 β-block mean=%.3f", warm_start, theta0[n_gamma:].mean())

    convergence_trace: list[float] = []
    _t_sampling = [0.0]   # accumulated wall time inside sampler calls (GPU/CPU statevector)
    _deadline = [None if max_time_s is None else time.perf_counter() + max_time_s]

    # Plateau detection state — stochastic objectives keep COBYLA's trust region
    # noisy so rhoend never triggers; instead we stop when the best value hasn't
    # improved by more than 1% in the last `patience` evaluations.
    _best_val = [float("inf")]
    _best_theta = [theta0.copy()]
    _stale = [0]
    _patience = max(50, len(params))

    class _Plateau(Exception):
        pass

    def objective(theta: np.ndarray) -> float:
        bound = qc.assign_parameters(dict(zip(params, theta)))
        t0 = time.perf_counter()
        job = sampler.run([bound], shots=n_shots_cobyla)
        counts = job.result()[0].data.meas.get_counts()
        _t_sampling[0] += time.perf_counter() - t0
        total = sum(counts.values())
        avg_q = 0.0
        for bs, cnt in counts.items():
            # Qiskit bitstrings are little-endian (qubit 0 = rightmost)
            bs_ordered = bs[::-1]
            val = proxy_fn(bs_ordered)
            if np.isfinite(val):
                avg_q += (cnt / total) * val
        val_out = avg_q if np.isfinite(avg_q) else 1e12
        if track_convergence:
            convergence_trace.append(val_out)
        # Wall-time cutoff
        if _deadline[0] is not None and time.perf_counter() >= _deadline[0]:
            raise _Plateau()
        # Plateau detection: track best and count stale evaluations
        if val_out < _best_val[0] * 0.99:
            _best_val[0] = val_out
            _best_theta[0] = theta.copy()
            _stale[0] = 0
        else:
            _stale[0] += 1
            if _stale[0] >= _patience:
                raise _Plateau()
        return val_out

    # Adaptive maxfun: 6 evals per parameter, min 150 (paper Fig. 2 linear scaling).
    # fmin_cobyla used directly — scipy.optimize.minimize ignores rhoend.
    maxfun = max(150, 6 * len(params))
    _dbg.debug("COBYLA maxfun=%d patience=%d (n_params=%d)", maxfun, _patience, len(params))
    t_opt_start = time.perf_counter()
    try:
        xopt = fmin_cobyla(
            func=objective,
            x0=theta0,
            cons=[],
            rhobeg=1.0,
            rhoend=1e-4,
            maxfun=maxfun,
            disp=0,
        )
    except _Plateau:
        xopt = _best_theta[0]
        _dbg.debug("COBYLA stopped early via plateau detection at nfev=%d", len(convergence_trace))
    t_opt = time.perf_counter() - t_opt_start

    # Final shot sample — locally (5000 shots) unless final_backend="ionq_qbraid",
    # in which case this is the one real qBraid/IonQ submission in the whole run.
    t_final_start = time.perf_counter()
    final_qc = qc.assign_parameters(dict(zip(params, xopt)))
    if final_backend == "ionq_qbraid":
        from solvers.ionq_qbraid_backend import run_circuit_shots, default_shots, DEVICE_ID
        if final_shots is None:
            final_shots = default_shots(DEVICE_ID)
        counts = run_circuit_shots(final_qc, shots=final_shots)
    elif final_backend == "local":
        job = sampler.run([final_qc], shots=5000)
        counts = job.result()[0].data.meas.get_counts()
    else:
        raise ValueError(f"Unknown final_backend: {final_backend!r} (use 'local' or 'ionq_qbraid')")

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

    if phase_times is not None:
        if sim_method == "tensor_network":
            sim_label = "MPS-CPU"
        else:
            sim_label = "GPU" if (_AER_AVAILABLE and use_gpu) else "CPU"
        phase_times[f"Aer sampling ({sim_label})"] = _t_sampling[0]
        phase_times["COBYLA + proxy eval (CPU)"] = max(0.0, t_opt - _t_sampling[0])
        if final_backend == "ionq_qbraid":
            phase_times[f"IonQ (qBraid) final sampling ({final_shots} shots)"] = (
                time.perf_counter() - t_final_start
            )
        else:
            phase_times["Final 5000-shot extraction"] = time.perf_counter() - t_final_start

    return candidates, convergence_trace


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

def _eval_one(args: tuple):
    """Top-level worker for parallel candidate evaluation (must be picklable)."""
    import copy
    bat_locs, commitment, grid, generators, batteries, T, second_stage = args
    try:
        if second_stage == "ed":
            from solvers.ed import run_ed
            gens_modified = copy.deepcopy(generators)
            for g, on in enumerate(commitment):
                if not on:
                    gens_modified[g]["p_min"] = 0.0
                    gens_modified[g]["p_max"] = 0.0
            gen_locs = {g: gen["bus"] for g, gen in enumerate(gens_modified)}
            result_obj = run_ed(grid, gens_modified, batteries, gen_locs, bat_locs, T)
        else:
            from solvers.uc import run_uc
            result_obj = run_uc(grid, generators, batteries, bat_locs, T)
        return (bat_locs, commitment, result_obj.total_cost, result_obj)
    except Exception:
        return None


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
    Candidates are evaluated in parallel using all available CPU cores.
    second_stage: "ed" | "uc"

    Workers use the "spawn" start method: the parent holds an active CUDA
    context after GPU statevector sampling, and fork()ing a CUDA-active
    process intermittently deadlocks the child (fork is unsafe with CUDA).
    """
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor
    from solvers.siting_benders import _GridData

    # Make grid picklable for subprocess workers
    grid_data = _GridData(grid)

    # Decode and deduplicate before dispatch
    seen_bat_locs: set[tuple] = set()
    work_items = []
    for u_bits, s_bits, _proxy_cost in candidates:
        placed_buses = [i + 1 for i, b in enumerate(s_bits) if b == "1"]
        # A candidate with more (or fewer) placed buses than real batteries is
        # infeasible — it can't map onto len(batteries) battery objects. This
        # can slip through when the quantum sieve's upstream feasibility
        # filter falls back to "use all candidates anyway" (e.g. it never
        # found an exactly-B-battery candidate within the time budget).
        # Skipping it here — rather than passing it through — is what
        # prevents a battery-count mismatch from surfacing later as an
        # IndexError deep in plotting code that assumes bat_locs keys stay
        # within range(len(batteries)).
        if len(placed_buses) != len(batteries):
            _dbg.debug(
                "Skipping infeasible candidate: %d buses placed, expected %d batteries",
                len(placed_buses), len(batteries),
            )
            continue
        bat_locs = {bat_idx: bus for bat_idx, bus in enumerate(placed_buses)}
        commitment = [int(b) for b in u_bits]
        bat_locs_key = tuple(bat_locs.values())
        if second_stage == "uc":
            if bat_locs_key in seen_bat_locs:
                continue
            seen_bat_locs.add(bat_locs_key)
        work_items.append((bat_locs, commitment, grid_data, generators, batteries, T, second_stage))

    results = []
    if not work_items:
        # All candidates were filtered out above (wrong battery count, or
        # deduped away) — nothing to submit. Let the caller's "no feasible
        # candidates" check handle this instead of asking for 0 workers.
        return results

    n_workers = min(len(work_items), os.cpu_count() or 1)
    with ProcessPoolExecutor(max_workers=n_workers,
                             mp_context=multiprocessing.get_context("spawn")) as pool:
        for outcome in pool.map(_eval_one, work_items):
            if outcome is not None:
                bat_locs, commitment, true_cost, result_obj = outcome
                _dbg.debug("PASS bat_locs=%s commit=%s cost=%.0f", bat_locs, commitment, true_cost)
                results.append(outcome)

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
    warm_start: str = "zeros",
    track_convergence: bool = False,
    _num_reads: int | None = None,
    device: str = "auto",
    max_time_s: float | None = None,
    ansatz: str = "auto",
    final_shots: int | None = None,
):
    """Full hybrid quantum-classical siting pipeline.

    Parameters
    ----------
    grid             : PJM 5-bus Case object
    generators       : list of generator dicts from assets
    batteries        : list of battery dicts from assets
    T                : number of hours to simulate
    backend          : "qiskit" | "aer_tn" | "dwave" | "ionq_qbraid"
    n_candidates     : number of candidates to evaluate classically
    second_stage     : "ed" | "uc"
    warm_start       : "zeros" | "random" | "sdp" (Qiskit/ionq_qbraid path only)
    track_convergence: record COBYLA objective per iteration (Qiskit/ionq_qbraid path only)
    device           : "auto" | "GPU" | "CPU" statevector device (Qiskit path only;
                       ionq_qbraid always trains locally on statevector, same as Qiskit)
    ansatz           : "auto" | "butterfly" | "linear_chain" (Qiskit/Aer TN/ionq_qbraid path only)
    final_shots      : shot count for the one real qBraid/IonQ submission when
                       backend="ionq_qbraid" (minimum 100). If None (default),
                       auto-picked by ionq_qbraid_backend.default_shots() based
                       on DEVICE_ID (5000 on the free simulator, 500 on billed
                       real hardware). Unused otherwise.

    "ionq_qbraid": COBYLA trains locally (identical to the "qiskit" backend —
    submitting each of the ~150+ training iterations to qBraid would be far
    too slow/costly), then the single converged circuit is submitted to the
    qBraid-routed IonQ device (solvers/ionq_qbraid_backend.py) for the final
    shot sample, so the reported result is a real IonQ execution. See that
    module's DEVICE_ID for the current device (simulator by default; swap to
    Forte 1 once real QPU account access is sorted).

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

    runtime_phases: dict[str, float] = {}

    # Compute congestion signal from no-battery DC-OPF shadow prices
    t_setup_start = time.perf_counter()
    ptdf = np.array(grid.PTDF)
    shadow_prices = _compute_shadow_prices(grid, generators, T)
    p_bat = batteries[0]["power_mw"]
    congestion_signal = compute_congestion_signal(ptdf, shadow_prices, p_bat)
    _dbg.debug(
        "Congestion signal ($/h): %s",
        ", ".join(f"bus{i+1}={v:.1f}" for i, v in enumerate(congestion_signal)),
    )

    proxy_fn, lambda1, lambda2 = build_proxy_cost_fn(
        generators, batteries, n_buses, demand_ref, T,
        congestion_signal=congestion_signal,
    )
    runtime_phases["Setup (shadow-price OPF + proxy)"] = time.perf_counter() - t_setup_start

    # ── Quantum sieve ────────────────────────────────────────────────────────
    t_q_start = time.perf_counter()

    if backend in ("qiskit", "aer_tn", "ionq_qbraid"):
        # Qiskit VQA: we wrap proxy_fn with feasibility filter via the sieve
        # The sieve returns top candidates regardless of feasibility; we rely on
        # run_vqa_qiskit to return them sorted by proxy_cost (feasible first via P_budget)
        # "ionq_qbraid" trains locally (statevector, same as "qiskit") and only
        # swaps the final shot sample onto the qBraid-routed IonQ device.
        _sdp_ingredients = None
        if warm_start == "sdp":
            _sdp_ingredients = {
                "generators": generators,
                "batteries": batteries,
                "demand_ref": demand_ref,
                "T": T,
            }
        _sim_method = "tensor_network" if backend == "aer_tn" else "statevector"
        _final_backend = "ionq_qbraid" if backend == "ionq_qbraid" else "local"
        raw_candidates, convergence_trace = run_vqa_qiskit(
            n_qubits_gen=G,
            n_qubits_bat=n_buses,
            proxy_fn=proxy_fn,
            n_candidates=n_candidates,
            warm_start=warm_start,
            track_convergence=track_convergence,
            _sdp_ingredients=_sdp_ingredients,
            phase_times=runtime_phases,
            device=device,
            sim_method=_sim_method,
            max_time_s=max_time_s,
            ansatz=ansatz,
            final_backend=_final_backend,
            final_shots=final_shots,
        )

        # Post-filter to exactly B batteries placed (P_budget == 0)
        feasible = [(u, s, c) for u, s, c in raw_candidates if sum(int(b) for b in s) == B]
        if not feasible:
            # Fall back to all candidates sorted by cost if none are exactly feasible
            feasible = sorted(raw_candidates, key=lambda x: x[2])
        quantum_candidates = feasible[:n_candidates]

    else:  # "dwave"
        convergence_trace = []
        bqm = build_bqm(
            generators, batteries, n_buses, demand_ref, lambda1, lambda2,
            congestion_signal=congestion_signal,
        )
        quantum_candidates = run_dwave_sa(
            bqm=bqm,
            n_qubits_gen=G,
            n_qubits_bat=n_buses,
            B=B,
            n_candidates=n_candidates,
            num_reads=_num_reads,
        )
        runtime_phases["D-Wave SA sampling"] = time.perf_counter() - t_q_start

    runtime_quantum = time.perf_counter() - t_q_start

    # ── Classical refinement ─────────────────────────────────────────────────
    t_c_start = time.perf_counter()

    _dbg.debug("Quantum sieve produced %d candidates (peak demand=%.1f MW)", len(quantum_candidates), demand_ref)
    for u, s, c in quantum_candidates:
        _dbg.debug("  candidate u=%s s=%s proxy=%.1f n_bats=%d", u, s, c, sum(int(b) for b in s))
    evaluated = evaluate_candidates(
        candidates=quantum_candidates,
        grid=grid,
        generators=generators,
        batteries=batteries,
        T=T,
        second_stage=second_stage,
    )

    runtime_classical = time.perf_counter() - t_c_start
    stage_label = "ED" if second_stage == "ed" else "UC"
    runtime_phases[f"Classical {stage_label} refinement"] = runtime_classical

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
        warm_start=warm_start if backend in ("qiskit", "ionq_qbraid") else "zeros",
        convergence_trace=convergence_trace if track_convergence else None,
        runtime_phases=runtime_phases,
    )
