"""FETCHAI_MODE=network transport: real uAgents message passing.

Four uAgents `Agent` objects (bridge, grid-agent, dc-agent, ev-agent)
run in one `Bureau` on a daemon thread and exchange the section-12
envelope as `EnvelopeMsg(envelope_json=...)`. Only documented uAgents
calls are used: Agent(name, seed, resolve), Bureau(agents, port,
endpoint), agent.on_message, agent.on_interval, ctx.send(address,
Model), bureau.run(), RulesBasedResolver. Verified against
uagents==0.26.1.

Address resolution is a RulesBasedResolver mapping each agent1q address
to the bureau's local /submit endpoint, so sends travel real HTTP into
the bureau's ASGI server and never touch the Almanac (works offline).

Outgoing envelopes are queued per sender agent and drained by that
agent's `on_interval` handler (ctx.send only exists inside handlers).
Incoming replies land in the bridge agent's `on_message` handler and are
collected by NetworkTransport.collect. The responder agents hold no
state; they call the same pure reply functions as local mode.

FETCHAI_API_KEY / ASI_ONE_API_KEY are not consumed: Agentverse-hosted
features (mailbox provisioning, Search API, hosted agents) are outside
the section-12 contract. See docs/DECISIONS.md.
"""

from __future__ import annotations

import queue
import socket
import threading
import time
from typing import Callable, Optional, Sequence

from agents.envelope import AgentEnvelope
from agents.local_agents import dc_agent_reply, ev_agent_replies
from optimizer.models import Schedule

REPLY_TIMEOUT_SECONDS = 2.5
REPLY_SETTLE_SECONDS = 0.15
OUTBOX_POLL_SECONDS = 0.05
READY_TIMEOUT_SECONDS = 2.0

# Stable seeds -> stable agent1q addresses across restarts (docs: seed
# phrases set fixed addresses).
_SEEDS = {
    "bridge": "gridpulse-bridge-seed-phrase",
    "grid-agent": "gridpulse-grid-agent-seed-phrase",
    "dc-agent": "gridpulse-dc-agent-seed-phrase",
    "ev-agent": "gridpulse-ev-agent-seed-phrase",
}

ResponderFn = Callable[[str], list[AgentEnvelope]]


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _reply_envelope(sender: str, schedule_id: str, body: dict) -> AgentEnvelope:
    type_ = "accept" if body.get("accepted") is True else "counter"
    return AgentEnvelope(
        from_=sender,  # type: ignore[arg-type]
        to="bridge",
        type=type_,  # type: ignore[arg-type]
        schedule_id=schedule_id,
        body=body,
    )


def _schedule_from_wire(envelope_json: str) -> Schedule:
    envelope = AgentEnvelope.model_validate_json(envelope_json)
    return Schedule.model_validate(envelope.body["schedule"])


class NegotiationNetwork:
    """Process-wide uAgents runtime: one bureau, started lazily, living
    for the process lifetime (like a connection pool)."""

    _instance: Optional["NegotiationNetwork"] = None
    _instance_lock = threading.Lock()

    @classmethod
    def get(cls) -> "NegotiationNetwork":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self) -> None:
        # Agent construction needs an event loop on the calling thread;
        # get() can be reached from asyncio.to_thread workers and the
        # warm-up thread, neither of which has one by default.
        import asyncio

        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())
        self.negotiation_lock = threading.Lock()
        self.ready = threading.Event()
        self.inbox: "queue.Queue[AgentEnvelope]" = queue.Queue()
        self.outbox: dict[str, "queue.Queue[tuple[str, object]]"] = {
            name: queue.Queue() for name in _SEEDS
        }
        self.responder_fns: dict[str, ResponderFn] = {}
        self._agents = {}
        self._build_and_run()

    def set_responder(self, name: str, fn: ResponderFn) -> None:
        self.responder_fns[name] = fn

    def _build_and_run(self) -> None:
        from uagents import Agent, Bureau, Context, Model
        from uagents.resolver import RulesBasedResolver

        class EnvelopeMsg(Model):
            envelope_json: str

        self.msg_model = EnvelopeMsg

        port = _free_port()
        endpoint = f"http://127.0.0.1:{port}/submit"

        # Addresses are deterministic from the seeds, so every agent can
        # resolve every other agent's address to the bureau's /submit
        # endpoint: real HTTP, no Almanac lookup.
        from uagents.crypto import Identity

        addresses = {
            name: Identity.from_seed(seed, 0).address
            for name, seed in _SEEDS.items()
        }
        rules = {address: endpoint for address in addresses.values()}
        for name, seed in _SEEDS.items():
            self._agents[name] = Agent(
                name=name, seed=seed, resolve=RulesBasedResolver(rules)
            )

        for name, agent in self._agents.items():
            outbox = self.outbox[name]

            # ctx.send only exists inside a handler, so an interval task
            # forwards this agent's queued envelopes.
            async def _drain_box(ctx: Context, box=outbox) -> None:
                self.ready.set()  # bureau is up and handlers are live
                while True:
                    try:
                        dest, msg = box.get_nowait()
                    except queue.Empty:
                        return
                    await ctx.send(self._agents[dest].address, msg)

            agent.on_interval(period=OUTBOX_POLL_SECONDS)(_drain_box)

        bridge = self._agents["bridge"]

        @bridge.on_message(model=EnvelopeMsg)
        async def _inbox(ctx: Context, sender: str, msg: EnvelopeMsg) -> None:
            try:
                self.inbox.put(
                    AgentEnvelope.model_validate_json(msg.envelope_json)
                )
            except Exception:
                pass  # malformed wire input never reaches the flow

        for name in ("dc-agent", "ev-agent"):

            def _make_responder(agent_name: str):
                @self._agents[agent_name].on_message(model=EnvelopeMsg)
                async def _reply(
                    ctx: Context, sender: str, msg: EnvelopeMsg
                ) -> None:
                    fn = self.responder_fns.get(agent_name)
                    if fn is None:
                        return
                    try:
                        replies = fn(msg.envelope_json)
                    except Exception:
                        return
                    for reply in replies:
                        await ctx.send(
                            sender,
                            EnvelopeMsg(
                                envelope_json=reply.model_dump_json(
                                    by_alias=True
                                )
                            ),
                        )

                return _reply

            _make_responder(name)

        bureau = Bureau(
            agents=list(self._agents.values()),
            port=port,
            endpoint=endpoint,
            log_level="ERROR",
        )
        self.thread = threading.Thread(
            target=bureau.run, name="gridpulse-uagents", daemon=True
        )
        self.thread.start()


