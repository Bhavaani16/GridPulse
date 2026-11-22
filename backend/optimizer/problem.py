"""Validate inputs and build each job's window. No solver, no globals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Mapping, Optional, Sequence, Union

from pydantic import ValidationError

from optimizer.models import (
    Asset,
    Constraints,
    GridSignal,
    Job,
    OptimizeError,
    infeasible_job,
    parse_hour_ts,
    solver_error,
)

HORIZON = 24


@dataclass(frozen=True)
class Problem:
    signals: list[GridSignal]
    jobs: list[Job]
    assets: list[Asset]
    data_center: Asset
    ev_hub: Asset
    it_capacity_kw: float
    charge_capacity_kw: float
    wet_extra_kw_per_kw: float
    dry_extra_kw_per_kw: float
    wet_water_l_per_kwh: float
    windows: dict[str, list[int]]
    max_it_kw: Optional[float]


def feasible_starts(window: list[int], duration_h: int) -> list[int]:
    available = set(window)
    starts: list[int] = []
    for start in window:
        if all(start + offset in available for offset in range(duration_h)):
            starts.append(start)
    return starts


def _coerce_constraints(
    constraints: Union[Constraints, Mapping[str, object], None],
) -> Union[Constraints, None, OptimizeError]:
    if constraints is None:
        return None
    if isinstance(constraints, Constraints):
        return constraints
    try:
        return Constraints.model_validate(dict(constraints))
    except ValidationError:
        raise
    except (TypeError, ValueError) as exc:
        return solver_error(f"invalid constraints: {exc}")


def build_problem(
    signals: Sequence[object],
    jobs: Sequence[object],
    assets: Sequence[object],
    constraints: Union[Constraints, Mapping[str, object], None] = None,
    *,
    apply_constraints: bool = True,
) -> Union[Problem, OptimizeError]:
    if len(signals) < HORIZON:
        return solver_error(f"expected at least {HORIZON} hourly signals")
    parsed_signals = [
        item if isinstance(item, GridSignal) else GridSignal.model_validate(item)
        for item in list(signals)[:HORIZON]
    ]

    previous = None
    for signal in parsed_signals:
        current = parse_hour_ts(signal.ts)
        if previous is not None and current - previous != timedelta(hours=1):
            return solver_error("signals must be contiguous hourly timestamps")
        previous = current

    parsed_jobs = [item if isinstance(item, Job) else Job.model_validate(item) for item in jobs]
    parsed_jobs = sorted(parsed_jobs, key=lambda job: job.job_id)
    job_ids = [job.job_id for job in parsed_jobs]
    if len(job_ids) != len(set(job_ids)):
        return solver_error("duplicate job_id")

    parsed_assets = [item if isinstance(item, Asset) else Asset.model_validate(item) for item in assets]
    centers = [asset for asset in parsed_assets if asset.kind == "data_center"]
    hubs = [asset for asset in parsed_assets if asset.kind == "ev_hub"]
    if len(centers) != 1 or len(hubs) != 1:
        return solver_error("expected one data_center asset and one ev_hub asset")
    data_center = centers[0]
    ev_hub = hubs[0]
    if (
        data_center.it_capacity_kw is None
        or data_center.wet_extra_kw_per_kw is None
        or data_center.dry_extra_kw_per_kw is None
        or data_center.wet_water_l_per_kwh is None
        or ev_hub.charge_capacity_kw is None
    ):
        return solver_error("asset capacity or cooling fields are missing")

    parsed_constraints: Union[Constraints, None, OptimizeError]
    if apply_constraints:
        parsed_constraints = _coerce_constraints(constraints)
        if isinstance(parsed_constraints, OptimizeError):
            return parsed_constraints
    else:
        parsed_constraints = None

    for job in parsed_jobs:
        if job.kind == "compute" and job.asset_id != data_center.asset_id:
            return solver_error(f"job {job.job_id} must use the data_center asset")
        if job.kind == "ev_charge" and job.asset_id != ev_hub.asset_id:
            return solver_error(f"job {job.job_id} must use the ev_hub asset")

    windows: dict[str, list[int]] = {}
    for job in parsed_jobs:
        deadline = _effective_deadline(job, parsed_constraints)
        windows[job.job_id] = _window_indexes(parsed_signals, job.release_ts, deadline)

    problem = Problem(
        signals=parsed_signals,
        jobs=parsed_jobs,
        assets=parsed_assets,
        data_center=data_center,
        ev_hub=ev_hub,
        it_capacity_kw=float(data_center.it_capacity_kw),
        charge_capacity_kw=float(ev_hub.charge_capacity_kw),
        wet_extra_kw_per_kw=float(data_center.wet_extra_kw_per_kw),
        dry_extra_kw_per_kw=float(data_center.dry_extra_kw_per_kw),
        wet_water_l_per_kwh=float(data_center.wet_water_l_per_kwh),
        windows=windows,
        max_it_kw=None if parsed_constraints is None else parsed_constraints.max_it_kw,
    )
    blocked = _first_window_error(problem)
    if blocked is not None:
        return blocked
    return problem


def _effective_deadline(job: Job, constraints: Optional[Constraints]) -> str:
    if constraints is None:
        return job.deadline_ts
    override = constraints.job_deadlines.get(job.job_id)
    if override is None:
        return job.deadline_ts
    if parse_hour_ts(override) < parse_hour_ts(job.deadline_ts):
        return override
    return job.deadline_ts


def _window_indexes(signals: list[GridSignal], release_ts: str, deadline_ts: str) -> list[int]:
    release = parse_hour_ts(release_ts)
    deadline = parse_hour_ts(deadline_ts)
    indexes: list[int] = []
    for index, signal in enumerate(signals):
        slot = parse_hour_ts(signal.ts)
        if release <= slot and slot + timedelta(hours=1) <= deadline:
            indexes.append(index)
    return indexes


def _first_window_error(problem: Problem) -> Optional[OptimizeError]:
    for job in problem.jobs:
        window = problem.windows[job.job_id]
        if len(window) < job.duration_h:
            return infeasible_job(job.job_id)
        if not job.checkpointable and not feasible_starts(window, int(job.duration_h)):
            return infeasible_job(job.job_id)
    return None
