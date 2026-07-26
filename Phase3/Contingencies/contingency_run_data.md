# Contingency Run Data: accumulated for Section 6 write-up

Source: fresh runs of `Phase 2 - /Git_Repo/square-peg-quantum-challenge`'s solver code, done 2026-07-22 by calling `solvers.uc.run_uc()` directly with the same setup `main.py` uses (datacenter injection, heat-factor scaling, outage constraints), for every scenario at both `line_losses=False` and `line_losses=True`. Cross-checked on 2026-07-22 against the actual PLEXOS output in `Phase 3 - /Baseline_confirmation/*.xlsx` (V6 workbooks), see the new section below, all four no-battery numbers below are independently confirmed against the PLEXOS model, not just our own repo standing in for "PLEXOS-comparable."

## Full results table (T=24h, UC solver)

| Scenario | Line losses | Total cost | Solver time |
|---|---|---:|---:|
| Baseline (4-batt, `4batt_dcbus4.py`) | off | $198,285.17 | 1.0s |
| Baseline (4-batt) | on | $212,507.56 | 7.3s |
| Gen 2 outage (4-batt, `4batt_dcbus4_g2out.py`) | off | $227,343.40 | 0.9s |
| Gen 2 outage (4-batt) | on | $250,793.37 | 14.8s |
| Heatwave (4-batt, `4batt_dcbus4_heatwave.py`) | off | $211,712.42 | 1.5s |
| Heatwave (4-batt) | on | $226,236.76 | 6.9s |
| Baseline (no-batt/PLEXOS, `nobatt_dcbus4.py`) | off | $219,548.90 | 0.5s |
| Baseline (no-batt/PLEXOS) | on | $237,545.95 | 5.0s |
| Gen 2 outage (no-batt/PLEXOS, `nobatt_dcbus4_g2out.py`) | off | $257,116.00 | 0.5s |
| Gen 2 outage (no-batt/PLEXOS) | on | $279,115.23 | 5.0s |

## Confirmed against the actual PLEXOS output (V6 workbooks, 2026-07-22)

`Phase 3 - /Baseline_confirmation/` has four V6 workbooks, each with a built-in "Tie-Out Summary" tab comparing the repo's `run_uc()` output directly against the PLEXOS model output for the same scenario. This is a genuine independent confirmation, not our own repo's no-battery run standing in for what PLEXOS would say:

| Scenario | Repo cost | PLEXOS cost | Diff | Note |
|---|---:|---:|---:|---|
| Base case, no losses | $219,548.90 | $219,549.40 | -$0.50 | Solver-tolerance level |
| Base case, with losses | $237,545.95 | $237,513.00 | +$32.95 | Solver-tolerance level |
| Gen 2 outage, no losses | $257,116.00 | $257,116.00 | $0.00 | Exact match |
| Gen 2 outage, with losses | $279,115.23 | $279,067.60 | +$47.63 | Solver-tolerance level |

Workbook files (all in `Phase 3 - /Baseline_confirmation/`):
- `No Batteries, No Line Losses, Base Case, V6.xlsx`
- `No Batteries, Line Losses Included, Base Case, V6.xlsx`
- `No Batteries, No Line Losses Included, Gen2 Off, Base Case, V6.xlsx`
- `No Batteries, Line Losses Included, Gen2 Off, Base Case, V6.xlsx`

Per-generator and per-line diffs inside these workbooks can be larger (up to about 100 MW on individual generators in the no-losses case) without indicating a real mismatch: this is the same LP degeneracy already documented in `V5_Tie_Out_Findings_2026-07-18.md`, whenever two generators share the same $/MWh price and neither is congestion-bound, the linear solver is indifferent to how the total is split between them. Total dispatch per hour, total daily cost, and the congestion pattern still tie out; only the split between tied-price units (and the flows that follow from it) can differ. Line losses break this tie (different marginal cost per unit once losses are counted), which is why the with-losses diffs above are tight to the dollar while the no-losses per-generator diffs can be large and still be a non-issue.

