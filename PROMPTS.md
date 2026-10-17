# GridPulse.ai — Agent Prompt Pack

Paste each prompt as-is. Replace anything in `<angle brackets>` first. Every prompt assumes `SPEC.md` is committed at the repo root and sponsor docs are saved in `/docs/*.txt`.

## Launch order

| Order | Prompt | Tool | When |
|---|---|---|---|
| 0 | Spec writer | Cursor (or any chat) | Hour 0 (you already have a SPEC.md; use only to regenerate or extend) |
| 1 | C1 Data fetcher | Cursor | Hour 2 |
| 2 | C2 Optimizer | Cursor | Hour 2 |
| 3 | D1 Backend + Tiger Data | Devin | Hour 2-3 |
| 4 | D2 Frontend dashboard | Devin | Hour 2-3 |
| 5 | D3 Photon approval loop | Devin | after D1 stubs merge |
| 6 | C3 Firmware + simulator | Cursor | Hour 3 (while you build hardware) |
| 7 | D4 Gemini explainer | Devin | after D1 stubs merge |
| 8 | C4 Integration fixer | Cursor | Hour 10+, reuse as needed |
| 9 | D5 Fetch.ai agents | Devin | Tier 2, only after the Tier 1 flow works |
| 10 | D6 Solana devnet | Devin | Tier 3 |
| 11 | D7 Vultr deploy | Devin | Tier 3, near the end |
| 12 | C5 Demo script, README, ElevenLabs | Cursor | Hour 30+ |
| 13 | Reviewer prompt | Cursor | before merging any PR |

## Shared header (already included in each prompt below)

Every prompt tells the agent to: read SPEC.md first, edit only its folders, not invent sponsor API calls, work on its own branch, open a PR, include tests and run notes, and stop and ask in the PR description when something is missing.

---

## Prompt 0: Spec writer (Cursor or any chat model)

```text
You are a senior engineer writing the single source of truth for a 36-hour solo hackathon project that several AI coding agents (Devin and Cursor) will build in parallel. Precision matters more than prose: mismatched field names between agents are the biggest risk.

PROJECT: GridPulse.ai, a campus-scale scheduler that shifts flexible compute jobs, cooling mode (wet vs dry), and EV charging toward hours with low carbon, low price and low water stress, using CAISO price/marginal-emissions data and WRI Aqueduct water stress. A Carbon-vs-Water "alpha" slider changes the schedule live. Major schedule changes need human approval by SMS (Photon). An ESP32 drives a real low-voltage fan from the approved schedule and streams telemetry. Metrics go to Tiger Data (Postgres/TimescaleDB). Gemini explains each decision in plain language. Fetch.ai agents (data center, EV hub, grid) negotiate the plan. Solana devnet records each applied schedule. FastAPI backend, React dashboard. All savings are SIMULATED and must be labeled so.

PRIORITY TIERS: Tier 1 (must work): optimizer vs naive baseline, dashboard with slider, Tiger Data, Gemini explanation, Photon approval loop, ESP32 with simulated fallback. Tier 2: Fetch.ai agents, ElevenLabs voiceover. Tier 3: Solana devnet, Vultr deploy. Default data source is cached CSVs; live data is a bonus toggle.

PRODUCE SPEC.md with these sections, in order:
1. One-paragraph overview
2. Repo layout with exactly one owner folder per agent (/backend, /frontend, /agents, /firmware, /data, /docs)
3. Stack and versions
4. Units and time conventions (24 hourly slots, UTC ISO-8601)
5. JSON data contracts with a concrete example for: GridSignal, Job, Asset, Schedule, DecisionLogEntry, Telemetry
6. REST API table plus exact request/response examples and error format; include demo endpoints (trigger-surplus, reset)
7. Optimizer formulation as a linear/mixed-integer program: sets, variables, constraints, objective with alpha, baseline definition; keep it linear by splitting IT load into wet and dry cooling variables
8. SQL schema for Tiger Data including hypertables and one continuous aggregate
9. ESP32 protocol, safety rules (low-voltage only, fail-safe when backend unreachable), and simulator behavior
10. Photon SMS approval state machine including timeout and manual-approve fallback
11. Gemini explain() contract with caching and a templated fallback
12. Agent message envelope and negotiation flow (max 2 rounds), with a local-message-passing fallback
13. Environment variables (.env.example)
14. Solana devnet logging behavior (must never block applying a schedule)
15. Frontend panel requirements
16. Acceptance tests per component and one end-to-end test
17. A reusable agent task prompt template
18. A lead checklist before launching agents

RULES: Do not invent sponsor API endpoints or request shapes. Where a detail depends on a sponsor's docs (Photon, Fetch.ai, Tiger Data connection string, Gemini model name, sensor choice) insert a line "TODO(human): <what is needed> from /docs/<file>.txt". Use only concrete examples; no vague wording like "appropriate" or "as needed". Output only the markdown file.
```

