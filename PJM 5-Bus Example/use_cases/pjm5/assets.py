GENERATORS = [
    {"name": "Unit 0", "bus": 1, "p_min": 100, "p_max": 600,
     "cost_a": 0.002,  "cost_b": 10, "cost_c": 500, "startup_cost": 0},
    {"name": "Unit 1", "bus": 3, "p_min": 100, "p_max": 400,
     "cost_a": 0.0025, "cost_b":  8, "cost_c": 300, "startup_cost": 0},
    {"name": "Unit 2", "bus": 5, "p_min":  50, "p_max": 200,
     "cost_a": 0.005,  "cost_b":  6, "cost_c": 100, "startup_cost": 0},
]

BATTERIES = [
    {"name": "Bat 0", "power_mw": 50, "capacity_mwh": 200, "efficiency": 0.85, "init_soc": 100},
    {"name": "Bat 1", "power_mw": 50, "capacity_mwh": 200, "efficiency": 0.85, "init_soc": 100},
]
