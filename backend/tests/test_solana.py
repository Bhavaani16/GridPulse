"""Solana settlement tests (SPEC section 16: SOL-1 through SOL-3).

SOL-1: SOLANA_MODE=mock returns mocksig- plus 16 hex chars and does not
open a socket.
SOL-2: the memo JSON contains schedule_id and hash equal to
metrics_hash(schedule.metrics).
SOL-3: a settlement timeout still leaves the schedule applied.

Nothing opens a real socket: live-mode tests monkeypatch
integrations.solana.send_memo_tx, and the mock-path test patches
solana.httpx.post to fail loudly if it is ever called.
"""

from __future__ import annotations

import hashlib
import json
import time

import pytest
from fastapi.testclient import TestClient

import integrations.solana as solana
from optimizer.metrics import metrics_hash
from state import get_state


def _make_app(
    tmp_path,
    monkeypatch,
    mode: str = "mock",
    keypair_path: str = "/tmp/gridpulse-test-keypair.json",
) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 's.db'}")
    monkeypatch.setenv("START_SIMULATOR", "0")
    monkeypatch.setenv("SOLANA_MODE", mode)
    monkeypatch.setenv("SOLANA_KEYPAIR_PATH", keypair_path)
    from main import create_app

    return TestClient(create_app())


def _proposed(client: TestClient) -> dict:
    schedule = client.post("/api/optimize", json={"alpha": 0.5}).json()
    client.post(
        f"/api/schedules/{schedule['schedule_id']}/request-approval"
    )
    return schedule


def _logs(event: str) -> list:
    return [
        row for row in get_state().db.list_logs(500, None)
        if row.event == event
    ]


def test_sol1_mock_returns_mocksig_and_opens_no_socket(
    tmp_path, monkeypatch
) -> None:
    def _boom(*args, **kwargs):
        raise AssertionError("mock mode opened a socket")

    monkeypatch.setattr(solana.httpx, "post", _boom)
    with _make_app(tmp_path, monkeypatch) as client:
        schedule = _proposed(client)
        signature = solana.record_settlement(
            get_state().db.get_schedule(schedule["schedule_id"])
        )
        expect = "mocksig-" + hashlib.sha256(
            schedule["schedule_id"].encode("utf-8")
        ).hexdigest()[:16]
        assert signature == expect
        rows = _logs("settlement_tx")
        assert rows[-1].actor == "solana"
        assert rows[-1].payload == {
            "signature": expect,
            "explorer_url": None,
            "mode": "mock",
        }


def test_sol2_memo_json_contains_schedule_id_and_metrics_hash(
    tmp_path, monkeypatch
) -> None:
    with _make_app(tmp_path, monkeypatch) as client:
        schedule_id = client.post(
            "/api/optimize", json={"alpha": 0.5}
        ).json()["schedule_id"]
        schedule = get_state().db.get_schedule(schedule_id)
        memo = solana.build_memo_json(schedule)
        parsed = json.loads(memo)
        assert parsed["schedule_id"] == schedule_id
        assert parsed["hash"] == metrics_hash(schedule.metrics)
        assert parsed["gridpulse"] == 1
        assert parsed["carbon_saved_kg"] == round(
            schedule.baseline_metrics.carbon_kg
            - schedule.metrics.carbon_kg,
            6,
        )
        assert set(parsed) == {
            "carbon_saved_kg",
            "gridpulse",
            "hash",
            "schedule_id",
        }
        # sorted keys + compact separators, exactly as SPEC 14 requires
        assert memo == (
            b'{"carbon_saved_kg":'
            + json.dumps(parsed["carbon_saved_kg"]).encode()
            + b',"gridpulse":1,"hash":"'
            + parsed["hash"].encode()
            + b'","schedule_id":"'
            + schedule_id.encode()
            + b'"}'
        )


def test_sol3_settlement_timeout_leaves_schedule_applied(
    tmp_path, monkeypatch
) -> None:
    def _timeout(*args, **kwargs):
        raise TimeoutError("devnet rpc timed out")

    monkeypatch.setattr(solana, "send_memo_tx", _timeout)
    with _make_app(tmp_path, monkeypatch, mode="live") as client:
        schedule = _proposed(client)
        applied = client.post(
            f"/api/schedules/{schedule['schedule_id']}/approve"
        ).json()
        assert applied["status"] == "applied"

        # the send runs on a background thread; wait for the error row
        deadline = time.monotonic() + 5.0
        errors = _logs("error")
        while (
            not any(
                row.payload.get("integration") == "solana"
                for row in errors
            )
            and time.monotonic() < deadline
        ):
            time.sleep(0.05)
            errors = _logs("error")
        assert any(
            row.payload.get("integration") == "solana"
            for row in errors
        ), "expected a solana error row after the timed-out send"
        stored = client.get(
            f"/api/schedules/{schedule['schedule_id']}"
        ).json()
        assert stored["status"] == "applied"
        assert not any(
            row.payload.get("mode") == "live"
            for row in _logs("settlement_tx")
        )


def test_live_mode_empty_keypair_logs_error(tmp_path, monkeypatch) -> None:
    with _make_app(
        tmp_path, monkeypatch, mode="live", keypair_path=""
    ) as client:
        schedule = client.post(
            "/api/optimize", json={"alpha": 0.5}
        ).json()
        result = solana.record_settlement(
            get_state().db.get_schedule(schedule["schedule_id"])
        )
        assert result is None
        errors = _logs("error")
        assert errors[-1].payload["integration"] == "solana"
        assert "SOLANA_KEYPAIR_PATH" in errors[-1].payload["message"]


def test_live_success_logs_settlement_tx_with_explorer_url(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        solana, "send_memo_tx", lambda *a, **k: "sig-FAKElive123"
    )
    with _make_app(tmp_path, monkeypatch, mode="live") as client:
        schedule = _proposed(client)
        client.post(
            f"/api/schedules/{schedule['schedule_id']}/approve"
        )
        deadline = time.monotonic() + 5.0
        rows = _logs("settlement_tx")
        while (
            not any(row.payload.get("mode") == "live" for row in rows)
            and time.monotonic() < deadline
        ):
            time.sleep(0.05)
            rows = _logs("settlement_tx")
        live = [
            row for row in rows if row.payload.get("mode") == "live"
        ]
        assert live, "expected a live settlement_tx row"
        assert live[-1].payload == {
            "signature": "sig-FAKElive123",
            "explorer_url": "https://explorer.solana.com/tx/"
            "sig-FAKElive123?cluster=devnet",
            "mode": "live",
        }
