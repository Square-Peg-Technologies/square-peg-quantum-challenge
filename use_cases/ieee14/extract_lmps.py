"""
Extract LMPs and shadow prices from a no-battery DC-OPF on ieee14.

Runs Economic Dispatch with no batteries and the datacenter load at bus 1.
Extracts:
  - LMP at each bus for each of the 24 hours  (14 x 24 table)
  - Shadow price on each line for each hour    (20 x 24 table)
  - LMP variance per bus                       (14-element summary)

Outputs:
  lmps_14x24.csv          — LMP table (buses as rows, hours as columns)
  shadow_prices_20x24.csv — shadow price table (lines as rows, hours as columns)
  lmp_summary.csv         — per-bus LMP mean, variance, std

Run from the repo root:
    python use_cases/ieee14/extract_lmps.py

Or directly:
    cd use_cases/ieee14 && python extract_lmps.py
"""

import sys
import os

# Allow running from either the repo root or the use_cases/ieee14 directory
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.join(_here, "..", "..")
sys.path.insert(0, _root)

import numpy as np
import cvxpy as cp
import csv

from ieee14 import Case
import importlib
import sys as _sys
# 4batt_dcbus1.py does a bare "from assets import GENERATORS, BATTERIES" to
# inherit the base battery file (4batt.py) — populate sys.modules["assets"]
# with it first, same trick main.py's loader uses.
_sys.modules["assets"] = importlib.import_module("4batt")
assets_mod = importlib.import_module("4batt_dcbus1")


def run_ed_with_duals(grid, generators, T):
    """
    Run no-battery DC-OPF and return LMPs and shadow prices.

    LMP at bus i = λ_t (energy price dual) + Σ_l PTDF_l,i * (μ_l,t^- - μ_l,t^+)
    where μ^+ is dual on upper flow limit, μ^- is dual on lower flow limit.

    Shadow price on line l at hour t = μ_l,t^+ - μ_l,t^-
    (positive = upper limit binding, negative = lower limit binding)
    """
    PTDF  = np.array(grid.PTDF)           # (n_line, n_bus)
    fbar  = np.array(grid.fbar).flatten() # (n_line,)
    demand = np.array(grid.power_demand)  # (n_bus, T)

    n_gen  = len(generators)
    n_bus  = PTDF.shape[1]
    n_line = PTDF.shape[0]

    p = cp.Variable((n_gen, T), nonneg=True)

    constraints = []
    balance_cons = []   # one per hour — dual = system energy price λ_t
    flow_up_cons = []   # one per hour — dual = μ^+ per line
    flow_dn_cons = []   # one per hour — dual = μ^- per line

    objective_terms = []

    # Build per-bus injection expressions from generator locations
    gen_buses = [gen["bus"] - 1 for gen in generators]  # 0-indexed

    for t in range(T):
        # Net injection vector (n_bus,)
        inj = cp.Constant(np.zeros(n_bus))
        for g in range(n_gen):
            e = np.zeros(n_bus)
            e[gen_buses[g]] = 1.0
            inj = inj + e * p[g, t]

        d_t = demand[:, t]

        # Power balance (one per hour) — dual is λ_t
        c_bal = cp.sum(inj) == cp.sum(d_t)
        constraints.append(c_bal)
        balance_cons.append(c_bal)

        # Line flow limits — dual μ^+ (upper) and μ^- (lower)
        flow = PTDF @ (inj - d_t)
        c_up = flow <= fbar
        c_dn = flow >= -fbar
        constraints.append(c_up)
        constraints.append(c_dn)
        flow_up_cons.append(c_up)
        flow_dn_cons.append(c_dn)

        # Generator bounds
        for g, gen in enumerate(generators):
            constraints.append(p[g, t] >= gen["p_min"])
            constraints.append(p[g, t] <= gen["p_max"])

        # Cost
        for g, gen in enumerate(generators):
            a, b, c = gen["cost_a"], gen["cost_b"], gen["cost_c"]
            objective_terms.append(a * cp.sum_squares(p[g, t]) + b * p[g, t] + c)

    prob = cp.Problem(cp.Minimize(cp.sum(objective_terms)), constraints)
    prob.solve(solver="HIGHS", verbose=False)

    if prob.status not in ("optimal", "optimal_inaccurate"):
        raise RuntimeError(f"Solve failed: {prob.status}")

    print(f"Total 24h dispatch cost (no batteries): ${prob.value:,.0f}")

    # Extract duals
    # CVXPY sign convention: dual_value for equality constraints is the multiplier
    # for inequality c <= 0 it is non-negative (shadow price on the upper bound)
    lmps        = np.zeros((n_bus, T))
    shadow_prices = np.zeros((n_line, T))

    for t in range(T):
        lam = float(balance_cons[t].dual_value)      # system energy price
        mu_up = np.array(flow_up_cons[t].dual_value).flatten()  # (n_line,)
        mu_dn = np.array(flow_dn_cons[t].dual_value).flatten()  # (n_line,)

        # Net shadow price per line (positive = upper limit binding)
        mu_net = mu_up - mu_dn
        shadow_prices[:, t] = mu_net

        # Nodal LMP: energy price + congestion component
        # CVXPY dual_value for equality constraints is negative of the Lagrange multiplier
        # so LMP = -lam + PTDF.T @ mu_net
        lmps[:, t] = -lam + PTDF.T @ mu_net

    return lmps, shadow_prices, prob.value


