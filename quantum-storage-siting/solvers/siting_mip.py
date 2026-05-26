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
    n_bn  = n_bat * n_bus   # flattened (battery, bus) index space

    # Generator injection matrix: E_gen[:, g] = unit vector for generator g's bus
    E_gen = np.zeros((n_bus, n_gen))
    for g in range(n_gen):
        E_gen[generators[g]["bus"] - 1, g] = 1.0

    # Battery injection matrix: B_bat[:, b*n_bus+n] = unit vector for bus n
    # B_bat @ (y_minus_flat - y_plus_flat) gives net battery injection per bus.
    B_bat = np.zeros((n_bus, n_bn))
    for b in range(n_bat):
        for n in range(n_bus):
            B_bat[n, b * n_bus + n] = 1.0

    # ── Decision variables ────────────────────────────────────────────────────
    p       = cp.Variable((n_gen, T), nonneg=True)   # generator output
    u       = cp.Variable((n_gen, T), boolean=True)  # commitment
    v       = cp.Variable((n_gen, T), boolean=True)  # startup indicator

    r_plus  = cp.Variable((n_bat, T), nonneg=True)   # battery charge rate
    r_minus = cp.Variable((n_bat, T), nonneg=True)   # battery discharge rate
    soc     = cp.Variable((n_bat, T), nonneg=True)   # state of charge
    z       = cp.Variable((n_bat, T), boolean=True)  # charge direction (1=charging)

    # x[b, n] = 1 → battery b placed at bus n
    x = cp.Variable((n_bat, n_bus), boolean=True)

    # Linearisation: y_*_flat[b*n_bus + n, t] = x[b,n] * r_*[b, t]
    # Kept 2D (n_bn, T) to avoid CVXPY's slow scipy fallback for 3-D tensors.
    y_plus_flat  = cp.Variable((n_bn, T), nonneg=True)
    y_minus_flat = cp.Variable((n_bn, T), nonneg=True)

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

    # Generator bounds and startup
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

    # Battery operation
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

    # Big-M linearisation over (b, n) pairs — uses scalar x[b,n] per pair,
    # with slice constraints over all T at once to stay 2D throughout.
    for b in range(n_bat):
        M = batteries[b]["power_mw"]
        for n in range(n_bus):
            i = b * n_bus + n
            constraints.append(y_plus_flat[i, :]  <= M * x[b, n])
            constraints.append(y_plus_flat[i, :]  <= r_plus[b, :])
            constraints.append(y_plus_flat[i, :]  >= r_plus[b, :]  - M * (1 - x[b, n]))
            constraints.append(y_minus_flat[i, :] <= M * x[b, n])
            constraints.append(y_minus_flat[i, :] <= r_minus[b, :])
            constraints.append(y_minus_flat[i, :] >= r_minus[b, :] - M * (1 - x[b, n]))

    # Power balance and line flows — fully vectorised over buses and time:
    #   net[n, t] = gen_injection[n,t] + bat_injection[n,t] - demand[n,t]
    demand_mat = grid.power_demand[:, :T]                    # shape (n_bus, T)
    net = E_gen @ p + B_bat @ (y_minus_flat - y_plus_flat) - demand_mat
    constraints.append(cp.sum(net, axis=0) == 0)            # balance per timestep
    flow = PTDF @ net                                        # shape (n_lines, T)
    constraints.append(flow <=  fbar.reshape(-1, 1))
    constraints.append(flow >= -fbar.reshape(-1, 1))

    # ── Iterative solve with no-good cuts ─────────────────────────────────────
    ranking    = []
    infeasible = []

    for _ in range(n_results):
        prob = cp.Problem(objective, constraints)
        prob.solve(solver="SCIP", verbose=False)

        if x.value is None:
            break

        x_val = np.round(x.value).astype(int)   # shape (n_bat, n_bus)

        # Determine bus for each battery (1-indexed)
        bat_locs  = {b: int(np.argmax(x_val[b, :])) + 1 for b in range(n_bat)}
        bus_tuple = tuple(bat_locs[b] for b in range(n_bat))
        total_cost = float(prob.value)

        # Reconstruct UCResult
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
