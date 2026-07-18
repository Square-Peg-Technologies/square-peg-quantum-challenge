"""
Warm-start strategy comparison for quantum siting VQA.

Runs all three paper-faithful warm-start strategies (arXiv:2505.00145) across every
available use case and reports convergence and solution quality side by side.

Usage:
    python warm_start_comparison.py [--trials N] [--n-candidates K] [--T H]

Strategies compared:
    zeros  — theta=0, paper simulation default (Section IV-A)
    random — theta~Uniform[-2pi,2pi], paper IonQ hardware default (Fig. 6/8)
    sdp    — LP-relaxation warm start, paper Section III mixer design
"""

import argparse
import importlib.util
import json
import os
import sys
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# Path setup — allow running from this directory or from the project root
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from solvers.quantum_siting import run_vqa_qiskit, build_proxy_cost_fn, _solve_lp_relaxation
from solvers.siting_mip import run_siting_mip


STRATEGIES = ["zeros", "random", "sdp"]


# ---------------------------------------------------------------------------
# Use-case discovery
# ---------------------------------------------------------------------------

def _discover_use_cases() -> list[tuple[str, str]]:
    """Return list of (name, path) for all use_cases/ subdirectories."""
    base = os.path.join(_PROJECT_ROOT, "use_cases")
    if not os.path.isdir(base):
        raise FileNotFoundError(f"use_cases/ directory not found at {base}")
    cases = sorted(
        d for d in os.listdir(base)
        if os.path.isdir(os.path.join(base, d)) and not d.startswith("_")
    )
    return [(name, os.path.join(base, name)) for name in cases]


def _load_use_case(name: str, path: str):
    """Load grid, assets, and locations modules from a use-case folder.

    Returns (grid, generators, batteries, gen_locs, bat_locs).
    """
    def _load_mod(mod_name: str, fpath: str):
        # Add use-case path so intra-package imports (e.g. *_dcbus*.py) work
        if path not in sys.path:
            sys.path.insert(0, path)
        spec = importlib.util.spec_from_file_location(mod_name, fpath)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    grid_mod = _load_mod(name, os.path.join(path, f"{name}.py"))
    # Use the base *batt*.py file (no datacenter variant) for the comparison —
    # the one without "dcbus" in its name, e.g. 4batt.py, 2batt.py, nobatt.py.
    import glob as _glob
    candidates = sorted(
        p for p in _glob.glob(os.path.join(path, "*batt*.py"))
        if "dcbus" not in os.path.basename(p)
    )
    if not candidates:
        raise FileNotFoundError(f"No *batt*.py in {path}")
    assets_file = candidates[0]
    assets_mod = _load_mod("assets", assets_file)
    loc_mod = _load_mod("locations", os.path.join(path, "locations.py"))

    grid = grid_mod.Case()   # same pattern as main.py line 423
    generators = assets_mod.GENERATORS
    batteries = assets_mod.BATTERIES
    gen_locs = loc_mod.GENERATOR_LOCATIONS
    bat_locs = getattr(loc_mod, "BATTERY_LOCATIONS", {})
    return grid, generators, batteries, gen_locs, bat_locs


# ---------------------------------------------------------------------------
# Single-trial VQA run with convergence trace
# ---------------------------------------------------------------------------

def _run_one_trial(
    n_qubits_gen: int,
    n_qubits_bat: int,
    proxy_fn,
    n_candidates: int,
    warm_start: str,
    sdp_ingredients: dict | None,
) -> dict:
    """Run one VQA trial. Returns dict with candidates, convergence_trace, wall_time."""
    t0 = time.perf_counter()
    candidates, trace = run_vqa_qiskit(
        n_qubits_gen=n_qubits_gen,
        n_qubits_bat=n_qubits_bat,
        proxy_fn=proxy_fn,
        n_candidates=n_candidates,
        warm_start=warm_start,
        track_convergence=True,
        _sdp_ingredients=sdp_ingredients if warm_start == "sdp" else None,
    )
    wall_time = time.perf_counter() - t0
    best_proxy = min((c for _, _, c in candidates), default=float("inf"))
    return {
        "candidates": candidates,
        "convergence_trace": trace,
        "best_proxy": best_proxy,
        "wall_time": wall_time,
        "nfev": len(trace),
        "final_obj": trace[-1] if trace else float("nan"),
    }


# ---------------------------------------------------------------------------
# Classical baseline
# ---------------------------------------------------------------------------

