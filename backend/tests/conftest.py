"""Test fixtures. The app must start offline: MODE=cached, no DATABASE_URL.

Every test gets a fresh app on a fresh SQLite file so the schedule state
machine starts from sch-baseline each time.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Set before main is imported so the module-level app also sees them.
os.environ.setdefault("MODE", "cached")
os.environ.setdefault("HARDWARE_MODE", "simulated")
os.environ.setdefault("START_SIMULATOR", "0")
os.environ.setdefault("OPTIMIZER_MODE", "real")
os.environ.setdefault("PHOTON_MODE", "mock")
os.environ.setdefault("GEMINI_MODE", "mock")
os.environ.setdefault("SOLANA_MODE", "mock")
os.environ.setdefault("FETCHAI_MODE", "local")
os.environ.setdefault("DATABASE_URL", "")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'gridpulse.db'}")
    monkeypatch.setenv("START_SIMULATOR", "0")
    from main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
