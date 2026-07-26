"""
Run Quantum Siting (n_candidates=20) for the datacenter-at-bus-4 scenario and
compare the ranked candidate placements against the PLEXOS solution pool
(Batteries, No Line Losses Base Case, V5: sol=0..4).

Mirrors main.py's opt=4 (Quantum Siting) CLI path non-interactively:
  sim_method="statevector", final_backend="local" (no qBraid credits spent),
  n_candidates=20, second_stage="uc", warm_start="zeros", line_losses=False.

Run from the repo root:
    python use_cases/ieee14/quantum_siting_dcbus4_top20.py
"""

import importlib.util
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.abspath(os.path.join(_here, "..", ".."))
for p in [_repo_root, _here]:
    if p not in sys.path:
        sys.path.insert(0, p)

T = 24


def _load_modules():
    grid_spec = importlib.util.spec_from_file_location("ieee14", os.path.join(_here, "ieee14.py"))
    grid_mod = importlib.util.module_from_spec(grid_spec)
    grid_spec.loader.exec_module(grid_mod)

    base_spec = importlib.util.spec_from_file_location("assets", os.path.join(_here, "4batt.py"))
    base_mod = importlib.util.module_from_spec(base_spec)
    sys.modules["assets"] = base_mod
    base_spec.loader.exec_module(base_mod)

    dc_spec = importlib.util.spec_from_file_location("dcbus4", os.path.join(_here, "4batt_dcbus4.py"))
    assets_mod = importlib.util.module_from_spec(dc_spec)
    dc_spec.loader.exec_module(assets_mod)

    return grid_mod, assets_mod


def main():
    from solvers.quantum_siting import run_quantum_siting

    grid_mod, assets_mod = _load_modules()
    grid = grid_mod.Case()
    grid.power_demand[assets_mod.DATACENTER_BUS - 1, :] += assets_mod.DATACENTER_MW

    print(f"Datacenter: bus {assets_mod.DATACENTER_BUS}, {assets_mod.DATACENTER_MW} MW flat")
    print(f"Batteries: {len(assets_mod.BATTERIES)} x "
          f"{assets_mod.BATTERIES[0]['power_mw']} MW / {assets_mod.BATTERIES[0]['capacity_mwh']} MWh")
    print(f"T={T}h, n_candidates=20, second_stage=uc\n")

    result = run_quantum_siting(
        grid=grid,
        generators=assets_mod.GENERATORS,
        batteries=assets_mod.BATTERIES,
        T=T,
        sim_method="statevector",
        final_backend="local",
        n_candidates=20,
        second_stage="uc",
        warm_start="zeros",
        track_convergence=False,
    )

    sorted_evals = sorted(result.evaluated, key=lambda x: x[2])
    print(f"\n{'Rank':<6} {'Buses':<24} {'Total Cost ($)':>16}")
    print("-" * 50)
    rank_by_buses = {}
    for rank, (bat_locs, _commit, cost, _res) in enumerate(sorted_evals, start=1):
        buses = sorted(bat_locs.values())
        rank_by_buses[tuple(buses)] = rank
        print(f"{rank:<6} {str(buses):<24} {cost:>16,.0f}")

    plexos_sols = {
        "sol=0": [4, 7, 8, 12],
        "sol=1": [4, 5, 8, 12],
        "sol=2": [5, 7, 8, 12],
        "sol=3": [7, 8, 12, 13],
        "sol=4": [4, 5, 7, 8],
    }
    print("\nComparison against the PLEXOS solutions:")
    print(f"{'PLEXOS sol':<10} {'Buses':<24} {'Our rank (of 20)':>18}")
    print("-" * 54)
    for name, buses in plexos_sols.items():
        key = tuple(sorted(buses))
        rank = rank_by_buses.get(key, "not in our 20")
        print(f"{name:<10} {str(buses):<24} {str(rank):>18}")


if __name__ == "__main__":
    main()
