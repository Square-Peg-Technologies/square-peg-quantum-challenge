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
from dcopf.losses import true_loss_mw


def _solve_ed_qp(grid, generators, batteries, gen_locs, bat_locs, T, demand,
                  line_losses=False):
    """Build and solve the ED QP (or QCQP, if line_losses) for a given demand.

    `demand` (n_bus, T) is a plain numpy array.
    """
    PTDF = np.array(grid.PTDF)
    fbar = np.array(grid.fbar).flatten()

    n_gen = len(generators)
    n_bat = len(batteries)
    n_bus = PTDF.shape[1]
    n_line = PTDF.shape[0]

    p = cp.Variable((n_gen, T), nonneg=True, name="p")
    r_plus  = cp.Variable((n_bat, T), nonneg=True, name="r_plus")
    r_minus = cp.Variable((n_bat, T), nonneg=True, name="r_minus")
    soc     = cp.Variable((n_bat, T), nonneg=True, name="soc")
    loss = cp.Variable((n_line, T), nonneg=True, name="loss") if line_losses else None

    constraints = []
    objective_terms = []

    for t in range(T):
        gen_inj_expr = cp.Constant(np.zeros(n_bus))
        for g, gen in enumerate(generators):
            bus_idx = gen_locs[g] - 1
            e = np.zeros(n_bus)
            e[bus_idx] = 1.0
            gen_inj_expr = gen_inj_expr + e * p[g, t]

        bat_inj_expr = cp.Constant(np.zeros(n_bus))
        for b, bat in enumerate(batteries):
            bus_idx = bat_locs[b] - 1
            e = np.zeros(n_bus)
            e[bus_idx] = 1.0
            bat_inj_expr = bat_inj_expr + e * (r_minus[b, t] - r_plus[b, t])

        net_inj = gen_inj_expr + bat_inj_expr
        d_t = demand[:, t]

        if line_losses:
            constraints.append(cp.sum(net_inj) == cp.sum(d_t) + cp.sum(loss[:, t]))
        else:
            constraints.append(cp.sum(net_inj) == cp.sum(d_t))

        flow = PTDF @ (net_inj - d_t)
        constraints.append(flow <= fbar.flatten())
        constraints.append(flow >= -fbar.flatten())

        if line_losses:
            R = np.array(grid.R, dtype=float).flatten()
            Sbase = grid.Sbase
            for l in range(n_line):
                constraints.append(R[l] / Sbase * cp.square(flow[l]) <= loss[l, t])

        for g, gen in enumerate(generators):
            constraints.append(p[g, t] >= gen["p_min"])
            constraints.append(p[g, t] <= gen["p_max"])

        for b, bat in enumerate(batteries):
            constraints.append(r_plus[b, t]  <= bat["power_mw"])
            constraints.append(r_minus[b, t] <= bat["power_mw"])

        for g, gen in enumerate(generators):
            a = gen["cost_a"]
            bcoef = gen["cost_b"]
            c = gen["cost_c"]
            objective_terms.append(
                a * cp.sum_squares(p[g, t]) + bcoef * p[g, t] + c
            )

    for b, bat in enumerate(batteries):
        eta = bat["efficiency"]
        cap = bat["capacity_mwh"]
        soc_init = bat["init_soc"]

        constraints.append(
            soc[b, 0] == soc_init + eta * r_plus[b, 0] - r_minus[b, 0]
        )
        for t in range(1, T):
            constraints.append(
                soc[b, t] == soc[b, t - 1] + eta * r_plus[b, t] - r_minus[b, t]
            )
        constraints.append(soc[b, :] <= cap)

    # Tiny battery throughput penalty: charge/discharge is otherwise free in
    # the objective, leaving a degenerate flat optimum — interior-point
    # solvers then return small simultaneous charge+discharge, and HiGHS's QP
    # path can fail to terminate on the flat face. 1e-4 $/MW is far below any
    # real cost and does not affect reported costs (computed from dispatch).
    objective_terms.append(1e-4 * (cp.sum(r_plus) + cp.sum(r_minus)))
    objective = cp.Minimize(cp.sum(objective_terms))
    prob = cp.Problem(objective, constraints)

    # Clarabel first: HiGHS's QP path can spin forever at 100% CPU on this
    # problem class (battery charge/discharge carries no objective cost, so
    # some placements leave a degenerate flat optimal face). Clarabel's
    # interior-point method terminates reliably. HiGHS stays as a fallback
    # with a hard time limit so a hang can never block the pipeline again.
    # Tight Clarabel tolerances: its interior-point solutions otherwise carry
    # ~1e-3 MW fuzz on the battery variables (charge and discharge both
    # slightly positive), which downstream checks read as simultaneous
    # charge/discharge.
    # HiGHS can't handle the quadratic loss constraints (line_losses=True) —
    # its SolverError is caught below and the chain falls through to SCIP.
    for solver_name, solver_opts in (
        ("CLARABEL", {"tol_gap_abs": 1e-10, "tol_gap_rel": 1e-10,
                      "tol_feas": 1e-10}),
        ("HIGHS", {"time_limit": 30.0}),
        ("SCIP", {}),
    ):
        try:
            prob.solve(solver=solver_name, verbose=False, **solver_opts)
        except cp.error.SolverError:
            continue
        if prob.status in ("optimal", "optimal_inaccurate"):
            break

    if prob.status not in ("optimal", "optimal_inaccurate"):
        raise RuntimeError(
            f"ED solver did not find a solution: status={prob.status}"
        )

    p_val   = np.clip(p.value, 0, None)
    rp_val  = np.clip(r_plus.value, 0, None)
    rm_val  = np.clip(r_minus.value, 0, None)
    soc_val = np.clip(soc.value, 0, None)
    return p_val, rp_val, rm_val, soc_val


