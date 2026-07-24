"""
Runs classical siting (Benders/SCIP) and quantum siting (VQA, local
statevector simulator) on all four IEEE14 scenarios requested for the Phase 3
solver-comparison table:
  1. no DC              -> 4batt.py
  2. DC at bus 4         -> 4batt_dcbus4.py
  3. DC@4, gen2 outage   -> 4batt_dcbus4_g2out.py
  4. DC@4, heatwave      -> 4batt_dcbus4_heatwave.py (heatwave only, NOT
                            combined with the Gen2 outage — the two are
                            separate, independent scenarios)

Same settings for all four: n_candidates=20 (matches the Phase 2 submission
table's "top n=20" methodology), second_stage="uc", warm_start="zeros",
sim_method="statevector", final_backend="local" (no qBraid job — the QPU row
in the final table is a placeholder, not measured here).

Scenario 3's OUTAGES (Gen2 trip, {1: set(range(24))}) is now read from the
assets file and threaded through to both solvers via the `outages` parameter
added to run_siting_benders/run_quantum_siting (and their internal run_uc()
calls) — previously this was a real gap (Gen2 stayed available regardless of
the assets file), now fixed.
"""
import json
import os
import sys
import time

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)
os.chdir(REPO)
DATA_DIR = os.path.dirname(os.path.abspath(__file__))

SCENARIOS = [
    ("No DC",                        "4batt.py"),
    ("DC @ bus 4",                   "4batt_dcbus4.py"),
    ("DC @ 4, Gen2 outage",          "4batt_dcbus4_g2out.py"),
    ("DC @ 4, heatwave",             "4batt_dcbus4_heatwave.py"),
]

N_CANDIDATES = 20
TIME_LIMIT_S = 120.0
T = 24


def main():
    import main as cli
    from solvers.siting_benders import run_siting_benders
    from solvers.quantum_siting import run_quantum_siting

    use_case = "ieee14"
    use_case_path = os.path.join(REPO, "use_cases", use_case)

    results = []
    for label, assets_file in SCENARIOS:
        print(f"\n{'='*70}\n{label} ({assets_file})\n{'='*70}")
        assets_path = os.path.join(use_case_path, assets_file)
        _, grid_mod, assets_mod, loc_mod = cli.load_modules(use_case, use_case_path, assets_path)
        grid = grid_mod.Case()

        # Match dashboard.py's _load_case: weather scenario scales demand
        # BEFORE the flat datacenter load is injected (the datacenter itself
        # is not weather-scaled).
        heat_factors = getattr(assets_mod, "HEAT_FACTORS", None)
        if heat_factors is not None:
            n = min(len(heat_factors), grid.power_demand.shape[1])
            import numpy as _np
            grid.power_demand[:, :n] *= _np.array(heat_factors[:n], dtype=float)[_np.newaxis, :]

        dc_bus = getattr(assets_mod, "DATACENTER_BUS", None)
        dc_mw = float(getattr(assets_mod, "DATACENTER_MW", 0))
        if dc_bus is not None and dc_mw:
            grid.power_demand[dc_bus - 1, :] += dc_mw

        outages = getattr(assets_mod, "OUTAGES", None)

        generators = assets_mod.GENERATORS
        batteries = assets_mod.BATTERIES

        # Classical siting (Benders/SCIP)
        t0 = time.perf_counter()
        classical = run_siting_benders(grid, generators, batteries, T, time_limit_s=TIME_LIMIT_S,
                                       outages=outages)
        classical_runtime = time.perf_counter() - t0
        print(f"Classical: buses {classical.bus_tuple}  ${classical.total_cost:,.0f}  "
              f"{classical_runtime:.1f}s  status={classical.scip_status}")

        # Quantum siting (VQA, local statevector simulator)
        t0 = time.perf_counter()
        quantum = run_quantum_siting(
            grid, generators, batteries, T,
            sim_method="statevector", final_backend="local",
            n_candidates=N_CANDIDATES, second_stage="uc", warm_start="zeros",
            outages=outages,
        )
        quantum_runtime = time.perf_counter() - t0
        q_bat_locs, q_commitment, q_cost, _ = quantum.best
        q_bus_tuple = tuple(q_bat_locs[b] for b in range(len(batteries)))
        gap_pct = 100.0 * (q_cost - classical.total_cost) / classical.total_cost
        print(f"Quantum: buses {q_bus_tuple}  ${q_cost:,.0f}  {quantum_runtime:.1f}s  "
              f"gap={gap_pct:.3f}%")

        results.append({
            "label": label,
            "assets_file": assets_file,
            "classical_buses": list(classical.bus_tuple),
            "classical_cost": classical.total_cost,
            "classical_runtime_s": classical_runtime,
            "classical_status": classical.scip_status,
            "quantum_buses": list(q_bus_tuple),
            "quantum_cost": q_cost,
            "quantum_runtime_s": quantum_runtime,
            "gap_pct": gap_pct,
        })

    out_path = os.path.join(DATA_DIR, "phase3_solver_comparison.json")
    if os.path.exists(out_path):
        with open(out_path) as f:
            existing = json.load(f)
        by_assets_file = {r["assets_file"]: r for r in existing}
        for r in results:
            by_assets_file[r["assets_file"]] = r
        results = list(by_assets_file.values())
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote {out_path}")

    print("\n\nSummary:")
    for r in results:
        print(f"{r['label']:35s} classical ${r['classical_cost']:,.0f} ({r['classical_runtime_s']:.0f}s)  "
              f"quantum ${r['quantum_cost']:,.0f} ({r['quantum_runtime_s']:.0f}s)  gap={r['gap_pct']:.3f}%")


if __name__ == "__main__":
    main()
