#!/usr/bin/env python3
"""Simulate an inbound SMS reply in PHOTON_MODE=mock (SPEC section 10).

Usage:
    python scripts/simulate_reply.py YES
    python scripts/simulate_reply.py NO

Posts {"message_id": "sim-<8 hex>", "from_number": OPERATOR_PHONE,
"text": YES|NO} to <base>/api/webhooks/photon and prints the result.
The base URL comes from GRIDPULSE_API_URL (default http://127.0.0.1:8000).
Phone numbers are masked in all output.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _mask(phone: str) -> str:
    if len(phone) < 2:
        return "**"
    return "*" * (len(phone) - 2) + phone[-2:]


def main() -> int:
    _load_env()
    if len(sys.argv) != 2 or sys.argv[1] not in ("YES", "NO"):
        print("usage: simulate_reply.py YES|NO", file=sys.stderr)
        return 2
    text = sys.argv[1]
    base = os.environ.get("GRIDPULSE_API_URL", "http://127.0.0.1:8000")
    operator = os.environ.get("OPERATOR_PHONE", "+15551230000")
    body = {
        "message_id": "sim-" + secrets.token_hex(4),
        "from_number": operator,
        "text": text,
    }
    url = base.rstrip("/") + "/api/webhooks/photon"
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read())
    except Exception as exc:
        print(f"webhook POST failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"sent {text} as {body['message_id']} from "
        f"{_mask(operator)} -> {json.dumps(payload)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
