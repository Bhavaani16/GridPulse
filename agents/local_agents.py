"""The three section-12 agents as pure functions (FETCHAI_MODE=local).

Each function takes already-validated inputs and returns an envelope body.
No sockets, no SDK: with /docs/fetchai.txt missing these are the whole
agent. The negotiation runner wraps the bodies in AgentEnvelope objects.

grid-agent  : inform -> bridge (curtailment surplus window)
dc-agent    : accept, or counter max_it_kw on any overloaded slot
ev-agent    : accept, or one counter per ev_charge job running at or
              after EV_FORCE_DEADLINE (job_id ascending)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from agents.envelope import DC_COUNTER_REASON, EV_COUNTER_REASON
from optimizer.models import GridSignal, Schedule


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def _format_ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def grid_inform_body(
    signals: Sequence[GridSignal], curtailment_surplus_mw: float
) -> dict:
    """inform body: the curtailment-surplus window from the signals.

    surplus_start is the ts of the first slot with curtailment_mw >= the
    threshold, surplus_end one hour after the last such slot. Both are
    null when no slot qualifies.
    """
    qualifying = [
        signal
        for signal in signals
        if signal.curtailment_mw >= curtailment_surplus_mw
    ]
    surplus_start: Optional[str] = None
    surplus_end: Optional[str] = None
    if qualifying:
        surplus_start = qualifying[0].ts
        surplus_end = _format_ts(_parse_ts(qualifying[-1].ts) + timedelta(hours=1))
    return {
        "surplus_start": surplus_start,
        "surplus_end": surplus_end,
        "curtailment_mw_min": curtailment_surplus_mw,
    }


def dc_agent_reply(schedule: Schedule, dc_max_it_kw: float) -> dict:
    """counter max_it_kw when any slot's it_load_kw exceeds the limit."""
    if any(slot.it_load_kw > dc_max_it_kw for slot in schedule.slots):
        return {
            "constraint": "max_it_kw",
            "max_it_kw": dc_max_it_kw,
            "reason": DC_COUNTER_REASON,
        }
    return {"accepted": True}


def ev_agent_replies(
    schedule: Schedule, ev_job_ids: Sequence[str], ev_force_deadline: str
) -> list[dict]:
    """One counter per ev_charge job fraction at/after the deadline.

    Returns a single accept body when nothing violates. Jobs are named in
    job_id ascending order (SPEC section 7 ordering convention).
    """
    deadline = _parse_ts(ev_force_deadline)
    violating: set[str] = set()
    for slot in schedule.slots:
        if _parse_ts(slot.ts) < deadline:
            continue
        for entry in slot.jobs:
            if entry.fraction > 0 and entry.job_id in ev_job_ids:
                violating.add(entry.job_id)
    if not violating:
        return [{"accepted": True}]
    return [
        {
            "constraint": "ev_deadline",
            "job_id": job_id,
            "deadline_ts": ev_force_deadline,
            "reason": EV_COUNTER_REASON,
        }
        for job_id in sorted(violating)
    ]
