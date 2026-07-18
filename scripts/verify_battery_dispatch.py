"""
Battery dispatch verification — generation shortfall test.

Confirms that batteries discharge during peak hours when cheap generator capacity
(Gen 1 + Gen 2, 472 MW combined) cannot cover total demand, and that the
expensive generators (Gen 3/4/5, $40/MWh) stay OFF throughout.

Two scenarios compared:
  1. No batteries — forces Gen 3/4/5 to commit at peak
  2. Batteries at buses (2, 4, 6, 7) — optimal placement from submission

Usage:
    python scripts/verify_battery_dispatch.py
    python scripts/verify_battery_dispatch.py --amplify 1.6  # sharper peak
"""

import argparse
import importlib.util
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPTS_DIR, ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from solvers.uc import run_uc


# ---------------------------------------------------------------------------
# Grid loading
# ---------------------------------------------------------------------------

def _load_mod(name, fpath, extra_path=None):
    if extra_path and extra_path not in sys.path:
        sys.path.insert(0, extra_path)
    spec = importlib.util.spec_from_file_location(name, fpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_ieee14_bus4(amplify: float = 1.0):
    """Load ieee14 grid with 200 MW datacenter at bus 4.

    amplify: scale factor applied to the BASE load for the 2 true peak hours
             (hours 12-13, 0-indexed) BEFORE datacenter injection.
             The datacenter is a flat 200 MW and is never amplified.
             Max useful value is ~1.3 — above that, cheap gen + battery
             capacity (672 MW) is exceeded and expensive gens must commit
             even in the battery scenario.
    """
    uc_dir = os.path.join(_PROJECT_ROOT, "use_cases", "ieee14")
    grid_mod = _load_mod("ieee14", os.path.join(uc_dir, "ieee14.py"), uc_dir)
    # 4batt_dcbus4.py does a bare "from assets import GENERATORS, BATTERIES" to
    # inherit the base battery file (4batt.py) — populate sys.modules["assets"]
    # with it first, same trick main.py's loader uses.
    sys.modules["assets"] = _load_mod("assets", os.path.join(uc_dir, "4batt.py"), uc_dir)
    assets_mod = _load_mod("assets_dc_bus4", os.path.join(uc_dir, "4batt_dcbus4.py"), uc_dir)

    grid = grid_mod.Case()

    # Amplify BASE load for the 2 sharpest peak hours before adding datacenter
    if amplify != 1.0:
        for h in [12, 13]:   # hours 12-13 (0-indexed) = the midday peak
            grid.power_demand[:, h] *= amplify

    # Inject flat datacenter load at bus 4 (1-indexed → 0-indexed = bus 3)
    dc_bus_0 = assets_mod.DATACENTER_BUS - 1
    dc_mw = assets_mod.DATACENTER_MW
    grid.power_demand[dc_bus_0, :] += dc_mw

    return grid, assets_mod.GENERATORS, assets_mod.BATTERIES


# ---------------------------------------------------------------------------
# Main verification
# ---------------------------------------------------------------------------

def run_verification(amplify: float = 1.0) -> None:
    print("=" * 65)
    print("Battery Dispatch Verification — Generation Shortfall Test")
    print("=" * 65)

    grid, generators, batteries = load_ieee14_bus4(amplify)

    T = grid.power_demand.shape[1]
    total_demand = grid.power_demand.sum(axis=0)   # shape (T,)

    cheap_cap = sum(g["p_max"] for g in generators if g["cost_b"] <= 20.0)
    expensive_gens = [g for g in generators if g["cost_b"] > 20.0]
    shortfall_hours = np.where(total_demand > cheap_cap)[0].astype(int)

    print(f"\nGrid:              IEEE 14-bus + 200 MW datacenter @ bus 4")
    print(f"Horizon:           T={T} hours")
    print(f"Cheap gen cap:     {cheap_cap:.0f} MW  (Gen 1 + Gen 2, $20/MWh)")
    print(f"Expensive gens:    {len(expensive_gens)} units x 100 MW @ $40/MWh  (Gen 3/4/5)")
    print(f"Peak demand:       {total_demand.max():.1f} MW  (hour {total_demand.argmax()})")
    print(f"Shortfall hours:   {(shortfall_hours + 1).tolist()}  (1-indexed, demand > {cheap_cap:.0f} MW)")
    if amplify != 1.0:
        print(f"Demand amplified:  x{amplify} applied to base load, hours 13-14 (peak)")

    # Optimal battery placement from submission (buses 2, 4, 6, 7)
    bat_locs_optimal = {i: b for i, b in enumerate([2, 4, 6, 7])}

    # ── Scenario 1: No batteries ─────────────────────────────────────────────
    # run_uc requires at least one battery (cvxpy rejects shape (0, T)).
    # Use a phantom battery with zero power — it is forced to r_plus=r_minus=0
    # by its own constraints, so it has no effect on dispatch.
    phantom_bat = [{"name": "phantom", "power_mw": 0.0, "capacity_mwh": 0.0,
                    "efficiency": 1.0, "init_soc": 0.0}]
    phantom_locs = {0: 1}
    print("\n--- Scenario 1: No batteries ---")
    uc_no_bat = run_uc(grid, generators, phantom_bat, phantom_locs, T)
    committed_no_bat = uc_no_bat.commitment  # shape (n_gen, T)
    expensive_on_no_bat = committed_no_bat[2:, :]  # Gen 3/4/5 rows
    peak_expensive = expensive_on_no_bat[:, shortfall_hours].sum(axis=0)
    print(f"  Gen 3/4/5 committed in shortfall hours: {peak_expensive.tolist()}")
    print(f"  Total cost: ${uc_no_bat.total_cost:,.0f}")

    # ── Scenario 2: Batteries at (2, 4, 6, 7) ───────────────────────────────
    print(f"\n--- Scenario 2: Batteries at buses {list(bat_locs_optimal.values())} ---")
    uc_with_bat = run_uc(grid, generators, batteries, bat_locs_optimal, T)
    committed_with_bat = uc_with_bat.commitment
    expensive_on_with_bat = committed_with_bat[2:, :]
    discharge = uc_with_bat.battery_discharge   # shape (n_bat, T)
    charge = uc_with_bat.battery_charge
    soc = uc_with_bat.soc

    discharge_shortfall = discharge[:, shortfall_hours].sum(axis=0)
    total_bat_discharge = discharge.sum(axis=1)

    print(f"  Gen 3/4/5 committed in shortfall hours: {expensive_on_with_bat[:, shortfall_hours].sum(axis=0).tolist()}")
    print(f"  Battery discharge in shortfall hours (MW, per hour): {discharge_shortfall.round(1).tolist()}")
    print(f"  Total discharge per battery (MWh): {total_bat_discharge.round(1).tolist()}")
    print(f"  Total cost: ${uc_with_bat.total_cost:,.0f}")

    # ── Assertions ────────────────────────────────────────────────────────────
    print("\n--- Verification ---")
    passed = True

    # 1. Without batteries, expensive gens must commit at peak
    no_bat_must_commit = peak_expensive.sum() > 0
    _check("No-battery scenario commits Gen 3/4/5 at peak", no_bat_must_commit, passed)
    passed = passed and no_bat_must_commit

    # 2. With batteries, Gen 3/4/5 commitment is reduced vs no-battery
    gen345_no_bat = expensive_on_no_bat.sum()
    gen345_with_bat = expensive_on_with_bat.sum()
    gen345_reduced = gen345_with_bat < gen345_no_bat
    if gen345_with_bat == 0:
        label = "With batteries: Gen 3/4/5 OFF all 24 hours"
    else:
        pct = (1 - gen345_with_bat / gen345_no_bat) * 100
        label = f"With batteries: Gen 3/4/5 commitment reduced by {pct:.0f}% ({gen345_no_bat} → {gen345_with_bat} unit-hours)"
    _check(label, gen345_reduced, passed)
    passed = passed and gen345_reduced

    # 3. Batteries discharge during shortfall hours
    bat_discharges_at_peak = discharge_shortfall.sum() > 0
    _check("Batteries discharge during shortfall hours", bat_discharges_at_peak, passed)
    passed = passed and bat_discharges_at_peak

    # 4. Cost savings
    savings = uc_no_bat.total_cost - uc_with_bat.total_cost
    has_savings = savings > 0
    _check(f"Battery case cheaper by ${savings:,.0f}", has_savings, passed)
    passed = passed and has_savings

    print(f"\n{'ALL CHECKS PASSED' if passed else 'SOME CHECKS FAILED'}")

    # ── Plot ─────────────────────────────────────────────────────────────────
    hours = np.arange(1, T + 1)
    fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)

    # Panel 1: Demand vs cheap gen cap
    ax = axes[0]
    ax.plot(hours, total_demand, "k-", linewidth=2, label="Total demand (incl. datacenter)")
    ax.axhline(cheap_cap, color="#1f77b4", linestyle="--", linewidth=1.5,
               label=f"Gen 1+2 capacity ({cheap_cap:.0f} MW)")
    ax.fill_between(hours, cheap_cap, total_demand,
                    where=total_demand > cheap_cap,
                    alpha=0.25, color="red", label="Shortfall window")
    ax.set_ylabel("MW")
    ax.set_title("Demand vs cheap generator capacity")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    # Panel 2: Generator commitment heatmap (no-bat top, with-bat bottom)
    ax = axes[1]
    gen_names = [g["name"] for g in generators[2:]]
    n_expensive = len(gen_names)
    # Stack rows: Gen3/4/5 no-bat on top half, Gen3/4/5 with-bat on bottom half
    heatmap = np.vstack([
        committed_no_bat[2:, :],    # rows 0-2: no batteries
        committed_with_bat[2:, :],  # rows 3-5: with batteries
    ]).astype(float)
    im = ax.imshow(heatmap, aspect="auto", cmap="RdYlGn", vmin=0, vmax=1,
                   extent=[0.5, T + 0.5, -0.5, 2 * n_expensive - 0.5],
                   origin="lower", interpolation="nearest")
    ax.set_yticks(range(2 * n_expensive))
    ax.set_yticklabels(
        [f"{n} — no storage" for n in gen_names] +
        [f"{n} — storage sited" for n in gen_names],
        fontsize=7,
    )
    ax.axhline(n_expensive - 0.5, color="white", linewidth=2)
    plt.colorbar(im, ax=ax, label="Committed (0=OFF, 1=ON)", fraction=0.03, pad=0.02)
    ax.set_title("Gen 3/4/5 commitment: without storage (top) vs with storage sited at buses (2,4,6,7) (bottom)")
    ax.grid(False)

    # Panel 3: Battery discharge + SOC
    ax = axes[2]
    bat_colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]
    total_dis = discharge.sum(axis=0)
    ax.bar(hours, total_dis, color="#1f77b4", alpha=0.6, label="Total battery discharge (MW)")
    ax2 = ax.twinx()
    for i in range(len(batteries)):
        ax2.plot(hours, soc[i, :], color=bat_colors[i], linewidth=1.2,
                 label=f"Bat {i} SOC (%)", alpha=0.8)
    ax.set_xlabel("Hour")
    ax.set_ylabel("Discharge (MW)", color="#1f77b4")
    ax2.set_ylabel("SOC (%)")
    ax.set_title("Battery discharge and state of charge")
    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, fontsize=7, loc="upper right")
    ax.grid(True, alpha=0.3)

    # Shade shortfall hours on all panels
    for ax_ in axes:
        for h in shortfall_hours:
            ax_.axvspan(h + 0.5, h + 1.5, alpha=0.08, color="red")

    fig.suptitle(
        f"IEEE 14-bus + 200 MW datacenter | Battery dispatch verification\n"
        f"Shortfall hours (demand > {cheap_cap:.0f} MW cheap cap): {(shortfall_hours + 1).tolist()}",
        fontsize=10,
    )
    fig.tight_layout()

    out_dir = os.path.join(_PROJECT_ROOT, "outputs")
    os.makedirs(out_dir, exist_ok=True)
    plot_path = os.path.join(out_dir, "battery_dispatch_verification.png")
    fig.savefig(plot_path, dpi=150)
    plt.close(fig)
    print(f"\nPlot saved: {plot_path}")


def _check(label: str, condition: bool, _: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}]  {label}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Battery dispatch verification")
    parser.add_argument(
        "--amplify", type=float, default=1.0,
        help="Demand amplifier for hours 11-14 (default 1.0 = standard profile). "
             "Use e.g. 1.5 for a sharper shortfall window.",
    )
    args = parser.parse_args()
    run_verification(amplify=args.amplify)
