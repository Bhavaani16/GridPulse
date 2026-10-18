"""Gemini schedule explanation (SPEC section 11). Owner: Gemini agent (D4).

Contract (replace the body, keep the signature):

    explain(schedule: Schedule, signals: list[GridSignal],
            prev_schedule: Schedule | None) -> str

explain_with_source also returns the ExplainResponse.source value
(gemini | fallback | cache) so main.py can fill the endpoint. The model
receives only the section-11 summary object plus the section-11
instruction string — never raw logs, phone numbers, or secrets.

GEMINI_MODE=mock (default) returns the template without a network call.
GEMINI_MODE=live needs GEMINI_MODEL, GEMINI_API_KEY, and the SDK usage
from /docs/gemini.txt. That file is missing, so no documented request
shape exists and the live path falls back to the template after logging
an error. Do not guess a model name or an SDK call.
"""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Any, Optional

from decision_log import write_log
from optimizer.models import GridSignal, Schedule, Slot
from state import get_state

GEMINI_TIMEOUT_SECONDS = 6.0  # SPEC section 11
MAX_ATTEMPTS = 2  # the initial call plus one retry
DOCS_PATH = Path(__file__).resolve().parents[2] / "docs" / "gemini.txt"

INSTRUCTION = (
    "Write 2 or 3 plain sentences. Mention the carbon versus water "
    "trade-off at this alpha. Use only numbers that appear in the "
    "summary. Do not use markdown."
)

TEMPLATE = (
    "Simulated result at alpha {alpha:.2f}: this schedule costs "
    "${cost_usd:.2f}, emits {carbon_kg:.2f} kg CO2, and uses "
    "{water_l:.1f} L of water, which is {cost_pct:+.1f}% cost, "
    "{carbon_pct:+.1f}% carbon, and {water_pct:+.1f}% water versus the "
    "naive baseline. Jobs moved: {shifted_job_count}. Cooling follows the "
    "wet/dry split in the schedule."
)

_NUMBER_RE = re.compile(r"-?\d+(\.\d+)?")
_SHIFT_EPS = 1e-6  # SPEC section 5.4 shifted-job tolerance
_GUARD_TOLERANCE = 0.05  # SPEC section 11 number guard

_cache: dict[str, str] = {}


class GeminiNotConfigured(RuntimeError):
    """No documented Gemini request exists to make."""


def clear_cache() -> None:
    _cache.clear()


def cache_key(schedule: Schedule) -> str:
    return f"{schedule.schedule_id}:{schedule.alpha:.2f}"


def _template_text(schedule: Schedule) -> str:
    metrics = schedule.metrics
    savings = schedule.savings_pct
    return TEMPLATE.format(
        alpha=schedule.alpha,
        cost_usd=metrics.cost_usd,
        carbon_kg=metrics.carbon_kg,
        water_l=metrics.water_l,
        cost_pct=savings.cost,
        carbon_pct=savings.carbon,
        water_pct=savings.water,
        shifted_job_count=schedule.shifted_job_count,
    )


def _log_error(schedule_id: Optional[str], message: str) -> None:
    write_log(
        schedule_id,
        "gemini",
        "error",
        {"integration": "gemini", "message": message},
    )


def _fractions(slots: list[Slot]) -> dict[str, dict[int, float]]:
    """job_id -> {t: fraction} for one schedule's slots."""
    out: dict[str, dict[int, float]] = {}
    for slot in slots:
        for job in slot.jobs:
            out.setdefault(job.job_id, {})[slot.t] = job.fraction
    return out


def _shifted_jobs(
    schedule: Schedule, prev_schedule: Optional[Schedule]
) -> list[dict[str, Any]]:
    """Jobs whose per-slot fraction moved versus the previous schedule.

    from_hours are the ascending slot indexes with fraction > 0 in
    prev_schedule; to_hours the same for this schedule. prev_schedule is
    the baseline in the demo flow, matching section 5.4's definition of
    shifted. When there is nothing to compare against, no job is shifted.
    """
    if prev_schedule is None:
        return []
    now = _fractions(schedule.slots)
    before = _fractions(prev_schedule.slots)
    shifted = []
    for job_id in sorted(set(now) | set(before)):
        new_map = now.get(job_id, {})
        old_map = before.get(job_id, {})
        moved = any(
            abs(new_map.get(t, 0.0) - old_map.get(t, 0.0)) > _SHIFT_EPS
            for t in set(new_map) | set(old_map)
        )
        if moved:
            shifted.append(
                {
                    "job_id": job_id,
                    "from_hours": sorted(
                        t for t, f in old_map.items() if f > 0
                    ),
                    "to_hours": sorted(
                        t for t, f in new_map.items() if f > 0
                    ),
                }
            )
    return shifted


def _argmax(
    signals: list[GridSignal], attr: str, exclude: int = -1
) -> Optional[tuple[int, float]]:
    """(t, value) of the largest attr; lowest t wins ties."""
    best: Optional[tuple[int, float]] = None
    for t, signal in enumerate(signals):
        if t == exclude:
            continue
        value = getattr(signal, attr)
        if best is None or value > best[1]:
            best = (t, value)
    return best


def _drivers(signals: list[GridSignal]) -> list[dict[str, Any]]:
    """Section-11 driver pair: largest curtailment, then largest carbon
    outside driver 1's slot, then largest price as the degenerate case."""
    drivers: list[dict[str, Any]] = []
    first = _argmax(signals, "curtailment_mw")
    if first is None:
        return drivers
    drivers.append(
        {"name": "curtailment_mw", "hour": first[0], "value": first[1]}
    )
    second = _argmax(signals, "marginal_gco2_per_kwh", exclude=first[0])
    if second is not None:
        drivers.append(
            {
                "name": "marginal_gco2_per_kwh",
                "hour": second[0],
                "value": second[1],
            }
        )
        return drivers
    price = _argmax(signals, "price_usd_per_mwh", exclude=first[0])
    if price is not None:
        drivers.append(
            {
                "name": "price_usd_per_mwh",
                "hour": price[0],
                "value": price[1],
            }
        )
    return drivers


