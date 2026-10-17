"""Closed-form California duck curve from SPEC section 5.1.

SEED is fixed so a later random perturbation stays reproducible. The committed
series does not use randomness; SPEC section 5.1 table is the source of truth.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

SEED = 42
HORIZON_START = datetime(2026, 6, 21, 7, 0, tzinfo=timezone.utc)
ROW_COUNT = 48

# price_usd_per_mwh, marginal_gco2_per_kwh, curtailment_mw, water_stress_index
LOCAL_HOUR_VALUES: tuple[tuple[float, float, float, float], ...] = (
    (45.0, 250.0, 5.0, 0.7455),
    (45.0, 250.0, 5.0, 0.7380),
    (45.0, 250.0, 5.0, 0.7293),
    (45.0, 250.0, 5.0, 0.7200),
    (45.0, 250.0, 5.0, 0.7107),
    (45.0, 250.0, 5.0, 0.7020),
    (45.0, 250.0, 5.0, 0.6945),
    (45.0, 250.0, 5.0, 0.6888),
    (45.0, 250.0, 5.0, 0.6852),
    (45.0, 250.0, 5.0, 0.6840),
    (20.0, 80.0, 250.0, 0.6852),
    (20.0, 80.0, 250.0, 0.6888),
    (20.0, 80.0, 250.0, 0.6945),
    (20.0, 80.0, 250.0, 0.7020),
    (20.0, 80.0, 250.0, 0.7107),
    (20.0, 80.0, 250.0, 0.7200),
    (45.0, 250.0, 40.0, 0.7293),
    (45.0, 250.0, 40.0, 0.7380),
    (90.0, 420.0, 5.0, 0.7455),
    (90.0, 420.0, 5.0, 0.7512),
    (90.0, 420.0, 5.0, 0.7548),
    (45.0, 250.0, 5.0, 0.7560),
    (45.0, 250.0, 5.0, 0.7548),
    (45.0, 250.0, 5.0, 0.7512),
)


def synthetic_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for i in range(ROW_COUNT):
        price, carbon, curtailment, water = LOCAL_HOUR_VALUES[i % 24]
        ts = HORIZON_START + timedelta(hours=i)
        rows.append(
            {
                "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "price_usd_per_mwh": price,
                "marginal_gco2_per_kwh": carbon,
                "curtailment_mw": curtailment,
                "water_stress_index": water,
                "source": "synthetic",
            }
        )
    return rows
