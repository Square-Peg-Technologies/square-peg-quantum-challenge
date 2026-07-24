import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
FIG_DIR = os.path.join(os.path.dirname(DATA_DIR), "stop_conditions_figures")

with open(os.path.join(DATA_DIR, "sweep_results_noiseless_vs_noisy.json")) as f:
    data = json.load(f)

rows_nl = data["noiseless_line_losses"]
rows_nz = data["noisy_line_losses"]
shots = [r["shots"] for r in rows_nl]

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 8), sharex=True)

ax1.plot(shots, [r["median_gap"] * 100 for r in rows_nl], "o-", color="#0d9488", label="Noiseless")
ax1.plot(shots, [r["median_gap"] * 100 for r in rows_nz], "o-", color="#dc2626", label="Noisy (forte-1)")
ax1.set_ylabel("Median optimality gap (%)")
ax1.set_title(f"Noiseless vs. noisy — WITH line losses\n"
              f"(n={data['n_trials']} bootstrap trials/point, "
              f"reference = best of {data['n_placements_evaluated']} sampled placements)")
ax1.legend(fontsize=9)
ax1.grid(alpha=0.3)

ax2.plot(shots, [r["success_rate"] * 100 for r in rows_nl], "o-", color="#0d9488", label="Noiseless")
ax2.plot(shots, [r["success_rate"] * 100 for r in rows_nz], "o-", color="#dc2626", label="Noisy (forte-1)")
ax2.set_xlabel("Shots")
ax2.set_ylabel("Success rate (%)")
ax2.legend(fontsize=9)
ax2.grid(alpha=0.3)

fig.tight_layout()
fig.savefig(os.path.join(FIG_DIR, "sweep_noiseless_vs_noisy_line_losses.png"), dpi=150)
plt.close(fig)
print("Saved sweep_noiseless_vs_noisy_line_losses.png")
