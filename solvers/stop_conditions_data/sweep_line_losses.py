"""
Shots-vs-optimality-gap sweep WITH line_losses=True, reusing the noisy
10k-shot sample already saved from the bug-verification run
(verify_cache_noisy.pkl) — no retraining, no new qBraid job. Now that
_GridData carries R/Sbase (solvers/siting_benders.py fix) and
evaluate_candidates accepts line_losses=True (solvers/quantum_siting.py
fix), the loss-aware cache can be batch-precomputed in parallel instead of
the ~9s/placement sequential path used for the earlier 100-placement
spot-check.
"""
import json
import os
import pickle
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRATCH = os.path.join(REPO, "solvers", "stop_conditions_data")
sys.path.insert(0, REPO)
os.chdir(REPO)

import numpy as np

# Cap the evaluate_candidates worker pool at half the machine's cores — a
# full-core ProcessPoolExecutor run of the 496-placement batch was running
# too hot. evaluate_candidates sizes its pool from os.cpu_count(), so
# monkeypatching it here (before importing quantum_siting) is the least
# invasive way to halve it without changing the shared production function's
# default (full-core) behavior for real dashboard runs.
_real_cpu_count = os.cpu_count() or 1
_capped_cpu_count = max(1, _real_cpu_count // 2)
os.cpu_count = lambda: _capped_cpu_count
print(f"Capping worker pool at {_capped_cpu_count} (half of {_real_cpu_count} cores)")

N_CANDIDATES = 10
SHOT_LEVELS = [25, 50, 75, 100, 150, 200, 250, 300, 400, 500]
N_TRIALS = 400


def main():
    import main as cli
    from solvers.quantum_siting import build_proxy_cost_fn, compute_congestion_signal, \
        _compute_shadow_prices, evaluate_candidates

    with open(os.path.join(SCRATCH, "verify_cache_noisy.pkl"), "rb") as f:
        saved = pickle.load(f)
    counts_noisy = saved["counts_noisy"]
    print(f"Loaded noisy sample: {sum(counts_noisy.values())} total shots, "
          f"{len(counts_noisy)} unique bitstrings")

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

    # Persist the placement->loss-aware-cost cache to disk so re-running the
    # bootstrap/metrics step (e.g. to add a new metric) never has to redo the
    # ~496-placement parallel evaluate_candidates batch.
    CACHE_PATH = os.path.join(SCRATCH, "line_losses_cost_cache.pkl")
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, "rb") as f:
            cache = pickle.load(f)
        print(f"Loaded cached {len(cache)} placement costs from {CACHE_PATH} (skipping re-evaluation)")
    else:
        # Extract unique weight-B placements from the saved noisy sample
        unique_bat_locs = {}
        for bs in counts_noisy:
            bs_ordered = bs[::-1]
            s_bits = bs_ordered[G:]
            if sum(int(b) for b in s_bits) != B:
                continue
            placed = tuple(i + 1 for i, b in enumerate(s_bits) if b == "1")
            unique_bat_locs[placed] = s_bits
        print(f"{len(unique_bat_locs)} unique weight-{B} placements to batch-evaluate WITH line losses")

        fake_candidates = [("1" * G, s_bits, 0.0) for s_bits in unique_bat_locs.values()]
        print("Batch-evaluating with line_losses=True (now parallel)...")
        evaluated = evaluate_candidates(fake_candidates, grid, generators, batteries, T, "uc",
                                        line_losses=True)
        cache = {tuple(bat_locs.values()): true_cost for bat_locs, commitment, true_cost, _ in evaluated}
        print(f"{len(cache)} placements evaluated successfully")
        with open(CACHE_PATH, "wb") as f:
            pickle.dump(cache, f)
        print(f"Saved cost cache to {CACHE_PATH}")

    true_optimum = min(cache.values())
    print(f"Best (loss-aware) cost found among sampled placements: {true_optimum:.2f} "
          f"(not necessarily proven global optimum — best found among {len(cache)} sampled "
          f"placements out of {__import__('math').comb(n_buses, B)} possible)")

    bs_list = list(counts_noisy.keys())
    cnt_list = np.array([counts_noisy[b] for b in bs_list], dtype=float)
    probs = cnt_list / cnt_list.sum()
    rng = np.random.default_rng(42)

    # A trial "succeeds" if its best feasible candidate matches the true
    # optimum (within float tolerance) — a stricter, standard VQA metric
    # distinct from optimality gap (how close) and feasibility (any valid
    # candidate at all).
    SUCCESS_TOL = 1e-6

    rows = []
    for N in SHOT_LEVELS:
        feasible_flags = []
        success_flags = []
        gaps = []
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

        feas_rate = float(np.mean(feasible_flags))
        success_rate = float(np.mean(success_flags))
        median_gap = float(np.median(gaps)) if gaps else None
        p95_gap = float(np.percentile(gaps, 95)) if gaps else None
        rows.append({"shots": N, "feasibility_rate": feas_rate,
                     "success_rate": success_rate,
                     "median_gap": median_gap, "p95_gap": p95_gap,
                     "n_feasible_trials": len(gaps)})
        print(f"  shots={N:4d}  feas_rate={feas_rate:.3f}  success_rate={success_rate:.3f}  "
              f"median_gap={median_gap}  p95_gap={p95_gap}")

    out = {"noisy_line_losses": rows, "true_optimum": true_optimum,
           "n_trials": N_TRIALS, "n_placements_evaluated": len(cache)}
    out_path = os.path.join(SCRATCH, "sweep_results_line_losses.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
