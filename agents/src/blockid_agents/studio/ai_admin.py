"""Admin "AI health" API (docs/PLAN-AI-GATEWAY.md §3) — backs the web Admin page `/admin/ai`.

Admin session required (the studio session cookie, role admin); non-admins get 403, no session 401. The data comes from
the shared usage ledger in Postgres (`studio.ai_usage`, `studio.ai_model_state`), so the API shows what the worker
is doing. Model ids contain ":" and "/" (e.g. "deepinfra:deepseek-ai/DeepSeek-V4-Flash"): send them URL-encoded
(encodeURIComponent) in the path; both encoded and raw forms are accepted.

GET /v1/admin/ai/health  ->  200
{
  "generated_at": "2026-09-27T10:00:00+00:00",
  "routing": "dynamic",                        // "dynamic" (quality x reliability / cost) | "static" (env order)
  "thresholds": {"demote_pct": 80, "skip_pct": 95},
  "providers": [                                // one per provider that has at least one configured model
    {"id": "sambanova",                         // sambanova | deepinfra | claude_bridge | claude_cli | brave | claude_search
     "label": "SambaNova",
     "concurrency": 6,                          // max parallel calls (per model for SambaNova, per provider otherwise)
     "spend_today_usd": 0.0,                    // estimated from tokens x config.MODEL_PRICES (UTC day)
     "budget_today_usd": null,                  // DeepInfra: DEEPINFRA_DAILY_BUDGET_USD (default 3); else null
     "models": ["sambanova:DeepSeek-V3.1", "sambanova:DeepSeek-V3.2"]}
  ],
  "models": [
    {"id": "sambanova:DeepSeek-V3.1",           // stable id used by pause / resume
     "provider": "sambanova",
     "model": "DeepSeek-V3.1",
     "label": "SambaNova DeepSeek-V3.1",
     "kind": "llm",                             // "llm" | "search"
     "status": "healthy",                       // healthy | demoted (>= 80 % of a window: fallback only)
                                                // | skipped (>= 95 %: not used until the window resets)
                                                // | open (circuit breaker open after failures) | paused (admin)
     "status_reason": null,                     // plain sentence, e.g. "near its daily limit (83 %)"
     "paused": false,
     "paused_by": null, "paused_until": null,   // ISO time or null (null = until resumed)
     "circuit": {"state": "closed",             // closed | open | half_open
                 "open_until": null,            // ISO time while open
                 "consecutive_failures": 0},
     "windows": [                               // every limit that applies to this model
       {"window": "minute",                     // minute | day | month | budget_day (USD)
        "used": 12, "limit": 60, "pct": 20.0,
        "resets_at": "2026-09-27T10:01:00+00:00",
        "source": "ledger"}                     // "ledger" (our own count) | "headers" (provider x-ratelimit-*)
     ],
     "usage_pct": 20.0,                         // max pct over the windows (0 when no limit is known)
     "calls_24h": 140, "errors_24h": 3,
     "error_rate": 0.021,                       // failed / sent over the last 24 h (0..1)
     "schema_valid_rate": 0.99,                 // answers that matched the JSON schema (0..1, null if no data)
     "latency_p50_s": 5.2, "latency_p90_s": 11.8,   // successful calls, last 24 h (null if no data)
     "tokens_in_today": 51234, "tokens_out_today": 8123,
     "spend_today_usd": 0.0,
     "next_reset": "2026-09-28T00:00:00+00:00", // earliest reset of a window at >= 80 % (else of the day window)
     "context_tokens": 131072,                  // null for search providers
     "profiles": ["extract_json", "reason_score", "long_context"],
     "last_error": {"at": "2026-09-27T09:58:00+00:00", "error": "timeout after 60 s"}   // or null
    }
  ],
  "profiles": {                                 // current dynamic order per task profile (first = tried first)
    "extract_json": ["sambanova:DeepSeek-V3.1", "deepinfra:deepseek-ai/DeepSeek-V4-Flash", "claude-bridge"],
    "reason_score": ["..."], "long_context": ["..."], "search": ["search:brave", "search:claude"]
  },
  "recent_fallbacks": [                         // newest first, at most 30
    {"at": "2026-09-27T09:58:00+00:00", "profile": "extract_json", "agent": "people_analyst",
     "failed": "claude-bridge", "next": "sambanova:DeepSeek-V3.1",
     "outcome": "timeout",                      // error | timeout | schema_invalid | rate_limited | skipped | cancelled
     "error": "timeout after 120 s"}
  ]
}

POST /v1/admin/ai/models/{id}/pause   body (optional): {"reason": "flaky today", "minutes": 60}  (minutes null/absent
     = until resumed)  ->  200 {"ok": true, "model": <model object as above>}
POST /v1/admin/ai/models/{id}/resume  (no body)  ->  200 {"ok": true, "model": <model object>}
Unknown id -> 404 {"detail": "unknown model"}. Every pause / resume writes a studio.audit row (ai_model_paused /
ai_model_resumed). A paused model is skipped by the router within ~10 s in every process.
"""
from __future__ import annotations

import logging
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


class PauseBody(BaseModel):
    reason: str = Field(default="", max_length=300)
    minutes: int | None = Field(default=None, ge=1, le=60 * 24 * 30)


def _gateway(ctx):
    from ..ai_gateway import get_gateway

    return get_gateway(ctx.settings, db=ctx.need_db())


def build_ai_admin_router(ctx) -> APIRouter:
    from .auth import COOKIE, Session

    r = APIRouter()

    def session(request: Request) -> Session | None:
        sid = request.cookies.get(COOKIE)
        return ctx.sessions.get(sid) if sid else None

    def require_admin(sess: Session | None = Depends(session)) -> Session:
        if sess is None:
            raise HTTPException(401, "sign in required")
        if not sess.is_admin:
            raise HTTPException(403, "admin only")
        if sess.must_change:
            raise HTTPException(403, "password change required")
        return sess

    def audit(sess, action: str, target: str, detail: dict) -> None:
        try:
            ctx.need_db().audit(sess.actor, action, target, **detail, role="platform_admin")
        except Exception:
            log.exception("ai admin audit")

    @r.get("/v1/admin/ai/health")
    def health(sess=Depends(require_admin)):
        return _gateway(ctx).health()

    def _model_id(request: Request) -> str:
        path = request.url.path  # raw path keeps an encoded "/" inside the id
        mid = path.split("/v1/admin/ai/models/", 1)[1].rsplit("/", 1)[0]
        return unquote(mid)

    @r.post("/v1/admin/ai/models/{model_id:path}/pause")
    def pause(model_id: str, request: Request, body: PauseBody | None = None, sess=Depends(require_admin)):
        gw = _gateway(ctx)
        mid = _model_id(request)
        if not gw.known_model(mid):
            raise HTTPException(404, "unknown model")
        b = body or PauseBody()
        gw.pause(mid, by=sess.actor, reason=b.reason, minutes=b.minutes)
        audit(sess, "ai_model_paused", mid, {"reason": b.reason, "minutes": b.minutes})
        return {"ok": True, "model": gw.model_health(mid)}

    @r.post("/v1/admin/ai/models/{model_id:path}/resume")
    def resume(model_id: str, request: Request, sess=Depends(require_admin)):
        gw = _gateway(ctx)
        mid = _model_id(request)
        if not gw.known_model(mid):
            raise HTTPException(404, "unknown model")
        gw.resume(mid, by=sess.actor)
        audit(sess, "ai_model_resumed", mid, {})
        return {"ok": True, "model": gw.model_health(mid)}

    return r
