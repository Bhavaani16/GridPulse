"""python -m agents.demo_scenario — SPEC section 12 demo.

Builds a schedule with one slot at it_load_kw 8.0 (above the default
DC_MAX_IT_KW 6.0) and runs it through the real backend bridge: inform,
round-1 proposes, a dc-agent counter, one re-optimize, round-2 proposes.
Every negotiation_msg decision-log row is printed as one JSON line.
Exits 0 when at least one counter envelope appears, 1 otherwise.

Run from the repo root:  backend/.local/venv/bin/python -m agents.demo_scenario
"""

from __future__ import annotations

import json
import sys

import agents  # noqa: F401  (puts /backend on sys.path)
from optimizer.models import Schedule


def _with_it_load(schedule: Schedule, t: int, it_load_kw: float) -> Schedule:
    """Return a copy of schedule with slot t set to it_load_kw."""
    slot = schedule.slots[t]
    delta = it_load_kw - slot.it_load_kw
    slots = list(schedule.slots)
    slots[t] = slot.model_copy(
        update={
            "it_load_kw": it_load_kw,
            "yw_kw": slot.yw_kw + delta,
            "total_load_kw": slot.total_load_kw + 1.15 * delta,
        }
    )
    return schedule.model_copy(update={"slots": slots})


def main() -> int:
    import signals as signals_mod
    from config import Config, load_env
    from db import open_database
    from optimizer import baseline, optimize
    from optimizer.models import OptimizeError
    from state import AppState, init_state

    load_env()
    config = Config.from_env()
    store, db_error = open_database("sqlite:///:memory:")
    if db_error:
        print(f"db error: {db_error}")
    state = init_state(AppState(config=config, db=store))
    signals, jobs, assets, ev_deadline, load_error = signals_mod.load_inputs(
        config
    )
    if load_error:
        print(f"input load error: {load_error}")
    state.signals = list(signals)
    state.jobs = list(jobs)
    state.assets = list(assets)
    state.ev_force_deadline = ev_deadline
    state.optimize_fn = optimize

    built = baseline(state.signals, state.jobs, state.assets)
    if isinstance(built, OptimizeError):
        print(f"baseline failed: {built.message}")
        return 1
    schedule = _with_it_load(built, 0, 8.0)
    print(
        f"demo: {schedule.schedule_id} with slot 0 it_load_kw=8.0, "
        f"DC_MAX_IT_KW={config.dc_max_it_kw}, "
        f"FETCHAI_MODE={config.fetchai_mode}"
    )

    from integrations.agents_bridge import negotiate

    result = negotiate(schedule)

    rows = [
        entry
        for entry in store.list_logs(200, None)
        if entry.event == "negotiation_msg"
    ]
    for entry in rows:
        print(json.dumps(entry.payload, sort_keys=True))
    for entry in store.list_logs(200, None):
        if entry.event == "error":
            print(f"error row: {json.dumps(entry.payload, sort_keys=True)}")
    counters = [e for e in rows if e.payload.get("type") == "counter"]
    print(
        f"negotiation: {len(rows)} envelopes, {len(counters)} counter(s), "
        f"returned {result.schedule_id}"
    )
    return 0 if counters else 1


if __name__ == "__main__":
    sys.exit(main())
