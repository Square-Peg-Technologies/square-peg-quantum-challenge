# PLEXOS N-1 contingency replication: Gen 2 tripped for the entire
# optimization horizon.
#
# Per Andrew's 2026-07-17 email (Phase 3 - /Baseline_confirmation/
# Andrew_EmaiJuly17l.md): "to confirm for the N-1 contingency, we agreed to
# trip Generator 2 for the whole optimization horizon for simplicity" — a
# full-horizon outage, not a mid-day trip. This differs from
# use_cases/ieee14/4batt_dcbus4_g2out.py, which models a partial-day trip
# (hours 14-24) for a different purpose (a realistic mid-day contingency
# scenario) and is NOT meant to replicate this PLEXOS baseline.
#
# Otherwise identical to nobatt_dcbus4.py in this folder (no batteries,
# 200 MW flat datacenter at bus 4, p_min matching PLEXOS's fixed-dispatch
# minimum stable levels).

from assets import GENERATORS, BATTERIES  # noqa: F401

DATACENTER_BUS: int | None = 4
DATACENTER_MW: float = 200.0

# Gen 2 (index 1) off for the full run. main.py/dashboard.py only ever pass
# T up to 24 for this use case's assets files (see ieee14_plexos_basecase.py
# docstring), so range(24) covers the whole horizon.
OUTAGES: dict[int, set[int]] = {1: set(range(24))}