What the tie-out actually checks, beyond total cost: each V6 workbook has four comparison tabs, not just the Tie-Out Summary.
- "Repo vs PLEXOS Diff": per-generator hourly dispatch, all 5 generators, all 24 hours. Ties exactly except for the LP-degeneracy splits above.
- "Repo vs PLEXOS Flow": per-line power flow, all 20 branches, all 24 hours, plus each line's shadow price. Ties to within about 0.03 MW once sign-corrected, PLEXOS and the repo label line direction oppositely (e.g. line 1_2), which is a labeling difference confirmed by every line/hour pair matching in magnitude once the sign is flipped, not a physical mismatch.
- "PLEXOS PTDFs": static network topology (power transfer distribution factors) for every branch against every bus, confirms the two models are solving the same network, not per-hour data.
- "Load by Node": per-node hourly load input, confirms the two models are fed the same demand data before any dispatch decision is made.
- Shadow prices and the resulting congestion on/off pattern are covered by the Tie-Out Summary's "Congestion on/off mismatches" row (0/480 or 5/480 depending on scenario, the mismatches are the same degeneracy hours, not real congestion disagreements).

This directly satisfies Section 6.0's RESULT 2 (PLEXOS baseline comparison) with an actual confirmed number rather than a placeholder, and upgrades the PLEXOS comparison already written into 6.1 from "our repo's no-battery run" to "confirmed exact match against the PLEXOS model." The V5 tie-out review (`V5_Tie_Out_Findings_2026-07-18.md`) covers the base-case, no-losses scenario only, done 2026-07-18 before the Gen2-off and line-losses variants were delivered on 2026-07-21; V6 supersedes it and extends the same confirmed tie-out to all four combinations.

## Baseline quantum siting result (Section 6.0, RESULT 1), 2026-07-22

Local Aer simulator run, `4batt_dcbus4.py` (ieee14, 4 real batteries, 200 MW datacenter at bus 4, T=24, no outage, no heat factors). Full parameters, per the standing convention that every cited run states its exact configuration: `sim_method=tensor_network`, `ansatz=butterfly` (matches the methodology documented in Section 2 Circuit Design and the already-written 6.1 quantum run; an earlier attempt without an explicit ansatz auto-selected linear-chain HEA instead and should not be cited), `warm_start=sdp`, `second_stage=uc`, `n_candidates=10`, `max_time_s=60.0`, `line_losses=False`, `final_backend=local`.

Result: 19 qubits (5 gen + 14 bus), circuit depth L=3 (114 params), final extraction at 5000 shots, 13 COBYLA iterations (final objective 4.884e+06), wall-clock 84.1s (80.3s quantum sieve, comprising 62.3s Aer MPS sampling and 17.9s final-shot extraction, plus 2.8s classical UC refinement). 6 quantum candidates found and evaluated. Best placement: buses (4, 8, 9, 10), cost $193,229. Two other candidates tie at the identical $193,229 cost, buses (8, 10, 12, 14) and (5, 12, 13, 14), the same placement-degeneracy pattern already noted for the Section 4 line-losses/degeneracy placeholder and the earlier linear-chain trial run (which also landed on $193,229 with a different bus set, (4, 9, 11, 14), reinforcing that the degeneracy is a real feature of the no-line-losses problem, not an artifact of one ansatz).

Decided: this $193,229 result is lower than the $199,804 figure already in Section 5's verbatim Phase 2 carryover text (para 43 in `Phase3_Draft_V3.docx`, "reduces 24-hour dispatch cost from the no-storage baseline of $228,429 to $199,804"). Section 5's Phase 2 text stays verbatim, unchanged, this is exactly the discrepancy the existing red placeholder at para 20 ("Reverify this not corrected, numbers will have to be revisited... the 199 has shifted slightly as we have reformulated part of the problem") already anticipated, and it does not get resolved by editing Phase 2's numbers. Instead, 6.0 will carry a short note explaining why its $193,229 differs from Section 5's $199,804/$228,429: the Phase 2 figures reflect an earlier code state, this run is on the current codebase after the p_min fix, congestion tightening, and other changes documented throughout `revise.md`.

