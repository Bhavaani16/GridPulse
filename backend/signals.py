"""Data replay: load the cached horizon and apply the HORIZON_MODE rebase.

MODE=cached reads /data/signals_cached.csv rows 0..23 plus jobs.json and
assets.json. MODE=live calls data_tools.fetch_live_signals() and falls back
to the cached rows on error (the caller logs the decision-log error).

HORIZON_MODE=fixed keeps timestamps as written. HORIZON_MODE=today shifts
every loaded timestamp by one constant offset so horizon_start becomes
local midnight in HORIZON_TZ of the current local date, expressed in UTC
(SPEC section 4). Files on disk are never modified.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from config import DISK_HORIZON_START, Config
from optimizer.models import Asset, GridSignal, Job, parse_hour_ts

HORIZON = 24


def _offset_seconds(config: Config) -> float:
    """today: local midnight now in HORIZON_TZ minus the on-disk start."""
    if config.horizon_mode == "fixed":
        return 0.0
    local_midnight = datetime.now(ZoneInfo(config.horizon_tz)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    new_start = local_midnight.astimezone(timezone.utc)
    old_start = parse_hour_ts(DISK_HORIZON_START)
    offset = (new_start - old_start).total_seconds()
    # Non-hour-aligned zones cannot produce hour-aligned timestamps; snap
    # to the nearest hour so the horizon stays slot-shaped.
    return round(offset / 3600.0) * 3600.0


def _shift(ts: str, offset: timedelta) -> str:
    moved = parse_hour_ts(ts) + offset
    return moved.strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_cached(data_dir: Path) -> list[GridSignal]:
    signals: list[GridSignal] = []
    with (data_dir / "signals_cached.csv").open(newline="") as handle:
        for row in csv.DictReader(handle):
            signals.append(
                GridSignal(
                    ts=row["ts"],
                    price_usd_per_mwh=float(row["price_usd_per_mwh"]),
                    marginal_gco2_per_kwh=float(row["marginal_gco2_per_kwh"]),
                    curtailment_mw=float(row["curtailment_mw"]),
                    water_stress_index=float(row["water_stress_index"]),
                    source=row["source"],  # type: ignore[arg-type]
                )
            )
            if len(signals) == HORIZON:
                break
    if len(signals) != HORIZON:
        raise ValueError(f"signals_cached.csv needs {HORIZON} hourly rows")
    return signals


def _read_json(data_dir: Path) -> tuple[list[Job], list[Asset]]:
    jobs = [
        Job.model_validate(item)
        for item in json.loads((data_dir / "jobs.json").read_text())
    ]
    assets = [
        Asset.model_validate(item)
        for item in json.loads((data_dir / "assets.json").read_text())
    ]
    return jobs, assets


def validate_inputs(config: Config) -> None:
    """Parse the on-disk inputs. Raises when they fail validation.

    Called at app creation so the process exits before serving; the real
    load (with the rebase) happens in lifespan via load_inputs.
    """
    signals = _read_cached(config.data_dir)
    jobs, assets = _read_json(config.data_dir)
    for signal in signals:
        parse_hour_ts(signal.ts)
    for job in jobs:
        parse_hour_ts(job.release_ts)
        parse_hour_ts(job.deadline_ts)


def load_inputs(
    config: Config,
) -> tuple[list[GridSignal], list[Job], list[Asset], str, Optional[str]]:
    """Return (signals, jobs, assets, ev_force_deadline, error_or_none).

    On MODE=live a fetch failure returns the cached rows and a message for
    the decision-log error event. Raises on invalid on-disk data (startup
    exits 1 per SPEC section 6).
    """
    error: Optional[str] = None
    signals = _read_cached(config.data_dir)
    jobs, assets = _read_json(config.data_dir)
    if config.mode == "live":
        try:
            from data_tools.live import fetch_live_signals

            live = fetch_live_signals()[:HORIZON]
            signals = [
                s if isinstance(s, GridSignal) else GridSignal.model_validate(s)
                for s in live
            ]
        except Exception as exc:
            error = f"fetch_live_signals failed: {exc}"

    offset = timedelta(seconds=_offset_seconds(config))
    if offset:
        signals = [
            signal.model_copy(update={"ts": _shift(signal.ts, offset)})
            for signal in signals
        ]
        jobs = [
            job.model_copy(
                update={
                    "release_ts": _shift(job.release_ts, offset),
                    "deadline_ts": _shift(job.deadline_ts, offset),
                }
            )
            for job in jobs
        ]
        ev_deadline = _shift(config.ev_force_deadline, offset)
    else:
        ev_deadline = config.ev_force_deadline
    return signals, jobs, assets, ev_deadline, error
