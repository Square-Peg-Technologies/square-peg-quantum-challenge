"""
26-generator Unit Commitment benchmark.

At this scale three things break down from the 3/10-generator approach:

  1. Classical brute force (2^26 = 67M assignments) is computationally infeasible.
     Replaced with a two-phase MIP approach using scipy.optimize.milp:
       Phase 1 — solve a 0-1 integer program to find the binary assignment u
                 that minimises sum_j u_j * c_min_j subject to meeting demand.
       Phase 2 — run SLSQP dispatch on the winning assignment to get exact
                 power levels and true cost (same as the tutorial notebook).

  2. VQA statevector simulation requires storing 2^26 complex amplitudes (~1 GB)
     and matrix-vector multiplies of that size. On CPU this is impractical.
     The VQA section is stubbed out with comments explaining what would be needed
     to run it: either a GPU-backed statevector simulator or real quantum hardware
     via qBraid (IBM or IonQ) with shot-based sampling.

  3. Simulated annealing (D-Wave Ocean SDK) scales fine — it runs annealing chains
     rather than enumerating the state space, so 26 variables is no problem.
     Included and run as normal with more reads to compensate for larger landscape.

This script is intended as a scaling study companion to uc_10gen_benchmark.py.
It shows where classical and quantum methods stand at a problem size where
classical MIP solvers begin to struggle on tight instances.
"""

import time
import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import minimize, milp, LinearConstraint, Bounds
from scipy.special import erf
import dimod
from dwave.samplers import SimulatedAnnealingSampler

# ── Generator specifications (26 units) ──────────────────────────────────────
# Parameters generated with a fixed seed to be reproducible.
# Follow the same quadratic cost structure F_j(p) = a*p^2 + b*p + c as the paper.
# Fleet is a realistic mix: a few large baseload units, medium mid-merit units,
# and small peakers — typical of a regional grid.

rng = np.random.default_rng(seed=42)

N_UNITS = 26

GENERATORS = []
for j in range(N_UNITS):
    if j < 5:
        # Large baseload (high fixed cost, efficient variable cost)
        gen = {
            "p_min": int(rng.integers(150, 250)),
            "p_max": int(rng.integers(500, 800)),
            "a": round(float(rng.uniform(0.0012, 0.002)), 4),
            "b": round(float(rng.uniform(9.0, 12.0)), 2),
            "c": round(float(rng.uniform(450, 700)), 1),
        }
    elif j < 15:
        # Mid-merit (moderate size and cost)
        gen = {
            "p_min": int(rng.integers(80, 150)),
            "p_max": int(rng.integers(300, 500)),
            "a": round(float(rng.uniform(0.002, 0.004)), 4),
            "b": round(float(rng.uniform(7.0, 10.0)), 2),
            "c": round(float(rng.uniform(200, 400)), 1),
        }
    else:
        # Small peakers (low fixed cost, less efficient)
        gen = {
            "p_min": int(rng.integers(40, 80)),
            "p_max": int(rng.integers(150, 300)),
            "a": round(float(rng.uniform(0.004, 0.007)), 4),
            "b": round(float(rng.uniform(5.0, 8.0)), 2),
            "c": round(float(rng.uniform(60, 180)), 1),
        }
    GENERATORS.append(gen)

# 4 time periods spanning low, medium, high, and medium-high demand
# Scaled to match a 26-unit fleet's capacity range
DEMANDS = [800, 2500, 5500, 1800]
N_PERIODS = len(DEMANDS)

total_p_max = sum(g["p_max"] for g in GENERATORS)
print(f"Problem: {N_UNITS} generators, {N_PERIODS} time periods")
print(f"Total fleet capacity: {total_p_max} MW")
print(f"Demands: {DEMANDS} MW")
print(f"Brute force space: 2^{N_UNITS} = {2**N_UNITS:,} assignments — NOT enumerated\n")


# ── Shared utility functions ──────────────────────────────────────────────────

def gen_cost(gen, p):
    return gen["a"] * p**2 + gen["b"] * p + gen["c"]

def c_min_j(j):
    """Minimum cost for generator j when ON: F_j(p_min)."""
    g = GENERATORS[j]
    return g["a"] * g["p_min"]**2 + g["b"] * g["p_min"] + g["c"]

