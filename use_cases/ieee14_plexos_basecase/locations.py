# Generator locations — identical to use_cases/ieee14/locations.py.
# Battery location is a placeholder; the single dummy battery in nobatt_dcbus4.py
# has zero power/capacity so its bus assignment has no effect.

GENERATOR_LOCATIONS = {
    0: 1,  # Gen 1 at bus 1
    1: 2,  # Gen 2 at bus 2
    2: 3,  # Gen 3 at bus 3
    3: 6,  # Gen 4 at bus 6
    4: 8,  # Gen 5 at bus 8
}

BATTERY_LOCATIONS = {
    0: 1,
}