---

## Prompt C1: Data fetcher (Cursor, folder: /data and /backend/data_tools)

```text
Read SPEC.md fully before starting.

Task: Build scripts that create the cached datasets the whole project depends on, so the app runs offline.

You may edit only: /data and /backend/data_tools

Deliverables:
1. /backend/data_tools/fetch_signals.py: produces /data/signals_cached.csv with 48 hourly rows matching the GridSignal schema (SPEC section 5.1): price_usd_per_mwh, marginal_gco2_per_kwh, curtailment_mw, water_stress_index, ts.
   - Try, in order: (a) CAISO OASIS day-ahead LMP for a NP15 or SP15 node and curtailment data, (b) EIA hourly data as a fallback, (c) a synthetic generator.
   - The synthetic generator must reproduce the California "duck curve": solar surplus around 10:00-16:00 local (low price, low carbon, high curtailment), peak price and carbon around 18:00-21:00. Seed it for reproducibility.
   - Marginal emissions: use the WattTime or Electricity Maps free endpoint if the key in .env works; otherwise derive from the synthetic curve. Label the source in a column `source`.
   - Water stress: a single constant per site from WRI Aqueduct if available, else a documented assumed value (use 0.72 for Southern California) scaled by a small hour-of-day factor.
2. /data/jobs.json: 8 sample jobs (mix of 4 checkpointable compute jobs, 2 non-checkpointable compute jobs, 2 ev_charge jobs) matching SPEC 5.2, with windows that make shifting useful.
3. /data/assets.json: one data center and one EV hub matching SPEC 5.3.
4. /data/README.md documenting each file, its source, and whether it is real or synthetic.
5. pytest tests: schema validity with Pydantic models, 48 rows, no NaN, hourly spacing, and that the cached file loads with no network.

Constraints: no network calls at import time; every network fetch must have a 10-second timeout and fall through to the next source on failure; never commit API keys. Do not invent endpoint URLs you are unsure of; if you cannot verify an endpoint, use the synthetic path and note it in the PR.

Open a PR on branch feat/data-cached-signals. Include how to run it and the test output.
```

---

## Prompt C2: Optimizer (Cursor, folder: /backend/optimizer). Review this one line by line.

```text
Read SPEC.md fully (especially sections 4, 5 and 7) before starting.

Task: Implement the scheduling optimizer as a pure function and a naive baseline.

You may edit only: /backend/optimizer (and its tests in /backend/optimizer/tests)

Deliverables:
1. /backend/optimizer/models.py: Pydantic v2 models for GridSignal, Job, Asset, Schedule, Slot, Metrics exactly as in SPEC section 5. Other agents will import these; do not rename fields.
2. /backend/optimizer/solver.py: `optimize(signals, jobs, assets, alpha) -> Schedule` implementing SPEC section 7:
   - Variables x[j,t], yw[t], yd[t]; constraints for completion, windows, load link, capacity.
   - Checkpointable jobs: continuous x in [0,1] (LP via scipy HiGHS).
   - Non-checkpointable jobs: one binary start variable per feasible start hour, solved as MILP (scipy.optimize.milp or PuLP; pick one and use it consistently).
   - Objective: 0.3*cost/cost_base + (1-alpha)*carbon/carbon_base + alpha*water/water_base.
3. /backend/optimizer/baseline.py: `baseline(signals, jobs, assets) -> Schedule` where every job starts at its release time and runs wet cooling only.
4. Metrics: cost_usd, carbon_kg, water_l, energy_kwh for both schedules plus savings_pct, computed by one shared function so the numbers are consistent.
5. A short `FORMULATION.md` in the folder explaining the math in plain language (the lead must be able to explain it to judges) including the water term and why wet/dry is split into yw and yd.
6. Infeasibility handling: if a job cannot fit its window, return a clear error object naming the job; never crash.
7. A CLI: `python -m optimizer.cli --alpha 0.5` that loads /data/signals_cached.csv, /data/jobs.json, /data/assets.json and prints a table of baseline vs optimized.

Tests (pytest, all must pass): every job completes its hours inside its window; load never exceeds capacity; optimized carbon <= baseline carbon at alpha=0; optimized water <= baseline water at alpha=1; non-checkpointable jobs run contiguously; alpha monotonicity (carbon rises and water falls as alpha goes 0 to 1 on the sample data, within a small tolerance); runtime under 2 seconds for 10 jobs x 24 hours.

Constraints: no web calls, no global state, deterministic output. If data in /data is not merged yet, create a tiny fixture in tests/fixtures and note it.

Open a PR on branch feat/optimizer-core. Include a table of baseline vs optimized numbers at alpha 0, 0.5 and 1, and the test output.
```

