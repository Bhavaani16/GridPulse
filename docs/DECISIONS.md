# Decisions

- 2026-10-17: Committed `signals_cached.csv` is the SPEC 5.1 synthetic duck curve. Reason: no documented provider returned 48 hourly GridSignal rows (EIA timeout, CAISO timeout, Electricity Maps latest is one hour, WattTime credentials absent, no WRI URL in `/docs/data_sources.txt`). Alternative rejected: replace the cache with a partial live series.
