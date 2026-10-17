# Decisions

- 2026-10-17: Committed `signals_cached.csv` is the SPEC 5.1 synthetic duck curve. Reason: no documented provider returned 48 hourly GridSignal rows (EIA timeout, CAISO timeout, Electricity Maps latest is one hour, WattTime credentials absent, no WRI URL in `/docs/data_sources.txt`). Alternative rejected: replace the cache with a partial live series.
- 2026-10-17: Solve the full schedule with one `scipy.optimize.milp` call (HiGHS, time_limit 1.5, mip_rel_gap 1e-4). Reason: SPEC section 7. Alternative rejected: a separate LP for checkpointable jobs, or PuLP.
- 2026-10-17: Water is only the alpha-weighted objective term. Reason: section 7 says alpha only changes the three coefficients. Alternative rejected: a hard cap of (1 - alpha) times baseline water from the section 1 overview.
- 2026-10-17: `created_at` and the optimized schedule id come from `optimizer.clock.now_utc`. Fractions and metrics do not. Reason: the SPEC id includes a timestamp, and tests need one clock to patch. Alternative rejected: stamp every schedule with horizon_start. The `-b`/`-c` id suffix for same-second collisions stays in the backend store.