---

## Prompt D1: Backend + Tiger Data (Devin, folder: /backend except /backend/optimizer)

```text
Read SPEC.md fully before starting. You are building the FastAPI backend.

Task: Implement the backend API, database layer and data replay, and create stub modules that other agents will fill in.

You may edit only: /backend (do NOT edit /backend/optimizer; import from it). If the optimizer PR is not merged yet, create a temporary mock in /backend/mocks/optimizer_mock.py behind the same function signature `optimize(signals, jobs, assets, alpha) -> Schedule` and switch via an env flag.

Deliverables:
1. FastAPI app (backend/main.py) with every endpoint in SPEC section 6, with Pydantic request/response models and the error format from the spec. Include /api/stream (SSE) if it takes under 30 minutes; otherwise skip it and say so in the PR.
2. Database layer for Tiger Data (Postgres + TimescaleDB): run the schema from SPEC section 8 at startup (idempotent). Use the DATABASE_URL env var. TODO(human): connection string format is in /docs/tigerdata.txt; read it, do not guess. Also support SQLite (or in-memory) fallback when DATABASE_URL is empty so the app runs offline.
3. Data replay: load /data/signals_cached.csv, /data/jobs.json, /data/assets.json at startup (MODE=cached). In MODE=live, call a `fetch_live_signals()` stub that returns cached data if it fails.
4. Endpoints for telemetry: POST /api/telemetry stores a row and returns {"command": {"fan_on": bool}} derived from the currently applied schedule (rule in SPEC section 9). GET /api/telemetry returns 1-minute aggregated data (use the continuous aggregate when available).
5. Decision log: every state change writes a DecisionLogEntry.
6. Demo endpoints: /api/demo/trigger-surplus (boost curtailment, lower price and carbon in the next 3-6 hours, call optimize, store the proposal, call the approval stub) and /api/demo/reset.
7. Simulator: backend/simulator.py that posts Telemetry with simulated=true every 2 seconds when HARDWARE_MODE=simulated, and adjusts temperature plausibly when fan_on changes.
8. STUB MODULES with documented signatures and a clear NotImplemented behavior that returns safe defaults, so other agents can fill them in without touching main.py:
   - backend/integrations/photon.py: `send_approval_sms(schedule) -> str`, router `photon_router` mounted at /api/webhooks
   - backend/integrations/gemini.py: `explain(schedule, signals, prev_schedule) -> str` (returns a templated sentence for now)
   - backend/integrations/solana.py: `record_settlement(schedule) -> str | None` (returns None for now)
   - backend/integrations/agents_bridge.py: `negotiate(schedule) -> Schedule` (returns the same schedule for now)
   main.py must import these once; other agents will only edit their own file.
9. Dockerfile and a Makefile with `make dev`, `make test`.
10. .env.example per SPEC section 13.

Tests (pytest + httpx TestClient): every endpoint returns schema-valid JSON; telemetry post returns a command; demo trigger creates a proposed schedule and a log entry within 3 seconds; app starts with MODE=cached and no internet and no DATABASE_URL.

Constraints: never invent Tiger Data or sponsor API calls; read /docs. No secrets in the repo. Keep functions small and typed.

Open a PR on branch feat/backend-core with run instructions (exact commands) and test output.
```

---

## Prompt D2: Frontend dashboard (Devin, folder: /frontend)

