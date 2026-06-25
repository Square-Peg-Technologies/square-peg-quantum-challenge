"""
Test script for IBM Quantum API access.

Usage:
    pip install qiskit qiskit-ibm-runtime --break-system-packages
    export IQP_API_TOKEN=your_44_char_api_key
    export IQP_INSTANCE=your_instance_crn   # optional, but recommended
    python test_ibm_quantum_access.py
"""

import os
import sys
from dotenv import load_dotenv
load_dotenv()  # loads .env into os.environment

def main():
    token = os.environ.get("IQP_API_TOKEN")
    instance = os.environ.get("IQP_INSTANCE")  # optional

    if not token:
        print("ERROR: Set the IQP_API_TOKEN environment variable with your API key.")
        sys.exit(1)

    try:
        from qiskit_ibm_runtime import QiskitRuntimeService
    except ImportError:
        print("ERROR: qiskit-ibm-runtime is not installed.")
        print("Run: pip install qiskit qiskit-ibm-runtime --break-system-packages")
        sys.exit(1)

    # --- Step 1: Authenticate ---
    print("Connecting to IBM Quantum Platform...")
    try:
        kwargs = {"token": token}
        if instance:
            kwargs["instance"] = instance
        service = QiskitRuntimeService(**kwargs)
        print("✅ Authentication successful.")
    except Exception as e:
        print(f"❌ Authentication failed: {e}")
        sys.exit(1)

    # --- Step 2: List available backends ---
    try:
        backends = service.backends()
        print(f"✅ Found {len(backends)} accessible backend(s):")
        for b in backends:
            status = b.status()
            print(f"   - {b.name} | operational={status.operational} | pending_jobs={status.pending_jobs}")
    except Exception as e:
        print(f"❌ Could not list backends: {e}")
        sys.exit(1)

    # --- Step 3: Run a tiny test circuit on the least busy backend ---
    try:
        from qiskit import QuantumCircuit
        from qiskit_ibm_runtime import SamplerV2 as Sampler

        backend = service.least_busy(operational=True, simulator=False)
        print(f"\nSubmitting a 1-qubit test circuit to: {backend.name}")

        qc = QuantumCircuit(1, 1)
        qc.h(0)
        qc.measure(0, 0)

        sampler = Sampler(mode=backend)
        job = sampler.run([qc])
        print(f"✅ Job submitted. Job ID: {job.job_id()}")
        print("   (Job is queued/running — check status with job.status() or the IBM Quantum dashboard.)")
    except Exception as e:
        print(f"⚠️ Could not submit a test job (auth/listing still worked): {e}")

    print("\nDone. If you saw checkmarks above, your API access is working.")


if __name__ == "__main__":
    main()
