"""Render the PJM 5-bus network topology to assets/pjm5_topology.png.

Reuses plots.py's grid-graph builder/layout so the diagram matches the node
styling (gen vs. load coloring, layout) used by the dashboard's power-flow
plots. The two constrained branches are drawn thicker/red with their MW
limit labeled, using self.fbar (the limits actually enforced by the DC-OPF
solver) rather than the branch table's rateA column.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np

from plots import _build_grid_graph, gen_node_color, load_node_color
from use_cases.pjm5.pjm5 import Case

GEN_BUSES = {1, 3, 5}


def main():
    grid = Case()
    Gg, pos_g, branches_list = _build_grid_graph(grid)
    fbar = np.array(grid.fbar).flatten().tolist()

    # (fbus, tbus) -> MW limit, for branches with a real (non-9999) limit.
    bottlenecks = {(f, t): fbar[i] for i, (f, t, _) in enumerate(branches_list) if fbar[i] < 9000}

    fig, ax = plt.subplots(figsize=(8, 6))

    normal_edges = [(f, t) for f, t, _ in branches_list if (f, t) not in bottlenecks]
    bottleneck_edges = list(bottlenecks.keys())

    nx.draw_networkx_edges(Gg, pos_g, ax=ax, edgelist=normal_edges,
                            edge_color="#888888", width=1.6, arrows=False)
    nx.draw_networkx_edges(Gg, pos_g, ax=ax, edgelist=bottleneck_edges,
                            edge_color="#d62728", width=3.0, arrows=False)

    for (f, t), mw in bottlenecks.items():
        x0, y0 = pos_g[f]
        x1, y1 = pos_g[t]
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        ax.text(mx, my, f"{mw:.0f} MW", fontsize=9, fontweight="bold", ha="center", va="center",
                color="#d62728", zorder=5,
                bbox=dict(boxstyle="round,pad=0.15", facecolor="white", edgecolor="none", alpha=0.85))

    node_colors = [gen_node_color if n in GEN_BUSES else load_node_color for n in Gg.nodes]
    node_sizes = [900 if n in GEN_BUSES else 550 for n in Gg.nodes]
    nx.draw_networkx_nodes(Gg, pos_g, ax=ax, node_color=node_colors, node_size=node_sizes)
    nx.draw_networkx_labels(Gg, pos_g, ax=ax, labels={n: str(n) for n in Gg.nodes},
                             font_color="white", font_weight="bold", font_size=9)

    gen_patch = plt.Line2D([0], [0], marker="o", color="none", markerfacecolor=gen_node_color,
                            markersize=12, label="Generator bus")
    load_patch = plt.Line2D([0], [0], marker="o", color="none", markerfacecolor=load_node_color,
                             markersize=10, label="Load bus")
    bottleneck_patch = plt.Line2D([0], [0], color="#d62728", linewidth=3, label="Bottleneck branch (MW limit)")
    ax.legend(handles=[gen_patch, load_patch, bottleneck_patch], loc="lower left", fontsize=8, frameon=True)

    ax.set_title("PJM 5-Bus Test System — Network Topology", fontsize=13, fontweight="bold", pad=12)
    ax.axis("off")

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pjm5_topology.png")
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved {out_path}")


if __name__ == "__main__":
    main()