```text
Read SPEC.md fully, especially sections 5, 6 and 15.

Task: Build the React dashboard. It must run fully on mock data first and switch to the real API with VITE_API_URL.

You may edit only: /frontend

Stack: Vite, React 18, TypeScript, Tailwind, Recharts. Dark mode only. Polished, high-contrast, readable on a projector.

Deliverables:
1. Typed API client generated by hand from SPEC section 5 and 6 types (src/api/types.ts, src/api/client.ts) and mock fixtures in src/mock/ that satisfy the exact schemas.
2. Layout (single page):
   - Header with mode badge (cached/live), hardware badge (real/simulated) from /api/health, and a visible "SIMULATED SAVINGS" tag near the KPIs.
   - KPI cards: cost, carbon, water savings vs baseline (percent plus absolute), updating live.
   - Carbon vs Water Pareto slider (alpha 0..1). Debounce 250 ms, call POST /api/optimize, update charts within 1 second. Show labels "Favor carbon" and "Favor water" and the current alpha.
   - Schedule timeline: 24-hour Gantt of jobs plus a strip showing cooling mode per hour (wet/dry) and a faint overlay of the curtailment window.
   - Signals chart: price, marginal carbon and curtailment per hour.
   - Live telemetry chart: power and temperature for the last 5 minutes, fan state markers.
   - Decision log feed with actor icons and relative timestamps, auto-updating (SSE from /api/stream if available, else poll every 2 s).
   - Schedule action bar: Request Approval, Approve, Reject buttons with state (proposed, pending_approval, approved, applied, expired). The Approve button is the manual fallback.
   - Gemini explanation card shown above the timeline (from GET /api/explain/{schedule_id}).
   - Demo controls (collapsed panel): Trigger Surplus, Reset.
   - Settlement link: when a log entry has event settlement_tx, show a link to the Solana devnet Explorer (https://explorer.solana.com/tx/<sig>?cluster=devnet).
3. Loading and error states for every panel; a visible banner when the backend is unreachable that falls back to mock data.
4. README in /frontend with `npm install`, `npm run dev`, env var, and screenshots.
5. Component tests (Vitest + Testing Library): slider triggers a debounced optimize call, KPI cards render values from fixtures, log feed renders new items.

Constraints: no calls to external services other than the backend; no hard-coded localhost URLs outside the env var; accessible color contrast; no console errors.

Open a PR on branch feat/frontend-dashboard with screenshots at alpha 0 and alpha 1 and test output.
```

---

## Prompt D3: Photon approval loop (Devin, file: backend/integrations/photon.py)

Before launching: paste the real Photon request/response/webhook shapes into `/docs/photon.txt` and fill the TODO in SPEC section 10.

```text
Read SPEC.md fully (sections 6 and 10) and /docs/photon.txt before starting. The stub backend/integrations/photon.py already exists from the backend PR.

Task: Implement the SMS human-in-the-loop approval flow with Photon.

You may edit only: backend/integrations/photon.py and its tests (backend/tests/test_photon.py). If you need an extra route or model, put it inside photon.py or ask in the PR.

Deliverables:
1. `send_approval_sms(schedule) -> str` sends the text from SPEC section 10 to OPERATOR_PHONE using only request shapes documented in /docs/photon.txt. Message must include the number of shifted jobs, kWh shifted and the target window, and "Reply YES or NO".
2. `photon_router` handling the inbound webhook at POST /api/webhooks/photon: parse the documented payload, normalize the reply text (trim, uppercase), then YES -> approve and apply the pending schedule, NO -> reject, anything else -> send one clarification and keep waiting. Use the existing state-transition functions from the backend (do not duplicate the logic; call them).
3. Timeout: after 5 minutes (configurable by env PHOTON_TIMEOUT_SECONDS) a pending schedule becomes `expired` and the baseline stays; log it. Use a background task, not blocking sleep.
4. Idempotency: ignore duplicate webhook deliveries (same message id) and replies for schedules that are no longer pending.
5. Every step writes a DecisionLogEntry (sms_sent, sms_reply, error).
6. A MOCK mode (PHOTON_MODE=mock) that logs instead of sending, plus a script `scripts/simulate_reply.py YES` that posts a fake webhook, so the loop can be tested without a phone.
7. Docs: `backend/integrations/PHOTON.md` explaining how to expose the webhook publicly during development (ngrok or the Vultr URL) and how to set the webhook URL in Photon.

Tests: YES applies, NO rejects, unknown text triggers one clarification, duplicate webhook is ignored, timeout expires the schedule, mock mode never makes network calls.

Constraints: do not invent Photon endpoints, headers or payload fields. If /docs/photon.txt is missing something you need, stop and list the questions in the PR description. Never log the phone number in full; mask it.

Open a PR on branch feat/photon-approval with test output and a sequence description.
```