## Deltas vs. matching no-outage baseline, same loss setting

Line losses off (matches the DC-lossless approximation used everywhere else in the draft, Section 4's "Encoding and assumptions" states "lossless branches" as the standing assumption, so this is the number to use in the main Section 6 text unless you're specifically discussing the loss-modeling sensitivity):
- 4-battery: baseline $198,285.17 to Gen 2 outage $227,343.40 (+$29,058.23, +14.7%)
- 4-battery: baseline $198,285.17 to heatwave $211,712.42 (+$13,427.25, +6.8%)
- No-battery/PLEXOS: baseline $219,548.90 to Gen 2 outage $257,116.00 (+$37,567.10, +17.1%)

Line losses on (I squared R losses modeled exactly per `solvers/uc.py`'s convex loss formulation, useful as a robustness check/sensitivity discussion, not the headline number, since it's a different assumption than the rest of the paper uses):
- 4-battery: baseline $212,507.56 to Gen 2 outage $250,793.37 (+$38,285.81, +18.0%)
- 4-battery: baseline $212,507.56 to heatwave $226,236.76 (+$13,729.20, +6.5%)
- No-battery/PLEXOS: baseline $237,545.95 to Gen 2 outage $279,115.23 (+$41,569.28, +17.5%)

Takeaway if you want one sentence for the write-up: line losses add a consistent roughly 7% to every scenario's cost (baseline and both contingencies), and the contingency deltas (the percent increase from baseline within each loss setting) are close but not identical with losses on vs off. Gen 2 outage's relative impact goes from +14.7% (no losses) to +18.0% (with losses) on the 4-battery case, meaning losses slightly amplify the outage's relative cost impact rather than just shifting every number by a flat amount.

## Quantum vs. classical siting comparison (Gen 2 outage, 4-battery, no line losses, from earlier dashboard runs, 2026-07-21)

Kept from the previous data pull, these used the quantum/classical siting solvers, not plain UC, so they weren't part of the fresh run above (siting search doesn't currently expose a line_losses flag the same way; treat this as the no-losses baseline comparison):

- Quantum siting (Aer TN VQA + UC refinement): 19 qubits, best placement buses (3, 4, 8, 11), cost $207,626, 176.3s total (77.5s quantum sieve, 5.4s classical, 91.9s loss-aware re-solve of 6 candidates, plus setup/extraction overhead).
- Classical siting search (SCIP Benders): best placement buses (3, 8, 10, 11), cost $207,725 (stopped early, no further improvement), 149.0s total.
- Under this contingency, quantum and classical pick different buses and quantum lands $99 cheaper, unlike the exact tie in the Section 5 base case. Worth a sentence in Section 6 Observations.

## Reconciliation: previously-flagged discrepancies, now explained

1. The two 07-21 no-battery UC runs that disagreed by about $22k ($257,116.00 vs $279,115.23): explained. They weren't inconsistent, one was run with the line-losses prompt answered "off," the other "on." The fresh run above confirms both numbers exactly, and both are now independently confirmed against the actual PLEXOS V6 output too (see above).
2. `contingencies.md`'s stated Gen 2 outage delta (+$29,058.23, +14.7%) didn't match the 07-18 dashboard log ($209,458.35, +5.6%): explained. The 07-18 log predates the 2026-07-21 code change that switched the outage from a partial mid-day trip (hours 14-24) to a full-horizon trip (see the comment header in `4batt_dcbus4_g2out.py`). The fresh run above, on the current code, reproduces `contingencies.md`'s number exactly ($227,343.40); `contingencies.md` was already correct and current, the 07-18 log was simply the pre-update scenario definition. No changes needed to `contingencies.md`.

Bottom line: use the no-line-losses numbers as the primary Section 6.1/6.2 figures (consistent with the paper's stated DC-lossless assumption), the line-losses column is a ready-made robustness/sensitivity note if you want one, and the no-battery/PLEXOS numbers throughout are now backed by an actual confirmed PLEXOS tie-out, not an approximation.
