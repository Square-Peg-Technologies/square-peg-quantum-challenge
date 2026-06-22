# IEEE 30-bus generator and battery locations.
# Generator buses match the case30 data exactly.
# Battery locations are placeholders — the siting solvers determine optimal placement.

GENERATOR_LOCATIONS = {
    0: 1,   # Gen 1 at bus 1
    1: 2,   # Gen 2 at bus 2
    2: 22,  # Gen 3 at bus 22
    3: 27,  # Gen 4 at bus 27
    4: 23,  # Gen 5 at bus 23
    5: 13,  # Gen 6 at bus 13
}

# Placeholder: all 4 batteries start at bus 1.
# run_siting and run_quantum_siting will override these with optimised locations.
BATTERY_LOCATIONS = {
    0: 1,
    1: 1,
    2: 1,
    3: 1,
}
