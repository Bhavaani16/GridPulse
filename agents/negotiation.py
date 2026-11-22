"""The section-12 negotiation flow.

    inform -> propose r1 -> counter merge -> one optimize -> propose r2

run_negotiation is synchronous and deterministic; the 8-second wall
clock and the never-raise guarantee live in
backend/integrations/agents_bridge.py, which also supplies emit (one
negotiation_msg log row per envelope) and report_error (error rows with
integration "agents").

Transport is pluggable: LocalTransport calls the agent reply functions
in-process (FETCHAI_MODE=local), agents/network.py swaps in real uAgents
delivery (FETCHAI_MODE=network). The flow is identical either way.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional, Protocol, Sequence, Union

from agents.envelope import (
    AgentEnvelope,
    MalformedEnvelope,
    validate_reply,
)
from agents.local_agents import (
    dc_agent_reply,
    ev_agent_replies,
    grid_inform_body,
)
from optimizer.models import (
    Asset,
    Constraints,
    GridSignal,
    Job,
    OptimizeError,
    Schedule,
)

OptimizeFn = Callable[
    [Sequence[GridSignal], Sequence[Job], Sequence[Asset], float, object],
    Union[Schedule, OptimizeError],
]
EmitFn = Callable[[AgentEnvelope], None]
ReportFn = Callable[[str], None]

RESPONDERS = ("dc-agent", "ev-agent")


class Transport(Protocol):
    """Envelope delivery. send() logs and delivers; collect() returns the
    reply envelopes grouped by sender for the proposed schedule."""

    def send(self, envelope: AgentEnvelope) -> None: ...

    def collect(
        self, senders: Sequence[str], schedule: Schedule
    ) -> dict[str, list[AgentEnvelope]]: ...


@dataclass
class NegotiationDeps:
    """Everything the flow needs; injected so tests and the demo can run
    without the FastAPI app state."""

    signals: Sequence[GridSignal]
    jobs: Sequence[Job]
    assets: Sequence[Asset]
    optimize_fn: OptimizeFn
    dc_max_it_kw: float
    curtailment_surplus_mw: float
    ev_force_deadline: str
    emit: EmitFn
    report_error: ReportFn
    transport: Optional[Transport] = None


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def _emit(deps: NegotiationDeps, envelope: AgentEnvelope) -> None:
    try:
        deps.emit(envelope)
    except Exception as exc:
        deps.report_error(f"negotiation_msg log failed: {type(exc).__name__}")


def _envelope(
    sender: str, to: str, type_: str, schedule_id: str, body: dict
) -> AgentEnvelope:
    return AgentEnvelope(
        from_=sender,  # type: ignore[arg-type]
        to=to,  # type: ignore[arg-type]
        type=type_,  # type: ignore[arg-type]
        schedule_id=schedule_id,
        body=body,
    )


class LocalTransport:
    """FETCHAI_MODE=local: in-process function calls, no sockets."""

    def __init__(self, deps: NegotiationDeps) -> None:
        self._deps = deps

    def send(self, envelope: AgentEnvelope) -> None:
        _emit(self._deps, envelope)

    def collect(
        self, senders: Sequence[str], schedule: Schedule
    ) -> dict[str, list[AgentEnvelope]]:
        deps = self._deps
        replies: dict[str, list[AgentEnvelope]] = {}
        for sender in senders:
            try:
                if sender == "dc-agent":
                    bodies = [dc_agent_reply(schedule, deps.dc_max_it_kw)]
                else:
                    ev_job_ids = [
                        job.job_id
                        for job in deps.jobs
                        if job.kind == "ev_charge"
                    ]
                    bodies = ev_agent_replies(
                        schedule, ev_job_ids, deps.ev_force_deadline
                    )
            except Exception as exc:
                deps.report_error(f"{sender} failed: {type(exc).__name__}")
                bodies = []
            replies[sender] = [
                _envelope(sender, "bridge", type_, schedule.schedule_id, body)
                for body in bodies
                for type_ in (
                    "accept" if body.get("accepted") is True else "counter",
                )
            ]
        return replies


def _propose_round(
    deps: NegotiationDeps, transport: Transport, schedule: Schedule
) -> tuple[list[AgentEnvelope], bool]:
    """Bridge proposes to dc-agent and ev-agent.

    Returns (executed replies, complete) where complete is True only when
    both agents produced at least one executed reply. Replies that fail
    validation are logged as error and not executed.
    """
    for target in RESPONDERS:
        transport.send(
            _envelope(
                "bridge",
                target,
                "propose",
                schedule.schedule_id,
                {"schedule": schedule.model_dump()},
            )
        )
    replies: list[AgentEnvelope] = []
    complete = True
    for sender, raw in transport.collect(RESPONDERS, schedule).items():
        executed: list[AgentEnvelope] = []
        for envelope in raw:
            try:
                executed.append(validate_reply(envelope, sender))  # type: ignore[arg-type]
            except MalformedEnvelope as exc:
                deps.report_error(str(exc)[:300])
        if not executed:
            complete = False
        for envelope in executed:
            _emit(deps, envelope)
        replies.extend(executed)
    return replies, complete


def _merge_constraints(replies: Sequence[AgentEnvelope]) -> Constraints:
    """max_it_kw is the smallest countered value; job_deadlines keeps the
    earliest deadline named for each job (SPEC section 12)."""
    max_it_kw: Optional[float] = None
    job_deadlines: dict[str, str] = {}
    for reply in replies:
        if reply.type != "counter":
            continue
        body = reply.body
        if body.get("constraint") == "max_it_kw":
            value = float(body["max_it_kw"])
            if max_it_kw is None or value < max_it_kw:
                max_it_kw = value
        elif body.get("constraint") == "ev_deadline":
            job_id = str(body["job_id"])
            deadline = str(body["deadline_ts"])
            current = job_deadlines.get(job_id)
            if current is None or _ts(deadline) < _ts(current):
                job_deadlines[job_id] = deadline
    return Constraints(max_it_kw=max_it_kw, job_deadlines=job_deadlines)


def run_negotiation(schedule: Schedule, deps: NegotiationDeps) -> Schedule:
    """The section-12 flow. The bridge adds the wall clock and the
    never-raise guarantee around this function."""
    transport = deps.transport or LocalTransport(deps)

    transport.send(
        _envelope(
            "grid-agent",
            "bridge",
            "inform",
            schedule.schedule_id,
            grid_inform_body(deps.signals, deps.curtailment_surplus_mw),
        )
    )

    replies, complete = _propose_round(deps, transport, schedule)
    counters = [reply for reply in replies if reply.type == "counter"]
    if complete and not counters:
        # Every executed reply is accept and none was dropped.
        return schedule

    constraints = _merge_constraints(replies)
    result = deps.optimize_fn(
        deps.signals, deps.jobs, deps.assets, schedule.alpha, constraints
    )
    if isinstance(result, OptimizeError):
        deps.report_error(
            f"re-optimize after counters failed: {result.code} {result.message}"
        )
        return schedule

    # Round 2: propose once, record the replies, never optimize again.
    _propose_round(deps, transport, result)
    return result
