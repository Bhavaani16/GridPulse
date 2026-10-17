"""Pydantic models for SPEC sections 5.1, 5.2, and 5.3.

backend/optimizer/models.py does not exist yet. These fields match SPEC.md.
When the optimizer package lands, import those models instead of copying fields.
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

SourceName = Literal[
    "synthetic",
    "caiso",
    "eia",
    "watttime",
    "electricity_maps",
    "wri",
]


class GridSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ts: str
    price_usd_per_mwh: float
    marginal_gco2_per_kwh: float
    curtailment_mw: float
    water_stress_index: float
    source: SourceName


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(pattern=r"^[a-z0-9-]{1,64}$")
    name: str
    kind: Literal["compute", "ev_charge"]
    checkpointable: bool
    asset_id: str
    power_kw: float
    duration_h: float
    energy_kwh: float
    release_ts: str
    deadline_ts: str

    @model_validator(mode="after")
    def energy_matches_power_times_duration(self) -> "Job":
        if abs(self.energy_kwh - self.power_kw * self.duration_h) > 1e-6:
            raise ValueError("energy_kwh must equal power_kw * duration_h")
        if self.power_kw <= 0 or self.duration_h <= 0:
            raise ValueError("power_kw and duration_h must be > 0")
        if not self.checkpointable and self.duration_h != int(self.duration_h):
            raise ValueError("non-checkpointable duration_h must be an integer")
        return self


class Asset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    kind: Literal["data_center", "ev_hub"]
    name: str
    it_capacity_kw: Optional[float]
    charge_capacity_kw: Optional[float]
    wet_extra_kw_per_kw: Optional[float]
    dry_extra_kw_per_kw: Optional[float]
    wet_water_l_per_kwh: Optional[float]
