import glob
import importlib.util
import os
import sys
import time

import numpy as np

from solvers.results import UCResult, SitingResult, SitingMIPResult, QuantumSitingResult

FULL_WEEK_HOURS = 168


def extend_to_full_week(grid, hours: int = FULL_WEEK_HOURS) -> None:
    """Cyclically repeat a case's demand/cost profile out to `hours` columns.

    Some use cases (e.g. ieee14_plexos_basecase, a single-day PLEXOS
    replication) only define one day of data. Tiling that pattern here,
    generically, means every use case's hour slider/prompt can reach a
    full week without each case author hand-rolling a DAYS=7 repeat loop
    themselves — new use cases get this for free. Cases that already
    define >= `hours` columns (e.g. ieee14/pjm5/ieee30, already extended
    to 168h) are left untouched.
    """
    n_native = grid.power_demand.shape[1]
    if n_native >= hours:
        return
    reps = -(-hours // n_native)  # ceil division
    grid.power_demand = np.tile(grid.power_demand, reps)[:, :hours]
    grid.generator_cost = np.tile(grid.generator_cost, reps)[:, :hours]


def prompt_optimization() -> int:
    while True:
        print("Select optimization to run:")
        print("  1. Economic Dispatch (ED)")
        print("  2. Unit Commitment (UC)")
        print("  3. Battery Siting (MIP, optimal)")
        print("  4. Quantum Siting (Hybrid VQA + Classical)")
        raw = input("Enter number: ").strip()
        if raw in ("1", "2", "3", "4"):
            return int(raw)
        print("Invalid selection. Please enter 1, 2, 3, or 4.")


def prompt_hours(max_hours: int) -> int:
    while True:
        raw = input(f"How many hours to simulate? (1-{max_hours}): ").strip()
        try:
            val = int(raw)
        except ValueError:
            print(f"Invalid input. Please enter a whole number between 1 and {max_hours}.")
            continue
        if 1 <= val <= max_hours:
            return val
        print(f"Invalid input. Please enter a whole number between 1 and {max_hours}.")


def prompt_use_case() -> tuple[str, str]:
    """Scan use_cases/ for subdirectories and prompt the user to pick one.

    Returns (use_case_name, use_case_path).
    """
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "use_cases")
    if not os.path.isdir(base):
        print("No use_cases/ directory found.")
        sys.exit(1)

    cases = sorted(
        d for d in os.listdir(base)
        if os.path.isdir(os.path.join(base, d)) and not d.startswith("_")
    )
    if not cases:
        print("No use cases found in use_cases/.")
        sys.exit(1)

    if len(cases) == 1:
        name = cases[0]
        return name, os.path.join(base, name)

    print("Available use cases:")
    for i, name in enumerate(cases, start=1):
        print(f"  {i}. {name}")

    while True:
        raw = input("Select a use case (enter number): ").strip()
        try:
            idx = int(raw)
        except ValueError:
            print("Invalid selection. Please enter a number from the list.")
            continue
        if 1 <= idx <= len(cases):
            name = cases[idx - 1]
            return name, os.path.join(base, name)
        print("Invalid selection. Please enter a number from the list.")


def load_modules(use_case_name: str, use_case_path: str, assets_path: str) -> tuple:
    """Non-interactive module loader shared by the CLI and the dashboard.

    Returns (assets_file_name, grid_mod, assets_mod, loc_mod).
    """
    # Grid — file must be named after the use case (e.g. pjm5/pjm5.py)
    grid_file = os.path.join(use_case_path, f"{use_case_name}.py")
    grid_spec = importlib.util.spec_from_file_location(use_case_name, grid_file)
    assert grid_spec is not None and grid_spec.loader is not None
    grid_mod = importlib.util.module_from_spec(grid_spec)
    grid_spec.loader.exec_module(grid_mod)  # type: ignore[union-attr]

    # Locations
    loc_file = os.path.join(use_case_path, "locations.py")
    loc_spec = importlib.util.spec_from_file_location("locations", loc_file)
    assert loc_spec is not None and loc_spec.loader is not None
    loc_mod = importlib.util.module_from_spec(loc_spec)
    loc_spec.loader.exec_module(loc_mod)  # type: ignore[union-attr]

    # Add use_case_path to sys.path so assets_dc_bus{N}.py can do "from assets import ..."
    if use_case_path not in sys.path:
        sys.path.insert(0, use_case_path)

    # assets_dc_bus{N}.py variants do a bare "from assets import GENERATORS,
    # BATTERIES" to inherit their use case's base assets.py. Python caches
    # that under sys.modules["assets"] on first import — since every use
    # case has its own assets.py, whichever use case's assets.py got
    # imported FIRST in this process stays cached under that shared name and
    # leaks into every other use case's "from assets import ..." for the
    # rest of the process (e.g. dashboard switching from pjm5 to ieee14).
    # Force sys.modules["assets"] to this use case's own assets.py right
    # before loading the requested file, so the bare import always resolves
    # to the current use case regardless of load order/history.
    base_assets_path = os.path.join(use_case_path, "assets.py")
    if os.path.exists(base_assets_path):
        base_spec = importlib.util.spec_from_file_location("assets", base_assets_path)
        assert base_spec is not None and base_spec.loader is not None
        base_assets_mod = importlib.util.module_from_spec(base_spec)
        sys.modules["assets"] = base_assets_mod
        base_spec.loader.exec_module(base_assets_mod)  # type: ignore[union-attr]

    assets_spec = importlib.util.spec_from_file_location("assets_chosen", assets_path)
    assert assets_spec is not None and assets_spec.loader is not None
    assets_mod = importlib.util.module_from_spec(assets_spec)
    assets_spec.loader.exec_module(assets_mod)  # type: ignore[union-attr]

    return os.path.basename(assets_path), grid_mod, assets_mod, loc_mod


