import glob
import importlib.util
import os
import sys
import time

from solvers.results import UCResult, SitingResult, QuantumSitingResult


def prompt_optimization() -> int:
    while True:
        print("Select optimization to run:")
        print("  1. Economic Dispatch (ED)")
        print("  2. Unit Commitment (UC)")
        print("  3. Battery Siting (exhaustive search)")
        print("  4. Quantum Siting (Hybrid VQA + Classical)")
        raw = input("Enter number: ").strip()
        if raw in ("1", "2", "3", "4"):
            return int(raw)
        print("Invalid selection. Please enter 1, 2, 3, or 4.")


def prompt_hours() -> int:
    while True:
        raw = input("How many hours to simulate? (1-24): ").strip()
        try:
            val = int(raw)
        except ValueError:
            print("Invalid input. Please enter a whole number between 1 and 24.")
            continue
        if 1 <= val <= 24:
            return val
        print("Invalid input. Please enter a whole number between 1 and 24.")


def prompt_assets() -> tuple:
    found = sorted(glob.glob("assets*.py"))
    if not found:
        print("No assets files found in current directory.")
        sys.exit(1)

    print("Available assets files:")
    for i, fname in enumerate(found, start=1):
        print(f"  {i}. {fname}")

    while True:
        raw = input("Select a file (enter number): ").strip()
        try:
            idx = int(raw)
        except ValueError:
            print("Invalid selection. Please enter a number from the list.")
            continue
        if 1 <= idx <= len(found):
            chosen = found[idx - 1]
            spec = importlib.util.spec_from_file_location("assets_chosen", chosen)
            assert spec is not None and spec.loader is not None
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            return chosen, mod
        print("Invalid selection. Please enter a number from the list.")


def print_header(
    opt_name: str,
    T: int,
    assets_file: str,
    generators: list,
    batteries: list,
) -> None:
    print("=============================================")
    print(f"Run: {opt_name} | Hours: {T} | Assets: {assets_file}")

    gen_lines = []
    for g in generators:
        line = (
            f"{g['name']} (Bus {g['bus']}, "
            f"{g['p_min']}-{g['p_max']} MW, "
            f"a={g['cost_a']}, b=${g['cost_b']}, c=${g['cost_c']})"
        )
        gen_lines.append(line)

    prefix_gen = "Generators: "
    prefix_pad = " " * len(prefix_gen)
    for i, line in enumerate(gen_lines):
        if i == 0:
            print(f"{prefix_gen}{{{line}}}")
        else:
            print(f"{prefix_pad}{{{line}}}")

    bat_parts = []
    for b in batteries:
        bat_parts.append(f"{{{b['name']} ({b['power_mw']} MW / {b['capacity_mwh']} MWh)}}")
    print("Batteries:  " + ", ".join(bat_parts))
    print("=============================================")


def prompt_quantum_options() -> tuple[str, int, str]:
    """Prompt for backend, n_candidates, and second_stage. Returns (backend, n_candidates, second_stage)."""
    while True:
        print("Select quantum backend:")
        print("  1. Qiskit (VQA, local simulator)")
        print("  2. D-Wave (Simulated Annealing)")
        raw = input("Enter number: ").strip()
        if raw == "1":
            backend = "qiskit"
            break
        elif raw == "2":
            backend = "dwave"
            break
        print("Invalid selection. Please enter 1 or 2.")

    while True:
        raw = input("How many candidates to evaluate classically? [default: 10]: ").strip()
        if raw == "":
            n_candidates = 10
            break
        try:
            n_candidates = int(raw)
            if n_candidates >= 1:
                break
        except ValueError:
            pass
        print("Invalid input. Please enter a positive integer.")

    while True:
        print("Second-stage solver:")
        print("  1. ED dispatch (fix commitment and placement)")
        print("  2. Full UC re-solve (fix placement only)")
        raw = input("Enter number: ").strip()
        if raw == "1":
            second_stage = "ed"
            break
        elif raw == "2":
            second_stage = "uc"
            break
        print("Invalid selection. Please enter 1 or 2.")

    return backend, n_candidates, second_stage


