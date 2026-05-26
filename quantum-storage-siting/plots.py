import os
import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches


# ---------------------------------------------------------------------------
# Module-level pjm5 topology — used only by the __main__ standalone block
# ---------------------------------------------------------------------------

# (fbus, tbus, flow_limit_MW)
branches = [
    (1, 2, 400),
    (1, 4,   0),
    (1, 5,   0),
    (2, 3,   0),
    (3, 4,   0),
    (4, 5, 240),
]

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


# ---------------------------------------------------------------------------
# Dynamic topology builder
# ---------------------------------------------------------------------------

def _build_grid_graph(grid):
    """Build a networkx graph from a Case object.

    Looks for branch/bus data on the object itself or on grid.case_description,
    which is how the BaseCase subclasses expose MATPOWER data.
    """
    import numpy as np
    fbar = np.array(grid.fbar).flatten()

    # branch data: try direct attribute first, then case_description
    cd = getattr(grid, "case_description", None)
    branch_data = (
        getattr(grid, "branch", None)
        or (getattr(cd, "branch", None) if cd is not None else None)
    )
    bus_data = (
        getattr(grid, "bus", None)
        or (getattr(cd, "bus", None) if cd is not None else None)
    )

    if branch_data is None:
        raise AttributeError("Cannot find branch data on grid object.")

    branches_list = [(int(row[0]), int(row[1]), float(fbar[i]))
                     for i, row in enumerate(branch_data)]
    n_bus = len(bus_data) if bus_data is not None else max(
        b for f, t, _ in branches_list for b in (f, t)
    )
    Gg = nx.Graph()
    Gg.add_nodes_from(range(1, n_bus + 1))
    for f, t, _ in branches_list:
        Gg.add_edge(f, t)
    pos_g = nx.kamada_kawai_layout(Gg)
    return Gg, pos_g, branches_list


# ---------------------------------------------------------------------------
# Label helpers — black text, white bbox, offset above node
# ---------------------------------------------------------------------------

def _label_pos(pos_g, offset=0.06):
    """Return positions shifted slightly above each node for readable labels."""
    return {n: (x, y + offset) for n, (x, y) in pos_g.items()}


def _draw_labels(Gg, pos_g, ax, labels, font_size=8):
    lpos = _label_pos(pos_g)
    nx.draw_networkx_labels(
        Gg, lpos, ax=ax, labels=labels,
        font_color="black", font_size=font_size,
        bbox=dict(fc="white", ec="none", alpha=0.85, pad=1.5),
    )


# ---------------------------------------------------------------------------
# Core drawing helpers
# ---------------------------------------------------------------------------

def draw_network(Gg, pos_g, ax, gen_buses_set=None):
    if gen_buses_set is None:
        gen_buses_set = gen_buses
    node_colors = [gen_node_color if n in gen_buses_set else load_node_color
                   for n in Gg.nodes]
    node_sizes  = [900 if n in gen_buses_set else 600 for n in Gg.nodes]
    nx.draw_networkx_nodes(Gg, pos_g, ax=ax,
                           node_color=node_colors, node_size=node_sizes)
    nx.draw_networkx_edges(Gg, pos_g, ax=ax,
                           edge_color="#444444", width=2, arrows=False)
    _draw_labels(Gg, pos_g, ax, {n: str(n) for n in Gg.nodes})


def _congested_edge_colors(result, branches_list=None):
    if branches_list is None:
        branches_list = branches
    all_congested = set()
    for hour_lines in result.congested_lines:
        for idx in hour_lines:
            all_congested.add(idx)
    return ["red" if i in all_congested else "black" for i in range(len(branches_list))]


def _draw_datacenter(ax, pos_g, dc_bus, dc_mw):
    """Overlay a datacenter marker (purple diamond) on the network axes."""
    x, y = pos_g[dc_bus]
    ax.scatter(x, y, marker="D", s=220, color="#7b2d8b", zorder=6)
    ax.annotate(
        f"DC\n{dc_mw:.0f} MW",
        xy=(x, y), xytext=(0, -22), textcoords="offset points",
        ha="center", va="top", fontsize=7.5, fontweight="bold",
        color="#7b2d8b",
        bbox=dict(fc="white", ec="none", alpha=0.85, pad=1),
    )


