"""One HiGHS MILP for SPEC section 7. Same inputs, same fractions and metrics."""

from __future__ import annotations

import math
from typing import Mapping, Sequence, Union

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from optimizer.baseline import baseline
from optimizer.assemble import build_slots, make_optimized_schedule
from optimizer.models import (
    Asset,
    Constraints,
    GridSignal,
    Job,
    OptimizeError,
    Schedule,
    solver_error,
)
from optimizer.problem import HORIZON, Problem, build_problem, feasible_starts

MILP_OPTIONS = {"time_limit": 1.5, "mip_rel_gap": 1e-4, "disp": False}
_UNIT = 1_000_000


def optimize(
    signals: Sequence[GridSignal],
    jobs: Sequence[Job],
    assets: Sequence[Asset],
    alpha: float,
    constraints: Union[Constraints, Mapping[str, object], None] = None,
) -> Union[Schedule, OptimizeError]:
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)):
        return solver_error("alpha must be between 0 and 1")
    if not math.isfinite(float(alpha)) or not 0.0 <= float(alpha) <= 1.0:
        return solver_error("alpha must be between 0 and 1")
    alpha_value = float(alpha)
    problem = build_problem(signals, jobs, assets, constraints, apply_constraints=True)
    if isinstance(problem, OptimizeError):
        return problem
    reference = baseline(problem.signals, problem.jobs, problem.assets)
    if isinstance(reference, OptimizeError):
        return reference
    try:
        return _solve(problem, alpha_value, reference)
    except Exception as exc:
        return solver_error(f"solver failed: {exc}")


def water_budget_l(alpha: float, baseline_water_l: float) -> float:
    """Water allowed at this alpha: (1 - alpha) times the naive baseline."""
    return max(0.0, (1.0 - float(alpha)) * float(baseline_water_l))


def _solve(problem: Problem, alpha: float, reference: Schedule) -> Union[Schedule, OptimizeError]:
    x_index, s_index, starts, yw_index, yd_index, count = _variables(problem)
    objective = _objective(problem, reference, x_index, yw_index, yd_index, count)
    matrix, lower, upper = _constraints(
        problem,
        x_index,
        s_index,
        starts,
        yw_index,
        yd_index,
        count,
        water_budget_l(alpha, reference.metrics.water_l),
    )
    bounds_lower = np.zeros(count, dtype=float)
    bounds_upper = np.ones(count, dtype=float)
    integrality = np.zeros(count, dtype=int)
    for index in s_index.values():
        integrality[index] = 1
    for index in yw_index.values():
        bounds_upper[index] = problem.it_capacity_kw
    for index in yd_index.values():
        bounds_upper[index] = problem.it_capacity_kw

    result = milp(
        objective,
        integrality=integrality,
        bounds=Bounds(bounds_lower, bounds_upper),
        constraints=LinearConstraint(matrix, lower, upper),
        options=MILP_OPTIONS,
    )
    if result.x is None or not result.success or not np.all(np.isfinite(result.x)):
        detail = getattr(result, "message", "no solution")
        return solver_error(f"solver failed: {detail}")

    fractions = _read_fractions(problem, result.x, x_index, s_index, starts)
    if isinstance(fractions, OptimizeError):
        return fractions
    wet = [float(result.x[yw_index[t]]) for t in range(HORIZON)]
    dry = [float(result.x[yd_index[t]]) for t in range(HORIZON)]
    slots = build_slots(problem.signals, problem.jobs, problem.data_center, fractions, wet, dry)
    checked = _check_schedule(problem, fractions, slots)
    if checked is not None:
        return checked
    return make_optimized_schedule(
        problem.signals,
        problem.jobs,
        problem.assets,
        slots,
        alpha,
        reference,
    )


def _variables(
    problem: Problem,
) -> tuple[
    dict[tuple[str, int], int],
    dict[tuple[str, int], int],
    dict[str, list[int]],
    dict[int, int],
    dict[int, int],
    int,
]:
    x_index: dict[tuple[str, int], int] = {}
    s_index: dict[tuple[str, int], int] = {}
    starts: dict[str, list[int]] = {}
    cursor = 0
    for job in problem.jobs:
        for t in problem.windows[job.job_id]:
            x_index[(job.job_id, t)] = cursor
            cursor += 1
    for job in problem.jobs:
        if job.checkpointable:
            continue
        found = feasible_starts(problem.windows[job.job_id], int(job.duration_h))
        starts[job.job_id] = found
        for t in found:
            s_index[(job.job_id, t)] = cursor
            cursor += 1
    yw_index = {t: cursor + t for t in range(HORIZON)}
    cursor += HORIZON
    yd_index = {t: cursor + t for t in range(HORIZON)}
    cursor += HORIZON
    return x_index, s_index, starts, yw_index, yd_index, cursor


