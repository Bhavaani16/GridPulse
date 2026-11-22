"""Schedule state machine (SPEC section 10).

Resting statuses: proposed, pending_approval, applied, rejected, expired,
superseded. approve_and_apply writes 'approved' then 'applied' in one call.
Illegal transitions raise InvalidStateError and write nothing.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from decision_log import write_log
from errors import InvalidStateError, NotFoundError
from optimizer.models import Schedule
from state import get_state


def get_schedule(schedule_id: str) -> Schedule:
    schedule = get_state().db.get_schedule(schedule_id)
    if schedule is None:
        raise NotFoundError(schedule_id)
    return schedule


def unique_schedule_id(schedule: Schedule) -> Schedule:
    """Append -b, -c, ... when the generated id already exists."""
    state = get_state()
    candidate = schedule
    suffix = ord("b")
    while state.db.get_schedule(candidate.schedule_id) is not None:
        candidate = schedule.model_copy(
            update={"schedule_id": f"{schedule.schedule_id}-{chr(suffix)}"}
        )
        suffix += 1
    return candidate


def store_proposed(schedule: Schedule) -> Schedule:
    """Persist a proposed schedule and log the proposed event."""
    state = get_state()
    schedule = unique_schedule_id(schedule)
    state.db.upsert_schedule(schedule)
    write_log(
        schedule.schedule_id,
        "optimizer",
        "proposed",
        {
            "alpha": schedule.alpha,
            "shifted_job_count": schedule.shifted_job_count,
            "shifted_kwh": schedule.shifted_kwh,
        },
    )
    return schedule


def _cancel_expire_timer() -> None:
    state = get_state()
    if state.expire_task is not None and not state.expire_task.done():
        state.expire_task.cancel()
    state.expire_task = None
    state.pending_schedule_id = None


async def _expire_after(schedule_id: str, seconds: float) -> None:
    await asyncio.sleep(seconds)
    state = get_state()
    pending = state.db.schedules_with_status("pending_approval")
    if any(row.schedule_id == schedule_id for row in pending):
        try:
            expire(schedule_id, "photon", reason="timeout")
        except InvalidStateError:
            pass


def _start_expire_timer(schedule_id: str) -> None:
    """Schedule the pending-approval timeout on the app's event loop."""
    state = get_state()
    _cancel_expire_timer()
    state.pending_schedule_id = schedule_id
    coro = _expire_after(schedule_id, state.config.photon_timeout_seconds)
    try:
        state.expire_task = asyncio.get_running_loop().create_task(coro)
        return
    except RuntimeError:
        pass
    if state.loop is not None:
        state.expire_task = asyncio.run_coroutine_threadsafe(coro, state.loop)
    else:
        coro.close()


def request_approval(schedule_id: str, actor: str) -> Schedule:
    """proposed -> pending_approval (or applied when nothing shifted).

    Calls negotiate() first per SPEC section 12; a re-optimized schedule is
    stored under its own id and becomes the one awaiting approval.
    """
    state = get_state()
    schedule = get_schedule(schedule_id)
    if schedule.status != "proposed":
        raise InvalidStateError(schedule_id, schedule.status, "request_approval")

    negotiated = state.negotiate(schedule)
    if negotiated.schedule_id != schedule.schedule_id:
        negotiated = store_proposed(negotiated)
        schedule = negotiated

    if schedule.shifted_job_count == 0:
        return approve_and_apply(schedule.schedule_id, actor)

    for other in state.db.schedules_with_status("pending_approval"):
        expire(other.schedule_id, actor, reason="superseded_by_new_request")

    schedule = schedule.model_copy(update={"status": "pending_approval"})
    state.db.upsert_schedule(schedule)
    write_log(
        schedule.schedule_id,
        actor,
        "approval_requested",
        {
            "shifted_job_count": schedule.shifted_job_count,
            "shifted_kwh": schedule.shifted_kwh,
        },
    )
    try:
        state.send_approval_sms(schedule)
    except Exception as exc:
        write_log(
            schedule.schedule_id, "photon", "error",
            {"integration": "photon", "message": f"send_approval_sms: {exc}"},
        )
    _start_expire_timer(schedule.schedule_id)
    return schedule


def approve_and_apply(schedule_id: str, actor: str) -> Schedule:
    """proposed|pending_approval -> approved -> applied."""
    state = get_state()
    schedule = get_schedule(schedule_id)
    if schedule.status not in ("proposed", "pending_approval"):
        raise InvalidStateError(schedule_id, schedule.status, "approve")

    via = "sms" if actor == "photon" else "dashboard"
    write_log(schedule_id, actor, "approved", {"via": via})

    previous_id: Optional[str] = None
    for other in state.db.schedules_with_status("applied"):
        if other.schedule_id == schedule_id:
            continue
        previous_id = other.schedule_id
        superseded = other.model_copy(update={"status": "superseded"})
        state.db.upsert_schedule(superseded)
        write_log(
            other.schedule_id, actor, "superseded",
            {"replaced_by": schedule_id},
        )

    schedule = schedule.model_copy(update={"status": "applied"})
    state.db.upsert_schedule(schedule)
    write_log(
        schedule_id,
        actor,
        "applied",
        {"previous_schedule_id": previous_id or ""},
    )
    _cancel_expire_timer()
    try:
        state.record_settlement(schedule)
    except Exception as exc:
        write_log(
            schedule_id, "solana", "error",
            {"integration": "solana", "message": f"record_settlement: {exc}"},
        )
    return schedule


def reject(schedule_id: str, actor: str, reason: Optional[str] = None) -> Schedule:
    state = get_state()
    schedule = get_schedule(schedule_id)
    if schedule.status not in ("proposed", "pending_approval"):
        raise InvalidStateError(schedule_id, schedule.status, "reject")
    schedule = schedule.model_copy(update={"status": "rejected"})
    state.db.upsert_schedule(schedule)
    write_log(
        schedule_id,
        actor,
        "rejected",
        {"reason": reason or ("sms_no" if actor == "photon" else "dashboard")},
    )
    _cancel_expire_timer()
    return schedule


def expire(schedule_id: str, actor: str, reason: str = "timeout") -> Schedule:
    state = get_state()
    schedule = get_schedule(schedule_id)
    if schedule.status != "pending_approval":
        raise InvalidStateError(schedule_id, schedule.status, "expire")
    schedule = schedule.model_copy(update={"status": "expired"})
    state.db.upsert_schedule(schedule)
    write_log(schedule_id, actor, "expired", {"reason": reason})
    if state.pending_schedule_id == schedule_id:
        state.pending_schedule_id = None
    return schedule


def applied_schedule() -> Optional[Schedule]:
    rows = get_state().db.schedules_with_status("applied")
    return rows[0] if rows else None


def pending_schedule() -> Optional[Schedule]:
    rows = get_state().db.schedules_with_status("pending_approval")
    return rows[0] if rows else None


def previous_applied(schedule: Schedule) -> Optional[Schedule]:
    """The schedule that was applied before this one (SPEC section 11)."""
    state = get_state()
    if schedule.status != "applied":
        return applied_schedule()
    logs = state.db.list_logs(200, None)
    applied_ids = [row.schedule_id for row in logs if row.event == "applied"]
    try:
        index = applied_ids.index(schedule.schedule_id)
    except ValueError:
        return None
    if index == 0:
        return None
    return state.db.get_schedule(applied_ids[index - 1])
