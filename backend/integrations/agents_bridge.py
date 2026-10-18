"""Fetch.ai / local agent negotiation (SPEC section 12). Owner: Agents (D5).

    negotiate(schedule: Schedule) -> Schedule

Runs the inform -> propose -> counter/accept -> merge -> one optimize ->
propose flow with grid-agent, dc-agent, and ev-agent envelopes. The wall
clock is 8 seconds; on timeout or any exception the input schedule is
returned unchanged and an error row is written. One negotiation_msg log
row is written per envelope.

FETCHAI_MODE=local (default) uses in-process calls, no sockets.
FETCHAI_MODE=network runs the same envelopes over real uAgents message
passing in agents/network.py (documented calls only; verified against
uagents==0.26.1). Any transport failure logs an error and falls back to
the local flow.
"""

from __future__ import annotations

import logging
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from decision_log import write_log
from optimizer.models import Schedule
from state import get_state

logger = logging.getLogger("gridpulse.agents")

# /agents lives at the repo root; /backend is the import root when this
# module runs inside the app, so add the repo root for `import agents`.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))

from agents.envelope import (  # noqa: E402
    AgentEnvelope,
    EnvelopeFrom,
    EnvelopeType,
)
from agents.negotiation import NegotiationDeps, run_negotiation  # noqa: E402

__all__ = ["AgentEnvelope", "EnvelopeFrom", "EnvelopeType", "negotiate"]

NEGOTIATION_TIMEOUT_SECONDS = 8.0


def _emit(envelope: AgentEnvelope) -> None:
    """One negotiation_msg log row per envelope (SPEC section 12)."""
    write_log(
        envelope.schedule_id,
        envelope.from_,
        "negotiation_msg",
        envelope.as_payload(),
    )


def _report(schedule_id: str, message: str) -> None:
    """Error row with integration agents; degrades to stdlib logging."""
    try:
        write_log(
            schedule_id,
            "bridge",
            "error",
            {"integration": "agents", "message": message},
        )
    except Exception:
        logger.error("agents error (decision log unavailable): %s", message)


def _deps_for(schedule: Schedule) -> NegotiationDeps:
    state = get_state()
    return NegotiationDeps(
        signals=state.signals,
        jobs=state.jobs,
        assets=state.assets,
        optimize_fn=state.optimize_fn,
        dc_max_it_kw=state.config.dc_max_it_kw,
        curtailment_surplus_mw=state.config.curtailment_surplus_mw,
        ev_force_deadline=state.ev_force_deadline
        or state.config.ev_force_deadline,
        emit=_emit,
        report_error=lambda message: _report(schedule.schedule_id, message),
    )


def negotiate(schedule: Schedule) -> Schedule:
    """Run the section-12 flow. Never raises; returns the input schedule
    on timeout or any failure."""
    try:
        return _negotiate(schedule)
    except Exception as exc:
        _report(
            schedule.schedule_id,
            f"negotiate: {type(exc).__name__}: {str(exc)[:300]}",
        )
        return schedule


def _transport_for(
    state, schedule: Schedule, deps: NegotiationDeps
) -> Optional[object]:
    """Build the section-12 transport for FETCHAI_MODE.

    network: real uAgents envelopes via agents/network.py. Any failure
    logs an error and falls back to the local in-process transport.
    """
    mode = state.config.fetchai_mode
    if mode == "network":
        try:
            from agents.network import make_network_transport

            return make_network_transport(deps)
        except Exception as exc:
            _report(
                schedule.schedule_id,
                f"network transport unavailable: {type(exc).__name__}: "
                f"{str(exc)[:200]}; using local calls",
            )
            return None
    if mode != "local":
        _report(
            schedule.schedule_id,
            f"FETCHAI_MODE={mode} is unknown; using local calls",
        )
    return None


def _negotiate(schedule: Schedule) -> Schedule:
    state = get_state()
    deps = _deps_for(schedule)
    transport = _transport_for(state, schedule, deps)
    if transport is not None:
        deps.transport = transport  # type: ignore[assignment]
    pool = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="gridpulse-negotiate"
    )
    try:
        future = pool.submit(run_negotiation, schedule, deps)
        return future.result(timeout=NEGOTIATION_TIMEOUT_SECONDS)
    finally:
        if transport is not None and hasattr(transport, "close"):
            try:
                transport.close()
            except Exception:
                pass
        pool.shutdown(wait=False)


def _warm_network_transport() -> None:
    """Boot the uAgents bureau in the background at import time when
    FETCHAI_MODE=network, so the first negotiate() does not pay the
    ~2 s startup inside the 8 s wall clock. No-op in local mode; any
    failure degrades to the existing fallback."""
    try:
        if get_state().config.fetchai_mode != "network":
            return
        from agents.network import NegotiationNetwork

        threading.Thread(
            target=NegotiationNetwork.get,
            name="gridpulse-uagents-warm",
            daemon=True,
        ).start()
    except Exception:
        pass


# This module is imported at app startup (_bind_integrations), which is
# the earliest cheap opportunity to pre-warm the shared bureau.
_warm_network_transport()
