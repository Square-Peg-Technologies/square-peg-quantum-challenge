# IEEE 14-Bus Test Case
# Original: American Electric Power system, February 1962
# Source: MATPOWER case14.m (https://matpower.org)
#
# 5 generators at buses 1, 2, 3, 6, 8:
#   Gen 1 — bus 1: p_min=50, p_max=332 MW, b=$20/MWh (swing bus, cheapest)
#   Gen 2 — bus 2: p_min=20, p_max=140 MW, b=$20/MWh
#   Gen 3 — bus 3: p_min=20, p_max=100 MW, b=$40/MWh
#   Gen 4 — bus 6: p_min=20, p_max=100 MW, b=$40/MWh
#   Gen 5 — bus 8: p_min=20, p_max=100 MW, b=$40/MWh
#
# Total installed capacity: 772 MW.
# Base load: 259 MW (11 load buses).  24h demand shaped by factors below,
# repeated daily out to a one-week (168h) horizon for Phase 3 (battery SoC
# free-floats continuously across the week — no reset between days).
# Line limits (fbar) derived from branch reactances — see CaseDescription.

from dcopf.cases.base import BaseCase, BaseCaseDescription
import numpy as np

# 24-hour demand shape. Base load (factor=1.0) = 259 MW.
# Min (0.45) ≈ 117 MW night; peak (1.40) ≈ 363 MW midday.
DAILY_FACTORS = [
    0.45, 0.45, 0.45, 0.50, 0.55, 0.65,  # hours 0-5:  night
    0.80, 0.90, 1.00, 1.10, 1.20, 1.30,  # hours 6-11: morning ramp
    1.35, 1.40, 1.35, 1.30, 1.20, 1.10,  # hours 12-17: midday/afternoon
    1.00, 0.90, 0.80, 0.70, 0.60, 0.50,  # hours 18-23: evening ramp-down
]

DAYS = 7
T = 24 * DAYS  # one week — the daily shape above repeats DAYS times


class Case(BaseCase):
    def __init__(self):
        super().__init__(CaseDescription(), T)

        # Weekly demand shape: the daily profile above repeats for each of
        # DAYS days. Callers may still run fewer hours (main.py/dashboard
        # prompt for T <= this array's column count); the profile just
        # repeats identically day over day either way.
        self.factors = DAILY_FACTORS * DAYS

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
        IEEE 14-Bus System (MATPOWER case14)
        Original data: American Electric Power, February 1962.
        Archive: http://labs.ece.uw.edu/pstca/pf14/pg_tca14bus.htm
        MATPOWER: https://matpower.org/docs/ref/matpower5.0/case14.html
        """
        super().__init__(f"ieee14_{T}")

        # Linear cost coefficients ($/MWh) matching gencost from case14:
        # Gen 1 & 2: $20/MWh (cheapest, buses 1 and 2)
        # Gen 3, 4, 5: $40/MWh (buses 3, 6, 8)
        self.gen_cost = [20, 20, 40, 40, 40]

        self.baseMVA = 100

        # bus data
        # bus_i  type  Pd      Qd      Gs  Bs  area  Vm     Va       baseKV  zone  Vmax  Vmin
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

        # generator data (21 columns: bus Pg Qg Qmax Qmin Vg mBase status Pmax Pmin + 11 zeros)
        # Pmax/Pmin are our operating limits; Pg is initialisation point.
        # Buses 3, 6, 8 are synchronous condensers in the original case (Pg=0) but we model
        # them as real generators with Pmax=100 MW so they can contribute real power.
        self.gen = [
            [1, 232.4, -16.9, 10,   0, 1.060, 100, 1, 332, 50, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [2,  40.0,  42.4, 50, -40, 1.045, 100, 1, 140, 20, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [3,   0.0,  23.4, 40,   0, 1.010, 100, 1, 100, 20, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [6,   0.0,  12.2, 24,  -6, 1.070, 100, 1, 100, 20, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [8,   0.0,  17.4, 24,  -6, 1.090, 100, 1, 100, 20, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        ]

        # branch data (13 columns: fbus tbus r x b rateA rateB rateC ratio angle status angmin angmax)
        # rateA matches self.fbar below. Transformers have ratio != 0.
        f = [
            400,   # 0:  1→2   strong backbone (x=0.059)
            120,   # 1:  1→5   (x=0.223) — moderate limit to create bus-5 congestion at high load
            120,   # 2:  2→3   (x=0.198) — bus 3 has Gen 3, limits import need
            120,   # 3:  2→4   (x=0.176)
            120,   # 4:  2→5   (x=0.174)
            120,   # 5:  3→4   (x=0.171)
            9999,  # 6:  4→5   local tie (x=0.042)
            80,    # 7:  4→7   transformer; limits power into bus-7 cluster (x=0.209, ratio=0.978)
            40,    # 8:  4→9   high-x transformer; hard bottleneck for bus-9 cluster (x=0.556, ratio=0.969)
            80,    # 9:  5→6   transformer; sole path to bus-6 cluster (x=0.252, ratio=0.932)
            80,    # 10: 6→11  (x=0.199)
            60,    # 11: 6→12  (x=0.256)
            120,   # 12: 6→13  (x=0.130)
            80,    # 13: 7→8   (x=0.176)
            100,   # 14: 7→9   combined with 4→9 limits total import to bus-9 cluster (x=0.110)
            200,   # 15: 9→10  (x=0.085)
            80,    # 16: 9→14  (x=0.270)
            80,    # 17: 10→11 (x=0.192)
            80,    # 18: 12→13 (x=0.200)
            60,    # 19: 13→14 (x=0.348)
        ]

        self.branch = [
            # fbus tbus      r        x        b       rA    rB    rC   ratio angle  st  angmin angmax
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

        # Explicit flow limits (MW) used by the DC-OPF solver.
        # Values are set above in f[] to match rateA in branch data.
        self.fbar = f
