"""
Gradio dashboard — browser UI over the same solvers main.py drives.

Layout (Mockup C): one tab per problem (ED, UC, Battery Siting MIP, Quantum
Siting). Inside a tab, all inputs sit in one compact control bar on top;
outputs live in sub-tabs below (Results / Plots / Terminal, plus Power Flow
and Runtime for Quantum Siting). A run-history strip at the bottom of the
page lets you reload the output of any earlier run.

Launch:  .venv/bin/python dashboard.py   →  http://127.0.0.1:7860

Settings are persisted to outputs/dashboard_settings.json on every run and
restored on the next launch. Each run's terminal output is saved to
outputs/dashboard_runs/ and indexed in outputs/dashboard_history.json.
"""

from __future__ import annotations

import contextlib
import copy
import glob
import io
import json
import os
import re
import shutil
import time
import traceback
from datetime import datetime

import gradio as gr
import numpy as np
import pandas as pd

import main as cli
from solvers.results import QuantumSitingResult, SitingMIPResult

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "outputs")
RUNS_DIR = os.path.join(OUT_DIR, "dashboard_runs")
POWERFLOW_DIR = os.path.join(OUT_DIR, "powerflow")
SETTINGS_PATH = os.path.join(OUT_DIR, "dashboard_settings.json")
HISTORY_PATH = os.path.join(OUT_DIR, "dashboard_history.json")

# Battery Siting (MIP)'s "Candidate ranking" table can otherwise show every
# Benders-explored candidate (100+ rows for larger grids); capping what's
# rendered keeps tab-switch rendering fast. Full ranking is still saved to
# outputs/dashboard_history.json regardless of this cap.
_SITING_TABLE_ROW_CAP = 30

# Short labels so dropdowns don't get cut off. info= renders as inline text
# under the label (not a tooltip), so these stay to a few words — the full
# explanations live in the markdown blurb under the Quantum Siting control row.
BACKEND_CHOICES = ["Qiskit", "Aer TN"]
BACKEND_INFO = "local sim vs. tensor-network"
SAMPLING_CHOICES = ["Local (Qiskit)", "IonQ (qBraid29sim)", "IonQ (qBraid29sim, noise)"]
SAMPLING_INFO = "where the final shot sample runs"

# Old long labels from earlier saved settings → new short labels
_LABEL_MIGRATION = {
    "Qiskit (GPU)": "Qiskit",
    "Qiskit (CPU)": "Qiskit",
    "Qiskit (VQA, local simulator)": "Qiskit",
    # Old single-dropdown era had an "IonQ (qBraid29sim)" *backend* choice —
    # that implied training via Qiskit statevector, so migrate the VQA-backend
    # setting to "Qiskit" (the sampling setting picks up "IonQ (qBraid29sim)"
    # on its own, since that string already matches a SAMPLING_CHOICES entry).
    "IonQ (qBraid29sim)": "Qiskit",
    "IonQ (qBraid)": "Qiskit",
    "ED dispatch (fix commitment and placement)": "ED",
    "Full UC re-solve (fix placement only)": "UC",
    "zeros — paper sim default": "zeros",
    "random — paper IonQ hardware default": "random",
    "sdp — LP-relaxation warm start": "sdp",
}

# Old long IonQ label → current canonical sampling-backend label.
_SAMPLING_LABEL_MIGRATION = {
    "IonQ (qBraid)": "IonQ (qBraid29sim)",
    "Local": "Local (Qiskit)",
}


def _default_backend() -> str:
    return "Qiskit"


def _default_sampling() -> str:
    return "Local (Qiskit)"


def _migrate_sampling_label(value, default: str) -> str:
    if value in SAMPLING_CHOICES:
        return value
    migrated = _SAMPLING_LABEL_MIGRATION.get(value)
    return migrated if migrated in SAMPLING_CHOICES else default


def _migrate_label(value, choices: list[str], default: str) -> str:
    if value in choices:
        return value
    migrated = _LABEL_MIGRATION.get(value)
    return migrated if migrated in choices else default


# ---------------------------------------------------------------------------
# Settings persistence
# ---------------------------------------------------------------------------

def _load_settings() -> dict:
    try:
        with open(SETTINGS_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_settings(tab: str, values: dict) -> None:
    settings = _load_settings()
    settings[tab] = values
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)


_SETTINGS = _load_settings()


def _setting(tab: str, key: str, default):
    return _SETTINGS.get(tab, {}).get(key, default)


# ---------------------------------------------------------------------------
# Run history (outputs/dashboard_history.json, newest first)
# ---------------------------------------------------------------------------

def _load_history() -> list[dict]:
    try:
        with open(HISTORY_PATH) as f:
            return json.load(f)
    except Exception:
        return []


def _record_history(record: dict) -> None:
    history = _load_history()
    history.insert(0, record)
    with open(HISTORY_PATH, "w") as f:
        json.dump(history[:100], f, indent=2)


def _history_table() -> pd.DataFrame:
    rows = [
        {
            "When": r.get("when", ""),
            "Problem": r.get("problem", ""),
            "Use case": r.get("use_case", ""),
            "Assets": r.get("assets_file", ""),
            "T": r.get("T", ""),
            "Backend": r.get("backend", ""),
            "Runtime (s)": f"{r['runtime_s']:.1f}" if r.get("runtime_s") is not None else "",
            "Result": r.get("summary", ""),
        }
        for r in _load_history()
    ]
    cols = ["When", "Problem", "Use case", "Assets", "T", "Backend", "Runtime (s)", "Result"]
    return pd.DataFrame(rows, columns=cols)


def _on_history_select(evt: gr.SelectData):
    """Load the selected run's terminal log and plots into the history viewer."""
    history = _load_history()
    row = evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index
    if row is None or row >= len(history):
        return "", []
    rec = history[row]
    text = ""
    try:
        with open(rec["log"]) as f:
            text = f.read()
    except Exception:
        text = f"(log file missing: {rec.get('log')})"
    plots = [p for p in rec.get("plots", []) if os.path.exists(p)]
    return text, plots


# ---------------------------------------------------------------------------
# Use case / assets discovery
# ---------------------------------------------------------------------------

def list_use_cases() -> list[str]:
    base = os.path.join(BASE_DIR, "use_cases")
    return sorted(
        d for d in os.listdir(base)
        if os.path.isdir(os.path.join(base, d)) and not d.startswith("_")
    )



# Asset files hidden from all dropdowns/prompts (judge-facing build); the
# files themselves are untouched in use_cases/ — remove entries here to
# bring them back.
_HIDDEN_ASSETS = {"4batt_dcbus1.py", "4batt_dcbus2.py", "4batt_dcbus5.py"}


def list_assets(use_case: str) -> list[str]:
    found = sorted(glob.glob(os.path.join(BASE_DIR, "use_cases", use_case, "*batt*.py")))
    return [os.path.basename(p) for p in found if os.path.basename(p) not in _HIDDEN_ASSETS]


