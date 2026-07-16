# MIP Solver Stopping Conditions

## siting_mip.py — Joint Battery Siting + UC MIP

A single SCIP model containing all siting binaries, generator commitment, and
dispatch variables. SCIP runs branch-and-bound internally and stops on the
first of the following:

1. Hard time limit
   Set via model.setRealParam("limits/time", time_limit_s).
   Default: 120 s (user-configurable at the prompt).
   SCIP interrupts B&B at the wall-clock boundary and returns the best
   feasible integer solution found so far (status "timelimit").
   If no feasible solution was found before the limit, a RuntimeError is raised.

2. Proven optimality
   SCIP closes the duality gap: the LP relaxation lower bound equals the best
   integer incumbent. Status returns as "optimal". The gap is tracked
   internally across the B&B tree — no explicit tolerance is set in the code,
   so SCIP uses its default of 0% (exact optimality).

3. Sub-optimal feasible exit ("bestsol")
   SCIP found at least one feasible integer solution but could not prove it is
   optimal within the time limit. The code accepts this and returns the best
   incumbent.

Internal SCIP mechanisms that accelerate convergence (not explicit code params):
- Node pruning: any B&B node whose LP bound exceeds the best incumbent is cut.
- Primal heuristics: diving, RENS, and others find incumbents early, tightening
  the bound and pruning more of the tree.
- SOS1 branching on x[b,:] (siting variables): SCIP branches on the "pick one
  bus" set directly instead of individual binaries, reducing tree depth.
- Symmetry-breaking constraints: ascending bus-index order enforced on identical
  batteries eliminates n_bat! equivalent permutations from the search space.
- LP tightening cuts: redundant flow-equality constraints force the LP at each
  node to attribute battery power to exactly one bus, tightening the LP bound
  and reducing the number of nodes explored.
- Parallel B&B: all available CPU cores used
  (parallel/maxnthreads = os.cpu_count()).


## siting_benders.py — Benders Decomposition Loop

Master problem: tiny SCIP MIP with only siting variables x[b,n] and a cost
bound eta. Subproblems: one full UC solve per candidate placement, run in
parallel. The outer loop adds cuts and iterates; stopping is controlled at the
application level.

1. Hard time limit
   remaining = time_limit_s - elapsed is checked at the top of each iteration.
   When remaining <= 0 the loop exits immediately.
   Default: 120 s.

2. Gap convergence (primary optimality condition)
   if master_lb >= best_cost - gap_tol
   master_lb is the objective value of the current master solve (a lower bound
   on the true optimal UC cost for any placement). best_cost is the lowest UC
   cost seen across all evaluated placements (an upper bound).
   When master_lb closes to within gap_tol of best_cost the loop exits —
   no placement can improve on the current best by more than gap_tol dollars.
   Default gap_tol: 1e-3 (0.1% of best_cost).

   Tuning: tighten to 1e-5 for near-exact optimality at the cost of more
   iterations; loosen to 1e-2 to accept a 1% gap and exit sooner.

3. Master exhaustion
   After enough no-good cuts the master becomes infeasible — every feasible
   placement has been enumerated and added as a cut. The master returns status
   "infeasible" (or "timelimit" with no solution) and the loop breaks.
   This is the exact-optimality exit when the search space is fully covered.

4. Incomplete master solution (safety guard)
   If the master returns fewer than n_bat placed batteries (len(bat_locs) < n_bat),
   something went wrong with solution extraction and the loop exits cleanly
   rather than dispatching a broken subproblem.

Benders cut structure:
- No-good cuts: quicksum(x[b,n] for (b,n) in S_plus) <= n_bat - 1
  Prevents the master from re-proposing a placement already evaluated.
- Integer L-shaped optimality cuts: eta >= UC_cost - M*(n_bat - sum(x[b,n]))
  Lift the master's eta lower bound based on observed UC costs, guiding it
  toward cheap placements and tightening the lower bound faster than no-good
  cuts alone.