def draw_ed_result(result, gen_locations: dict, bat_locations: dict, ax,
                   _topo=None, dc_bus=None, dc_mw=0.0):
    if _topo is None:
        Gg, pos_g, branches_list = G, pos, branches
    else:
        Gg, pos_g, branches_list = _topo

    edge_colors = _congested_edge_colors(result, branches_list)
    nx.draw_networkx_edges(Gg, pos_g, ax=ax,
                           edgelist=[(f, t) for f, t, _ in branches_list],
                           edge_color=edge_colors, width=2, arrows=False)

    gen_bus_set = set(gen_locations.values())
    bat_bus_set = set(bat_locations.values())
    node_colors, node_sizes = [], []
    for n in Gg.nodes:
        if n in gen_bus_set:
            gen_idx = [g for g, b in gen_locations.items() if b == n][0]
            node_sizes.append(400 + result.dispatch[gen_idx, -1] * 0.5)
            node_colors.append(gen_node_color)
        elif n in bat_bus_set:
            node_sizes.append(800)
            node_colors.append("#2ca02c")
        else:
            node_sizes.append(600)
            node_colors.append(load_node_color)

    nx.draw_networkx_nodes(Gg, pos_g, ax=ax, nodelist=list(Gg.nodes),
                           node_color=node_colors, node_size=node_sizes)

    for bat_idx, bus in bat_locations.items():
        ax.scatter(*pos_g[bus], marker="*", s=600, color="#2ca02c", zorder=5)

    labels = {}
    for gen_idx, bus in gen_locations.items():
        labels[bus] = f"{bus}\n{result.dispatch[gen_idx, -1]:.0f} MW"
    for bat_idx, bus in bat_locations.items():
        soc = result.soc[bat_idx, -1]
        labels[bus] = labels.get(bus, str(bus)) + f"\nB{bat_idx} {soc:.0f}MWh"
    for n in Gg.nodes:
        if n not in labels:
            labels[n] = str(n)
    _draw_labels(Gg, pos_g, ax, labels)

    if dc_bus is not None and dc_mw > 0:
        _draw_datacenter(ax, pos_g, dc_bus, dc_mw)

    gen_patch  = mpatches.Patch(color=gen_node_color,  label="Generator bus")
    load_patch = mpatches.Patch(color=load_node_color, label="Load / reference bus")
    bat_patch  = mpatches.Patch(color="#2ca02c",       label="Battery bus")
    cong_patch = mpatches.Patch(color="red",           label="Congested line")
    handles = [gen_patch, load_patch, bat_patch, cong_patch]
    if dc_bus is not None and dc_mw > 0:
        handles.append(mpatches.Patch(color="#7b2d8b", label="Datacenter"))
    ax.legend(handles=handles, loc="lower left", fontsize=8, framealpha=0.9)
    ax.axis("off")


def draw_uc_result(result, gen_locations: dict, bat_locations: dict, ax,
                   _topo=None, dc_bus=None, dc_mw=0.0):
    if _topo is None:
        Gg, pos_g, branches_list = G, pos, branches
    else:
        Gg, pos_g, branches_list = _topo

    edge_colors = _congested_edge_colors(result, branches_list)
    nx.draw_networkx_edges(Gg, pos_g, ax=ax,
                           edgelist=[(f, t) for f, t, _ in branches_list],
                           edge_color=edge_colors, width=2, arrows=False)

    gen_bus_set = set(gen_locations.values())
    bat_bus_set = set(bat_locations.values())
    node_colors, node_sizes = [], []
    for n in Gg.nodes:
        if n in gen_bus_set:
            gen_idx = [g for g, b in gen_locations.items() if b == n][0]
            committed = result.commitment[gen_idx, -1]
            if committed == 1:
                node_sizes.append(400 + result.dispatch[gen_idx, -1] * 0.5)
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

    nx.draw_networkx_nodes(Gg, pos_g, ax=ax, nodelist=list(Gg.nodes),
                           node_color=node_colors, node_size=node_sizes)

    for bat_idx, bus in bat_locations.items():
        ax.scatter(*pos_g[bus], marker="*", s=600, color="#2ca02c", zorder=5)

    labels = {}
    for gen_idx, bus in gen_locations.items():
        committed = result.commitment[gen_idx, -1]
        if committed == 1:
            labels[bus] = f"{bus}\n{result.dispatch[gen_idx, -1]:.0f} MW"
        else:
            labels[bus] = f"{bus}\n(off)"
    for bat_idx, bus in bat_locations.items():
        soc = result.soc[bat_idx, -1]
        labels[bus] = labels.get(bus, str(bus)) + f"\nB{bat_idx} {soc:.0f}MWh"
    for n in Gg.nodes:
        if n not in labels:
            labels[n] = str(n)
    _draw_labels(Gg, pos_g, ax, labels)

    if dc_bus is not None and dc_mw > 0:
        _draw_datacenter(ax, pos_g, dc_bus, dc_mw)

    gen_patch  = mpatches.Patch(color=gen_node_color,  label="Generator bus (active)")
    off_patch  = mpatches.Patch(color="#aaaaaa",       label="Generator bus (inactive)")
    load_patch = mpatches.Patch(color=load_node_color, label="Load / reference bus")
    bat_patch  = mpatches.Patch(color="#2ca02c",       label="Battery bus")
    cong_patch = mpatches.Patch(color="red",           label="Congested line")
    handles = [gen_patch, off_patch, load_patch, bat_patch, cong_patch]
    if dc_bus is not None and dc_mw > 0:
        handles.append(mpatches.Patch(color="#7b2d8b", label="Datacenter"))
    ax.legend(handles=handles, loc="lower left", fontsize=8, framealpha=0.9)
    ax.axis("off")


