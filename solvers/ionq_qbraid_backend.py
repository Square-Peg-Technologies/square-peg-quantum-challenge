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

# Noise model applied when run_circuit_shots(..., noisy=True) is used: still
# the same simulator device (capped at 29 qubits regardless of noise model —
# the model only changes the error channel, not the device or qubit count).
#
# qBraid's device.profile.noise_models for "ionq:ionq:sim:simulator" reports
# only {"aria-1", "harmony", "ideal"} (verified 2026-07-24) — stale catalog
# metadata on qBraid's side: "harmony" was retired by IonQ in July 2025, while
# "forte-1" (IonQ's current, actively-supported noise model per
# docs.ionq.com/features/simulation-with-noise-models) is missing from it.
# Confirmed empirically that qBraid's *backend* accepts "forte-1" fine — only
# the client-side membership check in _resolve_noise_model rejects it — so
# run_circuit_shots force-registers "forte-1" into the profile's noise_models
# set before submitting, to work around the stale client-side list.
#
# Also verified 2026-07-24: this qBraid SDK version (0.12.2) has no seed
# parameter anywhere in the IonQ noise-model code path — noisy runs are not
# reproducible via a fixed seed the way IonQ's direct API allows.
NOISE_MODEL_ID = "forte-1"

# Default shots on billed real hardware (e.g. Forte 1), at 3 credits/task +
# 8 credits/shot: 100 shots = 803 credits (~$8 at 10,000 credits/$100, ~8% of
# a 10,000 credit budget per run). Set from the shots-vs-optimality-gap sweep
# (solvers/stop_conditions.md, 2026-07-24, ieee14/4batt_dcbus4_g2out.py,
# forte-1 noise, line_losses=True): feasibility is ~100% by 25 shots already,
# and the optimality gap vs. the best-found placement drops sharply through
# ~100 shots (0.079% median at 25 shots -> 0.032% at 100 shots) then flattens
# hard (0.032% at 100 -> 0.018% at 500) — the last 5x more shots buys a much
# smaller further improvement than the first 100 shots did.
DEFAULT_SHOTS_HARDWARE = 100


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
                      timeout: int = 600, noisy: bool = False) -> dict[str, int]:
    """Submit a Qiskit circuit to the qBraid-routed IonQ device and return counts.

    circuit must already include measurement (e.g. built with .measure_all(),
    as run_vqa_qiskit's ansatzes do) — returns the same {bitstring: count}
    shape as the local Aer/Qiskit samplers, so this is a drop-in swap for the
    final-shot extraction step in run_vqa_qiskit.

    shots defaults to default_shots(device_id) — 5000 on the free simulator,
    500 on billed real hardware — rather than a single fixed constant, so
    switching DEVICE_ID to Forte 1 doesn't silently also switch you to a
    5000-shot bill.

    noisy=True applies NOISE_MODEL_ID's hardware noise model to the simulation
    instead of running the ideal simulator (still on the same free simulator
    device, not real QPU hardware).
    """
    if shots is None:
        shots = default_shots(device_id)
    if shots < MIN_SHOTS:
        raise ValueError(f"shots={shots} is below IonQ's minimum of {MIN_SHOTS}.")

    device = get_device(device_id)
    if noisy:
        if NOISE_MODEL_ID not in device.profile.noise_models:
            # qBraid's device catalog is stale and doesn't list NOISE_MODEL_ID
            # even though qBraid's backend accepts it fine (see NOISE_MODEL_ID
            # comment above) — register it locally so the SDK's client-side
            # membership check in _resolve_noise_model doesn't reject it.
            device.profile.noise_models.add(NOISE_MODEL_ID)
        job = device.run(circuit, shots=shots, runtime_options={"noise_model": NOISE_MODEL_ID})
    else:
        job = device.run(circuit, shots=shots)

    job.wait_for_final_state(timeout=timeout, poll_interval=5)
    status = job.status()
    if str(status) == "JobStatus.FAILED":
        raise RuntimeError(f"IonQ job failed on the server: {status.status_message}")

    result = job.result()
    return dict(result.data.get_counts())
