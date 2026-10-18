"""Photon SMS approval (SPEC section 10). Owner: Photon agent (D3).

Contract (other agents replace the bodies, not the signatures):

    send_approval_sms(schedule: Schedule) -> str
        Returns the message id. Mock: "mock-sms-" + schedule_id, writes an
        sms_sent decision-log row, opens no socket.

    photon_router: APIRouter mounted at /api/webhooks; routes POST "" so the
        public path is POST /api/webhooks/photon -> WebhookResult.

Mock mode (PHOTON_MODE=mock, default) accepts
{"message_id", "from_number", "text"} and runs the full reply state
machine with no network I/O.

Live mode (PHOTON_MODE=live) implements the Photon Beta (2.0) mapping from
the public API reference (api.photon.codes/openapi.json, event contract
apiVersion 2026-07-01) as documented in PHOTON.md. It needs
PHOTON_API_KEY (pho_sk_), PHOTON_PROJECT_ID (pho_prj_), OPERATOR_PHONE and
PHOTON_WEBHOOK_SECRET (returned by the webhook destination registration);
PHOTON_PLATFORM selects the channel (imessage or sms). When the key or
project id is absent, live mode is unconfigured: the webhook returns 501
photon_unconfigured and send_approval_sms logs an error and returns the
mock id without networking (SPEC section 10).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from datetime import timedelta
from typing import Optional

import clock
import httpx
from decision_log import mask_phone, write_log
from errors import InvalidStateError
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from models import PhotonWebhookBody, WebhookResult, error_body
from optimizer.models import Schedule
from schedules import approve_and_apply, pending_schedule, reject
from state import get_state

CLARIFICATION_TEXT = "Reply YES or NO"

PHOTON_BASE_URL = "https://api.photon.codes"
# Webhook signature headers, Standard Webhooks (with Spectrum-era fallbacks).
SIG_HEADERS = ("webhook-signature", "x-spectrum-signature")
ID_HEADERS = ("webhook-id", "x-spectrum-webhook-id")
TS_HEADERS = ("webhook-timestamp", "x-spectrum-timestamp")
SIGNATURE_TOLERANCE_SECONDS = 300
SEND_TIMEOUT_SECONDS = 10.0  # SPEC section 10: 10 s, then one retry

photon_router = APIRouter()


def approval_window(schedule: Schedule) -> tuple[str, str]:
    """Earliest/latest slot where a shifted job beats its baseline share."""
    state = get_state()
    baseline = state.db.get_schedule("sch-baseline")
    start_ts = None
    end_ts = None
    if baseline is not None:
        for slot, base_slot in zip(schedule.slots, baseline.slots):
            base_frac = {j.job_id: j.fraction for j in base_slot.jobs}
            for job in slot.jobs:
                if job.fraction > base_frac.get(job.job_id, 0.0) + 1e-6:
                    slot_start = clock.parse_ts(slot.ts)
                    if start_ts is None or slot.ts < start_ts:
                        start_ts = slot.ts
                    end = slot_start + timedelta(hours=1)
                    if end_ts is None or clock.iso(end) > end_ts:
                        end_ts = clock.iso(end)
    if start_ts is None:
        start_ts = schedule.slots[0].ts if schedule.slots else ""
        end_ts = start_ts
    return start_ts, end_ts or start_ts


def _live_env() -> dict[str, str]:
    """Photon credentials from the process env (config.py is not ours)."""
    return {
        "api_key": os.environ.get("PHOTON_API_KEY", "").strip(),
        "project_id": os.environ.get("PHOTON_PROJECT_ID", "").strip(),
        "webhook_secret": os.environ.get("PHOTON_WEBHOOK_SECRET", "").strip(),
        "platform": os.environ.get("PHOTON_PLATFORM", "imessage").strip()
        or "imessage",
    }


def _live_configured() -> bool:
    env = _live_env()
    return bool(env["api_key"] and env["project_id"])


def _photon_request(
    env: dict[str, str],
    method: str,
    path: str,
    body: Optional[dict] = None,
    idempotency_key: Optional[str] = None,
) -> httpx.Response:
    """One documented Photon call: 10 s timeout, at most one retry.

    Retries only transport failures and 5xx; 4xx responses return to the
    caller unchanged so the caller can read the problem body.
    """
    url = f"{PHOTON_BASE_URL}/v1/projects/{env['project_id']}{path}"
    headers = {"Authorization": f"Bearer {env['api_key']}"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    last_error: Optional[BaseException | str] = None
    for attempt in range(2):
        try:
            with httpx.Client(timeout=SEND_TIMEOUT_SECONDS) as client:
                response = client.request(method, url, json=body, headers=headers)
            if response.status_code < 500:
                return response
            last_error = f"HTTP {response.status_code}"
        except (httpx.HTTPError, OSError) as exc:
            last_error = exc
        if attempt == 0:
            time.sleep(0.5)
    raise RuntimeError(f"photon {method} {path}: {last_error}")


def _send_live(schedule: Schedule, text: str) -> Optional[str]:
    """Send via the documented Beta calls. Returns the pho_msg_ id or None.

    A shared line cannot send first: this needs an existing direct space,
    which the operator's first inbound message creates. Agent user id is
    the other participant of that space.
    """
    env = _live_env()
    phone = get_state().config.operator_phone
    if not phone:
        return None
    platform = env["platform"]
    resp = _photon_request(
        env, "POST", "/users", {"handle": phone, "platform": platform}
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"users create-or-get: HTTP {resp.status_code}")
    operator_id = resp.json().get("id")

    resp = _photon_request(env, "GET", "/spaces")
    if resp.status_code >= 400:
        raise RuntimeError(f"spaces list: HTTP {resp.status_code}")
    space_id = None
    agent_id = None
    for space in resp.json().get("items", []):
        if space.get("platform") != platform:
            continue
        participants = space.get("participantIds", [])
        if operator_id in participants:
            space_id = space["id"]
            others = [u for u in participants if u != operator_id]
            agent_id = others[0] if others else None
            break
    if not space_id or not agent_id:
        return None

    resp = _photon_request(
        env,
        "POST",
        "/messages",
        {
            "senderId": agent_id,
            "spaceId": space_id,
            "content": {"type": "text", "format": "plain", "text": text},
        },
        idempotency_key=f"gridpulse-approval-{schedule.schedule_id}",
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"messages send: HTTP {resp.status_code}")
    return resp.json().get("id")


def send_approval_sms(schedule: Schedule) -> str:
    """Exact SPEC section 10 text; mock id when mock or send fails.

    Mock mode and unconfigured live mode open no socket and return
    'mock-sms-' + schedule_id. Live send failure logs an error and leaves
    the schedule pending_approval (the caller's state unchanged).
    """
    state = get_state()
    start, end = approval_window(schedule)
    text = (
        f"GridPulse: {schedule.shifted_job_count} jobs shifted, "
        f"{schedule.shifted_kwh:.1f} kWh moved into {start}-{end} UTC. "
        "Reply YES or NO"
    )
    message_id = "mock-sms-" + schedule.schedule_id
    live = state.config.photon_mode == "live"
    if live and not _live_configured():
        write_log(
            schedule.schedule_id,
            "photon",
            "error",
            {
                "integration": "photon",
                "message": "PHOTON_MODE=live but /docs/photon.txt is missing",
            },
        )
    elif live:
        try:
            sent_id = _send_live(schedule, text)
            if sent_id:
                message_id = sent_id
            else:
                write_log(
                    schedule.schedule_id,
                    "photon",
                    "error",
                    {
                        "integration": "photon",
                        "message": "no existing conversation space for "
                        "operator; shared lines cannot send first",
                    },
                )
        except Exception as exc:
            write_log(
                schedule.schedule_id,
                "photon",
                "error",
                {"integration": "photon", "message": f"send failed: {exc}"},
            )
    write_log(
        schedule.schedule_id,
        "photon",
        "sms_sent",
        {
            "message_id": message_id,
            "phone_masked": mask_phone(state.config.operator_phone),
            "text": text,
        },
    )
    return message_id


def _handle_reply(body: PhotonWebhookBody) -> WebhookResult:
    """Reply state machine (SPEC section 10), shared by mock and live."""
    state = get_state()
    if body.message_id in state.seen_message_ids:
        return WebhookResult(
            status="ignored", reason="duplicate", clarification=False
        )
    state.seen_message_ids.add(body.message_id)
    phone_masked = mask_phone(body.from_number)

    pending = pending_schedule()
    if pending is None:
        write_log(
            None,
            "photon",
            "sms_reply",
            {
                "message_id": body.message_id,
                "phone_masked": phone_masked,
                "text": body.text,
            },
        )
        return WebhookResult(
            status="ignored", reason="not_pending", clarification=False
        )

    write_log(
        pending.schedule_id,
        "photon",
        "sms_reply",
        {
            "message_id": body.message_id,
            "phone_masked": phone_masked,
            "text": body.text,
        },
    )
    reply = body.text.strip().upper()
    try:
        if reply == "YES":
            applied = approve_and_apply(pending.schedule_id, "photon")
            return WebhookResult(
                status="applied", schedule_id=applied.schedule_id
            )
        if reply == "NO":
            rejected = reject(pending.schedule_id, "photon", reason="sms_no")
            return WebhookResult(
                status="rejected", schedule_id=rejected.schedule_id
            )
    except InvalidStateError:
        # The timeout task expired the row between the pending check and
        # the transition; the reply arrived too late.
        return WebhookResult(
            status="ignored", reason="not_pending", clarification=False
        )

    clarified = pending.schedule_id in state.clarified_schedule_ids
    if not clarified:
        state.clarified_schedule_ids.add(pending.schedule_id)
        write_log(
            pending.schedule_id,
            "photon",
            "clarification_sent",
            {
                "message_id": "mock-sms-clar-" + body.message_id,
                "text": CLARIFICATION_TEXT,
            },
        )
    return WebhookResult(
        status="pending_approval",
        schedule_id=pending.schedule_id,
        clarification=not clarified,
    )


def _header(request: Request, names: tuple[str, ...]) -> str:
    for name in names:
        value = request.headers.get(name)
        if value:
            return value
    return ""


def _verify_signature(raw_body: bytes, request: Request, secret: str) -> bool:
    """Standard Webhooks: HMAC-SHA256 of '<id>.<ts>.<rawBody>' -> 'v1,<b64>'."""
    webhook_id = _header(request, ID_HEADERS)
    timestamp = _header(request, TS_HEADERS)
    signatures = _header(request, SIG_HEADERS)
    if not webhook_id or not timestamp or not signatures:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs(time.time() - ts) > SIGNATURE_TOLERANCE_SECONDS:
        return False
    key = secret[len("whsec_"):] if secret.startswith("whsec_") else secret
    try:
        key_bytes = base64.b64decode(key)
    except Exception:
        return False
    signed = f"{webhook_id}.{timestamp}.".encode() + raw_body
    expected = base64.b64encode(
        hmac.new(key_bytes, signed, hashlib.sha256).digest()
    ).decode()
    return any(
        hmac.compare_digest(candidate[3:], expected)
        for candidate in signatures.split(" ")
        if candidate.startswith("v1,")
    )


def _live_event_to_reply(event: dict) -> Optional[PhotonWebhookBody]:
    """Map a message.received event (apiVersion 2026-07-01) onto the body."""
    if event.get("type") != "message.received":
        return None
    obj = event.get("data", {}).get("object", {})
    content = obj.get("content", {})
    if content.get("type") != "text":
        return None
    return PhotonWebhookBody(
        message_id=obj.get("id", ""),
        from_number=obj.get("sentBy", {}).get("handle", ""),
        text=content.get("text", ""),
    )


async def photon_webhook(request: Request):
    """POST /api/webhooks/photon (mock body or live Photon delivery)."""
    state = get_state()
    raw = await request.body()
    if state.config.photon_mode == "live":
        if not _live_configured():
            write_log(
                None,
                "photon",
                "error",
                {
                    "integration": "photon",
                    "message": "PHOTON_MODE=live but credentials are missing",
                },
            )
            return JSONResponse(
                status_code=501,
                content=error_body(
                    "photon_unconfigured",
                    "PHOTON_MODE=live and photon credentials are missing",
                ),
            )
        env = _live_env()
        if not _verify_signature(raw, request, env["webhook_secret"]):
            return JSONResponse(
                status_code=401,
                content=error_body("unauthorized", "bad webhook signature"),
            )
        try:
            event = _parse_json_object(raw)
        except ValueError:
            return JSONResponse(
                status_code=422,
                content=error_body("validation_error", "invalid JSON"),
            )
        body = _live_event_to_reply(event)
        if body is None:
            # Not an inbound text reply; acknowledge so Photon stops retrying.
            return WebhookResult(
                status="ignored", reason="not_pending", clarification=False
            ).model_dump(exclude_none=True)
        operator = state.config.operator_phone
        if operator and body.from_number != operator:
            write_log(
                None,
                "photon",
                "sms_reply",
                {
                    "message_id": body.message_id or "unknown",
                    "phone_masked": mask_phone(body.from_number),
                    "text": body.text,
                },
            )
            return WebhookResult(
                status="ignored", reason="not_pending", clarification=False
            ).model_dump(exclude_none=True)
        return _handle_reply(body).model_dump(exclude_none=True)

    try:
        event = _parse_json_object(raw)
    except ValueError:
        return JSONResponse(
            status_code=422,
            content=error_body("validation_error", "invalid JSON"),
        )
    try:
        body = PhotonWebhookBody.model_validate(event)
    except Exception:
        return JSONResponse(
            status_code=422,
            content=error_body("validation_error", "invalid webhook body"),
        )
    # reason is omitted unless status is ignored (SPEC section 6).
    return _handle_reply(body).model_dump(exclude_none=True)


def _parse_json_object(raw: bytes) -> dict:
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("webhook body must be a JSON object")
    return parsed


photon_router.add_api_route("", photon_webhook, methods=["POST"])
photon_router.add_api_route("/photon", photon_webhook, methods=["POST"])
