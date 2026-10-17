# Progress

## 2026-10-17 cached datasets

- Changed: `/data/signals_cached.csv`, `/data/jobs.json`, `/data/assets.json`, `/backend/data_tools`.
- Run: from the repo root, `.venv/bin/python -m data_tools.fetch_signals` (cwd `backend`) and `.venv/bin/python -m pytest data_tools/tests -q`.
- Test output on Python 3.9.6 (3.11 is not installed on this machine): `5 passed in 0.13s`.
- Mocked: the committed signals are synthetic. Electricity Maps latest probe returned PASS for one hour and was not written into the cache.
- Gaps: no 48-hour live price, carbon, or curtailment file. WattTime and WRI were not called. No git remote, so the PR was not opened.