def infeasibility_penalty(assignment, demand):
    p_max_total = sum(GENERATORS[j]["p_max"] for j, u in enumerate(assignment) if u == 1)
    shortfall = max(0.0, demand - p_max_total)
    return float(erf(shortfall))

def solve_dispatch(assignment, demand):
    """SLSQP dispatch: find optimal continuous output given a fixed binary assignment."""
    active_idx = [j for j, u in enumerate(assignment) if u == 1]
    if not active_idx:
        return float("inf"), None
    active_gens = [GENERATORS[j] for j in active_idx]
    p_min_vals = [g["p_min"] for g in active_gens]
    p_max_vals = [g["p_max"] for g in active_gens]
    if sum(p_max_vals) < demand:
        return float("inf"), None
    n = len(active_gens)
    result = minimize(
        fun=lambda p: sum(gen_cost(active_gens[i], p[i]) for i in range(n)),
        x0=[demand / n] * n,
        method="SLSQP",
        bounds=list(zip(p_min_vals, p_max_vals)),
        constraints={"type": "eq", "fun": lambda p: sum(p) - demand},
    )
    if not result.success:
        return float("inf"), None
    full_p = [0.0] * N_UNITS
    for i, j in enumerate(active_idx):
        full_p[j] = result.x[i]
    return result.fun, full_p


# ── Classical solver: MIP + SLSQP ────────────────────────────────────────────
#
# Why not brute force?
# 2^26 = 67 million assignments. Even at 1 microsecond per feasibility check
# that is 67 seconds just to scan — before running any SLSQP. With SLSQP
# per assignment it would take hours.
#
# Approach: scipy.optimize.milp
# Phase 1 — 0-1 integer program minimising sum_j u_j * c_min_j subject to
#            sum_j u_j * p_max_j >= demand (the fleet can physically meet load).
#            This finds the cheapest feasible assignment without enumerating.
# Phase 2 — SLSQP dispatch on the winning assignment to get exact power levels
#            and true cost, identical to the tutorial notebook.
#
# Limitation: milp solves the c_min proxy, not the true quadratic dispatch cost.
# The result is a very good assignment but may not be globally optimal for the
# true cost function. At this scale it is the best tractable classical baseline
# without a commercial solver like CPLEX or Gurobi.

def classical_mip_solve(demand):
    """MIP (Phase 1) + SLSQP (Phase 2) UC solution for a single time period."""

    # Phase 1: minimise sum_j u_j * c_min_j subject to sum_j u_j * p_max_j >= demand
    c_obj = np.array([c_min_j(j) for j in range(N_UNITS)])           # objective
    p_max_arr = np.array([GENERATORS[j]["p_max"] for j in range(N_UNITS)])

    # Feasibility constraint: sum_j u_j * p_max_j >= demand
    constraints = LinearConstraint(
        A=p_max_arr.reshape(1, -1),
        lb=demand,
        ub=np.inf,
    )

    # All variables binary (integrality=1), bounded [0, 1]
    integrality = np.ones(N_UNITS)
    bounds = Bounds(lb=np.zeros(N_UNITS), ub=np.ones(N_UNITS))

    mip_result = milp(c=c_obj, constraints=constraints,
                      integrality=integrality, bounds=bounds)

    if not mip_result.success:
        return {"assignment": None, "dispatch": None, "cost": float("inf")}

    assignment = [int(round(x)) for x in mip_result.x]

    # Phase 2: exact dispatch via SLSQP
    true_cost, dispatch = solve_dispatch(assignment, demand)
    return {"assignment": assignment, "dispatch": dispatch, "cost": true_cost}

print("Running classical MIP solver (scipy.optimize.milp + SLSQP dispatch)...")
t0 = time.perf_counter()
classical_results = [classical_mip_solve(d) for d in DEMANDS]
classical_time = time.perf_counter() - t0

print(f"  Done in {classical_time*1000:.1f} ms")
for t, res in enumerate(classical_results):
    on_count = sum(res["assignment"]) if res["assignment"] else 0
    print(f"  Period {t} (demand={DEMANDS[t]} MW): {on_count} units ON, cost={res['cost']:.2f} $/h")


# ── QUBO / simulated annealing ────────────────────────────────────────────────
#
# Simulated annealing scales fine to 26 variables — it runs annealing chains
# rather than enumerating the state space. More reads used here (5000) to
# give better landscape coverage at the larger problem size.

