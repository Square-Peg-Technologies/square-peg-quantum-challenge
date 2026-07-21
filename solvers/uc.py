import numpy as np
import cvxpy as cp

from .results import UCResult
from dcopf.losses import true_loss_mw


def _solve_uc_miqp(grid, generators, batteries, bat_locs, T, outages, demand,
                    line_losses=False):
    """Build and solve the UC MIQP (or MIQCP, if line_losses) for a demand.

    `demand` (n_bus, T) is a plain numpy array.
    """
    PTDF = np.array(grid.PTDF)
    fbar = np.array(grid.fbar).flatten()
    n_bus = PTDF.shape[1]
    n_gen = len(generators)
    n_bat = len(batteries)
    n_line = PTDF.shape[0]

    p = cp.Variable((n_gen, T), nonneg=True)
    u = cp.Variable((n_gen, T), boolean=True)
    v = cp.Variable((n_gen, T), boolean=True)

    r_plus  = cp.Variable((n_bat, T), nonneg=True)
    r_minus = cp.Variable((n_bat, T), nonneg=True)
    soc     = cp.Variable((n_bat, T), nonneg=True)
    z       = cp.Variable((n_bat, T), boolean=True)

    loss = cp.Variable((n_line, T), nonneg=True) if line_losses else None

    e_gen = []
    for g in range(n_gen):
        e = np.zeros(n_bus)
        e[generators[g]["bus"] - 1] = 1.0
        e_gen.append(e)

    e_bat = []
    for b in range(n_bat):
        e = np.zeros(n_bus)
        e[bat_locs[b] - 1] = 1.0
        e_bat.append(e)

    obj_terms = []
    for g in range(n_gen):
        ca = generators[g]["cost_a"]
        cb = generators[g]["cost_b"]
        cc = generators[g]["cost_c"]
        sc = generators[g]["startup_cost"]
        obj_terms.append(ca * cp.sum_squares(p[g, :]))
        obj_terms.append(cb * cp.sum(p[g, :]))
        obj_terms.append(cc * cp.sum(u[g, :]))
        obj_terms.append(sc * cp.sum(v[g, :]))

    constraints = []

    for g in range(n_gen):
        p_min = generators[g]["p_min"]
        p_max = generators[g]["p_max"]
        for t in range(T):
            constraints.append(p[g, t] >= p_min * u[g, t])
            constraints.append(p[g, t] <= p_max * u[g, t])
            if outages and g in outages and t in outages[g]:
                constraints.append(u[g, t] == 0)
            if t == 0:
                constraints.append(v[g, t] >= u[g, t])
            else:
                constraints.append(v[g, t] >= u[g, t] - u[g, t - 1])

    for b in range(n_bat):
        pw   = batteries[b]["power_mw"]
        cap  = batteries[b]["capacity_mwh"]
        eff  = batteries[b]["efficiency"]
        soc0 = batteries[b]["init_soc"]
        for t in range(T):
            constraints.append(r_plus[b, t]  <= pw * z[b, t])
            constraints.append(r_minus[b, t] <= pw * (1 - z[b, t]))
            if t == 0:
                constraints.append(soc[b, t] == soc0 + eff * r_plus[b, t] - r_minus[b, t])
            else:
                constraints.append(soc[b, t] == soc[b, t - 1] + eff * r_plus[b, t] - r_minus[b, t])
            constraints.append(soc[b, t] >= 0)
            constraints.append(soc[b, t] <= cap)

    if line_losses:
        R = np.array(grid.R, dtype=float).flatten()
        Sbase = grid.Sbase

    for t in range(T):
        d_t = demand[:, t]
        inj = cp.Constant(np.zeros(n_bus))
        for g in range(n_gen):
            inj = inj + p[g, t] * e_gen[g]
        for b in range(n_bat):
            inj = inj + (r_minus[b, t] - r_plus[b, t]) * e_bat[b]

        net = inj - d_t
        if line_losses:
            constraints.append(cp.sum(net) == cp.sum(loss[:, t]))
        else:
            constraints.append(cp.sum(net) == 0)

        flow = PTDF @ net
        constraints.append(flow <=  fbar)
        constraints.append(flow >= -fbar)

        if line_losses:
            for l in range(n_line):
                constraints.append(R[l] / Sbase * cp.square(flow[l]) <= loss[l, t])

    objective = cp.Minimize(sum(obj_terms))
    prob = cp.Problem(objective, constraints)
    prob.solve(solver="SCIP", verbose=False)

    if p.value is None:
        raise RuntimeError(
            f"UC solver did not find a feasible solution (status: {prob.status})"
        )

    p_val  = p.value
    u_val  = np.round(u.value).astype(int)
    v_val  = np.round(v.value).astype(int)
    rp_val = r_plus.value
    rm_val = r_minus.value
    soc_val = soc.value
    return p_val, u_val, v_val, rp_val, rm_val, soc_val


