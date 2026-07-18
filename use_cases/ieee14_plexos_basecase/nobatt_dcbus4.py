# PLEXOS base-case replication assets.
#
# p_min matches the 50/20/20/20/20 MW floor used elsewhere in ieee14/4batt.py.
# Andrew's PLEXOS baseline originally ran with no minimum-stable-level
# constraint (statistical approach, p_min=0, more congestion) but switched to
# a fixed dispatch approach as of the V5 workbook (2026-07-18 email): PLEXOS's
# "Generator Information" tab now specifies these min-stable levels directly,
# and generators are held above them. The quantum battery-valuation algorithm
# requires the min-stable-level constraint, so this is the agreed target
# going forward — Andrew confirmed in the same email.
#
# No batteries ("No Batteries" case) — represented as a single zero-power,
# zero-capacity dummy so the solver's battery arrays aren't empty.
#
# Run with Unit Commitment (not Economic Dispatch): with p_min>0 the UC
# commitment binaries can bind, so ED and UC no longer solve to the same
# answer.

GENERATORS = [
    {
        "name": "Gen 1", "bus": 1,
        "p_min": 50.0, "p_max": 332.0,
        "cost_a": 0.0, "cost_b": 20.0, "cost_c": 0.0,
        "startup_cost": 0.0,
    },
    {
        "name": "Gen 2", "bus": 2,
        "p_min": 20.0, "p_max": 140.0,
        "cost_a": 0.0, "cost_b": 20.0, "cost_c": 0.0,
        "startup_cost": 0.0,
    },
    {
        "name": "Gen 3", "bus": 3,
        "p_min": 20.0, "p_max": 100.0,
        "cost_a": 0.0, "cost_b": 40.0, "cost_c": 0.0,
        "startup_cost": 0.0,
    },
    {
        "name": "Gen 4", "bus": 6,
        "p_min": 20.0, "p_max": 100.0,
        "cost_a": 0.0, "cost_b": 40.0, "cost_c": 0.0,
        "startup_cost": 0.0,
    },
    {
        "name": "Gen 5", "bus": 8,
        "p_min": 20.0, "p_max": 100.0,
        "cost_a": 0.0, "cost_b": 40.0, "cost_c": 0.0,
        "startup_cost": 0.0,
    },
]

BATTERIES = [
    {"name": "null", "power_mw": 0.0, "capacity_mwh": 0.0, "efficiency": 0.90, "init_soc": 0.0},
]

DATACENTER_BUS: int | None = 4
DATACENTER_MW: float = 200.0
