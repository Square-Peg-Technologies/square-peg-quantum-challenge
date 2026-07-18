"""
IonQ execution backend via qBraid's runtime (QbraidProvider).

Used only for the FINAL shot-sampling step of the quantum siting VQA, never
for COBYLA training — each qBraid submission is a real network round trip
(job queue + poll), so running hundreds of COBYLA iterations through it would
be far too slow and would burn shots/credits on parameter search instead of
on the reported result. Training still runs on the local Aer/Qiskit
statevector sampler exactly as the "qiskit" backend does; only the converged
circuit's final sample is executed here, so the reported result actually ran
on qBraid-routed IonQ hardware/simulator.

Swapping in the real Forte 1 QPU once account access is sorted out (see
Constitution/Todo.md) is a one-line change: update DEVICE_ID below to the
online, non-"aws:" Forte 1 route (as of 2026-07-14, "openquantum:ionq:qpu:
forte-1" once the Open Quantum account is linked, or "azure:ionq:qpu:forte-1"
if that route comes online — avoid "aws:ionq:qpu:forte-1", which bills
against AWS marketplace credits we don't have and 402s).
"""

from __future__ import annotations

import os

# --- Single swap point for real hardware ------------------------------------
# Currently the qBraid-native IonQ simulator (confirmed working 2026-07-14,
# billed against qBraid credits). Change to a Forte 1 device ID to run on
# real QPU hardware once account access allows it.
DEVICE_ID = "ionq:ionq:sim:simulator"

# IonQ jobs (via qBraid) reject shots below 100.
MIN_SHOTS = 100

# The one qBraid device ID that is free (no per-shot billing) — used to pick
# the right default shot count automatically. Keep in sync with DEVICE_ID's
# simulator route if that ever changes.
FREE_SIMULATOR_ID = "ionq:ionq:sim:simulator"

# Default shots on the free simulator: no cost penalty for over-sampling, so
# use enough to match the local "qiskit"/"aer_tn" backends' final sample size
# and avoid spurious infeasible candidates from an under-sampled distribution.
DEFAULT_SHOTS_SIMULATOR = 5000

# Default shots on billed real hardware (e.g. Forte 1), at 3 credits/task +
# 8 credits/shot: 500 shots = 4,003 credits (~$40 at 10,000 credits/$100).
# Empirically (2026-07-14, ieee14/4batt_dcbus4, 24h) 500 shots already finds
# the same top-ranked placement as 5000 shots; 250 shots and below is not
# reliable (too few valid post-selected candidates). Only ~4% of a 10,000
# credit budget per run, vs. ~40% for 5000 shots.
DEFAULT_SHOTS_HARDWARE = 500


def default_shots(device_id: str = None) -> int:
    """Pick a sensible default shot count for the given device.

    Returns DEFAULT_SHOTS_SIMULATOR for the free qBraid IonQ simulator, or
    DEFAULT_SHOTS_HARDWARE for anything else (billed real hardware) — so
    callers don't have to remember to shrink the shot count by hand when
    DEVICE_ID gets swapped to a real Forte 1 route.
    """
    if device_id is None:
        device_id = DEVICE_ID
    return DEFAULT_SHOTS_SIMULATOR if device_id == FREE_SIMULATOR_ID else DEFAULT_SHOTS_HARDWARE


def _load_token() -> str:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    token = os.environ.get("IONQ_TOKEN")
    if not token:
        raise RuntimeError(
            "IONQ_TOKEN is not set. Add it to a .env file in the repo root "
            "(this is your qBraid API key, from account.qbraid.com — despite "
            "the variable name, it is NOT a standalone IonQ Cloud key)."
        )
    return token.strip().strip("'\"")


def get_device(device_id: str = DEVICE_ID):
    """Return a qBraid runtime device object for the given device ID."""
    try:
        from qbraid.runtime import QbraidProvider
    except ImportError as err:
        raise RuntimeError(
            "qbraid is not installed. Run: pip install qbraid --break-system-packages"
        ) from err

    token = _load_token()
    provider = QbraidProvider(api_key=token)
    return provider.get_device(device_id)


def run_circuit_shots(circuit, shots: int | None = None, device_id: str = DEVICE_ID,
                      timeout: int = 600) -> dict[str, int]:
    """Submit a Qiskit circuit to the qBraid-routed IonQ device and return counts.

    circuit must already include measurement (e.g. built with .measure_all(),
    as run_vqa_qiskit's ansatzes do) — returns the same {bitstring: count}
    shape as the local Aer/Qiskit samplers, so this is a drop-in swap for the
    final-shot extraction step in run_vqa_qiskit.

    shots defaults to default_shots(device_id) — 5000 on the free simulator,
    500 on billed real hardware — rather than a single fixed constant, so
    switching DEVICE_ID to Forte 1 doesn't silently also switch you to a
    5000-shot bill.
    """
    if shots is None:
        shots = default_shots(device_id)
    if shots < MIN_SHOTS:
        raise ValueError(f"shots={shots} is below IonQ's minimum of {MIN_SHOTS}.")

    device = get_device(device_id)
    job = device.run(circuit, shots=shots)

    job.wait_for_final_state(timeout=timeout, poll_interval=5)
    status = job.status()
    if str(status) == "JobStatus.FAILED":
        raise RuntimeError(f"IonQ job failed on the server: {status.status_message}")

    result = job.result()
    return dict(result.data.get_counts())
