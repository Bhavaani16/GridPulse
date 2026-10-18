"""SPEC section 12 message envelope and the four typed bodies.

The JSON key is ``from``; the Python field is ``from_`` with alias
``from`` and serialization uses the alias. Extra keys are invalid in the
envelope and in every body.
"""

from __future__ import annotations

import secrets
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

EnvelopeFrom = Literal["grid-agent", "dc-agent", "ev-agent", "bridge"]
EnvelopeType = Literal["inform", "propose", "accept", "counter"]

DC_COUNTER_REASON = "dc thermal limit"
EV_COUNTER_REASON = "minimum charge deadline"


class MalformedEnvelope(ValueError):
    """Raised when an envelope fails section-12 validation."""


class InformBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surplus_start: Optional[str]
    surplus_end: Optional[str]
    curtailment_mw_min: float


class ProposeBody(BaseModel):
    """body.schedule is the Schedule object serialized as JSON."""

    model_config = ConfigDict(extra="forbid")

    schedule: dict


class AcceptBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: Literal[True]


class DcCounterBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    constraint: Literal["max_it_kw"]
    max_it_kw: float
    reason: Literal["dc thermal limit"]


class EvCounterBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    constraint: Literal["ev_deadline"]
    job_id: str
    deadline_ts: str
    reason: Literal["minimum charge deadline"]


class AgentEnvelope(BaseModel):
    """The section-12 message envelope. Serializes with the 'from' alias."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    msg_id: str = Field(default_factory=lambda: "msg-" + secrets.token_hex(6))
    from_: EnvelopeFrom = Field(alias="from")
    to: EnvelopeFrom
    type: EnvelopeType
    schedule_id: str
    body: dict

    def as_payload(self) -> dict:
        """The negotiation_msg decision-log payload."""
        return self.model_dump(by_alias=True)


_REPLY_BODY_MODELS: dict[tuple[str, str], type[BaseModel]] = {
    ("dc-agent", "accept"): AcceptBody,
    ("dc-agent", "counter"): DcCounterBody,
    ("ev-agent", "accept"): AcceptBody,
    ("ev-agent", "counter"): EvCounterBody,
}


def validate_reply(envelope: AgentEnvelope, sender: EnvelopeFrom) -> AgentEnvelope:
    """Check a reply envelope against the section-12 contract.

    Returns the envelope unchanged. Raises MalformedEnvelope when the
    sender, recipient, type, or body shape is wrong.
    """
    if envelope.from_ != sender:
        raise MalformedEnvelope(
            f"reply from {envelope.from_}, expected {sender}"
        )
    if envelope.to != "bridge":
        raise MalformedEnvelope(f"reply to {envelope.to}, expected bridge")
    model = _REPLY_BODY_MODELS.get((sender, envelope.type))
    if model is None:
        raise MalformedEnvelope(
            f"unexpected reply type {envelope.type} from {sender}"
        )
    try:
        model.model_validate(envelope.body)
    except Exception as exc:
        raise MalformedEnvelope(
            f"invalid {envelope.type} body from {sender}: {exc}"
        ) from exc
    return envelope


def validate_propose(envelope: AgentEnvelope) -> AgentEnvelope:
    """Check a bridge->agent propose envelope. Raises MalformedEnvelope."""
    if envelope.from_ != "bridge" or envelope.type != "propose":
        raise MalformedEnvelope("expected a propose envelope from bridge")
    if envelope.to not in ("dc-agent", "ev-agent"):
        raise MalformedEnvelope(f"propose to {envelope.to}")
    try:
        ProposeBody.model_validate(envelope.body)
    except Exception as exc:
        raise MalformedEnvelope(f"invalid propose body: {exc}") from exc
    return envelope
