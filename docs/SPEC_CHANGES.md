# SPEC change proposals

## 2026-10-17 data cache

- What: The C1 prompt says `fetch_signals.py` should try CAISO, then EIA, then write the result to `/data/signals_cached.csv`. SPEC section 5.1 says the committed file is the synthetic 48-row table and a live fetch must not overwrite it.
- Why: EIA and CAISO probes timed out. Electricity Maps' documented latest route returned one hour, not 48. Overwriting the cache would break DATA-1 and DATA-2.
- Files: `/data/signals_cached.csv`, `backend/data_tools/fetch_signals.py`.
- Followed SPEC. Live checks are `--probe` only. `--live` writes `/data/signals_live.csv` from the synthetic series.

## 2026-10-17 optimizer

- What: The optimizer prompt says checkpointable jobs are a separate LP and non-checkpointable jobs may use PuLP. SPEC section 7 says one `scipy.optimize.milp` call.
- Why: Other agents call one `optimize()`. Two solvers would drift.
- Files: `backend/optimizer/solver.py`.
- Followed SPEC. One HiGHS MILP, continuous x, binary start variables.

- What: Section 1 says water stays at or below (1 - alpha) times baseline water. Section 7 does not list that constraint, and it says alpha only changes the three objective coefficients.
- Why: A hard cap would change the feasible region as the slider moves. OPT-3, OPT-4, and OPT-6 match the weighted objective.
- Files: `backend/optimizer/solver.py`, `backend/optimizer/FORMULATION.md`.
- Followed section 7. On the committed sample, alpha 1 still reaches zero water because every IT kilowatt is dry-cooled.
