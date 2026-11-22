"""Mock optimizer for OPTIMIZER_MODE=mock.

Exposes the same signatures as the real modules:

    optimize(signals, jobs, assets, alpha, constraints=None) -> Schedule
    baseline(signals, jobs, assets) -> Schedule

Returns a feasible schedule for the sample data: every job runs as a
contiguous full-power block from its release (the naive placement, all
wet cooling). optimize reuses that placement, so shifted counts are zero
and request_approval auto-applies it. Depends only on optimizer.models
(the shared contract), not on the solver.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping, Optional, Sequence, Union

from optimizer.models import (
    Asset,
    Constraints,
    GridSignal,
    Job,
    JobFraction,
    Metrics,
    OptimizeError,
    SavingsPct,
    Schedule,
    Slot,
    infeasible_job,
    parse_hour_ts,
    solver_error,
)

HORIZON = 24


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _windows(
    signals: list[GridSignal], jobs: list[Job], constraints: Optional[Constraints]
) -> dict[str, list[int]]:
    windows: dict[str, list[int]] = {}
    overrides = {} if constraints is None else constraints.job_deadlines
    for job in jobs:
        deadline = job.deadline_ts
        override = overrides.get(job.job_id)
        if override is not None and parse_hour_ts(override) < parse_hour_ts(deadline):
            deadline = override
        release = parse_hour_ts(job.release_ts)
        end = parse_hour_ts(deadline)
        windows[job.job_id] = [
            t
            for t, signal in enumerate(signals)
            if release <= parse_hour_ts(signal.ts)
            and parse_hour_ts(signal.ts).timestamp() + 3600 <= end.timestamp()
        ]
    return windows


def _place(jobs: list[Job], windows: dict[str, list[int]]):
    fractions: dict[str, dict[int, float]] = {}
    for job in sorted(jobs, key=lambda j: j.job_id):
        window = windows[job.job_id]
        if len(window) < job.duration_h:
            return infeasible_job(job.job_id)
        if not job.checkpointable:
            duration = int(job.duration_h)
            start = window[0]
            if any(start + k not in window for k in range(duration)):
                return infeasible_job(job.job_id)
            fractions[job.job_id] = {start + k: 1.0 for k in range(duration)}
            continue
        remaining = float(job.duration_h)
        cursor = window[0]
        hours: dict[int, float] = {}
        while remaining > 1e-8:
            if cursor not in window:
                return infeasible_job(job.job_id)
            take = 1.0 if remaining >= 1.0 else remaining
            hours[cursor] = take
            remaining -= take
            cursor += 1
        fractions[job.job_id] = hours
    return fractions


def _slots(
    signals: list[GridSignal],
    jobs: list[Job],
    dc: Asset,
    fractions: dict[str, dict[int, float]],
) -> list[Slot]:
    wet_extra = float(dc.wet_extra_kw_per_kw or 0.0)
    slots: list[Slot] = []
    for t, signal in enumerate(signals):
        it = ev = 0.0
        running: list[JobFraction] = []
        for job in jobs:
            fraction = fractions.get(job.job_id, {}).get(t, 0.0)
            if fraction <= 0.0:
                continue
            if job.kind == "compute":
                it += job.power_kw * fraction
            else:
                ev += job.power_kw * fraction
            running.append(JobFraction(job_id=job.job_id, fraction=fraction))
        slots.append(
            Slot(
                t=t,
                ts=signal.ts,
                cooling_mode="wet",
                it_load_kw=round(it, 6),
                yw_kw=round(it, 6),
                yd_kw=0.0,
                ev_load_kw=round(ev, 6),
                total_load_kw=round(it + wet_extra * it + ev, 6),
                jobs=running,
            )
        )
    return slots


def _metrics(signals: list[GridSignal], slots: list[Slot], dc: Asset) -> Metrics:
    wet_water = float(dc.wet_water_l_per_kwh or 0.0)
    cost = carbon = water = energy = 0.0
    for signal, slot in zip(signals, slots):
        cost += slot.total_load_kw * signal.price_usd_per_mwh / 1000.0
        carbon += slot.total_load_kw * signal.marginal_gco2_per_kwh / 1000.0
        water += wet_water * slot.yw_kw * signal.water_stress_index
        energy += slot.total_load_kw
    return Metrics(
        cost_usd=round(cost, 6),
        carbon_kg=round(carbon, 6),
        water_l=round(water, 6),
        energy_kwh=round(energy, 6),
    )


def _prepare(
    signals: Sequence[GridSignal],
    jobs: Sequence[Job],
    assets: Sequence[Asset],
    constraints: Union[Constraints, Mapping[str, object], None],
):
    parsed_signals = list(signals)[:HORIZON]
    if len(parsed_signals) < HORIZON:
        return solver_error("expected at least 24 hourly signals")
    parsed_jobs = list(jobs)
    parsed_assets = list(assets)
    centers = [a for a in parsed_assets if a.kind == "data_center"]
    if len(centers) != 1:
        return solver_error("expected one data_center asset")
    parsed_constraints = (
        constraints
        if constraints is None or isinstance(constraints, Constraints)
        else Constraints.model_validate(dict(constraints))
    )
    windows = _windows(parsed_signals, parsed_jobs, parsed_constraints)
    fractions = _place(parsed_jobs, windows)
    if isinstance(fractions, OptimizeError):
        return fractions
    slots = _slots(parsed_signals, parsed_jobs, centers[0], fractions)
    metrics = _metrics(parsed_signals, slots, centers[0])
    return parsed_signals, slots, metrics


def baseline(
    signals: Sequence[GridSignal],
    jobs: Sequence[Job],
    assets: Sequence[Asset],
) -> Union[Schedule, OptimizeError]:
    prepared = _prepare(signals, jobs, assets, None)
    if isinstance(prepared, OptimizeError):
        return prepared
    parsed_signals, slots, metrics = prepared
    return Schedule(
        schedule_id="sch-baseline",
        schedule_kind="baseline",
        status="applied",
        alpha=0.0,
        horizon_start=parsed_signals[0].ts,
        created_at=_now(),
        slots=slots,
        metrics=metrics,
        baseline_metrics=metrics,
        savings_pct=SavingsPct(cost=0.0, carbon=0.0, water=0.0),
        shifted_job_count=0,
        shifted_kwh=0.0,
        savings_label="simulated",
        explanation=None,
    )


def optimize(
    signals: Sequence[GridSignal],
    jobs: Sequence[Job],
    assets: Sequence[Asset],
    alpha: float,
    constraints: Union[Constraints, Mapping[str, object], None] = None,
) -> Union[Schedule, OptimizeError]:
    if not 0.0 <= float(alpha) <= 1.0:
        return solver_error("alpha must be between 0 and 1")
    prepared = _prepare(signals, jobs, assets, constraints)
    if isinstance(prepared, OptimizeError):
        return prepared
    parsed_signals, slots, metrics = prepared
    created = _now()
    stamp = created.replace("-", "").replace(":", "")
    return Schedule(
        schedule_id=f"sch-{stamp}-a{round(float(alpha) * 100):03d}",
        schedule_kind="optimized",
        status="proposed",
        alpha=float(alpha),
        horizon_start=parsed_signals[0].ts,
        created_at=created,
        slots=slots,
        metrics=metrics,
        baseline_metrics=metrics,
        savings_pct=SavingsPct(cost=0.0, carbon=0.0, water=0.0),
        shifted_job_count=0,
        shifted_kwh=0.0,
        savings_label="simulated",
        explanation=None,
    )
