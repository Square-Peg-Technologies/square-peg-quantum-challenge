"""
Economic Dispatch solver for the PJM 5-bus system.

Uses CVXPY with HiGHS for the LP/QP core and handles batteries as
continuous variables (no binary z). In ED the optimizer naturally avoids
simultaneous charge and discharge because it is never cost-beneficial;
we skip the binary z to keep the problem a QP solvable directly by HiGHS.
"""

import numpy as np
import cvxpy as cp

from .results import EDResult


def run_ed(grid, generators, batteries, gen_locs, bat_locs, T):
    """
    Run Economic Dispatch over T hours.

    Parameters
    ----------
    grid       : Case object (PTDF 6x5, fbar list len 6, power_demand 5xT,
                  plobar 5x1, phibar 5x1)
    generators : list of dicts from assets.GENERATORS
    batteries  : list of dicts from assets.BATTERIES
    gen_locs   : dict {gen_index: bus_number}  (buses 1-indexed)
    bat_locs   : dict {bat_index: bus_number}  (buses 1-indexed)
    T          : number of hours

    Returns
    -------
    EDResult
    """
    PTDF = np.array(grid.PTDF)            # (6, 5)
    fbar = np.array(grid.fbar).flatten()  # (6,)
    demand = np.array(grid.power_demand)  # (5, T)

    n_gen = len(generators)
    n_bat = len(batteries)
    n_bus = PTDF.shape[1]   # 5
    n_line = PTDF.shape[0]  # 6

    # ------------------------------------------------------------------
    # Decision variables
    # ------------------------------------------------------------------
    # Generator dispatch: (n_gen, T)
    p = cp.Variable((n_gen, T), nonneg=True, name="p")

    # Battery charge / discharge / state-of-charge: (n_bat, T)
    r_plus  = cp.Variable((n_bat, T), nonneg=True, name="r_plus")   # charge
    r_minus = cp.Variable((n_bat, T), nonneg=True, name="r_minus")  # discharge
    soc     = cp.Variable((n_bat, T), nonneg=True, name="soc")

    constraints = []
    objective_terms = []

    # ------------------------------------------------------------------
    # Build per-hour constraints
    # ------------------------------------------------------------------
    for t in range(T):
        # Generator contributions
        gen_inj_expr = cp.Constant(np.zeros(n_bus))
        for g, gen in enumerate(generators):
            bus_idx = gen_locs[g] - 1   # 0-indexed
            e = np.zeros(n_bus)
            e[bus_idx] = 1.0
            gen_inj_expr = gen_inj_expr + e * p[g, t]

        # Battery contributions (discharge injects, charge absorbs)
        bat_inj_expr = cp.Constant(np.zeros(n_bus))
        for b, bat in enumerate(batteries):
            bus_idx = bat_locs[b] - 1
            e = np.zeros(n_bus)
            e[bus_idx] = 1.0
            bat_inj_expr = bat_inj_expr + e * (r_minus[b, t] - r_plus[b, t])

        net_inj = gen_inj_expr + bat_inj_expr  # shape (5,) CVXPY expression
        d_t = demand[:, t]                      # (5,) numpy

        # Power balance: total injection == total demand
        constraints.append(cp.sum(net_inj) == cp.sum(d_t))

        # Line flow limits: PTDF @ (net_inj - demand) in [-fbar, fbar]
        flow = PTDF @ (net_inj - d_t)           # (6,) expression
        constraints.append(flow <= fbar.flatten())
        constraints.append(flow >= -fbar.flatten())

        # Generator bounds
        for g, gen in enumerate(generators):
            constraints.append(p[g, t] >= gen["p_min"])
            constraints.append(p[g, t] <= gen["p_max"])

        # Battery charge/discharge rate limits
        for b, bat in enumerate(batteries):
            constraints.append(r_plus[b, t]  <= bat["power_mw"])
            constraints.append(r_minus[b, t] <= bat["power_mw"])

        # Generator cost term (quadratic)
        for g, gen in enumerate(generators):
            a = gen["cost_a"]
            bcoef = gen["cost_b"]
            c = gen["cost_c"]
            # a*p^2 + b*p + c  -> use cp.sum_squares for the quadratic term
            objective_terms.append(
                a * cp.sum_squares(p[g, t]) + bcoef * p[g, t] + c
            )

    # ------------------------------------------------------------------
    # Battery dynamics (across hours)
    # ------------------------------------------------------------------
    for b, bat in enumerate(batteries):
        eta = bat["efficiency"]
        cap = bat["capacity_mwh"]
        soc_init = bat["init_soc"]

        # Hour 0: SoC initialised from init_soc
        constraints.append(
            soc[b, 0] == soc_init + eta * r_plus[b, 0] - r_minus[b, 0]
        )
        # Hours 1..T-1: carry-forward
        for t in range(1, T):
            constraints.append(
                soc[b, t] == soc[b, t - 1] + eta * r_plus[b, t] - r_minus[b, t]
            )
        # SoC bounds (for all hours)
        constraints.append(soc[b, :] <= cap)

    # ------------------------------------------------------------------
    # Solve
    # ------------------------------------------------------------------
    objective = cp.Minimize(cp.sum(objective_terms))
    prob = cp.Problem(objective, constraints)

    try:
        prob.solve(solver="HIGHS", verbose=False)
    except cp.error.SolverError:
        prob.solve(solver="SCIP", verbose=False)

    if prob.status not in ("optimal", "optimal_inaccurate"):
        raise RuntimeError(
            f"ED solver did not find a solution: status={prob.status}"
        )

    # ------------------------------------------------------------------
    # Extract solution values
    # ------------------------------------------------------------------
    p_val      = p.value                  # (n_gen, T)
    rp_val     = r_plus.value             # (n_bat, T)
    rm_val     = r_minus.value            # (n_bat, T)
    soc_val    = soc.value                # (n_bat, T)

    # Clip tiny numerical noise to zero
    p_val   = np.clip(p_val,   0, None)
    rp_val  = np.clip(rp_val,  0, None)
    rm_val  = np.clip(rm_val,  0, None)
    soc_val = np.clip(soc_val, 0, None)

    # Hourly costs and congested lines
    hourly_costs = []
    congested_lines = []

    for t in range(T):
        # Rebuild net injection with solved values
        net_inj_t = np.zeros(n_bus)
        for g, gen in enumerate(generators):
            bus_idx = gen_locs[g] - 1
            net_inj_t[bus_idx] += p_val[g, t]
        for b, bat in enumerate(batteries):
            bus_idx = bat_locs[b] - 1
            net_inj_t[bus_idx] += rm_val[b, t] - rp_val[b, t]

        flow_t = PTDF @ (net_inj_t - demand[:, t])   # (6,)

        # Congested lines: |flow| > 0.999 * fbar
        cong = [i for i in range(n_line) if abs(flow_t[i]) > fbar[i] * 0.999]
        congested_lines.append(cong)

        # Hour cost using solved dispatch
        hcost = 0.0
        for g, gen in enumerate(generators):
            pg = p_val[g, t]
            hcost += gen["cost_a"] * pg**2 + gen["cost_b"] * pg + gen["cost_c"]
        hourly_costs.append(float(hcost))

    total_cost = float(sum(hourly_costs))

    return EDResult(
        dispatch=p_val,
        battery_charge=rp_val,
        battery_discharge=rm_val,
        soc=soc_val,
        total_cost=total_cost,
        hourly_costs=hourly_costs,
        congested_lines=congested_lines,
    )
