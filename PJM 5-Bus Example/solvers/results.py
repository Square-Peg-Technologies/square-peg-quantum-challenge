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
