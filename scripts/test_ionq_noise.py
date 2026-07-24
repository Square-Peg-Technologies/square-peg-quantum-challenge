"""
Verifies solvers/ionq_qbraid_backend.run_circuit_shots() end-to-end for both
the ideal simulator and the forte-1 noise model, using the real qBraid API
(100 shots each, free simulator device — no credits spent).

Usage:
    python scripts/test_ionq_noise.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qiskit import QuantumCircuit
from solvers.ionq_qbraid_backend import run_circuit_shots

qc = QuantumCircuit(2)
qc.h(0)
qc.cx(0, 1)
qc.measure_all()

print("Running WITHOUT noise (100 shots)...")
counts_ideal = run_circuit_shots(qc, shots=100, noisy=False)
print("Ideal counts:", counts_ideal)

print("\nRunning WITH forte-1 noise model (100 shots)...")
counts_noisy = run_circuit_shots(qc, shots=100, noisy=True)
print("Noisy counts:", counts_noisy)
