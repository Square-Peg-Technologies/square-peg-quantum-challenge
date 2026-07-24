# ERCOT Sept 6-7, 2023 heat event - public load data

## What I could and couldn't pull

ERCOT's own hourly-load reports (NP6-345-CD "Actual System Load by Weather Zone",
NP6-346-CD "Actual System Load by Forecast Zone") only keep a rolling 31-day window
on the public report interface - the raw hourly CSV for Sept 2023 is no longer served
there. Full historical hourly archives live behind the ERCOT Data Portal
(data.ercot.com), which needs a free account, and EIA's Hourly Electric Grid Monitor
(which also covers the ERCOT balancing authority, code ERCO) needs a free
self-service API key - I don't have either registered in this session, so I couldn't
pull the raw hourly series directly.

What I could get, and what's arguably a cleaner citation anyway, are ERCOT's own
published peak-demand press releases for that week - exact MW figures, dated,
publicly posted, no login needed.

## Sourced figures

- Sept 6, 2023: new September peak demand record, **82,705 MW**, "driven by extreme
  heat across the state." ([ERCOT, "ERCOT Has Exited Emergency Operations..."](https://www.ercot.com/news/release/2023-09-06-ercot-has-exited))
- Sept 7, 2023: broke that record again, **83,911 MW**. ([ERCOT, "ERCOT Provides New Look at Peak Demand Records"](https://www.ercot.com/news/release/09142023-ercot-provides-new))
- Prior September peak (before this heat wave), Sept 1, 2021: **72,370 MW**. (same release)
- For context: ERCOT's all-time peak that summer was 85,508 MW on Aug 10, 2023.
  ([ERCOT Yearly Peak Demand Records](https://www.ercot.com/static-assets/data/news/content/a-peak-demand/all-time-records.htm))

## Computed ratio

Using the prior September peak (72,370 MW) as the "normal" baseline and the two heat-event
days as the "hot" case:

- Sept 6 vs baseline: 82,705 / 72,370 = **1.143** (+14.3%)
- Sept 7 vs baseline: 83,911 / 72,370 = **1.160** (+16.0%)
- Average across the two days: **~+15%** peak-hour uplift

This is a peak-to-peak ratio, not an hourly curve - it says the heat event pushed
ERCOT's system peak about 15% above a typical September peak. Applying it as a flat
multiplier on our own peak hour (or a few hours around it) is a defensible proxy;
applying it project-wide across all 24 hours would overstate the effect, since
heat-driven load increases concentrate around the afternoon peak, not overnight.

## Feasibility check against our model

Our `ieee14_plexos_basecase`/`ieee14` system: base variable load peaks at 362.6 MW
(259 MW x 1.4 peak factor) plus the 200 MW flat datacenter = 562.6 MW peak, against
772 MW of total generator capacity (332+140+100+100+100).

- +15% on the variable load only at peak hour: 362.6 x 1.15 = 417.0 MW + 200 MW DC =
  **617.0 MW** peak. Still comfortably under 772 MW total capacity (155 MW headroom).
- Combined with the Gen 2 contingency (140 MW trip) discussed separately: remaining
  capacity 772 - 140 = 632 MW vs a 617 MW peak - only **15 MW of headroom**. Running
  both scenarios in the same hour together is feasible but tight, and worth flagging
  explicitly in the writeup rather than treating it as a comfortable margin.

## Caveat for the writeup

ERCOT's peak demand (~80,000+ MW) is roughly 140x our system's peak (~560 MW) - we
are not claiming to model ERCOT itself, only using its documented peak-demand
percentage increase as a citable, real-world basis for scaling our own synthetic
demand curve during a "hot day" scenario.
