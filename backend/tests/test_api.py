"""API contract tests (SPEC section 16, API-1 through API-5)."""

from __future__ import annotations

import asyncio
import time

import clock
from fastapi.testclient import TestClient
from optimizer.models import GridSignal, Job, Asset, Schedule

IN_HORIZON_TS = None  # resolved per-test against the live horizon


def _in_horizon_ts(client: TestClient) -> str:
    signals = client.get("/api/signals").json()["items"]
    return signals[5]["ts"]


def test_health(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["mode"] == "cached"
    assert body["hardware_mode"] == "simulated"
    assert body["database"] == "sqlite"
    assert body["optimizer_mode"] == "real"
    assert body["photon_mode"] == "mock"
    assert body["gemini_mode"] == "mock"
    assert body["solana_mode"] == "mock"
    assert body["agents_mode"] == "local"


def test_signals_jobs_assets(client: TestClient) -> None:
    body = client.get("/api/signals").json()
    assert body["horizon_start"] == body["items"][0]["ts"]
    assert len(body["items"]) == 24
    for item in body["items"]:
        GridSignal.model_validate(item)
    jobs = client.get("/api/jobs").json()["items"]
    assert len(jobs) == 8
    for item in jobs:
        Job.model_validate(item)
    assets = client.get("/api/assets").json()["items"]
    assert len(assets) == 2
    for item in assets:
        Asset.model_validate(item)


def test_optimize_returns_proposed_schedule(client: TestClient) -> None:
    response = client.post("/api/optimize", json={"alpha": 0.5})
    assert response.status_code == 200
    schedule = Schedule.model_validate(response.json())
    assert schedule.schedule_kind == "optimized"
    assert schedule.status == "proposed"
    assert schedule.savings_label == "simulated"
    assert len(schedule.slots) == 24
    assert client.get(f"/api/schedules/{schedule.schedule_id}").json()[
        "schedule_id"
    ] == schedule.schedule_id


def test_optimize_validation_error(client: TestClient) -> None:
    response = client.post("/api/optimize", json={"alpha": 0.5, "bogus": 1})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    response = client.post("/api/optimize", json={"alpha": 1.5})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    response = client.post(
        "/api/optimize",
        json={"alpha": 0.5, "constraints": {"max_it_kw": 6.0, "nope": 1}},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_optimize_constraints_accepted(client: TestClient) -> None:
    response = client.post(
        "/api/optimize",
        json={"alpha": 0.5, "constraints": {"max_it_kw": 6.0}},
    )
    assert response.status_code == 200
    schedule = response.json()
    # Solver stores fractions rounded to 6 decimals; allow its 1e-4 check tolerance.
    assert all(slot["it_load_kw"] <= 6.0 + 1e-4 for slot in schedule["slots"])


def test_telemetry_command_follows_schedule(client: TestClient) -> None:
    ts = _in_horizon_ts(client)
    response = client.post(
        "/api/telemetry",
        json={
            "device_id": "esp32-fan-sim",
            "ts": ts,
            "power_w": 4.5,
            "temp_c": 31.5,
            "fan_on": False,
            "simulated": True,
        },
    )
    assert response.status_code == 200
    # sch-baseline cools all IT wet, so the fan command is off.
    assert response.json() == {"command": {"fan_on": False}}


def test_telemetry_command_true_outside_horizon(client: TestClient) -> None:
    response = client.post(
        "/api/telemetry",
        json={
            "device_id": "esp32-fan-sim",
            "ts": "2030-01-01T00:00:00Z",
            "power_w": 4.5,
            "temp_c": 31.5,
            "fan_on": False,
            "simulated": True,
        },
    )
    assert response.json() == {"command": {"fan_on": True}}


def test_flagged_telemetry(client: TestClient) -> None:
    ts = _in_horizon_ts(client)
    response = client.post(
        "/api/telemetry",
        json={
            "device_id": "esp32-fan-sim",
            "ts": ts,
            "power_w": 900.0,
            "temp_c": 31.5,
            "fan_on": True,
            "simulated": True,
        },
    )
    assert response.status_code == 200
    items = client.get("/api/telemetry", params={"minutes": 60}).json()["items"]
    assert all(item["power_w"] < 900 for item in items)
    events = [
        row["event"]
        for row in client.get("/api/decisions").json()["items"]
    ]
    assert "telemetry_flagged" in events


def test_telemetry_minute_aggregation(client: TestClient) -> None:
    now = clock.now_dt().replace(microsecond=0)
    # Two distinct timestamps inside the same minute bucket.
    for power, seconds in ((4.0, 0), (5.0, 30)):
        ts = now.replace(second=seconds)
        client.post(
            "/api/telemetry",
            json={
                "device_id": "esp32-fan-sim",
                "ts": clock.iso(ts),
                "power_w": power,
                "temp_c": 30.0,
                "fan_on": True,
                "simulated": True,
            },
        )
    items = client.get("/api/telemetry", params={"minutes": 5}).json()["items"]
    sim_rows = [i for i in items if i["device_id"] == "esp32-fan-sim"]
    assert len(sim_rows) == 1
    assert sim_rows[0]["power_w"] == 4.5
    assert sim_rows[0]["fan_on"] is True


def test_schedule_not_found(client: TestClient) -> None:
    response = client.get("/api/schedules/sch-nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_approve_and_reject_transitions(client: TestClient) -> None:
    schedule = client.post("/api/optimize", json={"alpha": 0.4}).json()
    approved = client.post(
        f"/api/schedules/{schedule['schedule_id']}/approve"
    ).json()
    assert approved["status"] == "applied"
    applied = client.get("/api/schedules/applied").json()
    assert applied["schedule_id"] == schedule["schedule_id"]
    baseline = client.get("/api/schedules/sch-baseline").json()
    assert baseline["status"] == "superseded"
    # Approving again is illegal now that the schedule is applied.
    response = client.post(f"/api/schedules/{schedule['schedule_id']}/approve")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_state"

    schedule2 = client.post("/api/optimize", json={"alpha": 0.2}).json()
    rejected = client.post(
        f"/api/schedules/{schedule2['schedule_id']}/reject"
    ).json()
    assert rejected["status"] == "rejected"


def test_request_approval_then_sms_yes(client: TestClient) -> None:
    schedule = client.post("/api/optimize", json={"alpha": 0.5}).json()
    pending = client.post(
        f"/api/schedules/{schedule['schedule_id']}/request-approval"
    ).json()
    if pending["shifted_job_count"] == 0:
        assert pending["status"] == "applied"
        return
    assert pending["status"] == "pending_approval"
    result = client.post(
        "/api/webhooks/photon",
        json={
            "message_id": "sim-req-0001",
            "from_number": "+15551230000",
            "text": "YES",
        },
    ).json()
    assert result["status"] == "applied"
    assert result["schedule_id"] == schedule["schedule_id"]


def test_sms_clarification_once(client: TestClient) -> None:
    schedule = client.post("/api/optimize", json={"alpha": 0.5}).json()
    pending = client.post(
        f"/api/schedules/{schedule['schedule_id']}/request-approval"
    ).json()
    if pending["status"] != "pending_approval":
        return  # nothing shifted; nothing to clarify
    body = {
        "message_id": "sim-maybe-1",
        "from_number": "+15551230000",
        "text": "MAYBE",
    }
    first = client.post("/api/webhooks/photon", json=body).json()
    assert first["status"] == "pending_approval"
    assert first["clarification"] is True
    body["message_id"] = "sim-maybe-2"
    second = client.post("/api/webhooks/photon", json=body).json()
    assert second["status"] == "pending_approval"
    assert second["clarification"] is False
    clarifications = [
        row
        for row in client.get("/api/decisions").json()["items"]
        if row["event"] == "clarification_sent"
    ]
    assert len(clarifications) == 1


def test_duplicate_message_id_ignored(client: TestClient) -> None:
    schedule = client.post("/api/optimize", json={"alpha": 0.5}).json()
    pending = client.post(
        f"/api/schedules/{schedule['schedule_id']}/request-approval"
    ).json()
    if pending["status"] != "pending_approval":
        return
    body = {
        "message_id": "sim-dup-01",
        "from_number": "+15551230000",
        "text": "YES",
    }
    assert client.post("/api/webhooks/photon", json=body).json()["status"] == "applied"
    dup = client.post("/api/webhooks/photon", json=body).json()
    assert dup["status"] == "ignored"
    assert dup["reason"] == "duplicate"


def test_photon_timeout_expires(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 't.db'}")
    monkeypatch.setenv("START_SIMULATOR", "0")
    monkeypatch.setenv("PHOTON_TIMEOUT_SECONDS", "1")
    from main import create_app

    with TestClient(create_app()) as client:
        schedule = client.post("/api/optimize", json={"alpha": 0.5}).json()
        pending = client.post(
            f"/api/schedules/{schedule['schedule_id']}/request-approval"
        ).json()
        if pending["status"] != "pending_approval":
            return
        deadline = time.monotonic() + 5.0
        status = "pending_approval"
        while time.monotonic() < deadline and status == "pending_approval":
            time.sleep(0.25)
            status = client.get(
                f"/api/schedules/{schedule['schedule_id']}"
            ).json()["status"]
        assert status == "expired"
        assert client.get("/api/schedules/applied").json()[
            "schedule_id"
        ] == "sch-baseline"


def test_decisions_after_cursor(client: TestClient) -> None:
    client.post("/api/optimize", json={"alpha": 0.3})
    items = client.get("/api/decisions").json()["items"]
    assert len(items) >= 2
    first_id = items[0]["log_id"]
    rest = client.get(
        "/api/decisions", params={"after": first_id}
    ).json()["items"]
    assert all(row["log_id"] != first_id for row in rest)
    assert len(rest) == len(items) - 1


def test_explain_fallback_source(client: TestClient) -> None:
    schedule = client.post("/api/optimize", json={"alpha": 0.5}).json()
    body = client.get(f"/api/explain/{schedule['schedule_id']}").json()
    assert body["schedule_id"] == schedule["schedule_id"]
    assert body["source"] == "fallback"
    assert "Simulated result at alpha 0.50" in body["text"]
    cached = client.get(f"/api/explain/{schedule['schedule_id']}").json()
    assert cached["source"] == "cache"


def test_stream_backlog(client: TestClient) -> None:
    # TestClient cannot consume an unbounded SSE body (it waits for the
    # stream to end), so drive the endpoint's StreamingResponse directly.
    client.post("/api/optimize", json={"alpha": 0.5})
    route = next(
        r for r in client.app.routes if getattr(r, "path", "") == "/api/stream"
    )

    async def collect() -> str:
        response = await route.endpoint()
        iterator = response.body_iterator
        chunks: list[str] = []
        try:
            async for chunk in iterator:
                chunks.append(chunk if isinstance(chunk, str) else chunk.decode())
                if sum("event: decision" in c for c in chunks) >= 2:
                    break
        finally:
            await iterator.aclose()
        return "".join(chunks)

    body = asyncio.run(collect())
    assert "event: decision" in body
    assert '"event":"startup"' in body or '"event":"proposed"' in body
