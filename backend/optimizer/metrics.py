"""Shared cost, carbon, water, energy, savings, and metrics hash.

baseline and optimize both call these. There is no second copy of the sums.
"""

from __future__ import annotations

import hashlib
import json

from optimizer.models import Asset, GridSignal, Metrics, SavingsPct, Slot


def r6(value: float) -> float:
    rounded = round(float(value), 6)
    if rounded == 0:
        return 0.0
    return rounded


def _wet_water_l_per_kwh(assets: list[Asset]) -> float:
    centers = [asset for asset in assets if asset.kind == "data_center"]
    if len(centers) != 1 or centers[0].wet_water_l_per_kwh is None:
        raise ValueError("compute_metrics requires one data_center asset")
    return float(centers[0].wet_water_l_per_kwh)


def compute_metrics(
    signals: list[GridSignal],
    slots: list[Slot],
    assets: list[Asset],
) -> Metrics:
    if len(signals) != len(slots):
        raise ValueError("signals and slots must have the same length")
    wet_water = _wet_water_l_per_kwh(assets)
    cost = 0.0
    carbon = 0.0
    water = 0.0
    energy = 0.0
    for signal, slot in zip(signals, slots):
        cost += slot.total_load_kw * signal.price_usd_per_mwh / 1000.0
        carbon += slot.total_load_kw * signal.marginal_gco2_per_kwh / 1000.0
        water += wet_water * slot.yw_kw * signal.water_stress_index
        energy += slot.total_load_kw
    return Metrics(
        cost_usd=r6(cost),
        carbon_kg=r6(carbon),
        water_l=r6(water),
        energy_kwh=r6(energy),
    )


def savings_pct(optimized: Metrics, baseline: Metrics) -> SavingsPct:
    def one(new: float, base: float) -> float:
        if base > 0:
            return r6((base - new) / base * 100.0)
        return 0.0

    return SavingsPct(
        cost=one(optimized.cost_usd, baseline.cost_usd),
        carbon=one(optimized.carbon_kg, baseline.carbon_kg),
        water=one(optimized.water_l, baseline.water_l),
    )


def metrics_hash(metrics: Metrics) -> str:
    body = {
        "carbon_kg": r6(metrics.carbon_kg),
        "cost_usd": r6(metrics.cost_usd),
        "energy_kwh": r6(metrics.energy_kwh),
        "water_l": r6(metrics.water_l),
    }
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
