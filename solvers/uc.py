import numpy as np
import cvxpy as cp

from .results import UCResult


def run_uc(grid, generators, batteries, bat_locs, T, outages=None):
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

    Returns
    -------
    UCResult
    """
    n_gen = len(generators)
    n_bat = len(batteries)
    PTDF = np.array(grid.PTDF)
    fbar = np.array(grid.fbar).flatten()
    n_bus = PTDF.shape[1]

    if len(set(bat_locs.values())) != len(bat_locs):
        raise ValueError(
            f"bat_locs assigns more than one battery to the same bus: {bat_locs} "
            "— only one battery per node is allowed."
        )

    # Decision variables
    p = cp.Variable((n_gen, T), nonneg=True)   # generator output
    u = cp.Variable((n_gen, T), boolean=True)  # commitment (on/off)
    v = cp.Variable((n_gen, T), boolean=True)  # startup indicator

    r_plus  = cp.Variable((n_bat, T), nonneg=True)  # battery charge
    r_minus = cp.Variable((n_bat, T), nonneg=True)  # battery discharge
    soc     = cp.Variable((n_bat, T), nonneg=True)  # state of charge
    z       = cp.Variable((n_bat, T), boolean=True) # charge direction (1=charging)

    # Unit vectors for each generator bus
    e_gen = []
    for g in range(n_gen):
        e = np.zeros(n_bus)
        e[generators[g]["bus"] - 1] = 1.0
        e_gen.append(e)

    # Unit vectors for each battery bus
    e_bat = []
    for b in range(n_bat):
        e = np.zeros(n_bus)
        e[bat_locs[b] - 1] = 1.0
        e_bat.append(e)

    # Objective
    obj_terms = []
    for g in range(n_gen):
        ca = generators[g]["cost_a"]
        cb = generators[g]["cost_b"]
        cc = generators[g]["cost_c"]
        sc = generators[g]["startup_cost"]
        # quadratic generation cost + no-load cost + startup cost
        obj_terms.append(ca * cp.sum_squares(p[g, :]))
        obj_terms.append(cb * cp.sum(p[g, :]))
        obj_terms.append(cc * cp.sum(u[g, :]))
        obj_terms.append(sc * cp.sum(v[g, :]))

    objective = cp.Minimize(sum(obj_terms))

    constraints = []

    # Generator constraints
    for g in range(n_gen):
        p_min = generators[g]["p_min"]
        p_max = generators[g]["p_max"]
        for t in range(T):
            # output bounds with commitment
            constraints.append(p[g, t] >= p_min * u[g, t])
            constraints.append(p[g, t] <= p_max * u[g, t])
            # forced outage: contingency, not an economic commitment choice
            if outages and g in outages and t in outages[g]:
                constraints.append(u[g, t] == 0)
            # startup indicator: v[g,t] >= u[g,t] - u[g,t-1]
            if t == 0:
                constraints.append(v[g, t] >= u[g, t])
            else:
                constraints.append(v[g, t] >= u[g, t] - u[g, t - 1])

    # Battery constraints
    for b in range(n_bat):
        pw   = batteries[b]["power_mw"]
        cap  = batteries[b]["capacity_mwh"]
        eff  = batteries[b]["efficiency"]
        soc0 = batteries[b]["init_soc"]
        for t in range(T):
            # charge/discharge direction
            constraints.append(r_plus[b, t]  <= pw * z[b, t])
            constraints.append(r_minus[b, t] <= pw * (1 - z[b, t]))
            # SOC evolution
            if t == 0:
                constraints.append(soc[b, t] == soc0 + eff * r_plus[b, t] - r_minus[b, t])
            else:
                constraints.append(soc[b, t] == soc[b, t - 1] + eff * r_plus[b, t] - r_minus[b, t])
            # SOC bounds
            constraints.append(soc[b, t] >= 0)
            constraints.append(soc[b, t] <= cap)

    # Per-timestep power balance and line flow constraints
    for t in range(T):
        demand = grid.power_demand[:, t]

        # Net injection expression (CVXPY)
        inj = cp.Constant(np.zeros(n_bus))
        for g in range(n_gen):
            inj = inj + p[g, t] * e_gen[g]
        for b in range(n_bat):
            inj = inj + (r_minus[b, t] - r_plus[b, t]) * e_bat[b]

        net = inj - demand

        # Power balance: total injection equals total demand
        constraints.append(cp.sum(net) == 0)

        # Line flow limits: PTDF @ net in [-fbar, fbar]
        flow = PTDF @ net
        constraints.append(flow <=  fbar)
        constraints.append(flow >= -fbar)

    # Solve
    prob = cp.Problem(objective, constraints)
    prob.solve(solver="SCIP", verbose=False)

    if p.value is None:
        raise RuntimeError(
            f"UC solver did not find a feasible solution (status: {prob.status})"
        )

    # Extract solution values
    p_val   = p.value
    u_val   = np.round(u.value).astype(int)
    v_val   = np.round(v.value).astype(int)
    rp_val  = r_plus.value
    rm_val  = r_minus.value
    soc_val = soc.value

    total_cost = float(prob.value)

    # Hourly costs (generation only, no battery cost)
    hourly_costs = []
    for t in range(T):
        cost_t = 0.0
        for g in range(n_gen):
            ca = generators[g]["cost_a"]
            cb = generators[g]["cost_b"]
            cc = generators[g]["cost_c"]
            cost_t += ca * p_val[g, t] ** 2 + cb * p_val[g, t] + cc * u_val[g, t]
        hourly_costs.append(cost_t)

    # Congested lines per hour
    congested_lines = []
    for t in range(T):
        demand = grid.power_demand[:, t]
        inj_val = np.zeros(n_bus)
        for g in range(n_gen):
            inj_val[generators[g]["bus"] - 1] += p_val[g, t]
        for b in range(n_bat):
            bus_idx = bat_locs[b] - 1
            inj_val[bus_idx] += rm_val[b, t] - rp_val[b, t]
        net_val = inj_val - demand
        flow_val = PTDF @ net_val
        congested = [i for i in range(len(fbar)) if abs(flow_val[i]) > fbar[i] * 0.999]
        congested_lines.append(congested)

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
    )
