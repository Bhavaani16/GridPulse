"""Print baseline vs optimized for the cached horizon.

From /backend: python -m optimizer.cli --alpha 0.5
"""

from __future__ import annotations

import argparse
import json
import sys

from pydantic import ValidationError

from optimizer.baseline import baseline
from optimizer.inputs import load_horizon
from optimizer.models import OptimizeError, Schedule
from optimizer.solver import optimize


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="optimizer.cli")
    parser.add_argument("--alpha", type=float, required=True)
    args = parser.parse_args(argv)
    try:
        signals, jobs, assets = load_horizon()
    except (OSError, ValueError, ValidationError) as exc:
        print(f"failed to load data: {exc}", file=sys.stderr)
        return 1
    reference = baseline(signals, jobs, assets)
    if isinstance(reference, OptimizeError):
        print(f"{reference.code}: {reference.message}", file=sys.stderr)
        return 1
    optimized = optimize(signals, jobs, assets, args.alpha)
    if isinstance(optimized, OptimizeError):
        print(f"{optimized.code}: {optimized.message}", file=sys.stderr)
        return 1
    _print_table(signals, reference, optimized)
    return 0


def _print_table(signals, reference: Schedule, optimized: Schedule) -> None:
    header = (
        f"{'t':>2} {'it_kw_base':>12} {'it_kw_opt':>12} "
        f"{'cooling_base':>13} {'cooling_opt':>12} "
        f"{'price_usd_per_mwh':>18} {'marginal_gco2_per_kwh':>22} {'curtailment_mw':>14}"
    )
    print(header)
    for signal, base_slot, opt_slot in zip(signals, reference.slots, optimized.slots):
        print(
            f"{base_slot.t:2d} {base_slot.it_load_kw:12.6f} {opt_slot.it_load_kw:12.6f} "
            f"{base_slot.cooling_mode:>13} {opt_slot.cooling_mode:>12} "
            f"{signal.price_usd_per_mwh:18.1f} {signal.marginal_gco2_per_kwh:22.1f} "
            f"{signal.curtailment_mw:14.1f}"
        )
    print(
        json.dumps(
            {
                "baseline": reference.metrics.model_dump(),
                "optimized": optimized.metrics.model_dump(),
                "savings_pct": optimized.savings_pct.model_dump(),
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
