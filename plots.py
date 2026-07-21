import os
import textwrap
import networkx as nx
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches


# ---------------------------------------------------------------------------
# Time-axis scaling helpers — keep multi-day (T up to 168h) plots readable
# instead of cramming one tick/label per hour into a fixed-width figure.
# ---------------------------------------------------------------------------

def _time_axis_figwidth(T, base=13.0, min_width=13.0, max_width=34.0, per_hour=0.11):
    """Figure width (inches) that grows with T but saturates for long horizons."""
    return max(min_width, min(max_width, base + per_hour * max(0, T - 24)))


def _hour_tick_step(T, max_ticks=28):
    """Pick a 'nice' hour spacing so tick labels never overlap regardless of T."""
    if T <= max_ticks:
        return 1
    for step in (2, 3, 4, 6, 8, 12, 24, 48, 72):
        if -(-T // step) <= max_ticks:  # ceil division
            return step
    return 168


def _set_hour_axis(ax, T, xlabel=None):
    step = _hour_tick_step(T)
    ticks = list(range(1, T + 1, step))
    if ticks[-1] != T:
        ticks.append(T)
    ax.set_xticks(ticks)
    ax.set_xlim(0.5, T + 0.5)
    if T > 24:
        ax.tick_params(axis="x", labelrotation=45)
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=10)


def _format_congested_hours(congested_hours, max_chars=60):
    """Compact a possibly-long set of hours into ranges, wrapped to fit the figure."""
    hours = sorted(congested_hours)
    ranges = []
    start = prev = hours[0]
    for h in hours[1:]:
        if h == prev + 1:
            prev = h
            continue
        ranges.append(f"{start}" if start == prev else f"{start}-{prev}")
        start = prev = h
    ranges.append(f"{start}" if start == prev else f"{start}-{prev}")
    text = f"Red shading = congested hour(s): {', '.join(ranges)}"
    return "\n".join(textwrap.wrap(text, width=max_chars))


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

gen_node_color   = "#e05c3a"
load_node_color  = "#5b8dd9"
outage_node_color = "#8e44ad"  # forced outage (contingency), distinct from active/grey/battery/line colors


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

def _draw_labels(Gg, pos_g, ax, labels, font_size=8):
    import matplotlib.patheffects as _pe
    _stroke = [_pe.withStroke(linewidth=3, foreground="white")]
    for n, lbl in labels.items():
        x, y = pos_g[n]
        ax.text(x, y + 0.11, lbl, fontsize=font_size, ha="center", va="bottom",
                color="black", zorder=6, path_effects=_stroke)


# ---------------------------------------------------------------------------
# Core drawing helpers
# ---------------------------------------------------------------------------

def _grid_load_buses(grid):
    """Buses (1-indexed) with nonzero demand at any hour, or None if unknown."""
    if grid is None:
        return None
    import numpy as np
    demand = np.array(grid.power_demand)
    return {i + 1 for i in range(demand.shape[0]) if demand[i].sum() > 0}


def _draw_split_nodes(ax, pos_g, node_roles, node_sizes, dc_bus=None):
    """Draw nodes whose colour shows every role at that bus.

    node_roles: {node: [colour, ...]} — one colour is a plain circle, two is a
    left/right half split, three a pie split. node_sizes uses the same point²
    scale as networkx so existing size logic carries over. The datacenter bus
    gets a red ring.
    """
    from matplotlib.patches import Circle, Wedge

    xs = [p[0] for p in pos_g.values()]
    ys = [p[1] for p in pos_g.values()]
    span = max(max(xs) - min(xs), max(ys) - min(ys)) or 2.0
    ax.set_aspect("equal")
    base_r = span * 0.038

    for n, colors in node_roles.items():
        x, y = pos_g[n]
        r = base_r * (node_sizes.get(n, 600) / 600.0) ** 0.5
        if len(colors) == 1:
            ax.add_patch(Circle((x, y), r, facecolor=colors[0],
                                edgecolor="none", zorder=2))
        else:
            arc = 360.0 / len(colors)
            for i, c in enumerate(colors):
                ax.add_patch(Wedge((x, y), r, 90 + i * arc, 90 + (i + 1) * arc,
                                   facecolor=c, edgecolor="white",
                                   linewidth=0.6, zorder=2))
        if dc_bus is not None and n == dc_bus:
            ax.add_patch(Circle((x, y), r * 1.18, fill=False, edgecolor="red",
                                linewidth=2.5, zorder=3))


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
    nx.draw_networkx_labels(Gg, pos_g, ax=ax, labels={n: str(n) for n in Gg.nodes},
                            font_color="white", font_weight="bold", font_size=9)


