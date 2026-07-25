import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Combines the two single-panel optimality-gap plots side by side (1x2) to
# save space in the paper: left = median gap + P95 band, noisy/line-losses
# only; right = noiseless vs. noisy median gap comparison, with line losses.

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
FIG_DIR = os.path.join(os.path.dirname(DATA_DIR), "stop_conditions_figures")

with open(os.path.join(DATA_DIR, "sweep_results_line_losses.json")) as f:
    data_gap = json.load(f)
with open(os.path.join(DATA_DIR, "sweep_results_noiseless_vs_noisy.json")) as f:
    data_cmp = json.load(f)

rows = data_gap["noisy_line_losses"]
shots_gap = [r["shots"] for r in rows]
median_gap = [r["median_gap"] * 100 for r in rows]
p95_gap = [r["p95_gap"] * 100 for r in rows]

rows_nl = data_cmp["noiseless_line_losses"]
rows_nz = data_cmp["noisy_line_losses"]
shots_cmp = [r["shots"] for r in rows_nl]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))

ax1.plot(shots_gap, median_gap, "o-", color="#dc2626", label="Median optimality gap")
ax1.fill_between(shots_gap, median_gap, p95_gap, color="#dc2626", alpha=0.15, label="to P95")
ax1.set_xlabel("Shots")
ax1.set_ylabel("Optimality gap vs. best-found cost (%)")
ax1.set_title(f"Gap vs. shots — line losses, forte-1 noise\n"
              f"(n={data_gap['n_trials']} trials/point)", fontsize=10)
ax1.legend(fontsize=8)
ax1.grid(alpha=0.3)

ax2.plot(shots_cmp, [r["median_gap"] * 100 for r in rows_nl], "o-", color="#0d9488", label="Noiseless")
ax2.plot(shots_cmp, [r["median_gap"] * 100 for r in rows_nz], "o-", color="#dc2626", label="Noisy (forte-1)")
ax2.set_xlabel("Shots")
ax2.set_ylabel("Median optimality gap (%)")
ax2.set_title(f"Noiseless vs. noisy — line losses\n"
              f"(n={data_cmp['n_trials']} trials/point)", fontsize=10)
ax2.legend(fontsize=8)
ax2.grid(alpha=0.3)

fig.tight_layout()
out_path = os.path.join(FIG_DIR, "optimality_gap_combined_line_losses.png")
fig.savefig(out_path, dpi=150)
plt.close(fig)
print(f"Saved {out_path}")