def _load_price(signal: GridSignal, cost_scale: float, carbon_scale: float) -> float:
    return (
        cost_scale * signal.price_usd_per_mwh / 1000.0
        + carbon_scale * signal.marginal_gco2_per_kwh / 1000.0
    )


def _objective(
    problem: Problem,
    reference: Schedule,
    x_index: dict[tuple[str, int], int],
    yw_index: dict[int, int],
    yd_index: dict[int, int],
    count: int,
) -> np.ndarray:
    """0.3 * cost_term + 1.0 * carbon_term. Water is the budget row, not a term."""
    metrics = reference.metrics
    cost_scale = 0.3 / metrics.cost_usd if metrics.cost_usd > 0 else 0.0
    carbon_scale = 1.0 / metrics.carbon_kg if metrics.carbon_kg > 0 else 0.0
    coefficients = np.zeros(count, dtype=float)
    for job in problem.jobs:
        for t in problem.windows[job.job_id]:
            price = _load_price(problem.signals[t], cost_scale, carbon_scale)
            coefficients[x_index[(job.job_id, t)]] += job.power_kw * price
    for t in range(HORIZON):
        price = _load_price(problem.signals[t], cost_scale, carbon_scale)
        coefficients[yw_index[t]] += problem.wet_extra_kw_per_kw * price
        coefficients[yd_index[t]] += problem.dry_extra_kw_per_kw * price
    return coefficients


class _Rows:
    def __init__(self, count: int) -> None:
        self.count = count
        self.rows: list[np.ndarray] = []
        self.lower: list[float] = []
        self.upper: list[float] = []

    def add(self, terms: list[tuple[int, float]], lower: float, upper: float) -> None:
        row = np.zeros(self.count, dtype=float)
        for index, coef in terms:
            row[index] += coef
        self.rows.append(row)
        self.lower.append(lower)
        self.upper.append(upper)


