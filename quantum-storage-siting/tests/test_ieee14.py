"""
Tests for the IEEE 14-bus use case.

Fast tests cover grid structure, datacenter load injection, assets file content,
and proxy/BQM/ansatz construction — no UC/ED solves.
Full quantum siting end-to-end is marked @pytest.mark.slow.
"""

import importlib.util
import os
import sys

import numpy as np
import pytest

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__),
        "..", "..", "..", "..", "Tutorial", "Quantum Network Flow Diagrams",
    ),
)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_IEEE14_DIR = os.path.join(os.path.dirname(__file__), "..", "use_cases", "ieee14")
sys.path.insert(0, _IEEE14_DIR)


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_IEEE14_DIR, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ieee14_mod = _load("ieee14", "ieee14.py")
_assets_mod = _load("assets", "assets.py")
_assets_dc4_mod = _load("assets_dc_bus4", "assets_dc_bus4.py")

from solvers.quantum_siting import (  # noqa: E402
    build_proxy_cost_fn,
    build_bqm,
    build_butterfly_ansatz,
    run_quantum_siting,
)
from solvers.results import QuantumSitingResult  # noqa: E402

N_BUSES = 14
N_BRANCHES = 20
G = len(_assets_mod.GENERATORS)
B = len(_assets_mod.BATTERIES)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def grid():
    return _ieee14_mod.Case()


@pytest.fixture(scope="module")
def grid_dc4():
    g = _ieee14_mod.Case()
    dc_bus_0 = _assets_dc4_mod.DATACENTER_BUS - 1
    g.power_demand[dc_bus_0, :] += _assets_dc4_mod.DATACENTER_MW
    return g


@pytest.fixture(scope="module")
def demand_ref(grid):
    return float(np.nanmax(np.array(grid.power_demand).sum(axis=0)))


@pytest.fixture(scope="module")
def proxy_tuple(demand_ref):
    return build_proxy_cost_fn(
        _assets_mod.GENERATORS, _assets_mod.BATTERIES, N_BUSES, demand_ref
    )


@pytest.fixture(scope="module")
def proxy_fn(proxy_tuple):
    return proxy_tuple[0]


@pytest.fixture(scope="module")
def lambdas(proxy_tuple):
    return proxy_tuple[1], proxy_tuple[2]


@pytest.fixture(scope="module")
def bqm(demand_ref, lambdas):
    l1, l2 = lambdas
    return build_bqm(
        _assets_mod.GENERATORS, _assets_mod.BATTERIES, N_BUSES, demand_ref, l1, l2
    )


# ---------------------------------------------------------------------------
# Grid structure
# ---------------------------------------------------------------------------

def test_grid_ptdf_shape(grid):
    ptdf = np.array(grid.PTDF)
    assert ptdf.shape == (N_BRANCHES, N_BUSES)


def test_grid_fbar_length(grid):
    assert len(np.array(grid.fbar).flatten()) == N_BRANCHES


def test_grid_demand_shape(grid):
    assert np.array(grid.power_demand).shape == (N_BUSES, 24)


def test_grid_demand_non_negative(grid):
    assert np.all(np.array(grid.power_demand) >= 0)


def test_grid_peak_demand_reasonable(grid):
    # Peak base demand ~363 MW (1.4x base 259 MW)
    total = np.array(grid.power_demand).sum(axis=0)
    assert 300 < total.max() < 500


# ---------------------------------------------------------------------------
# Datacenter injection
# ---------------------------------------------------------------------------

def test_datacenter_bus_is_four():
    assert _assets_dc4_mod.DATACENTER_BUS == 4


def test_datacenter_mw_is_200():
    assert _assets_dc4_mod.DATACENTER_MW == 200.0


def test_datacenter_injection_increases_demand(grid, grid_dc4):
    base_total = np.array(grid.power_demand).sum(axis=0).sum()
    dc_total = np.array(grid_dc4.power_demand).sum(axis=0).sum()
    assert dc_total > base_total


def test_datacenter_injection_amount(grid, grid_dc4):
    # Should add exactly 200 MW × 24 hours = 4800 MWh total
    base_total = np.array(grid.power_demand).sum(axis=0).sum()
    dc_total = np.array(grid_dc4.power_demand).sum(axis=0).sum()
    assert abs((dc_total - base_total) - 200.0 * 24) < 1e-6


def test_datacenter_only_affects_bus4(grid, grid_dc4):
    base = np.array(grid.power_demand)
    dc = np.array(grid_dc4.power_demand)
    dc_bus_0 = _assets_dc4_mod.DATACENTER_BUS - 1
    # All buses except bus 4 unchanged
    for i in range(N_BUSES):
        if i != dc_bus_0:
            assert np.allclose(base[i, :], dc[i, :])


def test_datacenter_peak_demand_with_dc(grid_dc4):
    # Peak with datacenter should be ~563 MW (363 + 200)
    total = np.array(grid_dc4.power_demand).sum(axis=0)
    assert 540 < total.max() < 590


# ---------------------------------------------------------------------------
# Assets files
# ---------------------------------------------------------------------------

def test_base_assets_generator_count():
    assert len(_assets_mod.GENERATORS) == 5


def test_base_assets_battery_count():
    assert len(_assets_mod.BATTERIES) == 4


def test_base_assets_no_datacenter():
    assert _assets_mod.DATACENTER_BUS is None
    assert _assets_mod.DATACENTER_MW == 0.0


def test_generator_buses_match_case14():
    buses = [g["bus"] for g in _assets_mod.GENERATORS]
    assert buses == [1, 2, 3, 6, 8]


def test_generator_capacities_positive():
    for g in _assets_mod.GENERATORS:
        assert g["p_max"] > g["p_min"] >= 0


