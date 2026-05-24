"""
Tests for the Unit Commitment solver (solvers/uc.py).

SCIP is slow so all tests here are marked slow.
One UC solve at T=1 shared across all tests via a module-scoped fixture.
"""

import sys
import os
import importlib.util

import numpy as np
import pytest

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__),
        "..", "..", "..", "..",
        "Tutorial", "Quantum Network Flow Diagrams",
    ),
)

_pjm5_path = os.path.join(os.path.dirname(__file__), "..", "use_cases", "pjm5", "pjm5.py")
_spec = importlib.util.spec_from_file_location("pjm5", os.path.abspath(_pjm5_path))
_pjm5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pjm5)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "use_cases", "pjm5")))
from assets import GENERATORS, BATTERIES  # noqa: E402
from locations import BATTERY_LOCATIONS  # noqa: E402
from solvers.uc import run_uc  # noqa: E402
from solvers.results import UCResult  # noqa: E402

T_TEST = 1


@pytest.fixture(scope="module")
def grid():
    g = _pjm5.Case()
    g.power_demand = g.power_demand[:, :T_TEST]
    return g


@pytest.fixture(scope="module")
def uc_result(grid):
    return run_uc(grid, GENERATORS, BATTERIES, BATTERY_LOCATIONS, T_TEST)


@pytest.mark.slow
def test_uc_returns_result(uc_result):
    assert isinstance(uc_result, UCResult)
    assert np.isfinite(uc_result.total_cost)
    assert uc_result.total_cost > 0


@pytest.mark.slow
def test_commitment_binary(uc_result):
    comm = uc_result.commitment
    assert np.all((comm >= -1e-6) & (comm <= 1 + 1e-6))
    assert np.all(np.abs(comm - np.round(comm)) < 1e-6)


@pytest.mark.slow
def test_generator_commitment_link(uc_result):
    for g, gen in enumerate(GENERATORS):
        for t in range(T_TEST):
            if uc_result.commitment[g, t] == 0:
                assert uc_result.dispatch[g, t] < 1e-3
            else:
                assert uc_result.dispatch[g, t] >= gen["p_min"] - 1e-3


@pytest.mark.slow
def test_power_balance_uc(uc_result, grid):
    for t in range(T_TEST):
        total_gen = uc_result.dispatch[:, t].sum()
        net_bat = (uc_result.battery_discharge[:, t] - uc_result.battery_charge[:, t]).sum()
        total_dem = grid.power_demand[:, t].sum()
        assert abs(total_gen + net_bat - total_dem) < 1.0
