# PLEXOS base-case replication assets.
#
# p_min = 0 on every generator (not the usual 20 MW floor used elsewhere in
# ieee14/assets.py). PLEXOS's own "Generation by Hour" output shows Gen 3
# and Gen 4 sitting at exactly 0 MW whenever unused, and Gen 5 running
# fractional values like 1.88 / 3.8 / 7.62 MW — all below a 20 MW floor —
# so his base case appears to run with no minimum-stable-level constraint.
# This is reverse-engineered from his output, not confirmed by him directly;
# see the open question in docs/plexos_comparison/Comparison_Summary.md.
#
# No batteries ("No Batteries" case) — represented as a single zero-power,
# zero-capacity dummy so the solver's battery arrays aren't empty.
#
# Run with Economic Dispatch (option 1 in main.py): with p_min=0 the UC
# commitment binaries never bind, so ED and UC solve to the same answer;
# ED is faster.

GENERATORS = [
    {
        "name": "Gen 1", "bus": 1,
        "p_min": 0.0, "p_max": 332.0,
        "cost_a": 0.0, "cost_b": 20.0, "cost_c": 0.0,
        "startup_cost": 0.0,
    },
    {
        "name": "Gen 2", "bus": 2,
        "p_min": 0.0, "p_max": 140.0,
        "cost_a": 0.0, "cost_b": 20.0, "cost_c": 0.0,
        "startup_cost": 0.0,
    },
    {
        "name": "Gen 3", "bus": 3,
        "p_min": 0.0, "p_max": 100.0,
        "cost_a": 0.0, "cost_b": 40.0, "cost_c": 0.0,
        "startup_cost": 0.0,
    },
    {
        "name": "Gen 4", "bus": 6,
        "p_min": 0.0, "p_max": 100.0,
        "cost_a": 0.0, "cost_b": 40.0, "cost_c": 0.0,
        "startup_cost": 0.0,
    },
    {
        "name": "Gen 5", "bus": 8,
        "p_min": 0.0, "p_max": 100.0,
        "cost_a": 0.0, "cost_b": 40.0, "cost_c": 0.0,
        "startup_cost": 0.0,
    },
]

BATTERIES = [
    {"name": "null", "power_mw": 0.0, "capacity_mwh": 0.0, "efficiency": 0.90, "init_soc": 0.0},
]

DATACENTER_BUS: int | None = 4
DATACENTER_MW: float = 200.0
