"""Photon SMS approval tests (SPEC section 16, PH-1 through PH-6).

Covers the mock webhook contract, the reply state machine, the timeout
task, the exact SMS text, phone masking, no-socket mock mode, and the
live-unconfigured 501 fallback. Every test runs on a fresh app/database
via the shared client fixture; some build their own app for env tweaks.
"""

from __future__ import annotations

import re
import socket
import time
from datetime import timedelta

import clock
import pytest
from fastapi.testclient import TestClient

PHONE = "+15557654321"
MASKED_SUFFIX = PHONE[-2:]


def _optimize_pending(client: TestClient) -> dict:
    schedule = client.post("/api/optimize", json={"alpha": 0.5}).json()
    pending = client.post(
        f"/api/schedules/{schedule['schedule_id']}/request-approval"
    ).json()
    # The cached dataset shifts jobs at alpha 0.5.
    assert pending["status"] == "pending_approval"
    assert pending["shifted_job_count"] > 0
    return pending


def _reply(
    client: TestClient,
    message_id: str,
    text: str,
    from_number: str = PHONE,
) -> dict:
    return client.post(
        "/api/webhooks/photon",
        json={
            "message_id": message_id,
            "from_number": from_number,
            "text": text,
        },
    ).json()


def _events(client: TestClient) -> list[dict]:
    return client.get("/api/decisions", params={"limit": 200}).json()["items"]


def _schedule_status(client: TestClient, schedule_id: str) -> str:
    return client.get(f"/api/schedules/{schedule_id}").json()["status"]


@pytest.fixture()
def no_sockets(monkeypatch):
    """Fail the test if anything opens an outbound socket connection.

    Instantiation alone is not counted: TestClient's event loop builds a
    socketpair() self-pipe, which is local plumbing, not network I/O.
    PH-6 forbids Photon from connecting anywhere in mock mode.
    """
    attempts: list[tuple] = []

    def _connect(self, address):
        attempts.append(("connect", address))
        raise AssertionError(f"socket connect attempt: {address!r}")

    def _connect_ex(self, address):
        attempts.append(("connect_ex", address))
        raise AssertionError(f"socket connect_ex attempt: {address!r}")

    def _create_connection(*args, **kwargs):
        attempts.append(("create_connection", args))
        raise AssertionError(f"create_connection attempt: {args!r}")

    monkeypatch.setattr(socket.socket, "connect", _connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _connect_ex)
    monkeypatch.setattr(socket, "create_connection", _create_connection)
    return attempts


def test_ph1_yes_applies_and_supersedes(client: TestClient) -> None:
    pending = _optimize_pending(client)
    result = _reply(client, "sim-ph1-0001", "  yes\n")
    assert result["status"] == "applied"
    assert result["schedule_id"] == pending["schedule_id"]
    assert _schedule_status(client, pending["schedule_id"]) == "applied"
    # The previously applied row is the baseline on a fresh database.
    assert _schedule_status(client, "sch-baseline") == "superseded"
    assert client.get("/api/schedules/applied").json()["schedule_id"] == (
        pending["schedule_id"]
    )
    approved = [
        row
        for row in _events(client)
        if row["event"] == "approved"
        and row["schedule_id"] == pending["schedule_id"]
    ]
    assert approved and approved[0]["payload"]["via"] == "sms"


def test_ph2_no_rejects_and_keeps_applied(client: TestClient) -> None:
    pending = _optimize_pending(client)
    result = _reply(client, "sim-ph2-0001", "NO")
    assert result["status"] == "rejected"
    assert result["schedule_id"] == pending["schedule_id"]
    assert _schedule_status(client, pending["schedule_id"]) == "rejected"
    assert client.get("/api/schedules/applied").json()["schedule_id"] == (
        "sch-baseline"
    )
    rejected = [
        row
        for row in _events(client)
        if row["event"] == "rejected"
        and row["schedule_id"] == pending["schedule_id"]
    ]
    assert rejected and rejected[0]["payload"]["reason"] == "sms_no"


def test_ph3_invalid_text_clarifies_once(client: TestClient) -> None:
    pending = _optimize_pending(client)
    first = _reply(client, "sim-ph3-0001", "MAYBE")
    assert first["status"] == "pending_approval"
    assert first["clarification"] is True
    second = _reply(client, "sim-ph3-0002", "MAYBE")
    assert second["status"] == "pending_approval"
    assert second["clarification"] is False
    assert _schedule_status(client, pending["schedule_id"]) == (
        "pending_approval"
    )
    clarifications = [
        row for row in _events(client) if row["event"] == "clarification_sent"
    ]
    assert len(clarifications) == 1
    assert clarifications[0]["payload"]["text"] == "Reply YES or NO"
    # A valid reply still works after clarifications.
    third = _reply(client, "sim-ph3-0003", "YES")
    assert third["status"] == "applied"


def test_ph4_duplicate_message_id_ignored(client: TestClient) -> None:
    pending = _optimize_pending(client)
    first = _reply(client, "sim-ph4-0001", "YES")
    assert first["status"] == "applied"
    dup = _reply(client, "sim-ph4-0001", "YES")
    assert dup["status"] == "ignored"
    assert dup["reason"] == "duplicate"
    assert "schedule_id" not in dup
    applied_logs = [
        row
        for row in _events(client)
        if row["event"] == "applied"
        and row["schedule_id"] == pending["schedule_id"]
    ]
    assert len(applied_logs) == 1


