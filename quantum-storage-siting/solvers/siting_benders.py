"""
Battery siting via batch Benders decomposition.

Master problem : tiny SCIP MIP — only x[b,n] binary siting vars + eta (cost bound)
Subproblem     : run_uc() with a fixed placement (pure UC, no siting)
Cuts           : no-good cuts (prevent revisiting) + integer L-shaped optimality cuts
Parallelism    : K placements enumerated per iteration, all K UC solves run in parallel

Convergence    : master lower bound >= best known UC cost  (or time limit)
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
from pyscipopt import Model, quicksum

from .results import SitingMIPResult, UCResult


# ---------------------------------------------------------------------------
# Picklable grid wrapper
# ---------------------------------------------------------------------------

class _GridData:
    """Plain numpy-only snapshot of a Case object — safe to pickle for workers."""
    __slots__ = ("PTDF", "fbar", "power_demand")

    def __init__(self, grid):
        self.PTDF          = np.array(grid.PTDF)
        self.fbar          = np.array(grid.fbar)
        self.power_demand  = np.array(grid.power_demand)


# ---------------------------------------------------------------------------
# Helpers shared with siting_mip
# ---------------------------------------------------------------------------

def _batteries_identical(b1: dict, b2: dict) -> bool:
    return (
        b1["power_mw"]     == b2["power_mw"]
        and b1["capacity_mwh"] == b2["capacity_mwh"]
        and b1["efficiency"]   == b2["efficiency"]
        and b1["init_soc"]     == b2["init_soc"]
    )


# ---------------------------------------------------------------------------
# Parallel UC worker (top-level so it is picklable)
# ---------------------------------------------------------------------------

def _uc_worker(args: tuple):
    bat_locs, grid, generators, batteries, T = args
    try:
        from solvers.uc import run_uc
        result = run_uc(grid, generators, batteries, bat_locs, T)
        return bat_locs, result.total_cost, result
    except Exception:
        return bat_locs, float("inf"), None


# ---------------------------------------------------------------------------
# Master problem builder
# ---------------------------------------------------------------------------

def _build_master(batteries: list, n_bus: int):
    """Construct the Benders master: only x[b,n] + eta."""
    n_bat = len(batteries)
    master = Model("benders_master")
    master.hideOutput()
    # Master solves are tiny — use all cores for the occasional hard node
    master.setIntParam("parallel/maxnthreads", os.cpu_count() or 1)

    x = {}
    for b in range(n_bat):
        for n in range(n_bus):
            x[b, n] = master.addVar(vtype="B", name=f"x_{b}_{n}")

    eta = master.addVar(lb=0.0, name="eta")
    master.setObjective(eta, sense="minimize")

    for b in range(n_bat):
        master.addCons(quicksum(x[b, n] for n in range(n_bus)) == 1,
                       name=f"one_bus_{b}")

    for b in range(n_bat):
        master.addConsSOS1([x[b, n] for n in range(n_bus)])

    for b in range(n_bat - 1):
        if _batteries_identical(batteries[b], batteries[b + 1]):
            master.addCons(
                quicksum(n * x[b, n] for n in range(n_bus))
                <= quicksum(n * x[b + 1, n] for n in range(n_bus))
            )

    return master, x, eta


# ---------------------------------------------------------------------------
# Main solver
# ---------------------------------------------------------------------------

def run_siting_benders(
    grid,
    generators: list[dict],
    batteries:  list[dict],
    T: int,
    time_limit_s: float = 120.0,
    gap_tol: float = 1e-3,
    batch_size: int | None = None,
) -> SitingMIPResult:
    """Battery siting via batch Benders decomposition.

    Parameters
    ----------
    grid          : Case object
    generators    : list of generator dicts
    batteries     : list of battery dicts
    T             : number of time steps
    time_limit_s  : wall-clock budget in seconds
    gap_tol       : stop when master_LB >= best_cost * (1 - gap_tol)
    batch_size    : UC subproblems evaluated in parallel per Benders iteration.
                    Defaults to os.cpu_count().
    """
    n_bat    = len(batteries)
    grid     = _GridData(grid)          # make picklable for subprocess workers
    n_bus    = grid.PTDF.shape[1]
    K        = batch_size or (os.cpu_count() or 1)

    master, x, eta = _build_master(batteries, n_bus)

    best_cost:    float        = float("inf")
    best_result:  UCResult     = None          # type: ignore[assignment]
    best_bat_locs: dict        = {}

    t_start  = time.perf_counter()
    n_iters  = 0
    n_solved = 0

    while True:
        elapsed   = time.perf_counter() - t_start
        remaining = time_limit_s - elapsed
        if remaining <= 0:
            break

        # ── Step 1: enumerate up to K placements from master ─────────────────
        # Each master solve takes < 1 ms; K sequential no-good cuts give K
        # diverse placements which are then evaluated in parallel.

        master.setRealParam("limits/time", remaining)
        batch_placements: list[dict] = []
        batch_x_stars:   list[list]  = []     # list of S_plus per placement

        for _ in range(K):
            master.optimize()
            status = master.getStatus()
            if status == "infeasible" or (
                status == "timelimit" and master.getNSols() == 0
            ):
                break

            master_lb = master.getObjVal()

            # Convergence check
            if master_lb >= best_cost - gap_tol:
                break

            # Extract placement
            bat_locs: dict[int, int] = {}
            S_plus:   list[tuple]    = []
            for b in range(n_bat):
                for n in range(n_bus):
                    if master.getVal(x[b, n]) > 0.5:
                        bat_locs[b] = n + 1   # 1-indexed
                        S_plus.append((b, n))
                        break

            if len(bat_locs) < n_bat:
                break   # incomplete solution — safety guard

            batch_placements.append(bat_locs)
            batch_x_stars.append(S_plus)

            # Immediate no-good cut so next master solve gives a different placement
            master.freeTransform()
            master.addCons(
                quicksum(x[b, n] for (b, n) in S_plus) <= n_bat - 1,
                name=f"nogood_{n_iters}_{_}",
            )

        if not batch_placements:
            break   # master exhausted or converged

        # ── Step 2: evaluate all placements in parallel ───────────────────────
        args = [
            (bl, grid, generators, batteries, T)
            for bl in batch_placements
        ]
        with ProcessPoolExecutor(max_workers=len(args)) as pool:
            outcomes = list(pool.map(_uc_worker, args))

        # ── Step 3: update best solution + add L-shaped cuts ─────────────────
        master.freeTransform()

        for (bat_locs, Z, uc_result), S_plus in zip(outcomes, batch_x_stars):
            n_solved += 1
            if Z < best_cost:
                best_cost     = Z
                best_result   = uc_result
                best_bat_locs = dict(bat_locs)

            if Z < float("inf"):
                # Integer L-shaped optimality cut (Laporte & Louveaux 1993):
                # eta >= Z * (sum_{(b,n) in S+} x[b,n] - (n_bat - 1))
                # Guarantees eta >= Z when the same placement is re-selected.
                master.addCons(
                    eta >= Z * (
                        quicksum(x[b, n] for (b, n) in S_plus) - (n_bat - 1)
                    ),
                    name=f"lshaped_{n_iters}_{n_solved}",
                )

        n_iters += 1

        elapsed = time.perf_counter() - t_start
        if elapsed >= time_limit_s:
            break

        # Final convergence check with all cuts in place
        master.setRealParam("limits/time", time_limit_s - elapsed)
        master.optimize()
        if master.getStatus() == "infeasible":
            break
        if master.getObjVal() >= best_cost - gap_tol:
            break

    if best_result is None:
        raise RuntimeError(
            "Benders found no feasible solution within the time limit"
        )

    bus_tuple  = tuple(best_bat_locs[b] for b in range(n_bat))
    elapsed    = time.perf_counter() - t_start
    scip_status = "optimal" if elapsed < time_limit_s - 1.0 else "timelimit"

    return SitingMIPResult(
        bus_tuple   = bus_tuple,
        bat_locs    = best_bat_locs,
        uc_result   = best_result,
        total_cost  = best_cost,
        scip_status = scip_status,
    )
