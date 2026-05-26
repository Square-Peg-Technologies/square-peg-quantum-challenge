import numpy as np
import cvxpy as cp

from .results import UCResult, SitingResult


def run_siting_mip(grid, generators, batteries, T, n_results=10) -> SitingResult:
    """Joint battery-siting + unit-commitment MILP.

    Solves placement and commitment simultaneously. Top-K placements are
    recovered by adding a no-good cut after each solve and re-solving.

    Parameters
    ----------
    grid       : Case object with .PTDF, .fbar, .power_demand
    generators : list of dicts (name, bus, p_min, p_max, cost_a, cost_b, cost_c, startup_cost)
    batteries  : list of dicts (name, power_mw, capacity_mwh, efficiency, init_soc)
    T          : number of time steps
    n_results  : how many top placements to return

    Returns
    -------
    SitingResult
    """
    n_gen = len(generators)
    n_bat = len(batteries)
    PTDF  = np.array(grid.PTDF)
    fbar  = np.array(grid.fbar).flatten()
    n_bus = PTDF.shape[1]

    # Unit vectors for generator buses
    e_gen = []
    for g in range(n_gen):
        e = np.zeros(n_bus)
        e[generators[g]["bus"] - 1] = 1.0
        e_gen.append(e)

    # Identity matrix — one column per bus for battery injection
    e_bus = np.eye(n_bus)

    # ── Decision variables ────────────────────────────────────────────────────
    p       = cp.Variable((n_gen, T), nonneg=True)   # generator output
    u       = cp.Variable((n_gen, T), boolean=True)  # commitment
    v       = cp.Variable((n_gen, T), boolean=True)  # startup indicator

    r_plus  = cp.Variable((n_bat, T), nonneg=True)   # battery charge rate
    r_minus = cp.Variable((n_bat, T), nonneg=True)   # battery discharge rate
    soc     = cp.Variable((n_bat, T), nonneg=True)   # state of charge
    z       = cp.Variable((n_bat, T), boolean=True)  # charge direction (1=charging)

    x       = cp.Variable((n_bat, n_bus), boolean=True)   # siting: x[b,n]=1 → bat b at bus n
    y_plus  = cp.Variable((n_bat, n_bus, T), nonneg=True) # linearisation of x*r_plus
    y_minus = cp.Variable((n_bat, n_bus, T), nonneg=True) # linearisation of x*r_minus

    # ── Objective (identical to run_uc) ──────────────────────────────────────
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
    objective = cp.Minimize(sum(obj_terms))

    # ── Base constraints ──────────────────────────────────────────────────────
    constraints = []

    # Generator bounds and startup (same as run_uc)
    for g in range(n_gen):
        p_min = generators[g]["p_min"]
        p_max = generators[g]["p_max"]
        for t in range(T):
            constraints.append(p[g, t] >= p_min * u[g, t])
            constraints.append(p[g, t] <= p_max * u[g, t])
            if t == 0:
                constraints.append(v[g, t] >= u[g, t])
            else:
                constraints.append(v[g, t] >= u[g, t] - u[g, t - 1])

    # Battery operation (same as run_uc)
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

    # Siting: each battery placed at exactly one bus
    for b in range(n_bat):
        constraints.append(cp.sum(x[b, :]) == 1)

    # Big-M linearisation: y_plus[b,n,t]  = x[b,n] * r_plus[b,t]
    #                       y_minus[b,n,t] = x[b,n] * r_minus[b,t]
    for b in range(n_bat):
        M = batteries[b]["power_mw"]
        for n in range(n_bus):
            for t in range(T):
                constraints.append(y_plus[b, n, t]  <= M * x[b, n])
                constraints.append(y_plus[b, n, t]  <= r_plus[b, t])
                constraints.append(y_plus[b, n, t]  >= r_plus[b, t]  - M * (1 - x[b, n]))
                constraints.append(y_minus[b, n, t] <= M * x[b, n])
                constraints.append(y_minus[b, n, t] <= r_minus[b, t])
                constraints.append(y_minus[b, n, t] >= r_minus[b, t] - M * (1 - x[b, n]))

    # Power balance and line flows with siting-aware battery injection
    for t in range(T):
        demand = grid.power_demand[:, t]
        inj = cp.Constant(np.zeros(n_bus))
        for g in range(n_gen):
            inj = inj + p[g, t] * e_gen[g]
        for b in range(n_bat):
            for n in range(n_bus):
                inj = inj + (y_minus[b, n, t] - y_plus[b, n, t]) * e_bus[n]
        net = inj - demand
        constraints.append(cp.sum(net) == 0)
        flow = PTDF @ net
        constraints.append(flow <=  fbar)
        constraints.append(flow >= -fbar)

    # ── Iterative solve with no-good cuts ─────────────────────────────────────
    ranking    = []
    infeasible = []

    for _ in range(n_results):
        prob = cp.Problem(objective, constraints)
        prob.solve(solver="SCIP", verbose=False)

        if x.value is None:
            break

        x_val = np.round(x.value).astype(int)

        # Determine bus for each battery (1-indexed)
        bat_locs  = {b: int(np.argmax(x_val[b, :])) + 1 for b in range(n_bat)}
        bus_tuple = tuple(bat_locs[b] for b in range(n_bat))
        total_cost = float(prob.value)

        # Reconstruct UCResult from solved variable values
        p_val   = p.value
        u_val   = np.round(u.value).astype(int)
        v_val   = np.round(v.value).astype(int)
        rp_val  = r_plus.value
        rm_val  = r_minus.value
        soc_val = soc.value

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
        ranking.append((bus_tuple, total_cost, uc_result))

        # No-good cut: at least one battery must move to a different bus
        constraints.append(
            cp.sum(cp.multiply(x_val.astype(float), x)) <= n_bat - 1
        )

    return SitingResult(ranking=ranking, infeasible=infeasible)
