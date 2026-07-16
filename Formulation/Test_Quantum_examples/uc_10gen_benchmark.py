"""
10-generator Unit Commitment benchmark.
Runs classical brute force, simulated annealing (QUBO), and VQA (Butterfly ansatz)
on a scaled-up UC problem. Reports cost, approximation error, and runtime per method.
Same metrics and structure as the tutorial notebook, no explanations.
"""

import itertools
import time
import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import minimize
from scipy.special import erf

# ── Generator specifications (10 units) ──────────────────────────────────────
# Parameters follow quadratic cost F_j(p) = a*p^2 + b*p + c
# Units span a range of sizes and efficiencies representative of a mixed fleet
GENERATORS = [
    {"p_min": 100, "p_max": 600, "a": 0.002,  "b": 10.0, "c": 500},  # Unit 0 — large base
    {"p_min": 100, "p_max": 400, "a": 0.0025, "b": 8.0,  "c": 300},  # Unit 1
    {"p_min":  50, "p_max": 200, "a": 0.005,  "b": 6.0,  "c": 100},  # Unit 2 — small peaker
    {"p_min": 150, "p_max": 500, "a": 0.0018, "b": 9.5,  "c": 450},  # Unit 3
    {"p_min":  80, "p_max": 350, "a": 0.003,  "b": 7.5,  "c": 250},  # Unit 4
    {"p_min": 200, "p_max": 700, "a": 0.0015, "b": 11.0, "c": 600},  # Unit 5 — large efficient
    {"p_min":  60, "p_max": 250, "a": 0.004,  "b": 7.0,  "c": 150},  # Unit 6
    {"p_min": 120, "p_max": 450, "a": 0.0022, "b": 9.0,  "c": 380},  # Unit 7
    {"p_min":  50, "p_max": 180, "a": 0.006,  "b": 5.5,  "c":  80},  # Unit 8 — small cheap
    {"p_min": 100, "p_max": 400, "a": 0.0028, "b": 8.5,  "c": 320},  # Unit 9
]

# 4 time periods with varied demand levels
DEMANDS = [400, 1200, 2500, 800]

N_UNITS = len(GENERATORS)
N_PERIODS = len(DEMANDS)

print(f"Problem: {N_UNITS} generators, {N_PERIODS} time periods")
print(f"Demands: {DEMANDS} MW")
print(f"Enumeration space: 2^{N_UNITS} = {2**N_UNITS} assignments per period\n")


# ── Shared utility functions ──────────────────────────────────────────────────

def cost(gen, p):
    return gen["a"] * p**2 + gen["b"] * p + gen["c"]

def c_min(assignment):
    return sum(
        GENERATORS[j]["a"] * GENERATORS[j]["p_min"]**2
        + GENERATORS[j]["b"] * GENERATORS[j]["p_min"]
        + GENERATORS[j]["c"]
        for j, u in enumerate(assignment) if u == 1
    )

def infeasibility_penalty(assignment, demand):
    p_max_total = sum(GENERATORS[j]["p_max"] for j, u in enumerate(assignment) if u == 1)
    shortfall = max(0.0, demand - p_max_total)
    return float(erf(shortfall))

def solve_dispatch(assignment, demand):
    active_idx = [j for j, u in enumerate(assignment) if u == 1]
    if not active_idx:
        return float("inf"), None
    active_gens = [GENERATORS[j] for j in active_idx]
    p_min = [g["p_min"] for g in active_gens]
    p_max = [g["p_max"] for g in active_gens]
    if sum(p_max) < demand:
        return float("inf"), None
    n = len(active_gens)
    result = minimize(
        fun=lambda p: sum(cost(active_gens[i], p[i]) for i in range(n)),
        x0=[demand / n] * n,
        method="SLSQP",
        bounds=list(zip(p_min, p_max)),
        constraints={"type": "eq", "fun": lambda p: sum(p) - demand},
    )
    if not result.success:
        return float("inf"), None
    full_p = [0.0] * N_UNITS
    for i, j in enumerate(active_idx):
        full_p[j] = result.x[i]
    return result.fun, full_p


