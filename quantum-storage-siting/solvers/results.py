from dataclasses import dataclass
import numpy as np


@dataclass
class EDResult:
    dispatch: np.ndarray           # shape (n_generators, T)
    battery_charge: np.ndarray     # shape (n_batteries, T)
    battery_discharge: np.ndarray  # shape (n_batteries, T)
    soc: np.ndarray                # shape (n_batteries, T)
    total_cost: float
    hourly_costs: list[float]
    congested_lines: list[list[int]]  # per hour, list of line indices


@dataclass
class UCResult:
    dispatch: np.ndarray           # shape (n_generators, T)
    battery_charge: np.ndarray     # shape (n_batteries, T)
    battery_discharge: np.ndarray  # shape (n_batteries, T)
    soc: np.ndarray                # shape (n_batteries, T)
    total_cost: float
    hourly_costs: list[float]
    congested_lines: list[list[int]]  # per hour
    commitment: np.ndarray         # shape (n_generators, T), binary
    startups: np.ndarray           # shape (n_generators, T), binary


@dataclass
class SitingResult:
    ranking: list[tuple]    # [(bus_pair, total_cost, UCResult), ...]
    infeasible: list[tuple]  # [(bus_a, bus_b), ...] placements with no valid schedule


@dataclass
class SitingMIPResult:
    bus_tuple: tuple        # optimal bus assignment per battery, e.g. (3, 7, 1, 12)
    bat_locs: dict          # {battery_index: bus_number}  (1-indexed)
    uc_result: UCResult     # full UC schedule for the optimal placement
    total_cost: float
    scip_status: str = "optimal"  # "optimal" | "timelimit" (best found so far)


@dataclass
class QuantumSitingResult:
    backend: str                   # "qiskit" | "dwave"
    second_stage: str              # "ed" | "uc"
    n_candidates: int
    quantum_candidates: list       # [(u_bits, s_bits, proxy_cost), ...]
    evaluated: list                # [(bat_locs, commitment, true_cost, result_obj), ...]
    best: tuple                    # entry in evaluated with minimum true_cost
    runtime_quantum: float         # seconds
    runtime_classical: float       # seconds
