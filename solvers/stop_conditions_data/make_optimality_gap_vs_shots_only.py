import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Single-panel variant of make_line_losses_sweep_plot.py: median gap (with
# P95 band) vs. shots only, success-rate panel dropped per request.

SCRATCH = os.path.dirname(os.path.abspath(__file__))
FIG_DIR = os.path.join(os.path.dirname(SCRATCH), "stop_conditions_figures")

with open(os.path.join(SCRATCH, "sweep_results_line_losses.json")) as f:
    data = json.load(f)

rows = data["noisy_line_losses"]
shots = [r["shots"] for r in rows]
median = [r["median_gap"] * 100 for r in rows]
p95 = [r["p95_gap"] * 100 for r in rows]

fig, ax = plt.subplots(figsize=(8, 4.5))
ax.plot(shots, median, "o-", color="#dc2626", label="Median optimality gap")
ax.fill_between(shots, median, p95, color="#dc2626", alpha=0.15, label="to P95")
ax.set_xlabel("Shots")
ax.set_ylabel("Optimality gap vs. best-found cost (%)")
ax.set_title(f"Optimality gap vs. shots — WITH line losses, forte-1 noise\n"
             f"(n={data['n_trials']} bootstrap trials/point, "
             f"reference = best of {data['n_placements_evaluated']} sampled placements)")
ax.legend(fontsize=9)
ax.grid(alpha=0.3)

fig.tight_layout()
out_path = os.path.join(FIG_DIR, "optimality_gap_vs_shots_line_losses.png")
fig.savefig(out_path, dpi=150)
plt.close(fig)
print(f"Saved {out_path}")
