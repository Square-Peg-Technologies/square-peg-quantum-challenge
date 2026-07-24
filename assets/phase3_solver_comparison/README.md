# Phase 3 solver comparison table

Cost/runtime/gap comparison across four IEEE14 scenarios (No DC, DC @ bus 4,
DC @ 4 + Gen2 outage, DC @ 4 + heatwave — the Gen2 outage and heatwave
scenarios are separate/independent, not combined), classical siting vs.
quantum siting (local simulator), with placeholder QPU rows.

## Files

- `benchmark_4_scenarios.py` — runs classical siting (`run_siting_benders`)
  and quantum siting (`run_quantum_siting`, local Aer statevector simulator)
  on all four scenarios and writes `phase3_solver_comparison.json`. Run from
  anywhere with the repo's `.venv` active:
  `python assets/phase3_solver_comparison/benchmark_4_scenarios.py`
  Takes several minutes (mostly the quantum VQA training per scenario).
- `phase3_solver_comparison.json` — the raw results from the last run
  (buses, cost, runtime, gap per scenario/method).
- `phase3_solver_table.tex` — the actual LaTeX table (booktabs `table` float
  with `\multirow`), meant to be `\input{}` directly into the Phase 3 report.
  Requires `\usepackage{multirow}` in the including document's preamble (not
  yet in `submission.tex` — add it there before using this).
- `phase3_solver_table_render.tex` — same table content, but as a plain
  `tabular` + manually-typeset caption instead of a `table` float. Floats
  don't size correctly under the `standalone` document class used for PNG
  rendering, so this is the render-only variant; edit `phase3_solver_table.tex`
  and mirror the same edits here to keep both in sync.
- `render_table_standalone.tex` — wraps `phase3_solver_table_render.tex` in
  a `standalone`-class document for PNG export.
- `phase3_solver_comparison.png` — the rendered table image.

## To regenerate the PNG after editing the table

```
cd assets/phase3_solver_comparison
pdflatex -interaction=nonstopmode render_table_standalone.tex
pdftoppm -png -r 300 render_table_standalone.pdf phase3_solver_comparison
mv phase3_solver_comparison-1.png phase3_solver_comparison.png
```

Requires `pdflatex` (with `standalone`, `booktabs`, `multirow`, `mathptmx`
packages) and `pdftoppm` (poppler-utils).

## Known caveats baked into the current numbers (see table footnotes)

- **Gen2 outage is now correctly modeled by both siting solvers.**
  Previously `OUTAGES` was read only by the standalone Unit Commitment
  tab/solve, so the outage scenario was silently dispatched identically to
  plain DC@4. Fixed by adding an `outages` parameter to
  `run_siting_benders`/`run_quantum_siting` (`solvers/siting_benders.py`,
  `solvers/quantum_siting.py`) threaded through to every internal `run_uc()`
  call, and wiring `dashboard.py`/`main.py` to read `assets_mod.OUTAGES` and
  pass it through for the Siting and Quantum Siting tabs (mirroring the UC
  tab's existing pattern). ED second-stage evaluation still ignores
  `outages` (it dispatches a fixed commitment from the candidate's own
  `u_bits` rather than solving one — see `_eval_one` in
  `solvers/quantum_siting.py`). Confirmed by re-running: Gen2-outage cost
  jumped from the stale $193,229 to $227,343, with classical and quantum
  agreeing exactly (0.000% gap).
- **Heatwave scaling is applied manually in the benchmark script**, mirroring
  `dashboard.py`'s `_load_case` (`HEAT_FACTORS` scales `grid.power_demand`
  before the flat datacenter load is injected). If `dashboard.py`'s loading
  logic changes, update `benchmark_4_scenarios.py` to match.
- **The heatwave scenario's negative gap (-0.133%)** reflects the classical
  Benders search stopping early via its stall-detection heuristic
  (`scip_status="stalled"`), not a bug — quantum's candidate list happened to
  include a placement Benders' early stop missed. Increasing
  `TIME_LIMIT_S` in `benchmark_4_scenarios.py` and re-running would show
  whether classical catches up given more time.
- **QPU rows are placeholders.** No real Forte-1 hardware runs have been
  submitted for this comparison (budget-limited to a small number of real
  QPU submissions — see `solvers/stop_conditions.md` for the shots-vs-gap
  analysis used to size those runs).
