"""Naive schedule: each job starts at release and cooling is entirely wet."""

from __future__ import annotations

from typing import Sequence, Union

from optimizer.assemble import build_slots, make_baseline_schedule
from optimizer.metrics import r6
from optimizer.models import Asset, GridSignal, Job, OptimizeError, Schedule, infeasible_job
from optimizer.problem import Problem, build_problem


def baseline(
    signals: Sequence[GridSignal],
    jobs: Sequence[Job],
    assets: Sequence[Asset],
) -> Union[Schedule, OptimizeError]:
    problem = build_problem(signals, jobs, assets, apply_constraints=False)
    if isinstance(problem, OptimizeError):
        return problem
    placed = _place_all(problem)
    if isinstance(placed, OptimizeError):
        return placed
    slots = build_slots(problem.signals, problem.jobs, problem.data_center, placed)
    return make_baseline_schedule(problem.signals, problem.assets, slots)


def _place_all(problem: Problem) -> Union[dict[str, dict[int, float]], OptimizeError]:
    placed: dict[str, dict[int, float]] = {}
    for job in problem.jobs:
        hours = _place_from_release(job, problem.windows[job.job_id])
        if hours is None:
            return infeasible_job(job.job_id)
        placed[job.job_id] = hours
    return placed


def _place_from_release(job: Job, window: list[int]) -> dict[int, float] | None:
    """Contiguous block at x=1 starting at the earliest window slot.

    A non-integer checkpointable duration puts the remainder on the last hour.
    """
    if not window:
        return None
    available = set(window)
    remaining = float(job.duration_h)
    cursor = window[0]
    ordered: list[tuple[int, float]] = []
    while remaining > 1e-8:
        if cursor not in available:
            return None
        fraction = 1.0 if remaining >= 1.0 else remaining
        ordered.append((cursor, fraction))
        remaining -= fraction
        cursor += 1
    if not ordered:
        return None
    hours: dict[int, float] = {}
    running = 0.0
    for slot, fraction in ordered[:-1]:
        stored = 1.0 if fraction >= 1.0 else r6(fraction)
        hours[slot] = stored
        running += stored
    last_slot, _ = ordered[-1]
    tail = r6(float(job.duration_h) - running)
    if tail <= 0.0 or tail > 1.0:
        return None
    hours[last_slot] = tail
    return hours
