"""Clock for schedule ids. Tests patch now_utc so runs stay repeatable."""

from __future__ import annotations

from datetime import datetime, timezone


def now_utc() -> str:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")