def run_ed(grid, generators, batteries, gen_locs, bat_locs, T, line_losses=False):
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
    line_losses : if True, model I^2R transmission losses exactly, in one
                 solve: each line gets a loss variable lower-bounded by the
                 convex constraint loss_l >= R_l * flow_l**2 / Sbase (flow
                 computed from raw generation - demand, no per-bus loss
                 withdrawal needed), and the system power balance becomes
                 sum(generation) - sum(demand) == sum(loss). Minimizing
                 generation cost pulls each loss_l down to its tight value,
                 so this is exact, not an approximation. Defaults to False
                 (today's lossless DC power flow, single QP solve).

    Returns
    -------
    EDResult
    """
    if len(set(bat_locs.values())) != len(bat_locs):
        raise ValueError(
            f"bat_locs assigns more than one battery to the same bus: {bat_locs} "
            "— only one battery per node is allowed."
        )

    PTDF = np.array(grid.PTDF)
    fbar = np.array(grid.fbar).flatten()
    demand = np.array(grid.power_demand)[:, :T]
    n_bus = PTDF.shape[1]
    n_line = PTDF.shape[0]

    p_val, rp_val, rm_val, soc_val = _solve_ed_qp(
        grid, generators, batteries, gen_locs, bat_locs, T, demand,
        line_losses=line_losses,
    )

    # ------------------------------------------------------------------
    # Congested lines, realized losses, and hourly costs from the solve
    # ------------------------------------------------------------------
    hourly_costs = []
    congested_lines = []
    total_losses_mw = [] if line_losses else None

    for t in range(T):
        net_inj_t = np.zeros(n_bus)
        for g, gen in enumerate(generators):
            net_inj_t[gen_locs[g] - 1] += p_val[g, t]
        for b, bat in enumerate(batteries):
            net_inj_t[bat_locs[b] - 1] += rm_val[b, t] - rp_val[b, t]

        flow_t = PTDF @ (net_inj_t - demand[:, t])

        cong = [i for i in range(n_line) if abs(flow_t[i]) > fbar[i] * 0.999]
        congested_lines.append(cong)

        if line_losses:
            total_losses_mw.append(float(true_loss_mw(flow_t, grid.R, grid.Sbase).sum()))

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
        total_losses_mw=total_losses_mw,
    )