def _max_hours_for(use_case: str, assets_file: str | None) -> int:
    """How many hours of demand data this use case's grid actually has
    (e.g. ieee14 is a week/168h; other cases may still be 24h)."""
    if not use_case or not assets_file:
        return 24
    try:
        grid, _, _, _, _ = _load_case(use_case, assets_file)
        return int(grid.power_demand.shape[1])
    except Exception:
        return 24


def _on_use_case_change(use_case: str):
    choices = list_assets(use_case)
    assets_default = choices[0] if choices else None
    max_hours = _max_hours_for(use_case, assets_default)
    return (
        gr.update(choices=choices, value=assets_default),
        gr.update(maximum=max_hours),
    )


# ---------------------------------------------------------------------------
# Shared run plumbing
# ---------------------------------------------------------------------------

_base_grid_cache: dict[str, object] = {}


def _base_grid(use_case: str, grid_mod) -> object:
    """Construct grid_mod.Case() once per use case and reuse it thereafter.

    Each tab's control bar and every run call _load_case for the same
    use case, and Case() construction prints and does real work (PTDF
    build), so without caching it re-runs on every tab load and every run.
    Returns a shallow copy with its own power_demand array so callers can
    inject the datacenter load without mutating the cached base.
    """
    if use_case not in _base_grid_cache:
        grid0 = grid_mod.Case()
        cli.extend_to_full_week(grid0)
        _base_grid_cache[use_case] = grid0
    base = _base_grid_cache[use_case]
    grid = copy.copy(base)
    grid.power_demand = np.array(base.power_demand, copy=True)
    return grid


def _load_case(use_case: str, assets_file: str):
    """Load grid/assets/locations and inject the datacenter load (mirrors main.main)."""
    use_case_path = os.path.join(BASE_DIR, "use_cases", use_case)
    assets_path = os.path.join(use_case_path, assets_file)
    assets_file_name, grid_mod, assets_mod, loc_mod = cli.load_modules(
        use_case, use_case_path, assets_path
    )
    grid = _base_grid(use_case, grid_mod)

    # Weather scenario: hourly load multiplier applied before datacenter
    # injection (the datacenter is a flat load, not scaled by weather or the
    # daily demand curve). Only bites during the first len(HEAT_FACTORS)
    # hours of any run, mirroring how OUTAGES models a single dated event
    # rather than a recurring pattern.
    heat_factors = getattr(assets_mod, "HEAT_FACTORS", None)
    if heat_factors is not None:
        n = min(len(heat_factors), grid.power_demand.shape[1])
        grid.power_demand[:, :n] *= np.array(heat_factors[:n], dtype=float)[np.newaxis, :]

    dc_bus = getattr(assets_mod, "DATACENTER_BUS", None)
    dc_mw = float(getattr(assets_mod, "DATACENTER_MW", 0))
    if dc_bus is not None and dc_mw > 0:
        grid.power_demand[dc_bus - 1, :] += dc_mw
    return grid, assets_mod, loc_mod, dc_bus, dc_mw


_PLOT_SAVED_RE = re.compile(r"Plot saved: (.+\.png)")


def _plots_from_log(text: str) -> list[str]:
    return [p for p in _PLOT_SAVED_RE.findall(text) if os.path.exists(p)]


