"""
Final noiseless-vs-noisy sweep, WITH line losses, against the PROVEN exhaustive
loss-aware optimum (exhaustive_loss_aware_cache.pkl, all 1001 placements,
each an exact UC solve) rather than a sample-derived best-found estimate.
Retrains once locally (deterministic statevector COBYLA, same settings as the
run that produced counts_noisy) to get a matched noiseless 10k-shot sample,
and persists it to disk this time.
"""
import json
import os
import pickle
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)
os.chdir(REPO)
DATA_DIR = os.path.dirname(os.path.abspath(__file__))

import numpy as np

N_CANDIDATES = 10
SHOT_LEVELS = [25, 50, 75, 100, 150, 200, 250, 300, 400, 500]
N_TRIALS = 400
SUCCESS_TOL = 1e-6
N_NOISELESS_SAMPLE_SHOTS = 10000


def bootstrap_sweep(counts, cache, proxy_fn, true_optimum, G, B, rng):
    bs_list = list(counts.keys())
    cnt_list = np.array([counts[b] for b in bs_list], dtype=float)
    probs = cnt_list / cnt_list.sum()

    rows = []
    for N in SHOT_LEVELS:
        feasible_flags, success_flags, gaps = [], [], []
        for _trial in range(N_TRIALS):
            draw_idx = rng.choice(len(bs_list), size=N, p=probs, replace=True)
            unique_bs = set(bs_list[i] for i in draw_idx)

            cand = []
            for bs in unique_bs:
                bs_ordered = bs[::-1]
                u_bits = bs_ordered[:G]
                if all(c == "0" for c in u_bits):
                    continue
                s_bits = bs_ordered[G:]
                cost = proxy_fn(bs_ordered)
                cand.append((u_bits, s_bits, cost))
            cand.sort(key=lambda x: x[2])
            top = cand[:N_CANDIDATES]

            feasible_top = [c for c in top if sum(int(b) for b in c[1]) == B]
            final_set = feasible_top if feasible_top else top

            valid_costs = []
            for u_bits, s_bits, _pc in final_set:
                if sum(int(b) for b in s_bits) != B:
                    continue
                placed = tuple(i + 1 for i, b in enumerate(s_bits) if b == "1")
                if placed in cache:
                    valid_costs.append(cache[placed])

            if valid_costs:
                best = min(valid_costs)
                feasible_flags.append(True)
                success_flags.append(bool(best - true_optimum < SUCCESS_TOL))
                gaps.append((best - true_optimum) / true_optimum)
            else:
                feasible_flags.append(False)
                success_flags.append(False)

        rows.append({
            "shots": N,
            "feasibility_rate": float(np.mean(feasible_flags)),
            "success_rate": float(np.mean(success_flags)),
            "median_gap": float(np.median(gaps)) if gaps else None,
            "p95_gap": float(np.percentile(gaps, 95)) if gaps else None,
        })
    return rows


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

    noiseless_path = os.path.join(DATA_DIR, "counts_noiseless.pkl")
    if os.path.exists(noiseless_path):
        with open(noiseless_path, "rb") as f:
            counts_noiseless = pickle.load(f)
        print(f"Loaded cached noiseless sample: {sum(counts_noiseless.values())} shots, "
              f"{len(counts_noiseless)} unique bitstrings")
    else:
        print("Retraining locally (deterministic statevector COBYLA, same settings "
              "as the run that produced counts_noisy)...")
        candidates, convergence_trace, quantum_meta = run_vqa_qiskit(
            n_qubits_gen=G, n_qubits_bat=n_buses, proxy_fn=proxy_fn,
            n_candidates=10, n_layers=3, warm_start="zeros",
            track_convergence=True, final_backend="local",
        )
        final_qc = quantum_meta["final_qc"]

        from qiskit_aer.primitives import SamplerV2 as AerSamplerV2
        sampler = AerSamplerV2()
        sampler.options.backend_options = {"method": "statevector", "device": "CPU"}
        job = sampler.run([final_qc], shots=N_NOISELESS_SAMPLE_SHOTS)
        counts_noiseless = dict(job.result()[0].data.meas.get_counts())
        with open(noiseless_path, "wb") as f:
            pickle.dump(counts_noiseless, f)
        print(f"Drew and saved {sum(counts_noiseless.values())} noiseless shots, "
              f"{len(counts_noiseless)} unique bitstrings")

    with open(os.path.join(DATA_DIR, "verify_cache_noisy.pkl"), "rb") as f:
        noisy_saved = pickle.load(f)
    counts_noisy = noisy_saved["counts_noisy"]

    with open(os.path.join(DATA_DIR, "exhaustive_loss_aware_cache.pkl"), "rb") as f:
        cache = pickle.load(f)
    print(f"Loaded exhaustive cache: {len(cache)} placements (proven optimum)")

    true_optimum = min(cache.values())
    best_placement = min(cache, key=cache.get)
    print(f"Proven true_optimum = {true_optimum:.2f} at {best_placement}")

    rng_noisy = np.random.default_rng(42)
    rng_noiseless = np.random.default_rng(42)
    rows_noisy = bootstrap_sweep(counts_noisy, cache, proxy_fn, true_optimum, G, B, rng_noisy)
    rows_noiseless = bootstrap_sweep(counts_noiseless, cache, proxy_fn, true_optimum, G, B, rng_noiseless)

    print("\n| Shots | Feas (noiseless) | Feas (noisy) | Success (noiseless) | Success (noisy) | "
          "Median gap (noiseless) | Median gap (noisy) | P95 gap (noiseless) | P95 gap (noisy) |")
    print("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for rn, rz in zip(rows_noiseless, rows_noisy):
        print(f"| {rn['shots']} | {rn['feasibility_rate']:.1%} | {rz['feasibility_rate']:.1%} | "
              f"{rn['success_rate']:.1%} | {rz['success_rate']:.1%} | "
              f"{rn['median_gap']*100:.4f}% | {rz['median_gap']*100:.4f}% | "
              f"{rn['p95_gap']*100:.4f}% | {rz['p95_gap']*100:.4f}% |")

    out = {
        "noiseless_line_losses": rows_noiseless,
        "noisy_line_losses": rows_noisy,
        "true_optimum": true_optimum,
        "true_optimum_is_proven": True,
        "best_placement": list(best_placement),
        "n_trials": N_TRIALS,
        "n_placements_evaluated": len(cache),
    }
    out_path = os.path.join(DATA_DIR, "sweep_results_noiseless_vs_noisy.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