def _congested_edge_colors(result, branches_list=None):
    if branches_list is None:
        branches_list = branches
    all_congested = set()
    for hour_lines in result.congested_lines:
        for idx in hour_lines:
            all_congested.add(idx)
    return ["red" if i in all_congested else "black" for i in range(len(branches_list))]


def _node_edge_colors(nodes, dc_bus):
    """Return per-node border colour: red for the datacenter node, none elsewhere."""
    return ["red" if n == dc_bus else "none" for n in nodes]


def draw_ed_result(result, gen_locations: dict, bat_locations: dict, ax,
                   _topo=None, dc_bus=None, dc_mw=0.0, load_buses=None):
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
    node_roles, node_sizes = {}, {}
    for n in Gg.nodes:
        colors, size = [], 600
        if n in gen_bus_set:
            gen_idx = [g for g, b in gen_locations.items() if b == n][0]
            colors.append(gen_node_color)
            size = 400 + result.dispatch[gen_idx, -1] * 0.5
        if n in bat_bus_set:
            colors.append("#2ca02c")
            size = max(size, 700)
        if (load_buses is not None and n in load_buses) or not colors:
            colors.append(load_node_color)
        node_roles[n], node_sizes[n] = colors, size

    _draw_split_nodes(ax, pos_g, node_roles, node_sizes, dc_bus=dc_bus)

    # Bus number inside node (white), status info offset above
    node_labels = {n: str(n) for n in Gg.nodes}
    nx.draw_networkx_labels(Gg, pos_g, ax=ax, labels=node_labels,
                            font_color="white", font_weight="bold", font_size=9)

    status = {}
    for gen_idx, bus in gen_locations.items():
        status[bus] = f"{result.dispatch[gen_idx, -1]:.0f} MW"
    for bat_idx, bus in bat_locations.items():
        soc = result.soc[bat_idx, -1]
        status[bus] = status.get(bus, "") + (f"\n" if bus in status else "") + f"B{bat_idx} {soc:.0f}MWh"
    if dc_bus is not None and dc_mw > 0:
        status[dc_bus] = status.get(dc_bus, "") + (f"\n" if dc_bus in status else "") + f"DC {dc_mw:.0f}MW"
    _draw_labels(Gg, pos_g, ax, {n: status[n] for n in status})

    gen_patch  = mpatches.Patch(color=gen_node_color,  label="Generator bus")
    load_patch = mpatches.Patch(color=load_node_color, label="Load / reference bus")
    bat_patch  = mpatches.Patch(color="#2ca02c",       label="Battery bus")
    cong_patch = mpatches.Patch(color="red",           label="Congested line")
    handles = [gen_patch, load_patch, bat_patch, cong_patch]
    if dc_bus is not None and dc_mw > 0:
        from matplotlib.lines import Line2D
        handles.append(Line2D([0], [0], marker="o", color="w", markerfacecolor="none",
                               markeredgecolor="red", markeredgewidth=2, markersize=10,
                               label="Datacenter load"))
    ax.legend(handles=handles, loc="lower left", fontsize=8, framealpha=0.9)
    ax.axis("off")


