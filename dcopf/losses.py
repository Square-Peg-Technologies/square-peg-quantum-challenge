"""I^2R transmission line loss helpers.

solvers/uc.py and solvers/ed.py model losses as an exact convex constraint
inside the same solve (see each module's run_uc/run_ed docstring): a
per-line loss variable lower-bounded by loss_l >= R_l * flow_l**2 / Sbase,
with flow computed directly from raw (generation - demand) and the system
power balance relaxed to sum(generation) - sum(demand) == sum(loss).
Minimizing generation cost pulls each loss_l down to its tight value, so
one solve is exact — no bus-level loss allocation or iteration needed.

true_loss_mw below is the plain-numpy version of that same formula, used
only for reporting the realized loss from a solved flow (not inside the
optimization itself).
"""

import numpy as np


def true_loss_mw(flow_val, R, Sbase=100.0):
    """Exact I^2R loss (MW) for each line given realized numeric flow (MW).

    loss_l = R_l * flow_l**2 / Sbase, the standard per-unit line loss
    formula (R_l in pu, Sbase = system base MVA).
    """
    R = np.asarray(R, dtype=float).flatten()
    flow_val = np.asarray(flow_val, dtype=float).flatten()
    return R * flow_val ** 2 / Sbase