def draw_siting_result(siting_result, gen_locations: dict, ax, _topo=None):
    bus_pair, total_cost, uc_result = siting_result.ranking[0]
    bat_locs = {i: bus for i, bus in enumerate(bus_pair)}
    draw_uc_result(uc_result, gen_locations, bat_locs, ax, _topo=_topo)
    ax.set_title(
        f"Best Battery Placement: Buses {bus_pair} | Cost: ${total_cost:,.0f}",
        fontsize=13, pad=14,
    )


# ---------------------------------------------------------------------------
# Line stress utilities
# ---------------------------------------------------------------------------

def _line_stress(uc_result, gen_locations, bat_locs, grid):
    """Return max |flow|/fbar per line across all hours."""
    import numpy as np
    PTDF  = np.array(grid.PTDF)
    fbar  = np.array(grid.fbar).flatten()
    n_bus = PTDF.shape[1]
    max_stress = np.zeros(len(fbar))

    p_val  = uc_result.dispatch
    rp_val = uc_result.battery_charge
    rm_val = uc_result.battery_discharge
    T = p_val.shape[1]

    for t in range(T):
        demand = grid.power_demand[:, t]
        inj = np.zeros(n_bus)
        for g, bus in gen_locations.items():
            inj[bus - 1] += p_val[g, t]
        for b, bus in bat_locs.items():
            inj[bus - 1] += rm_val[b, t] - rp_val[b, t]
        flow = PTDF @ (inj - demand)
        for k in range(len(fbar)):
            if fbar[k] < 9000:
                max_stress[k] = max(max_stress[k], abs(flow[k]) / fbar[k])
    return max_stress


def _stress_color(s):
    if s < 0.70: return "#444444"
    if s < 0.90: return "#ff7f0e"
    return "#d62728"


def _stress_width(s):
    if s < 0.70: return 2.0
    if s < 0.90: return 3.0
    return 4.0