def print_quantum_results(result: "QuantumSitingResult") -> None:
    backend_label = "Qiskit VQA" if result.backend == "qiskit" else "D-Wave SA"
    stage_label = "ED" if result.second_stage == "ed" else "UC"

    print(f"\nQuantum Siting Results ({backend_label} + {stage_label} refinement)")
    print(f"Quantum candidates found:   {len(result.quantum_candidates)}")
    print(f"Candidates evaluated:       {len(result.evaluated)}")
    print(f"Runtime — quantum sieve:    {result.runtime_quantum:.1f}s")
    print(f"Runtime — classical stage:  {result.runtime_classical:.1f}s")

    if not result.evaluated:
        print("No feasible candidates found.")
        return

    is_uc = result.second_stage == "uc"
    sorted_evals = sorted(result.evaluated, key=lambda x: x[2])

    if is_uc:
        print(f"\n{'Rank':<6} {'Bat Placement':<20} {'True Cost ($)':>16}")
        print("-" * 44)
        for rank, (bat_locs, _commit, true_cost, _res) in enumerate(sorted_evals, start=1):
            bat_str = str(tuple(bat_locs.values()))
            print(f"{rank:<6} {bat_str:<20} {true_cost:>16,.0f}")
    else:
        print(f"\n{'Rank':<6} {'Bat Placement':<20} {'Commitment':<16} {'True Cost ($)':>16}")
        print("-" * 62)
        for rank, (bat_locs, commitment, true_cost, _res) in enumerate(sorted_evals, start=1):
            bat_str = str(tuple(bat_locs.values()))
            commit_str = "".join("1" if c else "0" for c in commitment)
            print(f"{rank:<6} {bat_str:<20} {commit_str:<16} {true_cost:>16,.0f}")

    best_locs, best_commit, best_cost, best_res = result.best
    print(f"\nBest placement: buses {tuple(best_locs.values())}, cost ${best_cost:,.0f}")

    if is_uc:
        commitment_matrix = best_res.commitment  # shape (G, T)
        G, T = commitment_matrix.shape
        gen_names = [f"Unit {g}" for g in range(G)]
        print("Commitment schedule (UC re-optimised per hour):")
        header = f"  {'Hour':>4} | " + " | ".join(f"{n:>8}" for n in gen_names)
        print(header)
        print("  " + "-" * (len(header) - 2))
        for t in range(T):
            row = " | ".join(
                f"{'ON' if commitment_matrix[g, t] > 0.5 else 'OFF':>8}"
                for g in range(G)
            )
            print(f"  {t + 1:>4} | {row}")
    else:
        print(f"Best commitment: {['ON' if c else 'OFF' for c in best_commit]}")


def print_results(
    result,
    opt_name: str,
    T: int,
    generators: list,
    batteries: list,
) -> None:
    if isinstance(result, QuantumSitingResult):
        print_quantum_results(result)
        return

    if isinstance(result, SitingResult):
        print("\nBattery Siting Results (ranked by total cost):")
        print(f"{'Rank':<6} {'Bus Pair':<12} {'Total Cost ($)':>16} {'Congested Hrs':>14}")
        print("-" * 54)
        for rank, (bus_pair, total_cost, uc_result) in enumerate(result.ranking, start=1):
            pair_str = f"({bus_pair[0]}, {bus_pair[1]})"
            cong_hrs = sum(1 for lines in uc_result.congested_lines if lines)
            print(f"{rank:<6} {pair_str:<12} {total_cost:>16,.0f} {cong_hrs:>14}")
        if result.infeasible:
            print("\nInfeasible placements (line limits unsatisfiable at peak hours):")
            for bus_a, bus_b in result.infeasible:
                print(f"  Buses ({bus_a}, {bus_b})")
        if result.ranking:
            best_pair, best_cost, _ = result.ranking[0]
            print(f"\nBest placement: buses {best_pair[0]} and {best_pair[1]}, cost ${best_cost:.0f}")
        return

    is_uc = isinstance(result, UCResult)

    gen_names = [g["name"] for g in generators]
    bat_names = [b["name"] for b in batteries]
    gen_header = " | ".join(f"{n:>10}" for n in gen_names)

    # Battery header: two columns per battery (net MW and SOC)
    bat_header_parts = []
    for name in bat_names:
        short = name.replace("Bat ", "B")
        bat_header_parts.append(f"{short+' MW':>8}")
        bat_header_parts.append(f"{short+' SOC':>8}")
    bat_header = " | ".join(bat_header_parts)

    if is_uc:
        commit_header = " | ".join(f"{'Commit':>6}" for _ in gen_names)
        header = f"{'Hour':>4} | {'Cost ($)':>12} | {gen_header} | {commit_header} | {bat_header} | Congested"
    else:
        header = f"{'Hour':>4} | {'Cost ($)':>12} | {gen_header} | {bat_header} | Congested"

    print(f"\n{opt_name} Results:")
    print(header)
    print("-" * len(header))

    for t in range(T):
        dispatch_vals = " | ".join(
            f"{result.dispatch[g, t]:>10.1f}" for g in range(len(generators))
        )
        cost = result.hourly_costs[t]
        congested = result.congested_lines[t]
        congested_str = str(congested) if congested else "none"

        # Battery columns: positive = charging, negative = discharging
        bat_vals_parts = []
        for b in range(len(batteries)):
            net_mw = result.battery_charge[b, t] - result.battery_discharge[b, t]
            soc = result.soc[b, t]
            bat_vals_parts.append(f"{net_mw:>8.1f}")
            bat_vals_parts.append(f"{soc:>8.1f}")
        bat_vals = " | ".join(bat_vals_parts)

        if is_uc:
            commit_vals = " | ".join(
                f"{'ON' if result.commitment[g, t] > 0.5 else 'OFF':>6}"
                for g in range(len(generators))
            )
            print(f"{t + 1:>4} | {cost:>12,.2f} | {dispatch_vals} | {commit_vals} | {bat_vals} | {congested_str}")
        else:
            print(f"{t + 1:>4} | {cost:>12,.2f} | {dispatch_vals} | {bat_vals} | {congested_str}")

    print("-" * len(header))
    print(f"{'TOTAL':>4} | {result.total_cost:>12,.2f}")


