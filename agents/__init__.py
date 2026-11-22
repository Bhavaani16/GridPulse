"""GridPulse negotiating agents (SPEC section 12). Owner: Agents (D5).

FETCHAI_MODE=local (default): in-process function calls, no sockets.
FETCHAI_MODE=network: the same envelopes over real uAgents message
passing (agents/network.py, verified against uagents==0.26.1); it is
imported lazily by the bridge so local mode never needs the SDK.

The sibling /backend directory is added to sys.path so this package can
import the shared contracts (optimizer.models) both when invoked as
``python -m agents.demo_scenario`` from the repo root and when imported by
backend/integrations/agents_bridge.py (where /backend is already on the
path and the insert is a no-op).
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
