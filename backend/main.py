"""GridPulse FastAPI app. Implements every endpoint in SPEC section 6.

Run from /backend: uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Optional

import clock
import signals as signals_mod
import simulator as simulator_mod
from config import Config, load_env
from db import open_database
from decision_log import write_log
from errors import InvalidStateError, NotFoundError
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from models import (
    ExplainResponse,
    Health,
    OptimizeRequest,
    Telemetry,
    error_body,
)
from optimizer.models import OptimizeError, Schedule
from schedules import (
    applied_schedule,
    approve_and_apply,
    get_schedule,
    previous_applied,
    reject,
    request_approval,
    store_proposed,
)
from state import AppState, init_state
from telemetry import ingest, recent_minutes

logger = logging.getLogger("gridpulse")


def _bind_integrations(state: AppState) -> list[str]:
    """Import optional integration modules; failures degrade to stubs."""
    errors: list[str] = []
    try:
        from integrations.photon import send_approval_sms

        state.send_approval_sms = send_approval_sms
    except Exception as exc:
        errors.append(f"photon: {exc}")
    try:
        from integrations.gemini import clear_cache, explain_with_source

        state.explain_with_source = explain_with_source
        state.clear_gemini_cache = clear_cache
    except Exception as exc:
        errors.append(f"gemini: {exc}")
    try:
        from integrations.solana import record_settlement

        state.record_settlement = record_settlement
    except Exception as exc:
        errors.append(f"solana: {exc}")
    try:
        from integrations.agents_bridge import negotiate

        state.negotiate = negotiate
    except Exception as exc:
        errors.append(f"agents_bridge: {exc}")
    return errors


def _bind_optimizer(state: AppState) -> Optional[str]:
    """OPTIMIZER_MODE=mock uses backend/mocks/optimizer_mock.py."""
    if state.config.optimizer_mode == "mock":
        try:
            from mocks.optimizer_mock import baseline, optimize

            state.optimize_fn = optimize
            state.baseline_fn = baseline
            return None
        except Exception as exc:
            return f"optimizer_mock: {exc}"
    try:
        from optimizer import baseline, optimize

        state.optimize_fn = optimize
        state.baseline_fn = baseline
        return None
    except Exception as exc:
        return f"optimizer: {exc}"


def _store_baseline(state: AppState) -> None:
    if state.db.get_schedule("sch-baseline") is not None:
        return
    built = state.baseline_fn(state.signals, state.jobs, state.assets)
    if isinstance(built, OptimizeError):
        write_log(
            None,
            "optimizer",
            "error",
            {"integration": "optimizer", "message": built.message},
        )
        return
    state.db.upsert_schedule(built)


def _reload_inputs(state: AppState) -> Optional[str]:
    loaded = signals_mod.load_inputs(state.config)
    signals, jobs, assets, ev_deadline, error = loaded
    state.signals = list(signals)
    state.jobs = list(jobs)
    state.assets = list(assets)
    state.ev_force_deadline = ev_deadline
    state.db.replace_inputs(state.signals, state.jobs, state.assets)
    return error


@asynccontextmanager
async def lifespan(app: FastAPI):
    state: AppState = app.state.app_state
    state.loop = asyncio.get_running_loop()
    # Exit code 1 when the cached files fail validation (SPEC section 6).
    try:
        load_error = _reload_inputs(state)
    except Exception as exc:
        raise SystemExit(1) from exc
    if load_error:
        write_log(
            None,
            "system",
            "error",
            {"integration": "data_tools", "message": load_error},
        )
    _store_baseline(state)
    write_log(
        None,
        "system",
        "startup",
        {
            "mode": state.config.mode,
            "hardware_mode": state.config.hardware_mode,
        },
    )
    for message in state.startup_errors:
        write_log(None, "system", "error", message)
    if state.config.start_simulator and state.config.hardware_mode == "simulated":
        state.simulator_task = simulator_mod.start(state)
    try:
        yield
    finally:
        if state.simulator_task is not None:
            state.simulator_task.cancel()
        if state.expire_task is not None:
            state.expire_task.cancel()
        state.db.close()


def create_app(config: Optional[Config] = None) -> FastAPI:
    load_env()
    config = config or Config.from_env()
    # Exit code 1 when the cached files fail validation (SPEC section 6).
    # Validated here so the failure happens before the server binds.
    try:
        signals_mod.validate_inputs(config)
    except Exception as exc:
        raise SystemExit(1) from exc
    store, db_error = open_database(config.database_url)
    state = init_state(AppState(config=config, db=store))
    state.startup_errors = []
    if db_error:
        state.startup_errors.append(
            {"integration": "tigerdata", "message": db_error}
        )
    optimizer_error = _bind_optimizer(state)
    if optimizer_error:
        state.startup_errors.append(
            {"integration": "optimizer", "message": optimizer_error}
        )
    for message in _bind_integrations(state):
        state.startup_errors.append(
            {"integration": "integrations", "message": message}
        )
    for message in getattr(store, "timescale_errors", []):
        state.startup_errors.append(
            {"integration": "tigerdata", "message": message}
        )

    application = FastAPI(title="GridPulse.ai", lifespan=lifespan)
    application.state.app_state = state
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[config.cors_origins],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        detail = exc.errors()[0] if exc.errors() else {}
        loc = [str(part) for part in detail.get("loc", []) if part != "body"]
        field_name = loc[-1] if loc else "body"
        return JSONResponse(
            status_code=422,
            content=error_body(
                "validation_error",
                detail.get("msg", "request failed validation"),
                {"field": field_name},
            ),
        )

    @application.exception_handler(NotFoundError)
    async def _not_found(request: Request, exc: NotFoundError):
        return JSONResponse(
            status_code=404,
            content=error_body(
                "not_found",
                f"unknown schedule_id {exc.schedule_id}",
                {"schedule_id": exc.schedule_id},
            ),
        )

    @application.exception_handler(InvalidStateError)
    async def _invalid_state(request: Request, exc: InvalidStateError):
        return JSONResponse(
            status_code=409,
            content=error_body(
                "invalid_state",
                str(exc),
                {"schedule_id": exc.schedule_id, "status": exc.status},
            ),
        )

    @application.exception_handler(Exception)
    async def _internal(request: Request, exc: Exception):
        logger.exception("internal error")
        return JSONResponse(
            status_code=500,
            content=error_body("internal_error", "internal error"),
        )

    def _optimize_error_response(err: OptimizeError) -> JSONResponse:
        details = err.model_dump()
        if err.code == "infeasible":
            details = {"job_id": err.job_id}
        return JSONResponse(
            status_code=422,
            content=error_body(err.code, err.message, details),
        )

    @application.get("/api/health")
    async def health() -> Health:
        return Health(
            status="ok",
            mode=config.mode,
            hardware_mode=config.hardware_mode,
            database=store.kind,
            optimizer_mode=config.optimizer_mode,
            photon_mode=config.photon_mode,
            gemini_mode=config.gemini_mode,
            solana_mode=config.solana_mode,
            agents_mode=config.fetchai_mode,
        )

    @application.get("/api/signals")
    async def get_signals() -> dict:
        return {
            "horizon_start": state.signals[0].ts if state.signals else "",
            "items": [s.model_dump() for s in state.signals],
        }

    @application.get("/api/jobs")
    async def get_jobs() -> dict:
        return {"items": [j.model_dump() for j in state.jobs]}

    @application.get("/api/assets")
    async def get_assets() -> dict:
        return {"items": [a.model_dump() for a in state.assets]}

    @application.post("/api/optimize")
    async def post_optimize(body: OptimizeRequest):
        result = await asyncio.to_thread(
            state.optimize_fn,
            state.signals,
            state.jobs,
            state.assets,
            body.alpha,
            body.constraints,
        )
        if isinstance(result, OptimizeError):
            return _optimize_error_response(result)
        state.latest_alpha = body.alpha
        return store_proposed(result)

    @application.get("/api/schedules/applied")
    async def get_applied() -> Schedule:
        schedule = applied_schedule()
        if schedule is None:
            raise NotFoundError("applied")
        return schedule

    @application.get("/api/schedules/{schedule_id}")
    async def get_schedule_route(schedule_id: str) -> Schedule:
        return get_schedule(schedule_id)

    @application.post("/api/schedules/{schedule_id}/request-approval")
    async def post_request_approval(schedule_id: str) -> Schedule:
        return await asyncio.to_thread(request_approval, schedule_id, "dashboard")

    @application.post("/api/schedules/{schedule_id}/approve")
    async def post_approve(schedule_id: str) -> Schedule:
        return await asyncio.to_thread(approve_and_apply, schedule_id, "dashboard")

    @application.post("/api/schedules/{schedule_id}/reject")
    async def post_reject(schedule_id: str) -> Schedule:
        return await asyncio.to_thread(reject, schedule_id, "dashboard")

    @application.get("/api/explain/{schedule_id}")
    async def get_explain(schedule_id: str) -> ExplainResponse:
        schedule = get_schedule(schedule_id)
        if schedule.explanation is not None:
            text, source = schedule.explanation, "cache"
        else:
            text, source = await asyncio.to_thread(
                state.explain_with_source,
                schedule,
                state.signals,
                previous_applied(schedule),
            )
            schedule = schedule.model_copy(update={"explanation": text})
            state.db.upsert_schedule(schedule)
        write_log(
            schedule.schedule_id,
            "gemini",
            "explanation",
            {"source": source, "text": text},
        )
        return ExplainResponse(
            schedule_id=schedule.schedule_id, text=text, source=source
        )

    @application.get("/api/decisions")
    async def get_decisions(
        limit: int = Query(default=50, ge=1, le=200),
        after: Optional[str] = None,
    ) -> dict:
        return {"items": [e.model_dump() for e in state.db.list_logs(limit, after)]}

    @application.post("/api/telemetry")
    async def post_telemetry(body: Telemetry) -> dict:
        return ingest(state, body)

    @application.get("/api/telemetry")
    async def get_telemetry(minutes: int = Query(default=5, ge=1, le=60)) -> dict:
        return {"items": [m.model_dump() for m in recent_minutes(state, minutes)]}

    @application.get("/api/stream")
    async def stream() -> StreamingResponse:
        queue: asyncio.Queue = asyncio.Queue()
        state.sse_subscribers.append(queue)
        backlog = state.db.list_logs(200, None)[-20:]

        async def events():
            try:
                for entry in backlog:
                    yield f"event: decision\ndata: {entry.model_dump_json()}\n\n"
                while True:
                    try:
                        entry = await asyncio.wait_for(queue.get(), timeout=15.0)
                        yield f"event: decision\ndata: {entry.model_dump_json()}\n\n"
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
            finally:
                if queue in state.sse_subscribers:
                    state.sse_subscribers.remove(queue)

        return StreamingResponse(events(), media_type="text/event-stream")

    def _surplus_signals():
        """Copy the horizon and boost 4 slots from the current one (SPEC 6)."""
        copied = [s.model_copy() for s in state.signals]
        now = clock.now_dt()
        t0 = 10
        for index, signal in enumerate(copied):
            start = clock.parse_ts(signal.ts)
            if start <= now < start + timedelta(hours=1):
                t0 = index
                break
        for t in range(t0, t0 + 4):
            if not 0 <= t < len(copied):
                continue
            signal = copied[t]
            copied[t] = signal.model_copy(
                update={
                    "curtailment_mw": signal.curtailment_mw + 300.0,
                    "price_usd_per_mwh": signal.price_usd_per_mwh * 0.5,
                    "marginal_gco2_per_kwh": signal.marginal_gco2_per_kwh * 0.5,
                }
            )
        return copied

    def _trigger_flow() -> Schedule | OptimizeError:
        modified = _surplus_signals()
        result = state.optimize_fn(
            modified, state.jobs, state.assets, state.latest_alpha
        )
        if isinstance(result, OptimizeError):
            return result
        negotiated = state.negotiate(result)
        stored = store_proposed(negotiated)
        if stored.shifted_job_count > 0:
            return request_approval(stored.schedule_id, "optimizer")
        return approve_and_apply(stored.schedule_id, "optimizer")

    @application.post("/api/demo/trigger-surplus")
    async def trigger_surplus():
        result = await asyncio.to_thread(_trigger_flow)
        if isinstance(result, OptimizeError):
            return _optimize_error_response(result)
        return result

    @application.post("/api/demo/reset")
    async def demo_reset() -> dict:
        if state.expire_task is not None and not state.expire_task.done():
            state.expire_task.cancel()
            state.expire_task = None
        state.pending_schedule_id = None
        state.latest_alpha = 0.5
        state.db.reset()
        state.clear_gemini_cache()
        state.seen_message_ids.clear()
        state.clarified_schedule_ids.clear()
        error = await asyncio.to_thread(_reload_inputs, state)
        if error:
            write_log(
                None, "system", "error",
                {"integration": "data_tools", "message": error},
            )
        _store_baseline(state)
        write_log(
            None, "system", "reset", {"applied_schedule_id": "sch-baseline"}
        )
        return {"status": "ok", "applied_schedule_id": "sch-baseline"}

    try:
        from integrations.photon import photon_router

        application.include_router(photon_router, prefix="/api/webhooks")
    except Exception as exc:
        state.startup_errors.append(
            {"integration": "photon", "message": f"router import: {exc}"}
        )

    return application


app = create_app()