def draw_siting_panel(uc_result, gen_locations, bat_locs, grid, ax, title, subtitle,
                      _topo=None):
    import numpy as np
    if _topo is None:
        Gg, pos_g, branches_list = G, pos, branches
    else:
        Gg, pos_g, branches_list = _topo

    stress = _line_stress(uc_result, gen_locations, bat_locs, grid)
    fbar   = np.array(grid.fbar).flatten()

    edge_list   = [(f, t) for f, t, _ in branches_list]
    edge_colors = [_stress_color(stress[i]) for i in range(len(branches_list))]
    edge_widths = [_stress_width(stress[i]) for i in range(len(branches_list))]
    nx.draw_networkx_edges(Gg, pos_g, ax=ax, edgelist=edge_list,
                           edge_color=edge_colors, width=edge_widths, arrows=False)

    edge_labels = {}
    for i, (f, t, _) in enumerate(branches_list):
        if fbar[i] < 9000:
            edge_labels[(f, t)] = f"{int(round(stress[i] * 100))}%"
    nx.draw_networkx_edge_labels(Gg, pos_g, ax=ax, edge_labels=edge_labels,
                                 font_size=7, font_color="black",
                                 bbox=dict(fc="white", ec="none", alpha=0.8))

    gen_bus_set = set(gen_locations.values())
    bat_bus_set = set(bat_locs.values())
    node_colors, node_sizes = [], []
    for n in Gg.nodes:
        if n in gen_bus_set:
            g_idx = [g for g, b in gen_locations.items() if b == n][0]
            committed = uc_result.commitment[g_idx, -1]
            node_colors.append(gen_node_color if committed > 0.5 else "#aaaaaa")
            output = uc_result.dispatch[g_idx, -1]
            node_sizes.append(400 + output * 0.5 if committed > 0.5 else 300)
        elif n in bat_bus_set:
            node_colors.append("#2ca02c")
            node_sizes.append(700)
        else:
            node_colors.append(load_node_color)
            node_sizes.append(500)

    nx.draw_networkx_nodes(Gg, pos_g, ax=ax, node_color=node_colors, node_size=node_sizes)

    for bus in bat_bus_set:
        ax.scatter(*pos_g[bus], marker="*", s=500, color="white", zorder=5)

    labels = {}
    for n in Gg.nodes:
        if n in gen_bus_set:
            g_idx = [g for g, b in gen_locations.items() if b == n][0]
            committed = uc_result.commitment[g_idx, -1]
            output = uc_result.dispatch[g_idx, -1]
            labels[n] = f"{n}\n{output:.0f}MW" if committed > 0.5 else f"{n}\n(off)"
        elif n in bat_bus_set:
            b_indices = [b for b, bus in bat_locs.items() if bus == n]
            soc_str = ",".join(f"B{b}" for b in b_indices)
            labels[n] = f"{n}\n{soc_str}"
        else:
            labels[n] = str(n)
    _draw_labels(Gg, pos_g, ax, labels, font_size=7)

    ax.set_title(title, fontsize=11, fontweight="bold", pad=10)
    ax.text(0.5, -0.04, subtitle, transform=ax.transAxes,
            ha="center", fontsize=9, color="#444")
    ax.axis("off")


# ---------------------------------------------------------------------------
# Save functions
# ---------------------------------------------------------------------------