def compute_lambda(demand):
    """
    Estimate lambda from the MIP solution neighbourhood.
    At 26 generators we can't enumerate all feasible assignments to compute
    the exact c_min range, so we use a heuristic: 2x the c_min of the MIP
    solution, which gives a conservative but effective penalty weight.
    """
    mip = classical_mip_solve(demand)
    if mip["assignment"] is None:
        return 50000.0
    c_min_mip = sum(c_min_j(j) for j, u in enumerate(mip["assignment"]) if u == 1)
    return max(c_min_mip * 2, 10000.0)

def build_qubo(demand, lam):
    bqm = dimod.BinaryQuadraticModel(vartype="BINARY")
    for j, gen in enumerate(GENERATORS):
        linear_cost = gen["a"] * gen["p_min"]**2 + gen["b"] * gen["p_min"] + gen["c"]
        bqm.add_variable(j, linear_cost)
    for j, gen in enumerate(GENERATORS):
        bqm.add_variable(j, lam * (-2 * demand * gen["p_max"] + gen["p_max"]**2))
    for i in range(N_UNITS):
        for j in range(i + 1, N_UNITS):
            bqm.add_interaction(i, j, lam * 2 * GENERATORS[i]["p_max"] * GENERATORS[j]["p_max"])
    return bqm

print("\nRunning simulated annealing (QUBO, 5000 reads per period)...")
sampler = SimulatedAnnealingSampler()
annealing_results = []
t0 = time.perf_counter()

for t, demand in enumerate(DEMANDS):
    lam = compute_lambda(demand)
    bqm = build_qubo(demand, lam)
    sampleset = sampler.sample(bqm, num_reads=5000)
    annealing_results.append((t, demand, sampleset))

annealing_time = time.perf_counter() - t0

annealing_solved = []
for t, demand, sampleset in annealing_results:
    best_cost, best_assignment, best_dispatch = float("inf"), None, None
    for sample, energy in sampleset.data(["sample", "energy"]):
        assignment = tuple(sample[j] for j in range(N_UNITS))
        if infeasibility_penalty(assignment, demand) > 0:
            continue
        c, p = solve_dispatch(assignment, demand)
        if c < best_cost:
            best_cost, best_assignment, best_dispatch = c, list(assignment), p
    annealing_solved.append({"assignment": best_assignment, "dispatch": best_dispatch, "cost": best_cost})

print(f"  Done in {annealing_time*1000:.1f} ms")
for t, res in enumerate(annealing_solved):
    if res["cost"] == float("inf"):
        print(f"  Period {t}: no feasible assignment found")
    else:
        opt = classical_results[t]["cost"]
        err = abs(res["cost"] - opt) / opt * 100 if opt < float("inf") else float("nan")
        on_count = sum(res["assignment"])
        print(f"  Period {t}: {on_count} units ON, cost={res['cost']:.2f} $/h, error={err:.2f}%")


# ── VQA — stubbed out ─────────────────────────────────────────────────────────
#
# Why VQA is not run here:
#
#   Statevector simulation at 26 qubits requires storing 2^26 = 67 million
#   complex128 amplitudes — approximately 1 GB of memory. Each expectation
#   value evaluation requires a full matrix-vector multiply over that state,
#   making COBYLA with 300+ iterations completely impractical on CPU.
#
# What would be needed to run VQA at this scale:
#
#   Option A — GPU statevector: qiskit-aer with CUDA backend can handle
#              up to ~30 qubits on a modern GPU (e.g. A100). Set
#              CIRCUIT_BACKEND = "local_gpu" in the notebook.
#
#   Option B — Real quantum hardware via qBraid: submit the Butterfly ansatz
#              circuit to IonQ Forte or IBM Heron with shot-based sampling
#              (e.g. 5000 shots per iteration). This is the path to actual
#              quantum advantage experiments in Phase 3.
#
#   Option C — Reduce problem size: reformulate using Bender's decomposition
#              (as discussed in Section 7c) to keep the quantum layer small
#              while pushing the dispatch to a classical inner loop.
#
# The IonQ paper reports ~2.5% mean error on the 26-unit case using IonQ Forte
# hardware with 10 ansatz layers — included in the benchmark table below for
# reference.

