# Progress

## 2026-10-17 cached datasets

- Changed: `/data/signals_cached.csv`, `/data/jobs.json`, `/data/assets.json`, `/backend/data_tools`.
- Run: from the repo root, `.venv/bin/python -m data_tools.fetch_signals` (cwd `backend`) and `.venv/bin/python -m pytest data_tools/tests -q`.
- Test output on Python 3.9.6 (3.11 is not installed on this machine): `5 passed in 0.13s`.
- Mocked: the committed signals are synthetic. Electricity Maps latest probe returned PASS for one hour and was not written into the cache.
- Gaps: no 48-hour live price, carbon, or curtailment file. WattTime and WRI were not called. No git remote, so the PR was not opened.

## 2026-10-17 optimizer core

- Changed: `/backend/optimizer` (Pydantic models, wet-only baseline, one HiGHS MILP, shared metrics, CLI, OPT-1..OPT-9, FORMULATION.md).
- Run: from `/backend`, `.local/venv/bin/python -m pytest optimizer/tests -q` and `.local/venv/bin/python -m optimizer.cli --alpha 0.5`. Interpreter is Python 3.11.17 with scipy 1.14.1 in `backend/.local/venv`. The system Python is 3.9.6, which cannot install scipy 1.14.1.
- Test output: `18 passed in 2.69s`.
- Mocked: nothing. Inputs are `/data/signals_cached.csv` rows 0..23, `/data/jobs.json`, and `/data/assets.json`. No test fixture was required.
- Gaps: schedule ids use `optimizer.clock.now_utc`. Same-second id collisions (`-b`, `-c`) are left to the backend store. Savings are simulated.
