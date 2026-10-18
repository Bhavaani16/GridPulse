# agents — GridPulse negotiating agents (SPEC section 12)

Three agents and the negotiation flow used by
`backend/integrations/agents_bridge.py`:

- `grid-agent` sends one `inform` with the curtailment-surplus window.
- `dc-agent` replies `accept`, or `counter` `max_it_kw` when any slot's
  `it_load_kw` exceeds `DC_MAX_IT_KW` (default 6.0).
- `ev-agent` replies `accept`, or one `counter` `ev_deadline` per
  `ev_charge` job with a fraction at or after `EV_FORCE_DEADLINE`.

Flow: `inform` -> round-1 `propose` -> merge counters -> at most one
`optimize` call -> round-2 `propose` -> return the round-2 schedule.
Each envelope is one `negotiation_msg` decision-log row. A malformed
envelope is logged as `error` with `integration` `agents` and is not
executed. The bridge enforces an 8-second wall clock and returns the
input schedule on any failure.

## Transport: local and network

`FETCHAI_MODE=local` (the default) uses in-process function calls — no
sockets, fully deterministic.

`FETCHAI_MODE=network` delivers the same envelopes over real uAgents
message passing (`agents/network.py`): four `Agent` objects in one
`Bureau` on a daemon thread, a `RulesBasedResolver` mapping each agent1q
address to the bureau's local `/submit` endpoint, `ctx.send` /
`on_message` / `on_interval`. Only calls verified in the installed
`uagents==0.26.1` source are used. Any transport failure logs an
`agents` error and falls back to local. `FETCHAI_API_KEY` /
`ASI_ONE_API_KEY` are not consumed: the bureau needs no credentials and
works offline.

## Run

```bash
# demo: prints every envelope; at least one counter appears
backend/.local/venv/bin/python -m agents.demo_scenario

# tests (AG-1 .. AG-4)
backend/.local/venv/bin/python -m pytest agents/tests -q
```

## Verified

- `hello_world.py`: documented uAgents hello-world (send/receive via
  `ctx.send` + `on_message`) — PASS.
- `demo_scenario` under `FETCHAI_MODE=network`: full two-round flow over
  real envelopes, dc + ev counters received — PASS.

## Not tested live

Agentverse-hosted agents, Almanac/remote registration, mailbox delivery,
and ASI:One integration — the bureau runs in-process on loopback HTTP.
The bureau is pre-warmed at app startup (`_warm_network_transport` in
the bridge), so a warm negotiation is loopback HTTP + one optimize call;
a cold first call or a timeout falls back to the input schedule.
