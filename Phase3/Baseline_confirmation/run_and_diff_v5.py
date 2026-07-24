import importlib.util
import os
import sys

import numpy as np
import openpyxl

SPQ = "/home/mb/Desktop/Desktop_Stuff/square_peg/PQIC/Phase 3 - /Judge_version_GitRepo/square-peg-quantum-challenge"
USE_CASE = os.path.join(SPQ, "use_cases", "ieee14_plexos_basecase")
V5 = "/home/mb/Desktop/Desktop_Stuff/square_peg/PQIC/Phase 3 - /Baseline_confirmation/No Batteries, No Line Losses, Base Case, V5.xlsx"

sys.path.insert(0, SPQ)
sys.path.insert(0, USE_CASE)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


IEEE14 = os.path.join(SPQ, "use_cases", "ieee14")
grid_mod = load_module("ieee14", os.path.join(IEEE14, "ieee14.py"))
assets_mod = load_module("assets", os.path.join(USE_CASE, "assets.py"))
loc_mod = load_module("locations", os.path.join(USE_CASE, "locations.py"))

grid = grid_mod.Case()
T = 24
grid.power_demand = grid.power_demand[:, :T]
grid.generator_cost = grid.generator_cost[:, :T]

generators = assets_mod.GENERATORS
batteries = assets_mod.BATTERIES
gen_locs = loc_mod.GENERATOR_LOCATIONS
bat_locs = loc_mod.BATTERY_LOCATIONS

dc_bus = assets_mod.DATACENTER_BUS
dc_mw = assets_mod.DATACENTER_MW
if dc_bus is not None and dc_mw > 0:
    grid.power_demand[dc_bus - 1, :] += dc_mw

from solvers.uc import run_uc

result = run_uc(grid, generators, batteries, bat_locs, T)

print("=== REPO UC RESULT (ieee14_plexos_basecase, corrected p_min, T=24) ===")
print("Total 24h cost: $", round(result.total_cost, 2))
for t in range(T):
    disp = " ".join(f"{result.dispatch[g, t]:7.2f}" for g in range(len(generators)))
    print(f"hour {t:2d}: {disp}  cost={result.hourly_costs[t]:9.2f}  congested={result.congested_lines[t]}")

# --- Load V5 Generation by Hour (Jan 1, first 24 rows) ---
wb = openpyxl.load_workbook(V5, data_only=True, read_only=True)
ws = wb["Generation by Hour (Output)"]
rows = list(ws.iter_rows(min_row=2, max_row=25, values_only=True))
v5_gen = np.array([[r[6], r[7], r[8], r[9], r[10]] for r in rows])  # Gen1..Gen5, hours 0-23

print("\n=== DIFF: repo dispatch vs V5 Generation by Hour, Jan 1 ===")
repo_gen = result.dispatch.T  # (T, n_gen)
max_abs_diff = 0.0
for t in range(T):
    diff = repo_gen[t] - v5_gen[t]
    max_abs_diff = max(max_abs_diff, np.max(np.abs(diff)))
    flag = "  <-- MISMATCH" if np.max(np.abs(diff)) > 0.5 else ""
    print(f"hour {t:2d}: repo={repo_gen[t].round(2)} v5={v5_gen[t].round(2)} diff={diff.round(2)}{flag}")

print(f"\nMax abs dispatch diff across all gens/hours: {max_abs_diff:.4f} MW")

v5_cost = 0.0
srmc = [20, 20, 40, 40, 40]
for t in range(T):
    v5_cost += sum(v5_gen[t][g] * srmc[g] for g in range(5))
print(f"V5 24h total cost (recomputed from Gen x SRMC): ${v5_cost:,.2f}")
print(f"Repo 24h total cost: ${result.total_cost:,.2f}")
print(f"Cost diff: ${result.total_cost - v5_cost:,.2f}")