def save_siting_comparison(siting_result, gen_locations, grid, T, assets_file,
                           out_dir=None):
    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
    os.makedirs(out_dir, exist_ok=True)

    _topo = _build_grid_graph(grid)

    best_pair,  best_cost,  best_uc  = siting_result.ranking[0]
    worst_pair, worst_cost, worst_uc = siting_result.ranking[-1]
    best_bat_locs  = {i: bus for i, bus in enumerate(best_pair)}
    worst_bat_locs = {i: bus for i, bus in enumerate(worst_pair)}

    best_cong  = sum(1 for l in best_uc.congested_lines  if l)
    worst_cong = sum(1 for l in worst_uc.congested_lines if l)
    n_infeas   = len(siting_result.infeasible)

    fig, (ax_best, ax_worst) = plt.subplots(1, 2, figsize=(16, 8))
    fig.suptitle(
        f"Battery Siting — Best vs Worst Feasible Placement  |  T={T}h  |  {assets_file}"
        + (f"  |  {n_infeas} infeasible" if n_infeas else ""),
        fontsize=13, y=1.01,
    )

    draw_siting_panel(
        best_uc, gen_locations, best_bat_locs, grid, ax_best,
        title=f"BEST — Buses {best_pair}",
        subtitle=f"Cost: ${best_cost:,.0f}  |  Congested hours: {best_cong}",
        _topo=_topo,
    )
    draw_siting_panel(
        worst_uc, gen_locations, worst_bat_locs, grid, ax_worst,
        title=f"WORST — Buses {worst_pair}",
        subtitle=f"Cost: ${worst_cost:,.0f}  |  Congested hours: {worst_cong}",
        _topo=_topo,
    )

    gen_patch  = mpatches.Patch(color=gen_node_color,  label="Generator (active)")
    off_patch  = mpatches.Patch(color="#aaaaaa",        label="Generator (off)")
    load_patch = mpatches.Patch(color=load_node_color,  label="Load bus")
    bat_patch  = mpatches.Patch(color="#2ca02c",        label="Battery bus (★)")
    line_ok    = mpatches.Patch(color="#444444",        label="Line  < 70%")
    line_warn  = mpatches.Patch(color="#ff7f0e",        label="Line 70–90%")
    line_crit  = mpatches.Patch(color="#d62728",        label="Line ≥ 90%")
    fig.legend(handles=[gen_patch, off_patch, load_patch, bat_patch,
                         line_ok, line_warn, line_crit],
               loc="lower center", ncol=4, fontsize=9,
               framealpha=0.9, bbox_to_anchor=(0.5, -0.04))

    filename = os.path.join(
        out_dir,
        f"siting_{T}h_{assets_file.replace('.py', '')}_comparison.png",
    )
    plt.tight_layout()
    plt.savefig(filename, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Plot saved: {filename}")
    return filename


def save_dispatch_overview(result, opt_name, T, assets_file, generators, batteries,
                           grid=None, out_dir=None):
    import numpy as np
    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
    os.makedirs(out_dir, exist_ok=True)

    hours = list(range(1, T + 1))
    is_uc = hasattr(result, "commitment")

    gen_colors = ["#e05c3a", "#5b8dd9", "#2ca02c", "#d62728", "#ff7f0e",
                  "#1f77b4", "#8c564b", "#bcbd22"]
    bat_colors = ["#9467bd", "#8c564b", "#17becf", "#e377c2", "#7f7f7f", "#bcbd22"]

    fig, axes = plt.subplots(4, 1, figsize=(13, 11), sharex=True)
    fig.suptitle(f"{opt_name} Overview | T={T}h | {assets_file}", fontsize=13, y=0.98)

    congested_hours = {t + 1 for t, lines in enumerate(result.congested_lines) if lines}
    for ax in axes:
        for h in congested_hours:
            ax.axvspan(h - 0.5, h + 0.5, color="#ffcccc", alpha=0.5, zorder=0)

    # panel 1: generator dispatch
    ax = axes[0]
    for g, gen in enumerate(generators):
        dispatch = result.dispatch[g, :T]
        label = gen["name"]
        if is_uc:
            committed = result.commitment[g, :T]
            on_mask  = committed > 0.5
            x_on  = [h for h, on in zip(hours, on_mask)  if on]
            y_on  = [dispatch[t] for t, on in enumerate(on_mask)  if on]
            x_off = [h for h, off in zip(hours, ~on_mask) if off]
            y_off = [dispatch[t] for t, off in enumerate(~on_mask) if off]
            ax.plot(x_on, y_on, color=gen_colors[g], linewidth=2,
                    marker="o", markersize=4, label=label)
            if x_off:
                ax.plot(x_off, y_off, color=gen_colors[g], linewidth=1,
                        linestyle="--", marker="x", markersize=5, alpha=0.4)
        else:
            ax.plot(hours, dispatch, color=gen_colors[g], linewidth=2,
                    marker="o", markersize=4, label=label)

    if grid is not None:
        demand_total = np.array(grid.power_demand).sum(axis=0)[:T]
        ax.plot(hours, demand_total, color="black", linewidth=1.5,
                linestyle=":", label="Total demand")

    ax.set_ylabel("Output (MW)", fontsize=10)
    ax.set_title("Generator Dispatch" + (" (dashed = OFF)" if is_uc else ""), fontsize=10)
    ax.legend(loc="upper left", fontsize=8, ncol=2)
    ax.grid(axis="y", linestyle="--", alpha=0.35)

    # panel 2: battery net MW
    ax = axes[1]
    ax.axhline(0, color="black", linewidth=0.8)
    for b, bat in enumerate(batteries):
        net = result.battery_charge[b, :T] - result.battery_discharge[b, :T]
        label = f"{bat['name']} (+charge / -discharge)"
        ax.plot(hours, net, color=bat_colors[b], linewidth=2, marker="o", markersize=4, label=label)
        ax.fill_between(hours, net, 0, where=[v > 0 for v in net],
                        alpha=0.15, color=bat_colors[b])
        ax.fill_between(hours, net, 0, where=[v < 0 for v in net],
                        alpha=0.25, color=bat_colors[b])
    ax.set_ylabel("MW", fontsize=10)
    ax.set_title("Battery Charge / Discharge  (positive = charging)", fontsize=10)
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(axis="y", linestyle="--", alpha=0.35)

    # panel 3: battery SOC
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

    # panel 4: hourly cost
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
            fontsize=7.5, color="#cc0000", va="top",
        )

    ax.set_xticks(hours)
    ax.set_xlim(0.5, T + 0.5)
    plt.tight_layout(rect=[0, 0, 1, 0.97])
    filename = os.path.join(
        out_dir, f"{opt_name.lower()}_{T}h_{assets_file.replace('.py', '')}_overview.png"
    )
    plt.savefig(filename, dpi=150)
    plt.close(fig)
    print(f"Plot saved: {filename}")
    return filename