def load_use_case(use_case_name: str, use_case_path: str) -> tuple:
    """Load grid module, assets module, and locations module from a use case folder.

    If multiple assets*.py files exist the user is prompted to pick one;
    if only one exists it is loaded automatically.

    Returns (assets_file_name, grid_mod, assets_mod, loc_mod).
    """
    found = sorted(glob.glob(os.path.join(use_case_path, "assets*.py")))
    if not found:
        print(f"No assets files found in {use_case_path}.")
        sys.exit(1)

    if len(found) == 1:
        chosen = found[0]
    else:
        print("Available assets files:")
        for i, fpath in enumerate(found, start=1):
            print(f"  {i}. {os.path.basename(fpath)}")
        while True:
            raw = input("Select assets file (enter number): ").strip()
            try:
                idx = int(raw)
            except ValueError:
                print("Invalid selection. Please enter a number from the list.")
                continue
            if 1 <= idx <= len(found):
                chosen = found[idx - 1]
                break
            print("Invalid selection. Please enter a number from the list.")

    return load_modules(use_case_name, use_case_path, chosen)


def print_header(
    opt_name: str,
    T: int,
    use_case: str,
    assets_file: str,
    generators: list,
    batteries: list,
    dc_bus: int | None = None,
    dc_mw: float = 0.0,
) -> None:
    print("=============================================")
    print(f"Run: {opt_name} | Hours: {T} | Use case: {use_case} | Assets: {assets_file}")
    if dc_bus is not None and dc_mw > 0:
        print(f"Datacenter: {dc_mw:.0f} MW flat load injected at Bus {dc_bus}")

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


def prompt_quantum_options() -> tuple[str, str, int, str, str]:
    """Prompt for sim_method, final_backend, n_candidates, second_stage, warm_start."""
    while True:
        print("Select VQA backend (how training runs):")
        print("  1. Qiskit (statevector simulator)")
        print("  2. Aer Tensor Network (MPS — scales to 36+ qubits)")
        raw = input("Enter number: ").strip()
        if raw == "1":
            sim_method = "statevector"
            break
        elif raw == "2":
            sim_method = "tensor_network"
            break
        print("Invalid selection. Please enter 1 or 2.")

    while True:
        print("Sample final shots on:")
        print("  1. Local (same simulator used for training)")
        print("  2. IonQ via qBraid (real hardware/simulator — spends qBraid credits)")
        raw = input("Enter number: ").strip()
        if raw == "1":
            final_backend = "local"
            break
        elif raw == "2":
            final_backend = "ionq_qbraid"
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

    warm_start = "zeros"
    while True:
        print("Warm-start strategy (arXiv:2505.00145):")
        print("  1. zeros  — theta=0, paper simulation default [default]")
        print("  2. random — theta~Uniform[-2pi,2pi], paper IonQ hardware default")
        print("  3. sdp    — LP-relaxation warm start, paper Section III mixer design")
        raw = input("Enter number [default: 1]: ").strip()
        if raw in ("", "1"):
            warm_start = "zeros"
            break
        elif raw == "2":
            warm_start = "random"
            break
        elif raw == "3":
            warm_start = "sdp"
            break
        print("Invalid selection. Please enter 1, 2, or 3.")

    return sim_method, final_backend, n_candidates, second_stage, warm_start


