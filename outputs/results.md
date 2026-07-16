# Battery Siting Results — ieee14, T=24h, assets_dc_bus1.py

**Grid:** IEEE 14-bus  
**Horizon:** 24 hours  
**Assets:** assets_dc_bus1.py — 200 MW flat datacenter load injected at Bus 1  
**Batteries:** 4 × (50 MW / 200 MWh, η=0.85, SOC₀=100 MWh)  
**Generators:** 5 units across buses 1/2/3/6/8, linear cost (cost_a=0)

---

## Head-to-head: Option 3 vs Option 4

| | Option 3 — Battery Siting (Benders) | Option 4 — Quantum Siting (Qiskit VQA + UC) |
|---|---|---|
| **Algorithm** | Batch Benders decomposition | VQA quantum sieve + classical UC refinement |
| **Wall time** | 2m 7s | 5m 22s |
| **Quantum sieve time** | — | 5m 12s (312s) |
| **Classical stage time** | 2m 7s (all Benders iterations) | 9.9s (10 parallel UC solves) |
| **Candidates evaluated** | ~2,800 placements (24 parallel/batch) | 10 |
| **Best placement** | buses (4, 10, 13, 13) | buses (1, 4, 7, 13) |
| **Total cost** | $199,804 | $199,804 |
| **Proven optimal?** | No (time limit hit) | No (heuristic) |
| **GPU used** | No | Yes (Aer GPU statevector) |

---

## Notes on the $199,804 degeneracy

All 10 quantum candidates and every Benders placement evaluated so far return **exactly $199,804**.
This is a consequence of the **lossless DC network model**:

- The PTDF-based power flow has no resistive losses (I²R = 0)
- At no hour is any line congested (Congested column shows "none" for all hours)
- In a lossless, uncongested network, battery placement has zero effect on dispatch cost —
  power injected at any bus reaches any load at identical cost

The siting problem is therefore degenerate: all ~2,000+ symmetry-reduced placements
(4 batteries on 14 buses) are globally optimal with cost $199,804.

**Adding resistive line losses or sufficient line congestion would break this degeneracy**
and give each placement a genuinely distinct cost, allowing both solvers to converge quickly
to a meaningful optimum.

---

## Algorithm evolution (Option 3)

| Version | ieee14 T=24 result |
|---|---|
| Original MIP (no time limit) | Did not converge — killed after 40+ CPU-minutes |
| MIP + 5-min time limit | buses (8, 10, 11, 12), $199,804 — time limit hit |
| Benders + 2-min time limit | buses (4, 10, 13, 13), $199,804 — time limit hit, ~2800 placements/2 min |

Improvements added to the MIP/Benders formulation over the session:

- SOS1 constraints on x[b,n] for efficient SCIP branching
- Symmetry breaking for identical batteries (eliminates 4! = 24× equivalent permutations)
- SCIP parallel branch-and-bound (all 24 cores)
- Flow equality cuts: sum_n y[b,n,t] == r[b,t] (tightens LP relaxation at each B&B node)
- Greedy warm-start hint injected before solve
- Batch Benders: 24 UC subproblems evaluated in parallel per iteration

---

## Quantum solver ranking (all 10 candidates)

| Rank | Placement | Cost |
|---|---|---|
| 1 | (1, 4, 7, 13) | $199,804 |
| 2 | (1, 7, 9, 13) | $199,804 |
| 3 | (1, 4, 11, 13) | $199,804 |
| 4 | (3, 5, 12, 14) | $199,804 |
| 5 | (3, 4, 7, 9) | $199,804 |
| 6 | (1, 7, 12, 13) | $199,804 |
| 7 | (4, 7, 10, 13) | $199,804 |
| 8 | (1, 11, 12, 14) | $199,804 |
| 9 | (6, 8, 11, 13) | $199,804 |
| 10 | (3, 4, 7, 13) | $199,804 |
