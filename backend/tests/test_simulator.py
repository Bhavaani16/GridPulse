"""Simulator behavior (SPEC section 9)."""

from __future__ import annotations

import simulator
from fastapi.testclient import TestClient
from state import get_state


def test_simulator_step_posts_and_adapts(client: TestClient) -> None:
    state = get_state()
    assert state.sim_temperature_c == 32.0
    first = simulator.step(state)
    command_on = first["command"]["fan_on"]
    if command_on:
        assert state.sim_temperature_c == 31.7
        assert state.sim_power_w == 4.5
    else:
        assert state.sim_temperature_c == 32.3
        assert state.sim_power_w == 0.0
    assert state.sim_fan_on == command_on

    items = client.get("/api/telemetry", params={"minutes": 5}).json()["items"]
    sim_rows = [row for row in items if row["device_id"] == "esp32-fan-sim"]
    assert len(sim_rows) == 1
    assert sim_rows[0]["simulated"] is True


def test_simulator_temperature_bounds(client: TestClient) -> None:
    state = get_state()
    for _ in range(20):
        simulator.step(state)
    assert 28.0 <= state.sim_temperature_c <= 45.0
