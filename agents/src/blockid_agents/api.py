"""HTTP API used by the eth.blockid.au web app (runs on the app VM, behind Nginx + IAP).

All AI work is asynchronous: endpoints enqueue jobs and return 202 immediately; the UI polls
`GET /v1/workflows/{id}` and shows the pending human gate when there is one.

Issuance Studio endpoints (cookie sessions, see docs/IMPLEMENTATION.md) live in studio/routes.py
and are mounted here; the legacy X-API-Key endpoints below are kept for backwards compatibility.
"""
from __future__ import annotations

import hmac
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .config import Settings, get_settings
from .jobs import JobQueue

log = logging.getLogger(__name__)


class OnboardingRequest(BaseModel):
    dataroom: dict[str, str]  # filename -> extracted text (upload/OCR happens before this call)
    issuance_inputs: dict[str, Any]


class DividendRequest(BaseModel):
    dividend: dict[str, Any]  # record_block, balances, total_amount, pay_token, distributor, ...


class Decision(BaseModel):
    decision: dict[str, Any]  # {"approved": bool, "reviewer": "...", ...gate-specific fields}


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_EXEMPT_PATHS = {"/v1/rpc"}  # cookie-less public JSON-RPC proxy (wallets, scripts)
_DEV_ORIGIN = re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d{1,5})?$")


def origin_allowed(origin: str, s: Settings) -> bool:
    o = origin.strip().rstrip("/")
    return o in s.allowed_origins or (s.studio_dev and bool(_DEV_ORIGIN.match(o)))


def _request_origin(request: Request) -> str | None:
    if request.headers.get("origin"):
        return request.headers["origin"]
    ref = request.headers.get("referer")
    if ref:
        p = urlparse(ref)
        return f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else "null"
    return None


def _studio_context(s: Settings, studio, chain, issuer, runner_factory):
    from .studio.routes import StudioContext
    from .studio.services import IssuerClient, Web3ChainReader

    if studio is None and s.database_url.startswith("postgres"):
        from .studio.db import Studio

        studio = Studio(s.database_url)
    if studio is not None:
        try:
            studio.apply_schema()
            studio.seed_admin(s.admin_username, s.admin_password_hash)
        except Exception:  # DB not up yet: retried lazily on first request
            log.exception("studio schema not applied at startup")
    if chain is None and s.local_rpc_url:
        chain = Web3ChainReader(s.local_rpc_url)
    if issuer is None and s.issuer_internal_token:
        issuer = IssuerClient(s.issuer_url, s.issuer_internal_token)
    if runner_factory is None and studio is not None:
        def runner_factory():
            from .deps import Deps
            from .llm import build_llm
            from .studio.runner import ValuationRunner
            from .worker import make_checkpointer

            deps = Deps.default(build_llm(s), s)
            return ValuationRunner(deps, make_checkpointer(deps), studio)
    return StudioContext(settings=s, db=studio, chain=chain, issuer=issuer, runner_factory=runner_factory)


