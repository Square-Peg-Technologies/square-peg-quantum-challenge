import numpy as np
from pyscipopt import Model, quicksum

from .results import UCResult, SitingMIPResult


def run_siting_mip(grid, generators, batteries, T) -> SitingMIPResult:
    """Joint battery-siting + unit-commitment MILP via PySCIPOpt.

    Finds the globally optimal battery bus placement and generator commitment
    schedule in a single SCIP solve. SOS1 constraints on the siting variables
    let SCIP branch efficiently without needing indicator constraints.

    Parameters
    ----------
    grid       : Case object with .PTDF, .fbar, .power_demand
    generators : list of dicts (name, bus, p_min, p_max, cost_a, cost_b, cost_c, startup_cost)
    batteries  : list of dicts (name, power_mw, capacity_mwh, efficiency, init_soc)
    T          : number of time steps

    Returns
    -------
    SitingMIPResult
    """
    n_gen   = len(generators)
    n_bat   = len(batteries)
    PTDF    = np.array(grid.PTDF)
    fbar    = np.array(grid.fbar).flatten()
    n_bus   = PTDF.shape[1]
    n_lines = PTDF.shape[0]

    model = Model("battery_siting")
    model.hideOutput()

    # ── Variables ─────────────────────────────────────────────────────────────

    p = {}; u = {}; v = {}
    for g in range(n_gen):
        pmax = generators[g]["p_max"]
        for t in range(T):
            p[g, t] = model.addVar(lb=0, ub=pmax,  name=f"p_{g}_{t}")
            u[g, t] = model.addVar(vtype="B",       name=f"u_{g}_{t}")
            v[g, t] = model.addVar(vtype="B",       name=f"v_{g}_{t}")

    r_plus = {}; r_minus = {}; soc = {}; z = {}
    for b in range(n_bat):
        pw  = batteries[b]["power_mw"]
        cap = batteries[b]["capacity_mwh"]
        for t in range(T):
            r_plus[b, t]  = model.addVar(lb=0, ub=pw,  name=f"rp_{b}_{t}")
            r_minus[b, t] = model.addVar(lb=0, ub=pw,  name=f"rm_{b}_{t}")
            soc[b, t]     = model.addVar(lb=0, ub=cap, name=f"soc_{b}_{t}")
            z[b, t]       = model.addVar(vtype="B",    name=f"z_{b}_{t}")

    # x[b,n] = 1 → battery b placed at bus n
    x = {}
    for b in range(n_bat):
        for n in range(n_bus):
            x[b, n] = model.addVar(vtype="B", name=f"x_{b}_{n}")

    # y_plus[b,n,t]  = x[b,n] * r_plus[b,t]   (linearisation)
    # y_minus[b,n,t] = x[b,n] * r_minus[b,t]
    y_plus = {}; y_minus = {}
    for b in range(n_bat):
        pw = batteries[b]["power_mw"]
        for n in range(n_bus):
            for t in range(T):
                y_plus[b, n, t]  = model.addVar(lb=0, ub=pw, name=f"yp_{b}_{n}_{t}")
                y_minus[b, n, t] = model.addVar(lb=0, ub=pw, name=f"ym_{b}_{n}_{t}")

    # ── Objective ─────────────────────────────────────────────────────────────
    # setObjective only accepts linear expressions in PySCIPOpt 6.x.
    # Quadratic generation costs (cost_a * p^2) are handled via an auxiliary
    # variable q_quad with a nonlinear constraint q_quad >= sum(ca * p^2).

    linear_obj = []
    quad_terms = []
    for g in range(n_gen):
        ca = generators[g]["cost_a"]
        cb = generators[g]["cost_b"]
        cc = generators[g]["cost_c"]
        sc = generators[g]["startup_cost"]
        for t in range(T):
            if ca != 0.0:
                quad_terms.append(ca * p[g, t] * p[g, t])
            linear_obj.append(cb * p[g, t])
            linear_obj.append(cc * u[g, t])
            linear_obj.append(sc * v[g, t])

    if quad_terms:
        q_quad = model.addVar(lb=0, name="q_quad")
        model.addCons(q_quad >= quicksum(quad_terms))
        linear_obj.append(q_quad)

    model.setObjective(quicksum(linear_obj), sense="minimize")

    # ── Generator constraints ─────────────────────────────────────────────────

    for g in range(n_gen):
        p_min = generators[g]["p_min"]
        p_max = generators[g]["p_max"]
        for t in range(T):
            model.addCons(p[g, t] >= p_min * u[g, t])
            model.addCons(p[g, t] <= p_max * u[g, t])
            if t == 0:
                model.addCons(v[g, t] >= u[g, t])
            else:
                model.addCons(v[g, t] >= u[g, t] - u[g, t - 1])

    # ── Battery constraints ───────────────────────────────────────────────────

    for b in range(n_bat):
        pw   = batteries[b]["power_mw"]
        eff  = batteries[b]["efficiency"]
        soc0 = batteries[b]["init_soc"]
        for t in range(T):
            model.addCons(r_plus[b, t]  <= pw * z[b, t])
            model.addCons(r_minus[b, t] <= pw * (1 - z[b, t]))
            if t == 0:
                model.addCons(soc[b, t] == soc0 + eff * r_plus[b, t] - r_minus[b, t])
            else:
                model.addCons(soc[b, t] == soc[b, t - 1] + eff * r_plus[b, t] - r_minus[b, t])

    # ── Siting: each battery placed at exactly one bus ────────────────────────

    for b in range(n_bat):
        model.addCons(quicksum(x[b, n] for n in range(n_bus)) == 1)

    # SOS1: SCIP branches on x[b,:] as a "pick one" set, avoiding the
    # exponential binary branching that makes big-M slow.
    for b in range(n_bat):
        model.addConsSOS1([x[b, n] for n in range(n_bus)])

    # ── Big-M linearisation ───────────────────────────────────────────────────
    # With SOS1 branching, x[b,n] is fixed early in the tree, making the
    # big-M constraints tight at each node — no LP relaxation weakness.

    for b in range(n_bat):
        M = batteries[b]["power_mw"]
        for n in range(n_bus):
            for t in range(T):
                model.addCons(y_plus[b, n, t]  <= r_plus[b, t])
                model.addCons(y_plus[b, n, t]  <= M * x[b, n])
                model.addCons(y_plus[b, n, t]  >= r_plus[b, t]  - M * (1 - x[b, n]))
                model.addCons(y_minus[b, n, t] <= r_minus[b, t])
                model.addCons(y_minus[b, n, t] <= M * x[b, n])
                model.addCons(y_minus[b, n, t] >= r_minus[b, t] - M * (1 - x[b, n]))

    # ── Power balance and line flow constraints ───────────────────────────────

    for t in range(T):
        demand = grid.power_demand[:, t]

        # Net injection per bus as a dict of SCIP expressions
        net = {}
        for n in range(n_bus):
            gen_inj = quicksum(
                p[g, t] for g in range(n_gen) if generators[g]["bus"] - 1 == n
            )
            bat_inj = quicksum(
                y_minus[b, n, t] - y_plus[b, n, t] for b in range(n_bat)
            )
            net[n] = gen_inj + bat_inj - demand[n]

        # Power balance: sum of net injections == 0
        model.addCons(quicksum(net[n] for n in range(n_bus)) == 0)

        # Line flows within limits
        for l in range(n_lines):
            flow_l = quicksum(PTDF[l, n] * net[n] for n in range(n_bus))
            model.addCons(flow_l <=  fbar[l])
            model.addCons(flow_l >= -fbar[l])

    # ── Solve ─────────────────────────────────────────────────────────────────

    model.optimize()

    status = model.getStatus()
    if status not in ("optimal", "bestsol"):
        raise RuntimeError(f"SCIP did not find a feasible solution (status: {status})")

    # ── Extract solution ──────────────────────────────────────────────────────

    bat_locs = {}
    for b in range(n_bat):
        for n in range(n_bus):
            if model.getVal(x[b, n]) > 0.5:
                bat_locs[b] = n + 1   # 1-indexed
                break
    bus_tuple = tuple(bat_locs[b] for b in range(n_bat))

    p_val   = np.array([[model.getVal(p[g, t])          for t in range(T)] for g in range(n_gen)])
    u_val   = np.array([[round(model.getVal(u[g, t]))   for t in range(T)] for g in range(n_gen)], dtype=int)
    v_val   = np.array([[round(model.getVal(v[g, t]))   for t in range(T)] for g in range(n_gen)], dtype=int)
    rp_val  = np.array([[model.getVal(r_plus[b, t])     for t in range(T)] for b in range(n_bat)])
    rm_val  = np.array([[model.getVal(r_minus[b, t])    for t in range(T)] for b in range(n_bat)])
    soc_val = np.array([[model.getVal(soc[b, t])        for t in range(T)] for b in range(n_bat)])

    total_cost = model.getObjVal()

    hourly_costs = []
    for t in range(T):
        cost_t = 0.0
        for g in range(n_gen):
            ca = generators[g]["cost_a"]
            cb = generators[g]["cost_b"]
            cc = generators[g]["cost_c"]
            cost_t += ca * p_val[g, t] ** 2 + cb * p_val[g, t] + cc * u_val[g, t]
        hourly_costs.append(cost_t)

    congested_lines = []
    for t in range(T):
        demand = grid.power_demand[:, t]
        inj_val = np.zeros(n_bus)
        for g in range(n_gen):
            inj_val[generators[g]["bus"] - 1] += p_val[g, t]
        for b in range(n_bat):
            inj_val[bat_locs[b] - 1] += rm_val[b, t] - rp_val[b, t]
        net_val  = inj_val - demand
        flow_val = PTDF @ net_val
        congested = [i for i in range(len(fbar)) if abs(flow_val[i]) > fbar[i] * 0.999]
        congested_lines.append(congested)

    uc_result = UCResult(
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

    return SitingMIPResult(
        bus_tuple=bus_tuple,
        bat_locs=bat_locs,
        uc_result=uc_result,
        total_cost=total_cost,
    )
