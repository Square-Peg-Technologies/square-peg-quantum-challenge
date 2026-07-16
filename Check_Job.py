"""
Check the status/result of a previously submitted IBM Quantum Runtime job.

Usage:
    python Check_Job.py <job_id>

Requires a .env file (same as test_ibm_quantum_access.py) with:
    IQP_API_TOKEN=your_44_char_api_key
    IQP_INSTANCE=your_instance_crn   # optional, but recommended
"""

import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("NOTE: python-dotenv not installed — .env file will be ignored.")
    print("Run: pip install python-dotenv --break-system-packages\n")

from qiskit_ibm_runtime import QiskitRuntimeService

def main():
    if len(sys.argv) < 2:
        print("Usage: python Check_Job.py <job_id>")
        sys.exit(1)

    job_id = sys.argv[1]

    token = os.environ.get("IQP_API_TOKEN")
    instance = os.environ.get("IQP_INSTANCE")

    if not token:
        print("ERROR: IQP_API_TOKEN not set (check your .env file).")
        sys.exit(1)

    kwargs = {"token": token}
    if instance:
        kwargs["instance"] = instance

    service = QiskitRuntimeService(**kwargs)
    job = service.job(job_id)

    print(f"Job ID: {job_id}")
    print(f"Status: {job.status()}")

    # --- Usage / timing metrics ---
    try:
        metrics = job.metrics()
        print("\nMetrics:")
        usage_seconds = metrics.get("usage", {}).get("seconds")
        if usage_seconds is not None:
            print(f"  QPU usage (billed): {usage_seconds} seconds")
        # Print everything else returned, in case the API exposes more detail
        for key, value in metrics.items():
            if key != "usage":
                print(f"  {key}: {value}")
    except Exception as e:
        print(f"  (Could not retrieve metrics: {e})")

    if job.status() == "DONE":
        result = job.result()
        print("\nResult:")
        print(result)
    else:
        print("\nJob not finished yet — run this again later to check progress.")


if __name__ == "__main__":
    main()
