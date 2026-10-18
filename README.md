# GridPulse.ai

Schedule compute, cooling and EV charging around clean, low-water power, with a human approving each change.

GridPulse.ai places eight flexible jobs, data-center cooling and EV charging onto 24 hourly slots to cut simulated electricity cost, marginal carbon and cooling water. A slider sets a water-reduction target. The result is shown against a naive baseline, explained in plain language, and nothing is applied until a person replies YES by SMS or presses Approve.

Live demo: https://45-32-137-12.sslip.io

**Every savings number is simulated.** The comparison is between an optimized schedule and a naive baseline on cached, synthetic CAISO-style and WRI Aqueduct-style rows. Nothing here is a forecast for a real site.

## What is real, what is simulated, what is planned

| Part | Status | Detail |
| --- | --- | --- |
| Optimizer | Real | One mixed-integer linear program (SciPy `milp`, HiGHS) over 8 jobs, solved in the backend in tens of milliseconds. Objective `0.3 cost + 1.0 carbon`, subject to `water <= (1 - alpha) * baseline water`. |
| Data | Cached, synthetic | `data/signals_cached.csv` is a synthetic duck curve in CAISO and WRI Aqueduct style. Timestamps are shifted to today's local date so the demo looks current. No live market data. |
| Savings | Simulated | Baseline runs every job at its earliest slot with wet cooling. The label `SIMULATED SAVINGS` is on every screen. |
| Human approval | Real state machine | Dashboard Approve/Reject, and an SMS webhook with YES/NO, one clarification, duplicate suppression, and a 300 s expiry. |
| Tiger Data | Real when `DATABASE_URL` is set | Hypertables and a `telemetry_1m` continuous aggregate on Tiger Cloud (Postgres 18, TimescaleDB 2.30). SQLite when the URL is empty. The live demo runs on Tiger Cloud. |
| Photon SMS | Real in the live demo | `PHOTON_MODE=live` sends the approval text over iMessage to `OPERATOR_PHONE`; the reply comes back through a Standard-Webhooks-signed `message.received` delivery to `/api/webhooks/photon`, and only `YES`/`NO` from the operator number is acted on. `PHOTON_MODE=mock` runs the same state machine without a phone (`scripts/simulate_reply.py YES`). |
| Gemini explanation | Real in the live demo | `GEMINI_MODE=live` calls `models.generateContent` over REST (`docs/gemini.txt`) with `gemini-flash-lite-latest`, about 2 s. Every number in the model text must match the schedule summary within 0.05 or the section-11 template is shown instead, labelled `template fallback`. |
| Hardware (ESP32 fan) | Out of scope | Telemetry and the fan command come from a simulator (`hardware_mode simulated`). |
| Fetch.ai agents | Working locally, Tier 2 | Three in-process agents negotiate over real uAgents envelopes in one Bureau. Not registered on Agentverse. |
| Solana devnet log | Real in the live demo | Every applied schedule writes an SPL Memo transaction on devnet (`schedule_id`, `carbon_saved_kg`, schedule hash) from a background thread; the feed links to the explorer. Mock signatures when `SOLANA_MODE=mock`. |
| ElevenLabs voiceover | Planned | Not built. |
| Vultr deployment | Real | One Ubuntu instance, Docker Compose, Caddy with automatic HTTPS. |

## How it works

1. The backend loads 24 hourly rows of price, marginal carbon, solar curtailment and water stress, and shifts them to today's local day.
2. Moving the slider posts `alpha` to `POST /api/optimize`. The solver minimizes weighted cost and carbon while holding cooling water at or below `(1 - alpha)` times the baseline. Alpha 0 ignores water; alpha 1 allows no wet cooling.
3. The result is stored as a proposed schedule with metrics, baseline metrics and savings percentages. Moving the slider never asks for approval.
4. Trigger Surplus (or Request Approval) asks the operator: `GridPulse: N jobs shifted, X kWh moved into START-END UTC. Reply YES or NO`. YES applies, NO rejects, silence expires it after 300 s. The Approve button does the same.
5. One schedule is applied at a time. The previous one becomes superseded.
6. The simulated device posts power and temperature, and the backend answers with the fan command the applied schedule implies for the current hour.
7. The explanation card and the decision log record every step.

