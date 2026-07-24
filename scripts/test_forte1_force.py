"""
Diagnostic script that discovered qBraid's device.profile.noise_models for
"ionq:ionq:sim:simulator" is stale: it lists {"aria-1", "harmony", "ideal"}
(harmony was retired by IonQ in July 2025) and omits "forte-1", even though
IonQ's own docs (docs.ionq.com/features/simulation-with-noise-models) list
forte-1 as the current, actively-supported noise model.

This script proves the qBraid *backend* accepts "forte-1" fine — only the
SDK's local, client-side membership check (in
qbraid.runtime.native.device.QbraidDevice._resolve_noise_model) rejects it,
by comparing against that stale in-memory list. Force-registering "forte-1"
into device.profile.noise_models (a plain local Python object, no network
call) is enough to get past the client-side check and successfully submit a
real forte-1-noise job.

This exact workaround is now built into
solvers/ionq_qbraid_backend.run_circuit_shots(noisy=True) — this script is
kept only as a record of how the workaround was discovered/verified.

Usage:
    python scripts/test_forte1_force.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qiskit import QuantumCircuit
from solvers.ionq_qbraid_backend import get_device

qc = QuantumCircuit(2)
qc.h(0)
qc.cx(0, 1)
qc.measure_all()

device = get_device()
print("Before force-add:", device.profile.noise_models)

device.profile.noise_models.add("forte-1")
print("After force-add:", device.profile.noise_models)

try:
    job = device.run(qc, shots=100, runtime_options={"noise_model": "forte-1"})
    job.wait_for_final_state(timeout=300, poll_interval=5)
    status = job.status()
    print("Status:", status)
    if str(status) == "JobStatus.FAILED":
        print("FAILED message:", status.status_message)
    else:
        result = job.result()
        print("Counts:", dict(result.data.get_counts()))
except Exception as e:
    print(f"Exception ({type(e).__name__}): {e}")
