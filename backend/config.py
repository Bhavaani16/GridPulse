"""Environment configuration. /backend loads .env from the repo root."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent

DISK_HORIZON_START = "2026-06-21T07:00:00Z"


def load_env() -> None:
    """Load the repo-root .env. Existing environment variables win."""
    load_dotenv(REPO_ROOT / ".env", override=False)


@dataclass(frozen=True)
class Config:
    mode: str = "cached"
    hardware_mode: str = "simulated"
    start_simulator: bool = False
    database_url: str = ""
    data_dir: Path = field(default_factory=lambda: REPO_ROOT / "data")
    optimizer_mode: str = "real"
    cors_origins: str = "http://localhost:5173"
    photon_mode: str = "mock"
    photon_timeout_seconds: float = 300.0
    operator_phone: str = ""
    gemini_mode: str = "mock"
    gemini_model: str = ""
    solana_mode: str = "mock"
    solana_rpc_url: str = "https://api.devnet.solana.com"
    solana_keypair_path: str = ""
    fetchai_mode: str = "local"
    dc_max_it_kw: float = 6.0
    curtailment_surplus_mw: float = 50.0
    ev_force_deadline: str = DISK_HORIZON_START
    horizon_mode: str = "today"
    horizon_tz: str = "America/Los_Angeles"

    @classmethod
    def from_env(cls) -> "Config":
        data_dir_raw = os.environ.get("DATA_DIR", "").strip()
        data_dir = Path(data_dir_raw) if data_dir_raw else REPO_ROOT / "data"
        return cls(
            mode=os.environ.get("MODE", "cached"),
            hardware_mode=os.environ.get("HARDWARE_MODE", "simulated"),
            start_simulator=os.environ.get("START_SIMULATOR", "0") == "1",
            database_url=os.environ.get("DATABASE_URL", "").strip(),
            data_dir=data_dir,
            optimizer_mode=os.environ.get("OPTIMIZER_MODE", "real"),
            cors_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173"),
            photon_mode=os.environ.get("PHOTON_MODE", "mock"),
            photon_timeout_seconds=float(
                os.environ.get("PHOTON_TIMEOUT_SECONDS", "300")
            ),
            operator_phone=os.environ.get("OPERATOR_PHONE", ""),
            gemini_mode=os.environ.get("GEMINI_MODE", "mock"),
            gemini_model=os.environ.get("GEMINI_MODEL", ""),
            solana_mode=os.environ.get("SOLANA_MODE", "mock"),
            solana_rpc_url=os.environ.get(
                "SOLANA_RPC_URL", "https://api.devnet.solana.com"
            ),
            solana_keypair_path=os.environ.get("SOLANA_KEYPAIR_PATH", ""),
            fetchai_mode=os.environ.get("FETCHAI_MODE", "local"),
            dc_max_it_kw=float(os.environ.get("DC_MAX_IT_KW", "6.0")),
            curtailment_surplus_mw=float(
                os.environ.get("CURTAILMENT_SURPLUS_MW", "50")
            ),
            ev_force_deadline=os.environ.get(
                "EV_FORCE_DEADLINE", "2026-06-21T21:00:00Z"
            ),
            horizon_mode=os.environ.get("HORIZON_MODE", "today"),
            horizon_tz=os.environ.get("HORIZON_TZ", "America/Los_Angeles"),
        )

    @property
    def database_kind(self) -> str:
        if self.database_url.startswith(("postgres://", "postgresql://")):
            return "postgres"
        return "sqlite"
