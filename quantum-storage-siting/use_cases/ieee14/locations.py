# IEEE 14-bus generator and battery locations.
# Generator buses match the case14 data exactly.
# Battery locations are placeholders — the siting solvers determine optimal placement.

GENERATOR_LOCATIONS = {
    0: 1,  # Gen 1 at bus 1
    1: 2,  # Gen 2 at bus 2
    2: 3,  # Gen 3 at bus 3
    3: 6,  # Gen 4 at bus 6
    4: 8,  # Gen 5 at bus 8
}

# Placeholder: one battery per bus (1-4). run_siting and run_quantum_siting
# will override these with optimised locations.
BATTERY_LOCATIONS = {
    0: 1,
    1: 2,
    2: 3,
    3: 4,
}
