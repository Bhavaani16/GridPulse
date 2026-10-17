"""SPEC section 16 data tests: DATA-1 through DATA-4."""

import json
import socket
from datetime import datetime, timedelta
from pathlib import Path

from data_tools.fetch_signals import CACHE_PATH, load_cached_signals, write_cached_csv
from data_tools.models import Asset, Job
from data_tools.synthetic import LOCAL_HOUR_VALUES, SEED, synthetic_rows

REPO = Path(__file__).resolve().parents[3]
JOBS_PATH = REPO / "data" / "jobs.json"
ASSETS_PATH = REPO / "data" / "assets.json"


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_data_1_shape_spacing_and_no_empty_fields():
    text = CACHE_PATH.read_text()
    assert "NaN" not in text
    rows = load_cached_signals()
    assert len(rows) == 48
    previous = None
    for row in rows:
        assert row.ts
        assert row.price_usd_per_mwh == row.price_usd_per_mwh
        assert row.marginal_gco2_per_kwh == row.marginal_gco2_per_kwh
        assert row.curtailment_mw == row.curtailment_mw
        assert row.water_stress_index == row.water_stress_index
        current = _parse_ts(row.ts)
        if previous is not None:
            assert current - previous == timedelta(hours=1)
        previous = current
    assert rows[0].ts == "2026-06-21T07:00:00Z"


def test_data_2_known_rows_and_water_sum():
    rows = load_cached_signals()
    assert rows[0].price_usd_per_mwh == 45.0
    assert rows[0].marginal_gco2_per_kwh == 250.0
    assert rows[0].curtailment_mw == 5.0
    assert rows[0].water_stress_index == 0.7455
    assert rows[10].price_usd_per_mwh == 20.0
    assert rows[10].marginal_gco2_per_kwh == 80.0
    assert rows[10].curtailment_mw == 250.0
    assert rows[10].water_stress_index == 0.6852
    assert rows[18].price_usd_per_mwh == 90.0
    assert rows[18].marginal_gco2_per_kwh == 420.0
    assert rows[24].ts == "2026-06-22T07:00:00Z"
    assert rows[24].price_usd_per_mwh == rows[0].price_usd_per_mwh
    water = sum(row.water_stress_index for row in rows[:24])
    assert water == 17.28
    for row in rows:
        assert row.source == "synthetic"


def test_data_3_jobs_and_assets_match_spec():
    jobs = [Job.model_validate(item) for item in json.loads(JOBS_PATH.read_text())]
    assets = [Asset.model_validate(item) for item in json.loads(ASSETS_PATH.read_text())]
    assert len(jobs) == 8
    assert sum(1 for job in jobs if job.kind == "compute" and job.checkpointable) == 4
    assert sum(1 for job in jobs if job.kind == "compute" and not job.checkpointable) == 2
    assert sum(1 for job in jobs if job.kind == "ev_charge") == 2
    assert [job.job_id for job in jobs] == [
        "job-cp-01",
        "job-cp-02",
        "job-cp-03",
        "job-cp-04",
        "job-ncp-01",
        "job-ncp-02",
        "job-ev-01",
        "job-ev-02",
    ]
    assert {asset.kind for asset in assets} == {"data_center", "ev_hub"}
    dc = next(asset for asset in assets if asset.asset_id == "asset-dc-01")
    ev = next(asset for asset in assets if asset.asset_id == "asset-ev-01")
    assert dc.it_capacity_kw == 20.0
    assert dc.wet_water_l_per_kwh == 1.8
    assert ev.charge_capacity_kw == 50.0
    assert ev.it_capacity_kw is None


def test_data_4_load_does_not_open_a_socket(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("network")

    monkeypatch.setattr(socket, "create_connection", fail)
    rows = load_cached_signals()
    assert len(rows) == 48
    assert SEED == 42


def test_rewrite_matches_synthetic_table(tmp_path: Path):
    target = tmp_path / "signals_cached.csv"
    write_cached_csv(target)
    written = target.read_text().splitlines()
    assert written[0] == (
        "ts,price_usd_per_mwh,marginal_gco2_per_kwh,"
        "curtailment_mw,water_stress_index,source"
    )
    assert len(written) == 49
    generated = synthetic_rows()
    assert written[1].startswith(str(generated[0]["ts"]))
    assert float(written[1].split(",")[1]) == LOCAL_HOUR_VALUES[0][0]
    assert written[1].endswith(",synthetic")
