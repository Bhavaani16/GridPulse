# SPEC change proposals

## 2026-10-17 data cache

- What: The C1 prompt says `fetch_signals.py` should try CAISO, then EIA, then write the result to `/data/signals_cached.csv`. SPEC section 5.1 says the committed file is the synthetic 48-row table and a live fetch must not overwrite it.
- Why: EIA and CAISO probes timed out. Electricity Maps' documented latest route returned one hour, not 48. Overwriting the cache would break DATA-1 and DATA-2.
- Files: `/data/signals_cached.csv`, `backend/data_tools/fetch_signals.py`.
- Followed SPEC. Live checks are `--probe` only. `--live` writes `/data/signals_live.csv` from the synthetic series.