def draw_uc_result(result, gen_locations: dict, bat_locations: dict, ax,
                   _topo=None, dc_bus=None, dc_mw=0.0, load_buses=None, outages=None):
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
    node_roles, node_sizes = {}, {}
    for n in Gg.nodes:
        colors, size = [], 600
        if n in gen_bus_set:
            gen_idx = [g for g, b in gen_locations.items() if b == n][0]
            has_outage = bool(outages and gen_idx in outages and len(outages[gen_idx]) > 0)
            ever_committed = result.commitment[gen_idx, :].max() > 0.5
            if has_outage:
                colors.append(outage_node_color)
                size = 400 + result.dispatch[gen_idx, :].max() * 0.5 if ever_committed else 500
            elif ever_committed:
                colors.append(gen_node_color)
                size = 400 + result.dispatch[gen_idx, :].max() * 0.5
            else:
                colors.append("#aaaaaa")
                size = 500
        if n in bat_bus_set:
            colors.append("#2ca02c")
            size = max(size, 700)
        if (load_buses is not None and n in load_buses) or not colors:
            colors.append(load_node_color)
        node_roles[n], node_sizes[n] = colors, size

    _draw_split_nodes(ax, pos_g, node_roles, node_sizes, dc_bus=dc_bus)

    # Bus number inside node (white), status info offset above
    node_labels = {n: str(n) for n in Gg.nodes}
    nx.draw_networkx_labels(Gg, pos_g, ax=ax, labels=node_labels,
                            font_color="white", font_weight="bold", font_size=9)

    status = {}
    for gen_idx, bus in gen_locations.items():
        ever_committed = result.commitment[gen_idx, :].max() > 0.5
        has_outage = bool(outages and gen_idx in outages and len(outages[gen_idx]) > 0)
        label = f"peak {result.dispatch[gen_idx, :].max():.0f} MW" if ever_committed else "(off)"
        if has_outage:
            label += f"\noutage {len(outages[gen_idx])}h"
        status[bus] = label
    for bat_idx, bus in bat_locations.items():
        soc = result.soc[bat_idx, -1]
        status[bus] = status.get(bus, "") + (f"\n" if bus in status else "") + f"B{bat_idx} {soc:.0f}MWh"
    if dc_bus is not None and dc_mw > 0:
        status[dc_bus] = status.get(dc_bus, "") + (f"\n" if dc_bus in status else "") + f"DC {dc_mw:.0f}MW"
    _draw_labels(Gg, pos_g, ax, {n: status[n] for n in status})

    gen_patch    = mpatches.Patch(color=gen_node_color,    label="Generator bus (used this horizon)")
    off_patch    = mpatches.Patch(color="#aaaaaa",         label="Generator bus (never committed)")
    outage_patch = mpatches.Patch(color=outage_node_color, label="Generator bus (forced outage)")
    load_patch   = mpatches.Patch(color=load_node_color,   label="Load / reference bus")
    bat_patch    = mpatches.Patch(color="#2ca02c",         label="Battery bus")
    cong_patch   = mpatches.Patch(color="red",             label="Congested line")
    handles = [gen_patch, off_patch, load_patch, bat_patch, cong_patch]
    if outages:
        handles.insert(2, outage_patch)
    if dc_bus is not None and dc_mw > 0:
        from matplotlib.lines import Line2D
        handles.append(Line2D([0], [0], marker="o", color="w", markerfacecolor="none",
                               markeredgecolor="red", markeredgewidth=2, markersize=10,
                               label="Datacenter load"))
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
    """Return (max_stress, peak_hour) per line across all hours.

    max_stress: array of max |flow|/fbar
    peak_hour:  array of 1-indexed hour at which each line's max stress occurs
    """
    import numpy as np
    PTDF  = np.array(grid.PTDF)
    fbar  = np.array(grid.fbar).flatten()
    n_bus = PTDF.shape[1]
    max_stress = np.zeros(len(fbar))
    peak_hour  = np.ones(len(fbar), dtype=int)

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
                s = abs(flow[k]) / fbar[k]
                if s > max_stress[k]:
                    max_stress[k] = s
                    peak_hour[k]  = t + 1
    return max_stress, peak_hour


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

    stress, peak_hour = _line_stress(uc_result, gen_locations, bat_locs, grid)
    fbar   = np.array(grid.fbar).flatten()

    edge_list   = [(f, t) for f, t, _ in branches_list]
    edge_colors = [_stress_color(stress[i]) for i in range(len(branches_list))]
    edge_widths = [_stress_width(stress[i]) for i in range(len(branches_list))]
    nx.draw_networkx_edges(Gg, pos_g, ax=ax, edgelist=edge_list,
                           edge_color=edge_colors, width=edge_widths, arrows=False)

    for i, (f, t, _) in enumerate(branches_list):
        if fbar[i] >= 9000:
            continue
        x0, y0 = pos_g[f]
        x1, y1 = pos_g[t]
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        # perpendicular offset so label sits beside the line, not on it
        dx, dy = x1 - x0, y1 - y0
        length = (dx**2 + dy**2) ** 0.5 or 1
        ox, oy = -dy / length * 0.04, dx / length * 0.04
        pct = int(round(stress[i] * 100))
        lbl = f"{pct}%\nh{peak_hour[i]}" if stress[i] >= 0.70 else f"{pct}%"
        color = _stress_color(stress[i]) if stress[i] >= 0.70 else "#555555"
        import matplotlib.patheffects as _pe
        ax.text(mx + ox, my + oy, lbl, fontsize=7, ha="center", va="center",
                color=color, fontweight="bold" if stress[i] >= 0.70 else "normal",
                zorder=4, path_effects=[_pe.withStroke(linewidth=2, foreground="white")])

    load_buses = _grid_load_buses(grid)
    gen_bus_set = set(gen_locations.values())
    bat_bus_set = set(bat_locs.values())
    node_roles, node_sizes = {}, {}
    for n in Gg.nodes:
        colors, size = [], 500
        if n in gen_bus_set:
            g_idx = [g for g, b in gen_locations.items() if b == n][0]
            ever_committed = uc_result.commitment[g_idx, :].max() > 0.5
            colors.append(gen_node_color if ever_committed else "#aaaaaa")
            peak_output = uc_result.dispatch[g_idx, :].max()
            size = 400 + peak_output * 0.5 if ever_committed else 300
        if n in bat_bus_set:
            colors.append("#2ca02c")
            size = max(size, 700)
        if (load_buses is not None and n in load_buses) or not colors:
            colors.append(load_node_color)
        node_roles[n], node_sizes[n] = colors, size

    _draw_split_nodes(ax, pos_g, node_roles, node_sizes)


    # White bus number centered inside each node
    nx.draw_networkx_labels(Gg, pos_g, ax=ax, labels={n: str(n) for n in Gg.nodes},
                            font_color="white", font_weight="bold", font_size=9)

    # Black MW/battery status above nodes (with white halo via _draw_labels)
    status = {}
    for n in Gg.nodes:
        if n in gen_bus_set:
            g_idx = [g for g, b in gen_locations.items() if b == n][0]
            ever_committed = uc_result.commitment[g_idx, :].max() > 0.5
            peak_output = uc_result.dispatch[g_idx, :].max()
            status[n] = f"peak {peak_output:.0f}MW" if ever_committed else "(off)"
        elif n in bat_bus_set:
            b_indices = [b for b, bus in bat_locs.items() if bus == n]
            status[n] = ",".join(f"B{b}" for b in b_indices)
    if status:
        _draw_labels(Gg, pos_g, ax, status, font_size=7)

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

    gen_patch  = mpatches.Patch(color=gen_node_color,  label="Generator (used this horizon)")
    off_patch  = mpatches.Patch(color="#aaaaaa",        label="Generator (never committed)")
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


