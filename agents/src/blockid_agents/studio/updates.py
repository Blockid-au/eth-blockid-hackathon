"""Business updates API (docs/UPGRADE-INVESTOR-PLAN.md 3c, lean MVP).

Founder side (platform admin, or an active owner / manager of the company, see company_admins.CompanyAuthz):
  GET  /v1/companies/{tk}/kpis                 KPI values entered so far, by period
  PUT  /v1/companies/{tk}/kpis                 {period_end, values:{metric: number|null}}   (null = remove)
  POST /v1/companies/{tk}/updates              {cadence, period_end, kpis?, note?} -> draft built by code from the
                                               numbers (update_draft.build_draft); re-preparing a draft / rejected /
                                               failed update of the same period rebuilds it
  PATCH /v1/updates/{id}                       {title?, summary?, note?, highlights?, risks?}  (draft / rejected)
  POST /v1/updates/{id}/submit                 draft | rejected -> pending_approval
Approval (platform admin only; queue "updates" in GET /v1/admin/approvals):
  POST /v1/admin/updates/{id}/approve          pending_approval | failed -> publishing, content_hash computed,
                                               the issuer records it on BlockID Chain (POST /disclose) -> published
  POST /v1/admin/updates/{id}/reject           {reason}
Everyone (a published update is the disclosure itself):
  GET  /v1/companies/{tk}/updates              published only (company admins also see drafts / pending)
  GET  /v1/updates/{id}                        + canonical JSON text, content_hash, on-chain record
  GET  /v1/me/updates                          published updates of the companies the signed-in wallet holds
  GET  /v1/demo/updates                        same, for the sample portfolio

Nothing here signs: approval flips the row and asks the issuer, which re-checks the hash before sending.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from . import accounts as acct
from . import update_draft as ud
from .auth import COOKIE, Session
from .company_admins import CompanyAuthz
from .db import ONCHAIN_STATUSES, jsonable
from .services import IssuerError

log = logging.getLogger(__name__)

EDITABLE = ("draft", "rejected")
MAX_ABS = Decimal(10) ** 15
NONNEG = {"revenue", "cash", "customers", "headcount"}


class _Body(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")


class KpiBody(_Body):
    period_end: date
    values: dict[str, float | None] = Field(default_factory=dict)


class PrepareBody(_Body):
    cadence: Literal["weekly", "monthly", "quarterly", "annual"] = "monthly"
    period_end: date
    kpis: dict[str, float | None] | None = None
    note: str = Field(default="", max_length=2000)


class EditBody(_Body):
    title: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=2000)
    highlights: list[str] | None = Field(default=None, max_length=12)
    risks: list[str] | None = Field(default=None, max_length=12)


class ReasonBody(_Body):
    reason: str = Field(default="", max_length=1000)


def pending_updates(db, ids: list[int] | None = None) -> list[dict]:
    """Updates waiting for a platform admin (GET /v1/admin/approvals 'updates'); company scope sees none."""
    if ids is not None:
        return []
    rows = db.all("SELECT u.*, c.ticker, c.name AS company_name FROM studio.updates u "
                  "JOIN studio.companies c ON c.id=u.company_id WHERE u.status IN ('pending_approval','failed') "
                  "ORDER BY u.updated_at, u.id")
    return [view(r, private=True) for r in rows]


def view(u: dict, *, private: bool = False, canonical: str | None = None) -> dict:
    out = {
        "id": u["id"], "ticker": u.get("ticker"), "company": u.get("company_name"), "company_id": u["company_id"],
        "cadence": u["cadence"], "period_start": u["period_start"], "period_end": u["period_end"],
        "period_label": ud.period_label(u["cadence"], u["period_end"]),
        "status": u["status"], "title": u.get("title") or "", "body": ud.canonical_body(u.get("body")),
        "content_hash": u.get("content_hash"), "anchor": u.get("anchor"), "published_at": u.get("published_at"),
        "created_at": u.get("created_at"), "updated_at": u.get("updated_at"),
    }
    if private:
        out.update(created_by=u.get("created_by"), approved_by=u.get("approved_by"), error=u.get("error"),
                   reason=u.get("reason"))
    if canonical is not None:
        out["canonical"] = canonical
    return jsonable(out)


def _check_value(metric: str, v: float | None) -> Decimal | None:
    if metric not in ud.METRICS:
        raise HTTPException(422, f"unknown metric {metric!r}; use {sorted(ud.METRICS)}")
    if v is None:
        return None
    d = Decimal(str(v))
    if abs(d) >= MAX_ABS:
        raise HTTPException(422, f"{metric}: value out of range")
    if metric in NONNEG and d < 0:
        raise HTTPException(422, f"{metric} cannot be negative")
    if ud.METRICS[metric] == "count" and d != d.to_integral_value():
        raise HTTPException(422, f"{metric} must be a whole number")
    return d.quantize(Decimal("0.01"))


def build_updates_router(ctx) -> APIRouter:
    r = APIRouter()
    authz = CompanyAuthz(ctx)
    s = ctx.settings

    def session(request: Request) -> Session | None:
        sid = request.cookies.get(COOKIE)
        return ctx.sessions.get(sid) if sid else None

    def require_user(sess: Session | None = Depends(session)) -> Session:
        if sess is None:
            raise HTTPException(401, "sign in required")
        return sess

    def require_admin(sess: Session = Depends(require_user)) -> Session:
        if not sess.is_admin:
            raise HTTPException(403, "admin only")
        if sess.must_change:
            raise HTTPException(403, "password change required")
        return sess

    def company(tk: str) -> dict:
        c = ctx.need_db().one("SELECT * FROM studio.companies WHERE ticker=%s", (tk.upper(),))
        if not c:
            raise HTTPException(404, "unknown ticker")
        return c

    def audit(sess: Session, role: str, action: str, target: str, **detail) -> None:
        ctx.need_db().audit(sess.actor, action, target, role=role, **detail)

    def load(uid: str) -> dict:
        u = ctx.need_db().one("SELECT u.*, c.ticker, c.name AS company_name FROM studio.updates u "
                              "JOIN studio.companies c ON c.id=u.company_id WHERE u.id=%s", (uid,))
        if not u:
            raise HTTPException(404, "unknown update")
        return u

    def can_manage(sess: Session | None, cid: int) -> bool:
        return bool(sess) and authz.role(sess, cid) is not None

    # -------------------------------------------------------------- KPIs
    def kpi_periods(cid: int) -> list[dict]:
        rows = ctx.need_db().all("SELECT period_end, metric, value, unit FROM studio.kpi_values WHERE company_id=%s "
                                 "ORDER BY period_end DESC, metric", (cid,))
        out: dict[date, dict] = {}
        for x in rows:
            out.setdefault(x["period_end"], {})[x["metric"]] = ud.num(x["value"])
        return jsonable([{"period_end": k, "values": v} for k, v in out.items()])

    def upsert_kpis(c: dict, period_end: date, values: dict[str, float | None], actor: str) -> dict:
        checked = {m: _check_value(m, v) for m, v in values.items()}
        with ctx.need_db().tx() as tx:
            for m, v in checked.items():
                if v is None:
                    tx.execute("DELETE FROM studio.kpi_values WHERE company_id=%s AND metric=%s AND period_end=%s",
                               (c["id"], m, period_end))
                else:
                    tx.execute("INSERT INTO studio.kpi_values (company_id, period_end, metric, value, unit, source, "
                               "entered_by) VALUES (%s,%s,%s,%s,%s,'manual',%s) ON CONFLICT (company_id, metric, "
                               "period_end) DO UPDATE SET value=EXCLUDED.value, unit=EXCLUDED.unit, "
                               "source='manual', entered_by=EXCLUDED.entered_by, created_at=now()",
                               (c["id"], period_end, m, v, ud.METRICS[m], actor))
        return {m: ud.num(v) for m, v in checked.items()}

    def check_period(end: date) -> None:
        if end > datetime.now(timezone.utc).date() + timedelta(days=1):
            raise HTTPException(422, "the period cannot end in the future")
        if end.year < 2000:
            raise HTTPException(422, "period_end is too far in the past")

    @r.get("/v1/companies/{tk}/kpis")
    def get_kpis(tk: str, sess: Session = Depends(require_user)):
        c = company(tk)
        authz.check(sess, c["id"])
        return {"ticker": c["ticker"], "metrics": [{"metric": m, "unit": u} for m, u in ud.METRICS.items()],
                "periods": kpi_periods(c["id"])}

    @r.put("/v1/companies/{tk}/kpis")
    def put_kpis(tk: str, body: KpiBody, sess: Session = Depends(require_user)):
        c = company(tk)
        role = authz.check(sess, c["id"])
        check_period(body.period_end)
        saved = upsert_kpis(c, body.period_end, body.values, sess.actor)
        audit(sess, role, "kpis_entered", c["ticker"], company_id=c["id"], period_end=body.period_end, values=saved)
        return {"ticker": c["ticker"], "period_end": body.period_end.isoformat(), "saved": saved,
                "periods": kpi_periods(c["id"])}

    # -------------------------------------------------------------- drafts
    @r.post("/v1/companies/{tk}/updates", status_code=201)
    def prepare(tk: str, body: PrepareBody, sess: Session = Depends(require_user)):
        db = ctx.need_db()
        c = company(tk)
        role = authz.check(sess, c["id"])
        if c["status"] not in ONCHAIN_STATUSES:
            raise HTTPException(409, "updates start once the shares are issued")
        check_period(body.period_end)
        start = ud.period_start(body.cadence, body.period_end)
        existing = db.one("SELECT id, status FROM studio.updates WHERE company_id=%s AND cadence=%s AND period_end=%s",
                          (c["id"], body.cadence, body.period_end))
        if existing and existing["status"] not in ("draft", "rejected", "failed"):
            raise HTTPException(409, f"the {body.cadence} update for this period is already {existing['status']}")
        if body.kpis:
            upsert_kpis(c, body.period_end, body.kpis, sess.actor)
        cur = {x["metric"]: x["value"] for x in db.all(
            "SELECT metric, value FROM studio.kpi_values WHERE company_id=%s AND period_end=%s",
            (c["id"], body.period_end))}
        if not cur:
            raise HTTPException(422, "enter at least one figure for this period first")
        prev = {x["metric"]: x["value"] for x in db.all(
            "SELECT DISTINCT ON (metric) metric, value FROM studio.kpi_values WHERE company_id=%s AND period_end < %s "
            "ORDER BY metric, period_end DESC", (c["id"], start))}
        draft = ud.build_draft(c, body.cadence, start, body.period_end, cur, prev, body.note)
        if existing:
            db.exec("UPDATE studio.updates SET status='draft', period_start=%s, title=%s, body=%s, content_hash=NULL, "
                    "anchor=NULL, error=NULL, reason=NULL, approved_by=NULL, created_by=%s, updated_at=now() "
                    "WHERE id=%s", (start, draft["title"], Jsonb(draft["body"]), sess.actor, existing["id"]))
            uid = existing["id"]
        else:
            uid = "upd_" + uuid.uuid4().hex[:12]
            db.exec("INSERT INTO studio.updates (id, company_id, cadence, period_start, period_end, status, title, "
                    "body, created_by) VALUES (%s,%s,%s,%s,%s,'draft',%s,%s,%s)",
                    (uid, c["id"], body.cadence, start, body.period_end, draft["title"], Jsonb(draft["body"]),
                     sess.actor))
        audit(sess, role, "update_prepared", c["ticker"], company_id=c["id"], update_id=uid, cadence=body.cadence,
              period_end=body.period_end, rebuilt=bool(existing))
        return view(load(uid), private=True)

    @r.patch("/v1/updates/{uid}")
    def edit(uid: str, body: EditBody, sess: Session = Depends(require_user)):
        db = ctx.need_db()
        u = load(uid)
        role = authz.check(sess, u["company_id"])
        if u["status"] not in EDITABLE:
            raise HTTPException(409, f"update is {u['status']}; only drafts can be edited")
        b = ud.canonical_body(u.get("body"))
        changed = []
        for k in ("summary", "note"):
            v = getattr(body, k)
            if v is not None:
                b[k] = v.strip()
                changed.append(k)
        for k in ("highlights", "risks"):
            v = getattr(body, k)
            if v is not None:
                b[k] = [x.strip()[:500] for x in v if x and x.strip()]
                changed.append(k)
        title = u["title"]
        if body.title is not None:
            if not body.title.strip():
                raise HTTPException(422, "title cannot be empty")
            title = body.title.strip()
            changed.append("title")
        n = db.exec("UPDATE studio.updates SET title=%s, body=%s, status='draft', reason=CASE WHEN status='rejected' "
                    "THEN reason ELSE NULL END, updated_at=now() WHERE id=%s AND status IN ('draft','rejected')",
                    (title, Jsonb(b), uid))
        if not n:
            raise HTTPException(409, "update changed meanwhile; reload")
        audit(sess, role, "update_edited", u["ticker"], company_id=u["company_id"], update_id=uid, fields=changed)
        return view(load(uid), private=True)

    @r.post("/v1/updates/{uid}/submit")
    def submit(uid: str, sess: Session = Depends(require_user)):
        db = ctx.need_db()
        u = load(uid)
        role = authz.check(sess, u["company_id"])
        n = db.exec("UPDATE studio.updates SET status='pending_approval', reason=NULL, error=NULL, updated_at=now() "
                    "WHERE id=%s AND status IN ('draft','rejected')", (uid,))
        if not n:
            raise HTTPException(409, f"update is {u['status']}, not a draft")
        audit(sess, role, "update_submitted", u["ticker"], company_id=u["company_id"], update_id=uid)
        return view(load(uid), private=True)

    # -------------------------------------------------------------- approval (platform admin)
    @r.post("/v1/admin/updates/{uid}/approve", status_code=202)
    def approve(uid: str, sess: Session = Depends(require_admin)):
        db = ctx.need_db()
        issuer = ctx.need_issuer()
        row = db.one("WITH prev AS (SELECT id, status FROM studio.updates WHERE id=%s FOR UPDATE) "
                     "UPDATE studio.updates u SET status='publishing', approved_by=%s, error=NULL, updated_at=now() "
                     "FROM prev WHERE u.id = prev.id AND u.status IN ('pending_approval','failed') "
                     "RETURNING u.*, prev.status AS previous", (uid, sess.actor))
        if not row:
            u = load(uid)
            raise HTTPException(409, f"update is {u['status']}, not waiting for approval")
        c = db.one("SELECT * FROM studio.companies WHERE id=%s", (row["company_id"],))
        h = ud.content_hash(row, c)
        db.exec("UPDATE studio.updates SET content_hash=%s WHERE id=%s", (h, uid))
        audit(sess, "platform_admin", "update_approved", c["ticker"], company_id=c["id"], update_id=uid,
              content_hash=h, previous=row["previous"])
        try:
            issuer.post("/disclose", {"update_id": uid})
        except IssuerError as e:
            db.exec("UPDATE studio.updates SET status=%s, error=%s, updated_at=now() WHERE id=%s AND status='publishing'",
                    (row["previous"], str(e)[:1000], uid))
            audit(sess, "platform_admin", "update_approved_issuer_error", c["ticker"], update_id=uid,
                  error=str(e)[:300])
            raise HTTPException(502, str(e)) from None
        return {"id": uid, "status": "publishing", "content_hash": h}

    @r.post("/v1/admin/updates/{uid}/reject")
    def reject(uid: str, body: ReasonBody, sess: Session = Depends(require_admin)):
        db = ctx.need_db()
        u = load(uid)
        n = db.exec("UPDATE studio.updates SET status='rejected', reason=%s, updated_at=now() "
                    "WHERE id=%s AND status IN ('pending_approval','failed')",
                    (body.reason.strip() or "rejected by admin", uid))
        if not n:
            raise HTTPException(409, f"update is {u['status']}, not waiting for approval")
        audit(sess, "platform_admin", "update_rejected", u["ticker"], company_id=u["company_id"], update_id=uid,
              reason=body.reason)
        return view(load(uid), private=True)

    # -------------------------------------------------------------- reading
    @r.get("/v1/companies/{tk}/updates")
    def list_updates(tk: str, request: Request):
        db = ctx.need_db()
        c = company(tk)
        sess = session(request)
        mine = can_manage(sess, c["id"])
        if c["status"] not in ONCHAIN_STATUSES and not mine:
            raise HTTPException(404, "unknown ticker")
        rows = db.all("SELECT u.*, c.ticker, c.name AS company_name FROM studio.updates u JOIN studio.companies c "
                      "ON c.id=u.company_id WHERE u.company_id=%s" + ("" if mine else " AND u.status='published'")
                      + " ORDER BY u.period_end DESC, u.created_at DESC LIMIT 100", (c["id"],))
        return {"ticker": c["ticker"], "name": c["name"], "can_manage": mine,
                "updates": [view(x, private=mine) for x in rows]}

    @r.get("/v1/updates/{uid}")
    def get_update(uid: str, request: Request):
        u = load(uid)
        sess = session(request)
        mine = can_manage(sess, u["company_id"])
        if u["status"] != "published" and not mine:
            raise HTTPException(404, "unknown update")
        c = ctx.need_db().one("SELECT * FROM studio.companies WHERE id=%s", (u["company_id"],))
        text = ud.canonical_text(u, c)
        out = view(u, private=mine, canonical=text)
        out["recorded"] = {"chain_id": s.local_chain_id, "tag": "0x" + ud.DISCLOSURE_TAG_HEX,
                           "calldata": ud.disclosure_calldata(u["content_hash"]) if u.get("content_hash") else None}
        return out

    def feed(wallets: list[str]) -> list[dict]:
        low = [w.lower() for w in wallets if w]
        if not low:
            return []
        db = ctx.need_db()
        ids = [x["company_id"] for x in db.all(
            "SELECT company_id FROM studio.holders WHERE lower(wallet) = ANY(%s) AND shares > 0 "
            "UNION SELECT company_id FROM studio.mints WHERE status='minted' AND lower(to_wallet) = ANY(%s) "
            "UNION SELECT company_id FROM studio.transfers WHERE status='done' AND lower(to_wallet) = ANY(%s)",
            (low, low, low))]
        if not ids:
            return []
        rows = db.all("SELECT u.*, c.ticker, c.name AS company_name FROM studio.updates u JOIN studio.companies c "
                      "ON c.id=u.company_id WHERE u.company_id = ANY(%s) AND u.status='published' "
                      "ORDER BY u.published_at DESC NULLS LAST, u.period_end DESC LIMIT 30", (ids,))
        return [view(x) for x in rows]

    @r.get("/v1/me/updates")
    def my_updates(sess: Session = Depends(require_user)):
        return {"updates": feed(acct.account_wallets(ctx.need_db(), sess.account_id, sess.address))}

    @r.get("/v1/demo/updates")
    def demo_updates():
        w = s.demo_holder or s.demo_wallet
        if not w:
            row = ctx.need_db().one("SELECT wallet FROM studio.holders GROUP BY wallet "
                                    "ORDER BY count(DISTINCT company_id) DESC, wallet LIMIT 1")
            w = row["wallet"] if row else ""
        return {"updates": feed([w] if w else []), "demo": True}

    return r
