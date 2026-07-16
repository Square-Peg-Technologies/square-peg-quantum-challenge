# PJM 5-bus network with generators from the IonQ/ORNL unit commitment paper
# (arXiv:2505.00145, Table I). Network topology from MATPOWER case5.m.
#
# 3 generators placed at buses 1, 3, 5 (quadratic costs linearised to b coefficient):
#   Unit 0 — bus 1: p_min=100, p_max=600 MW, b=$10/MWh
#   Unit 1 — bus 3: p_min=100, p_max=400 MW, b=$8/MWh
#   Unit 2 — bus 5: p_min= 50, p_max=200 MW, b=$6/MWh (cheapest, drives line 4-5 congestion)
#
# The DCOPF framework uses linear costs. The full quadratic F(p) = a*p^2 + b*p + c
# from the paper is approximated here by the incremental term b only.
# 24 time steps (24 hours x 1 hourly interval), repeated daily out to a
# one-week (168h) horizon — battery SoC free-floats continuously across
# the week, no reset between days.

from dcopf.cases.base import BaseCase, BaseCaseDescription
import numpy as np

# 24-hour demand shape scaled to match the IonQ/ORNL paper (arXiv:2505.00145)
# demand range. Paper uses loads [170, 520, 1100, 330] MW across 4 hours;
# we extend to 24 hours with a realistic daily shape spanning the same range.
# Base demand (Bus2=300, Bus3=300, Bus4=400 MW) * factor = nodal demand.
# Factors below 0.60 allow Units 1+2 to serve load without Unit 0 (max 600 MW).
# Factors below 0.20 allow Unit 2 alone to serve load (max 200 MW).
DAILY_FACTORS = [0.30, 0.30, 0.30, 0.33, 0.38, 0.45,  # hours 0-5:  night 300-450 MW
                 0.55, 0.65, 0.80, 0.95, 1.05, 1.10,  # hours 6-11: ramp to peak 1100 MW
                 1.08, 1.05, 1.00, 0.98, 0.95, 0.90,  # hours 12-17: midday/afternoon
                 0.80, 0.70, 0.60, 0.52, 0.42, 0.33]  # hours 18-23: evening ramp-down

DAYS = 7
T = 24 * DAYS  # one week — the daily shape above repeats DAYS times

class Case(BaseCase):
    def __init__(self):
        super().__init__(CaseDescription(), T)

        self.factors = DAILY_FACTORS * DAYS

        # self.noise_power_demand = np.sqrt(3)
        # self.noise_generator_cost = 2.88

        # seed = 43
        # rs = np.random.RandomState(seed)

        pd0 = self.power_demand.flatten()
        gc0 = self.generator_cost.flatten()
        pds = []; gcs = []

        for factor in self.factors:
            pd = pd0 * factor
            # pd = pd0 * factor + self.noise_power_demand * rs.randn(*np.shape(pd0)) * np.sign(pd0)
            pds.append(pd)
            gc = gc0.copy()
            # gc = gc0 + self.noise_generator_cost * rs.randn(*np.shape(gc0)) * np.sign(gc0)
            gcs.append(gc)

        self.power_demand = np.array(pds).T
        self.generator_cost = np.array(gcs).T


class CaseDescription(BaseCaseDescription):
    def __init__(self):
        """
        PJM 5-Bus System (MATPOWER case5)
        Converted from MATPOWER case5.m
        Original data from:
          F. Li and R. Bo, "Small Test Systems for Power System Economic Studies",
          2010 IEEE PES General Meeting
        Available at: https://matpower.org/docs/ref/matpower5.0/case5.html
        """
        super().__init__("pjm5_{}".format(T))

        # Linear cost approximation using the b (incremental) coefficient from the
        # IonQ/ORNL paper quadratic cost F(p) = a*p^2 + b*p + c (Table I).
        # Order matches gen list below: Unit 0 @ bus 1, Unit 1 @ bus 3, Unit 2 @ bus 5.
        self.gen_cost = [10, 8, 6]

        self.baseMVA = 100

        # bus data
        # bus_i  type  Pd      Qd      Gs  Bs  area  Vm  Va  baseKV  zone  Vmax  Vmin
        self.bus = [
            [1, 2, 0,   0,      0, 0, 1, 1, 0, 230, 1, 1.1, 0.9],
            [2, 1, 300, 98.61,  0, 0, 1, 1, 0, 230, 1, 1.1, 0.9],
            [3, 2, 300, 98.61,  0, 0, 1, 1, 0, 230, 1, 1.1, 0.9],
            [4, 3, 400, 131.47, 0, 0, 1, 1, 0, 230, 1, 1.1, 0.9],
            [5, 2, 0,   0,      0, 0, 1, 1, 0, 230, 1, 1.1, 0.9],
        ]

        # generator data — 3 units from IonQ/ORNL paper Table I
        # bus  Pg   Qg  Qmax  Qmin  Vg  mBase  status  Pmax  Pmin  (remaining cols zero)
        # Unit 0: p_min=100, p_max=600, a=0.002,  b=10, c=500
        # Unit 1: p_min=100, p_max=400, a=0.0025, b=8,  c=300
        # Unit 2: p_min= 50, p_max=200, a=0.005,  b=6,  c=100
        self.gen = [
            [1, 350, 0, 0, 0, 1, 100, 1, 600, 100, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [3, 250, 0, 0, 0, 1, 100, 1, 400, 100, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [5, 125, 0, 0, 0, 1, 100, 1, 200,  50, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        ]

        # branch data
        # fbus  tbus  r        x        b        rateA  rateB  rateC  ratio  angle  status  angmin  angmax
        self.branch = [
            [1, 2, 0.00281, 0.0281, 0.00712, 400, 400, 400, 0, 0, 1, -360, 360],
            [1, 4, 0.00304, 0.0304, 0.00658, 0,   0,   0,   0, 0, 1, -360, 360],
            [1, 5, 0.00064, 0.0064, 0.03126, 0,   0,   0,   0, 0, 1, -360, 360],
            [2, 3, 0.00108, 0.0108, 0.01852, 0,   0,   0,   0, 0, 1, -360, 360],
            [3, 4, 0.00297, 0.0297, 0.00674, 0,   0,   0,   0, 0, 1, -360, 360],
            [4, 5, 0.00297, 0.0297, 0.00674, 240, 240, 240, 0, 0, 1, -360, 360],
        ]

        # explicit flow limits (MW): rateA where constrained, large value otherwise
        self.fbar = [250, 9999, 9999, 9999, 9999, 200]
