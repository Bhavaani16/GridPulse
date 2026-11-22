"""Load the cached horizon from /data. No network."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from optimizer.models import Asset, GridSignal, Job
from optimizer.problem import HORIZON


def default_data_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data"


def load_horizon(
    data_dir: Path | None = None,
) -> tuple[list[GridSignal], list[Job], list[Asset]]:
    root = default_data_dir() if data_dir is None else data_dir
    signals: list[GridSignal] = []
    with (root / "signals_cached.csv").open(newline="") as handle:
        for row in csv.DictReader(handle):
            signals.append(
                GridSignal(
                    ts=row["ts"],
                    price_usd_per_mwh=float(row["price_usd_per_mwh"]),
                    marginal_gco2_per_kwh=float(row["marginal_gco2_per_kwh"]),
                    curtailment_mw=float(row["curtailment_mw"]),
                    water_stress_index=float(row["water_stress_index"]),
                    source=row["source"],  # type: ignore[arg-type]
                )
            )
            if len(signals) == HORIZON:
                break
    if len(signals) != HORIZON:
        raise ValueError(f"signals_cached.csv needs {HORIZON} hourly rows")
    jobs = [Job.model_validate(item) for item in json.loads((root / "jobs.json").read_text())]
    assets = [Asset.model_validate(item) for item in json.loads((root / "assets.json").read_text())]
    return signals, jobs, assets