def run_uc(grid, generators, batteries, bat_locs, T, outages=None, line_losses=False):
    """Unit Commitment MIQP solver using CVXPY with SCIP.

    Parameters
    ----------
    grid       : Case object with .PTDF (6x5), .fbar (list of 6), .power_demand (5xT)
    generators : list of dicts (name, bus, p_min, p_max, cost_a, cost_b, cost_c, startup_cost)
    batteries  : list of dicts (name, power_mw, capacity_mwh, efficiency, init_soc)
    bat_locs   : dict {bat_index: bus_number}  (1-indexed buses)
    T          : number of time steps
    outages    : optional dict {gen_index: set of 0-indexed hours} forcing that
                 generator offline (u[g,t] == 0) for the listed hours — models a
                 contingency (e.g. a documented single-generator-loss event)
                 rather than an economic commitment decision. Hours beyond T are
                 silently ignored. Defaults to no outages.
    line_losses : if True, model I^2R transmission losses exactly, in one
                 solve: each line gets a loss variable lower-bounded by the
                 convex constraint loss_l >= R_l * flow_l**2 / Sbase (flow
                 computed from raw generation - demand, no per-bus loss
                 withdrawal needed), and the system power balance becomes
                 sum(generation) - sum(demand) == sum(loss). Minimizing
                 generation cost pulls each loss_l down to its tight value,
                 so this is exact, not an approximation. Defaults to False
                 (today's lossless DC power flow, single MIQP solve).

    Returns
    -------
    UCResult
    """
    n_gen = len(generators)
    n_bat = len(batteries)
    PTDF = np.array(grid.PTDF)
    fbar = np.array(grid.fbar).flatten()
    n_bus = PTDF.shape[1]
    n_line = PTDF.shape[0]

    if len(set(bat_locs.values())) != len(bat_locs):
        raise ValueError(
            f"bat_locs assigns more than one battery to the same bus: {bat_locs} "
            "— only one battery per node is allowed."
        )

    demand = np.array(grid.power_demand)[:, :T]

    p_val, u_val, v_val, rp_val, rm_val, soc_val = _solve_uc_miqp(
        grid, generators, batteries, bat_locs, T, outages, demand,
        line_losses=line_losses,
    )

    # ------------------------------------------------------------------
    # Hourly costs, congested lines, and realized losses from the solve
    # ------------------------------------------------------------------
    hourly_costs = []
    for t in range(T):
        cost_t = 0.0
        for g in range(n_gen):
            ca = generators[g]["cost_a"]
            cb = generators[g]["cost_b"]
            cc = generators[g]["cost_c"]
            cost_t += ca * p_val[g, t] ** 2 + cb * p_val[g, t] + cc * u_val[g, t]
        hourly_costs.append(cost_t)
    total_cost = float(sum(hourly_costs))

    congested_lines = []
    total_losses_mw = [] if line_losses else None
    for t in range(T):
        inj_val = np.zeros(n_bus)
        for g in range(n_gen):
            inj_val[generators[g]["bus"] - 1] += p_val[g, t]
        for b in range(n_bat):
            inj_val[bat_locs[b] - 1] += rm_val[b, t] - rp_val[b, t]
        flow_val = PTDF @ (inj_val - demand[:, t])
        congested = [i for i in range(len(fbar)) if abs(flow_val[i]) > fbar[i] * 0.999]
        congested_lines.append(congested)
        if line_losses:
            total_losses_mw.append(float(true_loss_mw(flow_val, grid.R, grid.Sbase).sum()))

    return UCResult(
        dispatch=p_val,
        battery_charge=rp_val,
        battery_discharge=rm_val,
        soc=soc_val,
        total_cost=total_cost,
        hourly_costs=hourly_costs,
        congested_lines=congested_lines,
        commitment=u_val,
        startups=v_val,
        total_losses_mw=total_losses_mw,
    )