def write_csv(filepath, data, row_labels, col_labels):
    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([""] + col_labels)
        for i, row in enumerate(data):
            writer.writerow([row_labels[i]] + [f"{v:.4f}" for v in row])
    print(f"Saved: {filepath}")


def main():
    T = 24
    grid = Case()

    # Inject datacenter load
    dc_bus = getattr(assets_mod, "DATACENTER_BUS", None)
    dc_mw  = float(getattr(assets_mod, "DATACENTER_MW", 0))
    if dc_bus and dc_mw > 0:
        grid.power_demand[dc_bus - 1, :] += dc_mw
        print(f"Datacenter: {dc_mw:.0f} MW injected at bus {dc_bus}")

    generators = assets_mod.GENERATORS
    n_bus  = grid.PTDF.shape[1]   # 14
    n_line = grid.PTDF.shape[0]   # 20

    print(f"Running no-battery DC-OPF on ieee14 ({n_bus} buses, {n_line} lines, T={T}h)...")
    lmps, shadow_prices, total_cost = run_ed_with_duals(grid, generators, T)

    # Labels
    bus_labels  = [f"Bus {i+1}" for i in range(n_bus)]
    line_labels = [f"Line {i+1}" for i in range(n_line)]
    hour_labels = [f"h{t+1:02d}" for t in range(T)]

    # Output directory
    out_dir = os.path.join(_root, "outputs")
    os.makedirs(out_dir, exist_ok=True)

    # LMP table (14 x 24)
    write_csv(os.path.join(out_dir, "lmps_14x24.csv"), lmps, bus_labels, hour_labels)

    # Shadow price table (20 x 24)
    write_csv(os.path.join(out_dir, "shadow_prices_20x24.csv"), shadow_prices, line_labels, hour_labels)

    # LMP summary per bus
    lmp_mean = lmps.mean(axis=1)
    lmp_var  = lmps.var(axis=1)
    lmp_std  = lmps.std(axis=1)

    summary_path = os.path.join(out_dir, "lmp_summary.csv")
    with open(summary_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Bus", "Mean LMP ($/MWh)", "Variance", "Std Dev", "Min", "Max"])
        for i in range(n_bus):
            writer.writerow([
                f"Bus {i+1}",
                f"{lmp_mean[i]:.4f}",
                f"{lmp_var[i]:.4f}",
                f"{lmp_std[i]:.4f}",
                f"{lmps[i].min():.4f}",
                f"{lmps[i].max():.4f}",
            ])
    print(f"Saved: {summary_path}")

    # Print summary to terminal
    print("\nLMP Summary (no-battery DC-OPF, ieee14 + 200MW DC at bus 1):")
    print(f"{'Bus':<8} {'Mean $/MWh':>12} {'Variance':>12} {'Std Dev':>10} {'Min':>8} {'Max':>8}")
    print("-" * 62)
    for i in range(n_bus):
        print(f"Bus {i+1:<4} {lmp_mean[i]:>12.4f} {lmp_var[i]:>12.4f} {lmp_std[i]:>10.4f} "
              f"{lmps[i].min():>8.4f} {lmps[i].max():>8.4f}")

    print("\nBinding lines (any hour with |shadow price| > 0.01):")
    branch_pairs = [
        (1,2),(1,5),(2,3),(2,4),(2,5),(3,4),(4,5),(4,7),(4,9),(5,6),
        (6,11),(6,12),(6,13),(7,8),(7,9),(9,10),(9,14),(10,11),(12,13),(13,14)
    ]
    for l in range(n_line):
        max_shadow = np.max(np.abs(shadow_prices[l]))
        if max_shadow > 0.01:
            hours_binding = [t+1 for t in range(T) if abs(shadow_prices[l, t]) > 0.01]
            fr, to = branch_pairs[l]
            print(f"  Line {l+1:2d} ({fr:2d}-{to:2d}): max shadow = {max_shadow:.4f}, "
                  f"binding in hours {hours_binding}")


if __name__ == "__main__":
    main()
