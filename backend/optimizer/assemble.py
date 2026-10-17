"""Turn per-hour fractions into a 24-slot Schedule."""

from __future__ import annotations

from optimizer import clock
from optimizer.metrics import compute_metrics, r6, savings_pct
from optimizer.models import (
    Asset,
    GridSignal,
    Job,
    JobFraction,
    SavingsPct,
    Schedule,
    Slot,
)

HORIZON = 24


def optimized_schedule_id(created_at: str, alpha: float) -> str:
    stamp = created_at.replace("-", "").replace(":", "")
    return f"sch-{stamp}-a{round(float(alpha) * 100):03d}"


def build_slots(
    signals: list[GridSignal],
    jobs: list[Job],
    data_center: Asset,
    fractions: dict[str, dict[int, float]],
    yw: list[float] | None = None,
    yd: list[float] | None = None,
) -> list[Slot]:
    if data_center.wet_extra_kw_per_kw is None or data_center.dry_extra_kw_per_kw is None:
        raise ValueError("data_center cooling coefficients are required")
    wet_extra = float(data_center.wet_extra_kw_per_kw)
    dry_extra = float(data_center.dry_extra_kw_per_kw)
    slots: list[Slot] = []
    for t, signal in enumerate(signals):
        it = 0.0
        ev = 0.0
        running: list[JobFraction] = []
        for job in jobs:
            fraction = r6(fractions.get(job.job_id, {}).get(t, 0.0))
            if fraction == 0.0:
                continue
            if job.kind == "compute":
                it += job.power_kw * fraction
            else:
                ev += job.power_kw * fraction
            running.append(JobFraction(job_id=job.job_id, fraction=fraction))
        it = r6(it)
        ev = r6(ev)
        wet_kw, dry_kw = _cooling_split(it, None if yw is None else yw[t], None if yd is None else yd[t])
        total = r6(it + wet_extra * wet_kw + dry_extra * dry_kw + ev)
        mode = "dry" if dry_kw > wet_kw else "wet"
        slots.append(
            Slot(
                t=t,
                ts=signal.ts,
                cooling_mode=mode,
                it_load_kw=it,
                yw_kw=wet_kw,
                yd_kw=dry_kw,
                ev_load_kw=ev,
                total_load_kw=total,
                jobs=running,
            )
        )
    if len(slots) != HORIZON:
        raise ValueError("build_slots requires 24 signals")
    return slots


def _cooling_split(it: float, raw_wet: float | None, raw_dry: float | None) -> tuple[float, float]:
    if it == 0.0 or raw_wet is None or raw_dry is None:
        return it, 0.0
    wet = max(float(raw_wet), 0.0)
    dry = max(float(raw_dry), 0.0)
    total = wet + dry
    share = 1.0 if total <= 1e-9 else wet / total
    wet_kw = r6(it * share)
    dry_kw = r6(it - wet_kw)
    return wet_kw, dry_kw


def fractions_from_slots(slots: list[Slot]) -> dict[str, dict[int, float]]:
    found: dict[str, dict[int, float]] = {}
    for slot in slots:
        for item in slot.jobs:
            found.setdefault(item.job_id, {})[slot.t] = item.fraction
    return found


def shift_stats(
    jobs: list[Job],
    baseline_slots: list[Slot],
    optimized_slots: list[Slot],
) -> tuple[int, float]:
    base = fractions_from_slots(baseline_slots)
    opt = fractions_from_slots(optimized_slots)
    shifted: list[Job] = []
    for job in jobs:
        before = base.get(job.job_id, {})
        after = opt.get(job.job_id, {})
        hours = set(before) | set(after)
        if any(abs(before.get(t, 0.0) - after.get(t, 0.0)) > 1e-6 for t in hours):
            shifted.append(job)
    return len(shifted), r6(sum(job.energy_kwh for job in shifted))


def make_baseline_schedule(
    signals: list[GridSignal],
    assets: list[Asset],
    slots: list[Slot],
) -> Schedule:
    metrics = compute_metrics(signals, slots, assets)
    return Schedule(
        schedule_id="sch-baseline",
        schedule_kind="baseline",
        status="applied",
        alpha=0.0,
        horizon_start=signals[0].ts,
        created_at=clock.now_utc(),
        slots=slots,
        metrics=metrics,
        baseline_metrics=metrics,
        savings_pct=SavingsPct(cost=0.0, carbon=0.0, water=0.0),
        shifted_job_count=0,
        shifted_kwh=0.0,
        savings_label="simulated",
        explanation=None,
    )


def make_optimized_schedule(
    signals: list[GridSignal],
    jobs: list[Job],
    assets: list[Asset],
    slots: list[Slot],
    alpha: float,
    baseline_schedule: Schedule,
) -> Schedule:
    metrics = compute_metrics(signals, slots, assets)
    shifted_count, shifted_kwh = shift_stats(jobs, baseline_schedule.slots, slots)
    created_at = clock.now_utc()
    return Schedule(
        schedule_id=optimized_schedule_id(created_at, alpha),
        schedule_kind="optimized",
        status="proposed",
        alpha=float(alpha),
        horizon_start=signals[0].ts,
        created_at=created_at,
        slots=slots,
        metrics=metrics,
        baseline_metrics=baseline_schedule.metrics,
        savings_pct=savings_pct(metrics, baseline_schedule.metrics),
        shifted_job_count=shifted_count,
        shifted_kwh=shifted_kwh,
        savings_label="simulated",
        explanation=None,
    )
