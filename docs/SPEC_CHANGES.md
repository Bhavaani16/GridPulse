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

## 2026-10-17 gemini explain

- What: The D4 task prompt describes a "patched section 11" whose summary object includes `shifted_job_count` and `dry_share_pct`, and a number guard that strips job ids and clock times, extracts unsigned numbers, and uses tolerance 0.5 against the summary numbers plus `100 * alpha`. The committed SPEC.md section 11 has none of that: the summary keys are `alpha`, `shifted_jobs`, `drivers`, `cooling_dry_hours`, `savings_pct`, `metrics`, and the guard extracts `-?\d+(\.\d+)?` with tolerance 0.05 against numbers in the summary JSON.
- Why: SPEC.md is the contract; the patch text never landed in it.
- Files: `backend/integrations/gemini.py`, `docs/SPEC_CHANGES.md`.
- Followed SPEC.md. If the lead wants the patched guard, the change is `_NUMBER_RE`, `_GUARD_TOLERANCE`, an id/clock strip step, and appending `100 * alpha` to `_summary_numbers`.

- What: The prompt asks for tests GEM-1 through GEM-5; SPEC section 16 defines only GEM-1 through GEM-4.
- Why: The prompt's own deliverable lists an empty model body as a template trigger, so the fifth test covers that rule.
- Files: `backend/tests/test_gemini.py`.
- Followed SPEC for the four named tests; `test_gem5_empty_body_returns_template` covers the prompt's fifth case.

- What: The prompt's credentials gate requires `/docs/gemini.txt`; the file is absent. `.env` carries `GEMINI_API_KEY` and `GEMINI_MODEL=gemini-3.8-flash`, but there is no documented SDK usage or model name to verify against.
- Why: SPEC section 11: "If GEMINI_MODE=live and GEMINI_MODEL is empty or the docs file is missing, use the template and log error. Do not guess a model name."
- Files: `backend/integrations/gemini.py`.
- Followed SPEC. `_generate_model_text` is the seam for the documented call and raises `GeminiNotConfigured` until `/docs/gemini.txt` lands.

## 2026-10-17 agents negotiation

- What: The prompt's credentials gate needs `/docs/fetchai.txt` (uAgents quickstart, messaging, Agentverse registration). The file is absent, though `.env` does set `FETCHAI_API_KEY`.
- Why: SPEC section 12: "If that file is missing, stay on FETCHAI_MODE=local", and SPEC forbids inventing SDK calls.
- Files: `agents/`, `backend/integrations/agents_bridge.py`.
- Followed SPEC and the gate's `mock` branch: in-process transport is the whole implementation. `FETCHAI_MODE=network` logs an `agents` error and falls back to local. uAgents transport and Agentverse registration are not tested live.

Update 2026-10-18: the lead said to source Fetch.ai docs from the web. `uagents==0.26.1` was installed and its real signatures verified (`Agent`, `Bureau`, `Model`, `ctx.send`, `on_message`, `on_interval`, `RulesBasedResolver`) — the invariants permit calls verified in the installed package. `FETCHAI_MODE=network` now delivers the section-12 envelopes over real uAgents HTTP between four in-process agents in one Bureau; a documented hello-world passes and the full negotiation round-trips. Hosted-agent features (Almanac writes, mailbox, ASI:One) remain untested live.

