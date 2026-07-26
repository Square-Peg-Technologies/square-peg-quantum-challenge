"""
Rigetti execution backend via qBraid's runtime (QbraidProvider).

Used only for the FINAL shot-sampling step of the quantum siting VQA, never
for COBYLA training — each qBraid submission is a real network round trip
(job queue + poll), so running hundreds of COBYLA iterations through it would
be far too slow and would burn shots/QCS time on parameter search instead of
on the reported result. Training still runs on the local Aer/Qiskit
statevector sampler exactly as the "qiskit" backend does; only the converged
circuit's final sample is executed here, so the reported result actually ran
on Rigetti QPU hardware.

Unlike solvers/ionq_qbraid_backend.py, there is no free-simulator route here
— DEVICE_ID below is a real QPU (verified working manually via
scripts/Rigetti_test.py, 2026-07-26) and every run bills qBraid credits and
queues for hardware time.

No manual transpile/gate-set-conversion step is needed before calling
run_circuit_shots: qBraid's RigettiDevice.transform() compiles the submitted
circuit into the QPU's native gate set via quilc automatically as part of
device.run(), the same way the IonQ backend needs no manual step either.
"""

from __future__ import annotations

import os

# --- Single swap point for the target device --------------------------------
# Real Rigetti QCS QPU (confirmed working manually 2026-07-26, billed against
# qBraid credits/QCS time — there is no free-simulator equivalent to IonQ's
# "ionq:ionq:sim:simulator"). Change to a different Rigetti QCS processor ID
# to target another chip.
DEVICE_ID = "rigetti:rigetti:qpu:cepheus-1-108q"

# Default shots for the final extraction. Real QPU time is billed, so this
# stays modest rather than matching the local/IonQ-simulator default of 5000
# — bump it explicitly via run_circuit_shots(shots=...) if a run needs more.
DEFAULT_SHOTS = 200


def default_shots(device_id: str = None) -> int:
    """Return the default shot count for the given device (always DEFAULT_SHOTS
    for now — kept as a function, mirroring ionq_qbraid_backend.default_shots,
    so callers don't need to special-case this module if a free-simulator
    route is ever added here too).
    """
    return DEFAULT_SHOTS


def _load_token() -> str:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    # Reuses the same qBraid platform key as IONQ_TOKEN (see
    # scripts/Rigetti_test.py) — it's the same underlying qBraid API key
    # regardless of which provider it routes to.
    token = os.environ.get("IONQ_TOKEN")
    if not token:
        raise RuntimeError(
            "IONQ_TOKEN is not set. Add it to a .env file in the repo root "
            "(this is your qBraid API key, from account.qbraid.com, reused "
            "here for Rigetti access same as the IonQ backend)."
        )
    return token.strip().strip("'\"")


def get_device(device_id: str = DEVICE_ID):
    """Return a qBraid runtime device object for the given device ID."""
    try:
        from qbraid.runtime import QbraidProvider
    except ImportError as err:
        raise RuntimeError(
            "qbraid is not installed. Run: pip install 'qbraid[qiskit]' --break-system-packages"
        ) from err

    token = _load_token()
    provider = QbraidProvider(api_key=token)
    return provider.get_device(device_id)


def run_circuit_shots(circuit, shots: int | None = None, device_id: str = DEVICE_ID,
                      timeout: int = 600) -> dict[str, int]:
    """Submit a Qiskit circuit to the qBraid-routed Rigetti QPU and return counts.

    circuit must already include measurement (e.g. built with .measure_all(),
    as run_vqa_qiskit's ansatzes do) — returns the same {bitstring: count}
    shape as the local Aer/Qiskit samplers and the IonQ backend, so this is a
    drop-in swap for the final-shot extraction step in run_vqa_qiskit.

    shots defaults to default_shots(device_id) — 100, since this is real
    billed QPU hardware with no free-simulator route to fall back to.
    """
    if shots is None:
        shots = default_shots(device_id)

    device = get_device(device_id)
    job = device.run(circuit, shots=shots)

    job.wait_for_final_state(timeout=timeout, poll_interval=5)
    status = job.status()
    if str(status) == "JobStatus.FAILED":
        raise RuntimeError(f"Rigetti job failed on the server: {status.status_message}")

    result = job.result()
    return dict(result.data.get_counts())