def print_quantum_results(result: "QuantumSitingResult") -> None:
    sim_label = {"statevector": "Qiskit VQA", "tensor_network": "Aer TN (VQA)"}.get(
        result.sim_method, result.sim_method)
    backend_label = f"{sim_label} → IonQ (qBraid29sim)" if result.final_backend == "ionq_qbraid" else sim_label
    stage_label = "ED" if result.second_stage == "ed" else "UC"

    warm_label = {"zeros": "θ=0 (paper sim default)", "random": "θ~Uniform[-2π,2π] (paper hardware)", "sdp": "LP-relaxation (paper Sec III)"}.get(result.warm_start, result.warm_start)
    print(f"\nQuantum Siting Results ({backend_label} + {stage_label} refinement)")
    print(f"Warm-start:                {warm_label}")
    print(f"Quantum candidates found:   {len(result.quantum_candidates)}")
    print(f"Candidates evaluated:       {len(result.evaluated)}")
    print(f"Runtime — quantum sieve:    {result.runtime_quantum:.1f}s")
    print(f"Runtime — classical stage:  {result.runtime_classical:.1f}s")
    if result.runtime_phases:
        total = sum(result.runtime_phases.values())
        print("Runtime breakdown by phase:")
        for label, sec in result.runtime_phases.items():
            pct = 100.0 * sec / total if total > 0 else 0.0
            print(f"  {label:<36} {sec:>8.1f}s  ({pct:>4.1f}%)")
    if result.convergence_trace:
        print(f"COBYLA iterations:         {len(result.convergence_trace)}  (final obj: {result.convergence_trace[-1]:.4g})")

    if not result.evaluated:
        print("No feasible candidates found.")
        return

    is_uc = result.second_stage == "uc"
    sorted_evals = sorted(result.evaluated, key=lambda x: x[2])

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

    if isinstance(result, SitingMIPResult):
        label = {
            "timelimit": "Best placement found (time limit hit)",
            "stalled": "Best placement found (stopped early — no improvement)",
        }.get(result.scip_status, "Optimal battery placement")
        print(f"\n{label}: buses {result.bus_tuple}")
        print(f"Total cost: ${result.total_cost:,.0f}")
        if result.runtime_phases:
            total = sum(result.runtime_phases.values())
            print("Runtime breakdown by phase:")
            for phase_label, sec in result.runtime_phases.items():
                pct = 100.0 * sec / total if total > 0 else 0.0
                print(f"  {phase_label:<42} {sec:>8.1f}s  ({pct:>4.1f}%)")
        result = result.uc_result   # fall through to UC display below

    if isinstance(result, SitingResult):
        print("\nBattery Siting Results (ranked by total cost):")
        print(f"{'Rank':<6} {'Bus Placement':<20} {'Total Cost ($)':>16} {'Congested Hrs':>14}")
        print("-" * 62)
        for rank, (bus_tuple, total_cost, uc_result) in enumerate(result.ranking, start=1):
            placement_str = str(bus_tuple)
            cong_hrs = sum(1 for lines in uc_result.congested_lines if lines)
            print(f"{rank:<6} {placement_str:<20} {total_cost:>16,.0f} {cong_hrs:>14}")
        if result.ranking:
            best_tuple, best_cost, _ = result.ranking[0]
            print(f"\nBest placement: buses {best_tuple}, cost ${best_cost:.0f}")
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