def test_ph5_timeout_expires_pending(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 't.db'}")
    monkeypatch.setenv("START_SIMULATOR", "0")
    monkeypatch.setenv("PHOTON_TIMEOUT_SECONDS", "1")
    from main import create_app

    with TestClient(create_app()) as client:
        pending = _optimize_pending(client)
        applied_id = client.get("/api/schedules/applied").json()["schedule_id"]
        deadline = time.monotonic() + 5.0
        status = "pending_approval"
        while time.monotonic() < deadline and status == "pending_approval":
            time.sleep(0.25)
            status = _schedule_status(client, pending["schedule_id"])
        assert status == "expired"
        assert client.get("/api/schedules/applied").json()["schedule_id"] == (
            applied_id
        )
        expired = [
            row
            for row in _events(client)
            if row["event"] == "expired"
            and row["schedule_id"] == pending["schedule_id"]
        ]
        assert expired and expired[0]["payload"]["reason"] == "timeout"


def test_ph6_mock_opens_no_socket_and_masks_phone(
    tmp_path, monkeypatch, no_sockets
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 't.db'}")
    monkeypatch.setenv("START_SIMULATOR", "0")
    monkeypatch.setenv("PHOTON_MODE", "mock")
    monkeypatch.setenv("OPERATOR_PHONE", PHONE)
    from main import create_app

    with TestClient(create_app()) as client:
        pending = _optimize_pending(client)
        result = _reply(client, "sim-ph6-0001", "YES")
        assert result["status"] == "applied"
        phone_events = [
            row
            for row in _events(client)
            if "phone_masked" in row["payload"]
        ]
        assert phone_events
        for row in phone_events:
            masked = row["payload"]["phone_masked"]
            assert masked.endswith(MASKED_SUFFIX)
            assert set(masked[:-2]) == {"*"}
            assert PHONE not in str(row["payload"])
            assert PHONE not in str(row)
    assert no_sockets == []


def test_sms_text_exact_and_window(client: TestClient) -> None:
    pending = _optimize_pending(client)
    sms_logs = [
        row for row in _events(client) if row["event"] == "sms_sent"
    ]
    assert len(sms_logs) == 1
    payload = sms_logs[0]["payload"]
    assert payload["message_id"] == "mock-sms-" + pending["schedule_id"]

    baseline = client.get("/api/schedules/sch-baseline").json()
    base_frac = {
        (slot["ts"], job["job_id"]): job["fraction"]
        for slot in baseline["slots"]
        for job in slot["jobs"]
    }
    shifted_ts = [
        slot["ts"]
        for slot in pending["slots"]
        for job in slot["jobs"]
        if job["fraction"]
        > base_frac.get((slot["ts"], job["job_id"]), 0.0) + 1e-6
    ]
    start = min(shifted_ts)
    end = clock.iso(clock.parse_ts(max(shifted_ts)) + timedelta(hours=1))
    expected = (
        f"GridPulse: {pending['shifted_job_count']} jobs shifted, "
        f"{pending['shifted_kwh']:.1f} kWh moved into {start}-{end} UTC. "
        "Reply YES or NO"
    )
    assert payload["text"] == expected
    assert re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", start
    )


def test_not_pending_reply_ignored(client: TestClient) -> None:
    result = _reply(client, "sim-np-0001", "YES")
    assert result["status"] == "ignored"
    assert result["reason"] == "not_pending"
    assert "schedule_id" not in result
    assert _schedule_status(client, "sch-baseline") == "applied"


def test_new_pending_supersedes_old(client: TestClient) -> None:
    first = _optimize_pending(client)
    second = _optimize_pending(client)
    assert _schedule_status(client, first["schedule_id"]) == "expired"
    expired = [
        row
        for row in _events(client)
        if row["event"] == "expired"
        and row["schedule_id"] == first["schedule_id"]
    ]
    assert expired[0]["payload"]["reason"] == "superseded_by_new_request"
    result = _reply(client, "sim-sup-0001", "YES")
    assert result["status"] == "applied"
    assert result["schedule_id"] == second["schedule_id"]


def test_live_unconfigured_501_and_mock_send(
    tmp_path, monkeypatch, no_sockets
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 't.db'}")
    monkeypatch.setenv("START_SIMULATOR", "0")
    monkeypatch.setenv("PHOTON_MODE", "live")
    monkeypatch.setenv("OPERATOR_PHONE", PHONE)
    # Empty strings survive load_dotenv(override=False): force unconfigured.
    for var in ("PHOTON_API_KEY", "PHOTON_PROJECT_ID", "PHOTON_WEBHOOK_SECRET"):
        monkeypatch.setenv(var, "")
    from main import create_app

    with TestClient(create_app()) as client:
        pending = _optimize_pending(client)
        # Live without /docs/photon.txt: mock id, error logged, stays pending.
        errors = [
            row
            for row in _events(client)
            if row["event"] == "error"
            and row["payload"]["integration"] == "photon"
        ]
        assert errors
        sms_logs = [
            row for row in _events(client) if row["event"] == "sms_sent"
        ]
        assert sms_logs[0]["payload"]["message_id"] == (
            "mock-sms-" + pending["schedule_id"]
        )
        assert _schedule_status(client, pending["schedule_id"]) == (
            "pending_approval"
        )
        response = client.post(
            "/api/webhooks/photon",
            json={
                "message_id": "sim-live-1",
                "from_number": PHONE,
                "text": "YES",
            },
        )
        assert response.status_code == 501
        assert response.json()["error"]["code"] == "photon_unconfigured"
    assert no_sockets == []


def test_inbound_text_not_interpreted(client: TestClient) -> None:
    """Untrusted text: only exact YES/NO after strip().upper() counts."""
    pending = _optimize_pending(client)
    for index, text in enumerate(("yes please", "YES.", "' YES '", "1")):
        result = _reply(client, f"sim-unt-{index}", text)
        assert result["status"] == "pending_approval"
    assert _schedule_status(client, pending["schedule_id"]) == (
        "pending_approval"
    )