def create_app(settings: Settings | None = None, queue: JobQueue | None = None, *, studio=None, chain=None,
               issuer=None, runner_factory=None) -> FastAPI:
    """`studio` (db.Studio), `chain` (ChainReader), `issuer` (IssuerClient) and `runner_factory`
    are injectable for tests; by default they are built from settings."""
    from .studio.company_admins import build_company_admins_router
    from .studio.dividend_policy import build_dividend_policy_router, interval_from_env
    from .studio.hr import build_hr_router
    from .studio.offerings import build_offerings_router
    from .studio.routes import build_router
    from .studio.transfers import build_transfer_router
    from .studio.updates import build_updates_router
    from .studio.verify import build_verify_router

    s = settings or get_settings()
    q = queue or JobQueue(Path(s.data_dir) / "jobs.sqlite")
    dev = s.studio_dev
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Automatic dividends: declare for newly published updates, pay once the veto window has passed
        (studio/dividend_policy.py). Runs in the API because only the API can reach the issuer.
        DIVIDEND_AUTOMATION_SECONDS=0 disables it."""
        from .studio.offerings import interval_from_env as offering_interval

        from .studio.hr_store import HrWatchdog, watchdog_interval_from_env

        auto, offers = app.state.studio.automation, app.state.studio.offerings
        hrw = HrWatchdog(app.state.studio.db)
        auto.start(interval_from_env())
        offers.start(offering_interval())  # closes offerings whose closing date has passed (OFFERING_AUTOMATION_SECONDS)
        hrw.start(watchdog_interval_from_env())  # stalled HR runs: re-queue once, then fail (HR_WATCHDOG_SECONDS)
        # ops (docs/PLAN-OPS.md): ERROR+ logs -> studio.ops_errors; monitor loop (leader-elected) for incidents,
        # traffic, weekly report. OPS_ENABLED=0 disables the monitor (error capture stays on).
        from .ops.errors import install_error_capture
        from .ops.monitor import build_monitor

        install_error_capture(app.state.studio.db, "api")
        rt = app.state.ops
        if rt.cfg.enabled:
            rt.monitor = build_monitor(app.state.studio, rt.cfg)
            if rt.monitor is not None:
                rt.monitor.start()
        try:
            yield
        finally:
            auto.stop()
            offers.stop()
            hrw.stop()
            if rt.monitor is not None:
                rt.monitor.stop()

    app = FastAPI(title="BlockID Agents API", version="0.2.0", docs_url="/docs" if dev else None,
                  redoc_url="/redoc" if dev else None, openapi_url="/openapi.json" if dev else None, lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        """{"detail": "<field>: <message>; ..."} — never echoes the input (it may be NaN, huge or sensitive)."""
        parts = [f"{'.'.join(str(x) for x in e.get('loc', ())[1:]) or 'body'}: {e.get('msg', 'invalid')}"
                 for e in exc.errors()]
        return JSONResponse({"detail": "; ".join(parts)[:1000]}, status_code=422)

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        """State-changing requests must come from an allowed Origin (Referer if no Origin). Browsers always
        send Origin on cross-origin POST/PUT/DELETE, so a request with neither header is a non-browser client:
        it is allowed only when it carries no session cookie (it cannot ride a user's session)."""
        if request.method not in SAFE_METHODS and request.url.path not in CSRF_EXEMPT_PATHS:
            from .studio.auth import COOKIE

            origin = _request_origin(request)
            if origin is not None:
                if not origin_allowed(origin, s):
                    return JSONResponse({"detail": "cross-site request refused"}, status_code=403)
            elif COOKIE in request.cookies:
                return JSONResponse({"detail": "missing Origin header"}, status_code=403)
        return await call_next(request)

    from .ops.errors import install_access_log

    install_access_log(app)  # outermost: X-Request-ID + one JSON access line per request (ops/errors.py)

    ctx = _studio_context(s, studio, chain, issuer, runner_factory)
    app.state.studio = ctx
    app.include_router(build_router(ctx))
    app.include_router(build_verify_router(ctx))
    app.include_router(build_transfer_router(ctx))
    app.include_router(build_company_admins_router(ctx))
    app.include_router(build_updates_router(ctx))
    app.include_router(build_dividend_policy_router(ctx, ctx.automation))
    app.include_router(build_offerings_router(ctx, ctx.offerings))
    app.include_router(build_hr_router(ctx))  # founding-team / person reviews (hr.blockid.au)
    from .studio.ai_admin import build_ai_admin_router

    app.include_router(build_ai_admin_router(ctx))  # admin AI health: /v1/admin/ai/* (ai_gateway.py)
    from .ops.api import OpsRuntime, build_ops_router

    app.state.ops = OpsRuntime()
    app.include_router(build_ops_router(ctx, app.state.ops))  # admin ops: /v1/admin/ops/* (ops/__init__.py)


    def auth(x_api_key: str = Header(default="")) -> None:
        if not s.api_key or not hmac.compare_digest(x_api_key, s.api_key):
            raise HTTPException(401, "invalid API key")

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "queued": q.pending()}

    @app.post("/v1/onboarding", status_code=202, dependencies=[Depends(auth)])
    def start_onboarding(req: OnboardingRequest):
        jid = q.enqueue("onboarding", "onboarding", req.model_dump())
        return {"workflow_id": jid, "status": "queued"}

    @app.post("/v1/dividends", status_code=202, dependencies=[Depends(auth)])
    def start_dividend(req: DividendRequest):
        jid = q.enqueue("dividend", "dividend", req.model_dump())
        return {"workflow_id": jid, "status": "queued"}

    @app.get("/v1/workflows/{wid}", dependencies=[Depends(auth)])
    def get_workflow(wid: str):
        job = q.latest_for_thread(wid)
        if not job:
            raise HTTPException(404, "unknown workflow")
        job.pop("payload", None)  # never echo the data room back
        return job

    @app.post("/v1/workflows/{wid}/decision", status_code=202, dependencies=[Depends(auth)])
    def decide(wid: str, body: Decision):
        job = q.latest_for_thread(wid)
        if not job or job["status"] != "waiting_human":
            raise HTTPException(409, "workflow is not waiting for a decision")
        if not body.decision.get("reviewer"):
            raise HTTPException(422, "decision.reviewer is required")
        jid = q.enqueue("resume", job["graph"], body.model_dump(), thread_id=wid)
        return {"workflow_id": wid, "job_id": jid, "status": "queued"}

    @app.get("/v1/workflows/{wid}/safe-batch", dependencies=[Depends(auth)])
    def safe_batch(wid: str):
        job = q.latest_for_thread(wid)
        if not job or not (job.get("result") or {}).get("safe_batch"):
            raise HTTPException(404, "no Safe batch for this workflow yet")
        return job["result"]["safe_batch"]

    return app