# ── Classical solver (brute force + SLSQP) ───────────────────────────────────

def classical_solve(demand):
    best_cost, best_assignment, best_dispatch = float("inf"), None, None
    for assignment in itertools.product([0, 1], repeat=N_UNITS):
        c, p = solve_dispatch(assignment, demand)
        if c < best_cost:
            best_cost, best_assignment, best_dispatch = c, list(assignment), p
    return {"assignment": best_assignment, "dispatch": best_dispatch, "cost": best_cost}

print("Running classical solver (brute force over 2^10 assignments)...")
t0 = time.perf_counter()
classical_results = [classical_solve(d) for d in DEMANDS]
classical_time = time.perf_counter() - t0

print(f"  Done in {classical_time*1000:.1f} ms")
for t, res in enumerate(classical_results):
    print(f"  Period {t} (demand={DEMANDS[t]} MW): assignment={res['assignment']}, cost={res['cost']:.2f} $/h")


# ── QUBO / annealing ─────────────────────────────────────────────────────────

import dimod
from dwave.samplers import SimulatedAnnealingSampler

def compute_lambda(demand):
    all_assignments = list(itertools.product([0, 1], repeat=N_UNITS))
    feasible = [a for a in all_assignments if infeasibility_penalty(a, demand) == 0.0]
    if len(feasible) < 2:
        return 10000.0
    c_vals = [c_min(a) for a in feasible]
    return (max(c_vals) - min(c_vals)) * 2

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

print("\nRunning simulated annealing (QUBO, 2000 reads per period)...")
sampler = SimulatedAnnealingSampler()
annealing_results = []
t0 = time.perf_counter()

for t, demand in enumerate(DEMANDS):
    lam = compute_lambda(demand)
    bqm = build_qubo(demand, lam)
    sampleset = sampler.sample(bqm, num_reads=2000)
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
    err = abs(res["cost"] - classical_results[t]["cost"]) / classical_results[t]["cost"] * 100
    print(f"  Period {t}: assignment={res['assignment']}, cost={res['cost']:.2f} $/h, error={err:.2f}%")


# ── VQA (Butterfly ansatz + COBYLA) ──────────────────────────────────────────

from qiskit import QuantumCircuit
from qiskit.circuit import ParameterVector
from qiskit.quantum_info import SparsePauliOp, Statevector
from scipy.optimize import minimize as scipy_minimize

N_LAYERS = 3  # more layers needed for 10-qubit problem

def build_butterfly_ansatz(n_qubits, n_layers):
    gamma = ParameterVector("γ", n_layers * n_qubits)
    beta  = ParameterVector("β", n_layers * n_qubits)
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

def qubo_to_hamiltonian(bqm, n_qubits):
    pauli_list, coeffs = [], []
    offset = bqm.offset
    for j, h in bqm.linear.items():
        z_str = ["I"] * n_qubits
        z_str[j] = "Z"
        pauli_list.append("".join(reversed(z_str)))
        coeffs.append(-h / 2)
        offset += h / 2
    for (i, j), J in bqm.quadratic.items():
        zz_str = ["I"] * n_qubits; zz_str[i] = "Z"; zz_str[j] = "Z"
        pauli_list.append("".join(reversed(zz_str))); coeffs.append(J / 4)
        zi_str = ["I"] * n_qubits; zi_str[i] = "Z"
        pauli_list.append("".join(reversed(zi_str))); coeffs.append(-J / 4)
        zj_str = ["I"] * n_qubits; zj_str[j] = "Z"
        pauli_list.append("".join(reversed(zj_str))); coeffs.append(-J / 4)
        offset += J / 4
    return SparsePauliOp(pauli_list, coeffs=coeffs).simplify(), offset

def vqa_objective(theta, ansatz, hamiltonian):
    bound = ansatz.assign_parameters(dict(zip(ansatz.parameters, theta)))
    sv = Statevector(bound)
    return sv.expectation_value(hamiltonian).real

print(f"\nRunning VQA (Butterfly ansatz, {N_LAYERS} layers, COBYLA, max 300 iter per period)...")
vqa_solved = []
t0 = time.perf_counter()

