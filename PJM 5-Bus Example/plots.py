import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# Network topology from pjm5.py (MATPOWER case5)
# (fbus, tbus, flow_limit_MW)  — 0 means unconstrained
branches = [
    (1, 2, 400),
    (1, 4,   0),
    (1, 5,   0),
    (2, 3,   0),
    (3, 4,   0),
    (4, 5, 240),
]

# Generators: (unit_label, bus, p_min_MW, p_max_MW, cost_$/MWh)
generators = [
    ("Unit 0", 1, 100, 600, 10),
    ("Unit 1", 3, 100, 400,  8),
    ("Unit 2", 5,  50, 200,  6),
]

gen_buses = {g[1] for g in generators}
all_buses = list(range(1, 6))

G = nx.Graph()
G.add_nodes_from(all_buses)
for fbus, tbus, _ in branches:
    G.add_edge(fbus, tbus)

pos = nx.kamada_kawai_layout(G)

gen_node_color  = "#e05c3a"
load_node_color = "#5b8dd9"


def draw_network(G, pos, ax):
    node_colors = [gen_node_color if n in gen_buses else load_node_color for n in G.nodes]
    node_sizes  = [900 if n in gen_buses else 600 for n in G.nodes]
    nx.draw_networkx_nodes(G, pos, ax=ax,
                           node_color=node_colors,
                           node_size=node_sizes)
    nx.draw_networkx_labels(G, pos, ax=ax,
                            font_color="white", font_weight="bold", font_size=11)
    nx.draw_networkx_edges(G, pos, ax=ax,
                           edge_color="#444444", width=2, arrows=False)


def _congested_edge_colors(result):
    all_congested = set()
    for hour_lines in result.congested_lines:
        for idx in hour_lines:
            all_congested.add(idx)
    edge_colors = []
    for i, (fbus, tbus, _) in enumerate(branches):
        edge_colors.append("red" if i in all_congested else "black")
    return edge_colors


def draw_ed_result(result, gen_locations: dict, bat_locations: dict, ax):
    edge_colors = _congested_edge_colors(result)

    edge_list = [(f, t) for f, t, _ in branches]
    nx.draw_networkx_edges(G, pos, ax=ax,
                           edgelist=edge_list,
                           edge_color=edge_colors, width=2, arrows=False)

    node_sizes = []
    node_colors = []
    gen_bus_set = set(gen_locations.values())
    bat_bus_set = set(bat_locations.values())

    for n in G.nodes:
        if n in gen_bus_set:
            gen_idx = [g for g, b in gen_locations.items() if b == n][0]
            output = result.dispatch[gen_idx, -1]
            node_sizes.append(400 + output * 0.5)
            node_colors.append(gen_node_color)
        elif n in bat_bus_set:
            node_sizes.append(800)
            node_colors.append("#2ca02c")
        else:
            node_sizes.append(600)
            node_colors.append(load_node_color)

    gen_node_list = list(G.nodes)
    nx.draw_networkx_nodes(G, pos, ax=ax,
                           nodelist=gen_node_list,
                           node_color=node_colors,
                           node_size=node_sizes)

    for bat_idx, bus in bat_locations.items():
        soc = result.soc[bat_idx, -1]
        ax.scatter(*pos[bus], marker="*", s=800, color="#2ca02c", zorder=5)
        ax.annotate(f"B{bat_idx}\n{soc:.0f}MWh", xy=pos[bus],
                    fontsize=8, ha="center", va="bottom",
                    xytext=(0, 12), textcoords="offset points")

    gen_labels = {}
    for gen_idx, bus in gen_locations.items():
        output = result.dispatch[gen_idx, -1]
        gen_labels[bus] = f"Bus {bus}\n{output:.0f} MW"

    other_labels = {n: str(n) for n in G.nodes if n not in gen_locations.values()}
    nx.draw_networkx_labels(G, pos, ax=ax, labels={**other_labels, **gen_labels},
                            font_color="white", font_weight="bold", font_size=9)

    gen_patch = mpatches.Patch(color=gen_node_color, label="Generator bus")
    load_patch = mpatches.Patch(color=load_node_color, label="Load / reference bus")
    bat_patch = mpatches.Patch(color="#2ca02c", label="Battery bus")
    congested_patch = mpatches.Patch(color="red", label="Congested line")
    ax.legend(handles=[gen_patch, load_patch, bat_patch, congested_patch],
              loc="lower left", fontsize=9, framealpha=0.9)
    ax.axis("off")