def save_plot(result, opt_name: str, T: int, assets_file: str, grid=None) -> None:
    try:
        from plots import save_plot as _save_plot
    except ImportError:
        return
    try:
        _save_plot(result, opt_name, T, assets_file, grid=grid)
    except Exception as e:
        print(f"Plot save failed: {e}")


def save_overview(result, opt_name: str, T: int, assets_file: str,
                  generators: list, batteries: list, grid) -> None:
    try:
        from plots import save_dispatch_overview
    except ImportError:
        return
    try:
        save_dispatch_overview(result, opt_name, T, assets_file, generators, batteries, grid)
    except Exception as e:
        print(f"Overview plot save failed: {e}")


def main():
    sys.path.insert(
        0,
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "..",
            "Tutorial",
            "Quantum Network Flow Diagrams",
        ),
    )

    opt = prompt_optimization()
    quantum_opts = None
    if opt == 4:
        quantum_opts = prompt_quantum_options()
    T = prompt_hours()
    assets_file_name, assets_mod = prompt_assets()

    pjm5_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pjm5.py")
    spec = importlib.util.spec_from_file_location("pjm5", pjm5_path)
    pjm5_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pjm5_mod)
    grid = pjm5_mod.Case()

    generators = assets_mod.GENERATORS
    batteries = assets_mod.BATTERIES

    loc_spec = importlib.util.spec_from_file_location("locations", "locations.py")
    loc_mod = importlib.util.module_from_spec(loc_spec)
    loc_spec.loader.exec_module(loc_mod)
    gen_locs = loc_mod.GENERATOR_LOCATIONS
    bat_locs = loc_mod.BATTERY_LOCATIONS

    opt_names = {1: "ED", 2: "UC", 3: "Siting", 4: "Quantum Siting"}
    opt_name = opt_names[opt]

    print_header(opt_name, T, assets_file_name, generators, batteries)
    print(f"\nRunning {opt_name} optimization for T={T} hours...")

    from solvers.ed import run_ed
    from solvers.uc import run_uc
    from solvers.siting import run_siting
    from solvers.quantum_siting import run_quantum_siting

    t_start = time.perf_counter()
    if opt == 1:
        result = run_ed(grid, generators, batteries, gen_locs, bat_locs, T)
    elif opt == 2:
        result = run_uc(grid, generators, batteries, bat_locs, T)
    elif opt == 3:
        result = run_siting(grid, generators, batteries, T)
    else:
        backend, n_candidates, second_stage = quantum_opts
        result = run_quantum_siting(
            grid=grid,
            generators=generators,
            batteries=batteries,
            T=T,
            backend=backend,
            n_candidates=n_candidates,
            second_stage=second_stage,
        )
    elapsed = time.perf_counter() - t_start

    if elapsed < 60:
        time_str = f"{elapsed:.1f}s"
    else:
        m, s = divmod(elapsed, 60)
        time_str = f"{int(m)}m {s:.1f}s"
    print(f"Solver time: {time_str}")

    print_results(result, opt_name, T, generators, batteries)
    if not isinstance(result, (SitingResult, QuantumSitingResult)):
        save_plot(result, opt_name, T, assets_file_name, grid=grid)
        save_overview(result, opt_name, T, assets_file_name, generators, batteries, grid)
    elif isinstance(result, SitingResult):
        save_plot(result, opt_name, T, assets_file_name, grid=grid)


if __name__ == "__main__":
    main()
