"""python -m agents.hello_world — Fetch.ai credentials-gate smoke test.

The smallest documented uAgents hello-world: two agents in one Bureau
(uAgents docs, "Bureau"), one sends a Ping on startup, the other replies
with a Pong via ctx.send(sender, ...). Prints PASS or FAIL and exits.

Run from the repo root:  backend/.local/venv/bin/python -m agents.hello_world
"""

from __future__ import annotations

import socket
import sys
import threading

TIMEOUT_SECONDS = 15.0


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def main() -> int:
    from uagents import Agent, Bureau, Context, Model

    class Ping(Model):
        text: str

    class Pong(Model):
        text: str

    got_ping = threading.Event()
    got_pong = threading.Event()

    sender = Agent(name="gp-hello-sender", seed="gridpulse-hello-sender-seed")
    receiver = Agent(
        name="gp-hello-receiver", seed="gridpulse-hello-receiver-seed"
    )

    @receiver.on_message(model=Ping)
    async def _on_ping(ctx: Context, sender_addr: str, msg: Ping):
        got_ping.set()
        await ctx.send(sender_addr, Pong(text="pong"))

    @sender.on_message(model=Pong)
    async def _on_pong(ctx: Context, sender_addr: str, msg: Pong):
        got_pong.set()

    @sender.on_event("startup")
    async def _start(ctx: Context):
        # Retry a few times in case the peer handler is not ready yet.
        for _ in range(5):
            if got_pong.is_set():
                return
            await ctx.send(receiver.address, Ping(text="ping"))
            import asyncio

            await asyncio.sleep(0.5)

    bureau = Bureau(agents=[sender, receiver], port=_free_port(), log_level="ERROR")
    thread = threading.Thread(target=bureau.run, daemon=True)
    thread.start()

    ok = got_ping.wait(TIMEOUT_SECONDS) and got_pong.wait(TIMEOUT_SECONDS)
    print(f"hello_world: sender={sender.address}")
    print(f"hello_world: receiver={receiver.address}")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
