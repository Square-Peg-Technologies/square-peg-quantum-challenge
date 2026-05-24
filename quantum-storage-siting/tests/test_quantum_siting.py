"""
Tests for the Quantum Siting solver (solvers/quantum_siting.py).

D-Wave SA tests are excluded — use test_dwave_siting.py if needed.
Qiskit VQA end-to-end is marked @pytest.mark.slow.
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

_pjm5_path = os.path.join(os.path.dirname(__file__), "..", "use_cases", "pjm5", "pjm5.py")
_spec = importlib.util.spec_from_file_location("pjm5", _pjm5_path)
_pjm5_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pjm5_mod)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "use_cases", "pjm5"))
from assets import GENERATORS, BATTERIES  # noqa: E402
from solvers.quantum_siting import (  # noqa: E402
    build_proxy_cost_fn,
    build_bqm,
    build_butterfly_ansatz,
    run_quantum_siting,
)
from solvers.results import QuantumSitingResult, EDResult, UCResult  # noqa: E402

N_BUSES = 5
G = len(GENERATORS)
B = len(BATTERIES)
DEMAND_REF = 400.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def grid():
    return _pjm5_mod.Case()


@pytest.fixture(scope="module")
def proxy_tuple():
    return build_proxy_cost_fn(GENERATORS, BATTERIES, N_BUSES, DEMAND_REF)


@pytest.fixture(scope="module")
def proxy_fn(proxy_tuple):
    return proxy_tuple[0]


@pytest.fixture(scope="module")
def lambdas(proxy_tuple):
    return proxy_tuple[1], proxy_tuple[2]


@pytest.fixture(scope="module")
def bqm(lambdas):
    l1, l2 = lambdas
    return build_bqm(GENERATORS, BATTERIES, N_BUSES, DEMAND_REF, l1, l2)


@pytest.fixture(scope="module")
def qiskit_result(grid):
    return run_quantum_siting(
        grid=grid,
        generators=GENERATORS,
        batteries=BATTERIES,
        T=4,
        backend="qiskit",
        n_candidates=5,
        second_stage="ed",
    )


# ---------------------------------------------------------------------------
# build_proxy_cost_fn
# ---------------------------------------------------------------------------

def test_proxy_fn_returns_three_tuple(proxy_tuple):
    assert len(proxy_tuple) == 3


def test_lambdas_positive(lambdas):
    l1, l2 = lambdas
    assert l1 > 0
    assert l2 > 0


def test_proxy_fn_callable(proxy_fn):
    assert callable(proxy_fn)


def test_proxy_fn_returns_float(proxy_fn):
    bs = "1" * G + "0" * N_BUSES
    assert isinstance(proxy_fn(bs), float)


def test_proxy_fn_non_negative(proxy_fn):
    for u_val in ["000", "111", "101"]:
        for s_val in ["00000", "11000", "01010"]:
            assert proxy_fn(u_val + s_val) >= 0


def test_proxy_fn_budget_penalty_for_wrong_count(proxy_fn, lambdas):
    # With all generators on (capacity >> DEMAND_REF), P_infeas=0 for any battery
    # count, so budget penalty is the only difference between exact and extra.
    s_exact = "1" * B + "0" * (N_BUSES - B)
    s_extra = "1" * (B + 1) + "0" * (N_BUSES - B - 1)
    cost_exact = proxy_fn("1" * G + s_exact)
    cost_extra = proxy_fn("1" * G + s_extra)
    assert cost_extra > cost_exact



# ---------------------------------------------------------------------------
# build_bqm
# ---------------------------------------------------------------------------

def test_bqm_is_binary_quadratic_model(bqm):
    import dimod
    assert isinstance(bqm, dimod.BinaryQuadraticModel)
    assert bqm.vartype.name == "BINARY"


def test_bqm_has_all_variables(bqm):
    for g in range(G):
        assert f"u_{g}" in bqm.variables
    for i in range(N_BUSES):
        assert f"s_{i}" in bqm.variables


def test_bqm_variable_count(bqm):
    assert len(bqm.variables) == G + N_BUSES


def test_bqm_quadratic_count(bqm):
    expected = G * (G - 1) // 2 + N_BUSES * (N_BUSES - 1) // 2 + G * N_BUSES
    assert len(bqm.quadratic) == expected


def test_bqm_energy_finite(bqm):
    sample = {f"u_{g}": 1 for g in range(G)}
    sample.update({f"s_{i}": 1 if i < B else 0 for i in range(N_BUSES)})
    assert np.isfinite(bqm.energy(sample))


# ---------------------------------------------------------------------------
# build_butterfly_ansatz
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n_qubits,n_layers", [(8, 2), (8, 3), (4, 1)])
def test_butterfly_ansatz_qubit_count(n_qubits, n_layers):
    qc, _ = build_butterfly_ansatz(n_qubits, n_layers)
    assert qc.num_qubits == n_qubits


@pytest.mark.parametrize("n_qubits,n_layers", [(8, 2), (8, 3)])
def test_butterfly_ansatz_param_count(n_qubits, n_layers):
    _, params = build_butterfly_ansatz(n_qubits, n_layers)
    assert len(params) == 2 * n_layers * n_qubits


def test_butterfly_ansatz_has_measurements():
    qc, _ = build_butterfly_ansatz(8, 2)
    assert len(qc.cregs) > 0


# ---------------------------------------------------------------------------
# Qiskit VQA end-to-end (slow)
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_qiskit_returns_result(qiskit_result):
    assert isinstance(qiskit_result, QuantumSitingResult)


@pytest.mark.slow
def test_qiskit_backend_field(qiskit_result):
    assert qiskit_result.backend == "qiskit"


@pytest.mark.slow
def test_qiskit_candidates_nonempty(qiskit_result):
    assert len(qiskit_result.quantum_candidates) > 0


@pytest.mark.slow
def test_qiskit_evaluated_nonempty(qiskit_result):
    assert len(qiskit_result.evaluated) > 0


@pytest.mark.slow
def test_qiskit_feasible_candidates(qiskit_result):
    for u_bits, s_bits, _ in qiskit_result.quantum_candidates:
        assert sum(int(b) for b in s_bits) == B


@pytest.mark.slow
def test_qiskit_best_is_minimum(qiskit_result):
    min_cost = min(cost for _, _, cost, _ in qiskit_result.evaluated)
    _, _, best_cost, _ = qiskit_result.best
    assert abs(best_cost - min_cost) < 1e-6


@pytest.mark.slow
def test_qiskit_best_cost_positive(qiskit_result):
    _, _, cost, _ = qiskit_result.best
    assert cost > 0 and np.isfinite(cost)


@pytest.mark.slow
def test_qiskit_evaluated_are_ed_results(qiskit_result):
    for _, _, _, res_obj in qiskit_result.evaluated:
        assert isinstance(res_obj, EDResult)


@pytest.mark.slow
def test_qiskit_runtimes_positive(qiskit_result):
    assert qiskit_result.runtime_quantum > 0
    assert qiskit_result.runtime_classical > 0


@pytest.mark.slow
def test_qiskit_uc_second_stage(grid):
    result = run_quantum_siting(
        grid=grid,
        generators=GENERATORS,
        batteries=BATTERIES,
        T=2,
        backend="qiskit",
        n_candidates=3,
        second_stage="uc",
    )
    assert isinstance(result, QuantumSitingResult)
    assert result.second_stage == "uc"
    for _, _, _, res_obj in result.evaluated:
        assert isinstance(res_obj, UCResult)