def build_summary(
    schedule: Schedule,
    signals: list[GridSignal],
    prev_schedule: Optional[Schedule],
) -> dict[str, Any]:
    """The exact section-11 summary object; this is all the model sees."""
    reference = prev_schedule
    if reference is None:
        try:
            reference = get_state().db.get_schedule("sch-baseline")
        except Exception:
            reference = None
    return {
        "alpha": schedule.alpha,
        "shifted_jobs": _shifted_jobs(schedule, reference),
        "drivers": _drivers(signals),
        "cooling_dry_hours": [
            slot.t for slot in schedule.slots if slot.cooling_mode == "dry"
        ],
        "savings_pct": {
            "cost": schedule.savings_pct.cost,
            "carbon": schedule.savings_pct.carbon,
            "water": schedule.savings_pct.water,
        },
        "metrics": {
            "cost_usd": schedule.metrics.cost_usd,
            "carbon_kg": schedule.metrics.carbon_kg,
            "water_l": schedule.metrics.water_l,
            "energy_kwh": schedule.metrics.energy_kwh,
        },
    }


def _summary_numbers(node: Any) -> list[float]:
    """Every numeric leaf in the summary JSON, flattened."""
    if isinstance(node, bool):
        return []
    if isinstance(node, (int, float)):
        return [float(node)]
    if isinstance(node, dict):
        out: list[float] = []
        for value in node.values():
            out.extend(_summary_numbers(value))
        return out
    if isinstance(node, (list, tuple)):
        out = []
        for item in node:
            out.extend(_summary_numbers(item))
        return out
    return []


def _numbers_ok(text: str, summary: dict[str, Any]) -> bool:
    """Section-11 guard: every number in the model text must be within
    0.05 absolute of a number present in the summary JSON."""
    allowed = _summary_numbers(summary)
    for match in _NUMBER_RE.finditer(text):
        value = float(match.group())
        if not any(abs(value - known) <= _GUARD_TOLERANCE for known in allowed):
            return False
    return True


def _generate_model_text(summary: dict[str, Any]) -> str:
    """One Gemini generate request carrying a GEMINI_TIMEOUT_SECONDS bound.

    The request must be built exactly as /docs/gemini.txt documents, with
    the model id from GEMINI_MODEL, the key from GEMINI_API_KEY, and a
    body of INSTRUCTION plus the JSON summary — nothing else. Until that
    file exists there is no documented call, so this raises
    GeminiNotConfigured and explain falls back to the template (SPEC
    section 11 TODO).
    """
    raise GeminiNotConfigured("no documented request in /docs/gemini.txt")


def _generate_with_timeout(summary: dict[str, Any]) -> str:
    """Enforce the 6-second bound around whatever documented call lands
    in _generate_model_text."""
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(_generate_model_text, summary)
    try:
        return future.result(timeout=GEMINI_TIMEOUT_SECONDS)
    except FutureTimeoutError as exc:
        raise TimeoutError("gemini request timed out") from exc
    finally:
        pool.shutdown(wait=False)


def _live_block_reason() -> Optional[str]:
    """Why live mode cannot make a call, or None when it can."""
    config = get_state().config
    if not config.gemini_model:
        return "GEMINI_MODEL is empty"
    if not os.environ.get("GEMINI_API_KEY", "").strip():
        return "GEMINI_API_KEY is empty"
    if not DOCS_PATH.is_file():
        return "/docs/gemini.txt is missing"
    return None


def _live_explain(
    schedule: Schedule,
    signals: list[GridSignal],
    prev_schedule: Optional[Schedule],
) -> tuple[str, str]:
    summary = build_summary(schedule, signals, prev_schedule)
    text: Optional[str] = None
    last_error: Optional[BaseException] = None
    for _attempt in range(MAX_ATTEMPTS):
        try:
            text = _generate_with_timeout(summary)
            break
        except Exception as exc:
            last_error = exc
    if text is None:
        _log_error(
            schedule.schedule_id,
            f"generate failed: {type(last_error).__name__}",
        )
        return _template_text(schedule), "fallback"
    if not text.strip():
        _log_error(schedule.schedule_id, "empty model body")
        return _template_text(schedule), "fallback"
    if not _numbers_ok(text, summary):
        _log_error(schedule.schedule_id, "model text failed the number guard")
        return _template_text(schedule), "fallback"
    return text, "gemini"


def explain(
    schedule: Schedule,
    signals: list[GridSignal],
    prev_schedule: Optional[Schedule],
) -> str:
    """SPEC signature. Returns the explanation text."""
    text, _source = explain_with_source(schedule, signals, prev_schedule)
    return text


def explain_with_source(
    schedule: Schedule,
    signals: list[GridSignal],
    prev_schedule: Optional[Schedule],
) -> tuple[str, str]:
    """Explain plus its source (gemini | fallback | cache).

    Cache hit returns the stored text without a network call. Mock mode
    and every failure path return the section-11 template with source
    fallback.
    """
    key = cache_key(schedule)
    if key in _cache:
        return _cache[key], "cache"
    state = get_state()
    text = _template_text(schedule)
    source = "fallback"
    if state.config.gemini_mode == "live":
        reason = _live_block_reason()
        if reason is not None:
            _log_error(
                schedule.schedule_id, f"GEMINI_MODE=live but {reason}"
            )
        else:
            text, source = _live_explain(schedule, signals, prev_schedule)
    _cache[key] = text
    return text, source
