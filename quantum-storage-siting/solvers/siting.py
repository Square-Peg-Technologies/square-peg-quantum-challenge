import itertools

from solvers.uc import run_uc
from solvers.results import SitingResult


def run_siting(grid, generators, batteries, T) -> SitingResult:
    bus_pairs = list(itertools.combinations(range(1, 6), 2))  # 10 pairs

    results = []
    infeasible = []
    for (bus_a, bus_b) in bus_pairs:
        bat_locs = {0: bus_a, 1: bus_b}
        try:
            uc_result = run_uc(grid, generators, batteries, bat_locs, T)
            results.append(((bus_a, bus_b), uc_result.total_cost, uc_result))
        except RuntimeError:
            infeasible.append((bus_a, bus_b))
            print(f"  Placement ({bus_a}, {bus_b}): infeasible — skipped")

    sorted_list = sorted(results, key=lambda x: x[1])
    return SitingResult(ranking=sorted_list, infeasible=infeasible)
