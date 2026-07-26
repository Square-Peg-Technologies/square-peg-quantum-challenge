# Battery Siting Results Summary (Base Case, No Line Losses, V5)

Source: PLEXOS output, 2026-07-22/23. Up to 4 of 14 candidate BESS units allowed to build, no line losses, no contingencies.

Note: the PLEXOS run switched from the sequential solver (which was hanging) to a statistical/sampling optimization approach for this run. This changes only the precision of interval values, not the nature of the results, and the no-build case has already been benchmarked against this.

No objective/cost value is provided in any of the files for these solutions, so relative quality between sol=0 and sol=1-4 cannot be judged from the data alone. Open question against the PLEXOS run.

## Files

- `Batteries, No Line Losses Base Case, V5.xlsx` — backing detail for the primary case (sol=0), including hourly BESS Load (charging), Generation (discharging), and Capacity Built (MWh) by node.
- `Model Base All Bat On sol=0 Battery Units Built.csv` through `sol=4...csv` — five solutions, each building exactly 4 of the 14 candidate BESS nodes.

## Solutions (BESS nodes built, value = 1)

| Solution | Nodes Built |
|---|---|
| sol=0 (primary) | BESS_4, BESS_7, BESS_8, BESS_12 |
| sol=1 | BESS_4, BESS_5, BESS_8, BESS_12 |
| sol=2 | BESS_5, BESS_7, BESS_8, BESS_12 |
| sol=3 | BESS_7, BESS_8, BESS_12, BESS_13 |
| sol=4 | BESS_4, BESS_5, BESS_7, BESS_8 |

Observations:
- BESS_8 is built in all 5 solutions.
- BESS_12 is built in 4 of 5 solutions (all except sol=4).
- BESS_7 is built in 4 of 5 solutions (all except sol=1).
- BESS_4 and BESS_5 each appear in 3 of 5 solutions, trading off against each other and against BESS_7/BESS_12/BESS_13.
- BESS_13 appears only in sol=3.
- BESS_1, 2, 3, 6, 9, 10, 11, 14 never built in any solution.

## Open questions against the PLEXOS run

- What is the objective/cost value for each solution, so we can tell if sol=1-4 are near-ties with sol=0 or meaningfully worse?
- Confirm whether sol=0 is intended as the primary/optimal solution and sol=1-4 are the "suboptimal" alternates.

## Can we calculate the objective ourselves?

Partially, for sol=0 only. The xlsx has generator cost data (SRMC $/MWh, Fuel Price, Heat Rate on the "Generator Information" input tab) and hourly LMP components (Energy/Congestion/Marginal Loss Charge on "LMP Components by Node"). That means a total production cost for sol=0 could be reconstructed by multiplying each generator's hourly output ("Generation by Hour" tab) by its SRMC and summing across generators and hours.

This does not extend to sol=1 through sol=4: those CSVs only contain the battery build decision (0/1 per node), not hourly dispatch. Without the "Generation by Hour" / "BESS Charge-Discharge by Hour" data for those four runs, there's no way to compute their production cost from what's been sent, siting alone doesn't determine how the rest of the system dispatches around it.

Also, even a full production-cost reconstruction for sol=0 would only be part of the true objective if the underlying optimization also weighs battery capital/build cost, that term isn't recoverable from this data either way.

Bottom line: to compare solutions apples-to-apples, the objective value per solution directly, or the hourly dispatch data for sol=1-4 as well, is needed from the PLEXOS side.

## Cross-check against our own repo's siting solver

Ran our repo's Battery Siting (MIP) dashboard (Phase 2 - /Git_Repo/square-peg-quantum-challenge, `ieee14` use case, `4batt_dcbus4.py` assets — 4 identical 50 MW / 200 MWh batteries, 200 MW flat datacenter at bus 4, no line losses, T=24h) against the same 14-candidate-bus siting problem, using our own objective (production + startup cost). The Benders search evaluated 144 distinct placements before stalling; only one of the PLEXOS run's 5 solutions (sol=3) showed up in that 144, all four bus-4-containing ones were absent.

That initially looked like our model disfavoring bus 4 (the datacenter bus). It doesn't: directly re-solving all 5 of the PLEXOS run's exact placements with `run_uc` (bypassing Benders' partial search) gives:

| PLEXOS sol | Buses | Cost in our model | Congested hours |
|---|---|---|---|
| sol=0 | (4, 7, 8, 12) | $193,229 | 11 |
| sol=1 | (4, 5, 8, 12) | $193,229 | 11 |
| sol=2 | (5, 7, 8, 12) | $193,229 | 9 |
| sol=3 | (7, 8, 12, 13) | $193,229 | 12 |
| sol=4 | (4, 5, 7, 8) | $193,229 | 8 |
| our Benders "best" | (3, 8, 11, 12) | $193,229 | 11 |

All five PLEXOS solutions, and our own Benders incumbent, tie exactly at $193,229 in our model. This is a genuinely flat/degenerate objective surface in this scenario — many different 4-bus placements cost the same even though they congest different lines for a different number of hours — so the earlier "bus 4 is worse" read was an artifact of Benders' no-good-cut search order (it stalled at 144 evaluated placements before it happened to reach the bus-4 ties), not a real cost difference. Good news for the comparison: our model and PLEXOS agree on cost for every one of the PLEXOS run's 5 reported solutions, not just sol=3.

Open item: since so many placements tie in our model, ordering alone (rank 1 vs rank 12 vs "not found") isn't a meaningful way to validate against PLEXOS here, cost is. The PLEXOS objective values (still not provided, see above) would tell us whether PLEXOS shows the same degeneracy or actually discriminates between these placements.
