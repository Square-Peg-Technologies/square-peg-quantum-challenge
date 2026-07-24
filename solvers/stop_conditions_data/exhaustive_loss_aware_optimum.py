"""
Exhaustive loss-aware placement search: batch-evaluate ALL C(14,4)=1001
possible 4-battery placements with line_losses=True in parallel (each via an
exact UC solve), not just the ~760 placements sampled from VQA shot
distributions. Since this covers the entire search space and each placement's
cost is an exact UC solve, the resulting best-found cost is a proven global
optimum for the loss-aware objective (unlike the sample-derived reference
used so far), analogous in rigor to siting_mip.py's proven lossless optimum.
"""
import itertools
import json
import os
import pickle
import sys
import time

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)
os.chdir(REPO)
DATA_DIR = os.path.dirname(os.path.abspath(__file__))

_real_cpu_count = os.cpu_count() or 1
_capped_cpu_count = max(1, _real_cpu_count // 2)
os.cpu_count = lambda: _capped_cpu_count
print(f"Capping worker pool at {_capped_cpu_count} (half of {_real_cpu_count} cores)")


def main():
    import main as cli
    from solvers.quantum_siting import evaluate_candidates

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

    all_placements = list(itertools.combinations(range(1, n_buses + 1), B))
    print(f"Enumerating all {len(all_placements)} possible {B}-battery placements "
          f"out of {n_buses} buses")

    def placement_to_s_bits(placed_buses):
        return "".join("1" if (i + 1) in placed_buses else "0" for i in range(n_buses))

    fake_candidates = [("1" * G, placement_to_s_bits(p), 0.0) for p in all_placements]

    print("Batch-evaluating ALL placements with line_losses=True (parallel)...")
    t0 = time.perf_counter()
    evaluated = evaluate_candidates(fake_candidates, grid, generators, batteries, T, "uc",
                                    line_losses=True)
    elapsed = time.perf_counter() - t0
    cache = {tuple(bat_locs.values()): true_cost for bat_locs, commitment, true_cost, _ in evaluated}
    print(f"{len(cache)}/{len(all_placements)} placements evaluated successfully in {elapsed:.1f}s")

    true_optimum = min(cache.values())
    best_placement = min(cache, key=cache.get)
    print(f"Proven loss-aware global optimum: {true_optimum:.2f} at placement {best_placement}")

    with open(os.path.join(DATA_DIR, "exhaustive_loss_aware_cache.pkl"), "wb") as f:
        pickle.dump(cache, f)
    print(f"Saved full {len(cache)}-placement cache to exhaustive_loss_aware_cache.pkl")

    with open(os.path.join(DATA_DIR, "exhaustive_loss_aware_optimum.json"), "w") as f:
        json.dump({
            "true_optimum": true_optimum,
            "best_placement": list(best_placement),
            "n_placements_total": len(all_placements),
            "n_placements_evaluated": len(cache),
            "elapsed_seconds": elapsed,
        }, f, indent=2)
    print("Saved exhaustive_loss_aware_optimum.json")


if __name__ == "__main__":
    main()
