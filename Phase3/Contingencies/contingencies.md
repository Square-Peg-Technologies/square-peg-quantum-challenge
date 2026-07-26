# Contingency & Weather Scenarios — ieee14

Two scenarios layered on top of the ieee14 baseline (`4batt_dcbus4.py`: 4 real
batteries, 200 MW flat datacenter at bus 4, no weather/contingency effects,
$198,285.17 total cost over 24h). Both cite public DOE/ERCOT data per
criterion 4's requirement that scenario data be reproducible by judges.

## 1. Heat-wave weather scenario

**File:** `use_cases/ieee14/4batt_dcbus4_heatwave.py`

**What it does:** applies an hourly load multiplier (`HEAT_FACTORS`) to every
load bus (not the datacenter, which stays a flat, unscaled 200 MW load) for
the first 24 hours of any run.

**Data source:** ERCOT's Sept 6-7, 2023 heat event.
- Sept 6, 2023 peak demand: 82,705 MW ("new September peak demand record...
  driven by extreme heat across the state" — [ERCOT news release](https://www.ercot.com/news/release/2023-09-06-ercot-has-exited))
- Sept 7, 2023 peak demand: 83,911 MW ([ERCOT news release](https://www.ercot.com/news/release/09142023-ercot-provides-new))
- Prior September peak (Sept 1, 2021): 72,370 MW (same release)
- Peak-uplift ratio: 82,705/72,370 = 1.143, 83,911/72,370 = 1.160, average
  ≈ **1.15** — this is the peak value used in `HEAT_FACTORS`.
- Corresponding hourly temperatures (NSRDB, station 719433, near Austin, TX,
  shifted from UTC to local time): 106.9°F on Sept 6, 108.1°F on Sept 7,
  matching an independently-sourced cross-check exactly. See
  `Contingencies/ERCOT_Heat_Event_Sept2023.md` for the full derivation and
  `Contingencies/Weather and Contingency Planning v2.xlsx` (sheet
  "Heatwave Scenario") for the underlying hourly data table and comparison
  chart against a normal day (Sept 16, 2023 — the coolest day in the same
  month, used as the "no heat" baseline reference).

**Why an hourly array, not a flat multiplier:** heat-driven demand (AC/
cooling load) tracks temperature, which peaks in the afternoon, not
overnight. A flat multiplier applied to all 24 hours would overstate the
overnight effect and understate how sharp the actual peak gets. `HEAT_FACTORS`
is flat 1.0 overnight, ramps up through the morning, peaks at 1.15 around
hours 13-15 (matching where the system's own DAILY_FACTORS demand curve
already peaks), and tapers back to 1.0 by evening:

```
1.00, 1.00, 1.00, 1.00, 1.00, 1.00,   # hours 1-6:   overnight, no effect
1.01, 1.03, 1.05, 1.08, 1.11, 1.13,   # hours 7-12:  morning ramp
1.15, 1.15, 1.15, 1.13, 1.10, 1.07,   # hours 13-18: afternoon peak
1.04, 1.02, 1.00, 1.00, 1.00, 1.00,   # hours 19-24: evening cool-down
```

**What we are NOT claiming:** we did not import ERCOT's raw hourly load
shape — their system peaks around 85 GW, roughly 140x this system's ~560 MW
peak, so only the relative/proportional shift (~15%) is transferable, not
the absolute MW. ERCOT's own hourly load archive only keeps a rolling
31-day window on its public report interface, and its full historical
archive needs a Data Portal account we don't have registered; the temperature
data itself (NSRDB) was never gated and is genuine, already present in
`Weather and Contingency Planning.xlsx` before this scenario was built.

**Cost impact (T=24h, UC solver):** $198,285.17 (baseline) → $211,712.42
(heatwave), **+$13,427.25 (+6.8%)** — driven by the higher demand curve
requiring more/costlier generation, no infeasibility.

## 2. N-1 contingency: Gen 2 outage

**Files:**
- `use_cases/ieee14/4batt_dcbus4_g2out.py` (4 real batteries, 200 MW datacenter at bus 4)
- `use_cases/ieee14_plexos_basecase/nobatt_dcbus4_g2out.py` (no real batteries, matches the PLEXOS tie-out baseline)

**What it does:** forces Gen 2 (140 MW, generator index 1) offline for the
full 24-hour run via `OUTAGES: dict[int, set[int]] = {1: set(range(24))}` —
implemented as `u[g, t] == 0` constraints in `solvers/uc.py`'s `run_uc()`
(a contingency constraint, not an economic commitment decision the solver
is choosing).

**Why full-day, not partial-day:** this scenario originally modeled a
mid-day trip (hours 14-24 only), motivated directly by DOE OE-417's
documented December 16, 2023 LUMA Energy event — "Uncontrolled loss of
300 MW or more of firm system loads for 15 minutes or more from a single
incident," 220 MW loss, 230,330 customers affected (see
`Weather and Contingency Planning.xlsx`, OE-417 sheet). It was changed to a
full-horizon trip on 2026-07-21 to match the PLEXOS side's convention: "we
agreed to trip Generator 2 for the whole optimization horizon for
simplicity." Both
`4batt_dcbus4_g2out.py` and `nobatt_dcbus4_g2out.py` now use this same
full-horizon convention.

**Why Gen 2, not Gen 1:** Gen 1 alone is nearly half the system's total
capacity (332 of 772 MW) — tripping it risks infeasibility at peak demand.
Gen 2 (140 MW) is a meaningful but survivable loss: with Gen 2 out, remaining
capacity is 772 - 140 = 632 MW against a 562.6 MW system peak (variable load
+ datacenter), leaving 69.4 MW of headroom.

**Planned vs. unplanned framing:** this is modeled as a standard
planning-horizon N-1 contingency — the solver has full-horizon visibility of
the outage and re-dispatches optimally around it for the whole day, the same
way conventional N-1 security-constrained planning studies evaluate "can the
system survive losing this unit." We are explicitly not claiming to model an
operator's real-time, no-foresight reaction to a surprise trip (that would
require splitting the solve into two stages — a normal-operation solve
followed by a re-optimization from the actual post-trip state — which we
considered and decided against building, since it doesn't add clear
competition value over the standard N-1 framing). The LUMA/OE-417 citation is
kept as evidence that single-generator-loss events of this kind are real and
grid-relevant, not as a claim that we reproduce its 220 MW magnitude, its
~24-minute duration, or its unplanned character.

**Cost impact (T=24h, UC solver):** $198,285.17 (baseline) → $227,343.40
(Gen 2 out all day), **+$29,058.23 (+14.7%)**. Dispatch response: Gen 1 runs
at its 332 MW cap all 24 hours; Gen 5 ($40/MWh, generator index 4) covers
most of the gap, on for 18 of 24 hours (peak 79.0 MW); Gen 4 ($40/MWh, index
3) covers the remainder during the highest-demand hours (peak 98.8 MW, on
5 hours). No infeasibility, consistent with the 69.4 MW headroom above.
