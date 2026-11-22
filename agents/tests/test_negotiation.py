"""SPEC section 16 agent tests: AG-1 through AG-4 plus flow coverage.

Every test drives the real bridge negotiate() against a real AppState, so
the negotiation_msg decision-log rows are the actual rows the API serves.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from agents.envelope import AgentEnvelope
from agents.tests.conftest import (
    EV_DEADLINE,
    error_rows,
    make_schedule,
    negotiation_rows,
)


def _counting_optimize(state):
    """Wrap state.optimize_fn; returns (calls, wrapper)."""
    real = state.optimize_fn
    calls = []

    def wrapper(signals, jobs, assets, alpha, constraints=None):
        calls.append(constraints)
        return real(signals, jobs, assets, alpha, constraints)

    return calls, wrapper


def _envelopes(state):
    return [entry.payload for entry in negotiation_rows(state)]


# AG-1. A schedule whose IT load is at most DC_MAX_IT_KW and whose EV
# fractions are all before EV_FORCE_DEADLINE gets two accept replies and
# is returned unchanged.
def test_ag1_accepts_return_schedule_unchanged(app_state):
    from integrations.agents_bridge import negotiate

    calls, app_state.optimize_fn = _counting_optimize(app_state)
    schedule = make_schedule(app_state.signals, ev_fracs={0: 1.0, 1: 1.0})

    result = negotiate(schedule)

    assert result is schedule
    assert calls == []
    envelopes = _envelopes(app_state)
    types = [e["type"] for e in envelopes]
    assert types.count("inform") == 1
    assert types.count("propose") == 2
    assert types.count("accept") == 2
    assert "counter" not in types
    senders = {e["from"] for e in envelopes if e["type"] == "accept"}
    assert senders == {"dc-agent", "ev-agent"}
    assert error_rows(app_state) == []


# AG-2. A schedule with one slot it_load_kw 8 and default DC_MAX_IT_KW 6
# produces a counter and one optimize call.
def test_ag2_overloaded_slot_counters_and_reoptimizes(app_state):
    from integrations.agents_bridge import negotiate

    calls, app_state.optimize_fn = _counting_optimize(app_state)
    schedule = make_schedule(
        app_state.signals, it_loads={5: 8.0}, ev_fracs={0: 1.0}
    )

    result = negotiate(schedule)

    assert len(calls) == 1
    constraints = calls[0]
    assert constraints.max_it_kw == app_state.config.dc_max_it_kw == 6.0
    counters = [
        e for e in _envelopes(app_state) if e["type"] == "counter"
    ]
    dc_counters = [e for e in counters if e["from"] == "dc-agent"]
    assert dc_counters
    assert dc_counters[0]["body"] == {
        "constraint": "max_it_kw",
        "max_it_kw": 6.0,
        "reason": "dc thermal limit",
    }
    # The returned schedule is the re-optimized round-2 schedule, and it
    # respects the merged constraint.
    assert result.schedule_id != schedule.schedule_id
    assert all(s.it_load_kw <= 6.0 + 1e-4 for s in result.slots)


# AG-3. A second round of counters does not call optimize again.
def test_ag3_round_2_counters_do_not_reoptimize(app_state):
    from integrations.agents_bridge import negotiate

    schedule = make_schedule(app_state.signals, it_loads={5: 8.0})
    calls = []

    def echo(signals, jobs, assets, alpha, constraints=None):
        calls.append(constraints)
        return schedule  # still violates -> round-2 counter

    app_state.optimize_fn = echo

    result = negotiate(schedule)

    assert len(calls) == 1
    assert result is schedule
    counters = [
        e for e in _envelopes(app_state) if e["type"] == "counter"
    ]
    assert len(counters) >= 2  # one per round


# AG-4. A bridge exception returns the input schedule and writes error.
def test_ag4_exception_returns_input_and_logs_error(app_state, monkeypatch):
    import integrations.agents_bridge as bridge

    def boom(schedule, deps):
        raise RuntimeError("agent exploded")

    monkeypatch.setattr(bridge, "run_negotiation", boom)
    schedule = make_schedule(app_state.signals)

    result = bridge.negotiate(schedule)

    assert result is schedule
    errors = error_rows(app_state)
    assert any(e.payload["integration"] == "agents" for e in errors)


def test_ag4_timeout_returns_input_and_logs_error(app_state, monkeypatch):
    import integrations.agents_bridge as bridge

    def slow(schedule, deps):
        time.sleep(1.0)
        return schedule

    monkeypatch.setattr(bridge, "run_negotiation", slow)
    monkeypatch.setattr(bridge, "NEGOTIATION_TIMEOUT_SECONDS", 0.2)
    schedule = make_schedule(app_state.signals)

    started = time.monotonic()
    result = bridge.negotiate(schedule)
    elapsed = time.monotonic() - started

    assert result is schedule
    assert elapsed < 1.0
    errors = error_rows(app_state)
    assert any(e.payload["integration"] == "agents" for e in errors)


def test_ev_deadline_counter_merges_job_deadline(app_state):
    from integrations.agents_bridge import negotiate

    calls, app_state.optimize_fn = _counting_optimize(app_state)
    # t=14 is 2026-06-21T21:00:00Z == EV_FORCE_DEADLINE -> violation.
    schedule = make_schedule(app_state.signals, ev_fracs={14: 1.0})

    result = negotiate(schedule)

    assert len(calls) == 1
    assert calls[0].job_deadlines == {"job-ev-01": EV_DEADLINE}
    ev_counters = [
        e
        for e in _envelopes(app_state)
        if e["type"] == "counter" and e["from"] == "ev-agent"
    ]
    assert ev_counters[0]["body"] == {
        "constraint": "ev_deadline",
        "job_id": "job-ev-01",
        "deadline_ts": EV_DEADLINE,
        "reason": "minimum charge deadline",
    }
    assert result.schedule_id != schedule.schedule_id


def test_inform_body_matches_signals(app_state):
    from integrations.agents_bridge import negotiate

    schedule = make_schedule(app_state.signals, ev_fracs={0: 1.0})
    negotiate(schedule)

    informs = [
        e for e in _envelopes(app_state) if e["type"] == "inform"
    ]
    assert len(informs) == 1
    body = informs[0]["body"]
    threshold = app_state.config.curtailment_surplus_mw
    assert body["curtailment_mw_min"] == threshold
    qualifying = [
        s for s in app_state.signals if s.curtailment_mw >= threshold
    ]
    if qualifying:
        assert body["surplus_start"] == qualifying[0].ts
        last = datetime.fromisoformat(
            qualifying[-1].ts.replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        expected_end = (last + timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        assert body["surplus_end"] == expected_end
    else:
        assert body["surplus_start"] is None
        assert body["surplus_end"] is None


def test_envelope_from_alias_roundtrip():
    envelope = AgentEnvelope(
        from_="dc-agent",
        to="bridge",
        type="counter",
        schedule_id="sch-x",
        body={
            "constraint": "max_it_kw",
            "max_it_kw": 6.0,
            "reason": "dc thermal limit",
        },
    )
    payload = envelope.model_dump(by_alias=True)
    assert payload["from"] == "dc-agent"
    assert "from_" not in payload
    assert set(payload) == {
        "msg_id",
        "from",
        "to",
        "type",
        "schedule_id",
        "body",
    }
    assert payload["msg_id"].startswith("msg-")
    assert len(payload["msg_id"]) == 16
    reparsed = AgentEnvelope.model_validate(payload)
    assert reparsed.from_ == "dc-agent"


def test_malformed_reply_logged_and_not_executed(app_state, monkeypatch):
    import agents.negotiation as negotiation
    from integrations.agents_bridge import negotiate

    monkeypatch.setattr(
        negotiation,
        "dc_agent_reply",
        lambda schedule, limit: {"bogus": True},
    )
    schedule = make_schedule(app_state.signals)

    result = negotiate(schedule)

    errors = error_rows(app_state)
    assert any(e.payload["integration"] == "agents" for e in errors)
    # The malformed reply produced no negotiation_msg counter row.
    assert not [
        e
        for e in _envelopes(app_state)
        if e["type"] == "counter" and e["from"] == "dc-agent"
    ]