- What: The prompt asks for branch `feat/agents-negotiation`; the local-only rule (and the prompt's last line) forbid branches, commits, and pushes.
- Why: local-only replaces the branch/commit/PR steps in the operating loop; the lead publishes later.
- Files: none.
- Followed local-only. All files are left uncommitted; the PR text lives at the bottom of `docs/PROGRESS.md`.

- What: dc-agent counters on strict `it_load_kw > DC_MAX_IT_KW` while the solver's own feasibility check tolerates +1e-4. The solver can return a slot at 6.000008 kW against `max_it_kw 6.0`, so round-2 `counter` envelopes re-fire even on a successful re-optimize.
- Why: Both behaviors are SPEC-literal (strict `>` for dc-agent, 1e-4 slack for the solver); section 12 already defines round-2 replies as recorded-only, so the flow is correct, but the extra counters may surprise a reader.
- Files: `agents/local_agents.py`, `backend/optimizer/solver.py` (`_check_schedule`).
- Proposal: either clamp `it_load_kw` to `max_it_kw` exactly in `build_slots`, or give dc-agent the same 1e-4 tolerance. Recommend the solver clamp (one-line change, owner C2).

## 2026-10-18 solana devnet settlement (D6)

- What: SPEC 14 says "the HTTP handler starts it as a background task", but `schedules.approve_and_apply` (D1-owned) calls `state.record_settlement(schedule)` synchronously inside a try/except after the applied commit.
- Why: The task scope is only `backend/integrations/solana.py`, `backend/tests/test_solana.py`, `scripts/solana_setup.md`.
- Files: `backend/integrations/solana.py`, `backend/schedules.py` (unchanged).
- Followed the intent inside the owned file: `record_settlement` spawns the send on a daemon thread and returns immediately, so the approve path never waits on devnet. If the lead prefers, the thread can move up to `approve_and_apply` and `record_settlement` can return the real signature synchronously — one-line move, owner D1.

- What: `solders==0.29.0` was installed in the venv but cannot be added to `backend/requirements.txt` — that file is outside the task's edit scope.
- Files: `backend/requirements.txt`.
- Proposal: append `solders==0.29.0` (live mode only; lazy-imported, mock works without it). Owner: whoever can edit requirements.

- What: The prompt's credentials gate requires a funded devnet keypair. `SOLANA_KEYPAIR_PATH` points to a valid 64-byte keypair but its devnet balance is 0, and the public devnet RPC airdrop endpoint returned HTTP 429 (rate limited) on every attempt.
- Files: `scripts/solana_setup.md`.
- Followed the gate: mock is the default; the full live path (keypair load, blockhash fetch, sign, sendTransaction, error logging) was verified against real devnet and failed only at the funded-broadcast step with the expected "no record of a prior credit" simulation error.

Update 2026-10-18: the lead funded the keypair (5.0 devnet SOL via the web faucet; RPC `requestAirdrop` stayed 429). One live memo transaction was sent and finalized — signature `3wSTTJs8C7CTF99aqSHhNa7rhwUWeBG6D26JyPRDhDasCGaQNThqfXzRN325HnA7nc7ENAdDq6mnbbQzTxJ2uEH9` (slot 512305556, err null). Live mode is tested end to end.

## 2026-10-18 optimizer water budget

- What: Section 7 had the weighted objective `0.3 cost + (1 - alpha) carbon + alpha water`. The project brief (October 18) and section 1 describe alpha as a water-reduction target: minimize `0.3 cost + 1.0 carbon` subject to `water_l <= (1 - alpha) * water_base`.
- Why: On the sample the weighted form gave three distinct schedules across 21 alphas, all-wet below alpha 0.10 and all-dry above. The brief's part 4 table and the "21 different results" rule need the budget form. The lead asked for the app to follow the brief.
- Files: `backend/optimizer/solver.py`, `backend/optimizer/FORMULATION.md`, `backend/optimizer/tests/test_optimizer.py` (OPT-10, OPT-11), SPEC section 7 and section 16.
- Done. SPEC section 7 text now carries the budget form with a note on the change. The reference numbers at alpha 0, 0.5, 1 match the brief within 0.05 except water at alpha 0 (102.36 L here, 102.14 L in the brief): the water row is not binding there and the tie is broken by the solver.

## 2026-10-18 deploy packaging (D7 follow-up)

- What: `backend/Dockerfile` does not copy `/agents`, so the deployed backend logged `agents_bridge: No module named 'agents'` at startup and `negotiate()` was a no-op on the server. `agents_bridge.py` appends the repo root (`parents[2]`) to `sys.path` and imports `agents`, which resolves inside the image only if `/agents` exists.
- Why: backend/Dockerfile is outside the deploy task's edit scope (`/deploy`, `.github/workflows`, `DEPLOY.md`).
- Files: `deploy/Dockerfile.backend` (new), `deploy/docker-compose.yml`, `backend/Dockerfile` (unchanged).
- Workaround shipped: `deploy/Dockerfile.backend` duplicates backend/Dockerfile plus `COPY agents/ /agents/`; compose builds it instead. Verified live: after rebuild, optimize + request-approval produced 10 `negotiation_msg` envelopes on the server.
- Proposal: add `COPY agents/ /agents/` to `backend/Dockerfile` itself so the images can't diverge (owner: backend/D1).
