"""Database layer. Postgres + TimescaleDB when DATABASE_URL starts with
postgres:// or postgresql://, otherwise SQLite (SPEC sections 3 and 8).

An empty DATABASE_URL stores the file at backend/.local/gridpulse.db.
sqlite:///PATH stores that path (sqlite:///:memory: is in-memory).

Postgres connects with a 5-second timeout and one retry. On failure the
caller logs a decision-log error (integration tigerdata) and this module
returns the SQLite store instead. Timescale features are best-effort: if
the extension, hypertables, or the telemetry_1m continuous aggregate fail,
the plain Postgres tables keep serving and GET /api/telemetry aggregates
in Python.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from clock import iso, parse_ts
from config import BACKEND_DIR
from models import DecisionLogEntry, TelemetryMinute, TelemetryRow
from optimizer.models import Asset, GridSignal, Job, Schedule, Slot

SQLITE_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS grid_signals (
  ts TEXT PRIMARY KEY,
  price_usd_per_mwh REAL NOT NULL,
  marginal_gco2_per_kwh REAL NOT NULL,
  curtailment_mw REAL NOT NULL,
  water_stress_index REAL NOT NULL,
  source TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS assets (
  asset_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  it_capacity_kw REAL,
  charge_capacity_kw REAL,
  wet_extra_kw_per_kw REAL,
  dry_extra_kw_per_kw REAL,
  wet_water_l_per_kwh REAL
)""",
    """CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  checkpointable INTEGER NOT NULL,
  asset_id TEXT NOT NULL,
  power_kw REAL NOT NULL,
  duration_h REAL NOT NULL,
  energy_kwh REAL NOT NULL,
  release_ts TEXT NOT NULL,
  deadline_ts TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS schedules (
  schedule_id TEXT PRIMARY KEY,
  schedule_kind TEXT NOT NULL,
  status TEXT NOT NULL,
  alpha REAL NOT NULL,
  horizon_start TEXT NOT NULL,
  created_at TEXT NOT NULL,
  metrics_json TEXT NOT NULL,
  baseline_metrics_json TEXT NOT NULL,
  savings_pct_json TEXT NOT NULL,
  shifted_job_count INTEGER NOT NULL,
  shifted_kwh REAL NOT NULL,
  savings_label TEXT NOT NULL,
  explanation TEXT
)""",
    """CREATE TABLE IF NOT EXISTS schedule_slots (
  schedule_id TEXT NOT NULL,
  t INTEGER NOT NULL,
  ts TEXT NOT NULL,
  cooling_mode TEXT NOT NULL,
  it_load_kw REAL NOT NULL,
  yw_kw REAL NOT NULL,
  yd_kw REAL NOT NULL,
  ev_load_kw REAL NOT NULL,
  total_load_kw REAL NOT NULL,
  jobs_json TEXT NOT NULL,
  PRIMARY KEY (schedule_id, t)
)""",
    """CREATE TABLE IF NOT EXISTS decision_log (
  log_id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  schedule_id TEXT,
  actor TEXT NOT NULL,
  event TEXT NOT NULL,
  payload_json TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS telemetry (
  device_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  power_w REAL NOT NULL,
  temp_c REAL NOT NULL,
  fan_on INTEGER NOT NULL,
  simulated INTEGER NOT NULL,
  flagged INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (device_id, ts)
)""",
]