class _CommitShim:
    """Wrap an ED/siting result with a fixed commitment matrix so
    draw_siting_panel (which expects a `.commitment` attribute, as UC
    results have) also works for ED-refined quantum-siting candidates."""

    def __init__(self, result, commitment_list, T):
        self._r = result
        self.commitment = np.tile(np.array(commitment_list).reshape(-1, 1), (1, T))

    def __getattr__(self, name):
        return getattr(self._r, name)


def save_quantum_siting_gallery(result, gen_locations, grid, T, assets_file,
                                out_dir=None):
    """One network diagram per evaluated quantum-siting candidate, ranked by
    true cost — same panel (generator outputs, battery SOC, congested lines)
    as options 1-3, mirroring the dashboard's Power Flow gallery so the CLI
    (option 4) gets the same plot instead of terminal-only output.

    Returns the list of saved PNG paths, best-ranked first.
    """
    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
    os.makedirs(out_dir, exist_ok=True)

    topo = _build_grid_graph(grid)
    stem = assets_file.replace(".py", "")

    paths = []
    ranked = sorted(result.evaluated, key=lambda x: x[2])
    for rank, (bat_locs, commitment, true_cost, res_obj) in enumerate(ranked, start=1):
        panel_result = res_obj if hasattr(res_obj, "commitment") else _CommitShim(res_obj, commitment, T)
        fig, ax = plt.subplots(figsize=(9, 7))
        buses = tuple(bat_locs.values())
        draw_siting_panel(
            panel_result, gen_locations, bat_locs, grid, ax,
            title=f"Rank {rank} — Batteries at buses {buses}",
            subtitle=f"True cost: ${true_cost:,.0f}  |  line labels = max loading",
            _topo=topo,
        )
        path = os.path.join(out_dir, f"quantum_siting_{T}h_{stem}_rank{rank:02d}.png")
        plt.tight_layout()
        plt.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"Plot saved: {path}")
        paths.append(path)

    return paths


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

    fig, axes = plt.subplots(4, 1, figsize=(_time_axis_figwidth(T), 11), sharex=True)
    fig.suptitle(f"{opt_name} Overview | T={T}h | {assets_file}", fontsize=13, y=0.98)

    real_batteries = [
        (b, bat) for b, bat in enumerate(batteries)
        if bat["power_mw"] > 0 or bat["capacity_mwh"] > 0
    ]

    congested_hours = {t + 1 for t, lines in enumerate(result.congested_lines) if lines}
    for ax in axes:
        for h in congested_hours:
            ax.axvspan(h - 0.5, h + 0.5, color="#ffcccc", alpha=0.5, zorder=0)
    # Pale red background = congested hour. axvspan alone doesn't register with
    # ax.legend(), so add an explicit patch to every panel's legend (not just a
    # corner text note on panel 1) — the shading is applied to all four axes,
    # so each one needs its own explanation of what it means.
    cong_patch = mpatches.Patch(color="#ffcccc", alpha=0.5, label="Congested hour") if congested_hours else None

    def _legend_with_cong(ax, **kwargs):
        handles, labels = ax.get_legend_handles_labels()
        if cong_patch is not None:
            handles.append(cong_patch)
        ax.legend(handles=handles, **kwargs)

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
    _legend_with_cong(ax, loc="upper left", fontsize=8, ncol=2)
    ax.grid(axis="y", linestyle="--", alpha=0.35)

    # panel 2: battery net MW
    ax = axes[1]
    ax.axhline(0, color="black", linewidth=0.8)
    for b, bat in real_batteries:
        net = result.battery_charge[b, :T] - result.battery_discharge[b, :T]
        label = f"{bat['name']} (+charge / -discharge)"
        ax.plot(hours, net, color=bat_colors[b], linewidth=2, marker="o", markersize=4, label=label)
        ax.fill_between(hours, net, 0, where=[v > 0 for v in net],
                        alpha=0.15, color=bat_colors[b])
        ax.fill_between(hours, net, 0, where=[v < 0 for v in net],
                        alpha=0.25, color=bat_colors[b])
    ax.set_ylabel("MW", fontsize=10)
    ax.set_title("Battery Charge / Discharge  (positive = charging)", fontsize=10)
    if real_batteries:
        _legend_with_cong(ax, loc="lower left", fontsize=8)
    else:
        ax.text(0.5, 0.5, "No batteries in this use case", transform=ax.transAxes,
                ha="center", va="center", fontsize=10, color="#888888")
    ax.grid(axis="y", linestyle="--", alpha=0.35)

    # panel 3: battery SOC
    ax = axes[2]
    for b, bat in real_batteries:
        soc = result.soc[b, :T]
        cap = bat["capacity_mwh"]
        ax.plot(hours, soc, color=bat_colors[b], linewidth=2, marker="o", markersize=4,
                label=f"{bat['name']} (cap {cap} MWh)")
        ax.axhline(cap, color=bat_colors[b], linewidth=0.8, linestyle="--", alpha=0.5)
    ax.set_ylabel("SOC (MWh)", fontsize=10)
    ax.set_title("Battery State of Charge", fontsize=10)
    if real_batteries:
        _legend_with_cong(ax, loc="lower left", fontsize=8)
    else:
        ax.text(0.5, 0.5, "No batteries in this use case", transform=ax.transAxes,
                ha="center", va="center", fontsize=10, color="#888888")
    ax.grid(axis="y", linestyle="--", alpha=0.35)

    # panel 4: hourly cost
    ax = axes[3]
    ax.bar(hours, result.hourly_costs[:T], color="#7f7f7f", alpha=0.75, width=max(0.15, min(0.7, 60.0 / max(T, 1))))
    ax.set_ylabel("Cost ($)", fontsize=10)
    ax.set_title("Hourly Generation Cost", fontsize=10)
    if cong_patch is not None:
        ax.legend(handles=[cong_patch], loc="upper left", fontsize=8)
    ax.grid(axis="y", linestyle="--", alpha=0.35)

    if congested_hours:
        axes[0].annotate(
            _format_congested_hours(congested_hours),
            xy=(0.99, 0.97), xycoords="axes fraction",
            fontsize=7.5, color="#cc0000", va="top", ha="right",
        )

    _set_hour_axis(ax, T, xlabel="Hour")
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

    bar_width = max(0.15, min(0.8, 60.0 / max(T_d, 1)))
    fig, ax = plt.subplots(figsize=(_time_axis_figwidth(T_d, base=11.0, min_width=11.0, max_width=32.0), 5))
    bottom = np.zeros(T_d)
    for idx, (label, color) in zip(bus_indices, zip(bus_labels, bus_colors)):
        if idx < demand.shape[0]:
            ax.bar(hours, demand[idx], bottom=bottom, label=label,
                   color=color, alpha=0.75, width=bar_width)
            bottom += demand[idx]

    ax.plot(hours, total, color="black", linewidth=2, marker="o", markersize=4,
            label="Total demand")
    ax.set_ylabel("Demand (MW)", fontsize=11)
    ax.set_title(f"{T_d}-Hour Demand Profile", fontsize=13, pad=12)
    _set_hour_axis(ax, T_d, xlabel="Hour")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(axis="y", linestyle="--", alpha=0.4)

    filename = os.path.join(out_dir, "demand_profile_24h.png")
    plt.tight_layout()
    plt.savefig(filename, dpi=150)
    plt.close(fig)
    print(f"Plot saved: {filename}")
    return filename


