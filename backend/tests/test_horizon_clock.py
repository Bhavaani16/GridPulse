"""Horizon rebase follows backend.clock.now_utc, including across local midnight."""

from __future__ import annotations

from config import Config
from signals import load_inputs


def test_horizon_follows_patched_now_utc_across_local_midnight(monkeypatch) -> None:
    config = Config(
        horizon_mode="today",
        horizon_tz="America/Los_Angeles",
        ev_force_deadline="2026-06-21T21:00:00Z",
    )

    monkeypatch.setattr("clock.now_utc", lambda: "2026-10-18T17:00:00.000Z")
    before, _, _, _, _ = load_inputs(config)
    assert before[0].ts == "2026-10-18T07:00:00Z"

    # 07:30Z is 00:30 in Los Angeles on the next local date (PDT, UTC-7).
    monkeypatch.setattr("clock.now_utc", lambda: "2026-10-19T07:30:00.000Z")
    after, _, _, deadline, _ = load_inputs(config)
    assert after[0].ts == "2026-10-19T07:00:00Z"
    assert deadline == "2026-10-19T21:00:00Z"