def draw_uc_result(result, gen_locations: dict, bat_locations: dict, ax):
    edge_colors = _congested_edge_colors(result)

    edge_list = [(f, t) for f, t, _ in branches]
    nx.draw_networkx_edges(G, pos, ax=ax,
                           edgelist=edge_list,
                           edge_color=edge_colors, width=2, arrows=False)

    node_sizes = []
    node_colors = []
    gen_bus_set = set(gen_locations.values())
    bat_bus_set = set(bat_locations.values())

    for n in G.nodes:
        if n in gen_bus_set:
            gen_idx = [g for g, b in gen_locations.items() if b == n][0]
            committed = result.commitment[gen_idx, -1]
            if committed == 1:
                output = result.dispatch[gen_idx, -1]
                node_sizes.append(400 + output * 0.5)
                node_colors.append(gen_node_color)
            else:
                node_sizes.append(300)
                node_colors.append("#aaaaaa")
        elif n in bat_bus_set:
            node_sizes.append(800)
            node_colors.append("#2ca02c")
        else:
            node_sizes.append(600)
            node_colors.append(load_node_color)

    gen_node_list = list(G.nodes)
    nx.draw_networkx_nodes(G, pos, ax=ax,
                           nodelist=gen_node_list,
                           node_color=node_colors,
                           node_size=node_sizes)

    for bat_idx, bus in bat_locations.items():
        soc = result.soc[bat_idx, -1]
        ax.scatter(*pos[bus], marker="*", s=800, color="#2ca02c", zorder=5)
        ax.annotate(f"B{bat_idx}\n{soc:.0f}MWh", xy=pos[bus],
                    fontsize=8, ha="center", va="bottom",
                    xytext=(0, 12), textcoords="offset points")

    gen_labels = {}
    for gen_idx, bus in gen_locations.items():
        committed = result.commitment[gen_idx, -1]
        if committed == 1:
            output = result.dispatch[gen_idx, -1]
            gen_labels[bus] = f"Bus {bus}\n{output:.0f} MW"
        else:
            gen_labels[bus] = f"Bus {bus}\n(off)"

    other_labels = {n: str(n) for n in G.nodes if n not in gen_locations.values()}
    nx.draw_networkx_labels(G, pos, ax=ax, labels={**other_labels, **gen_labels},
                            font_color="white", font_weight="bold", font_size=9)

    gen_patch = mpatches.Patch(color=gen_node_color, label="Generator bus (active)")
    off_patch = mpatches.Patch(color="#aaaaaa", label="Generator bus (inactive)")
    load_patch = mpatches.Patch(color=load_node_color, label="Load / reference bus")
    bat_patch = mpatches.Patch(color="#2ca02c", label="Battery bus")
    congested_patch = mpatches.Patch(color="red", label="Congested line")
    ax.legend(handles=[gen_patch, off_patch, load_patch, bat_patch, congested_patch],
              loc="lower left", fontsize=9, framealpha=0.9)
    ax.axis("off")


def draw_siting_result(siting_result, gen_locations: dict, ax):
    bus_pair, total_cost, uc_result = siting_result.ranking[0]
    bat_locs = {0: bus_pair[0], 1: bus_pair[1]}
    draw_uc_result(uc_result, gen_locations, bat_locs, ax)
    ax.set_title(
        f"Best Battery Placement: Buses {bus_pair[0]} & {bus_pair[1]} | Cost: ${total_cost:,.0f}",
        fontsize=13, pad=14
    )


