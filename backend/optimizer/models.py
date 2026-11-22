"""Pydantic v2 contracts from SPEC section 5.

Other packages import these models. Field names match the spec exactly.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

HOUR_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:00:00Z$")

SourceName = Literal[
    "synthetic",
    "caiso",
    "eia",
    "watttime",
    "electricity_maps",
    "wri",
]
JobKind = Literal["compute", "ev_charge"]
AssetKind = Literal["data_center", "ev_hub"]
ScheduleKind = Literal["baseline", "optimized"]
ScheduleStatus = Literal[
    "proposed",
    "pending_approval",
    "approved",
    "applied",
    "rejected",
    "expired",
    "superseded",
]
CoolingMode = Literal["wet", "dry"]
OptimizeCode = Literal["infeasible", "solver_error"]


def parse_hour_ts(value: str) -> datetime:
    if not HOUR_TS.match(value):
        raise ValueError(f"timestamp must be hour-aligned UTC, got {value}")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class GridSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ts: str
    price_usd_per_mwh: float
    marginal_gco2_per_kwh: float
    curtailment_mw: float
    water_stress_index: float
    source: SourceName

    @model_validator(mode="after")
    def hour_aligned(self) -> "GridSignal":
        parse_hour_ts(self.ts)
        return self


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(pattern=r"^[a-z0-9-]{1,64}$")
    name: str
    kind: JobKind
    checkpointable: bool
    asset_id: str
    power_kw: float
    duration_h: float
    energy_kwh: float
    release_ts: str
    deadline_ts: str

    @model_validator(mode="after")
    def check_rules(self) -> "Job":
        if self.power_kw <= 0 or self.duration_h <= 0:
            raise ValueError("power_kw and duration_h must be > 0")
        if abs(self.energy_kwh - self.power_kw * self.duration_h) > 1e-6:
            raise ValueError("energy_kwh must equal power_kw * duration_h")
        if not self.checkpointable and self.duration_h != int(self.duration_h):
            raise ValueError("non-checkpointable duration_h must be an integer")
        release = parse_hour_ts(self.release_ts)
        deadline = parse_hour_ts(self.deadline_ts)
        if deadline <= release:
            raise ValueError("deadline_ts must be strictly after release_ts")
        return self


class Asset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    kind: AssetKind
    name: str
    it_capacity_kw: Optional[float]
    charge_capacity_kw: Optional[float]
    wet_extra_kw_per_kw: Optional[float]
    dry_extra_kw_per_kw: Optional[float]
    wet_water_l_per_kwh: Optional[float]

    @model_validator(mode="after")
    def check_kind_fields(self) -> "Asset":
        cooling = (
            self.wet_extra_kw_per_kw,
            self.dry_extra_kw_per_kw,
            self.wet_water_l_per_kwh,
        )
        if self.kind == "data_center":
            if self.it_capacity_kw is None:
                raise ValueError("data_center requires it_capacity_kw")
            if self.charge_capacity_kw is not None:
                raise ValueError("data_center charge_capacity_kw must be null")
            if any(value is None for value in cooling):
                raise ValueError("data_center requires wet and dry cooling coefficients")
        else:
            if self.charge_capacity_kw is None:
                raise ValueError("ev_hub requires charge_capacity_kw")
            if self.it_capacity_kw is not None:
                raise ValueError("ev_hub it_capacity_kw must be null")
            if any(value is not None for value in cooling):
                raise ValueError("ev_hub cooling coefficients must be null")
        return self


class JobFraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    fraction: float


class Slot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    t: int = Field(ge=0, le=23)
    ts: str
    cooling_mode: CoolingMode
    it_load_kw: float
    yw_kw: float
    yd_kw: float
    ev_load_kw: float
    total_load_kw: float
    jobs: list[JobFraction]


class Metrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cost_usd: float
    carbon_kg: float
    water_l: float
    energy_kwh: float


class SavingsPct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cost: float
    carbon: float
    water: float


class Schedule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schedule_id: str
    schedule_kind: ScheduleKind
    status: ScheduleStatus
    alpha: float = Field(ge=0, le=1)
    horizon_start: str
    created_at: str
    slots: list[Slot]
    metrics: Metrics
    baseline_metrics: Metrics
    savings_pct: SavingsPct
    shifted_job_count: int
    shifted_kwh: float
    savings_label: Literal["simulated"]
    explanation: Optional[str] = None

    @model_validator(mode="after")
    def slots_cover_horizon(self) -> "Schedule":
        if len(self.slots) != 24:
            raise ValueError("slots must have length 24")
        for index, slot in enumerate(self.slots):
            if slot.t != index:
                raise ValueError("slots must be ordered t = 0,1,...,23")
        return self


class Constraints(BaseModel):
    """Optional optimize input from SPEC section 5.7."""

    model_config = ConfigDict(extra="forbid")

    max_it_kw: Optional[float] = None
    job_deadlines: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_constraints(self) -> "Constraints":
        if self.max_it_kw is not None and self.max_it_kw < 0:
            raise ValueError("max_it_kw must be >= 0")
        for job_id, ts in self.job_deadlines.items():
            parse_hour_ts(ts)
            if not re.fullmatch(r"[a-z0-9-]{1,64}", job_id):
                raise ValueError(f"job_deadlines key {job_id} is not a job_id")
        return self


class OptimizeError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: OptimizeCode
    message: str
    job_id: Optional[str] = None

    @model_validator(mode="after")
    def job_id_matches_code(self) -> "OptimizeError":
        if self.code == "infeasible":
            if not self.job_id:
                raise ValueError("infeasible requires job_id")
        elif self.job_id is not None:
            raise ValueError("solver_error job_id must be null")
        return self


def infeasible_job(job_id: str) -> OptimizeError:
    return OptimizeError(
        code="infeasible",
        message=f"job {job_id} cannot complete inside its window",
        job_id=job_id,
    )


def solver_error(message: str) -> OptimizeError:
    return OptimizeError(code="solver_error", message=message, job_id=None)
