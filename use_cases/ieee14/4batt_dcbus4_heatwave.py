# Datacenter at bus 4 (200 MW flat, 24h) plus a heat-wave load multiplier
# on the rest of the system's demand.
#
# Motivated by ERCOT's documented Sept 6-7, 2023 heat event: system peak
# demand hit 82,705 MW (Sept 6) and 83,911 MW (Sept 7), against a prior
# September peak of 72,370 MW (Sept 1, 2021) - a 14.3-16.0% increase, ~15%
# on average. See Phase 3 - /Contingencies/ERCOT_Heat_Event_Sept2023.md and
# Phase 3 - /Contingencies/Weather and Contingency Planning.xlsx (NRSDB
# sheet: 106.9F on Sept 6, 108.1F on Sept 7, near Austin, TX).
#
# We are not importing ERCOT's raw load shape (their system peaks around
# 85 GW, roughly 140x this system's ~560 MW peak - only the relative,
# proportional shift is transferable, not the absolute MW). HEAT_FACTORS is
# a per-hour multiplier applied to every load bus (not the datacenter, which
# stays a flat, unscaled load), shaped to concentrate the ~15% peak uplift
# in the afternoon/early evening rather than spreading it flat across all
# 24 hours - heat-driven demand (AC/cooling load) tracks temperature, which
# peaks in the afternoon, not overnight. The shape is centered on hours
# 13-15, matching where the system's own DAILY_FACTORS curve already peaks
# (hour 14), tapering to 1.0 (no effect) by late evening and staying there
# overnight.
#
# Like OUTAGES, this only applies to the first 24 hours of any run (T=24 or
# T=168) - a documented two-day heat event, not a recurring daily pattern.

from assets import GENERATORS, BATTERIES  # noqa: F401

DATACENTER_BUS: int = 4
DATACENTER_MW: float = 200.0

HEAT_FACTORS: list[float] = [
    1.00, 1.00, 1.00, 1.00, 1.00, 1.00,  # hours 1-6:   overnight, no heat effect
    1.01, 1.03, 1.05, 1.08, 1.11, 1.13,  # hours 7-12:  morning ramp as temp rises
    1.15, 1.15, 1.15, 1.13, 1.10, 1.07,  # hours 13-18: afternoon peak (~15% uplift)
    1.04, 1.02, 1.00, 1.00, 1.00, 1.00,  # hours 19-24: evening cool-down
]