class NetworkTransport:
    """Section-12 transport over real uAgents envelopes.

    send() logs the envelope and queues it on the sender agent's outbox;
    collect() polls the bridge inbox for reply envelopes from the
    expected senders about the proposed schedule.
    """

    def __init__(self, deps) -> None:
        self._net = NegotiationNetwork.get()
        self._net.negotiation_lock.acquire()
        self._closed = False
        self._deps = deps
        self._net.set_responder("dc-agent", self._dc_replies)
        self._net.set_responder("ev-agent", self._ev_replies)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._net.responder_fns.clear()
            self._net.negotiation_lock.release()

    # responder-side: runs inside the uAgents handlers -------------------

    def _dc_replies(self, envelope_json: str) -> list[AgentEnvelope]:
        schedule = _schedule_from_wire(envelope_json)
        return [
            _reply_envelope("dc-agent", schedule.schedule_id, body)
            for body in [dc_agent_reply(schedule, self._deps.dc_max_it_kw)]
        ]

    def _ev_replies(self, envelope_json: str) -> list[AgentEnvelope]:
        schedule = _schedule_from_wire(envelope_json)
        ev_job_ids = [
            job.job_id for job in self._deps.jobs if job.kind == "ev_charge"
        ]
        return [
            _reply_envelope("ev-agent", schedule.schedule_id, body)
            for body in ev_agent_replies(
                schedule, ev_job_ids, self._deps.ev_force_deadline
            )
        ]

    # transport interface ------------------------------------------------

    def send(self, envelope: AgentEnvelope) -> None:
        self._deps.emit(envelope)
        # Bound the bureau-startup wait so round 1 is not lost while the
        # server is still booting; a timeout just queues and lets
        # collect() report the missing reply.
        self._net.ready.wait(timeout=READY_TIMEOUT_SECONDS)
        self._net.outbox[envelope.from_].put(
            (
                envelope.to,
                self._net.msg_model(
                    envelope_json=envelope.model_dump_json(by_alias=True)
                ),
            )
        )

    def collect(
        self, senders: Sequence[str], schedule: Schedule
    ) -> dict[str, list[AgentEnvelope]]:
        """One shared deadline for every expected reply. A sender's
        replies settle REPLY_SETTLE_SECONDS after the last matching
        envelope (ev-agent can emit one counter per violating job)."""
        deadline = time.monotonic() + REPLY_TIMEOUT_SECONDS
        found: dict[str, list[AgentEnvelope]] = {s: [] for s in senders}
        last_hit = 0.0
        while time.monotonic() < deadline:
            if not self._net.thread.is_alive():
                self._deps.report_error("uagents bureau thread stopped")
                return found
            try:
                env = self._net.inbox.get(timeout=0.05)
            except queue.Empty:
                env = None
            if env is not None:
                if env.from_ in found and env.schedule_id == schedule.schedule_id:
                    found[env.from_].append(env)
                    last_hit = time.monotonic()
                # Stale envelopes (informs, earlier rounds) are dropped.
            if all(found[s] for s in senders) and (
                time.monotonic() - last_hit > REPLY_SETTLE_SECONDS
            ):
                return found
        for sender in senders:
            if not found[sender]:
                self._deps.report_error(
                    f"no reply from {sender} within {REPLY_TIMEOUT_SECONDS}s"
                )
        return found


def make_network_transport(deps) -> NetworkTransport:
    """Bind the shared uAgents bureau to this negotiation's deps."""
    return NetworkTransport(deps)