def _constraints(
    problem: Problem,
    x_index: dict[tuple[str, int], int],
    s_index: dict[tuple[str, int], int],
    starts: dict[str, list[int]],
    yw_index: dict[int, int],
    yd_index: dict[int, int],
    count: int,
    water_cap_l: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rows = _Rows(count)
    # Water budget: sum_t wet_water_l_per_kwh * yw[t] * stress[t] <= cap.
    water_terms = [
        (yw_index[t], problem.wet_water_l_per_kwh * problem.signals[t].water_stress_index)
        for t in range(HORIZON)
    ]
    rows.add(water_terms, -np.inf, water_cap_l)
    for job in problem.jobs:
        terms = [(x_index[(job.job_id, t)], 1.0) for t in problem.windows[job.job_id]]
        rows.add(terms, job.duration_h, job.duration_h)
    for job in problem.jobs:
        if job.checkpointable:
            continue
        terms = [(s_index[(job.job_id, t)], 1.0) for t in starts[job.job_id]]
        rows.add(terms, 1.0, 1.0)
        duration = int(job.duration_h)
        for tau in problem.windows[job.job_id]:
            link = [(x_index[(job.job_id, tau)], 1.0)]
            for start in starts[job.job_id]:
                if start <= tau <= start + duration - 1:
                    link.append((s_index[(job.job_id, start)], -1.0))
            rows.add(link, 0.0, 0.0)
    for t in range(HORIZON):
        cooling = [(yw_index[t], 1.0), (yd_index[t], 1.0)]
        it_terms: list[tuple[int, float]] = []
        ev_terms: list[tuple[int, float]] = []
        for job in problem.jobs:
            if t not in problem.windows[job.job_id]:
                continue
            term = (x_index[(job.job_id, t)], job.power_kw)
            if job.kind == "compute":
                cooling.append((x_index[(job.job_id, t)], -job.power_kw))
                it_terms.append(term)
            else:
                ev_terms.append(term)
        rows.add(cooling, 0.0, 0.0)
        if it_terms:
            rows.add(it_terms, -np.inf, problem.it_capacity_kw)
            if problem.max_it_kw is not None:
                rows.add(it_terms, -np.inf, problem.max_it_kw)
        if ev_terms:
            rows.add(ev_terms, -np.inf, problem.charge_capacity_kw)
    matrix = np.vstack(rows.rows)
    return matrix, np.asarray(rows.lower, dtype=float), np.asarray(rows.upper, dtype=float)


def _read_fractions(
    problem: Problem,
    solution: np.ndarray,
    x_index: dict[tuple[str, int], int],
    s_index: dict[tuple[str, int], int],
    starts: dict[str, list[int]],
) -> Union[dict[str, dict[int, float]], OptimizeError]:
    fractions: dict[str, dict[int, float]] = {}
    for job in problem.jobs:
        if job.checkpointable:
            raw = {
                t: float(solution[x_index[(job.job_id, t)]])
                for t in problem.windows[job.job_id]
            }
            cleaned = _checkpoint_fractions(raw, float(job.duration_h))
            if cleaned is None:
                return solver_error(f"solver failed: job {job.job_id} did not complete")
            fractions[job.job_id] = cleaned
            continue
        chosen = [t for t in starts[job.job_id] if solution[s_index[(job.job_id, t)]] >= 0.5]
        if len(chosen) != 1:
            return solver_error(f"solver failed: job {job.job_id} has no unique start")
        start = chosen[0]
        fractions[job.job_id] = {start + offset: 1.0 for offset in range(int(job.duration_h))}
    return fractions


def _checkpoint_fractions(raw: dict[int, float], duration: float) -> dict[int, float] | None:
    positive = {t: min(1.0, max(0.0, value)) for t, value in raw.items() if value > 1e-8}
    total = sum(positive.values())
    if total <= 1e-8:
        return None
    if abs(total - duration) > 1e-3:
        return None
    scaled = {t: value * (duration / total) for t, value in positive.items()}
    target = int(round(duration * _UNIT))
    pieces: list[list[float]] = []
    for t in sorted(scaled):
        units = min(scaled[t], 1.0) * _UNIT
        base = min(_UNIT, int(math.floor(units + 1e-8)))
        pieces.append([float(t), float(base), units - base])
    used = int(sum(piece[1] for piece in pieces))
    if used > target:
        return None
    leftover = target - used
    for piece in sorted(pieces, key=lambda item: item[2], reverse=True):
        if leftover <= 0:
            break
        room = _UNIT - int(piece[1])
        take = min(room, leftover)
        piece[1] += take
        leftover -= take
    if leftover != 0:
        return None
    cleaned = {int(piece[0]): piece[1] / _UNIT for piece in pieces if piece[1] > 0}
    if abs(sum(cleaned.values()) - duration) > 1e-6:
        return None
    return cleaned


def _check_schedule(
    problem: Problem,
    fractions: dict[str, dict[int, float]],
    slots: list,
) -> OptimizeError | None:
    for job in problem.jobs:
        hours = fractions.get(job.job_id, {})
        if abs(sum(hours.values()) - job.duration_h) > 1e-4:
            return solver_error(f"solver failed: job {job.job_id} did not complete")
        window = set(problem.windows[job.job_id])
        if any(t not in window for t in hours):
            return solver_error(f"solver failed: job {job.job_id} left its window")
        if not job.checkpointable:
            chosen = sorted(hours)
            if (
                not chosen
                or max(chosen) - min(chosen) + 1 != len(chosen)
                or any(hours[t] != 1.0 for t in chosen)
            ):
                return solver_error(f"solver failed: job {job.job_id} is not one contiguous block")
    for slot in slots:
        if slot.it_load_kw > problem.it_capacity_kw + 1e-4:
            return solver_error("solver failed: IT load exceeded capacity")
        if problem.max_it_kw is not None and slot.it_load_kw > problem.max_it_kw + 1e-4:
            return solver_error("solver failed: IT load exceeded max_it_kw")
        if slot.ev_load_kw > problem.charge_capacity_kw + 1e-4:
            return solver_error("solver failed: EV load exceeded capacity")
        if abs(slot.yw_kw + slot.yd_kw - slot.it_load_kw) > 1e-4:
            return solver_error("solver failed: cooling split does not match IT load")
    return None
