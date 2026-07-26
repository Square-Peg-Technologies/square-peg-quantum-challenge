# V5 Tie-Out Review — 2026-07-18

Review of "No Batteries, No Line Losses, Base Case, V5.xlsx" against the repo baseline model (`use_cases/ieee14_plexos_basecase/` and `use_cases/ieee14/ieee14.py` in the square-peg-quantum-challenge repo), prompted by an updated PLEXOS output file.

## Three claims to verify against the PLEXOS output

1. Moved from statistical to fixed dispatch approach; generators now stay above their minimum stability point.
2. Increased PLEXOS capacity-module load-duration curves to 24/day, so the model output is now an exact repeat across all days of the year.
3. Added an LMP tab: energy component on top half, congestion on bottom half, by node.

## What checked out in V5 (internally consistent)

- Full year, 8760 hours, every day bit-for-bit identical to Jan 1 — confirms the 24-curve fix worked as claimed.
- No generator ever dispatches strictly between 0 and its min-stable level (Gen 1: 50 MW, Gen 2-5: 20 MW) anywhere in the year — fixed-commitment approach correctly enforced.
- No generator capacity violations anywhere in the year.
- Loads tie exactly to Node Information base values × the Hourly Load Multipliers tab (e.g. node 3: 131.88 × 0.321428571 = 42.39, matches Load by Node output).
- LMP tab structure matches the description: Energy Charge rows 1-8760, Congestion Charge rows 8762 onward.
- Congestion caps at $20/MWh, consistent with the $20/$40 SRMC spread between generator tiers.
- Node 11's $16.83 congestion charge matches the previously-confirmed line 1_5 shadow price from the V2/V3 24h validation (2026-07-14).
- Gen bus assignments in `assets.py` (buses 1, 2, 3, 6, 8) match the repo's documented IEEE 14-bus layout in `ieee14.py`.

## Blocker before this can be called a tie-out

### 1. p_min mismatch — FIXED 2026-07-18

`use_cases/ieee14_plexos_basecase/assets.py` hardcoded `p_min = 0.0` on all five generators, with an in-file comment stating this matched PLEXOS's old statistical approach (no minimum-stable-level constraint), as previously confirmed against the PLEXOS side.

V5's "Generator Information (Input)" tab shows:
- Gen 1: Min Stable Level 50 MW
- Gen 2: Min Stable Level 20 MW
- Gen 3: Min Stable Level 20 MW
- Gen 4: Min Stable Level 20 MW
- Gen 5: Min Stable Level 20 MW

Confirmed 2026-07-18 this is the correct, agreed direction — the quantum battery-valuation algorithm requires the min-stable-level constraint, and the PLEXOS side agreed to this. `assets.py` updated to these five values (both `ieee14_plexos_basecase/assets.py` and the stale cross-reference comment in `ieee14/assets.py`). `ieee14/assets.py` itself already had the correct values and needed no numeric change.

### 2. ~~Load profile mismatch~~ — RETRACTED, was an analysis error, not a real issue

Original finding (superseded): V5's "Hourly Load Multipliers" tab (trough 0.321428571 / peak 1.0) was flagged as a different, "AI-sourced" demand curve from the repo's `DAILY_FACTORS` (trough 0.45 / peak 1.4, the "Baseline Multipliers" tab) — based on computing node 3's hour-0 load as 131.88 × 0.45 = 59.35 and finding it didn't match V5's actual output of 42.39.