def _save_run_log(problem: str, text: str) -> str:
    os.makedirs(RUNS_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(RUNS_DIR, f"{problem}_{stamp}.txt")
    with open(path, "w") as f:
        f.write(text)
    return path


def _execute(problem: str, opt_name: str, use_case: str, assets_file: str, T: int,
             solve_fn):
    """Run solve_fn under captured stdout; return (result, terminal_text, plots, log_path, elapsed).

    solve_fn(grid, assets_mod, loc_mod, dc_bus, dc_mw) -> result object.
    On failure result is None and the traceback is in terminal_text; elapsed is
    None if solve_fn never started/finished (e.g. _load_case itself raised).

    elapsed is wall-clock solver time in seconds — computed here already (it
    was previously printed to the terminal log and then discarded instead of
    being persisted anywhere), now returned so callers can pass it into
    _finish_run and have it land in outputs/dashboard_history.json instead of
    being lost once the run completes.
    """
    buf = io.StringIO()
    result = None
    elapsed = None
    try:
        with contextlib.redirect_stdout(buf):
            grid, assets_mod, loc_mod, dc_bus, dc_mw = _load_case(use_case, assets_file)
            generators = assets_mod.GENERATORS
            batteries = assets_mod.BATTERIES
            cli.print_header(opt_name, T, use_case, assets_file, generators,
                             batteries, dc_bus, dc_mw)
            t0 = time.perf_counter()
            result = solve_fn(grid, assets_mod, loc_mod, dc_bus, dc_mw)
            elapsed = time.perf_counter() - t0
            print(f"Solver time: {elapsed:.1f}s")
            cli.print_results(result, opt_name, T, generators, batteries)
    except Exception:
        buf.write("\n" + traceback.format_exc())

    text = buf.getvalue()
    log_path = _save_run_log(problem, text)
    text += f"\n[run log saved: {log_path}]"
    return result, text, _plots_from_log(text), log_path, elapsed


def _snapshot_plots(paths: list[str], snap_dir: str) -> list[str]:
    """Copy plots into a per-run folder; return the copies' paths."""
    copies = []
    for p in paths:
        if not os.path.exists(p):
            continue
        try:
            os.makedirs(snap_dir, exist_ok=True)
            dest = os.path.join(snap_dir, os.path.basename(p))
            shutil.copy2(p, dest)
            copies.append(dest)
        except Exception:
            copies.append(p)  # fall back to the original path
    return copies


def _finish_run(problem: str, use_case: str, assets_file: str, T: int,
                summary_plain: str, log_path: str, plots: list[str],
                key: dict | None = None, extra: dict | None = None,
                runtime_s: float | None = None) -> pd.DataFrame:
    """Record the run in history and return the refreshed history table.

    key: the exact input settings — used to auto-load cached results when the
    dashboard reopens or inputs match a previous run.

    runtime_s: wall-clock solver time from _execute()'s `elapsed` return value
    (None if the run failed before a runtime could be measured). Persisted so
    later analysis (e.g. cross-scenario solver comparison tables) can read
    runtimes straight out of outputs/dashboard_history.json instead of having
    to re-run everything from scratch to recover timing data.

    Plot filenames only encode T + assets file, so different input combinations
    overwrite each other in outputs/. Snapshot this run's plots into a per-run
    folder so cached records keep showing the right images.
    """
    snap_dir = log_path[:-4] if log_path.endswith(".txt") else log_path + "_plots"
    plots = _snapshot_plots(plots, snap_dir)
    if extra and extra.get("runtime_chart"):
        snapped = _snapshot_plots([extra["runtime_chart"]], snap_dir)
        extra = {**extra, "runtime_chart": snapped[0] if snapped else None}

    record = {
        "when": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "problem": problem,
        "use_case": use_case,
        "assets_file": assets_file,
        "T": T,
        "runtime_s": runtime_s,
        "summary": summary_plain,
        "log": log_path,
        "plots": plots,
        "key": key,
    }
    if extra:
        record.update(extra)
    _record_history(record)
    return _history_table()


# ---------------------------------------------------------------------------
# Cached-run lookup — auto-load results for settings that were already run
# ---------------------------------------------------------------------------

def _find_cached(problem: str, key: dict) -> dict | None:
    for r in _load_history():
        if r.get("problem") == problem and r.get("key") == key:
            return r
    return None


def _cached_view(problem: str, key: dict):
    """Return (summary, terminal, plots) for a cached run, or None."""
    rec = _find_cached(problem, key)
    if rec is None:
        return None
    try:
        with open(rec["log"]) as f:
            text = f.read()
    except Exception:
        text = f"(log file missing: {rec.get('log')})"
    text = f"[cached run from {rec['when']}]\n\n" + text
    plots = [p for p in rec.get("plots", []) if os.path.exists(p)]
    if rec.get("summary") == "FAILED":
        summary = (f"### ⚠️ Last run with these settings **failed** ({rec['when']}) "
                   f"— see Terminal sub-tab. Press ▶ Run to retry.")
    else:
        summary = (f"### ✅ Already run — {rec.get('summary', '')}  \n"
                   f"*Loaded from {rec['when']}. Press ▶ Run to re-run.*")
    return summary, text, plots, rec


_NOT_RUN = "*Not run yet with these settings.*"


def _ed_key(use_case, assets_file, T, line_losses=False):
    return {"use_case": use_case, "assets_file": assets_file, "T": int(T),
            "line_losses": bool(line_losses)}


def _cached_ed(use_case, assets_file, T, line_losses=False):
    v = _cached_view("ED", _ed_key(use_case, assets_file, T, line_losses))
    return (v[0], v[1], v[2]) if v else (_NOT_RUN, "", [])


def _cached_uc(use_case, assets_file, T, line_losses=False):
    v = _cached_view("UC", _ed_key(use_case, assets_file, T, line_losses))
    return (v[0], v[1], v[2]) if v else (_NOT_RUN, "", [])


_PROBLEM_LABELS = ["Economic Dispatch", "Unit Commitment"]


def _cached_dispatch(problem_type, use_case, assets_file, T, line_losses=False):
    if problem_type == "Unit Commitment":
        return _cached_uc(use_case, assets_file, T, line_losses)
    return _cached_ed(use_case, assets_file, T, line_losses)


def _siting_key(use_case, assets_file, T, time_limit, line_losses=False, loss_top_k=10):
    return {"use_case": use_case, "assets_file": assets_file, "T": int(T),
            "time_limit": float(time_limit), "line_losses": bool(line_losses),
            "loss_top_k": int(loss_top_k)}


def _cached_siting(use_case, assets_file, T, time_limit, line_losses=False, loss_top_k=10):
    v = _cached_view("Siting", _siting_key(use_case, assets_file, T, time_limit,
                                           line_losses, loss_top_k))
    if not v:
        return _NOT_RUN, "", [], pd.DataFrame()
    summary, text, plots, rec = v
    table = pd.DataFrame(rec.get("table_rows", []))
    return summary, text, plots, table


def _quantum_key(use_case, assets_file, T, backend_label, sampling_label, n_candidates,
                 second_stage_label, warm_start_label, line_losses=False):
    return {"use_case": use_case, "assets_file": assets_file, "T": int(T),
            "backend": backend_label, "sampling": sampling_label,
            "n_candidates": int(n_candidates),
            "second_stage": second_stage_label, "warm_start": warm_start_label,
            "line_losses": bool(line_losses)}


def _cached_quantum(use_case, assets_file, T, backend_label, sampling_label, n_candidates,
                    second_stage_label, warm_start_label, line_losses=False):
    key = _quantum_key(use_case, assets_file, T, backend_label, sampling_label, n_candidates,
                       second_stage_label, warm_start_label, line_losses)
    v = _cached_view("Quantum", key)
    if v is None:
        return _NOT_RUN, "", [], pd.DataFrame(), None
    summary, text, plots, rec = v
    table = pd.DataFrame(rec.get("table_rows", []))
    chart = rec.get("runtime_chart")
    if chart and not os.path.exists(chart):
        chart = None
    return summary, text, plots, table, chart


# ---------------------------------------------------------------------------
# Problem runners
# ---------------------------------------------------------------------------

def run_ed_tab(use_case: str, assets_file: str, T: float, force: bool = False,
              line_losses: bool = False):
    T = int(T)
    _save_settings("ed", {"use_case": use_case, "assets_file": assets_file, "T": T})

    if not force:
        cached = _cached_view("ED", _ed_key(use_case, assets_file, T, line_losses))
        if cached is not None:
            return cached[0], cached[1], cached[2], _history_table()

    def solve(grid, assets_mod, loc_mod, dc_bus, dc_mw):
        from solvers.ed import run_ed
        result = run_ed(grid, assets_mod.GENERATORS, assets_mod.BATTERIES,
                        loc_mod.GENERATOR_LOCATIONS, loc_mod.BATTERY_LOCATIONS, T,
                        line_losses=line_losses)
        cli.save_plot(result, "ED", T, assets_file, grid=grid,
                      generators=assets_mod.GENERATORS,
                      bat_locs=loc_mod.BATTERY_LOCATIONS, batteries=assets_mod.BATTERIES,
                      dc_bus=dc_bus, dc_mw=dc_mw)
        cli.save_overview(result, "ED", T, assets_file,
                          assets_mod.GENERATORS, assets_mod.BATTERIES, grid)
        return result

    result, text, plots, log_path, elapsed = _execute("ed", "ED", use_case, assets_file, T, solve)
    if result is None:
        gr.Warning("ED run failed — open the Terminal sub-tab for the traceback.")
        summary, plain = "### Run failed — see Terminal sub-tab", "FAILED"
    else:
        plain = f"${result.total_cost:,.2f} total"
        summary = f"### ED — total cost **${result.total_cost:,.2f}** over {T}h"
        if line_losses and result.total_losses_mw:
            summary += f" (losses: {sum(result.total_losses_mw):,.1f} MWh)"
    history = _finish_run("ED", use_case, assets_file, T, plain, log_path, plots,
                          key=_ed_key(use_case, assets_file, T, line_losses),
                          runtime_s=elapsed)
    return summary, text, plots, history


def run_uc_tab(use_case: str, assets_file: str, T: float, force: bool = False,
              line_losses: bool = False):
    T = int(T)
    _save_settings("uc", {"use_case": use_case, "assets_file": assets_file, "T": T})

    if not force:
        cached = _cached_view("UC", _ed_key(use_case, assets_file, T, line_losses))
        if cached is not None:
            return cached[0], cached[1], cached[2], _history_table()

    def solve(grid, assets_mod, loc_mod, dc_bus, dc_mw):
        from solvers.uc import run_uc
        outages = getattr(assets_mod, "OUTAGES", None)
        result = run_uc(grid, assets_mod.GENERATORS, assets_mod.BATTERIES,
                        loc_mod.BATTERY_LOCATIONS, T, outages=outages,
                        line_losses=line_losses)
        cli.save_plot(result, "UC", T, assets_file, grid=grid,
                      generators=assets_mod.GENERATORS,
                      bat_locs=loc_mod.BATTERY_LOCATIONS, batteries=assets_mod.BATTERIES,
                      dc_bus=dc_bus, dc_mw=dc_mw, outages=outages)
        cli.save_overview(result, "UC", T, assets_file,
                          assets_mod.GENERATORS, assets_mod.BATTERIES, grid)
        return result

    result, text, plots, log_path, elapsed = _execute("uc", "UC", use_case, assets_file, T, solve)
    if result is None:
        gr.Warning("UC run failed — open the Terminal sub-tab for the traceback.")
        summary, plain = "### Run failed — see Terminal sub-tab", "FAILED"
    else:
        plain = f"${result.total_cost:,.2f} total"
        summary = f"### UC — total cost **${result.total_cost:,.2f}** over {T}h"
        if line_losses and result.total_losses_mw:
            summary += f" (losses: {sum(result.total_losses_mw):,.1f} MWh)"
    history = _finish_run("UC", use_case, assets_file, T, plain, log_path, plots,
                          key=_ed_key(use_case, assets_file, T, line_losses),
                          runtime_s=elapsed)
    return summary, text, plots, history


def run_dispatch_tab(problem_type: str, use_case: str, assets_file: str, T: float,
                     force: bool = False, line_losses: bool = False):
    """Dispatches to run_ed_tab or run_uc_tab based on the merged tab's dropdown."""
    _save_settings("dispatch", {"problem_type": problem_type})
    if problem_type == "Unit Commitment":
        return run_uc_tab(use_case, assets_file, T, force, line_losses)
    return run_ed_tab(use_case, assets_file, T, force, line_losses)


def run_siting_tab(use_case: str, assets_file: str, T: float, time_limit: float,
                   line_losses: bool = False, loss_top_k: float = 10,
                   force: bool = False):
    T = int(T)
    loss_top_k = int(loss_top_k)
    _save_settings("siting", {"use_case": use_case, "assets_file": assets_file,
                              "T": T, "time_limit": time_limit,
                              "line_losses": line_losses, "loss_top_k": loss_top_k})

    if not force:
        cached = _cached_view("Siting", _siting_key(use_case, assets_file, T, time_limit,
                                                     line_losses, loss_top_k))
        if cached is not None:
            summary, text, plots, rec = cached
            table = pd.DataFrame(rec.get("table_rows", [])[:_SITING_TABLE_ROW_CAP])
            return summary, text, plots, table, _history_table()

    def solve(grid, assets_mod, loc_mod, dc_bus, dc_mw):
        from solvers.siting_benders import run_siting_benders
        outages = getattr(assets_mod, "OUTAGES", None)
        result = run_siting_benders(grid, assets_mod.GENERATORS, assets_mod.BATTERIES,
                                    T, time_limit_s=float(time_limit),
                                    line_losses=line_losses, loss_top_k=loss_top_k,
                                    outages=outages)
        if result.runtime_phases:
            from plots import save_runtime_breakdown
            save_runtime_breakdown(result.runtime_phases, "Siting", T, assets_file)
        plot_result = result.uc_result if isinstance(result, SitingMIPResult) else result
        plot_bat_locs = result.bat_locs if isinstance(result, SitingMIPResult) else loc_mod.BATTERY_LOCATIONS
        cli.save_plot(plot_result, "Siting", T, assets_file, grid=grid,
                      generators=assets_mod.GENERATORS,
                      bat_locs=plot_bat_locs, batteries=assets_mod.BATTERIES,
                      dc_bus=dc_bus, dc_mw=dc_mw)
        cli.save_overview(plot_result, "Siting", T, assets_file,
                          assets_mod.GENERATORS, assets_mod.BATTERIES, grid)
        return result

    result, text, plots, log_path, elapsed = _execute("siting", "Siting", use_case,
                                             assets_file, T, solve)
    table = pd.DataFrame()
    extra = None
    if result is None:
        gr.Warning("Siting run failed — open the Terminal sub-tab for the traceback.")
        summary, plain = "### Run failed — see Terminal sub-tab", "FAILED"
    else:
        label = {"timelimit": "time limit hit",
                 "stalled": "stopped early — no improvement"}.get(
            result.scip_status, "optimal")
        plain = f"buses {result.bus_tuple} · ${result.total_cost:,.0f}"
        summary = (f"### Siting MIP — best placement **buses {result.bus_tuple}** "
                   f"at **${result.total_cost:,.0f}** ({label})")
        if line_losses and result.uc_result.total_losses_mw:
            summary += f"  \n(losses: {sum(result.uc_result.total_losses_mw):,.1f} MWh, top {loss_top_k} candidates re-solved)"
        if result.ranked:
            full_table = pd.DataFrame({
                "Rank": list(range(1, len(result.ranked) + 1)),
                "Buses": [str(bus_tuple) for bus_tuple, _ in result.ranked],
                "Total cost ($)": [f"{cost:,.0f}" for _, cost in result.ranked],
            })
            # Full ranking (every Benders-explored candidate, can run to 100+
            # rows) is kept in history for later analysis; only the cheapest
            # _SITING_TABLE_ROW_CAP are shown here — a Dataframe that large
            # was visibly slow to paint when switching into this tab.
            extra = {"table_rows": full_table.to_dict("records")}
            table = full_table.head(_SITING_TABLE_ROW_CAP)
    history = _finish_run("Siting", use_case, assets_file, T, plain, log_path, plots,
                          key=_siting_key(use_case, assets_file, T, time_limit,
                                          line_losses, loss_top_k),
                          extra=extra, runtime_s=elapsed)
    return summary, text, plots, table, history


class _CommitShim:
    """Wrap an EDResult with a fixed commitment matrix so draw_siting_panel works."""

    def __init__(self, ed_result, commitment_list, T):
        self._r = ed_result
        self.commitment = np.tile(np.array(commitment_list).reshape(-1, 1), (1, T))

    def __getattr__(self, name):
        return getattr(self._r, name)


def _render_powerflow_gallery(result: QuantumSitingResult, grid, generators,
                              T: int) -> list[tuple[str, str]]:
    """One network diagram per evaluated candidate, ranked by true cost.

    Returns [(png_path, caption), ...] for a gr.Gallery.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from plots import _build_grid_graph, draw_siting_panel

    os.makedirs(POWERFLOW_DIR, exist_ok=True)
    for old in glob.glob(os.path.join(POWERFLOW_DIR, "candidate_rank*.png")):
        os.remove(old)

    topo = _build_grid_graph(grid)
    gen_locations = {g: gen["bus"] for g, gen in enumerate(generators)}

    entries = []
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
        path = os.path.join(POWERFLOW_DIR, f"candidate_rank{rank:02d}.png")
        plt.tight_layout()
        plt.savefig(path, dpi=130, bbox_inches="tight")
        plt.close(fig)
        entries.append((path, f"Rank {rank} — buses {buses} — ${true_cost:,.0f}"))
    return entries


def _load_powerflow_gallery() -> list[str]:
    return sorted(glob.glob(os.path.join(POWERFLOW_DIR, "candidate_rank*.png")))


def _latest_runtime_chart() -> str | None:
    charts = glob.glob(os.path.join(OUT_DIR, "runtime_breakdown_*.png"))
    return max(charts, key=os.path.getmtime) if charts else None


def run_quantum_tab(use_case: str, assets_file: str, T: float, backend_label: str,
                    sampling_label: str, n_candidates: float, second_stage_label: str,
                    warm_start_label: str, max_time_s: float = 300,
                    ansatz_label: str = "Auto", line_losses: bool = False,
                    force: bool = False):
    T = int(T)
    n_candidates = int(n_candidates)
    if backend_label == "Qiskit":
        sim_method = "statevector"
    elif backend_label == "Aer TN":
        sim_method = "tensor_network"
    else:
        raise gr.Error(f"Unknown backend: {backend_label!r}")
    if sampling_label == "Local (Qiskit)":
        final_backend = "local"
    elif sampling_label == "IonQ (qBraid29sim)":
        final_backend = "ionq_qbraid"
    elif sampling_label == "IonQ (qBraid29sim, noise)":
        final_backend = "ionq_qbraid_noise"
    else:
        raise gr.Error(f"Unknown sampling backend: {sampling_label!r}")
    second_stage = "ed" if second_stage_label.startswith("ED") else "uc"
    warm_start = warm_start_label.split(" ")[0]
    backend_tag = backend_label if sampling_label == "Local (Qiskit)" else f"{backend_label} → {sampling_label}"
    _ansatz_map = {"Auto": "auto", "Butterfly": "butterfly", "Linear-chain HEA": "linear_chain"}
    ansatz = _ansatz_map.get(ansatz_label, "auto")

    # Preflight: fail fast with a dismissible popup instead of a long failed run
    if sim_method == "tensor_network":
        try:
            from solvers.quantum_siting import _AER_TN_AVAILABLE
            if not _AER_TN_AVAILABLE:
                raise gr.Error("Aer tensor-network simulator is not available — "
                               "install qiskit-aer with tensor-network support.")
        except ImportError:
            raise gr.Error("qiskit-aer is not installed.")
    if final_backend.startswith("ionq_qbraid"):
        try:
            from solvers.ionq_qbraid_backend import _load_token
            _load_token()
        except RuntimeError as e:
            raise gr.Error(str(e))
        except ImportError:
            raise gr.Error("qbraid is not installed. Run: pip install qbraid --break-system-packages")

    _save_settings("quantum", {
        "use_case": use_case, "assets_file": assets_file, "T": T,
        "backend": backend_label, "sampling": sampling_label, "n_candidates": n_candidates,
        "second_stage": second_stage_label, "warm_start": warm_start_label,
        "max_time_s": float(max_time_s), "ansatz": ansatz_label,
        "line_losses": line_losses,
    })

    if not force:
        c = _cached_quantum(use_case, assets_file, T, backend_label, sampling_label,
                            n_candidates, second_stage_label, warm_start_label, line_losses)
        if c[0] != _NOT_RUN:
            summary, text, plots, table, chart = c
            return (summary, text, plots, table, _load_powerflow_gallery(),
                    chart, _history_table())

    state = {}

    def solve(grid, assets_mod, loc_mod, dc_bus, dc_mw):
        from solvers.quantum_siting import run_quantum_siting, _AER_AVAILABLE, _AER_TN_AVAILABLE
        if sim_method == "tensor_network":
            print("Aer tensor-network simulator (MPS)")
        else:
            if _AER_AVAILABLE:
                print("Aer statevector: CPU")
            else:
                print("Aer: not installed — using Qiskit StatevectorSampler (CPU)")
        print(f"Ansatz: {ansatz_label}  |  Warm-start: {warm_start}")
        if final_backend.startswith("ionq_qbraid"):
            from solvers.ionq_qbraid_backend import DEVICE_ID, FREE_SIMULATOR_ID, NOISE_MODEL_ID
            noise_tag = f" with {NOISE_MODEL_ID} noise model" if final_backend == "ionq_qbraid_noise" else ""
            cost_tag = "free simulator" if DEVICE_ID == FREE_SIMULATOR_ID else "spends qBraid credits"
            print(f"IonQ (qBraid29sim): training locally above, final shots on device "
                  f"{DEVICE_ID!r}{noise_tag} (real job, {cost_tag})")
        outages = getattr(assets_mod, "OUTAGES", None)
        result = run_quantum_siting(
            grid=grid, generators=assets_mod.GENERATORS, batteries=assets_mod.BATTERIES,
            T=T, sim_method=sim_method, final_backend=final_backend, n_candidates=n_candidates,
            second_stage=second_stage, warm_start=warm_start, track_convergence=True,
            max_time_s=float(max_time_s), ansatz=ansatz, line_losses=line_losses,
            outages=outages,
        )
        from plots import save_runtime_breakdown
        state["runtime_chart"] = save_runtime_breakdown(
            result.runtime_phases, "Quantum Siting", T, assets_file,
            tag=backend_tag)

        # Same grid + overview plots as Battery Siting, for the best placement,
        # so classical and quantum runs compare like-for-like on the dashboard.
        best_locs, _best_commit, _best_cost, best_res = result.best
        cli.save_plot(best_res, "Quantum", T, assets_file, grid=grid,
                      generators=assets_mod.GENERATORS, bat_locs=best_locs,
                      batteries=assets_mod.BATTERIES, dc_bus=dc_bus, dc_mw=dc_mw)
        cli.save_overview(best_res, "Quantum", T, assets_file,
                          assets_mod.GENERATORS, assets_mod.BATTERIES, grid)

        state["grid"] = grid
        state["generators"] = assets_mod.GENERATORS
        return result

    result, text, plots, log_path, elapsed = _execute("quantum", "Quantum Siting", use_case,
                                             assets_file, T, solve)

    q_key = _quantum_key(use_case, assets_file, T, backend_label, sampling_label,
                         n_candidates, second_stage_label, warm_start_label, line_losses)

    if result is None:
        gr.Warning("Quantum run failed — open the Terminal sub-tab for the traceback.")
        history = _finish_run("Quantum", use_case, assets_file, T, "FAILED",
                              log_path, plots, key=q_key,
                              extra={"backend": backend_tag}, runtime_s=elapsed)
        return ("### Run failed — see Terminal sub-tab", text, plots,
                pd.DataFrame(), [], None, history)

    best_locs, _commit, best_cost, best_res = result.best
    plain = f"buses {tuple(best_locs.values())} · ${best_cost:,.0f}"
    summary = (
        f"### Quantum Siting — best placement **buses {tuple(best_locs.values())}** "
        f"at **${best_cost:,.0f}**\n"
        f"{len(result.evaluated)}/{len(result.quantum_candidates)} candidates feasible"
        + (f" (of {result.search_space_size} total placements)" if result.search_space_size else "")
        + f" · sieve {result.runtime_quantum:.1f}s · refinement {result.runtime_classical:.1f}s"
        + (f"  \n{result.n_qubits} qubits, {result.n_params} params · "
           f"shots: {result.shots_cobyla} (COBYLA) / {result.shots_final} (final)"
           if result.n_qubits is not None else "")
    )
    if line_losses and getattr(best_res, "total_losses_mw", None):
        summary += f"  \n(losses: {sum(best_res.total_losses_mw):,.1f} MWh, all {len(result.evaluated)} candidates re-solved)"

    ranked = sorted(result.evaluated, key=lambda x: x[2])
    table = pd.DataFrame(
        {
            "Rank": list(range(1, len(ranked) + 1)),
            "Battery placement": [str(tuple(bl.values())) for bl, _, _, _ in ranked],
            "Commitment": ["".join(str(c) for c in cm) for _, cm, _, _ in ranked],
            "True cost ($)": [f"{tc:,.0f}" for _, _, tc, _ in ranked],
        }
    )

    pf_gallery = _render_powerflow_gallery(result, state["grid"], state["generators"], T)
    history = _finish_run(
        "Quantum", use_case, assets_file, T, plain, log_path, plots, key=q_key,
        extra={"table_rows": table.to_dict("records"),
               "runtime_chart": state.get("runtime_chart"),
               "backend": backend_tag},
        runtime_s=elapsed,
    )
    return summary, text, plots, table, pf_gallery, state.get("runtime_chart"), history


# ---------------------------------------------------------------------------
# UI assembly
# ---------------------------------------------------------------------------

def _control_bar(tab: str):
    """Compact one-row control bar: use case, assets, T."""
    # ieee30, ieee14_plexos_basecase, and pjm5 temporarily hidden from the
    # dropdown (judge-facing build); all three use cases are untouched in
    # use_cases/ and list_use_cases() still returns them — remove this
    # filter to bring them back in the UI.
    _hidden_ucs = {"ieee30", "ieee14_plexos_basecase", "pjm5"}
    use_cases = [uc for uc in list_use_cases() if uc not in _hidden_ucs]
    uc_default = _setting(tab, "use_case", use_cases[0] if use_cases else None)
    if uc_default not in use_cases:
        uc_default = use_cases[0] if use_cases else None
    assets = list_assets(uc_default) if uc_default else []
    assets_default = _setting(tab, "assets_file", assets[0] if assets else None)
    if assets_default not in assets:
        assets_default = assets[0] if assets else None

    max_hours = _max_hours_for(uc_default, assets_default)

    use_case = gr.Dropdown(choices=use_cases, value=uc_default, label="Use case")
    assets_file = gr.Dropdown(choices=assets, value=assets_default, label="Assets")
    T = gr.Slider(1, max_hours, value=min(_setting(tab, "T", 24), max_hours), step=1, label="Hours T")
    use_case.change(_on_use_case_change, inputs=use_case, outputs=[assets_file, T])
    return use_case, assets_file, T


def _resizable_plots(paths_state: gr.State) -> None:
    """All plots side by side in one row, each scaled to fit its box.

    Re-renders whenever paths_state changes. CSS sizes the images against the
    viewport so the whole row is visible at a glance without scrolling; they
    rescale when the browser window resizes.
    """

    @gr.render(inputs=paths_state)
    def _show(paths):
        if not paths:
            gr.Markdown("*No plots yet — run the solver.*")
            return
        with gr.Row(elem_classes=["plot-row"], equal_height=True):
            for p in paths:
                name = os.path.basename(p).replace(".png", "")
                classes = ["plot-image"]
                if "runtime_breakdown" in name:
                    classes.append("plot-narrow")  # 1/3 width of the other plots
                gr.Image(value=p, type="filepath", label=name,
                         show_label=True, elem_classes=classes)


def build_app() -> gr.Blocks:
    with gr.Blocks(title="Quantum Storage Siting Dashboard") as app:
        gr.Markdown("# ⚡ Quantum Storage Siting Dashboard")

        # ── Economic Dispatch / Unit Commitment ──────────────────────────────
        with gr.Tab("Dispatch") as dispatch_tab:
            _dispatch_default = _setting("dispatch", "problem_type", _PROBLEM_LABELS[0])
            if _dispatch_default not in _PROBLEM_LABELS:
                _dispatch_default = _PROBLEM_LABELS[0]
            with gr.Row():
                d_problem = gr.Radio(_PROBLEM_LABELS, value=_dispatch_default,
                                     label="Problem type", scale=0, min_width=220)
                d_uc, d_assets, d_T = _control_bar("dispatch")
                d_losses = gr.Checkbox(value=False, label="Line Losses",
                                       scale=0, min_width=130)
                d_force = gr.Checkbox(value=False, label="Re-run even if cached",
                                      scale=0, min_width=150)
                d_btn = gr.Button("▶ Run", variant="primary", scale=0, min_width=120)
            gr.Markdown(
                "_Tests the Economic Dispatch / Unit Commitment inner loop in isolation — "
                "battery placement is fixed to the first 4 nodes here (from each use case's "
                "locations.py), not optimized. For battery-placement search, use Battery "
                "Siting (MIP) or Quantum Siting instead._\n\n"
                "_Assets files: **4batt.py** — base case, 4 batteries, no datacenter load · "
                "**4batt_dcbus4.py** — adds a 200 MW datacenter at bus 4 · "
                "**4batt_dcbus4_g2out.py** — same datacenter, plus Generator 2 out for the "
                "full horizon · **4batt_dcbus4_heatwave.py** — same datacenter, plus a "
                "heat-wave demand multiplier on the rest of the system._"
            )
            _d0 = _cached_dispatch(d_problem.value, d_uc.value, d_assets.value, d_T.value,
                                   d_losses.value)
            d_summary = gr.Markdown(_d0[0])
            with gr.Tab("📈 Plots"):
                d_plots = gr.State(_d0[2])
                _resizable_plots(d_plots)
            with gr.Tab("🖥 Terminal"):
                d_term = gr.Textbox(value=_d0[1], lines=22, max_lines=50,
                                    buttons=["copy"], interactive=False,
                                    label="Terminal output")

        # ── Battery Siting (MIP) ─────────────────────────────────────────────
        with gr.Tab("Battery Siting (MIP)") as st_tab:
            with gr.Row():
                st_uc, st_assets, st_T = _control_bar("siting")
                st_limit = gr.Number(value=600, label="Time limit (s)", scale=0,
                                     min_width=130, interactive=False)
                st_losses = gr.Checkbox(value=_setting("siting", "line_losses", False),
                                        label="Line Losses", scale=0, min_width=130)
                st_loss_topk = gr.Number(value=_setting("siting", "loss_top_k", 10),
                                         label="Loss re-solve top-K", scale=0, min_width=150,
                                         interactive=False)
                st_force = gr.Checkbox(value=False, label="Re-run even if cached",
                                       scale=0, min_width=150)
                st_btn = gr.Button("▶ Run", variant="primary", scale=0, min_width=120)
            gr.Markdown(
                "_Suggested limits: **ieee14** → 120–300 s. "
                "Benders stops early if optimal; the limit is a safety cap. "
                "Line Losses keeps the search itself lossless (unchanged speed), then "
                "re-solves the top-K distinct placements found with losses on and reports "
                "the cheapest of those, adding roughly K x (one loss-aware UC solve) to the "
                "total runtime._"
            )
            _st0 = _cached_siting(st_uc.value, st_assets.value, st_T.value, st_limit.value,
                                  st_losses.value, st_loss_topk.value)
            st_summary = gr.Markdown(_st0[0])
            with gr.Tab("📋 Results"):
                st_table = gr.Dataframe(value=_st0[3], label="Candidate ranking",
                                        interactive=False)
            with gr.Tab("📈 Plots"):
                st_plots = gr.State(_st0[2])
                _resizable_plots(st_plots)
            with gr.Tab("🖥 Terminal"):
                st_term = gr.Textbox(value=_st0[1], lines=22, max_lines=50,
                                     buttons=["copy"], interactive=False,
                                     label="Terminal output")

        # ── Quantum Siting ───────────────────────────────────────────────────
        with gr.Tab("Quantum Siting") as q_tab:
            with gr.Row():
                q_uc, q_assets, q_T = _control_bar("quantum")
                # Backend fixed to Qiskit and hidden from the UI (judge-facing
                # build) — Aer TN exists for 36+ qubit cases (ieee30, currently
                # also hidden) and is otherwise slower on the visible cases.
                # Remove this gr.State and restore the gr.Dropdown above it
                # (see git history) to bring the control back.
                q_backend = gr.State("Qiskit")
                with gr.Column(min_width=200):
                    q_sampling = gr.Dropdown(
                        SAMPLING_CHOICES,
                        value=_migrate_sampling_label(_setting("quantum", "sampling", None),
                                                      _default_sampling()),
                        label="Sampling", info=SAMPLING_INFO)
                q_ncand = gr.Slider(1, 300, value=20, step=1, label="Candidates",
                                    interactive=False)
                # 2nd stage fixed to "UC" — no longer user-configurable, dropped
                # from the UI to shrink this row.
                q_stage = gr.State("UC")
                # Warm start fixed to "sdp" and ansatz fixed to "Auto" — no longer
                # user-configurable, so dropped from the UI to shrink this row
                # (each dropdown's info= text was adding to the row height).
                # "Auto" (not "Butterfly") on purpose: run_quantum_siting's Auto
                # already picks butterfly for the Qiskit/statevector backend —
                # the same effective result — but still switches to linear-chain
                # for Aer TN (ieee30), which butterfly's long-range entanglement
                # is incompatible with (see solvers/quantum_siting.py:397).
                # Hardcoding "Butterfly" literally would silently break that path.
                q_warm = gr.State("sdp")
                q_ansatz = gr.State("Auto")
                q_limit = gr.Number(value=600, label="Time limit (s)", scale=0,
                                    min_width=130, interactive=False)
                q_losses = gr.Checkbox(value=_setting("quantum", "line_losses", False),
                                       label="Line Losses", scale=0, min_width=130)
                q_force = gr.Checkbox(value=False, label="Re-run even if cached",
                                      scale=0, min_width=150)
                q_btn = gr.Button("▶ Run", variant="primary", scale=0, min_width=120)
            gr.Markdown(
                "_**Backend** is fixed to Qiskit (local CPU statevector). "
                "**Sampling**: Local (Qiskit) = same simulator as training (free) · "
                "IonQ (qBraid29sim) = real qBraid-routed IonQ simulator for the final "
                "shot sample (free — only real QPU hardware bills credits) · "
                "IonQ (qBraid29sim, noise) = same, with the Forte-1 hardware noise model "
                "applied (also free). "
                "**2nd stage** is fixed to UC (full re-solve with placement fixed), "
                "**warm start** to sdp (LP-relaxation warm start), and **ansatz** to "
                "auto-select (butterfly for Qiskit) — none of these four are exposed as "
                "controls here anymore._"
            )
            gr.Markdown(
                "_Time limit is a safety ceiling, not a target — COBYLA stops on its own "
                "once it genuinely plateaus (114 evaluations with no improvement) or "
                "exhausts its evaluation budget, whichever comes first. Default (900s) is "
                "set generously so the limit should rarely if ever be the actual stopping "
                "reason; check the run log for 'plateau detection' vs. hitting the time "
                "limit with a low iteration count to tell which one fired. "
                "Applies to the VQA optimisation loop. "
                "Line Losses keeps the quantum sieve and classical refinement lossless, "
                "then re-solves all evaluated Candidates with losses on (the Candidates "
                "slider above controls this count) and reports the cheapest._"
            )
            _q0 = _cached_quantum(q_uc.value, q_assets.value, q_T.value,
                                  q_backend.value, q_sampling.value, q_ncand.value,
                                  q_stage.value, q_warm.value, q_losses.value)
            q_summary = gr.Markdown(_q0[0])
            with gr.Tab("📋 Results"):
                q_table = gr.Dataframe(value=_q0[3], label="Candidate ranking",
                                       interactive=False)
            with gr.Tab("📈 Plots"):
                q_plots = gr.State(_q0[2])
                _resizable_plots(q_plots)
            with gr.Tab("⏱ Runtime"):
                q_runtime = gr.Image(value=_q0[4] or _latest_runtime_chart(),
                                     type="filepath",
                                     label="Runtime breakdown (stacked bar)",
                                     elem_classes=["plot-image"])
            with gr.Tab("🖥 Terminal"):
                q_term = gr.Textbox(value=_q0[1], lines=22, max_lines=50,
                                    buttons=["copy"], interactive=False,
                                    label="Terminal output")

        # ── Power Flow ───────────────────────────────────────────────────────
        # Hidden from the UI (backend/gallery code kept as-is, still populated
        # by Quantum Siting runs) — set visible=True to bring the tab back.
        with gr.Tab("Power Flow", visible=False) as pf_tab:
            gr.Markdown(
                "Network diagrams for each candidate placement from the **latest "
                "quantum siting run**, ranked by true cost. Node size = generator "
                "output, green ★ = battery bus, line colour/label = max loading "
                "(orange ≥70%, red ≥90%)."
            )
            pf_refresh = gr.Button("↻ Reload from disk", scale=0)
            q_pf_gallery = gr.Gallery(value=_load_powerflow_gallery(),
                                      columns=3, height=640, object_fit="contain",
                                      label="Candidate placements (ranked by cost)")
            pf_refresh.click(_load_powerflow_gallery, outputs=q_pf_gallery)

        # ── Run history (hidden on the Power Flow tab) ──────────────────────
        with gr.Column(visible=True) as hist_section:
            gr.Markdown("### 🕘 Run history — click a row to reload its output")
            hist_table = gr.Dataframe(value=_history_table(), interactive=False,
                                      max_height=220)
            with gr.Tabs():
                with gr.Tab("📈 Plots"):
                    hist_plots = gr.State([])
                    _resizable_plots(hist_plots)
                with gr.Tab("🖥 Terminal"):
                    hist_term = gr.Textbox(lines=14, max_lines=40, buttons=["copy"],
                                           interactive=False,
                                           label="Selected run — terminal output")
        hist_table.select(_on_history_select, outputs=[hist_term, hist_plots])

        # Power Flow is currently visible=False (unreachable), so hist_section
        # never actually needs to hide — it used to toggle visible=True/False
        # on every tab.select, which re-sent the whole (up to 100-row) history
        # table to the browser on every single tab click. Left permanently
        # visible instead; restore the toggle here if Power Flow is ever
        # brought back (see its definition above).

        # Wire run buttons (cache-first; history table refreshes on every run)
        d_btn.click(run_dispatch_tab,
                    inputs=[d_problem, d_uc, d_assets, d_T, d_force, d_losses],
                    outputs=[d_summary, d_term, d_plots, hist_table])
        st_btn.click(run_siting_tab,
                     inputs=[st_uc, st_assets, st_T, st_limit, st_losses, st_loss_topk, st_force],
                     outputs=[st_summary, st_term, st_plots, st_table, hist_table])
        q_btn.click(
            run_quantum_tab,
            inputs=[q_uc, q_assets, q_T, q_backend, q_sampling, q_ncand, q_stage, q_warm,
                   q_limit, q_ansatz, q_losses, q_force],
            outputs=[q_summary, q_term, q_plots, q_table, q_pf_gallery,
                     q_runtime, hist_table],
        )

    return app


# Mockup C palette: slate background, white cards, teal accent (#0d9488)
_THEME = gr.themes.Default(
    primary_hue="teal",
    neutral_hue="slate",
    font=[gr.themes.GoogleFont("Inter"), "Segoe UI", "system-ui", "sans-serif"],
).set(
    # Every light-mode value below has a matching _dark override so the
    # dashboard looks identical regardless of the browser/OS reporting
    # prefers-color-scheme: dark (Gradio otherwise falls back to its own
    # built-in dark palette for any variable left unset, producing a mixed
    # light/dark render — near-black blocks behind still-white plot PNGs,
    # and unselected tab labels using a dark-on-dark default text color
    # that's invisible until :hover changes it).
    body_background_fill="#f8fafc",
    body_background_fill_dark="#f8fafc",
    body_text_color="#0f172a",
    body_text_color_dark="#0f172a",
    body_text_color_subdued="#64748b",
    body_text_color_subdued_dark="#64748b",
    block_background_fill="#ffffff",
    block_background_fill_dark="#ffffff",
    block_border_color="#e2e8f0",
    block_border_color_dark="#e2e8f0",
    block_shadow="0 1px 2px rgba(0,0,0,0.04)",
    block_label_text_color="#64748b",
    block_label_text_color_dark="#64748b",
    block_title_text_color="#0f172a",
    block_title_text_color_dark="#0f172a",
    button_primary_background_fill="#0d9488",
    button_primary_background_fill_dark="#0d9488",
    button_primary_background_fill_hover="#0f766e",
    button_primary_background_fill_hover_dark="#0f766e",
    button_primary_text_color="#ffffff",
    button_primary_text_color_dark="#ffffff",
    button_secondary_text_color="#0f172a",
    button_secondary_text_color_dark="#0f172a",
)

_CSS = """
:root { color-scheme: light; }
.gradio-container { background: #f8fafc; }
h1 { color: #0f172a; }
button.selected { color: #0d9488 !important; }
label span, .block-label { text-transform: uppercase; letter-spacing: 0.3px;
                           font-size: 11px !important; font-weight: 700; }
/* Plots side by side, whole plot visible at a glance, no page scroll:
   each image fills its column and is capped to the space left under the
   control bar + summary, rescaling with the browser window. */
.plot-row { flex-wrap: nowrap !important; gap: 8px; }
.plot-row .plot-image { flex: 1 1 0; min-width: 0; height: auto !important; }
.plot-row .plot-narrow { flex: 0.33 1 0; }
.plot-row .plot-image img { width: 100%; height: calc(100vh - 330px);
                            object-fit: contain; display: block; }
.plot-image img { max-width: 100%; object-fit: contain; margin: 0 auto;
                  display: block; max-height: 78vh; }
/* Tighten vertical rhythm so a run fits on screen */
.gradio-container .block { padding: 8px 12px; }
.gradio-container h1 { margin: 4px 0 8px; font-size: 22px; }
/* Grey out non-interactive number/text inputs (e.g. locked Time limit,
   Loss re-solve top-K) so they read as disabled instead of plain white. */
.gradio-container input:disabled, .gradio-container textarea:disabled {
    background: #e2e8f0 !important; color: #64748b !important;
    -webkit-text-fill-color: #64748b !important; opacity: 1 !important;
    cursor: not-allowed !important;
}
/* Sliders render a range track + thumb separate from the <input>, so the
   disabled-input rule above doesn't reach them — grey those out too. */
.gradio-container input[type=range]:disabled { opacity: 0.5 !important;
    cursor: not-allowed !important; }
.gradio-container input[type=range]:disabled::-webkit-slider-thumb {
    background: #94a3b8 !important; }
.gradio-container input[type=range]:disabled::-moz-range-thumb {
    background: #94a3b8 !important; }
"""

# Gradio's frontend only skips its own light/dark auto-detection
# (window.matchMedia("(prefers-color-scheme: dark)")) when the page URL
# already carries a "__theme" query param. Without it, dark mode depends on
# what the browser reports for that media query — which varies (e.g. some
# browsers' anti-fingerprinting protections normalize it, others pass the
# real OS preference through), so the same _THEME/_CSS can render
# differently across browsers. Forcing "__theme=light" in the URL via a
# <head> redirect (runs before Gradio's own bundle mounts) makes the
# dashboard render identically everywhere, matching our light-only design.
_FORCE_LIGHT_THEME_HEAD = """
<script>
(function () {
  var url = new URL(window.location.href);
  if (url.searchParams.get("__theme") !== "light") {
    url.searchParams.set("__theme", "light");
    window.location.replace(url.toString());
  }
})();
</script>
"""

if __name__ == "__main__":
    build_app().launch(server_name="127.0.0.1", server_port=7860, show_error=True,
                       theme=_THEME, css=_CSS, head=_FORCE_LIGHT_THEME_HEAD)