---

## Prompt C3: Firmware and hardware helpers (Cursor, folder: /firmware)

Fill in your sensor choice first (INA219 on a 5V fan load, or a Shelly/Tasmota plug) and your ESP32 board model.

```text
Read SPEC.md fully, especially section 9.

Task: Write the ESP32 firmware for GridPulse's edge controller.

You may edit only: /firmware

Hardware: <ESP32 board model>, <sensor: INA219 on I2C measuring a 5V USB fan | Shelly/Tasmota smart plug via local HTTP API>, <temperature sensor: DS18B20 | DHT22 | onboard>, fan switched through <logic-level MOSFET | relay module>. Pin map: <list pins>. Low-voltage loads only.

Deliverables (PlatformIO or Arduino IDE project, say which in the README):
1. Wi-Fi connect with retry and reconnect; credentials and BACKEND_URL from config.h (gitignored) with config.example.h committed.
2. Every 2 seconds: read power (W) and temperature (C), then POST to {BACKEND_URL}/api/telemetry with the exact JSON from SPEC section 5.6 (device_id, ISO-8601 UTC timestamp via NTP, power_w, temp_c, fan_on, simulated:false).
3. Parse the response `{"command":{"fan_on":bool}}` and switch the fan pin. Debounce: ignore commands that flip state faster than every 5 seconds.
4. Failsafe: if the backend is unreachable for 30 s, force fan ON and blink the onboard LED; resume normal control when it returns.
5. Serial debug logging at 115200 baud and an onboard LED status (blink = connecting, solid = OK, fast blink = failsafe).
6. A Python helper `firmware/tools/fake_esp32.py` that behaves like the firmware (posts telemetry, applies commands) so the backend can be tested without hardware.
7. README: wiring diagram in ASCII, library list, flash steps, how to calibrate the power reading, troubleshooting.

Constraints: no mains voltage anywhere in code comments or wiring instructions; add a clear safety note in the README. Use HTTPS only if the backend URL is https, otherwise plain HTTP is fine for the local network. Keep memory use low (static JSON buffers).

Open a PR on branch feat/firmware-esp32 with the wiring diagram and a sample serial log.
```

---

## Prompt D4: Gemini explainer (Devin, file: backend/integrations/gemini.py)

```text
Read SPEC.md fully (sections 5.4 and 11) and /docs/gemini.txt before starting.

Task: Implement the Gemini natural-language explanation layer.

You may edit only: backend/integrations/gemini.py and backend/tests/test_gemini.py.

Deliverables:
1. `explain(schedule, signals, prev_schedule) -> str` calling the Gemini API using only the SDK usage shown in /docs/gemini.txt, model name from env GEMINI_MODEL.
2. Prompt construction: send a compact JSON summary only (which jobs moved and from/to which hours, the top 2 signal drivers such as curtailment or carbon, cooling mode changes, alpha, and the savings percentages). Instruct the model: 2-3 plain sentences, mention the carbon vs water trade-off at the current alpha, use ONLY numbers present in the input, no markdown.
3. Number guard: after generation, verify that every number in the output appears in the input summary (allowing rounding); if not, discard and use the templated fallback.
4. Caching by schedule_id plus alpha (in-memory dict plus the decision_log). A timeout of 6 seconds and one retry.
5. Templated fallback sentence built purely from metrics, so the UI never shows an empty explanation.
6. Log a DecisionLogEntry with actor gemini and event explanation.
7. Offline mode (GEMINI_MODE=mock) returning the fallback.

Tests: fallback on timeout, number guard rejects an invented number, cache hit avoids a second call (mock the client), output length is within 3 sentences.

Constraints: do not invent SDK calls; never log the API key.

Open a PR on branch feat/gemini-explain with example inputs and outputs.
```

---

## Prompt C4: Integration fixer (Cursor, reusable from hour 10)

```text
Read SPEC.md fully.

Context: The merged components are <list: backend, optimizer, frontend, photon, gemini, firmware>. The end-to-end flow in SPEC section 16 is failing at this step: <step>. Observed behavior: <paste logs, error text, request/response bodies>.

Task: Find the root cause and fix it with the smallest change that preserves the contracts in SPEC.md.

Rules:
- First, write a failing test or a reproduction script that demonstrates the bug.
- Identify whether the bug is in the code or in a disagreement between two components about the SPEC. If it is a spec disagreement, do NOT change either side silently: list both sides and propose which one should change, and propose the SPEC.md edit.
- You may edit: <folders>. Do not touch any other folder.
- Do not add features. Do not refactor unrelated code.
- After the fix, run the full test suite and the reproduction script and paste the output.

Open a PR on branch fix/<short-name> with: root cause (2 sentences), the fix, the test, and any SPEC.md change proposed.
```

