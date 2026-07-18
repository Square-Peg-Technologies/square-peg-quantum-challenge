# IEEE 14-Bus Test Case — PLEXOS base-case replication
#
# Same network as use_cases/ieee14 (MATPOWER case14: buses, branches, PTDFs,
# generator buses/costs all identical — verified against the PLEXOS PTDF
# sheet to 4 decimal places). The only thing that changes here is the daily
# demand shape.
#
# PLEXOS_FACTORS previously held a curve back-solved from the "Load by Node
# (Output)" tab of an early, pre-V2 "No Batteries, No Line Losses, Base
# Case.xlsx" PLEXOS export (flatter, 0.56x-0.99x, peaking at hour 10/20).
# That export used a different, since-superseded demand shape — Andrew's
# PLEXOS output has matched use_cases/ieee14/ieee14.py's DAILY_FACTORS curve
# since the V2 workbook (confirmed 2026-07-14, reconfirmed against V5's
# "Hourly Load Multipliers" tab 2026-07-18, which is DAILY_FACTORS
# algebraically renormalized to a 1.0 peak). PLEXOS_FACTORS now mirrors
# DAILY_FACTORS directly so this file stays in sync with any future changes
# to that curve, rather than drifting again.
#
# Pair with assets.py in this folder (p_min matching PLEXOS's fixed/
# min-stable-level dispatch, 200 MW flat datacenter at bus 4) to reproduce
# his numbers.

from dcopf.cases.base import BaseCase, BaseCaseDescription
import numpy as np

# Mirrors use_cases/ieee14/ieee14.py's DAILY_FACTORS (single-day slice).
PLEXOS_FACTORS = [
    0.45, 0.45, 0.45, 0.50, 0.55, 0.65,  # hours 0-5:  night
    0.80, 0.90, 1.00, 1.10, 1.20, 1.30,  # hours 6-11: morning ramp
    1.35, 1.40, 1.35, 1.30, 1.20, 1.10,  # hours 12-17: midday/afternoon
    1.00, 0.90, 0.80, 0.70, 0.60, 0.50,  # hours 18-23: evening ramp-down
]

T = 24  # single-day slice; use ieee14/ieee14.py directly for the 168h week


class Case(BaseCase):
    def __init__(self):
        super().__init__(CaseDescription(), T)

        self.factors = PLEXOS_FACTORS

        pd0 = self.power_demand.flatten()
        gc0 = self.generator_cost.flatten()
        pds = []
        gcs = []

        for factor in self.factors:
            pds.append(pd0 * factor)
            gcs.append(gc0.copy())

        self.power_demand = np.array(pds).T
        self.generator_cost = np.array(gcs).T