def save_runtime_breakdown(runtime_phases: dict, opt_name: str, T: int,
                           assets_file: str, out_dir=None, tag: str = ""):
    """Stacked bar chart of per-phase wall time.

    runtime_phases: ordered {phase_label: seconds}. Total bar height = wall time.
    tag: optional run variant (e.g. backend "Qiskit (CPU)") — shown in the title
    and appended to the filename so variants don't overwrite each other.
    Returns the saved filename.
    """
    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
    os.makedirs(out_dir, exist_ok=True)

    phases = [(label, max(0.0, float(sec))) for label, sec in runtime_phases.items()]
    total = sum(sec for _, sec in phases)

    phase_colors = ["#5b8dd9", "#e05c3a", "#2ca02c", "#9467bd", "#ff7f0e",
                    "#8c564b", "#17becf", "#bcbd22"]

    fig, ax = plt.subplots(figsize=(3.4, 7))
    bottom = 0.0
    for i, (label, sec) in enumerate(phases):
        pct = 100.0 * sec / total if total > 0 else 0.0
        ax.bar([0], [sec], bottom=[bottom], width=0.5,
               color=phase_colors[i % len(phase_colors)],
               label=f"{label} — {sec:.1f}s ({pct:.0f}%)")
        bottom += sec

    ax.set_xlim(-0.5, 0.5)
    ax.set_xticks([])
    ax.set_ylabel("Wall time (s)", fontsize=10)
    title_tag = f" | {tag}" if tag else ""
    ax.set_title(f"Runtime Breakdown — {opt_name}{title_tag}\n"
                 f"T={T}h | {assets_file} | total {total:.1f}s",
                 fontsize=10, pad=10)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.03), fontsize=8,
              framealpha=0.9, ncol=1)
    ax.grid(axis="y", linestyle="--", alpha=0.35)

    file_tag = "_" + "".join(c if c.isalnum() else "_" for c in tag.lower()) if tag else ""
    filename = os.path.join(
        out_dir,
        f"runtime_breakdown_{opt_name.lower().replace(' ', '_')}"
        f"{file_tag}_{T}h_{assets_file.replace('.py', '')}.png",
    )
    plt.tight_layout()
    plt.savefig(filename, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Plot saved: {filename}")
    return filename


def save_plot(result, opt_name: str, T: int, assets_file: str, grid=None,
              generators=None, bat_locs=None, batteries=None, dc_bus=None, dc_mw=0.0,
              outages=None):
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

    # Zero-power/zero-capacity batteries are placeholders (e.g. the "null"
    # dummy in no-battery use cases, kept only so solver arrays aren't empty)
    # — drop them here so they don't draw as a real battery bus on the plot.
    if batteries is not None:
        bat_locations = {
            b: bus for b, bus in bat_locations.items()
            if b < len(batteries)
            and (batteries[b]["power_mw"] > 0 or batteries[b]["capacity_mwh"] > 0)
        }

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
                       dc_bus=dc_bus, dc_mw=dc_mw, load_buses=_grid_load_buses(grid),
                       outages=outages)
    else:
        fig, ax = plt.subplots(figsize=(10, 8))
        draw_ed_result(result, gen_locations, bat_locations, ax, _topo=_topo,
                       dc_bus=dc_bus, dc_mw=dc_mw, load_buses=_grid_load_buses(grid))

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
    for (f, t), lbl in constrained.items():
        x = (pos[f][0] + pos[t][0]) / 2
        y = (pos[f][1] + pos[t][1]) / 2
        ax.text(x, y, lbl, fontsize=8, ha="center", va="center", color="black", zorder=4)

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