def _line_stress(uc_result, gen_locations, bat_locs, grid):
    """Return max |flow|/fbar per line across all hours (0–1+ scale)."""
    import numpy as np
    PTDF = np.array(grid.PTDF)
    fbar = np.array(grid.fbar).flatten()
    n_lines = len(fbar)
    max_stress = np.zeros(n_lines)

    p_val  = uc_result.dispatch
    rp_val = uc_result.battery_charge
    rm_val = uc_result.battery_discharge
    T = p_val.shape[1]

    for t in range(T):
        demand = grid.power_demand[:, t]
        inj = np.zeros(5)
        for g, bus in gen_locations.items():
            inj[bus - 1] += p_val[g, t]
        for b, bus in bat_locs.items():
            inj[bus - 1] += rm_val[b, t] - rp_val[b, t]
        net = inj - demand
        flow = PTDF @ net
        for k in range(n_lines):
            if fbar[k] < 9000:   # only measure constrained lines
                stress = abs(flow[k]) / fbar[k]
                max_stress[k] = max(max_stress[k], stress)
    return max_stress


def _stress_color(s):
    if s < 0.70:
        return "#444444"
    if s < 0.90:
        return "#ff7f0e"
    return "#d62728"


def _stress_width(s):
    if s < 0.70:
        return 2.0
    if s < 0.90:
        return 3.0
    return 4.0


def draw_siting_panel(uc_result, gen_locations, bat_locs, grid, ax, title, subtitle):
    """Draw one network panel for the siting comparison plot."""
    import numpy as np

    stress = _line_stress(uc_result, gen_locations, bat_locs, grid)
    fbar   = np.array(grid.fbar).flatten()

    edge_list   = [(f, t) for f, t, _ in branches]
    edge_colors = [_stress_color(stress[i]) for i in range(len(branches))]
    edge_widths = [_stress_width(stress[i]) for i in range(len(branches))]

    nx.draw_networkx_edges(G, pos, ax=ax,
                           edgelist=edge_list,
                           edge_color=edge_colors,
                           width=edge_widths,
                           arrows=False)

    # edge stress labels on constrained lines
    edge_labels = {}
    for i, (f, t, _) in enumerate(branches):
        if fbar[i] < 9000:
            pct = int(round(stress[i] * 100))
            edge_labels[(f, t)] = f"{pct}%"
    nx.draw_networkx_edge_labels(G, pos, ax=ax,
                                 edge_labels=edge_labels,
                                 font_size=8,
                                 bbox=dict(fc="white", ec="none", alpha=0.8))

    # nodes
    gen_bus_set = set(gen_locations.values())
    bat_bus_set = set(bat_locs.values())
    node_colors, node_sizes = [], []
    for n in G.nodes:
        if n in gen_bus_set:
            committed = uc_result.commitment[
                [g for g, b in gen_locations.items() if b == n][0], -1
            ]
            node_colors.append(gen_node_color if committed > 0.5 else "#aaaaaa")
            output = uc_result.dispatch[
                [g for g, b in gen_locations.items() if b == n][0], -1
            ]
            node_sizes.append(400 + output * 0.5 if committed > 0.5 else 300)
        elif n in bat_bus_set:
            node_colors.append("#2ca02c")
            node_sizes.append(800)
        else:
            node_colors.append(load_node_color)
            node_sizes.append(600)

    nx.draw_networkx_nodes(G, pos, ax=ax,
                           node_color=node_colors, node_size=node_sizes)

    # battery stars
    for bus in bat_bus_set:
        ax.scatter(*pos[bus], marker="*", s=600, color="white", zorder=5)

    # node labels
    labels = {}
    for n in G.nodes:
        if n in gen_bus_set:
            g_idx = [g for g, b in gen_locations.items() if b == n][0]
            committed = uc_result.commitment[g_idx, -1]
            output = uc_result.dispatch[g_idx, -1]
            labels[n] = f"{n}\n{output:.0f}MW" if committed > 0.5 else f"{n}\n(off)"
        else:
            labels[n] = str(n)
    nx.draw_networkx_labels(G, pos, ax=ax, labels=labels,
                            font_color="white", font_weight="bold", font_size=8)

    ax.set_title(title, fontsize=12, fontweight="bold", pad=10)
    ax.text(0.5, -0.04, subtitle, transform=ax.transAxes,
            ha="center", fontsize=10, color="#444")
    ax.axis("off")


