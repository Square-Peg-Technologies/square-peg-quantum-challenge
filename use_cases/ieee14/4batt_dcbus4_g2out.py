# Datacenter at bus 4 (200 MW flat, 24h) plus a Gen 2 outage from 2pm to end
# of day (hours 14-24, 0-indexed 13-23).
#
# Modeled as a planning-horizon N-1 contingency: the solver has full-horizon
# visibility of the outage and re-dispatches optimally around it for the
# whole day, same as standard N-1 security-constrained planning studies
# (which evaluate "can the system survive losing this unit," not an
# operator's real-time reaction to a surprise trip). We are NOT claiming to
# model the no-foresight, real-time response to an unplanned event.
#
# Motivated by DOE OE-417's documented December 16, 2023 LUMA Energy event
# (an "Uncontrolled loss of 300 MW or more of firm system loads for 15
# minutes or more from a single incident," 220 MW loss, 230,330 customers
# affected) — cited as evidence that single-generator-loss events of this
# kind are real and grid-relevant, not as a claim that we reproduce its
# 220 MW magnitude, ~24-minute duration, or its unplanned/no-foresight
# character. See Phase 3 - /Contingencies/Email_from_Jacquay.txt and
# Phase 3 - /Contingencies/Weather and Contingency Planning.xlsx.
#
# Gen 2 (140 MW, generator index 1) was picked over Gen 1 because Gen 1
# alone is nearly half the system's total capacity (332 of 772 MW) —
# tripping it risks infeasibility at peak demand, where Gen 2 is a
# meaningful but survivable loss.
#
# The outage hours are absolute 0-indexed positions in the run, so they only
# bite during the first 24 hours of any run (T=24 or T=168) — Gen 2 is back
# to normal on day 2 onward, same as a real outage that gets fixed rather
# than one that never comes back.

from assets import GENERATORS, BATTERIES  # noqa: F401

DATACENTER_BUS: int = 4
DATACENTER_MW: float = 200.0

OUTAGES: dict[int, set[int]] = {1: set(range(13, 24))}  # Gen 2, hours 14-24
