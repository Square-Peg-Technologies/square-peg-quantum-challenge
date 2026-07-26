"""
Recover a Rigetti quantum-siting result when the local client already threw
a TimeoutError (job.wait_for_final_state's 600s cap) but the job actually
COMPLETED server-side afterward.

This happens because run_circuit_shots() blocks on wait_for_final_state with
only a 10-minute timeout -- a long real QCS queue can outlast that even
though the job itself succeeds a few minutes later. The result is still
retrievable from qBraid (check the job's status/result on qbraid.com or via
the SDK using the job ID printed in the original run's traceback), but the
local run never got to feed it through the classical post-processing step
(unique-bitstring ranking by proxy cost + top-N + classical UC/ED
evaluation) -- run_quantum_siting crashed before reaching that code.

This script re-runs ONLY that local, free, classical post-processing, using
the real measurement counts already returned by hardware. It does NOT
submit a new job or spend any additional qBraid credits --
run_circuit_shots is monkeypatched to return the already-obtained counts
instead of calling device.run() again.

Usage:
    python scripts/reprocess_rigetti_result.py <assets_file> <result_json_path>

<assets_file>      e.g. "4batt.py" (No DC) or "4batt_dcbus4_heatwave.py"
                   -- must exist in use_cases/ieee14/
<result_json_path> path to a JSON file containing the qBraid job result
                   (the same shape as `qbraid jobs result <job_id>` or the
                   dashboard's job.result() JSON dump), i.e. must contain
                   result["resultData"]["measurementCounts"] as a
                   {bitstring: count} dict.

Assumes the run used the same parameters as every other scenario in this
submission: T=24, sim_method="statevector", n_candidates=20,
second_stage="uc", warm_start="sdp", ansatz="auto", line_losses=False.
Edit the run_quantum_siting call below if a given re-run used different
settings.
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    assets_file, result_json_path = sys.argv[1], sys.argv[2]

    with open(result_json_path) as f:
        job_result = json.load(f)
    real_counts = job_result["resultData"]["measurementCounts"]
    real_counts = {bs: int(c) for bs, c in real_counts.items()}
    print(f"Loaded {sum(real_counts.values())} shots across "
          f"{len(real_counts)} unique bitstrings from {result_json_path}")

    import solvers.rigetti_qbraid_backend as rig

    def fake_run_circuit_shots(circuit, shots=None, device_id=None,
                                timeout=600, initial_layout=None):
        return real_counts

    rig.run_circuit_shots = fake_run_circuit_shots

    import dashboard as cli_dash
    from solvers.quantum_siting import run_quantum_siting

    grid, assets_mod, loc_mod, dc_bus, dc_mw = cli_dash._load_case(
        "ieee14", assets_file)
    outages = getattr(assets_mod, "OUTAGES", None)

    result = run_quantum_siting(
        grid=grid, generators=assets_mod.GENERATORS, batteries=assets_mod.BATTERIES,
        T=24, sim_method="statevector", final_backend="rigetti_qbraid",
        n_candidates=20, second_stage="uc", warm_start="sdp",
        track_convergence=True, max_time_s=60.0, ansatz="auto",
        line_losses=False, outages=outages,
    )

    best_locs, best_commit, best_cost, best_res = result.best
    print(f"\n=== {assets_file} -- Rigetti real-hardware result (recovered) ===")
    print("Best placement (buses):", sorted(best_locs.values()))
    print("True cost: $%.2f" % best_cost)
    print("Runtime phases:", result.runtime_phases)


if __name__ == "__main__":
    main()
