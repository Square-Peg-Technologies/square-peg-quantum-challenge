"""
Read-only diagnostic: dump everything qBraid's QbraidProvider knows about a
Rigetti device, looking for qubit connectivity/coupling-map data.

Does NOT submit any circuit or run any shots — no billing, no queueing.
Context: solvers/rigetti_qbraid_backend.py's real Rigetti runs keep failing
with "this instruction must be replaced or decomposed prior to compilation"
for two-qubit gates between non-adjacent qubits (e.g. "CZ 0 2") once the
gate-basis issue was fixed (see Constitution/Todo.md, "Rigetti (qBraid)
backend gate-decomposition fix", round 3). That needs the chip's real
coupling map to route around correctly. TargetProfile (what
qbraid.runtime.QuantumDevice.profile exposes) does not appear to carry a
coupling map field — this script checks whether the *raw* device response
(before qBraid narrows it down to a TargetProfile) has it anywhere.

Usage:
    python scripts/Rigetti_get_topology.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEVICE_ID = "rigetti:rigetti:qpu:cepheus-1-108q"

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("NOTE: python-dotenv not installed — .env file will be ignored.")


def _print_section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def main():
    token = os.environ.get("IONQ_TOKEN")
    if not token:
        print("ERROR: Set the IONQ_TOKEN environment variable with your qBraid API key.")
        sys.exit(1)
    token = token.strip().strip("'\"")

    from qbraid.runtime import QbraidProvider
    provider = QbraidProvider(api_key=token)
    device = provider.get_device(DEVICE_ID)

    _print_section("device.profile (TargetProfile — what run_circuit_shots sees today)")
    try:
        print(json.dumps(device.profile.model_dump(exclude=["program_spec"]),
                         indent=2, default=str))
    except Exception as e:
        print(f"(could not serialize profile: {e})")
        print(device.profile)

    _print_section("device.metadata()")
    try:
        print(json.dumps(device.metadata(), indent=2, default=str))
    except Exception as e:
        print(f"(could not serialize metadata: {e})")

    _print_section("Raw RuntimeDevice from provider.client.get_device(...)")
    try:
        raw = provider.client.get_device(DEVICE_ID)
        # Pydantic model in recent qbraid-core versions — dump every field,
        # not just the ones TargetProfile happens to keep.
        if hasattr(raw, "model_dump"):
            print(json.dumps(raw.model_dump(), indent=2, default=str))
        else:
            print(json.dumps(vars(raw), indent=2, default=str))
    except Exception as e:
        print(f"(could not fetch/serialize raw device: {e})")

    _print_section("Attributes on the device object itself")
    for attr in ("num_qubits", "coupling_map", "connectivity", "topology",
                "live_qubits", "gate_map", "isa"):
        if hasattr(device, attr):
            val = getattr(device, attr)
            try:
                val = val() if callable(val) else val
            except Exception as e:
                val = f"(call failed: {e})"
            print(f"  device.{attr} = {val}")

    print("\nDone. Look through the sections above for anything resembling a "
          "qubit adjacency list, coupling map, or ISA/architecture graph.")


if __name__ == "__main__":
    main()
