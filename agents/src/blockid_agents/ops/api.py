"""Admin ops API: /v1/admin/ops/* (platform admin only). JSON shapes: see the ops package docstring
(agents/src/blockid_agents/ops/__init__.py)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ..studio.db import jsonable
from .checks import REGISTRY
from .config import OpsConfig
from .incidents import IncidentStore, Notifier
from .report import Reports
from .traffic import TrafficStore, logs_readable

log = logging.getLogger(__name__)
EMAIL = r"^[^@\s,]+@[^@\s,]+\.[^@\s,]+$"


class NoteBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    note: str = Field(default="", max_length=1000)


class SendNowBody(BaseModel):
    kind: str = Field(default="weekly", pattern="^(weekly|daily)$")
    to: str | None = Field(default=None, max_length=200, pattern=EMAIL)


class TestEmailBody(BaseModel):
    to: str | None = Field(default=None, max_length=200, pattern=EMAIL)


class OpsRuntime:
    """Shared between the router and the API lifespan (which sets `monitor`)."""

    def __init__(self, cfg: OpsConfig | None = None, mailer=None):
        from ..studio.mailer import Mailer

        self.cfg = cfg or OpsConfig()
        self.mailer = mailer if mailer is not None else Mailer()
        self.monitor = None


def build_ops_router(ctx, rt: OpsRuntime) -> APIRouter:
    from ..studio.auth import COOKIE, Session

    r = APIRouter(prefix="/v1/admin/ops")

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

    def audit(sess, action: str, target, **detail) -> None:
        try:
            ctx.need_db().audit(sess.actor, action, None if target is None else str(target), role="platform_admin",
                                **detail)
        except Exception:  # noqa: BLE001
            log.exception("ops audit")

    def store() -> IncidentStore:
        return IncidentStore(ctx.need_db(), rt.cfg)

    def reports() -> Reports:
        gw = None
        if rt.monitor is not None and rt.monitor.env._gateway is not None:
            gw = rt.monitor.env.ai_health
        return Reports(ctx.need_db(), rt.cfg, rt.mailer, ai_health=gw)

    # -------------------------------------------------------------- summary
    @r.get("/summary")
    def summary(sess=Depends(require_admin)):
        db = ctx.need_db()
        st = IncidentStore(db, rt.cfg)
        states = {x["check_id"]: x for x in db.all("SELECT * FROM studio.ops_checks_state")}
        active = {x["check_id"]: x["id"] for x in db.all(
            "SELECT DISTINCT ON (check_id) check_id, id FROM studio.ops_incidents WHERE status <> 'resolved' "
            "ORDER BY check_id, CASE severity WHEN 'critical' THEN 0 WHEN 'warn' THEN 1 ELSE 2 END, opened_at")}
        checks = []
        for c in REGISTRY.values():
            s_ = states.get(c.id) or {}
            checks.append({"id": c.id, "title": c.title, "severity": c.severity,
                           "status": s_.get("status") or "unknown", "detail": s_.get("detail") or "not run yet",
                           "last_run_at": s_.get("last_run_at"), "last_ok_at": s_.get("last_ok_at"),
                           "incident_id": active.get(c.id), "runbook_id": c.runbook_id,
                           "runbook_url": rt.cfg.runbook_link(c.runbook_id)})
        today = datetime.now(timezone.utc).date()
        t = db.one("SELECT coalesce(sum(page_views),0)::int AS page_views, coalesce(sum(unique_visitors),0)::int AS "
                   "unique_visitors, coalesce(sum(requests),0)::int AS requests, coalesce(sum(status_5xx),0)::int AS "
                   "status_5xx FROM studio.ops_traffic_daily WHERE day=%s", (today,))
        errs = db.one("SELECT coalesce(sum(count),0)::int AS n FROM studio.ops_errors WHERE last_seen > now() - "
                      "interval '24 hours'")["n"]
        last = db.one("SELECT id, kind, created_at, emailed, email_reason FROM studio.ops_reports ORDER BY created_at "
                      "DESC, id DESC LIMIT 1")
        mon = states.get("_monitor") or {}
        from . import stats

        try:
            kpis = stats.kpis(db)
        except Exception:  # noqa: BLE001 - headline numbers must not break the page
            log.exception("ops kpis")
            kpis = None
        return jsonable({
            "generated_at": datetime.now(timezone.utc), "enabled": rt.cfg.enabled,
            "leader": bool(rt.monitor and rt.monitor.leader and rt.monitor.leader.is_leader),
            "last_run_at": mon.get("last_run_at"), "smtp_configured": bool(rt.mailer.configured),
            "alert_to": rt.cfg.alert_to, "report_to": rt.cfg.report_to,
            "unsent_emails": Notifier(db, rt.mailer, rt.cfg, st).unsent_count(),
            "open_incidents": st.counts(), "checks": checks, "errors_24h": int(errs), "traffic_today": t,
            "last_report": last, "kpis": kpis})

    # -------------------------------------------------------------- incidents
    @r.get("/incidents")
    def incidents(status: str = Query("active", pattern="^(active|open|acknowledged|resolved|all)$"),
                  limit: int = Query(100, ge=1, le=500), sess=Depends(require_admin)):
        return {"incidents": store().list(status, limit)}

    @r.get("/incidents/{iid}")
    def incident(iid: int, sess=Depends(require_admin)):
        s = store()
        row = s.get(iid)
        if row is None:
            raise HTTPException(404, "unknown incident")
        return {**row, "events": s.events(iid)}

    def _act(iid: int, body: NoteBody | None, sess, fn: str, action: str):
        s = store()
        try:
            row = getattr(s, fn)(iid, sess.actor, (body.note if body else ""))
        except KeyError:
            raise HTTPException(404, "unknown incident") from None
        except ValueError as e:
            raise HTTPException(409, str(e)) from None
        audit(sess, action, iid, note=(body.note if body else ""))
        return {"ok": True, "incident": row}

    @r.post("/incidents/{iid}/ack")
    def ack(iid: int, body: NoteBody | None = None, sess=Depends(require_admin)):
        return _act(iid, body, sess, "acknowledge", "ops_incident_ack")

    @r.post("/incidents/{iid}/resolve")
    def resolve(iid: int, body: NoteBody | None = None, sess=Depends(require_admin)):
        return _act(iid, body, sess, "resolve", "ops_incident_resolved")

    # -------------------------------------------------------------- errors
    @r.get("/errors")
    def errors(days: int = Query(7, ge=1, le=30), source: str | None = Query(None, pattern="^(api|worker|issuer)$"),
               limit: int = Query(100, ge=1, le=500), sess=Depends(require_admin)):
        db = ctx.need_db()
        since = datetime.now(timezone.utc) - timedelta(days=days)
        where, params = "last_seen >= %s", [since]
        if source:
            where += " AND source = %s"
            params.append(source)
        rows = db.all(f"SELECT id, fingerprint, source, logger, level, message, traceback, count, first_seen, "
                      f"last_seen, request_id, route FROM studio.ops_errors WHERE {where} ORDER BY last_seen DESC "
                      f"LIMIT %s", (*params, limit))
        total = db.one(f"SELECT count(*) AS n FROM studio.ops_errors WHERE {where}", tuple(params))["n"]
        return jsonable({"errors": rows, "total": int(total)})

    # -------------------------------------------------------------- traffic / stats
    @r.get("/traffic")
    def traffic(days: int = Query(14, ge=1, le=90), sess=Depends(require_admin)):
        db = ctx.need_db()
        rows = TrafficStore(db).daily(days)
        st = db.one("SELECT last_run_at, data FROM studio.ops_checks_state WHERE check_id='_traffic'")
        readable = bool(st and (st["data"] or {}).get("readable"))
        if st is None:
            readable, _ = logs_readable(rt.cfg.nginx_log_dir, rt.cfg.traffic_hosts)
        daily = [{k: r[k] for k in ("day", "host", "page_views", "unique_visitors", "requests", "bot_requests",
                                    "api_requests", "status_4xx", "status_5xx", "top_pages", "top_referrers",
                                    "countries")} for r in rows]
        keys = ("page_views", "unique_visitors", "requests", "bot_requests", "status_5xx")
        return jsonable({"days": days, "source": "nginx" if readable or rows else "unavailable",
                         "last_parsed_at": st["last_run_at"] if st else None,
                         "hosts": sorted({r["host"] for r in rows} | set(rt.cfg.traffic_hosts)),
                         "daily": daily, "totals": {k: sum(int(r[k]) for r in rows) for k in keys}})

    @r.get("/stats")
    def stats_(days: int = Query(30, ge=1, le=365), sess=Depends(require_admin)):
        from . import stats

        return stats.collect(ctx.need_db(), days)

    # -------------------------------------------------------------- reports
    @r.get("/reports")
    def report_list(limit: int = Query(20, ge=1, le=200), sess=Depends(require_admin)):
        return {"reports": reports().list(limit)}

    @r.get("/reports/preview")
    def report_preview(kind: str = Query("weekly", pattern="^(weekly|daily)$"), sess=Depends(require_admin)):
        rep = reports().build(kind)
        return {"subject": rep["subject"], "html": rep["html"], "text": rep["text"], "data": rep["data"]}

    @r.get("/reports/{rid}")
    def report_get(rid: int, sess=Depends(require_admin)):
        rep = reports().get(rid)
        if rep is None:
            raise HTTPException(404, "unknown report")
        return rep

    @r.post("/reports/send-now")
    def report_send(body: SendNowBody | None = None, sess=Depends(require_admin)):
        b = body or SendNowBody()
        rs = reports()
        db = ctx.need_db()
        rid = rs.store(rs.build(b.kind), trigger="manual", slot=None, to=b.to or rt.cfg.report_to)
        row = db.one("SELECT * FROM studio.ops_reports WHERE id=%s", (rid,))
        if rt.mailer.configured:
            ok = rs.deliver(row, Notifier(db, rt.mailer, rt.cfg))
        else:
            rs.mark_unsent("SMTP not configured")
            ok = False
        rep = rs.get(rid)
        audit(sess, "ops_report_sent", rid, kind=b.kind, to=row["to_addr"], emailed=ok)
        summary_ = {k: v for k, v in rep.items() if k not in ("html", "text", "data")}
        return {"ok": True, "report": summary_, "emailed": ok, "reason": None if ok else rep["email_reason"]}

    @r.post("/test-email")
    def test_email(body: TestEmailBody | None = None, sess=Depends(require_admin)):
        from . import mail

        to = (body.to if body and body.to else None) or rt.cfg.alert_to
        if not rt.mailer.configured:
            audit(sess, "ops_test_email", to, ok=False)
            return {"ok": False, "to": to, "reason": "SMTP not configured"}
        subject, text, html = mail.test_email(rt.cfg)
        ok, reason = Notifier(ctx.need_db(), rt.mailer, rt.cfg).send("test", to, subject, text, html)
        audit(sess, "ops_test_email", to, ok=ok)
        return {"ok": ok, "to": to, "reason": reason}

    return r
