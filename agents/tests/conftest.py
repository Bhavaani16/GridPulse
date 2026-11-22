"""Test fixtures for the agents package.

Tests run against a real AppState on a throwaway SQLite file so negotiate()
exercises the same write_log path as the running app. HORIZON_MODE=fixed
keeps the on-disk timestamps so EV_FORCE_DEADLINE compares literally.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
for entry in (str(REPO_ROOT), str(BACKEND_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

os.environ.setdefault("MODE", "cached")
os.environ.setdefault("HARDWARE_MODE", "simulated")
os.environ.setdefault("START_SIMULATOR", "0")
os.environ.setdefault("FETCHAI_MODE", "local")

EV_DEADLINE = "2026-06-21T21:00:00Z"


@pytest.fixture()
def app_state(tmp_path):
    import signals as signals_mod
    from config import Config
    from db import open_database
    from optimizer import optimize
    from state import AppState, init_state

    config = Config(
        data_dir=REPO_ROOT / "data",
        horizon_mode="fixed",
        ev_force_deadline=EV_DEADLINE,
    )
    store, _ = open_database(f"sqlite:///{tmp_path / 'gridpulse.db'}")
    state = init_state(AppState(config=config, db=store))
    signals, jobs, assets, ev_deadline, error = signals_mod.load_inputs(config)
    assert error is None
    state.signals = list(signals)
    state.jobs = list(jobs)
    state.assets = list(assets)
    state.ev_force_deadline = ev_deadline
    state.optimize_fn = optimize
    yield state
    store.close()


def make_schedule(signals, it_loads=None, ev_fracs=None):
    """A valid proposed Schedule with controllable IT load and EV fractions."""
    from optimizer.models import (
        JobFraction,
        Metrics,
        SavingsPct,
        Schedule,
        Slot,
    )

    it_loads = it_loads or {}
    ev_fracs = ev_fracs or {}
    slots = []
    for t, signal in enumerate(signals):
        it = it_loads.get(t, 4.0)
        fraction = ev_fracs.get(t, 0.0)
        ev_kw = round(7.0 * fraction, 6)
        jobs = [JobFraction(job_id="job-cp-01", fraction=1.0)]
        if fraction > 0:
            jobs.append(JobFraction(job_id="job-ev-01", fraction=fraction))
        slots.append(
            Slot(
                t=t,
                ts=signal.ts,
                cooling_mode="wet",
                it_load_kw=it,
                yw_kw=it,
                yd_kw=0.0,
                ev_load_kw=ev_kw,
                total_load_kw=round(1.15 * it + ev_kw, 6),
                jobs=jobs,
            )
        )
    metrics = Metrics(cost_usd=0.0, carbon_kg=0.0, water_l=0.0, energy_kwh=0.0)
    return Schedule(
        schedule_id="sch-test-agents",
        schedule_kind="optimized",
        status="proposed",
        alpha=0.5,
        horizon_start=signals[0].ts,
        created_at="2026-06-21T19:00:00Z",
        slots=slots,
        metrics=metrics,
        baseline_metrics=metrics,
        savings_pct=SavingsPct(cost=0.0, carbon=0.0, water=0.0),
        shifted_job_count=0,
        shifted_kwh=0.0,
        savings_label="simulated",
        explanation=None,
    )


def negotiation_rows(state):
    return [
        entry
        for entry in state.db.list_logs(200, None)
        if entry.event == "negotiation_msg"
    ]


def error_rows(state):
    return [
        entry
        for entry in state.db.list_logs(200, None)
        if entry.event == "error"
    ]
