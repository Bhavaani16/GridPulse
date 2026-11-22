"""Backend-owned Pydantic v2 models.

SPEC section 5 puts the shared data contracts (GridSignal, Job, Asset,
Schedule, Constraints, OptimizeError) in backend/optimizer/models.py. This
module holds the API-side models from SPEC sections 5.5, 5.6, and 6.
"""

from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from optimizer.models import Constraints, GridSignal  # noqa: F401  (re-export)

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")

Actor = Literal[
    "system",
    "optimizer",
    "dashboard",
    "photon",
    "gemini",
    "solana",
    "grid-agent",
    "dc-agent",
    "ev-agent",
    "bridge",
    "simulator",
]

EventName = Literal[
    "startup",
    "proposed",
    "approval_requested",
    "sms_sent",
    "sms_reply",
    "clarification_sent",
    "approved",
    "rejected",
    "applied",
    "expired",
    "superseded",
    "reset",
    "error",
    "explanation",
    "negotiation_msg",
    "settlement_tx",
    "telemetry_flagged",
]


class Telemetry(BaseModel):
    """SPEC section 5.6. Ranges are flagged at ingest, not rejected."""

    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    ts: str
    power_w: float
    temp_c: float
    fan_on: bool
    simulated: bool

    @field_validator("ts")
    @classmethod
    def _ts_is_utc(cls, value: str) -> str:
        if not TS_RE.match(value):
            raise ValueError("ts must be a UTC ISO-8601 timestamp")
        return value


class TelemetryRow(Telemetry):
    flagged: bool = False


class DecisionLogEntry(BaseModel):
    """SPEC section 5.5."""

    model_config = ConfigDict(extra="forbid")

    log_id: str = Field(pattern=r"^log-[0-9a-f]{12}$")
    ts: str
    schedule_id: Optional[str]
    actor: Actor
    event: EventName
    payload: dict


class TelemetryMinute(BaseModel):
    """SPEC section 6. Averages of non-flagged rows in one UTC minute."""

    model_config = ConfigDict(extra="forbid")

    bucket: str
    device_id: str
    power_w: float
    temp_c: float
    fan_on: bool
    simulated: bool


class Health(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    mode: str
    hardware_mode: str
    database: str
    optimizer_mode: str
    photon_mode: str
    gemini_mode: str
    solana_mode: str
    agents_mode: str


class OptimizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alpha: float = Field(ge=0.0, le=1.0)
    constraints: Optional[Constraints] = None


class ExplainResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schedule_id: str
    text: str
    source: Literal["gemini", "fallback", "cache"]


class CommandResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: dict


class WebhookResult(BaseModel):
    """SPEC section 6. schedule_id is omitted when status is ignored."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["applied", "rejected", "pending_approval", "ignored"]
    schedule_id: Optional[str] = None
    clarification: bool = False
    reason: Optional[Literal["duplicate", "not_pending"]] = None


class PhotonWebhookBody(BaseModel):
    """Mock-mode inbound SMS body (SPEC section 10)."""

    model_config = ConfigDict(extra="forbid")

    message_id: str
    from_number: str
    text: str


class SignalsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    horizon_start: str
    items: list[GridSignal]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


def error_body(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}
