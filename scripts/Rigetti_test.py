"""
Test script for Rigetti access through qBraid's runtime (QbraidProvider).

Same auth pattern as scripts/IonQ_test.py: the token is actually a qBraid
platform API key (starts with "qbr_"), not a standalone Rigetti/QCS account
key. It authenticates against qbraid.runtime.QbraidProvider, which routes to
Rigetti devices through qBraid's own job system and bills against qBraid
credits. Reuses the same IONQ_TOKEN env var as the IonQ scripts since it's
the same underlying qBraid key either way — see
https://docs.qbraid.com/v2/sdk/user-guide/providers/native.

Usage:
    pip install 'qbraid[qiskit]' python-dotenv --break-system-packages

    Create a file named .env in the same folder as this script (or in the
    repo root — python-dotenv walks up looking for one):
        IONQ_TOKEN=your_qbraid_api_key

    Then just run:
        python scripts/Rigetti_test.py

    (An environment variable set via `export IONQ_TOKEN=...` still works too
    and takes precedence over .env if both are set.)

Targets rigetti:rigetti:qpu:cepheus-1-108q by default — a real QPU, so this
will queue and bill qBraid credits. Change DEVICE_ID below to a Rigetti
simulator route instead if you just want to confirm the submit/result flow
without spending credits or queueing for hardware.

Step 4 builds a small butterfly ansatz (the same circuit shape run_vqa_qiskit
uses in production, just fewer qubits/layers for a quick/cheap check) and
submits it through solvers.rigetti_qbraid_backend.run_circuit_shots() itself
— not a hand-rolled circuit/transpile — so this is a real end-to-end check of
the exact code path the dashboard/CLI actually use, at only 10 shots.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEVICE_ID = "rigetti:rigetti:qpu:cepheus-1-108q"

try:
    from dotenv import load_dotenv
    load_dotenv()  # loads variables from a local .env file, if present
except ImportError:
    print("NOTE: python-dotenv not installed — .env file will be ignored.")
    print("Run: pip install python-dotenv --break-system-packages\n")


def main():
    token = os.environ.get("IONQ_TOKEN")

    if not token:
        print("ERROR: Set the IONQ_TOKEN environment variable with your qBraid API key.")
        sys.exit(1)

    # Sanity check the token got loaded cleanly — doesn't print the secret,
    # just enough to catch stray quotes/whitespace from a bad .env line, which
    # is the most common cause of an "Unauthorized" that looks like a real key.
    stripped = token.strip().strip("'\"")
    if stripped != token:
        print("⚠️ IONQ_TOKEN has leading/trailing whitespace or quotes in .env — "
              "using the stripped value, but fix the .env line to avoid surprises.")
        token = stripped
    print(f"Loaded IONQ_TOKEN: {token[:4]}...{token[-4:]} ({len(token)} chars)")

    try:
        from qbraid.runtime import QbraidProvider
    except ImportError:
        print("ERROR: qbraid is not installed.")
        print("Run: pip install 'qbraid[qiskit]' --break-system-packages")
        sys.exit(1)

    # --- Step 1: Authenticate ---
    print("Connecting to qBraid runtime...")
    try:
        provider = QbraidProvider(api_key=token)
        print("✅ Provider created.")
    except Exception as e:
        print(f"❌ Authentication failed: {e}")
        sys.exit(1)

    # --- Step 2: List devices, filter to Rigetti ---
    try:
        devices = provider.get_devices()
        rigetti_devices = [d for d in devices if "rigetti" in str(d.id).lower()]
        print(f"✅ Found {len(devices)} accessible device(s), {len(rigetti_devices)} Rigetti:")
        for d in rigetti_devices:
            try:
                print(f"   - {d.id} | status={d.status()}")
            except Exception as e:
                print(f"   - {d.id} | status check failed: {e}")
    except Exception as e:
        print(f"❌ Could not list devices: {e}")
        sys.exit(1)

    if not rigetti_devices:
        print("❌ No Rigetti devices found in your qBraid account — check that the")
        print("   account linking / credit loading actually completed.")
        sys.exit(1)

    # --- Step 3: Grab the requested device (fall back to the first Rigetti
    #             device found if DEVICE_ID isn't in the account's list) ---
    matches = [d for d in rigetti_devices if str(d.id) == DEVICE_ID]
    if matches:
        device = matches[0]
    else:
        print(f"⚠️ {DEVICE_ID!r} not in the account's device list — "
              f"falling back to {rigetti_devices[0].id!r}.")
        device = rigetti_devices[0]

    # --- Step 4: Run a small butterfly-ansatz circuit through the real
    #             backend module (same code path production uses) ---
    try:
        from solvers.quantum_siting import build_butterfly_ansatz
        from solvers.rigetti_qbraid_backend import run_circuit_shots

        n_qubits, n_layers = 4, 2
        qc, params = build_butterfly_ansatz(n_qubits, n_layers)
        bound = qc.assign_parameters({p: 0.37 for p in params})

        print(f"\nSubmitting a {n_qubits}-qubit/{n_layers}-layer butterfly ansatz "
              f"({len(params)} params, fixed at 0.37) to: {device.id}")

        counts = run_circuit_shots(bound, shots=10, device_id=device.id)
        print(f"✅ Result counts: {counts}")
    except Exception as e:
        print(f"❌ Could not submit/run the test circuit: {e}")
        sys.exit(1)

    print("\nDone. If you saw checkmarks above, your Rigetti access via qBraid is working.")


if __name__ == "__main__":
    main()
