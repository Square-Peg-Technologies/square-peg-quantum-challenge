"""I^2R transmission line loss helpers.

Shared by solvers/uc.py and solvers/ed.py, which both model losses via a
fixed-point iteration (see each module's run_uc/run_ed docstring): solve,
compute each line's exact loss from the realized flow, inject half the loss
as extra fixed demand at each line's two end buses, and re-solve until the
injected loss stops changing. These two functions are the physics: the
per-line quadratic loss formula and the bus allocation rule. Everything
here operates on plain numpy arrays (not CVXPY expressions) — losses are
computed *between* solves, not as part of the optimization itself, since an
earlier CVXPY-native piecewise-linear formulation proved structurally hard
to keep tight against gaming by other free variables in the model.
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


def loss_allocation(loss_vec, Atilde):
    """Split each line's loss half-and-half onto its two end buses.

    Parameters
    ----------
    loss_vec : np.ndarray, shape (n_line,) — per-line loss (MW), e.g. from
               true_loss_mw.
    Atilde   : np.ndarray, shape (n_line, n_bus) — line-bus incidence matrix
               (-1 at fbus, +1 at tbus), as built in dcopf.cases.base.BaseCase.

    Returns
    -------
    Extra withdrawal (MW) to add to demand at each bus, shape (n_bus,).
    """
    bus_incidence = np.abs(np.asarray(Atilde))  # 1 at each line's two end buses
    return 0.5 * (bus_incidence.T @ np.asarray(loss_vec))
