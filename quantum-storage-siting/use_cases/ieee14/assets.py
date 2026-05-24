# IEEE 14-bus base assets — no datacenter load.
# Select this file for baseline (no DC) studies.
# For datacenter scenarios, run site_datacenter.py then select the generated
# assets_dc_bus{N}.py file from this directory.

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
    {"name": "Bat 0", "power_mw": 50.0, "capacity_mwh": 200.0, "efficiency": 0.90, "init_soc": 100.0},
    {"name": "Bat 1", "power_mw": 50.0, "capacity_mwh": 200.0, "efficiency": 0.90, "init_soc": 100.0},
    {"name": "Bat 2", "power_mw": 50.0, "capacity_mwh": 200.0, "efficiency": 0.90, "init_soc": 100.0},
    {"name": "Bat 3", "power_mw": 50.0, "capacity_mwh": 200.0, "efficiency": 0.90, "init_soc": 100.0},
]

DATACENTER_BUS: int | None = None
DATACENTER_MW: float = 0.0
