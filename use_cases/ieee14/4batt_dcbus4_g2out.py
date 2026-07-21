# Datacenter at bus 4 (200 MW flat, 24h) plus a Gen 2 outage for the full
# optimization horizon.
#
# Modeled as a planning-horizon N-1 contingency: the solver has full-horizon
# visibility of the outage and re-dispatches optimally around it for the
# whole day, same as standard N-1 security-constrained planning studies
# (which evaluate "can the system survive losing this unit," not an
# operator's real-time reaction to a surprise trip).
#
# Full-horizon (not a mid-day trip) to match PLEXOS's N-1 contingency
# convention: per Andrew's 2026-07-17 email (Phase 3 - /Baseline_confirmation/
# Andrew_EmaiJuly17l.md), "we agreed to trip Generator 2 for the whole
# optimization horizon for simplicity." Previously this file modeled a
# mid-day trip (hours 14-24) motivated by DOE OE-417's documented December
# 16, 2023 LUMA Energy event (see Phase 3 - /Contingencies/
# Email_from_Jacquay.txt and Weather and Contingency Planning.xlsx) as a
# distinct, non-PLEXOS scenario; changed to full-horizon 2026-07-21 so all
# Gen 2 outage scenarios in the repo use one consistent convention.
#
# Gen 2 (140 MW, generator index 1) was picked over Gen 1 because Gen 1
# alone is nearly half the system's total capacity (332 of 772 MW) —
# tripping it risks infeasibility at peak demand, where Gen 2 is a
# meaningful but survivable loss.
#
# The outage hours are absolute 0-indexed positions in the run, so they only
# bite during the first 24 hours of any run (T=24 or T=168) — Gen 2 is back
# to normal on day 2 onward.

from assets import GENERATORS, BATTERIES  # noqa: F401

DATACENTER_BUS: int = 4
DATACENTER_MW: float = 200.0

OUTAGES: dict[int, set[int]] = {1: set(range(24))}  # Gen 2, full 24h horizon
