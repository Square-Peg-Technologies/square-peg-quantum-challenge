"""
Tests for the Economic Dispatch solver (solvers/ed.py) and battery dynamics.

One ED solve at T=4 shared across all tests via a module-scoped fixture.
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
        "..", "..", "..", "..", "Tutorial", "Quantum Network Flow Diagrams",
    ),
)

_pjm5_path = os.path.join(os.path.dirname(__file__), "..", "use_cases", "pjm5", "pjm5.py")
_spec = importlib.util.spec_from_file_location("pjm5", _pjm5_path)
_pjm5_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pjm5_mod)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "use_cases", "pjm5"))
from assets import GENERATORS, BATTERIES  # noqa: E402
from locations import GENERATOR_LOCATIONS, BATTERY_LOCATIONS  # noqa: E402
from solvers.ed import run_ed  # noqa: E402
from solvers.results import EDResult  # noqa: E402


@pytest.fixture(scope="module")
def grid():
    return _pjm5_mod.Case()


@pytest.fixture(scope="module")
def result(grid):
    return run_ed(grid, GENERATORS, BATTERIES, GENERATOR_LOCATIONS, BATTERY_LOCATIONS, T=4)


# ---------------------------------------------------------------------------
# ED correctness
# ---------------------------------------------------------------------------

def test_ed_returns_result(result):
    assert isinstance(result, EDResult)
    assert np.isfinite(result.total_cost)
    assert result.total_cost > 0


def test_power_balance(grid, result):
    demand = np.array(grid.power_demand)
    for t in range(result.dispatch.shape[1]):
        gen_sum = float(np.sum(result.dispatch[:, t]))
        bat_net = float(np.sum(result.battery_discharge[:, t]) - np.sum(result.battery_charge[:, t]))
        total_demand = float(np.sum(demand[:, t]))
        assert abs(gen_sum + bat_net - total_demand) < 1e-3, (
            f"Hour {t}: injection={gen_sum + bat_net:.4f} != demand={total_demand:.4f}"
        )


def test_generator_limits(result):
    for g, gen in enumerate(GENERATORS):
        for t in range(result.dispatch.shape[1]):
            val = result.dispatch[g, t]
            assert val >= gen["p_min"] - 1e-3
            assert val <= gen["p_max"] + 1e-3


def test_soc_limits(result):
    for b, bat in enumerate(BATTERIES):
        cap = bat["capacity_mwh"]
        for t in range(result.soc.shape[1]):
            val = result.soc[b, t]
            assert val >= -1e-6
            assert val <= cap + 1e-6


# ---------------------------------------------------------------------------
# Battery dynamics
# ---------------------------------------------------------------------------

def test_no_simultaneous_charge_discharge(result):
    for b in range(result.battery_charge.shape[0]):
        for t in range(result.battery_charge.shape[1]):
            product = result.battery_charge[b, t] * result.battery_discharge[b, t]
            assert product < 1e-6, (
                f"Bat {b} hour {t}: simultaneous charge/discharge"
            )


def test_soc_dynamics(result):
    bat = BATTERIES[0]
    eta = bat["efficiency"]
    for t in range(1, result.soc.shape[1]):
        expected = result.soc[0, t - 1] + eta * result.battery_charge[0, t] - result.battery_discharge[0, t]
        assert abs(result.soc[0, t] - expected) < 1e-4


def test_charge_rate_limit(result):
    for b, bat in enumerate(BATTERIES):
        assert np.all(result.battery_charge[b] <= bat["power_mw"] + 1e-3)


def test_discharge_rate_limit(result):
    for b, bat in enumerate(BATTERIES):
        assert np.all(result.battery_discharge[b] <= bat["power_mw"] + 1e-3)
