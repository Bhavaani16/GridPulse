"""Solana devnet settlement logging (SPEC section 14). Owner: Solana (D6).

    record_settlement(schedule: Schedule) -> str | None

Called after a schedule row is committed with status=applied.

mock mode (SOLANA_MODE=mock, the default): no socket. Returns
"mocksig-" + the first 16 hex chars of SHA-256(UTF-8 schedule_id) and
logs settlement_tx with mode mock, explorer_url null.

live mode (SOLANA_MODE=live): builds one SPL Memo instruction carrying
the section-14 memo JSON, signs it with the keypair file at
SOLANA_KEYPAIR_PATH, and sends it to SOLANA_RPC_URL over JSON-RPC
(getLatestBlockhash + sendTransaction). The send runs on a daemon
thread so the applied schedule is never blocked; the call returns None
immediately and the settlement_tx or error row lands when the wire call
finishes. Timeout 10 s, no retry.

Library calls come from the installed solders==0.29.0 source:
Keypair.from_bytes, Pubkey.from_string, Instruction, Hash.from_string,
Message.new_with_blockhash, Transaction.new_unsigned, tx.sign,
bytes(tx). RPC transport is plain JSON-RPC over httpx.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
from typing import Optional

import httpx

from decision_log import write_log
from optimizer.metrics import metrics_hash
from optimizer.models import Schedule
from state import get_state

RPC_TIMEOUT_SECONDS = 10.0

# SPL Memo program (v2). Fixed program id, not a credential.
MEMO_PROGRAM_ID = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"


def _log(schedule_id: str, event: str, payload: dict) -> None:
    try:
        write_log(schedule_id, "solana", event, payload)
    except Exception:
        pass


def _error(schedule_id: str, message: str) -> None:
    _log(
        schedule_id,
        "error",
        {"integration": "solana", "message": message},
    )


def build_memo_json(schedule: Schedule) -> bytes:
    """The section-14 memo: keys sorted, compact separators, UTF-8."""
    memo = {
        "carbon_saved_kg": round(
            schedule.baseline_metrics.carbon_kg - schedule.metrics.carbon_kg,
            6,
        ),
        "gridpulse": 1,
        "hash": metrics_hash(schedule.metrics),
        "schedule_id": schedule.schedule_id,
    }
    return json.dumps(memo, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _post_rpc(rpc_url: str, method: str, params: list) -> object:
    """One JSON-RPC call. Raises on transport or RPC error; no retry."""
    response = httpx.post(
        rpc_url,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=RPC_TIMEOUT_SECONDS,
    )
    body = response.json()
    if "error" in body and body["error"] is not None:
        raise RuntimeError(f"rpc {method}: {body['error']}")
    return body["result"]


def send_memo_tx(rpc_url: str, keypair_path: str, schedule: Schedule) -> str:
    """Build, sign and send the memo transaction. Returns the signature.

    Raises on any failure (caller logs and swallows). solders calls are
    verified against the installed 0.29.0 package."""
    from solders.hash import Hash
    from solders.instruction import Instruction
    from solders.keypair import Keypair
    from solders.message import Message
    from solders.pubkey import Pubkey
    from solders.transaction import Transaction

    with open(os.path.expanduser(keypair_path)) as fh:
        keypair = Keypair.from_bytes(bytes(json.load(fh)))

    blockhash_resp = _post_rpc(rpc_url, "getLatestBlockhash", [])
    blockhash = Hash.from_string(blockhash_resp["value"]["blockhash"])

    instruction = Instruction(
        Pubkey.from_string(MEMO_PROGRAM_ID),
        build_memo_json(schedule),
        [],
    )
    message = Message.new_with_blockhash(
        [instruction], keypair.pubkey(), blockhash
    )
    tx = Transaction.new_unsigned(message)
    tx.sign([keypair], blockhash)

    wire = base64.b64encode(bytes(tx)).decode("ascii")
    return _post_rpc(
        rpc_url,
        "sendTransaction",
        [wire, {"encoding": "base64"}],
    )


def _live_send_and_log(
    rpc_url: str, keypair_path: str, schedule: Schedule
) -> None:
    """Runs on the settlement thread; owns the outcome log row."""
    try:
        signature = send_memo_tx(rpc_url, keypair_path, schedule)
    except Exception as exc:
        _error(
            schedule.schedule_id,
            f"settlement send failed: {type(exc).__name__}: "
            f"{str(exc)[:200]}",
        )
        return
    _log(
        schedule.schedule_id,
        "settlement_tx",
        {
            "signature": signature,
            "explorer_url": "https://explorer.solana.com/tx/"
            f"{signature}?cluster=devnet",
            "mode": "live",
        },
    )


def record_settlement(schedule: Schedule) -> Optional[str]:
    """SPEC section 14. Never raises; a failure logs error with
    integration solana and leaves the applied schedule alone."""
    try:
        state = get_state()
        mode = state.config.solana_mode
    except Exception as exc:
        _error(schedule.schedule_id, f"config unavailable: {exc}")
        return None

    if mode != "live":
        digest = hashlib.sha256(
            schedule.schedule_id.encode("utf-8")
        ).hexdigest()
        signature = "mocksig-" + digest[:16]
        _log(
            schedule.schedule_id,
            "settlement_tx",
            {
                "signature": signature,
                "explorer_url": None,
                "mode": "mock",
            },
        )
        return signature

    rpc_url = state.config.solana_rpc_url
    keypair_path = state.config.solana_keypair_path
    if not keypair_path:
        _error(
            schedule.schedule_id,
            "SOLANA_MODE=live but SOLANA_KEYPAIR_PATH is empty",
        )
        return None

    # Background per SPEC 14: the HTTP handler must not wait for devnet.
    threading.Thread(
        target=_live_send_and_log,
        args=(rpc_url, keypair_path, schedule),
        name="gridpulse-settlement",
        daemon=True,
    ).start()
    return None