def test_cheap_generators_cheaper_than_expensive():
    cheap = [g for g in _assets_mod.GENERATORS if g["bus"] in (1, 2)]
    expensive = [g for g in _assets_mod.GENERATORS if g["bus"] in (3, 6, 8)]
    assert all(c["cost_b"] < e["cost_b"] for c in cheap for e in expensive)


def test_assets_dc4_imports_from_base():
    # assets_dc_bus4.py re-exports the same data as assets.py
    assert _assets_dc4_mod.GENERATORS == _assets_mod.GENERATORS
    assert _assets_dc4_mod.BATTERIES == _assets_mod.BATTERIES


def test_feasible_dc_assets_files_exist():
    # site_datacenter.py should have written assets for buses 1, 2, 4, 5
    for bus in [1, 2, 4, 5]:
        path = os.path.join(_IEEE14_DIR, f"assets_dc_bus{bus}.py")
        assert os.path.exists(path), f"Missing assets_dc_bus{bus}.py"


def test_dc_assets_have_correct_bus():
    for bus in [1, 2, 4, 5]:
        mod = _load(f"assets_dc_bus{bus}", f"assets_dc_bus{bus}.py")
        assert mod.DATACENTER_BUS == bus
        assert mod.DATACENTER_MW == 200.0


# ---------------------------------------------------------------------------
# Proxy cost function
# ---------------------------------------------------------------------------

def test_proxy_fn_callable(proxy_fn):
    assert callable(proxy_fn)


def test_proxy_fn_returns_float(proxy_fn):
    # All generators ON, 4 batteries placed at first 4 buses
    bitstring = "1" * G + "1" * B + "0" * (N_BUSES - B)
    assert isinstance(proxy_fn(bitstring), float)


def test_proxy_fn_non_negative(proxy_fn):
    bitstring = "1" * G + "1" * B + "0" * (N_BUSES - B)
    assert proxy_fn(bitstring) >= 0


def test_proxy_fn_penalises_wrong_battery_count(proxy_fn):
    u = "1" * G
    s_exact = "1" * B + "0" * (N_BUSES - B)
    s_extra = "1" * (B + 1) + "0" * (N_BUSES - B - 1)
    assert proxy_fn(u + s_extra) > proxy_fn(u + s_exact)


def test_lambdas_positive(lambdas):
    l1, l2 = lambdas
    assert l1 > 0
    assert l2 > 0


# ---------------------------------------------------------------------------
# BQM
# ---------------------------------------------------------------------------

def test_bqm_variable_count(bqm):
    assert len(bqm.variables) == G + N_BUSES


def test_bqm_has_gen_variables(bqm):
    for g in range(G):
        assert f"u_{g}" in bqm.variables


def test_bqm_has_siting_variables(bqm):
    for i in range(N_BUSES):
        assert f"s_{i}" in bqm.variables


def test_bqm_energy_finite(bqm):
    sample = {f"u_{g}": 1 for g in range(G)}
    sample.update({f"s_{i}": 1 if i < B else 0 for i in range(N_BUSES)})
    assert np.isfinite(bqm.energy(sample))


# ---------------------------------------------------------------------------
# Butterfly ansatz (19 qubits = 5 gen + 14 bus)
# ---------------------------------------------------------------------------

def test_ansatz_qubit_count():
    n_qubits = G + N_BUSES
    qc, _ = build_butterfly_ansatz(n_qubits, n_layers=3)
    assert qc.num_qubits == n_qubits


def test_ansatz_param_count():
    n_qubits = G + N_BUSES
    n_layers = 3
    _, params = build_butterfly_ansatz(n_qubits, n_layers)
    assert len(params) == 2 * n_layers * n_qubits


def test_ansatz_has_measurements():
    qc, _ = build_butterfly_ansatz(G + N_BUSES, n_layers=3)
    assert len(qc.cregs) > 0


# ---------------------------------------------------------------------------
# Full quantum siting (slow)
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_ieee14_quantum_siting_returns_result(grid_dc4):
    result = run_quantum_siting(
        grid=grid_dc4,
        generators=_assets_dc4_mod.GENERATORS,
        batteries=_assets_dc4_mod.BATTERIES,
        T=4,
        backend="qiskit",
        n_candidates=5,
        second_stage="ed",
    )
    assert isinstance(result, QuantumSitingResult)


@pytest.mark.slow
def test_ieee14_at_least_one_candidate_survives(grid_dc4):
    result = run_quantum_siting(
        grid=grid_dc4,
        generators=_assets_dc4_mod.GENERATORS,
        batteries=_assets_dc4_mod.BATTERIES,
        T=4,
        backend="qiskit",
        n_candidates=5,
        second_stage="ed",
    )
    assert len(result.evaluated) >= 1


@pytest.mark.slow
def test_ieee14_best_cost_positive(grid_dc4):
    result = run_quantum_siting(
        grid=grid_dc4,
        generators=_assets_dc4_mod.GENERATORS,
        batteries=_assets_dc4_mod.BATTERIES,
        T=4,
        backend="qiskit",
        n_candidates=5,
        second_stage="ed",
    )
    _, _, cost, _ = result.best
    assert cost > 0 and np.isfinite(cost)


@pytest.mark.slow
def test_ieee14_battery_count_correct(grid_dc4):
    result = run_quantum_siting(
        grid=grid_dc4,
        generators=_assets_dc4_mod.GENERATORS,
        batteries=_assets_dc4_mod.BATTERIES,
        T=4,
        backend="qiskit",
        n_candidates=5,
        second_stage="ed",
    )
    for _, s_bits, _ in result.quantum_candidates:
        assert sum(int(b) for b in s_bits) == B