def _classical_baseline(grid, generators: list, batteries: list, T: int) -> float:
    """Run siting MIP and return the best true cost."""
    try:
        result = run_siting_mip(grid, generators, batteries, T, time_limit_s=60.0)
        return result.total_cost
    except Exception as exc:
        print(f"    [classical baseline failed: {exc}]")
    return float("nan")


# ---------------------------------------------------------------------------
# Main comparison loop
# ---------------------------------------------------------------------------

def run_comparison(
    trials: int,
    n_candidates: int,
    T: int,
    output_dir: str,
    only_use_case: str | None = None,
    only_strategies: list[str] | None = None,
) -> None:
    os.makedirs(output_dir, exist_ok=True)
    use_cases = _discover_use_cases()
    if only_use_case:
        use_cases = [(n, p) for n, p in use_cases if n == only_use_case]
        if not use_cases:
            print(f"Use case '{only_use_case}' not found. Available: {[n for n, _ in _discover_use_cases()]}")
            return
    strategies = only_strategies if only_strategies else STRATEGIES
    print(f"Use cases: {[n for n, _ in use_cases]}  |  Strategies: {strategies}\n")

    for uc_name, uc_path in use_cases:
        print(f"{'=' * 60}")
        print(f"Use case: {uc_name}")
        print(f"{'=' * 60}")

        try:
            grid, generators, batteries, gen_locs, bat_locs = _load_use_case(uc_name, uc_path)
        except Exception as exc:
            print(f"  [SKIP — failed to load: {exc}]\n")
            continue

        import numpy as _np
        demand = _np.array(grid.power_demand)
        demand_ref = float(_np.nanmax(demand.sum(axis=0)))
        n_buses = demand.shape[0]
        G = len(generators)
        B = len(batteries)
        n_qubits = G + n_buses

        print(f"  {G} generators + {n_buses} buses = {n_qubits} qubits,  B={B} batteries,  T={T}h")

        proxy_fn, _lam1, _lam2 = build_proxy_cost_fn(
            generators, batteries, n_buses, demand_ref, T
        )

        sdp_ingredients = {
            "generators": generators,
            "batteries": batteries,
            "demand_ref": demand_ref,
            "T": T,
        }

        print(f"\n  Computing classical baseline (siting MIP)...")
        classical_cost = _classical_baseline(grid, generators, batteries, T)
        if _np.isfinite(classical_cost):
            print(f"  Classical optimum: ${classical_cost:,.0f}")
        else:
            print("  Classical optimum: unavailable")

        # Compute LP relaxation proxy cost as a reference lower bound
        x_star = _solve_lp_relaxation(generators, batteries, n_buses, demand_ref, T)
        lp_obj = proxy_fn("".join("1" if v > 0.5 else "0" for v in x_star))
        print(f"  LP relaxation rounded proxy: {lp_obj:.4g}")

        results_by_strategy: dict[str, list[dict]] = {}

        for strategy in strategies:
            print(f"\n  Strategy: {strategy}  ({trials} trial(s))")
            trial_results = []
            for trial_idx in range(trials):
                print(f"    Trial {trial_idx + 1}/{trials}...", end=" ", flush=True)
                try:
                    r = _run_one_trial(
                        n_qubits_gen=G,
                        n_qubits_bat=n_buses,
                        proxy_fn=proxy_fn,
                        n_candidates=n_candidates,
                        warm_start=strategy,
                        sdp_ingredients=sdp_ingredients,
                    )
                    trial_results.append(r)
                    adaptive_max = max(150, 6 * 2 * 3 * n_qubits)
                    status = "converged" if r['nfev'] < adaptive_max else "maxiter"
                    print(f"nfev={r['nfev']}  best_proxy={r['best_proxy']:.4g}  t={r['wall_time']:.1f}s  [{status}]")
                except Exception as exc:
                    print(f"FAILED: {exc}")
            results_by_strategy[strategy] = trial_results

            # Save per-strategy data so future runs can merge without re-running
            if trial_results:
                data_path = os.path.join(output_dir, f"warm_start_{uc_name}_{strategy}.json")
                payload = {
                    "use_case": uc_name,
                    "strategy": strategy,
                    "n_qubits": n_qubits,
                    "trials": [
                        {
                            "convergence_trace": r["convergence_trace"],
                            "best_proxy": r["best_proxy"],
                            "final_obj": r["final_obj"],
                            "nfev": r["nfev"],
                            "wall_time": r["wall_time"],
                        }
                        for r in trial_results
                    ],
                }
                with open(data_path, "w") as f:
                    json.dump(payload, f)
                print(f"    Data saved: {data_path}")

        # ── Load any previously saved strategies not in this run ────────────
        for s in STRATEGIES:
            if s not in results_by_strategy or not results_by_strategy[s]:
                data_path = os.path.join(output_dir, f"warm_start_{uc_name}_{s}.json")
                if os.path.exists(data_path):
                    with open(data_path) as f:
                        saved = json.load(f)
                    results_by_strategy[s] = saved["trials"]
                    print(f"  Loaded previous data for strategy '{s}' ({len(saved['trials'])} trial(s))")

        # ── Print summary table ──────────────────────────────────────────────
        all_strategies = [s for s in STRATEGIES if results_by_strategy.get(s)]
        print(f"\n  Summary — {uc_name}")
        hdr = f"  {'Strategy':<10} | {'Final obj (mean±σ)':>22} | {'nfev (mean)':>12} | {'Best proxy (mean)':>18} | {'Gap vs classical':>17} | {'Time (mean)':>12}"
        print(hdr)
        print("  " + "-" * (len(hdr) - 2))

        for strategy in all_strategies:
            trials_data = results_by_strategy[strategy]
            if not trials_data:
                print(f"  {strategy:<10} | {'N/A':>22} | {'N/A':>12} | {'N/A':>18} | {'N/A':>17} | {'N/A':>12}")
                continue
            final_objs = _np.array([r["final_obj"] for r in trials_data])
            nfevs = _np.array([r["nfev"] for r in trials_data])
            best_proxies = _np.array([r["best_proxy"] for r in trials_data])
            times = _np.array([r["wall_time"] for r in trials_data])
            gap = (best_proxies.mean() / classical_cost - 1.0) * 100.0 if _np.isfinite(classical_cost) else float("nan")

            obj_str = f"{final_objs.mean():.4g} ± {final_objs.std():.3g}"
            gap_str = f"{gap:.2f}%" if _np.isfinite(gap) else "N/A"
            print(
                f"  {strategy:<10} | {obj_str:>22} | {nfevs.mean():>12.1f} | "
                f"{best_proxies.mean():>18.4g} | {gap_str:>17} | {times.mean():>10.1f}s"
            )

        # ── Convergence plot — merges all available strategies ───────────────
        fig, ax = plt.subplots(figsize=(9, 5))
        colors = {"zeros": "#1f77b4", "random": "#ff7f0e", "sdp": "#2ca02c"}

        for strategy in all_strategies:
            trials_data = results_by_strategy[strategy]
            traces = [r["convergence_trace"] for r in trials_data if r.get("convergence_trace")]
            if not traces:
                continue
            max_len = max(len(t) for t in traces)
            padded = _np.array([
                t + [t[-1]] * (max_len - len(t)) for t in traces
            ])
            mean = padded.mean(axis=0)
            std = padded.std(axis=0)
            iters = _np.arange(1, max_len + 1)
            ax.plot(iters, mean, label=strategy, color=colors.get(strategy, None), linewidth=1.8)
            ax.fill_between(iters, mean - std, mean + std, alpha=0.2, color=colors.get(strategy, None))

        ax.set_xlabel("COBYLA function evaluation")
        ax.set_ylabel("Proxy objective Q(θ)")
        ax.set_title(f"VQA convergence by warm-start strategy — {uc_name} ({n_qubits} qubits)")
        ax.legend()
        ax.grid(True, alpha=0.3)
        fig.tight_layout()

        plot_path = os.path.join(output_dir, f"warm_start_{uc_name}.png")
        fig.savefig(plot_path, dpi=150)
        plt.close(fig)
        print(f"\n  Convergence plot saved: {plot_path}")
        print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Warm-start strategy comparison")
    parser.add_argument("--trials", type=int, default=3, help="Trials per strategy (default: 3)")
    parser.add_argument("--n-candidates", type=int, default=10, help="Candidates to extract (default: 10)")
    parser.add_argument("--T", type=int, default=4, help="Horizon in hours (default: 4)")
    parser.add_argument("--use-case", type=str, default=None, help="Run only this use case (e.g. pjm5)")
    parser.add_argument("--strategies", type=str, default=None, help="Comma-separated strategies to run (e.g. sdp or zeros,sdp)")
    args = parser.parse_args()

    output_dir = os.path.join(_PROJECT_ROOT, "outputs")
    run_comparison(
        trials=args.trials,
        n_candidates=args.n_candidates,
        T=args.T,
        output_dir=output_dir,
        only_use_case=args.use_case,
        only_strategies=[s.strip() for s in args.strategies.split(",")] if args.strategies else None,
    )