def save_demand_plot(grid, out_dir=None):
    import numpy as np
    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
    os.makedirs(out_dir, exist_ok=True)

    demand = np.array(grid.power_demand)  # (n_bus, T)
    T_d = demand.shape[1]
    hours = list(range(1, T_d + 1))

    bus_labels = ["Bus 2 (300 MW base)", "Bus 3 (300 MW base)", "Bus 4 (400 MW base)"]
    bus_colors = ["#5b8dd9", "#e05c3a", "#2ca02c"]
    bus_indices = [1, 2, 3]

    total = demand.sum(axis=0)

    fig, ax = plt.subplots(figsize=(11, 5))
    bottom = np.zeros(T_d)
    for idx, (label, color) in zip(bus_indices, zip(bus_labels, bus_colors)):
        if idx < demand.shape[0]:
            ax.bar(hours, demand[idx], bottom=bottom, label=label,
                   color=color, alpha=0.75, width=0.8)
            bottom += demand[idx]

    ax.plot(hours, total, color="black", linewidth=2, marker="o", markersize=4,
            label="Total demand")
    ax.set_xlabel("Hour", fontsize=11)
    ax.set_ylabel("Demand (MW)", fontsize=11)
    ax.set_title("24-Hour Demand Profile", fontsize=13, pad=12)
    ax.set_xticks(hours)
    ax.set_xlim(0.5, T_d + 0.5)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(axis="y", linestyle="--", alpha=0.4)

    filename = os.path.join(out_dir, "demand_profile_24h.png")
    plt.tight_layout()
    plt.savefig(filename, dpi=150)
    plt.close(fig)
    print(f"Plot saved: {filename}")
    return filename


def save_plot(result, opt_name: str, T: int, assets_file: str, grid=None,
              generators=None, bat_locs=None, dc_bus=None, dc_mw=0.0):
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
    os.makedirs(out_dir, exist_ok=True)

    # Build gen/bat location dicts from runtime data if available
    if generators is not None:
        gen_locations = {g: generators[g]["bus"] for g in range(len(generators))}
    else:
        gen_locations = {0: 1, 1: 3, 2: 5}  # pjm5 fallback

    if bat_locs is not None:
        bat_locations = dict(bat_locs)
    else:
        bat_locations = {0: 2, 1: 4}  # pjm5 fallback

    _topo = _build_grid_graph(grid) if grid is not None else None

    if hasattr(result, "ranking"):
        if grid is not None and len(result.ranking) >= 2:
            save_siting_comparison(result, gen_locations, grid, T, assets_file, out_dir)
            return
        fig, ax = plt.subplots(figsize=(10, 8))
        draw_siting_result(result, gen_locations, ax, _topo=_topo)
    elif hasattr(result, "commitment"):
        fig, ax = plt.subplots(figsize=(10, 8))
        draw_uc_result(result, gen_locations, bat_locations, ax, _topo=_topo,
                       dc_bus=dc_bus, dc_mw=dc_mw)
    else:
        fig, ax = plt.subplots(figsize=(10, 8))
        draw_ed_result(result, gen_locations, bat_locations, ax, _topo=_topo,
                       dc_bus=dc_bus, dc_mw=dc_mw)

    filename = os.path.join(
        out_dir, f"{opt_name.lower()}_{T}h_{assets_file.replace('.py', '')}.png"
    )
    plt.tight_layout()
    plt.savefig(filename, dpi=150)
    plt.close(fig)
    print(f"Plot saved: {filename}")


if __name__ == "__main__":
    fig, ax = plt.subplots(figsize=(9, 7))
    ax.set_title("Network — Generator Locations", fontsize=14, pad=14)

    gen_buses_pjm5 = {g[1] for g in generators}
    draw_network(G, pos, ax, gen_buses_set=gen_buses_pjm5)

    constrained = {(f, t): f"{lim} MW" for f, t, lim in branches if lim > 0}
    nx.draw_networkx_edge_labels(G, pos, ax=ax, edge_labels=constrained,
                                 font_size=8, font_color="black",
                                 bbox=dict(fc="white", ec="none", alpha=0.7))

    gen_patch  = mpatches.Patch(color=gen_node_color,  label="Generator bus")
    load_patch = mpatches.Patch(color=load_node_color, label="Load / reference bus")
    gen_lines  = [
        mpatches.Patch(color="none", label=f"  {label} @ Bus {bus}: {pmin}–{pmax} MW, ${cost}/MWh")
        for label, bus, pmin, pmax, cost in generators
    ]
    ax.legend(handles=[gen_patch, load_patch, mpatches.Patch(color="none", label="")] + gen_lines,
              loc="lower left", fontsize=9, framealpha=0.9, title="Key", title_fontsize=10)
    ax.axis("off")
    plt.tight_layout()
    plt.savefig("network.png", dpi=150)
    plt.show()
