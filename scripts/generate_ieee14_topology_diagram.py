"""Render the IEEE 14-bus network topology to assets/ieee14_topology.png.

Reuses plots.py's grid-graph builder/layout so the diagram matches the node
styling (gen vs. load coloring, layout) used by the dashboard's power-flow
plots. Bottleneck branches (from the README's "Key transmission bottlenecks"
table) are drawn thicker/red with their MW limit labeled.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib.pyplot as plt
import networkx as nx

from plots import _build_grid_graph, gen_node_color, load_node_color, _grid_load_buses
from use_cases.ieee14.ieee14 import Case

GEN_BUSES = {1, 2, 3, 6, 8}

# (fbus, tbus) -> MW limit, for the tightened bottleneck branches called out in the README.
BOTTLENECKS = {
    (4, 9): 40,
    (5, 6): 80,
    (6, 12): 60,
    (13, 14): 60,
    (7, 8): 80,
    (7, 9): 100,
}


def main():
    grid = Case()
    Gg, pos_g, branches_list = _build_grid_graph(grid)
    load_buses = _grid_load_buses(grid)

    fig, ax = plt.subplots(figsize=(9, 7))

    normal_edges = [(f, t) for f, t, _ in branches_list if (f, t) not in BOTTLENECKS and (t, f) not in BOTTLENECKS]
    bottleneck_edges = [(f, t) for f, t, _ in branches_list if (f, t) in BOTTLENECKS or (t, f) in BOTTLENECKS]

    nx.draw_networkx_edges(Gg, pos_g, ax=ax, edgelist=normal_edges,
                            edge_color="#888888", width=1.6, arrows=False)
    nx.draw_networkx_edges(Gg, pos_g, ax=ax, edgelist=bottleneck_edges,
                            edge_color="#d62728", width=3.0, arrows=False)

    for f, t in bottleneck_edges:
        mw = BOTTLENECKS.get((f, t), BOTTLENECKS.get((t, f)))
        x0, y0 = pos_g[f]
        x1, y1 = pos_g[t]
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        ax.text(mx, my, f"{mw} MW", fontsize=8, fontweight="bold", ha="center", va="center",
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

    ax.set_title("IEEE 14-Bus Test System — Network Topology", fontsize=13, fontweight="bold", pad=12)
    ax.axis("off")

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "ieee14_topology.png")
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved {out_path}")


if __name__ == "__main__":
    main()
