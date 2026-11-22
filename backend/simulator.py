"""Simulated ESP32 fan (SPEC section 9). Runs when START_SIMULATOR=1.

Calls the in-process telemetry ingest every 2.0 seconds and opens no
socket. Starts at temp_c 32.0 with the fan assumed on, then follows the
command returned by the ingest: fan on cools toward 28.0, fan off warms
toward 45.0.
"""

from __future__ import annotations

import asyncio

import clock
from decision_log import write_log
from models import Telemetry
from state import AppState
from telemetry import ingest

DEVICE_ID = "esp32-fan-sim"
TICK_SECONDS = 2.0


def step(state: AppState) -> dict:
    """Post one simulated Telemetry row in-process, then update the sim."""
    body = Telemetry(
        device_id=DEVICE_ID,
        ts=clock.now_utc(),
        power_w=state.sim_power_w,
        temp_c=round(state.sim_temperature_c, 6),
        fan_on=state.sim_fan_on,
        simulated=True,
    )
    result = ingest(state, body)
    command_on = bool(result["command"]["fan_on"])
    state.sim_fan_on = command_on
    if command_on:
        state.sim_temperature_c = max(28.0, state.sim_temperature_c - 0.3)
        state.sim_power_w = 4.5
    else:
        state.sim_temperature_c = min(45.0, state.sim_temperature_c + 0.3)
        state.sim_power_w = 0.0
    return result


async def run(state: AppState) -> None:
    while True:
        try:
            step(state)
        except Exception as exc:
            write_log(
                None,
                "simulator",
                "error",
                {"integration": "simulator", "message": f"step: {exc}"},
            )
        await asyncio.sleep(TICK_SECONDS)


def start(state: AppState) -> asyncio.Task:
    state.sim_temperature_c = 32.0
    state.sim_fan_on = True
    state.sim_power_w = 4.5
    return asyncio.create_task(run(state))
