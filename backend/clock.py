"""The backend reads the current time only through now_utc / now_dt.

Tests patch these functions. Log and telemetry timestamps may carry
milliseconds (SPEC section 4); hour boundaries stay second-aligned.
"""

from __future__ import annotations

from datetime import datetime, timezone


def now_utc() -> str:
    """The only place the backend reads the wall clock (SPEC section 4)."""
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{stamp}.{now.microsecond // 1000:03d}Z"


def now_dt() -> datetime:
    return parse_ts(now_utc())


def iso(dt: datetime) -> str:
    """Format an aware datetime as YYYY-MM-DDTHH:MM:SSZ (millis if present)."""
    utc = dt.astimezone(timezone.utc)
    stamp = utc.strftime("%Y-%m-%dT%H:%M:%S")
    if utc.microsecond:
        return f"{stamp}.{utc.microsecond // 1000:03d}Z"
    return f"{stamp}Z"


def parse_ts(value: str) -> datetime:
    """Parse a UTC ISO-8601 string, with or without milliseconds."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )
