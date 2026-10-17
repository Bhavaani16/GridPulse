# Cached datasets

These files are the offline inputs for GridPulse. The app can start with `MODE=cached` and no network.

| File | What it is | Real or synthetic |
|---|---|---|
| `signals_cached.csv` | 48 hourly `GridSignal` rows, SPEC section 5.1 | Synthetic. Every `source` value is `synthetic`. |
| `jobs.json` | 8 jobs, SPEC section 5.2 | Sample. 4 checkpointable compute, 2 non-checkpointable compute, 2 `ev_charge`. |
| `assets.json` | One data center and one EV hub, SPEC section 5.3 | Sample. |

## Signals

`signals_cached.csv` is the committed cache. A live fetch must not overwrite it. `python -m data_tools.fetch_signals --live` writes synthetic rows to `signals_live.csv` and does not open a socket, because no documented route returned 48 hours.

The series is the closed-form duck curve in SPEC section 5.1. Local hours 10 through 15 are the solar surplus: price 20.0 $/MWh, marginal carbon 80.0 gCO2/kWh, curtailment 250.0 MW. Local hours 18 through 20 are the peak: price 90.0 $/MWh and marginal carbon 420.0 gCO2/kWh. `SEED` in `backend/data_tools/synthetic.py` is 42. The committed numbers do not use a random draw, so the same seed always reproduces this table.

Row 0 starts at `2026-06-21T07:00:00Z`, which is local midnight PDT on that date. Row timestamps are one hour apart. The sum of `water_stress_index` on the first 24 rows is 17.28.

Water stress uses the Southern California assumption 0.72, scaled by the hour-of-day factor in SPEC section 5.1. WRI Aqueduct was not called. `/docs/data_sources.txt` is not in the repo, so no WRI URL is configured.

Jobs released at local midnight (`job-cp-01`, `job-cp-04`, `job-ncp-01`, `job-ev-01`) can move from those night hours into the local 10:00-15:00 surplus before their deadlines. That is the shift the optimizer is meant to find.

## Live probes on 2026-10-17

One request each, 10-second timeout, no retry. Keys were not printed.

| Provider | Result | Notes |
|---|---|---|
| EIA `GET https://api.eia.gov/v2/electricity/rto?api_key=` | FAIL | Read timed out. Documented catalog route, not a 48-hour price series. |
| Electricity Maps `GET https://api.electricitymaps.com/v3/carbon-intensity/latest?zone=US-CAL-CISO` with header `auth-token` | PASS | Body contained `carbonIntensity`. This route returns one hour, so it was not copied into the 48-row cache. |
| CAISO OASIS `PRC_LMP` day-ahead, node `LAPLMG1_7_B2` from the OASIS interface spec | FAIL | Timed out. |
| WattTime | SKIP | `WATTTIME_USER` and `WATTTIME_PASSWORD` are not set. No WattTime URL is listed in `/docs`. |

Not tested live: a full 48-hour price, carbon, or curtailment download. The cache remains synthetic.

## Run

From the repo root, with Python 3.11:

```text
python3 -m venv .venv
.venv/bin/pip install pydantic==2.10.6 pytest==8.3.4
.venv/bin/python -m data_tools.fetch_signals
cd backend && ../.venv/bin/python -m pytest data_tools/tests -q
```

`fetch_signals` with no arguments rewrites `data/signals_cached.csv` and does not open a socket. `--probe` repeats the provider checks. `--live` writes `data/signals_live.csv` from the synthetic series and does not open a socket.
