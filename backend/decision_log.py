"""Decision log. Every state change writes a DecisionLogEntry (SPEC 5.5).

write_log validates the payload keys for the event, stores the row, and
fans it out to SSE subscribers.
"""

from __future__ import annotations

import secrets
from typing import Optional

import clock
from models import DecisionLogEntry
from state import get_state

# Payload keys allowed per event (SPEC section 5.5). Extra keys are invalid.
EVENT_PAYLOAD_KEYS: dict[str, set[str]] = {
    "startup": {"mode", "hardware_mode"},
    "proposed": {"alpha", "shifted_job_count", "shifted_kwh"},
    "approval_requested": {"shifted_job_count", "shifted_kwh"},
    "sms_sent": {"message_id", "phone_masked", "text"},
    "sms_reply": {"message_id", "phone_masked", "text"},
    "clarification_sent": {"message_id", "text"},
    "approved": {"via"},
    "rejected": {"reason"},
    "applied": {"previous_schedule_id"},
    "expired": {"reason"},
    "superseded": {"replaced_by"},
    "reset": {"applied_schedule_id"},
    "error": {"integration", "message"},
    "explanation": {"source", "text"},
    # negotiation_msg carries the whole section-12 envelope.
    "negotiation_msg": {
        "msg_id",
        "from",
        "to",
        "type",
        "schedule_id",
        "body",
    },
    "settlement_tx": {"signature", "explorer_url", "mode"},
    "telemetry_flagged": {"device_id", "power_w", "temp_c"},
}


def mask_phone(phone: str) -> str:
    """Keep the last two characters; earlier ones become *."""
    if len(phone) < 2:
        return "**"
    return "*" * (len(phone) - 2) + phone[-2:]


def write_log(
    schedule_id: Optional[str],
    actor: str,
    event: str,
    payload: dict,
) -> DecisionLogEntry:
    allowed = EVENT_PAYLOAD_KEYS.get(event)
    if allowed is None:
        raise ValueError(f"unknown decision-log event {event}")
    if set(payload) != allowed:
        raise ValueError(
            f"payload for {event} must be exactly {sorted(allowed)}, "
            f"got {sorted(payload)}"
        )
    entry = DecisionLogEntry(
        log_id="log-" + secrets.token_hex(6),
        ts=clock.now_utc(),
        schedule_id=schedule_id,
        actor=actor,  # type: ignore[arg-type]
        event=event,  # type: ignore[arg-type]
        payload=payload,
    )
    state = get_state()
    state.db.insert_log(entry)
    loop = state.loop
    for queue in list(state.sse_subscribers):
        try:
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(queue.put_nowait, entry)
            else:
                queue.put_nowait(entry)
        except Exception:
            pass
    return entry


def list_logs(limit: int, after: Optional[str]) -> list[DecisionLogEntry]:
    return get_state().db.list_logs(limit, after)
