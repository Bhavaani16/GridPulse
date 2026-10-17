"""Live signal fetch. Default callers receive the cached horizon and open no socket.

SPEC: until /docs/data_sources.txt lists an URL, do not call the network from
the cache path. Provider probes run only from fetch_signals.py --probe.
"""

from __future__ import annotations

from data_tools.fetch_signals import load_cached_signals
from data_tools.models import GridSignal


def fetch_live_signals() -> list[GridSignal]:
    """Return cached rows 0..23. Does not open a socket."""
    return load_cached_signals()[:24]