# SPEC section 8 Postgres DDL. Tiger Data = Postgres + TimescaleDB.
# TODO(human): connection-string format lives in /docs/tigerdata.txt.
POSTGRES_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS grid_signals (
  ts TIMESTAMPTZ PRIMARY KEY,
  price_usd_per_mwh DOUBLE PRECISION NOT NULL,
  marginal_gco2_per_kwh DOUBLE PRECISION NOT NULL,
  curtailment_mw DOUBLE PRECISION NOT NULL,
  water_stress_index DOUBLE PRECISION NOT NULL,
  source TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS assets (
  asset_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  it_capacity_kw DOUBLE PRECISION,
  charge_capacity_kw DOUBLE PRECISION,
  wet_extra_kw_per_kw DOUBLE PRECISION,
  dry_extra_kw_per_kw DOUBLE PRECISION,
  wet_water_l_per_kwh DOUBLE PRECISION
)""",
    """CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  checkpointable BOOLEAN NOT NULL,
  asset_id TEXT NOT NULL,
  power_kw DOUBLE PRECISION NOT NULL,
  duration_h DOUBLE PRECISION NOT NULL,
  energy_kwh DOUBLE PRECISION NOT NULL,
  release_ts TIMESTAMPTZ NOT NULL,
  deadline_ts TIMESTAMPTZ NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS schedules (
  schedule_id TEXT PRIMARY KEY,
  schedule_kind TEXT NOT NULL,
  status TEXT NOT NULL,
  alpha DOUBLE PRECISION NOT NULL,
  horizon_start TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  metrics_json JSONB NOT NULL,
  baseline_metrics_json JSONB NOT NULL,
  savings_pct_json JSONB NOT NULL,
  shifted_job_count INTEGER NOT NULL,
  shifted_kwh DOUBLE PRECISION NOT NULL,
  savings_label TEXT NOT NULL,
  explanation TEXT
)""",
    """CREATE TABLE IF NOT EXISTS schedule_slots (
  schedule_id TEXT NOT NULL REFERENCES schedules(schedule_id),
  t INTEGER NOT NULL,
  ts TIMESTAMPTZ NOT NULL,
  cooling_mode TEXT NOT NULL,
  it_load_kw DOUBLE PRECISION NOT NULL,
  yw_kw DOUBLE PRECISION NOT NULL,
  yd_kw DOUBLE PRECISION NOT NULL,
  ev_load_kw DOUBLE PRECISION NOT NULL,
  total_load_kw DOUBLE PRECISION NOT NULL,
  jobs_json JSONB NOT NULL,
  PRIMARY KEY (schedule_id, t)
)""",
    """CREATE TABLE IF NOT EXISTS decision_log (
  log_id TEXT NOT NULL,
  ts TIMESTAMPTZ NOT NULL,
  schedule_id TEXT,
  actor TEXT NOT NULL,
  event TEXT NOT NULL,
  payload_json JSONB NOT NULL,
  PRIMARY KEY (log_id, ts)
)""",
    """CREATE TABLE IF NOT EXISTS telemetry (
  device_id TEXT NOT NULL,
  ts TIMESTAMPTZ NOT NULL,
  power_w DOUBLE PRECISION NOT NULL,
  temp_c DOUBLE PRECISION NOT NULL,
  fan_on BOOLEAN NOT NULL,
  simulated BOOLEAN NOT NULL,
  flagged BOOLEAN NOT NULL DEFAULT FALSE,
  PRIMARY KEY (device_id, ts)
)""",
]

POSTGRES_TIMESCALE = [
    "CREATE EXTENSION IF NOT EXISTS timescaledb",
    "SELECT create_hypertable('decision_log', 'ts', if_not_exists => TRUE)",
    "SELECT create_hypertable('telemetry', 'ts', if_not_exists => TRUE)",
]

POSTGRES_CAGG = """CREATE MATERIALIZED VIEW IF NOT EXISTS telemetry_1m
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT
  time_bucket('1 minute', ts) AS bucket,
  device_id,
  avg(power_w) AS power_w,
  avg(temp_c) AS temp_c,
  bool_or(fan_on) AS fan_on,
  bool_or(simulated) AS simulated
FROM telemetry
WHERE flagged = FALSE
GROUP BY bucket, device_id
WITH NO DATA"""

POSTGRES_CAGG_POLICY = """SELECT add_continuous_aggregate_policy(
  'telemetry_1m',
  start_offset => INTERVAL '1 hour',
  end_offset => INTERVAL '1 minute',
  schedule_interval => INTERVAL '1 minute',
  if_not_exists => TRUE
)"""


def _loads(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _ts(value: Any) -> str:
    return iso(value) if isinstance(value, datetime) else str(value)


def _dict_row(cursor: Any, row: Sequence[Any]) -> dict[str, Any]:
    columns = [col.name if hasattr(col, "name") else col[0] for col in cursor.description]
    return dict(zip(columns, row))


class Database:
    """Shared interface. Concrete stores keep their own connections."""

    kind = "sqlite"

    def setup(self) -> None: ...
    def close(self) -> None: ...
    def replace_inputs(self, signals, jobs, assets) -> None: ...
    def upsert_schedule(self, schedule: Schedule) -> None: ...
    def get_schedule(self, schedule_id: str) -> Optional[Schedule]: ...
    def schedules_with_status(self, status: str) -> list[Schedule]: ...
    def delete_all_schedules(self) -> None: ...
    def insert_log(self, entry: DecisionLogEntry) -> None: ...
    def list_logs(self, limit: int, after: Optional[str]) -> list[DecisionLogEntry]: ...
    def clear_logs(self) -> None: ...
    def insert_telemetry(self, row: TelemetryRow) -> None: ...
    def telemetry_minutes(self, minutes: int, now: datetime) -> list[TelemetryMinute]: ...
    def clear_telemetry(self) -> None: ...
    def reset(self) -> None: ...


class SQLiteStore(Database):
    kind = "sqlite"

    def __init__(self, path: Path | str) -> None:
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()

    def setup(self) -> None:
        with self._lock:
            for statement in SQLITE_SCHEMA:
                self._conn.execute(statement)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def replace_inputs(
        self,
        signals: list[GridSignal],
        jobs: list[Job],
        assets: list[Asset],
    ) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM grid_signals")
            self._conn.execute("DELETE FROM jobs")
            self._conn.execute("DELETE FROM assets")
            self._conn.executemany(
                "INSERT INTO grid_signals VALUES (?,?,?,?,?,?)",
                [
                    (
                        s.ts,
                        s.price_usd_per_mwh,
                        s.marginal_gco2_per_kwh,
                        s.curtailment_mw,
                        s.water_stress_index,
                        s.source,
                    )
                    for s in signals
                ],
            )
            self._conn.executemany(
                "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        j.job_id,
                        j.name,
                        j.kind,
                        int(j.checkpointable),
                        j.asset_id,
                        j.power_kw,
                        j.duration_h,
                        j.energy_kwh,
                        j.release_ts,
                        j.deadline_ts,
                    )
                    for j in jobs
                ],
            )
            self._conn.executemany(
                "INSERT INTO assets VALUES (?,?,?,?,?,?,?,?)",
                [
                    (
                        a.asset_id,
                        a.kind,
                        a.name,
                        a.it_capacity_kw,
                        a.charge_capacity_kw,
                        a.wet_extra_kw_per_kw,
                        a.dry_extra_kw_per_kw,
                        a.wet_water_l_per_kwh,
                    )
                    for a in assets
                ],
            )
            self._conn.commit()

    def upsert_schedule(self, schedule: Schedule) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO schedules VALUES
                   (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    schedule.schedule_id,
                    schedule.schedule_kind,
                    schedule.status,
                    schedule.alpha,
                    schedule.horizon_start,
                    schedule.created_at,
                    json.dumps(schedule.metrics.model_dump()),
                    json.dumps(schedule.baseline_metrics.model_dump()),
                    json.dumps(schedule.savings_pct.model_dump()),
                    schedule.shifted_job_count,
                    schedule.shifted_kwh,
                    schedule.savings_label,
                    schedule.explanation,
                ),
            )
            self._conn.execute(
                "DELETE FROM schedule_slots WHERE schedule_id = ?",
                (schedule.schedule_id,),
            )
            self._conn.executemany(
                "INSERT INTO schedule_slots VALUES (?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        schedule.schedule_id,
                        slot.t,
                        slot.ts,
                        slot.cooling_mode,
                        slot.it_load_kw,
                        slot.yw_kw,
                        slot.yd_kw,
                        slot.ev_load_kw,
                        slot.total_load_kw,
                        json.dumps([j.model_dump() for j in slot.jobs]),
                    )
                    for slot in schedule.slots
                ],
            )
            self._conn.commit()

    def get_schedule(self, schedule_id: str) -> Optional[Schedule]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM schedules WHERE schedule_id = ?",
                (schedule_id,),
            ).fetchone()
            if row is None:
                return None
            slots = self._conn.execute(
                "SELECT * FROM schedule_slots WHERE schedule_id = ? ORDER BY t",
                (schedule_id,),
            ).fetchall()
        return _sqlite_schedule(row, slots)

    def schedules_with_status(self, status: str) -> list[Schedule]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM schedules WHERE status = ? ORDER BY created_at",
                (status,),
            ).fetchall()
            result = []
            for row in rows:
                slots = self._conn.execute(
                    "SELECT * FROM schedule_slots WHERE schedule_id = ? ORDER BY t",
                    (row[0],),
                ).fetchall()
                result.append(_sqlite_schedule(row, slots))
        return result

    def delete_all_schedules(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM schedule_slots")
            self._conn.execute("DELETE FROM schedules")
            self._conn.commit()

    def insert_log(self, entry: DecisionLogEntry) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO decision_log VALUES (?,?,?,?,?,?)",
                (
                    entry.log_id,
                    entry.ts,
                    entry.schedule_id,
                    entry.actor,
                    entry.event,
                    json.dumps(entry.payload),
                ),
            )
            self._conn.commit()

    def list_logs(
        self, limit: int, after: Optional[str]
    ) -> list[DecisionLogEntry]:
        # rowid orders by insertion, which keeps same-millisecond rows in
        # causal order (proposed before approval_requested, and so on).
        with self._lock:
            if after is not None:
                anchor = self._conn.execute(
                    "SELECT rowid FROM decision_log WHERE log_id = ?",
                    (after,),
                ).fetchone()
                if anchor is None:
                    return []
                rows = self._conn.execute(
                    """SELECT * FROM decision_log
                       WHERE rowid > ? ORDER BY rowid LIMIT ?""",
                    (anchor[0], limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM decision_log ORDER BY rowid LIMIT ?",
                    (limit,),
                ).fetchall()
        return [
            DecisionLogEntry(
                log_id=r[0],
                ts=r[1],
                schedule_id=r[2],
                actor=r[3],
                event=r[4],
                payload=_loads(r[5]),
            )
            for r in rows
        ]

    def clear_logs(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM decision_log")
            self._conn.commit()

    def insert_telemetry(self, row: TelemetryRow) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO telemetry VALUES (?,?,?,?,?,?,?)",
                (
                    row.device_id,
                    row.ts,
                    row.power_w,
                    row.temp_c,
                    int(row.fan_on),
                    int(row.simulated),
                    int(row.flagged),
                ),
            )
            self._conn.commit()

    def telemetry_minutes(
        self, minutes: int, now: datetime
    ) -> list[TelemetryMinute]:
        since = iso(now - timedelta(minutes=minutes))
        with self._lock:
            rows = self._conn.execute(
                """SELECT ts, device_id, power_w, temp_c, fan_on, simulated
                   FROM telemetry WHERE flagged = 0 AND ts >= ?""",
                (since,),
            ).fetchall()
        return _aggregate_minutes(
            [
                (r[0], r[1], float(r[2]), float(r[3]), bool(r[4]), bool(r[5]))
                for r in rows
            ]
        )

    def clear_telemetry(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM telemetry")
            self._conn.commit()

    def reset(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM schedule_slots")
            self._conn.execute("DELETE FROM schedules")
            self._conn.execute("DELETE FROM decision_log")
            self._conn.execute("DELETE FROM telemetry")
            self._conn.commit()


def _sqlite_schedule(row: Sequence[Any], slots: Sequence[Sequence[Any]]) -> Schedule:
    return Schedule(
        schedule_id=row[0],
        schedule_kind=row[1],
        status=row[2],
        alpha=row[3],
        horizon_start=row[4],
        created_at=row[5],
        slots=[
            Slot(
                t=s[1],
                ts=s[2],
                cooling_mode=s[3],
                it_load_kw=s[4],
                yw_kw=s[5],
                yd_kw=s[6],
                ev_load_kw=s[7],
                total_load_kw=s[8],
                jobs=_loads(s[9]),
            )
            for s in slots
        ],
        metrics=_loads(row[6]),
        baseline_metrics=_loads(row[7]),
        savings_pct=_loads(row[8]),
        shifted_job_count=row[9],
        shifted_kwh=row[10],
        savings_label=row[11],
        explanation=row[12],
    )


def _aggregate_minutes(
    rows: list[tuple[str, str, float, float, bool, bool]],
) -> list[TelemetryMinute]:
    """Group non-flagged rows into SPEC TelemetryMinute buckets."""
    buckets: dict[tuple[str, str], list[tuple[float, float, bool, bool]]] = {}
    for ts, device_id, power_w, temp_c, fan_on, simulated in rows:
        minute = parse_ts(ts).replace(second=0, microsecond=0)
        key = (iso(minute), device_id)
        buckets.setdefault(key, []).append((power_w, temp_c, fan_on, simulated))
    items = []
    for (bucket, device_id), samples in sorted(buckets.items()):
        items.append(
            TelemetryMinute(
                bucket=bucket,
                device_id=device_id,
                power_w=round(sum(s[0] for s in samples) / len(samples), 6),
                temp_c=round(sum(s[1] for s in samples) / len(samples), 6),
                fan_on=any(s[2] for s in samples),
                simulated=any(s[3] for s in samples),
            )
        )
    return items


class PostgresStore(Database):
    """SPEC section 8 Postgres block. Requires psycopg (optional dep).

    TimescaleDB features are attempted in order; each failure drops that
    feature and keeps the plain tables (SPEC: keep serving plus Python
    aggregation).
    """

    kind = "postgres"

    def __init__(self, url: str) -> None:
        import psycopg

        self._psycopg = psycopg
        self._conn = psycopg.connect(url, connect_timeout=5, autocommit=True)
        self._lock = threading.Lock()
        self.cagg_available = False
        self.timescale_errors: list[str] = []

    @classmethod
    def connect(cls, url: str) -> "PostgresStore":
        """5-second connect timeout, one retry (SPEC section 8)."""
        try:
            return cls(url)
        except Exception:
            return cls(url)  # second attempt; a failure here propagates

    def setup(self) -> None:
        with self._lock:
            for statement in POSTGRES_SCHEMA:
                self._conn.execute(statement)
            self._setup_timescale()

    def _setup_timescale(self) -> None:
        try:
            for statement in POSTGRES_TIMESCALE:
                self._conn.execute(statement)
        except Exception as exc:
            self.timescale_errors.append(f"hypertable: {exc}")
            return
        for ddl in (POSTGRES_CAGG, POSTGRES_CAGG_POLICY):
            try:
                self._conn.execute(ddl)
            except Exception as exc:
                self.timescale_errors.append(f"telemetry_1m: {exc}")
                return
        self.cagg_available = True

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _all(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        cursor = self._conn.execute(sql, params)
        return [_dict_row(cursor, row) for row in cursor.fetchall()]

    def _one(self, sql: str, params: Sequence[Any] = ()) -> Optional[dict[str, Any]]:
        rows = self._all(sql, params)
        return rows[0] if rows else None

    def replace_inputs(
        self,
        signals: list[GridSignal],
        jobs: list[Job],
        assets: list[Asset],
    ) -> None:
        with self._lock, self._conn.transaction():
            self._conn.execute("DELETE FROM grid_signals")
            self._conn.execute("DELETE FROM jobs")
            self._conn.execute("DELETE FROM assets")
            for s in signals:
                self._conn.execute(
                    "INSERT INTO grid_signals VALUES (%s,%s,%s,%s,%s,%s)",
                    (
                        parse_ts(s.ts),
                        s.price_usd_per_mwh,
                        s.marginal_gco2_per_kwh,
                        s.curtailment_mw,
                        s.water_stress_index,
                        s.source,
                    ),
                )
            for j in jobs:
                self._conn.execute(
                    "INSERT INTO jobs VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        j.job_id,
                        j.name,
                        j.kind,
                        j.checkpointable,
                        j.asset_id,
                        j.power_kw,
                        j.duration_h,
                        j.energy_kwh,
                        parse_ts(j.release_ts),
                        parse_ts(j.deadline_ts),
                    ),
                )
            for a in assets:
                self._conn.execute(
                    "INSERT INTO assets VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        a.asset_id,
                        a.kind,
                        a.name,
                        a.it_capacity_kw,
                        a.charge_capacity_kw,
                        a.wet_extra_kw_per_kw,
                        a.dry_extra_kw_per_kw,
                        a.wet_water_l_per_kwh,
                    ),
                )

    def upsert_schedule(self, schedule: Schedule) -> None:
        from psycopg.types.json import Jsonb

        with self._lock, self._conn.transaction():
            self._conn.execute(
                "DELETE FROM schedule_slots WHERE schedule_id = %s",
                (schedule.schedule_id,),
            )
            self._conn.execute(
                """INSERT INTO schedules VALUES
                   (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (schedule_id) DO UPDATE SET
                   schedule_kind=EXCLUDED.schedule_kind,
                   status=EXCLUDED.status, alpha=EXCLUDED.alpha,
                   horizon_start=EXCLUDED.horizon_start,
                   created_at=EXCLUDED.created_at,
                   metrics_json=EXCLUDED.metrics_json,
                   baseline_metrics_json=EXCLUDED.baseline_metrics_json,
                   savings_pct_json=EXCLUDED.savings_pct_json,
                   shifted_job_count=EXCLUDED.shifted_job_count,
                   shifted_kwh=EXCLUDED.shifted_kwh,
                   savings_label=EXCLUDED.savings_label,
                   explanation=EXCLUDED.explanation""",
                (
                    schedule.schedule_id,
                    schedule.schedule_kind,
                    schedule.status,
                    schedule.alpha,
                    parse_ts(schedule.horizon_start),
                    parse_ts(schedule.created_at),
                    Jsonb(schedule.metrics.model_dump()),
                    Jsonb(schedule.baseline_metrics.model_dump()),
                    Jsonb(schedule.savings_pct.model_dump()),
                    schedule.shifted_job_count,
                    schedule.shifted_kwh,
                    schedule.savings_label,
                    schedule.explanation,
                ),
            )
            for slot in schedule.slots:
                self._conn.execute(
                    "INSERT INTO schedule_slots VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        schedule.schedule_id,
                        slot.t,
                        parse_ts(slot.ts),
                        slot.cooling_mode,
                        slot.it_load_kw,
                        slot.yw_kw,
                        slot.yd_kw,
                        slot.ev_load_kw,
                        slot.total_load_kw,
                        Jsonb([j.model_dump() for j in slot.jobs]),
                    ),
                )

    def _schedule_from_rows(
        self, row: dict[str, Any], slots: list[dict[str, Any]]
    ) -> Schedule:
        return Schedule(
            schedule_id=row["schedule_id"],
            schedule_kind=row["schedule_kind"],
            status=row["status"],
            alpha=row["alpha"],
            horizon_start=_ts(row["horizon_start"]),
            created_at=_ts(row["created_at"]),
            slots=[
                Slot(
                    t=s["t"],
                    ts=_ts(s["ts"]),
                    cooling_mode=s["cooling_mode"],
                    it_load_kw=s["it_load_kw"],
                    yw_kw=s["yw_kw"],
                    yd_kw=s["yd_kw"],
                    ev_load_kw=s["ev_load_kw"],
                    total_load_kw=s["total_load_kw"],
                    jobs=_loads(s["jobs_json"]),
                )
                for s in slots
            ],
            metrics=_loads(row["metrics_json"]),
            baseline_metrics=_loads(row["baseline_metrics_json"]),
            savings_pct=_loads(row["savings_pct_json"]),
            shifted_job_count=row["shifted_job_count"],
            shifted_kwh=row["shifted_kwh"],
            savings_label=row["savings_label"],
            explanation=row["explanation"],
        )

    def _slots_for(self, schedule_id: str) -> list[dict[str, Any]]:
        return self._all(
            "SELECT * FROM schedule_slots WHERE schedule_id = %s ORDER BY t",
            (schedule_id,),
        )

    def get_schedule(self, schedule_id: str) -> Optional[Schedule]:
        with self._lock:
            row = self._one(
                "SELECT * FROM schedules WHERE schedule_id = %s", (schedule_id,)
            )
            if row is None:
                return None
            slots = self._slots_for(schedule_id)
        return self._schedule_from_rows(row, slots)

    def schedules_with_status(self, status: str) -> list[Schedule]:
        with self._lock:
            rows = self._all(
                "SELECT * FROM schedules WHERE status = %s ORDER BY created_at",
                (status,),
            )
            return [
                self._schedule_from_rows(row, self._slots_for(row["schedule_id"]))
                for row in rows
            ]

    def delete_all_schedules(self) -> None:
        with self._lock, self._conn.transaction():
            self._conn.execute("DELETE FROM schedule_slots")
            self._conn.execute("DELETE FROM schedules")

    def insert_log(self, entry: DecisionLogEntry) -> None:
        from psycopg.types.json import Jsonb

        with self._lock:
            self._conn.execute(
                "INSERT INTO decision_log VALUES (%s,%s,%s,%s,%s,%s)",
                (
                    entry.log_id,
                    parse_ts(entry.ts),
                    entry.schedule_id,
                    entry.actor,
                    entry.event,
                    Jsonb(entry.payload),
                ),
            )

    def list_logs(
        self, limit: int, after: Optional[str]
    ) -> list[DecisionLogEntry]:
        with self._lock:
            if after is not None:
                anchor = self._one(
                    "SELECT ts, log_id FROM decision_log WHERE log_id = %s",
                    (after,),
                )
                if anchor is None:
                    return []
                rows = self._all(
                    """SELECT * FROM decision_log
                       WHERE ts > %s OR (ts = %s AND log_id > %s)
                       ORDER BY ts, log_id LIMIT %s""",
                    (anchor["ts"], anchor["ts"], anchor["log_id"], limit),
                )
            else:
                rows = self._all(
                    "SELECT * FROM decision_log ORDER BY ts, log_id LIMIT %s",
                    (limit,),
                )
        return [
            DecisionLogEntry(
                log_id=r["log_id"],
                ts=_ts(r["ts"]),
                schedule_id=r["schedule_id"],
                actor=r["actor"],
                event=r["event"],
                payload=_loads(r["payload_json"]),
            )
            for r in rows
        ]

    def clear_logs(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM decision_log")

    def insert_telemetry(self, row: TelemetryRow) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO telemetry VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (device_id, ts) DO UPDATE SET
                   power_w=EXCLUDED.power_w, temp_c=EXCLUDED.temp_c""",
                (
                    row.device_id,
                    parse_ts(row.ts),
                    row.power_w,
                    row.temp_c,
                    row.fan_on,
                    row.simulated,
                    row.flagged,
                ),
            )

    def telemetry_minutes(
        self, minutes: int, now: datetime
    ) -> list[TelemetryMinute]:
        since = now - timedelta(minutes=minutes)
        with self._lock:
            if self.cagg_available:
                try:
                    rows = self._all(
                        """SELECT bucket, device_id, power_w, temp_c,
                                  fan_on, simulated
                           FROM telemetry_1m WHERE bucket >= %s
                           ORDER BY bucket""",
                        (since,),
                    )
                    return [
                        TelemetryMinute(
                            bucket=_ts(r["bucket"]),
                            device_id=r["device_id"],
                            power_w=float(r["power_w"]),
                            temp_c=float(r["temp_c"]),
                            fan_on=bool(r["fan_on"]),
                            simulated=bool(r["simulated"]),
                        )
                        for r in rows
                    ]
                except Exception:
                    self.cagg_available = False
            raw = self._all(
                """SELECT ts, device_id, power_w, temp_c, fan_on, simulated
                   FROM telemetry WHERE flagged = FALSE AND ts >= %s""",
                (since,),
            )
        return _aggregate_minutes(
            [
                (
                    _ts(r["ts"]),
                    r["device_id"],
                    float(r["power_w"]),
                    float(r["temp_c"]),
                    bool(r["fan_on"]),
                    bool(r["simulated"]),
                )
                for r in raw
            ]
        )

    def clear_telemetry(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM telemetry")

    def reset(self) -> None:
        with self._lock, self._conn.transaction():
            self._conn.execute("DELETE FROM schedule_slots")
            self._conn.execute("DELETE FROM schedules")
            self._conn.execute("DELETE FROM decision_log")
            self._conn.execute("DELETE FROM telemetry")


def sqlite_path_from_url(database_url: str) -> Path | str:
    """Empty -> backend/.local/gridpulse.db. sqlite:///PATH -> PATH."""
    if not database_url:
        path = BACKEND_DIR / ".local" / "gridpulse.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    raw = database_url[len("sqlite:///"):]
    if raw == ":memory:":
        return ":memory:"
    path = Path(raw)
    if not path.is_absolute():
        path = BACKEND_DIR / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def open_database(config_url: str) -> tuple[Database, Optional[str]]:
    """Postgres when the URL says so, with one retry then SQLite fallback.

    Returns (store, error_message_or_None). The caller writes the
    decision-log error for integration tigerdata on fallback.
    """
    if config_url.startswith(("postgres://", "postgresql://")):
        try:
            store = PostgresStore.connect(config_url)
            store.setup()
            return store, None
        except Exception as exc:
            store = SQLiteStore(sqlite_path_from_url(""))
            store.setup()
            return store, f"postgres connect/setup failed: {exc}"
    store = SQLiteStore(sqlite_path_from_url(config_url))
    store.setup()
    return store, None
