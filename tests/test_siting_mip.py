import importlib.util
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Load pjm5 grid
pjm5_path = os.path.join(os.path.dirname(__file__), "..", "use_cases", "pjm5", "pjm5.py")
spec = importlib.util.spec_from_file_location("pjm5", pjm5_path)
pjm5_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pjm5_mod)
grid = pjm5_mod.Case()

assets_path = os.path.join(os.path.dirname(__file__), "..", "use_cases", "pjm5", "2batt.py")
assets_spec = importlib.util.spec_from_file_location("assets", assets_path)
assets_mod = importlib.util.module_from_spec(assets_spec)
assets_spec.loader.exec_module(assets_mod)
generators = assets_mod.GENERATORS
batteries  = assets_mod.BATTERIES

from solvers.siting_mip import run_siting_mip          # noqa: E402
from solvers.results import SitingMIPResult, UCResult  # noqa: E402


@pytest.mark.slow
def test_returns_siting_mip_result():
    result = run_siting_mip(grid, generators, batteries, T=1)
    assert isinstance(result, SitingMIPResult)


@pytest.mark.slow
def test_bus_assignments_valid():
    result = run_siting_mip(grid, generators, batteries, T=1)
    n_bus = len(grid.PTDF[0])
    assert len(result.bus_tuple) == len(batteries)
    for bus in result.bus_tuple:
        assert 1 <= bus <= n_bus
    assert result.bat_locs == {b: result.bus_tuple[b] for b in range(len(batteries))}


@pytest.mark.slow
def test_cost_positive():
    result = run_siting_mip(grid, generators, batteries, T=1)
    assert result.total_cost > 0


@pytest.mark.slow
def test_uc_result_shapes():
    result = run_siting_mip(grid, generators, batteries, T=1)
    uc = result.uc_result
    assert isinstance(uc, UCResult)
    assert uc.dispatch.shape       == (len(generators), 1)
    assert uc.commitment.shape     == (len(generators), 1)
    assert uc.battery_charge.shape == (len(batteries), 1)
    assert uc.total_cost > 0


@pytest.mark.slow
def test_cost_consistent():
    result = run_siting_mip(grid, generators, batteries, T=1)
    assert abs(result.total_cost - result.uc_result.total_cost) < 1.0


@pytest.mark.slow
def test_optimal_beats_arbitrary_placement():
    """MIP optimal cost must be <= any fixed-placement UC cost."""
    from solvers.uc import run_uc
    result = run_siting_mip(grid, generators, batteries, T=1)
    # Run UC with a fixed placement (batteries at buses 1 and 2)
    fixed_locs = {0: 1, 1: 2}
    fixed_uc = run_uc(grid, generators, batteries, fixed_locs, T=1)
    assert result.total_cost <= fixed_uc.total_cost + 1e-3
