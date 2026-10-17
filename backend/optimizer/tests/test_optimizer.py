"""SPEC section 16 optimizer tests OPT-1 through OPT-9."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from optimizer.baseline import baseline
from optimizer.inputs import load_horizon
from optimizer.metrics import metrics_hash, r6, savings_pct
from optimizer.models import Constraints, Job, Metrics, OptimizeError, Schedule
from optimizer.solver import optimize

BACKEND = Path(__file__).resolve().parents[2]
PYTHON = sys.executable


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("optimizer.clock.now_utc", lambda: "2026-06-21T19:00:00Z")


@pytest.fixture(scope="module")
def sample():
    return load_horizon()


def _fractions(schedule: Schedule, job_id: str) -> dict[int, float]:
    found = {t: 0.0 for t in range(24)}
    for slot in schedule.slots:
        for item in slot.jobs:
            if item.job_id == job_id:
                found[slot.t] = item.fraction
    return found


def _window(job: Job, signals) -> set[int]:
    from datetime import datetime, timedelta

    def parse(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    release = parse(job.release_ts)
    deadline = parse(job.deadline_ts)
    hours = set()
    for t, signal in enumerate(signals):
        slot = parse(signal.ts)
        if release <= slot and slot + timedelta(hours=1) <= deadline:
            hours.add(t)
    return hours


def test_opt_1_completion_and_window(sample):
    signals, jobs, assets = sample
    reference = baseline(signals, jobs, assets)
    optimized = optimize(signals, jobs, assets, 0.5)
    assert isinstance(reference, Schedule)
    assert isinstance(optimized, Schedule)
    for schedule in (reference, optimized):
        for job in jobs:
            fractions = _fractions(schedule, job.job_id)
            assert sum(fractions.values()) == pytest.approx(job.duration_h, abs=1e-6)
            allowed = _window(job, signals)
            for t, fraction in fractions.items():
                if t not in allowed:
                    assert fraction == 0.0


def test_opt_2_capacity(sample):
    signals, jobs, assets = sample
    for alpha in (0.0, 0.5, 1.0):
        schedule = optimize(signals, jobs, assets, alpha)
        assert isinstance(schedule, Schedule)
        for slot in schedule.slots:
            assert slot.it_load_kw <= 20
            assert slot.ev_load_kw <= 50
    reference = baseline(signals, jobs, assets)
    assert isinstance(reference, Schedule)
    for slot in reference.slots:
        assert slot.it_load_kw <= 20
        assert slot.ev_load_kw <= 50


def test_opt_3_alpha_zero_carbon(sample):
    signals, jobs, assets = sample
    reference = baseline(signals, jobs, assets)
    optimized = optimize(signals, jobs, assets, 0)
    assert isinstance(reference, Schedule)
    assert isinstance(optimized, Schedule)
    assert optimized.metrics.carbon_kg <= reference.metrics.carbon_kg


def test_opt_4_alpha_one_water(sample):
    signals, jobs, assets = sample
    reference = baseline(signals, jobs, assets)
    optimized = optimize(signals, jobs, assets, 1)
    assert isinstance(reference, Schedule)
    assert isinstance(optimized, Schedule)
    assert optimized.metrics.water_l <= reference.metrics.water_l


def test_opt_5_non_checkpointable_contiguous(sample):
    signals, jobs, assets = sample
    for alpha in (0.0, 0.5, 1.0):
        schedule = optimize(signals, jobs, assets, alpha)
        assert isinstance(schedule, Schedule)
        for job in jobs:
            if job.checkpointable:
                continue
            positive = [t for t, fraction in _fractions(schedule, job.job_id).items() if fraction > 0]
            assert positive
            assert max(positive) - min(positive) + 1 == len(positive) == int(job.duration_h)
            assert all(_fractions(schedule, job.job_id)[t] == 1.0 for t in positive)


def test_opt_6_alpha_monotonic(sample):
    signals, jobs, assets = sample
    carbons = []
    waters = []
    for alpha in (0.0, 0.25, 0.5, 0.75, 1.0):
        schedule = optimize(signals, jobs, assets, alpha)
        assert isinstance(schedule, Schedule)
        carbons.append(schedule.metrics.carbon_kg)
        waters.append(schedule.metrics.water_l)
    for earlier, later in zip(carbons, carbons[1:]):
        assert later + 0.05 >= earlier
    for earlier, later in zip(waters, waters[1:]):
        assert later <= earlier + 0.05


def test_opt_7_infeasible_names_the_job(sample, monkeypatch: pytest.MonkeyPatch):
    signals, jobs, assets = sample
    monkeypatch.setattr(
        "optimizer.solver.milp",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("solver should not run")),
    )
    target = next(job for job in jobs if job.job_id == "job-cp-01")
    broken = target.model_copy(update={"duration_h": 30, "energy_kwh": target.power_kw * 30})
    replaced = [broken if job.job_id == target.job_id else job for job in jobs]
    optimized = optimize(signals, replaced, assets, 0.5)
    reference = baseline(signals, replaced, assets)
    for result in (optimized, reference):
        assert isinstance(result, OptimizeError)
        assert result.code == "infeasible"
        assert result.job_id == "job-cp-01"
        assert result.message == "job job-cp-01 cannot complete inside its window"


def test_opt_8_runtime(sample):
    signals, jobs, assets = sample
    started = time.perf_counter()
    schedule = optimize(signals, jobs, assets, 0.5)
    elapsed = time.perf_counter() - started
    assert isinstance(schedule, Schedule)
    assert elapsed < 2.0

    extras = []
    for index in (1, 2):
        extras.append(
            Job(
                job_id=f"job-extra-0{index}",
                name=f"Extra {index}",
                kind="compute",
                checkpointable=True,
                asset_id="asset-dc-01",
                power_kw=1.0,
                duration_h=1,
                energy_kwh=1.0,
                release_ts=signals[0].ts,
                deadline_ts="2026-06-22T07:00:00Z",
            )
        )
    started = time.perf_counter()
    wider = optimize(signals, list(jobs) + extras, assets, 0.5)
    wider_elapsed = time.perf_counter() - started
    assert isinstance(wider, Schedule)
    assert wider_elapsed < 2.0


def test_opt_9_savings_pct_zeros_and_zero_baseline():
    metrics = Metrics(cost_usd=14.0, carbon_kg=21.0, water_l=100.0, energy_kwh=115.0)
    zeros = savings_pct(metrics, metrics)
    assert zeros.cost == 0.0
    assert zeros.carbon == 0.0
    assert zeros.water == 0.0

    nothing = Metrics(cost_usd=0.0, carbon_kg=0.0, water_l=0.0, energy_kwh=0.0)
    other = Metrics(cost_usd=1.0, carbon_kg=2.0, water_l=3.0, energy_kwh=4.0)
    saved = savings_pct(other, nothing)
    assert saved.cost == 0.0
    assert saved.carbon == 0.0
    assert saved.water == 0.0

    partial = Metrics(cost_usd=10.0, carbon_kg=0.0, water_l=0.0, energy_kwh=5.0)
    moved = Metrics(cost_usd=5.0, carbon_kg=1.0, water_l=1.0, energy_kwh=5.0)
    mixed = savings_pct(moved, partial)
    assert mixed.cost == 50.0
    assert mixed.carbon == 0.0
    assert mixed.water == 0.0


def test_savings_match_spec_example():
    base = Metrics(cost_usd=14.0, carbon_kg=21.0, water_l=100.0, energy_kwh=115.0)
    opt = Metrics(cost_usd=12.4, carbon_kg=18.2, water_l=90.0, energy_kwh=110.0)
    saved = savings_pct(opt, base)
    assert saved.cost == r6((14.0 - 12.4) / 14.0 * 100.0)
    assert saved.carbon == r6((21.0 - 18.2) / 21.0 * 100.0)
    assert saved.water == 10.0
    assert saved.cost == 11.428571
    assert saved.carbon == 13.333333


def test_metrics_hash_is_sha256_of_sorted_json():
    metrics = Metrics(cost_usd=2.5, carbon_kg=1.5, water_l=4.5, energy_kwh=3.5)
    body = {"carbon_kg": 1.5, "cost_usd": 2.5, "energy_kwh": 3.5, "water_l": 4.5}
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"))
    expect = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert metrics_hash(metrics) == expect


def test_baseline_sample_profile_and_wet_cooling(sample):
    signals, jobs, assets = sample
    schedule = baseline(signals, jobs, assets)
    assert isinstance(schedule, Schedule)
    expected_it = [12, 12, 12, 8, 3, 0, 6, 6, 4, 9, 9] + [0] * 13
    expected_ev = [7, 7, 7, 7] + [0] * 8 + [11, 11] + [0] * 10
    assert len(expected_it) == 24
    assert len(expected_ev) == 24
    for slot, it, ev in zip(schedule.slots, expected_it, expected_ev):
        assert slot.it_load_kw == it
        assert slot.ev_load_kw == ev
        assert slot.yw_kw == it
        assert slot.yd_kw == 0.0
        assert slot.cooling_mode == "wet"
        assert slot.total_load_kw == pytest.approx(it * 1.15 + ev, abs=1e-6)
    assert schedule.slots[0].total_load_kw == 20.8
    assert schedule.schedule_id == "sch-baseline"
    assert schedule.schedule_kind == "baseline"
    assert schedule.status == "applied"
    assert schedule.alpha == 0.0
    assert schedule.metrics == schedule.baseline_metrics
    assert schedule.savings_pct.cost == 0.0
    assert schedule.shifted_job_count == 0
    assert schedule.shifted_kwh == 0.0
    assert schedule.savings_label == "simulated"
    assert {item.job_id for item in schedule.slots[0].jobs} == {
        "job-cp-01",
        "job-cp-04",
        "job-ncp-01",
        "job-ev-01",
    }

    water = 0.0
    cost = 0.0
    carbon = 0.0
    energy = 0.0
    for signal, slot in zip(signals, schedule.slots):
        cost += slot.total_load_kw * signal.price_usd_per_mwh / 1000.0
        carbon += slot.total_load_kw * signal.marginal_gco2_per_kwh / 1000.0
        water += 1.8 * slot.yw_kw * signal.water_stress_index
        energy += slot.total_load_kw
    assert schedule.metrics.cost_usd == r6(cost)
    assert schedule.metrics.carbon_kg == r6(carbon)
    assert schedule.metrics.water_l == r6(water)
    assert schedule.metrics.energy_kwh == r6(energy)


def test_optimized_contract_and_shared_savings(sample):
    signals, jobs, assets = sample
    reference = baseline(signals, jobs, assets)
    optimized = optimize(signals, jobs, assets, 0.5)
    again = optimize(signals, jobs, assets, 0.5)
    assert isinstance(reference, Schedule)
    assert isinstance(optimized, Schedule)
    assert isinstance(again, Schedule)
    assert optimized.model_dump() == again.model_dump()
    assert optimized.schedule_id == "sch-20260621T190000Z-a050"
    assert optimize(signals, jobs, assets, 0).schedule_id == "sch-20260621T190000Z-a000"  # type: ignore[union-attr]
    assert optimize(signals, jobs, assets, 1).schedule_id == "sch-20260621T190000Z-a100"  # type: ignore[union-attr]
    assert optimized.schedule_kind == "optimized"
    assert optimized.status == "proposed"
    assert optimized.alpha == 0.5
    assert optimized.explanation is None
    assert optimized.savings_label == "simulated"
    assert optimized.baseline_metrics == reference.metrics
    assert optimized.savings_pct == savings_pct(optimized.metrics, reference.metrics)
    for slot in optimized.slots:
        assert abs(slot.yw_kw + slot.yd_kw - slot.it_load_kw) <= 1e-6


def test_fractional_checkpointable_tail(sample):
    signals, _, assets = sample
    job = Job(
        job_id="job-frac-01",
        name="Partial",
        kind="compute",
        checkpointable=True,
        asset_id="asset-dc-01",
        power_kw=2.0,
        duration_h=2.5,
        energy_kwh=5.0,
        release_ts=signals[0].ts,
        deadline_ts="2026-06-22T07:00:00Z",
    )
    reference = baseline(signals, [job], assets)
    assert isinstance(reference, Schedule)
    fractions = _fractions(reference, job.job_id)
    assert fractions[0] == 1.0
    assert fractions[1] == 1.0
    assert fractions[2] == 0.5
    assert sum(fractions.values()) == pytest.approx(2.5)
    optimized = optimize(signals, [job], assets, 0.0)
    assert isinstance(optimized, Schedule)
    assert sum(_fractions(optimized, job.job_id).values()) == pytest.approx(2.5)


def test_tight_deadline_names_that_job(sample):
    signals, jobs, assets = sample
    constraints = Constraints(job_deadlines={"job-ncp-02": "2026-06-21T17:00:00Z"})
    result = optimize(signals, jobs, assets, 0.5, constraints)
    assert isinstance(result, OptimizeError)
    assert result.code == "infeasible"
    assert result.job_id == "job-ncp-02"


def test_zero_it_cap_is_solver_error_not_a_crash(sample):
    signals, jobs, assets = sample
    result = optimize(signals, jobs, assets, 0.5, Constraints(max_it_kw=0))
    assert isinstance(result, OptimizeError)
    assert result.code == "solver_error"
    assert result.job_id is None


def test_models_reject_extra_keys():
    with pytest.raises(ValidationError):
        Job.model_validate(
            {
                "job_id": "job-cp-01",
                "name": "Nightly ETL",
                "kind": "compute",
                "checkpointable": True,
                "asset_id": "asset-dc-01",
                "power_kw": 5.0,
                "duration_h": 4,
                "energy_kwh": 20.0,
                "release_ts": "2026-06-21T07:00:00Z",
                "deadline_ts": "2026-06-22T07:00:00Z",
                "extra": 1,
            }
        )


def test_cli_prints_baseline_and_optimized():
    completed = subprocess.run(
        [PYTHON, "-m", "optimizer.cli", "--alpha", "0.5"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "it_kw_base" in completed.stdout
    assert "it_kw_opt" in completed.stdout
    assert "cooling_base" in completed.stdout
    assert "savings_pct" in completed.stdout
    last = completed.stdout.strip().splitlines()[-1]
    payload = json.loads(last)
    assert set(payload) == {"baseline", "optimized", "savings_pct"}
    assert set(payload["baseline"]) == {"cost_usd", "carbon_kg", "water_l", "energy_kwh"}
