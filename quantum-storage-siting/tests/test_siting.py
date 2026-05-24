import importlib.util
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "Tutorial", "Quantum Network Flow Diagrams"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Load pjm5 grid
pjm5_path = os.path.join(os.path.dirname(__file__), "..", "use_cases", "pjm5", "pjm5.py")
spec = importlib.util.spec_from_file_location("pjm5", pjm5_path)
pjm5_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pjm5_mod)
grid = pjm5_mod.Case()

# Load assets
assets_path = os.path.join(os.path.dirname(__file__), "..", "use_cases", "pjm5", "assets.py")
assets_spec = importlib.util.spec_from_file_location("assets", assets_path)
assets_mod = importlib.util.module_from_spec(assets_spec)
assets_spec.loader.exec_module(assets_mod)
generators = assets_mod.GENERATORS
batteries = assets_mod.BATTERIES

from solvers.siting import run_siting  # noqa: E402
from solvers.results import SitingResult  # noqa: E402


# Slow: runs 10 UC solves at T=1
@pytest.mark.slow
def test_siting_count():
    result = run_siting(grid, generators, batteries, T=1)
    assert isinstance(result, SitingResult)
    assert len(result.ranking) == 10


@pytest.mark.slow
def test_siting_sorted():
    result = run_siting(grid, generators, batteries, T=1)
    ranking = result.ranking
    assert all(ranking[i][1] <= ranking[i + 1][1] for i in range(9))


@pytest.mark.slow
def test_best_le_worst():
    result = run_siting(grid, generators, batteries, T=1)
    assert result.ranking[0][1] <= result.ranking[-1][1]


@pytest.mark.slow
def test_bus_pairs_valid():
    result = run_siting(grid, generators, batteries, T=1)
    for (pair, cost, uc_result) in result.ranking:
        assert pair[0] in {1, 2, 3, 4, 5}
        assert pair[1] in {1, 2, 3, 4, 5}
        assert pair[0] != pair[1]
        assert pair[0] < pair[1]
