"""End-to-end flow (SPEC section 16, E2E-1 through E2E-7).

MODE=cached, HARDWARE_MODE=simulated, START_SIMULATOR=0, all integrations
in mock/local mode, empty DATABASE_URL (each test gets a temp SQLite file).
"""

from __future__ import annotations

import time

import clock
from fastapi.testclient import TestClient
from optimizer.models import Schedule


def _telemetry_command(schedule: dict, ts: str) -> bool:
    """The section-9 rule, restated against the schedule object."""
    start = clock.parse_ts(ts)
    for slot in schedule["slots"]:
        slot_start = clock.parse_ts(slot["ts"])
        end = clock.parse_ts(slot["ts"]).timestamp() + 3600
        if slot_start <= start and start.timestamp() < end:
            return slot["cooling_mode"] == "dry"
    return True


def test_e2e_flow(client: TestClient) -> None:
    # E2E-1
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["mode"] == "cached"
    assert health["hardware_mode"] == "simulated"
    assert health["database"] == "sqlite"

    # E2E-2
    assert len(client.get("/api/jobs").json()["items"]) == 8

    # E2E-3
    optimized = client.post("/api/optimize", json={"alpha": 0}).json()
    assert optimized["schedule_kind"] == "optimized"
    assert optimized["metrics"]["carbon_kg"] <= optimized["baseline_metrics"]["carbon_kg"]

    # E2E-4
    reset = client.post("/api/demo/reset").json()
    assert reset == {"status": "ok", "applied_schedule_id": "sch-baseline"}
    started = time.monotonic()
    triggered = client.post("/api/demo/trigger-surplus").json()
    elapsed = time.monotonic() - started
    assert elapsed < 3.0, f"trigger-surplus took {elapsed:.2f}s"
    Schedule.model_validate(triggered)
    assert triggered["shifted_job_count"] >= 1
    assert triggered["status"] == "pending_approval"
    assert triggered["savings_label"] == "simulated"
    events = [row["event"] for row in client.get("/api/decisions").json()["items"]]
    assert "proposed" in events

    # E2E-5
    result = client.post(
        "/api/webhooks/photon",
        json={
            "message_id": "sim-e2e0001",
            "from_number": "+15551230000",
            "text": "YES",
        },
    ).json()
    assert result["status"] == "applied"
    applied = client.get("/api/schedules/applied").json()
    assert applied["schedule_id"] == result["schedule_id"]
    assert applied["schedule_id"] == triggered["schedule_id"]

    # E2E-6
    ts = applied["slots"][0]["ts"]
    response = client.post(
        "/api/telemetry",
        json={
            "device_id": "esp32-fan-sim",
            "ts": ts,
            "power_w": 4.5,
            "temp_c": 30.0,
            "fan_on": False,
            "simulated": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["command"]["fan_on"] == _telemetry_command(applied, ts)

    # E2E-7
    explain = client.get(f"/api/explain/{applied['schedule_id']}").json()
    assert len(explain["text"]) > 0
    assert explain["source"] == "fallback"