for t, demand in enumerate(DEMANDS):
    lam = compute_lambda(demand)
    bqm = build_qubo(demand, lam)
    H, _ = qubo_to_hamiltonian(bqm, N_UNITS)
    ansatz, _ = build_butterfly_ansatz(N_UNITS, N_LAYERS)
    ansatz_no_meas = ansatz.remove_final_measurements(inplace=False)

    result = scipy_minimize(
        fun=lambda th: vqa_objective(th, ansatz_no_meas, H),
        x0=np.zeros(len(ansatz_no_meas.parameters)),
        method="COBYLA",
        options={"maxiter": 300, "rhobeg": 1.0},
    )

    sv = Statevector(ansatz_no_meas.assign_parameters(
        dict(zip(ansatz_no_meas.parameters, result.x))
    ))
    probs = sv.probabilities_dict()

    best_cost, best_assignment, best_dispatch = float("inf"), None, None
    for bitstring, prob in sorted(probs.items(), key=lambda x: -x[1])[:30]:
        assignment = tuple(int(b) for b in reversed(bitstring))
        if infeasibility_penalty(assignment, demand) > 0:
            continue
        c, p = solve_dispatch(assignment, demand)
        if c < best_cost:
            best_cost, best_assignment, best_dispatch = c, list(assignment), p

    vqa_solved.append({"assignment": best_assignment, "dispatch": best_dispatch, "cost": best_cost})
    print(f"  Period {t}: {result.nfev} evaluations, cost={best_cost:.2f} $/h")

vqa_time = time.perf_counter() - t0


# ── Benchmark summary ─────────────────────────────────────────────────────────

print("\n" + "=" * 75)
print("BENCHMARK RESULTS — 10-Generator UC Problem")
print("=" * 75)

methods = ["Classical", "Annealing", "VQA"]
results_by_method = [classical_results, annealing_solved, vqa_solved]
times = [classical_time, annealing_time, vqa_time]

for method, results, elapsed in zip(methods, results_by_method, times):
    print(f"\n{method}  (total time: {elapsed*1000:.1f} ms)")
    print(f"  {'Period':<8} {'Demand':>7} {'Cost ($/h)':>12} {'Error %':>10}")
    print("  " + "-" * 40)
    for i, res in enumerate(results):
        opt = classical_results[i]["cost"]
        if res["cost"] == float("inf"):
            print(f"  {i:<8} {DEMANDS[i]:>7} {'N/A':>12} {'N/A':>10}")
        else:
            err = abs(res["cost"] - opt) / opt * 100
            print(f"  {i:<8} {DEMANDS[i]:>7} {res['cost']:>12.2f} {err:>9.2f}%")

# ── Bar chart ─────────────────────────────────────────────────────────────────

fig, axes = plt.subplots(1, N_PERIODS, figsize=(14, 4), sharey=False)
colors = ["#2196F3", "#FF9800", "#4CAF50"]

for t in range(N_PERIODS):
    ax = axes[t]
    costs = [results_by_method[m][t]["cost"] for m in range(len(methods))]
    bars = ax.bar(methods, costs, color=colors, edgecolor="black", linewidth=0.5)
    ax.set_title(f"Period {t}\n(demand={DEMANDS[t]} MW)")
    ax.set_ylabel("Cost ($/h)" if t == 0 else "")
    ax.set_xticklabels(methods, rotation=15, ha="right")
    for bar, c in zip(bars, costs):
        if c != float("inf"):
            opt = classical_results[t]["cost"]
            err = abs(c - opt) / opt * 100
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + opt * 0.005,
                    f"{err:.1f}%", ha="center", va="bottom", fontsize=8)

fig.suptitle("10-Generator UC Benchmark: Cost by Method and Period\n(% = approximation error vs classical)", fontsize=11)
plt.tight_layout()
plt.savefig("Assets/10gen_benchmark.png", dpi=150, bbox_inches="tight")
plt.show()
print("\nChart saved to Assets/10gen_benchmark.png")