---

## Prompt D5: Fetch.ai agents (Devin, folder: /agents and backend/integrations/agents_bridge.py). Tier 2 only after Tier 1 works.

Before launching: put the Fetch.ai / ASI:One / uAgents / Agentverse docs in `/docs/fetchai.txt` and fill the TODO in SPEC section 12.

```text
Read SPEC.md fully (sections 5.4, 5.5 and 12) and /docs/fetchai.txt before starting.

Task: Implement three negotiating agents and the bridge that the backend calls.

You may edit only: /agents and backend/integrations/agents_bridge.py (plus tests).

Deliverables:
1. Three agents, each a separate process or module: dc-agent (data center), ev-agent (EV hub), grid-agent. Use the Fetch.ai SDK exactly as documented in /docs/fetchai.txt. If after 90 minutes the SDK blocks you, implement the same message envelope with local in-process message passing and say so clearly in the README (do not pretend it is on the network).
2. Message envelope exactly as SPEC section 12 (msg_id, from, to, type, schedule_id, body).
3. Behavior:
   - grid-agent publishes an `inform` message describing the surplus window from the current GridSignal data.
   - The bridge sends the proposed Schedule to dc-agent and ev-agent as a `propose`.
   - Each asset agent checks local constraints (e.g. dc-agent: thermal limit of 6 kW above temperature X; ev-agent: minimum charge by a deadline) and replies `accept` or `counter` with a concrete constraint in the body.
   - The bridge re-solves ONCE with added constraints by calling the optimizer function (import from backend/optimizer; do not modify it), maximum 2 negotiation rounds, then returns the final Schedule.
4. `negotiate(schedule) -> Schedule` in agents_bridge.py replacing the stub; it must never raise: on any failure return the original schedule and log an error.
5. Every message is logged as a DecisionLogEntry with event negotiation_msg so the dashboard shows the conversation.
6. A scripted scenario `python -m agents.demo_scenario` that always produces at least one counter-proposal so the demo shows real negotiation; make the constraint values configurable via env.
7. Optional last step: register agents on Agentverse and ASI:One chat only if the docs make it a short step; document what is and is not done.

Tests: accept path, counter path with a re-solve that changes the schedule, 2-round limit, failure fallback.

Constraints: do not invent SDK calls or endpoints; do not block the backend request thread longer than 8 seconds.

Open a PR on branch feat/agents-negotiation with a sample transcript of a negotiation.
```

---

## Prompt D6: Solana devnet settlement (Devin, file: backend/integrations/solana.py). Tier 3.

```text
Read SPEC.md fully (sections 5.5 and 14).

Task: Record each applied schedule on Solana devnet.

You may edit only: backend/integrations/solana.py, backend/tests/test_solana.py, scripts/solana_setup.md.

Deliverables:
1. `record_settlement(schedule) -> str | None`: build a transaction that carries a memo (use the SPL Memo program) with JSON `{"gridpulse":1,"schedule_id":...,"hash":"<sha256 of the metrics JSON>","carbon_saved_kg":...}`, sign with the keypair at SOLANA_KEYPAIR_PATH and send to SOLANA_RPC_URL (default devnet). Return the signature string.
   Use solana-py / solders as documented by those libraries; verify function names against installed package versions rather than guessing.
2. Fire-and-forget: run in a background task with a 10-second timeout; failure must never block or fail applying the schedule; on failure log an error and return None.
3. Log a DecisionLogEntry with event settlement_tx and payload containing the signature and the Explorer URL (cluster=devnet).
4. Mock mode (SOLANA_MODE=mock) returning a fake signature.
5. scripts/solana_setup.md: how to create a devnet keypair, airdrop SOL, and the env vars. Also a short honest paragraph framing this as an auditable log of curtailment events and incentive payouts on devnet, not a production token system.

Tests: mock mode, timeout handling, memo payload contains the schedule id and hash.

Open a PR on branch feat/solana-devnet with an example transaction link.
```

---

