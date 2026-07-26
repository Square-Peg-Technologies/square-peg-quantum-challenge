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

A manual transpile step IS required before submission (confirmed 2026-07-26 —
a raw H/CX circuit failed server-side with "this instruction must be replaced
or decomposed prior to compilation"). qBraid's client-side auto-rebase only
covers IonQ: QbraidProvider._get_basis_gates (qbraid/runtime/native/
provider.py) returns real basis gates for provider=="ionq" and None for every
other provider, including Rigetti — so unlike the IonQ backend, which needs
no manual step, run_circuit_shots here transpiles the circuit via Qiskit's
own transpiler before calling device.run(). The route through qBraid's own
RigettiDevice.transform()/quilc (native/direct RigettiProvider path,
requiring a separate RIGETTI_REFRESH_TOKEN) is NOT used here — QbraidProvider
returns a generic QbraidDevice instead, which skips that quilc compilation
entirely.

Getting the right basis took three tries against the live QCS API
(2026-07-26), each rejected with the same "must be replaced or decomposed
prior to compilation" error for a different residual gate:
  1. basis_gates=["rx", "rz", "cz"] — qiskit's "rx" allows an arbitrary
     continuous angle; the server rejected "RX(2.213...)"-style instructions
     the same way it rejected raw H. Only fixed pi/2 pulses are native.
  2. basis_gates=["rz", "sx", "x", "cz"] — "sx"/"x" are qiskit's own
     *fixed*-angle gates (pi/2, pi), which fixed the RX angle problem, but
     the server then rejected the named "X" instruction itself: Quil's
     compiler treats a full pi rotation as non-native too, distinct from an
     "RX(pi/2)" pulse, even though both are "fixed angle."
  3. basis_gates=["rz", "sx", "cz"] (NATIVE_GATES below, no "x") — forces
     qiskit to build everything from RZ (virtual, arbitrary angle, free) +
     SX (the actual physical pi/2 pulse) + CZ alone. This is the real native
     set for this hardware model.

A fourth failure followed, of a different kind: "CZ 0 2: this instruction
must be replaced or decomposed prior to compilation" — a *topology* error,
not a gate-basis one. The butterfly ansatz's stride pattern deliberately
entangles non-adjacent qubits (e.g. qubit 0 with qubit 2), and since no
coupling_map was passed to transpile(), it assumed all-to-all connectivity
and never inserted routing SWAPs. TargetProfile (qBraid's client-side device
metadata) has no coupling-map field, but the *raw* device response
(provider.client.get_device(DEVICE_ID), confirmed via
scripts/Rigetti_get_topology.py, 2026-07-26) includes a "topology" field:
{"type": "square-lattice", "rows": 12, "cols": 9} — 108 sites (one of which
is disabled: profile.num_qubits reports 107). COUPLING_MAP below encodes
that grid. Verified locally that transpiling with this coupling_map produces
zero coupling-map violations for the butterfly ansatz. If DEVICE_ID ever
changes to a different chip, re-run scripts/Rigetti_get_topology.py to get
that chip's real topology instead of reusing this one.
"""

from __future__ import annotations

import os

# Rigetti's documented native gate set: virtual RZ (arbitrary angle, free) +
# the physical pi/2 X-axis pulse ("sx" — NOT qiskit's "rx", which allows an
# arbitrary angle, and NOT qiskit's "x", which the QCS compiler also rejects
# as non-native even though it's a fixed pi rotation — see module docstring
# for the three-round history of getting this basis right) + CZ two-qubit
# gate. Used to pre-decompose the circuit client-side since qBraid's own
# transpile step doesn't do this for non-IonQ devices. If a future chip
# generation rejects this basis, check the device's live ISA
# (get_device(...).profile) for its actual native gates.
NATIVE_GATES = ["rz", "sx", "cz"]

# Cepheus-1-108Q's real qubit connectivity (square lattice, 12 rows x 9
# cols — 108 sites, one disabled per profile.num_qubits=107), fetched via
# scripts/Rigetti_get_topology.py, 2026-07-26. Needed so transpile() can
# route the ansatz's non-adjacent two-qubit gates with SWAPs instead of
# emitting a CZ between physically disconnected qubits (see module
# docstring's topology-error round). Built lazily since qiskit's
# CouplingMap import isn't needed unless run_circuit_shots is actually called.
def _coupling_map():
    from qiskit.transpiler import CouplingMap
    return CouplingMap.from_grid(12, 9)

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

    shots defaults to default_shots(device_id) — 200, since this is real
    billed QPU hardware with no free-simulator route to fall back to.
    """
    if shots is None:
        shots = default_shots(device_id)

    from qiskit import transpile as qiskit_transpile
    # initial_layout pinned to identity (virtual qubit i -> physical qubit i):
    # circuit already has measure_all() applied (bound before this call), so
    # Qiskit's routing keeps each measured classical bit tied to its original
    # virtual qubit regardless of any mid-circuit SWAPs — this pin isn't
    # required for correctness, just keeps the physical-qubit mapping
    # predictable/debuggable rather than transpile picking its own placement
    # across all 108 sites (including whichever one is disabled).
    native_circuit = qiskit_transpile(
        circuit, basis_gates=NATIVE_GATES, coupling_map=_coupling_map(),
        initial_layout=list(range(circuit.num_qubits)), optimization_level=3,
    )

    device = get_device(device_id)
    job = device.run(native_circuit, shots=shots)

    job.wait_for_final_state(timeout=timeout, poll_interval=5)
    status = job.status()
    if str(status) == "JobStatus.FAILED":
        raise RuntimeError(f"Rigetti job failed on the server: {status.status_message}")

    result = job.result()
    return dict(result.data.get_counts())
