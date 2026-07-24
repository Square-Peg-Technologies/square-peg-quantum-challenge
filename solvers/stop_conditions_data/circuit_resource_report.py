"""
Circuit-depth / gate-count resource report for the writeup's third-metric
category. Trains locally (noiseless Aer statevector sampler, no qBraid job,
no line_losses — evaluate_candidates/line_losses is never invoked by
run_vqa_qiskit, which is called directly here) to get quantum_meta["final_qc"],
then reports depth and gate counts on the actual trained circuit.
"""
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)
os.chdir(REPO)

import numpy as np


def main():
    import main as cli
    from solvers.quantum_siting import (
        build_proxy_cost_fn, compute_congestion_signal, _compute_shadow_prices,
        run_vqa_qiskit,
    )

    use_case = "ieee14"
    assets_file = "4batt_dcbus4_g2out.py"
    use_case_path = os.path.join(REPO, "use_cases", use_case)
    assets_path = os.path.join(use_case_path, assets_file)
    _, grid_mod, assets_mod, loc_mod = cli.load_modules(use_case, use_case_path, assets_path)
    grid = grid_mod.Case()

    dc_bus = getattr(assets_mod, "DATACENTER_BUS", None)
    dc_mw = float(getattr(assets_mod, "DATACENTER_MW", 0))
    if dc_bus is not None and dc_mw:
        grid.power_demand[dc_bus - 1, :] += dc_mw

    generators = assets_mod.GENERATORS
    batteries = assets_mod.BATTERIES
    T = 24
    G = len(generators)
    B = len(batteries)
    n_buses = grid.power_demand.shape[0]

    demand = np.array(grid.power_demand)
    demand_ref = float(np.nanmax(demand.sum(axis=0)))
    ptdf = np.array(grid.PTDF)
    shadow_prices = _compute_shadow_prices(grid, generators, T)
    p_bat = batteries[0]["power_mw"]
    congestion_signal = compute_congestion_signal(ptdf, shadow_prices, p_bat)
    proxy_fn, _, _ = build_proxy_cost_fn(generators, batteries, n_buses, demand_ref, T,
                                        congestion_signal=congestion_signal)

    print("Training locally (noiseless, no line losses, no qBraid job)...")
    candidates, convergence_trace, quantum_meta = run_vqa_qiskit(
        n_qubits_gen=G, n_qubits_bat=n_buses, proxy_fn=proxy_fn,
        n_candidates=10, n_layers=3, warm_start="zeros",
        track_convergence=True, final_backend="local",
    )

    qc = quantum_meta["final_qc"]
    ops = qc.count_ops()
    two_q_gates = {k: v for k, v in ops.items() if k in ("rzx", "cx", "cz", "rxx", "ryy")}
    n_two_q = sum(two_q_gates.values())
    n_total = sum(v for k, v in ops.items() if k != "measure" and k != "barrier")

    print(f"\nn_qubits = {quantum_meta['n_qubits']}")
    print(f"n_params = {quantum_meta['n_params']}")
    print(f"circuit depth (abstract, Qiskit-native gates) = {qc.depth()}")
    print(f"gate counts: {dict(ops)}")
    print(f"total non-measurement gates = {n_total}")
    print(f"two-qubit (entangling) gates = {n_two_q} ({two_q_gates})")

    # Transpile to a standard 2-qubit basis for a hardware-comparable depth
    # (approximates what a real IonQ compile pass would produce; qBraid does
    # its own device-specific transpilation server-side, so this is an
    # estimate, not the exact submitted circuit).
    from qiskit import transpile
    qc_t = transpile(qc, basis_gates=["rz", "ry", "rx", "rxx"], optimization_level=1)
    ops_t = qc_t.count_ops()
    n_two_q_t = ops_t.get("rxx", 0)
    n_total_t = sum(v for k, v in ops_t.items() if k not in ("measure", "barrier"))
    print(f"\nTranspiled (rz/ry/rx/rxx basis, opt_level=1):")
    print(f"  depth = {qc_t.depth()}")
    print(f"  gate counts: {dict(ops_t)}")
    print(f"  total gates = {n_total_t}, two-qubit (rxx) gates = {n_two_q_t}")


if __name__ == "__main__":
    main()
