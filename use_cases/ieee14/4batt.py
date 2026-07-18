# IEEE 14-bus base assets — no datacenter load.
# Select this file for baseline (no DC) studies.
# For datacenter scenarios, run site_datacenter.py then select the generated
# 4batt_dcbus{N}.py file from this directory.
#
# p_min stays nonzero here, matching ieee14_plexos_basecase/nobatt_dcbus4.py, which
# also now uses these floors to match Andrew's PLEXOS baseline (switched from
# p_min=0/statistical to fixed/min-stable as of the V5 workbook, 2026-07-18).
# solvers/quantum_siting.py's
# proxy cost function approximates each generator's commitment cost as
# cost_a*p_min^2 + cost_b*p_min + cost_c; with cost_a=cost_c=0 here, that
# collapses to cost_b*p_min, which goes to zero at p_min=0 regardless of
# cost_b — the proxy (and its lambda1/lambda2 penalty scaling) can no longer
# tell a $20/MWh generator from a $40/MWh one, breaking Quantum Siting's
# classical-sieve stage. ED/UC/Battery-Siting-MIP/Benders all dispatch
# continuous p[g,t] against the real cost curve and handle p_min=0 fine —
# only this file's use in the Quantum Siting tab is the reason p_min isn't
# zeroed here too. The 50/20 MW floor values themselves have no documented
# source (MATPOWER case14 has no real Pmin for these units — buses 3, 6, 8
# are synchronous condensers, Pg=0, in the original data; the team gave them
# p_max=100 MW to act as real generators, and p_min was an arbitrary floor).

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
    {"name": "Bat 0", "power_mw": 50.0, "capacity_mwh": 200.0, "efficiency": 0.90, "init_soc": 0.90 * 200.0},
    {"name": "Bat 1", "power_mw": 50.0, "capacity_mwh": 200.0, "efficiency": 0.90, "init_soc": 0.90 * 200.0},
    {"name": "Bat 2", "power_mw": 50.0, "capacity_mwh": 200.0, "efficiency": 0.90, "init_soc": 0.90 * 200.0},
    {"name": "Bat 3", "power_mw": 50.0, "capacity_mwh": 200.0, "efficiency": 0.90, "init_soc": 0.90 * 200.0},
]

DATACENTER_BUS: int | None = None
DATACENTER_MW: float = 0.0

# Optional {gen_index: set of 0-indexed hours} forcing a generator offline for
# a contingency scenario (see 4batt_g2out.py). None here = runs normally.
OUTAGES: dict[int, set[int]] | None = None