def save_siting_comparison(siting_result, gen_locations, grid, T, assets_file, out_dir=None):
    import os
    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
    os.makedirs(out_dir, exist_ok=True)

    best_pair,  best_cost,  best_uc  = siting_result.ranking[0]
    worst_pair, worst_cost, worst_uc = siting_result.ranking[-1]
    best_bat_locs  = {0: best_pair[0],  1: best_pair[1]}
    worst_bat_locs = {0: worst_pair[0], 1: worst_pair[1]}

    best_cong  = sum(1 for l in best_uc.congested_lines  if l)
    worst_cong = sum(1 for l in worst_uc.congested_lines if l)
    n_infeas   = len(siting_result.infeasible)

    fig, (ax_best, ax_worst) = plt.subplots(1, 2, figsize=(14, 7))
    fig.suptitle(
        f"Battery Siting — Best vs Worst Feasible Placement  |  T={T}h  |  {assets_file}"
        + (f"  |  {n_infeas} infeasible placement(s)" if n_infeas else ""),
        fontsize=13, y=1.01
    )

    draw_siting_panel(
        best_uc, gen_locations, best_bat_locs, grid, ax_best,
        title=f"BEST — Buses {best_pair[0]} & {best_pair[1]}",
        subtitle=f"Cost: ${best_cost:,.0f}  |  Congested hours: {best_cong}"
    )
    draw_siting_panel(
        worst_uc, gen_locations, worst_bat_locs, grid, ax_worst,
        title=f"WORST — Buses {worst_pair[0]} & {worst_pair[1]}",
        subtitle=f"Cost: ${worst_cost:,.0f}  |  Congested hours: {worst_cong}"
    )

    # shared legend
    gen_patch  = mpatches.Patch(color=gen_node_color,  label="Generator (active, last hour)")
    off_patch  = mpatches.Patch(color="#aaaaaa",        label="Generator (off, last hour)")
    load_patch = mpatches.Patch(color=load_node_color,  label="Load bus")
    bat_patch  = mpatches.Patch(color="#2ca02c",        label="Battery bus (★)")
    line_ok    = mpatches.Patch(color="#444444",        label="Line  < 70% of limit")
    line_warn  = mpatches.Patch(color="#ff7f0e",        label="Line 70–90% of limit")
    line_crit  = mpatches.Patch(color="#d62728",        label="Line ≥ 90% of limit")
    fig.legend(
        handles=[gen_patch, off_patch, load_patch, bat_patch,
                 line_ok, line_warn, line_crit],
        loc="lower center", ncol=4, fontsize=9,
        framealpha=0.9, bbox_to_anchor=(0.5, -0.04)
    )

    filename = os.path.join(
        out_dir,
        f"siting_{T}h_{assets_file.replace('.py', '')}_comparison.png"
    )
    plt.tight_layout()
    plt.savefig(filename, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Plot saved: {filename}")
    return filename


def save_dispatch_overview(result, opt_name, T, assets_file, generators, batteries, grid=None, out_dir=None):
    import os
    import numpy as np
    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
    os.makedirs(out_dir, exist_ok=True)

    hours = list(range(1, T + 1))
    is_uc = hasattr(result, "commitment")

    gen_colors = ["#e05c3a", "#5b8dd9", "#2ca02c"]
    bat_colors = ["#9467bd", "#8c564b"]

    fig, axes = plt.subplots(4, 1, figsize=(13, 11), sharex=True)
    fig.suptitle(
        f"PJM 5-Bus — {opt_name} Overview | T={T}h | {assets_file}",
        fontsize=13, y=0.98
    )

    # shade congested hours across all panels
    congested_hours = {t + 1 for t, lines in enumerate(result.congested_lines) if lines}
    for ax in axes:
        for h in congested_hours:
            ax.axvspan(h - 0.5, h + 0.5, color="#ffcccc", alpha=0.5, zorder=0)

    # --- panel 1: generator dispatch ---
    ax = axes[0]
    for g, gen in enumerate(generators):
        dispatch = result.dispatch[g, :T]
        label = gen["name"]
        if is_uc:
            committed = result.commitment[g, :T]
            # solid when on, dotted when off
            on_mask  = committed > 0.5
            off_mask = ~on_mask
            x_on  = [h for h, on in zip(hours, on_mask)  if on]
            y_on  = [dispatch[t] for t, on in enumerate(on_mask)  if on]
            x_off = [h for h, off in zip(hours, off_mask) if off]
            y_off = [dispatch[t] for t, off in enumerate(off_mask) if off]
            ax.plot(x_on,  y_on,  color=gen_colors[g], linewidth=2, marker="o", markersize=4, label=label)
            if x_off:
                ax.plot(x_off, y_off, color=gen_colors[g], linewidth=1, linestyle="--",
                        marker="x", markersize=5, alpha=0.4)
        else:
            ax.plot(hours, dispatch, color=gen_colors[g], linewidth=2, marker="o", markersize=4, label=label)

    if grid is not None:
        demand_total = np.array(grid.power_demand).sum(axis=0)[:T]
        ax.plot(hours, demand_total, color="black", linewidth=1.5, linestyle=":", label="Total demand")

    ax.set_ylabel("Output (MW)", fontsize=10)
    ax.set_title("Generator Dispatch" + (" (dashed = committed OFF)" if is_uc else ""), fontsize=10)
    ax.legend(loc="upper left", fontsize=8, ncol=2)
    ax.grid(axis="y", linestyle="--", alpha=0.35)

    # --- panel 2: battery net MW ---
    ax = axes[1]
    ax.axhline(0, color="black", linewidth=0.8, linestyle="-")
    for b, bat in enumerate(batteries):
        net = result.battery_charge[b, :T] - result.battery_discharge[b, :T]
        label = f"{bat['name']} (+charge / -discharge)"
        ax.plot(hours, net, color=bat_colors[b], linewidth=2, marker="o", markersize=4, label=label)
        ax.fill_between(hours, net, 0,
                        where=[v > 0 for v in net], alpha=0.15, color=bat_colors[b])
        ax.fill_between(hours, net, 0,
                        where=[v < 0 for v in net], alpha=0.25, color=bat_colors[b])

    ax.set_ylabel("MW", fontsize=10)
    ax.set_title("Battery Charge / Discharge  (positive = charging)", fontsize=10)
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(axis="y", linestyle="--", alpha=0.35)

    # --- panel 3: battery SOC ---
    ax = axes[2]
    for b, bat in enumerate(batteries):
        soc = result.soc[b, :T]
        cap = bat["capacity_mwh"]
        ax.plot(hours, soc, color=bat_colors[b], linewidth=2, marker="o", markersize=4,
                label=f"{bat['name']} (cap {cap} MWh)")
        ax.axhline(cap, color=bat_colors[b], linewidth=0.8, linestyle="--", alpha=0.5)

    ax.set_ylabel("SOC (MWh)", fontsize=10)
    ax.set_title("Battery State of Charge", fontsize=10)
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(axis="y", linestyle="--", alpha=0.35)

    # --- panel 4: hourly cost ---
    ax = axes[3]
    ax.bar(hours, result.hourly_costs[:T], color="#7f7f7f", alpha=0.75, width=0.7)
    ax.set_ylabel("Cost ($)", fontsize=10)
    ax.set_xlabel("Hour", fontsize=10)
    ax.set_title("Hourly Generation Cost", fontsize=10)
    ax.grid(axis="y", linestyle="--", alpha=0.35)

    if congested_hours:
        axes[0].annotate(
            f"Red shading = congested hour(s): {sorted(congested_hours)}",
            xy=(0.01, 0.97), xycoords="axes fraction",
            fontsize=7.5, color="#cc0000", va="top"
        )

    ax.set_xticks(hours)
    ax.set_xlim(0.5, T + 0.5)

    plt.tight_layout(rect=[0, 0, 1, 0.97])
    filename = os.path.join(out_dir, f"{opt_name.lower()}_{T}h_{assets_file.replace('.py', '')}_overview.png")
    plt.savefig(filename, dpi=150)
    plt.close(fig)
    print(f"Plot saved: {filename}")
    return filename


def save_demand_plot(grid, out_dir=None):
    import os
    import numpy as np
    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
    os.makedirs(out_dir, exist_ok=True)

    demand = np.array(grid.power_demand)  # (5, 24)
    T = demand.shape[1]
    hours = list(range(1, T + 1))

    bus_labels = ["Bus 2 (300 MW base)", "Bus 3 (300 MW base)", "Bus 4 (400 MW base)"]
    bus_colors = ["#5b8dd9", "#e05c3a", "#2ca02c"]
    bus_indices = [1, 2, 3]  # bus 2, 3, 4 have loads (0-indexed)

    total = demand.sum(axis=0)

    fig, ax = plt.subplots(figsize=(11, 5))
    bottom = np.zeros(T)
    for idx, (label, color) in zip(bus_indices, zip(bus_labels, bus_colors)):
        ax.bar(hours, demand[idx], bottom=bottom, label=label, color=color, alpha=0.75, width=0.8)
        bottom += demand[idx]

    ax.plot(hours, total, color="black", linewidth=2, marker="o", markersize=4, label="Total demand")

    ax.set_xlabel("Hour", fontsize=11)
    ax.set_ylabel("Demand (MW)", fontsize=11)
    ax.set_title("PJM 5-Bus System — 24-Hour Demand Profile", fontsize=13, pad=12)
    ax.set_xticks(hours)
    ax.set_xlim(0.5, T + 0.5)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(axis="y", linestyle="--", alpha=0.4)

    filename = os.path.join(out_dir, "demand_profile_24h.png")
    plt.tight_layout()
    plt.savefig(filename, dpi=150)
    plt.close(fig)
    print(f"Plot saved: {filename}")
    return filename


def save_plot(result, opt_name: str, T: int, assets_file: str, grid=None):
    import os
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
    os.makedirs(out_dir, exist_ok=True)

    gen_locations = {0: 1, 1: 3, 2: 5}
    bat_locations = {0: 2, 1: 4}

    if hasattr(result, "ranking"):
        if grid is not None and len(result.ranking) >= 2:
            save_siting_comparison(result, gen_locations, grid, T, assets_file, out_dir)
            return
        # fallback: single best-placement network (no grid object available)
        fig, ax = plt.subplots(figsize=(9, 7))
        draw_siting_result(result, gen_locations, ax)
    elif hasattr(result, "commitment"):
        fig, ax = plt.subplots(figsize=(9, 7))
        draw_uc_result(result, gen_locations, bat_locations, ax)
    else:
        fig, ax = plt.subplots(figsize=(9, 7))
        draw_ed_result(result, gen_locations, bat_locations, ax)

    filename = os.path.join(out_dir, f"{opt_name.lower()}_{T}h_{assets_file.replace('.py', '')}.png")
    plt.tight_layout()
    plt.savefig(filename, dpi=150)
    plt.close(fig)
    print(f"Plot saved: {filename}")


if __name__ == "__main__":
    fig, ax = plt.subplots(figsize=(9, 7))
    ax.set_title("PJM 5-Bus Network — Generator Locations", fontsize=14, pad=14)

    draw_network(G, pos, ax)

    # Edge labels: show limit in MW where constrained
    constrained = {(f, t): f"{lim} MW limit" for f, t, lim in branches if lim > 0}
    nx.draw_networkx_edge_labels(G, pos, ax=ax,
                                 edge_labels=constrained,
                                 font_size=8, bbox=dict(fc="white", ec="none", alpha=0.7))

    # Legend — node type
    gen_patch  = mpatches.Patch(color=gen_node_color,  label="Generator bus")
    load_patch = mpatches.Patch(color=load_node_color, label="Load / reference bus")

    # Legend — generator power ranges
    gen_lines = [
        mpatches.Patch(color="none", label=f"  {label} @ Bus {bus}:  "
                                           f"{pmin}–{pmax} MW,  ${cost}/MWh")
        for label, bus, pmin, pmax, cost in generators
    ]

    legend = ax.legend(
        handles=[gen_patch, load_patch, mpatches.Patch(color="none", label="")] + gen_lines,
        loc="lower left",
        fontsize=9,
        framealpha=0.9,
        title="Key",
        title_fontsize=10,
    )

    ax.axis("off")
    plt.tight_layout()
    plt.savefig("network.png", dpi=150)
    plt.show()
