"""Gemini explanation tests (SPEC section 16: GEM-1 through GEM-4, plus
the task's GEM-5 — an empty model body falls back to the template).

Tests run against a real app on a fresh SQLite file so schedules,
signals, and the decision log are real. The "client" is the module-level
integrations.gemini._generate_model_text seam, monkeypatched in every
live-mode test; nothing opens a socket. _live_block_reason is patched to
None so the seam is reached without /docs/gemini.txt.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import integrations.gemini as gemini
from state import get_state

VALID_TEXT = "alpha 0.5 moved load into cleaner hours."


def _make_app(
    tmp_path,
    monkeypatch,
    mode: str = "live",
    model: str = "gemini-test-model",
) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'g.db'}")
    monkeypatch.setenv("START_SIMULATOR", "0")
    monkeypatch.setenv("GEMINI_MODE", mode)
    monkeypatch.setenv("GEMINI_MODEL", model)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    from main import create_app

    return TestClient(create_app())


def _optimized(client: TestClient):
    """A real optimized schedule plus signals and the baseline row."""
    body = client.post("/api/optimize", json={"alpha": 0.5}).json()
    state = get_state()
    schedule = state.db.get_schedule(body["schedule_id"])
    baseline = state.db.get_schedule("sch-baseline")
    assert schedule is not None and baseline is not None
    return schedule, state.signals, baseline


@pytest.fixture()
def live_client(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini, "_live_block_reason", lambda: None)
    gemini.clear_cache()
    with _make_app(tmp_path, monkeypatch, mode="live") as client:
        yield client
    gemini.clear_cache()


def _gemini_errors() -> list:
    state = get_state()
    return [
        row
        for row in state.db.list_logs(200, None)
        if row.event == "error" and row.payload.get("integration") == "gemini"
    ]


def test_gem1_client_timeout_returns_template(live_client, monkeypatch):
    calls = []

    def fake(summary):
        calls.append(summary)
        raise TimeoutError("simulated timeout")

    monkeypatch.setattr(gemini, "_generate_model_text", fake)
    schedule, signals, prev = _optimized(live_client)
    text, source = gemini.explain_with_source(schedule, signals, prev)
    assert source == "fallback"
    assert text == gemini._template_text(schedule)
    assert len(calls) == 2  # the one allowed retry ran
    assert _gemini_errors()


def test_gem2_invented_number_is_discarded(live_client, monkeypatch):
    monkeypatch.setattr(
        gemini,
        "_generate_model_text",
        lambda summary: "This schedule saves 99999 dollars.",
    )
    schedule, signals, prev = _optimized(live_client)
    text, source = gemini.explain_with_source(schedule, signals, prev)
    assert source == "fallback"
    assert text == gemini._template_text(schedule)


def test_gem3_cache_hit_skips_client(live_client, monkeypatch):
    calls = []

    def fake(summary):
        calls.append(summary)
        return VALID_TEXT

    monkeypatch.setattr(gemini, "_generate_model_text", fake)
    schedule, signals, prev = _optimized(live_client)
    first_text, first_source = gemini.explain_with_source(
        schedule, signals, prev
    )
    second_text, second_source = gemini.explain_with_source(
        schedule, signals, prev
    )
    assert first_source == "gemini"
    assert second_source == "cache"
    assert first_text == second_text == VALID_TEXT
    assert len(calls) == 1


def test_gem4_at_most_three_periods(live_client, monkeypatch):
    monkeypatch.setattr(
        gemini,
        "_generate_model_text",
        lambda summary: "Costs fell. Carbon fell. Water fell.",
    )
    schedule, signals, prev = _optimized(live_client)
    text, source = gemini.explain_with_source(schedule, signals, prev)
    assert source == "gemini"
    assert text.count(".") <= 3


def test_gem5_empty_body_returns_template(live_client, monkeypatch):
    monkeypatch.setattr(
        gemini, "_generate_model_text", lambda summary: "   "
    )
    schedule, signals, prev = _optimized(live_client)
    text, source = gemini.explain_with_source(schedule, signals, prev)
    assert source == "fallback"
    assert text == gemini._template_text(schedule)


def test_mock_mode_never_calls_client(tmp_path, monkeypatch):
    def boom(summary):
        raise AssertionError("client called in mock mode")

    monkeypatch.setattr(gemini, "_generate_model_text", boom)
    gemini.clear_cache()
    with _make_app(tmp_path, monkeypatch, mode="mock") as client:
        schedule, signals, prev = _optimized(client)
        text, source = gemini.explain_with_source(schedule, signals, prev)
        assert source == "fallback"
        assert text == gemini._template_text(schedule)
    gemini.clear_cache()


def test_summary_object_and_instruction(live_client, monkeypatch):
    sent = []

    def fake(summary):
        sent.append(summary)
        return VALID_TEXT

    monkeypatch.setattr(gemini, "_generate_model_text", fake)
    schedule, signals, prev = _optimized(live_client)
    gemini.explain_with_source(schedule, signals, prev)
    assert len(sent) == 1
    summary = sent[0]
    assert set(summary) == {
        "alpha",
        "shifted_jobs",
        "drivers",
        "cooling_dry_hours",
        "savings_pct",
        "metrics",
    }
    assert summary["alpha"] == 0.5
    assert summary["drivers"][0] == {
        "name": "curtailment_mw",
        "hour": 10,
        "value": 250.0,
    }
    assert summary["drivers"][1] == {
        "name": "marginal_gco2_per_kwh",
        "hour": 18,
        "value": 420.0,
    }
    assert len(summary["shifted_jobs"]) == schedule.shifted_job_count
    base = {s.t: s for s in prev.slots}
    mine = {s.t: s for s in schedule.slots}
    for entry in summary["shifted_jobs"]:
        job_id = entry["job_id"]
        assert entry["from_hours"] == [
            t
            for t, slot in base.items()
            if any(
                j.job_id == job_id and j.fraction > 0 for j in slot.jobs
            )
        ]
        assert entry["to_hours"] == [
            t
            for t, slot in mine.items()
            if any(
                j.job_id == job_id and j.fraction > 0 for j in slot.jobs
            )
        ]
    assert summary["savings_pct"]["cost"] == schedule.savings_pct.cost
    assert summary["metrics"]["cost_usd"] == schedule.metrics.cost_usd
    assert gemini.INSTRUCTION == (
        "Write 2 or 3 plain sentences. Mention the carbon versus water "
        "trade-off at this alpha. Use only numbers that appear in the "
        "summary. Do not use markdown."
    )


def test_explain_endpoint_stores_and_logs(tmp_path, monkeypatch):
    gemini.clear_cache()
    with _make_app(tmp_path, monkeypatch, mode="mock") as client:
        body = client.post("/api/optimize", json={"alpha": 0.5}).json()
        sid = body["schedule_id"]
        first = client.get(f"/api/explain/{sid}").json()
        assert first["schedule_id"] == sid
        assert first["source"] == "fallback"
        assert len(first["text"]) > 0
        stored = client.get(f"/api/schedules/{sid}").json()
        assert stored["explanation"] == first["text"]
        again = client.get(f"/api/explain/{sid}").json()
        assert again["source"] == "cache"
        events = client.get("/api/decisions", params={"limit": 200}).json()[
            "items"
        ]
        entries = [
            e
            for e in events
            if e["event"] == "explanation" and e["schedule_id"] == sid
        ]
        assert entries
        assert all(e["actor"] == "gemini" for e in entries)
        assert entries[0]["payload"]["text"] == first["text"]
    gemini.clear_cache()


def test_live_unconfigured_logs_error(tmp_path, monkeypatch):
    """GEMINI_MODE=live with no /docs/gemini.txt: template + error log."""
    calls = []

    def boom(summary):
        calls.append(summary)
        raise AssertionError("client called while unconfigured")

    monkeypatch.setattr(gemini, "_generate_model_text", boom)
    gemini.clear_cache()
    with _make_app(
        tmp_path, monkeypatch, mode="live", model=""
    ) as client:
        schedule, signals, prev = _optimized(client)
        text, source = gemini.explain_with_source(schedule, signals, prev)
        assert source == "fallback"
        assert text == gemini._template_text(schedule)
        assert calls == []
        assert _gemini_errors()
    gemini.clear_cache()
