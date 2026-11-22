"""The one place for mutable application state (SPEC: no other globals).

create_app() builds one AppState and registers it here so that module-level
functions like schedules.request_approval(schedule_id, actor) keep their
SPEC signatures while still reaching the database and config.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Optional

from config import Config
from optimizer.models import (
    Asset,
    GridSignal,
    Job,
    OptimizeError,
    Schedule,
    solver_error,
)

if TYPE_CHECKING:
    from db import Database


def _noop_sms(schedule: Schedule) -> str:
    return "mock-sms-" + schedule.schedule_id


def _identity_negotiate(schedule: Schedule) -> Schedule:
    return schedule


def _noop_settlement(schedule: Schedule) -> Optional[str]:
    return None


def _missing_optimizer(*args: Any) -> OptimizeError:
    return solver_error("optimizer module not loaded")


def _empty_explain(*args: Any) -> tuple[str, str]:
    return "", "fallback"


@dataclass
class AppState:
    config: Config
    db: "Database"
    signals: list[GridSignal] = field(default_factory=list)
    jobs: list[Job] = field(default_factory=list)
    assets: list[Asset] = field(default_factory=list)
    ev_force_deadline: str = ""
    latest_alpha: float = 0.5
    seen_message_ids: set[str] = field(default_factory=set)
    clarified_schedule_ids: set[str] = field(default_factory=set)
    expire_task: Any = None
    pending_schedule_id: Optional[str] = None
    simulator_task: Optional[asyncio.Task] = None
    sim_temperature_c: float = 32.0
    sim_fan_on: bool = True
    sim_power_w: float = 4.5
    sse_subscribers: list[asyncio.Queue] = field(default_factory=list)
    loop: Optional[asyncio.AbstractEventLoop] = None
    startup_errors: list[dict] = field(default_factory=list)

    # Integration callables, bound at startup. Missing modules degrade to
    # safe defaults instead of crashing (SPEC section 6 startup rules).
    optimize_fn: Callable[..., Any] = _missing_optimizer
    baseline_fn: Callable[..., Any] = _missing_optimizer
    send_approval_sms: Callable[[Schedule], str] = _noop_sms
    explain_with_source: Callable[..., tuple[str, str]] = _empty_explain
    record_settlement: Callable[[Schedule], Optional[str]] = _noop_settlement
    negotiate: Callable[[Schedule], Schedule] = _identity_negotiate
    clear_gemini_cache: Callable[[], None] = lambda: None


_state: Optional[AppState] = None


def init_state(state: AppState) -> AppState:
    global _state
    previous = _state
    if previous is not None and previous is not state:
        for task in (previous.expire_task, previous.simulator_task):
            if task is not None:
                try:
                    task.cancel()
                except Exception:
                    pass
        try:
            previous.db.close()
        except Exception:
            pass
    _state = state
    return _state


def get_state() -> AppState:
    if _state is None:
        raise RuntimeError("application state is not initialized")
    return _state