Reference numbers on the committed sample (fixed horizon, tolerance 0.05):

| | Baseline | Alpha 0 | Alpha 0.5 | Alpha 1 |
| --- | --- | --- | --- | --- |
| Cost (USD) | 5.63 | 2.86 | 3.02 | 3.19 |
| Carbon (kg CO2) | 30.29 | 11.45 | 12.08 | 12.75 |
| Water (L) | 104.06 | 102.4 | 52.03 | 0.00 |
| Dry-cooling share | 0% | 0% | 48% | 100% |

Water falls in a straight line as the slider moves right. Across 21 slider positions there are 21 different schedules.

## Run it locally

Requirements: Python 3.11, Node 20 or newer. No network keys are needed; every integration defaults to its mock.

```bash
# backend
cd backend
python3.11 -m venv .local/venv
.local/venv/bin/python -m pip install -r requirements.txt
cp ../.env.example ../.env          # all mock modes, SQLite
make dev                            # http://127.0.0.1:8000

# frontend, in a second terminal
cd frontend
npm install
echo 'VITE_API_URL=http://localhost:8000' > .env
npm run dev                         # http://localhost:5173
```

Open http://localhost:5173. The header shows `mode cached`, `hardware simulated`, `db sqlite`. If the backend is down the page shows `Backend unreachable. Showing mock data.` and runs on fixtures.

Demo path: drag the slider from 0 to 1 and watch water fall to 0 L. Open Demo controls, press Trigger Surplus, then Approve (or `python3 scripts/simulate_reply.py YES`). Read the explanation card and the decision log. Press Reset to return to the baseline.

## Tests

```bash
cd backend && .local/venv/bin/python -m pytest optimizer/tests tests ../agents/tests -q
cd frontend && npm test -- --run && npx tsc -b && npm run lint
```

Last run: backend, optimizer and agents `80 passed`; frontend `12 passed`. The IDs are in `SPEC.md` section 16: DATA, OPT-1 to OPT-11, API, PH, GEM, AG, SOL, FE, E2E.

## Configuration

`backend` reads `.env` at the repo root; `.env.example` lists every variable. The ones that change the demo:

| Variable | Default | Meaning |
| --- | --- | --- |
| `MODE` | `cached` | `live` tries `data_tools.fetch_live_signals` and falls back to the cache |
| `HARDWARE_MODE` | `simulated` | Only `simulated` is supported in this submission |
| `DATABASE_URL` | empty | Postgres/Tiger Cloud URL. Empty means SQLite in `backend/.local/gridpulse.db` |
| `HORIZON_MODE` | `today` | `fixed` keeps the June 2026 timestamps on disk |
| `PHOTON_MODE`, `GEMINI_MODE`, `SOLANA_MODE` | `mock` | `live` needs the keys listed in `.env.example` |
| `FETCHAI_MODE` | `local` | `network` runs the agents over uAgents HTTP in-process |

## Deploy

`DEPLOY.md` covers the Vultr instance: provision, rsync, `deploy/.env`, `docker compose up -d --build`, `deploy/healthcheck.sh`. Caddy serves the built dashboard and proxies `/api`. Only ports 22, 80 and 443 are open.

## Repository layout

| Path | Contents |
| --- | --- |
| `backend/` | FastAPI app, state machine, SQLite and Postgres stores, simulator, integrations |
| `backend/optimizer/` | MILP, baseline, shared metrics, `FORMULATION.md` |
| `frontend/` | React 18 + Vite dashboard |
| `agents/` | Negotiating agents and the uAgents transport |
| `data/` | Cached signals, jobs and assets |
| `deploy/` | Docker Compose, Caddyfile, provision and health scripts |
| `docs/` | `DECISIONS.md`, `PROGRESS.md`, `SPEC_CHANGES.md` |
| `SPEC.md` | The contract every part of the code follows |

## Built with

FastAPI, React and Vite, SciPy HiGHS, Tiger Data (Postgres and TimescaleDB), Photon (live in the demo), Gemini (live in the demo), Fetch.ai uAgents, Solana devnet (live in the demo), Vultr, Caddy.

AI coding agents wrote much of this code under the written spec in `SPEC.md`, with human review and the tests above.
