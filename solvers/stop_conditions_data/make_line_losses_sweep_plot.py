import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

SCRATCH = os.path.dirname(os.path.abspath(__file__))
FIG_DIR = os.path.join(os.path.dirname(SCRATCH), "stop_conditions_figures")

with open(os.path.join(SCRATCH, "sweep_results_line_losses.json")) as f:
    data = json.load(f)

rows = data["noisy_line_losses"]
shots = [r["shots"] for r in rows]
median = [r["median_gap"] * 100 for r in rows]
p95 = [r["p95_gap"] * 100 for r in rows]
success = [r["success_rate"] * 100 for r in rows]

fig, (ax, ax2) = plt.subplots(2, 1, figsize=(8, 8), sharex=True)
ax.plot(shots, median, "o-", color="#dc2626", label="Median optimality gap")
ax.fill_between(shots, median, p95, color="#dc2626", alpha=0.15, label="to P95")
ax.set_ylabel("Optimality gap vs. best-found cost (%)")
ax.set_title(f"Optimality gap and success rate vs. shots — WITH line losses, forte-1 noise\n"
             f"(n={data['n_trials']} bootstrap trials/point, "
             f"reference = best of {data['n_placements_evaluated']} sampled placements)")
ax.legend(fontsize=9)
ax.grid(alpha=0.3)

ax2.plot(shots, success, "o-", color="#0d9488", label="Success rate (exact best-found match)")
ax2.set_xlabel("Shots")
ax2.set_ylabel("Success rate (%)")
ax2.legend(fontsize=9)
ax2.grid(alpha=0.3)

fig.tight_layout()
fig.savefig(os.path.join(FIG_DIR, "sweep_optimality_gap_vs_shots_line_losses.png"), dpi=150)
plt.close(fig)
print("Saved sweep_optimality_gap_vs_shots_line_losses.png")

print("\n| Shots | Feasibility rate | Success rate | Median gap | P95 gap |")
print("|---:|---:|---:|---:|---:|")
for r in rows:
    print(f"| {r['shots']} | {r['feasibility_rate']:.1%} | {r['success_rate']:.1%} | "
          f"{r['median_gap']*100:.4f}% | {r['p95_gap']*100:.4f}% |")
