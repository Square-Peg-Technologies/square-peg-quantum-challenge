import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Renders the "Circuit resource cost (depth, gate count)" table from
# stop_conditions.md (butterfly ansatz, 19 qubits, 3 layers) as a PNG.

SCRATCH = os.path.dirname(os.path.abspath(__file__))
FIG_DIR = os.path.join(os.path.dirname(SCRATCH), "stop_conditions_figures")

columns = ["Metric", "Abstract\n(Qiskit-native gates)", "Transpiled\n(rz/ry/rx/rxx)"]
rows = [
    ["Circuit depth", "70", "189"],
    ["Total gates", "249", "774"],
    ["Two-qubit gates", "192 (rzx)", "192 (rxx)"],
]

fig, ax = plt.subplots(figsize=(6.6, 3.4))
ax.axis("off")

table = ax.table(cellText=rows, colLabels=columns, cellLoc="center", loc="center")
table.auto_set_font_size(False)
table.set_fontsize(12)
table.scale(1, 3.4)

for (row, col), cell in table.get_celld().items():
    cell.set_edgecolor("#cccccc")
    if row == 0:
        cell.set_facecolor("#0d9488")
        cell.set_text_props(color="white", weight="bold")
    else:
        cell.set_facecolor("#f5f5f5" if row % 2 == 0 else "white")
    if col == 0:
        cell.set_text_props(ha="left")
        cell.PAD = 0.03

fig.tight_layout()
out_path = os.path.join(FIG_DIR, "circuit_resource_cost_table.png")
fig.savefig(out_path, dpi=200, bbox_inches="tight")
plt.close(fig)
print(f"Saved {out_path}")