IONQ_PAPER_26GEN_ERROR = 0.025  # ~2.5% mean error reported in paper Table VI

vqa_solved = [{"assignment": None, "dispatch": None, "cost": float("inf")} for _ in DEMANDS]
print("\nVQA: skipped at 26 qubits (statevector simulation not feasible on CPU).")
print(f"  IonQ paper reports ~{IONQ_PAPER_26GEN_ERROR*100:.1f}% mean error on this scale (Table VI, IonQ Forte hardware).")


# ── Benchmark summary ─────────────────────────────────────────────────────────

print("\n" + "=" * 75)
print("BENCHMARK RESULTS — 26-Generator UC Problem")
print("=" * 75)

methods        = ["Classical (MIP)", "Annealing", "VQA (paper result)"]
results_by_method = [classical_results, annealing_solved, vqa_solved]
times          = [classical_time, annealing_time, None]

for method, results, elapsed in zip(methods, results_by_method, times):
    elapsed_str = f"{elapsed*1000:.1f} ms" if elapsed is not None else "N/A (hardware run)"
    print(f"\n{method}  (time: {elapsed_str})")
    print(f"  {'Period':<8} {'Demand':>7} {'Cost ($/h)':>14} {'Error %':>10}")
    print("  " + "-" * 44)
    for i, res in enumerate(results):
        opt = classical_results[i]["cost"]
        if res["cost"] == float("inf"):
            # For VQA, show the paper's reported error rate instead
            if method == "VQA (paper result)":
                implied_cost = opt * (1 + IONQ_PAPER_26GEN_ERROR) if opt < float("inf") else float("inf")
                print(f"  {i:<8} {DEMANDS[i]:>7} {'~'+str(round(implied_cost,2)):>14} {IONQ_PAPER_26GEN_ERROR*100:>9.1f}%*")
            else:
                print(f"  {i:<8} {DEMANDS[i]:>7} {'N/A':>14} {'N/A':>10}")
        else:
            err = abs(res["cost"] - opt) / opt * 100 if opt < float("inf") else float("nan")
            print(f"  {i:<8} {DEMANDS[i]:>7} {res['cost']:>14.2f} {err:>9.2f}%")

print("\n* VQA error is the mean error reported in IonQ/ORNL paper Table VI,")
print("  not computed here. Actual per-period costs not available without hardware run.")


# ── Bar chart (classical and annealing only, VQA shown as reference line) ────

fig, axes = plt.subplots(1, N_PERIODS, figsize=(14, 4), sharey=False)
colors = ["#2196F3", "#FF9800"]

for t in range(N_PERIODS):
    ax = axes[t]
    opt = classical_results[t]["cost"]
    ann = annealing_solved[t]["cost"]
    costs = [opt, ann if ann < float("inf") else 0]
    labels = ["Classical\n(MIP)", "Annealing"]

    bars = ax.bar(labels, costs, color=colors, edgecolor="black", linewidth=0.5)
    ax.set_title(f"Period {t}\n(demand={DEMANDS[t]} MW)")
    ax.set_ylabel("Cost ($/h)" if t == 0 else "")

    for bar, c, label in zip(bars, costs, labels):
        if c > 0 and opt > 0:
            err = abs(c - opt) / opt * 100
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + opt * 0.005,
                    f"{err:.1f}%", ha="center", va="bottom", fontsize=8)

    # Reference line for IonQ paper VQA error
    if opt < float("inf"):
        vqa_ref = opt * (1 + IONQ_PAPER_26GEN_ERROR)
        ax.axhline(vqa_ref, color="#4CAF50", linestyle="--", linewidth=1.2,
                   label=f"VQA paper ~{IONQ_PAPER_26GEN_ERROR*100:.0f}% err")
        if t == 0:
            ax.legend(fontsize=7)

fig.suptitle(
    "26-Generator UC Benchmark: Classical MIP vs Annealing\n"
    "(dashed green = IonQ paper VQA result, ~2.5% error, Table VI)",
    fontsize=11
)
plt.tight_layout()
plt.savefig("Assets/26gen_benchmark.png", dpi=150, bbox_inches="tight")
plt.show()
print("\nChart saved to Assets/26gen_benchmark.png")