## Prompt D7: Vultr deployment (Devin, files: deploy/ and CI). Tier 3, near the end.

```text
Read SPEC.md fully (sections 3 and 13).

Task: Deploy the backend (and the built frontend as static files) to a Vultr cloud instance, with a repeatable script.

You may edit only: /deploy and .github/workflows (and add a root DEPLOY.md).

Deliverables:
1. /deploy/docker-compose.yml running the FastAPI backend (from backend/Dockerfile) and serving the frontend build behind Caddy or nginx with automatic HTTPS if a domain is set, else plain HTTP on the instance IP.
2. /deploy/provision.sh: idempotent script for a fresh Ubuntu Vultr instance (install Docker, pull the repo, create the .env from a template, start compose, print the public URL).
3. /deploy/healthcheck.sh calling /api/health and returning non-zero when unhealthy.
4. DEPLOY.md with exact steps, how to set the Photon webhook URL and the ESP32 BACKEND_URL to the public address, how to roll back, and a localhost fallback procedure for the demo.
5. Firewall notes (only ports 80/443 and SSH).

Constraints: no secrets in the repo; .env is created on the server. Do not use paid services other than the Vultr instance. If you cannot access my Vultr account, produce the scripts and instructions only and say exactly what I must run.

Open a PR on branch feat/deploy-vultr.
```

---

## Prompt C5: Demo script, README, ElevenLabs voiceover (Cursor, folders: /docs-site, README.md, /demo)

```text
Read SPEC.md fully and the repo README if present.

Task: Produce the submission materials.

You may edit only: README.md, /demo, and /docs/architecture.

Deliverables:
1. README.md: one-paragraph pitch, problem statement, architecture diagram (Mermaid), a table of how each sponsor tool is used in the live system (one honest sentence each; say clearly what is real vs simulated and which tier it belongs to), setup and run instructions that work from a clean clone (cached mode, simulated hardware), the demo script, an honest "Limitations" section (simulated savings, demo-scale hardware, cached data by default, no real money moved), and the Devin usage log (which parts Devin built, with PR links to be filled in by me).
2. /demo/script_60s.md: a 60-second narration (about 150 words) synchronized to a shot list with timestamps.
3. /demo/pitch_3min.md: the 3-minute live pitch outline: hook, live demo steps with exact clicks, the Pareto slider moment, the headline numbers (leave placeholders `<X%>`), and the close.
4. /demo/qa.md: answers to 10 likely judge questions, including "how is this different from existing demand response", "where do your savings numbers come from", "what breaks at 1,000 sites", "why a dry cooling trade-off", "what does the agent network add vs a single optimizer".
5. /demo/elevenlabs_generate.py: reads script_60s.md and calls the ElevenLabs text-to-speech API to write /demo/voiceover.mp3. Use the official SDK or REST calls exactly as shown in the ElevenLabs docs (check them; do not guess); voice id and key from env.

Constraints: do not claim anything that is not implemented; if a feature is Tier 2/3 and not done, mark it as "planned".

Open a PR on branch docs/submission.
```

---

## Prompt: PR reviewer (Cursor, use before merging every PR)

```text
Read SPEC.md fully. Review the diff of this branch against main as a strict senior reviewer.

Check, in this order:
1. Contracts: do all JSON fields, endpoint paths, status values and env vars exactly match SPEC.md? List every mismatch.
2. Scope: did the author touch any folder they do not own?
3. Safety and secrets: any API keys, phone numbers, mains-voltage instructions, or logging of sensitive values?
4. Invented APIs: any sponsor API call, endpoint or field that is not documented in /docs? List them.
5. Failure behavior: what happens on timeout, empty data, or an unreachable service? Does it fall back as the SPEC requires?
6. Tests: do they actually assert behavior from the acceptance list in SPEC section 16? Are any trivial?
7. Run it: give me the exact commands to run it and the one manual check I should perform.

Output: a verdict (merge / merge after fixes / reject), a numbered list of required fixes, and a list of nice-to-haves. Do not edit any files.
```

---

## Tips for using these prompts

- Fill every TODO in SPEC.md before launching the task that depends on it.
- Launch Devin tasks on separate branches; merge them in the order backend, optimizer, frontend, then the integrations.
- Ask for the PR first and merge only after running the code yourself.
- If an agent asks a question in the PR instead of guessing, that is a good sign; answer it in SPEC.md.
- Keep Devin session links and PR URLs in a file as you go: you need them for the Cognition track and the README.
