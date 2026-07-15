"""
Test script for IonQ access through qBraid's runtime (QbraidProvider).

Despite the env var being named IONQ_TOKEN, what we actually have is a qBraid
platform API key (starts with "qbr_"), not a standalone IonQ Cloud account
key. A qBraid key authenticates against qbraid.runtime.QbraidProvider, which
routes to IonQ devices through qBraid's own job system and bills against
qBraid credits — NOT qbraid.runtime.IonQProvider, which talks directly to
IonQ's own Cloud API and requires a separate IonQ Cloud account key we don't
have. See https://docs.qbraid.com/v2/sdk/user-guide/providers/native.

Usage:
    pip install qbraid python-dotenv --break-system-packages

    Create a file named .env in the same folder as this script (or in the
    repo root — python-dotenv walks up looking for one):
        IONQ_TOKEN=your_qbraid_api_key

    Then just run:
        python scripts/IonQ_test.py

    (An environment variable set via `export IONQ_TOKEN=...` still works too
    and takes precedence over .env if both are set.)
"""

import os
import sys

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
        print("Run: pip install qbraid --break-system-packages")
        sys.exit(1)

    # --- Step 1: Authenticate ---
    print("Connecting to qBraid runtime...")
    try:
        provider = QbraidProvider(api_key=token)
        print("✅ Provider created.")
    except Exception as e:
        print(f"❌ Authentication failed: {e}")
        sys.exit(1)

    # --- Step 2: List devices, filter to IonQ ---
    try:
        devices = provider.get_devices()
        ionq_devices = [d for d in devices if "ionq" in str(d.id).lower()]
        print(f"✅ Found {len(devices)} accessible device(s), {len(ionq_devices)} IonQ:")
        for d in ionq_devices:
            try:
                print(f"   - {d.id} | status={d.status()}")
            except Exception as e:
                print(f"   - {d.id} | status check failed: {e}")
    except Exception as e:
        print(f"❌ Could not list devices: {e}")
        sys.exit(1)

    if not ionq_devices:
        print("❌ No IonQ devices found in your qBraid account — check that the")
        print("   account linking / credit loading from the typeform actually completed.")
        sys.exit(1)

    # --- Step 3: Run a tiny Bell-state test circuit on the IonQ simulator ---
    # NOTE: Forte 1 QPU access is currently blocked at the qBraid account
    # level (dashboard shows it as an "External Device" not bookable through
    # qBraid, separate from the per-route billing issues we also hit: aws:
    # route needs AWS credits we don't have, openquantum: route needs an
    # unlinked Open Quantum account, azure: route is offline). Until that's
    # resolved with qBraid support, this targets the qBraid-native IonQ
    # simulator (ionq:ionq:sim:simulator) instead, to confirm credit spend
    # and the submit/result flow actually work end-to-end.
    sim_devices = [d for d in ionq_devices if str(d.id).lower() == "ionq:ionq:sim:simulator"]
    if not sim_devices:
        sim_devices = [d for d in ionq_devices if "sim" in str(d.id).lower()]
    if not sim_devices:
        print("❌ No IonQ simulator device found — see the IonQ device list above.")
        sys.exit(1)

    device = sim_devices[0]

    try:
        print(f"\nSubmitting a 2-qubit Bell-state test circuit to: {device.id}")

        from qiskit import QuantumCircuit

        circuit = QuantumCircuit(2, 2)
        circuit.h(0)
        circuit.cx(0, 1)
        circuit.measure([0, 1], [0, 1])

        job = device.run(circuit, shots=100)
        print(f"✅ Job submitted. Job ID: {job.id}")

        # Real QPU jobs queue — poll status until it reaches a final state
        # (COMPLETED/FAILED/CANCELLED) instead of grabbing results too early.
        print(f"Waiting for job to complete (status={job.status()!r})...")
        job.wait_for_final_state(timeout=600, poll_interval=5)
        final_status = job.status()
        print(f"Final status: {final_status!r}")
        if str(final_status) == "JobStatus.FAILED":
            print(f"❌ Job failed on the server: {final_status.status_message}")
            sys.exit(1)

        result = job.result()
        counts = result.data.get_counts()
        print(f"✅ Result counts: {counts}")
    except Exception as e:
        print(f"❌ Could not submit/run the test circuit: {e}")
        sys.exit(1)

    print("\nDone. If you saw checkmarks above, your IonQ access via qBraid is working.")


if __name__ == "__main__":
    main()
