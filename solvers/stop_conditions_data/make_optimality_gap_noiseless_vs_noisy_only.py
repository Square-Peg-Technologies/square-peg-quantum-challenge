import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Single-panel variant of make_noiseless_vs_noisy_plot.py: median optimality
# gap vs. shots only, success-rate panel dropped per request.

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
FIG_DIR = os.path.join(os.path.dirname(DATA_DIR), "stop_conditions_figures")

with open(os.path.join(DATA_DIR, "sweep_results_noiseless_vs_noisy.json")) as f:
    data = json.load(f)

rows_nl = data["noiseless_line_losses"]
rows_nz = data["noisy_line_losses"]
shots = [r["shots"] for r in rows_nl]

fig, ax1 = plt.subplots(figsize=(8, 4.5))

ax1.plot(shots, [r["median_gap"] * 100 for r in rows_nl], "o-", color="#0d9488", label="Noiseless")
ax1.plot(shots, [r["median_gap"] * 100 for r in rows_nz], "o-", color="#dc2626", label="Noisy (forte-1)")
ax1.set_xlabel("Shots")
ax1.set_ylabel("Median optimality gap (%)")
ax1.set_title(f"Noiseless vs. noisy — median optimality gap vs. shots, WITH line losses\n"
              f"(n={data['n_trials']} bootstrap trials/point, "
              f"reference = best of {data['n_placements_evaluated']} sampled placements)")
ax1.legend(fontsize=9)
ax1.grid(alpha=0.3)

fig.tight_layout()
out_path = os.path.join(FIG_DIR, "optimality_gap_noiseless_vs_noisy_line_losses.png")
fig.savefig(out_path, dpi=150)
plt.close(fig)
print(f"Saved {out_path}")
