"""Telemetry ingest and the fan command rule (SPEC sections 5.6 and 9).

The fan command is a function of the applied schedule only. The 'now' for
POST /api/telemetry is the body's ts, not the server clock.
"""

from __future__ import annotations

from datetime import timedelta

import clock
from decision_log import write_log
from models import Telemetry, TelemetryMinute, TelemetryRow
from optimizer.models import Schedule
from state import AppState

POWER_W_RANGE = (0.0, 500.0)
TEMP_C_RANGE = (-20.0, 120.0)


def fan_command(applied: Schedule | None, ts: str) -> bool:
    """SPEC section 9. True unless the covering slot cools wet."""
    if applied is None:
        return True
    when = clock.parse_ts(ts)
    for slot in applied.slots:
        start = clock.parse_ts(slot.ts)
        if start <= when < start + timedelta(hours=1):
            return slot.cooling_mode == "dry"
    return True


def ingest(state: AppState, body: Telemetry) -> dict:
    """Store one telemetry row and return {"command": {"fan_on": bool}}."""
    flagged = not (
        POWER_W_RANGE[0] <= body.power_w <= POWER_W_RANGE[1]
        and TEMP_C_RANGE[0] <= body.temp_c <= TEMP_C_RANGE[1]
    )
    row = TelemetryRow(**body.model_dump(), flagged=flagged)
    state.db.insert_telemetry(row)
    if flagged:
        write_log(
            None,
            "simulator" if body.simulated else "system",
            "telemetry_flagged",
            {
                "device_id": body.device_id,
                "power_w": body.power_w,
                "temp_c": body.temp_c,
            },
        )
    applied_rows = state.db.schedules_with_status("applied")
    applied = applied_rows[0] if applied_rows else None
    return {"command": {"fan_on": fan_command(applied, body.ts)}}


def recent_minutes(state: AppState, minutes: int) -> list[TelemetryMinute]:
    minutes = max(1, min(minutes, 60))
    return state.db.telemetry_minutes(minutes, clock.now_dt())