def save_plot(result, opt_name: str, T: int, assets_file: str, grid=None,
              generators=None, bat_locs=None, dc_bus=None, dc_mw=0.0) -> None:
    try:
        from plots import save_plot as _save_plot
    except ImportError:
        return
    try:
        _save_plot(result, opt_name, T, assets_file, grid=grid,
                   generators=generators, bat_locs=bat_locs,
                   dc_bus=dc_bus, dc_mw=dc_mw)
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
    opt = prompt_optimization()
    quantum_opts = None
    if opt == 4:
        quantum_opts = prompt_quantum_options()
    use_case_name, use_case_path = prompt_use_case()
    assets_file_name, grid_mod, assets_mod, loc_mod = load_use_case(use_case_name, use_case_path)

    grid = grid_mod.Case()
    extend_to_full_week(grid)

    # Bound the hours prompt by how many hours of demand data this case
    # actually has (e.g. ieee14 has a week/168h; other cases may still be 24h).
    max_hours = grid.power_demand.shape[1]
    T = prompt_hours(max_hours)

    # Inject datacenter load if the assets file specifies one
    dc_bus = getattr(assets_mod, "DATACENTER_BUS", None)
    dc_mw = float(getattr(assets_mod, "DATACENTER_MW", 0))
    if dc_bus is not None and dc_mw > 0:
        grid.power_demand[dc_bus - 1, :] += dc_mw

    generators = assets_mod.GENERATORS
    batteries = assets_mod.BATTERIES
    gen_locs = loc_mod.GENERATOR_LOCATIONS
    bat_locs = loc_mod.BATTERY_LOCATIONS

    opt_names = {1: "ED", 2: "UC", 3: "Siting", 4: "Quantum Siting"}
    opt_name = opt_names[opt]

    print_header(opt_name, T, use_case_name, assets_file_name, generators, batteries, dc_bus, dc_mw)
    print(f"\nRunning {opt_name} optimization for T={T} hours...")

    from solvers.ed import run_ed
    from solvers.uc import run_uc
    from solvers.siting_benders import run_siting_benders
    from solvers.quantum_siting import run_quantum_siting

    t_start = time.perf_counter()
    if opt == 1:
        result = run_ed(grid, generators, batteries, gen_locs, bat_locs, T)
    elif opt == 2:
        result = run_uc(grid, generators, batteries, bat_locs, T)
    elif opt == 3:
        tl = input("Time limit in seconds (default 120): ").strip()
        time_limit_s = float(tl) if tl else 120.0
        result = run_siting_benders(grid, generators, batteries, T, time_limit_s=time_limit_s)
    else:
        sim_method, final_backend, n_candidates, second_stage, warm_start = quantum_opts
        from solvers.quantum_siting import _AER_AVAILABLE, _AER_TN_AVAILABLE
        if sim_method == "tensor_network":
            if _AER_TN_AVAILABLE:
                print("Aer: tensor-network simulator available")
            else:
                print("WARNING: Aer tensor-network not available — install qiskit-aer with TN support")
        else:
            if _AER_AVAILABLE:
                print("Aer: using CPU statevector")
            else:
                print("Aer: not installed — using Qiskit StatevectorSampler")
        if final_backend == "ionq_qbraid":
            from solvers.ionq_qbraid_backend import DEVICE_ID
            print(f"IonQ (qBraid29sim): training locally, final shots on device {DEVICE_ID!r} "
                  "(this submits a real job and spends qBraid credits)")
        print(f"Warm-start: {warm_start}")
        result = run_quantum_siting(
            grid=grid,
            generators=generators,
            batteries=batteries,
            T=T,
            sim_method=sim_method,
            final_backend=final_backend,
            n_candidates=n_candidates,
            second_stage=second_stage,
            warm_start=warm_start,
            track_convergence=True,
        )
    elapsed = time.perf_counter() - t_start

    if elapsed < 60:
        time_str = f"{elapsed:.1f}s"
    else:
        m, s = divmod(elapsed, 60)
        time_str = f"{int(m)}m {s:.1f}s"
    print(f"Solver time: {time_str}")

    print_results(result, opt_name, T, generators, batteries)

    if isinstance(result, SitingMIPResult):
        plot_result     = result.uc_result
        plot_bat_locs   = result.bat_locs
    else:
        plot_result     = result
        plot_bat_locs   = bat_locs

    if not isinstance(plot_result, (SitingResult, QuantumSitingResult)):
        save_plot(plot_result, opt_name, T, assets_file_name, grid=grid,
                  generators=generators, bat_locs=plot_bat_locs,
                  dc_bus=dc_bus, dc_mw=dc_mw)
        save_overview(plot_result, opt_name, T, assets_file_name, generators, batteries, grid)
    elif isinstance(plot_result, SitingResult):
        save_plot(plot_result, opt_name, T, assets_file_name, grid=grid,
                  generators=generators, dc_bus=dc_bus, dc_mw=dc_mw)
    elif isinstance(plot_result, QuantumSitingResult):
        if plot_result.evaluated:
            try:
                from plots import save_quantum_siting_gallery
                save_quantum_siting_gallery(plot_result, gen_locs, grid, T, assets_file_name)
            except Exception as e:
                print(f"Quantum siting network plot failed: {e}")
        else:
            print("No evaluated candidates — skipping network plot.")

    if isinstance(result, (QuantumSitingResult, SitingMIPResult)) and result.runtime_phases:
        try:
            from plots import save_runtime_breakdown
            save_runtime_breakdown(result.runtime_phases, opt_name, T, assets_file_name)
        except Exception as e:
            print(f"Runtime breakdown plot failed: {e}")


if __name__ == "__main__":
    main()