That comparison was wrong: 131.88 is the base load *already scaled ×1.4* (Node Information's second column set), so multiplying it by the raw 0.45 factor double-counts the 1.4 scaling. A prior 2026-07-14 reply had already established the correct relationship for V4, confirmed to hold for V5 too: the Hourly Load Multipliers tab is exactly `DAILY_FACTORS / 1.4` (checked numerically for all 24 hours), and it's paired with the ×1.4-scaled Node Information loads specifically so the two cancel out algebraically to reproduce the same per-node hourly load as the original base × `DAILY_FACTORS`. Verified across 4 nodes × 4 hours, exact match to 4 decimals in every case (e.g. node 3, hour 0: 94.2 × 0.45 = 131.88 × 0.321428571 = 42.39).

So the PLEXOS side is using the repo's `DAILY_FACTORS` curve, just restructured (normalized to a 1.0 peak, paired with pre-scaled node maxes) — likely to fit however PLEXOS's load-duration-curve/capacity module wants the shape ingested. Not a second, different curve. There is no load-profile blocker.

Loose end, not worth chasing: the workbook's own note on the "Baseline Multipliers" tab calls the Hourly Load Multipliers tab "the AI-sourced profile in the tab to the left," implying two different curves — that label is stale or inaccurate given what the numbers show.

## Contradiction noted and resolved

Earlier memory (`project_phase3_baseline_validation`, 2026-07-17) recorded the agreed plan as sampled dispatch mode with no minimum-power enforcement, since that's what the battery-valuation algorithm was thought to consume. This looked like it conflicted with the PLEXOS side's move to the fixed/min-stable approach.

Clarified 2026-07-18: the fixed/min-stable p_min approach is the correct, currently agreed direction — the quantum algorithm requires it, and the PLEXOS side agreed to this. The earlier note referred to a different, superseded decision point. No outstanding contradiction.

## Stale demand curve found in `ieee14_plexos_basecase.py` — caused a false mismatch, now bypassed

`use_cases/ieee14_plexos_basecase/ieee14_plexos_basecase.py` (the demand/network case originally paired with the assets.py file above) does not use `DAILY_FACTORS` or the Hourly Load Multipliers tab at all — it has its own hand-built `PLEXOS_FACTORS` array (0.56–0.99, single 24h day, T=24), back-solved from the *original* "No Batteries, No Line Losses, Base Case.xlsx" export (pre-V2), per its own comment: "bus 3: 60.29/94.2 = 0.64 at hour 0." That 60.29 figure is the same unexplained V4 output value noted earlier in this review — now explained: the original/V4 exports used a different, since-superseded load shape than V5's.

First diff attempt used this file's grid and came back with real-looking mismatches (total demand off by 50-90 MW/hour, Gen 4 never dispatching at all) — that was this stale curve, not an actual repo/PLEXOS problem. Re-ran using `ieee14/ieee14.py`'s grid (correct DAILY_FACTORS, T=168, sliced to first 24h) paired with the same corrected assets — see below. Still undecided whether to update `PLEXOS_FACTORS` to match DAILY_FACTORS, or retire this file since `ieee14.py` + `ieee14_plexos_basecase/assets.py` now covers the same comparison correctly — not urgent.

## Diff run — 2026-07-18: TIES OUT

Ran `ieee14/ieee14.py` grid (DAILY_FACTORS, first 24h) + `ieee14_plexos_basecase/assets.py` (corrected p_min) through the repo's `run_uc` (Unit Commitment/SCIP), diffed hour-by-hour against V5's Generation by Hour tab (Jan 1, hours 0-23). Script: `run_and_diff_v5.py` in this folder.

Results:
- Total 24h cost: repo $219,548.90 vs V5 $219,549.40 — 50-cent difference (solver tolerance).
- Congested hours 9-17 (9 hours): dispatch matches V5 exactly on every generator, to the hundredth of a MW, no exceptions.
- Congested lines each of those hours: [1, 3] → lines 1_5 and 2_4 (fbar index 1 and 3), matching the binding lines confirmed in the 2026-07-14 V2/V3 validation.
- Uncongested hours (0-3, 4-8, 18-23): total dispatch matches exactly, but the split between Gen 1 and Gen 2 sometimes differs (e.g. hour 4: repo 256.75/85.70 vs V5 322.45/20.00 — same 342.45 MW total, same cost). Both units are priced at $20/MWh, so the LP has no way to prefer one split over the other when neither line is binding. This is the same "LP degeneracy" artifact already noted and accepted as non-blocking in the 2026-07-14 validation — it never touches total cost, congestion, or shadow prices, only which of two identically-priced units gets credited with the MW.

## Status as of 2026-07-18

Ties out. p_min fix done, load-profile question resolved (no real mismatch), and the actual repo-vs-V5 diff now confirms matching cost, congestion, and shadow-price-relevant dispatch, modulo the known/accepted Gen1-Gen2 degeneracy in uncongested hours. Open, non-blocking item: what to do with the stale `PLEXOS_FACTORS` in `ieee14_plexos_basecase.py`.
