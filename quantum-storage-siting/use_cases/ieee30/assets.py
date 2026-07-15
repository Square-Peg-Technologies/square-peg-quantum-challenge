# IEEE 30-bus base assets — no datacenter load.
# Generator buses and Pmax/Pmin from MATPOWER case30.m.
# Cost coefficients from case30 gencost (polynomial: cost_a*p^2 + cost_b*p + cost_c).
# Pmin raised from 0 to small positive values so unit-commitment decisions are meaningful.

GENERATORS = [
    {
        "name": "Gen 1", "bus": 1,
        "p_min": 10.0, "p_max": 80.0,
        "cost_a": 0.0200, "cost_b": 2.00, "cost_c": 0.0,
        "startup_cost": 0.0,
    },
    {
        "name": "Gen 2", "bus": 2,
        "p_min": 10.0, "p_max": 80.0,
        "cost_a": 0.0175, "cost_b": 1.75, "cost_c": 0.0,
        "startup_cost": 0.0,
    },
    {
        "name": "Gen 3", "bus": 22,
        "p_min": 10.0, "p_max": 50.0,
        "cost_a": 0.0625, "cost_b": 1.00, "cost_c": 0.0,
        "startup_cost": 0.0,
    },
    {
        "name": "Gen 4", "bus": 27,
        "p_min": 10.0, "p_max": 55.0,
        "cost_a": 0.00834, "cost_b": 3.25, "cost_c": 0.0,
        "startup_cost": 0.0,
    },
    {
        "name": "Gen 5", "bus": 23,
        "p_min": 5.0, "p_max": 30.0,
        "cost_a": 0.025, "cost_b": 3.00, "cost_c": 0.0,
        "startup_cost": 0.0,
    },
    {
        "name": "Gen 6", "bus": 13,
        "p_min": 5.0, "p_max": 40.0,
        "cost_a": 0.025, "cost_b": 3.00, "cost_c": 0.0,
        "startup_cost": 0.0,
    },
]

BATTERIES = [
    {"name": "Bat 0", "power_mw": 30.0, "capacity_mwh": 120.0, "efficiency": 0.90, "init_soc": 0.90 * 120.0},
    {"name": "Bat 1", "power_mw": 30.0, "capacity_mwh": 120.0, "efficiency": 0.90, "init_soc": 0.90 * 120.0},
    {"name": "Bat 2", "power_mw": 30.0, "capacity_mwh": 120.0, "efficiency": 0.90, "init_soc": 0.90 * 120.0},
    {"name": "Bat 3", "power_mw": 30.0, "capacity_mwh": 120.0, "efficiency": 0.90, "init_soc": 0.90 * 120.0},
]

DATACENTER_BUS: int | None = None
DATACENTER_MW: float = 0.0