class CaseDescription(BaseCaseDescription):
    def __init__(self):
        """
        IEEE 14-Bus System (MATPOWER case14) — network data identical to
        use_cases/ieee14/ieee14.py. See that file for full field-by-field
        commentary; not repeated here to avoid drift between two copies of
        the same numbers.
        """
        super().__init__(f"ieee14_plexos_basecase_{T}")

        self.gen_cost = [20, 20, 40, 40, 40]
        self.baseMVA = 100

        self.bus = [
            [1,  3,   0.0,   0.0,  0, 0, 1, 1.060,   0.00, 0, 1, 1.06, 0.94],
            [2,  2,  21.7,  12.7,  0, 0, 1, 1.045,  -4.98, 0, 1, 1.06, 0.94],
            [3,  2,  94.2,  19.0,  0, 0, 1, 1.010, -12.72, 0, 1, 1.06, 0.94],
            [4,  1,  47.8,  -3.9,  0, 0, 1, 1.019, -10.33, 0, 1, 1.06, 0.94],
            [5,  1,   7.6,   1.6,  0, 0, 1, 1.020,  -8.78, 0, 1, 1.06, 0.94],
            [6,  2,  11.2,   7.5,  0, 0, 1, 1.070, -14.22, 0, 1, 1.06, 0.94],
            [7,  1,   0.0,   0.0,  0, 0, 1, 1.062, -13.37, 0, 1, 1.06, 0.94],
            [8,  2,   0.0,   0.0,  0, 0, 1, 1.090, -13.36, 0, 1, 1.06, 0.94],
            [9,  1,  29.5,  16.6,  0, 19, 1, 1.056, -14.94, 0, 1, 1.06, 0.94],
            [10, 1,   9.0,   5.8,  0, 0, 1, 1.051, -15.10, 0, 1, 1.06, 0.94],
            [11, 1,   3.5,   1.8,  0, 0, 1, 1.057, -14.79, 0, 1, 1.06, 0.94],
            [12, 1,   6.1,   1.6,  0, 0, 1, 1.055, -15.07, 0, 1, 1.06, 0.94],
            [13, 1,  13.5,   5.8,  0, 0, 1, 1.050, -15.16, 0, 1, 1.06, 0.94],
            [14, 1,  14.9,   5.0,  0, 0, 1, 1.036, -16.04, 0, 1, 1.06, 0.94],
        ]

        self.gen = [
            [1, 232.4, -16.9, 10,   0, 1.060, 100, 1, 332, 50, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [2,  40.0,  42.4, 50, -40, 1.045, 100, 1, 140, 20, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [3,   0.0,  23.4, 40,   0, 1.010, 100, 1, 100, 20, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [6,   0.0,  12.2, 24,  -6, 1.070, 100, 1, 100, 20, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [8,   0.0,  17.4, 24,  -6, 1.090, 100, 1, 100, 20, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        ]

        f = [
            400, 120, 120, 120, 120, 120, 9999, 80, 40, 80,
            80, 60, 120, 80, 100, 200, 80, 80, 80, 60,
        ]

        self.branch = [
            [1,  2, 0.01938, 0.05917, 0.0528, f[0],  f[0],  f[0],  0,     0, 1, -360, 360],
            [1,  5, 0.05403, 0.22304, 0.0492, f[1],  f[1],  f[1],  0,     0, 1, -360, 360],
            [2,  3, 0.04699, 0.19797, 0.0438, f[2],  f[2],  f[2],  0,     0, 1, -360, 360],
            [2,  4, 0.05811, 0.17632, 0.0340, f[3],  f[3],  f[3],  0,     0, 1, -360, 360],
            [2,  5, 0.05695, 0.17388, 0.0346, f[4],  f[4],  f[4],  0,     0, 1, -360, 360],
            [3,  4, 0.06701, 0.17103, 0.0128, f[5],  f[5],  f[5],  0,     0, 1, -360, 360],
            [4,  5, 0.01335, 0.04211, 0.0000, f[6],  f[6],  f[6],  0,     0, 1, -360, 360],
            [4,  7, 0.00000, 0.20912, 0.0000, f[7],  f[7],  f[7],  0.978, 0, 1, -360, 360],
            [4,  9, 0.00000, 0.55618, 0.0000, f[8],  f[8],  f[8],  0.969, 0, 1, -360, 360],
            [5,  6, 0.00000, 0.25202, 0.0000, f[9],  f[9],  f[9],  0.932, 0, 1, -360, 360],
            [6, 11, 0.09498, 0.19890, 0.0000, f[10], f[10], f[10], 0,     0, 1, -360, 360],
            [6, 12, 0.12291, 0.25581, 0.0000, f[11], f[11], f[11], 0,     0, 1, -360, 360],
            [6, 13, 0.06615, 0.13027, 0.0000, f[12], f[12], f[12], 0,     0, 1, -360, 360],
            [7,  8, 0.00000, 0.17615, 0.0000, f[13], f[13], f[13], 0,     0, 1, -360, 360],
            [7,  9, 0.00000, 0.11001, 0.0000, f[14], f[14], f[14], 0,     0, 1, -360, 360],
            [9, 10, 0.03181, 0.08450, 0.0000, f[15], f[15], f[15], 0,     0, 1, -360, 360],
            [9, 14, 0.12711, 0.27038, 0.0000, f[16], f[16], f[16], 0,     0, 1, -360, 360],
            [10, 11, 0.08205, 0.19207, 0.0000, f[17], f[17], f[17], 0,    0, 1, -360, 360],
            [12, 13, 0.22092, 0.19988, 0.0000, f[18], f[18], f[18], 0,    0, 1, -360, 360],
            [13, 14, 0.17093, 0.34802, 0.0000, f[19], f[19], f[19], 0,    0, 1, -360, 360],
        ]

        self.fbar = f
