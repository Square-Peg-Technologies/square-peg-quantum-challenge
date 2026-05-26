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

assets_path = os.path.join(os.path.dirname(__file__), "..", "use_cases", "pjm5", "assets.py")
assets_spec = importlib.util.spec_from_file_location("assets", assets_path)
assets_mod = importlib.util.module_from_spec(assets_spec)
assets_spec.loader.exec_module(assets_mod)
generators = assets_mod.GENERATORS
batteries  = assets_mod.BATTERIES

from solvers.siting_mip import run_siting_mip          # noqa: E402
from solvers.results import SitingResult, UCResult      # noqa: E402


@pytest.mark.slow
def test_returns_siting_result():
    result = run_siting_mip(grid, generators, batteries, T=1, n_results=3)
    assert isinstance(result, SitingResult)


@pytest.mark.slow
def test_returns_requested_count():
    result = run_siting_mip(grid, generators, batteries, T=1, n_results=3)
    assert len(result.ranking) == 3


@pytest.mark.slow
def test_ranking_is_sorted():
    result = run_siting_mip(grid, generators, batteries, T=1, n_results=3)
    costs = [cost for (_, cost, _) in result.ranking]
    assert costs == sorted(costs)


@pytest.mark.slow
def test_bus_assignments_valid():
    result = run_siting_mip(grid, generators, batteries, T=1, n_results=3)
    n_bus = len(grid.PTDF[0])
    for (bus_tuple, _, _) in result.ranking:
        assert len(bus_tuple) == len(batteries)
        for bus in bus_tuple:
            assert 1 <= bus <= n_bus


@pytest.mark.slow
def test_all_placements_distinct():
    result = run_siting_mip(grid, generators, batteries, T=1, n_results=3)
    placements = [bus_tuple for (bus_tuple, _, _) in result.ranking]
    assert len(placements) == len(set(placements))


@pytest.mark.slow
def test_uc_result_shapes():
    result = run_siting_mip(grid, generators, batteries, T=1, n_results=1)
    _, _, uc = result.ranking[0]
    assert isinstance(uc, UCResult)
    assert uc.dispatch.shape       == (len(generators), 1)
    assert uc.commitment.shape     == (len(generators), 1)
    assert uc.battery_charge.shape == (len(batteries), 1)
    assert uc.total_cost > 0


@pytest.mark.slow
def test_costs_positive():
    result = run_siting_mip(grid, generators, batteries, T=1, n_results=3)
    for (_, cost, _) in result.ranking:
        assert cost > 0
