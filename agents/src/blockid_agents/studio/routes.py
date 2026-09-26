"""Issuance Studio HTTP API (docs/IMPLEMENTATION.md, "HTTP API").

Cookie sessions (`bid_session`), roles `user` / `admin`. Every admin action writes a studio.audit
row. Nothing here signs a transaction: approvals flip a DB status and ask the issuer service to act.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from ..agents import dividend as dividend_agent
from ..agents.site_intake import SiteError, normalize_url
from ..config import Settings
from ..schemas import QualitativeScores, SelfReportedMetrics
from ..tools import captable
from ..tools import ticker as tickers
from ..tools.merkle import build_distribution
from . import metrics
from .auth import (
    COOKIE,
    AuthError,
    LoginThrottle,
    Session,
    Sessions,
    allowed_domains,
    check_password,
    hash_password,
    verify_siwe,
)
from .db import ONCHAIN_STATUSES, LimitError, Studio, jsonable
from .services import ChainReader, IssuerClient, IssuerError

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ request bodies
class Body(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)  # NaN / Infinity never reach maths or SQL


class SiweBody(Body):
    message: str = Field(max_length=4000)
    signature: str = Field(max_length=200)


class LoginBody(Body):
    username: str = Field(max_length=100)
    password: str = Field(max_length=200)


class ChangePasswordBody(Body):
    current: str = Field(max_length=200)
    new: str = Field(max_length=200)


class ValuationBody(Body):
    url: str = Field(max_length=500)
    metrics: SelfReportedMetrics | None = None  # optional founder-provided figures (labelled self-reported)


class DecisionBody(Body):
    approved: bool
    overrides: dict[str, float] | None = None
    reason: str = ""


class HolderIn(Body):
    name: str = Field(max_length=200)
    wallet: str = Field(max_length=64)
    pct: float


class CompanyBody(Body):
    valuation_id: str
    name: str = Field(min_length=1, max_length=200)
    ticker: str = Field(max_length=8)
    share_price_aud: float = 1
    total_shares: int | None = None
    holders: list[HolderIn] = Field(min_length=1, max_length=500)


class ReasonBody(Body):
    reason: str = Field(default="", max_length=1000)


class RevalueBody(Body):
    valuation_aud: float = Field(gt=0)
    note: str = Field(default="", max_length=1000)


class MintBody(Body):
    to_wallet: str = Field(max_length=64)
    holder_name: str = Field(min_length=1, max_length=200)
    shares: int = Field(gt=0, le=10**15)
    reason: str = Field(default="", max_length=1000)


class DividendBody(Body):
    total_maud: float = Field(gt=0, le=10**12)


class IssuerWalletBody(Body):
    address: str = Field(max_length=64)
    label: str = Field(max_length=200)


# ------------------------------------------------------------------ context
@dataclass
class StudioContext:
    settings: Settings
    db: Studio | None
    chain: ChainReader | None = None
    issuer: IssuerClient | None = None
    runner_factory: Callable[[], Any] | None = None
    throttle: LoginThrottle = field(default_factory=LoginThrottle)
    rpc_transport: httpx.AsyncBaseTransport | None = None  # tests
    _runner: Any = None

    @property
    def sessions(self) -> Sessions:
        return Sessions(self.need_db(), self.settings.session_secret, self.settings.session_hours)

    def need_db(self) -> Studio:
        if self.db is None:
            raise HTTPException(503, "studio database not configured")
        try:
            self.db.ensure_schema()
        except Exception as e:
            log.exception("schema")
            raise HTTPException(503, "studio database unavailable") from e
        return self.db

    def runner(self):
        if self._runner is None:
            if self.runner_factory is None:
                raise HTTPException(503, "valuation runner not configured")
            self._runner = self.runner_factory()
        return self._runner

    def need_issuer(self) -> IssuerClient:
        if self.issuer is None:
            raise HTTPException(503, "issuer service not configured")
        return self.issuer


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _client_ip(request: Request) -> str:
    # nginx sets X-Real-IP to $remote_addr (overwrites any client value); the API itself binds to 127.0.0.1
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "?")


# ------------------------------------------------------------------ public JSON-RPC proxy policy
RPC_MAX_BODY = 256 * 1024
RPC_MAX_BATCH = 20
_RPC_ALLOWED = re.compile(r"^(eth|net|web3)_[A-Za-z0-9]+$")
_RPC_DENIED = re.compile(r"^eth_(sign\w*|sendTransaction|accounts|coinbase|mining|hashrate|getWork|submit\w+|"
                         r"subscribe|unsubscribe)$")


def rpc_method_allowed(method: object) -> bool:
    return isinstance(method, str) and bool(_RPC_ALLOWED.match(method)) and not _RPC_DENIED.match(method)


def _rpc_error(id_: object, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _grade(band: str | None) -> str | None:
    return (band or "").strip()[:1].upper() or None


def build_router(ctx: StudioContext) -> APIRouter:
    r = APIRouter()
    s = ctx.settings
    admin_set = {a.lower() for a in s.admin_wallets}
    domains = allowed_domains(s.public_base_url)

    # -------------------------------------------------------------- session dependencies
    def session(request: Request) -> Session | None:
        sid = request.cookies.get(COOKIE)
        if not sid:
            return None
        return ctx.sessions.get(sid)

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

    def set_cookie(resp: Response, sid: str) -> None:
        resp.set_cookie(COOKIE, sid, max_age=s.session_hours * 3600, httponly=True, secure=True, samesite="lax",
                        path="/")

    def audit(sess: Session, action: str, target: Any = None, **detail) -> None:
        ctx.need_db().audit(sess.actor, action, None if target is None else str(target), **detail)

    def require_issuer_wallet(sess: Session) -> None:
        if sess.is_admin:
            return
        w = ctx.need_db().one("SELECT status FROM studio.issuer_wallets WHERE lower(address)=lower(%s)",
                              (sess.address or "",))
        if not w or w["status"] != "active":
            raise HTTPException(403, "this wallet is not an approved issuer; ask an admin to grant the role")

    def is_owner(sess: Session, owner: str | None) -> bool:
        return bool(owner) and owner.lower() == sess.actor.lower()

    # -------------------------------------------------------------- auth
    @r.get("/v1/auth/nonce")
    def nonce():
        return {"nonce": ctx.sessions.issue_nonce()}

    @r.post("/v1/auth/siwe")
    def siwe(body: SiweBody, response: Response):
        sessions = ctx.sessions
        try:
            msg = verify_siwe(body.message, body.signature, domains, dev=s.studio_dev)
        except AuthError as e:
            raise HTTPException(e.status, e.detail) from None
        if not sessions.consume_nonce(msg.nonce):
            raise HTTPException(401, "nonce unknown, used or expired")
        role = "admin" if msg.address.lower() in admin_set else "user"
        set_cookie(response, sessions.create(role, address=msg.address))
        if role == "admin":
            ctx.need_db().audit(msg.address, "login_siwe", msg.address, chain_id=msg.chain_id)
        return {"address": msg.address, "role": role}

    @r.post("/v1/auth/login")
    def login(body: LoginBody, request: Request, response: Response):
        db = ctx.need_db()
        ip = _client_ip(request)
        if ctx.throttle.blocked(ip):
            raise HTTPException(429, "too many failed logins; try again in 15 minutes")
        row = db.one("SELECT * FROM studio.admin_users WHERE username=%s", (body.username,))
        if not check_password(body.password, row["password_hash"] if row else None):
            ctx.throttle.fail(ip)
            raise HTTPException(401, "wrong username or password")
        ctx.throttle.reset(ip)
        set_cookie(response, ctx.sessions.create("admin", username=row["username"]))
        db.audit(row["username"], "login_password", row["username"], ip=ip)
        return {"role": "admin", "must_change": bool(row["must_change"])}

    @r.post("/v1/auth/change-password")
    def change_password(body: ChangePasswordBody, request: Request, sess: Session = Depends(require_user)):
        db = ctx.need_db()
        if not sess.username or not sess.is_admin:
            raise HTTPException(403, "password sessions only")
        ip = _client_ip(request)
        if ctx.throttle.blocked(ip):
            raise HTTPException(429, "too many failed attempts; try again in 15 minutes")
        row = db.one("SELECT * FROM studio.admin_users WHERE username=%s", (sess.username,))
        if not row or not check_password(body.current, row["password_hash"]):
            ctx.throttle.fail(ip)
            raise HTTPException(401, "current password is wrong")
        if len(body.new) < 10:
            raise HTTPException(422, "new password must be at least 10 characters")
        if body.new == body.current:
            raise HTTPException(422, "new password must differ from the current one")
        db.exec("UPDATE studio.admin_users SET password_hash=%s, must_change=false WHERE username=%s",
                (hash_password(body.new), sess.username))
        db.audit(sess.username, "change_password", sess.username)
        return {"ok": True}

    @r.post("/v1/auth/logout")
    def logout(request: Request, response: Response):
        ctx.sessions.delete(request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        return {"ok": True}

    @r.get("/v1/auth/me")
    def me(sess: Session = Depends(require_user)):
        out: dict[str, Any] = {"role": sess.role}
        if sess.address:
            out["address"] = sess.address
        if sess.username:
            out["username"] = sess.username
            out["must_change"] = sess.must_change
        if sess.address:
            db = ctx.need_db()
            w = db.one("SELECT status FROM studio.issuer_wallets WHERE lower(address)=lower(%s)", (sess.address,))
            out["issuer"] = sess.is_admin or bool(w and w["status"] == "active")
        else:
            out["issuer"] = sess.is_admin
        return out

    # -------------------------------------------------------------- valuations
    def valuation_view(row: dict, *, evidence: bool = False) -> dict:
        res = row.get("result") or {}
        out = {
            "id": row["id"], "url": row["url"], "status": row["status"], "steps": row.get("steps") or [],
            "counters": res.get("counters") or {"pages": 0, "competitors": 0, "sources": 0},
            "profile": res.get("profile"), "competitors": res.get("competitors") or [], "market": res.get("market"),
            "svi": res.get("svi"), "warnings": res.get("warnings") or [], "error": row.get("error"),
            "self_reported": row.get("self_reported") or res.get("self_reported") or None,
            "requested_by": row.get("requested_by"),
            "searches": res.get("searches") or [], "llm_providers_used": res.get("llm_providers_used") or [],
            "created_at": row.get("created_at"), "updated_at": row.get("updated_at"),
        }
        if evidence:
            out["evidence"] = res.get("evidence") or []
        return out

    def load_valuation(vid: str, sess: Session) -> dict:
        row = ctx.need_db().get_valuation(vid)
        if not row:
            raise HTTPException(404, "unknown valuation")
        if not (sess.is_admin or is_owner(sess, row["requested_by"])):
            raise HTTPException(403, "not your valuation")
        return row

    @r.post("/v1/studio/valuations", status_code=202)
    def create_valuation(body: ValuationBody, sess: Session = Depends(require_user)):
        db = ctx.need_db()
        try:
            url = normalize_url(body.url)
        except SiteError as e:
            raise HTTPException(422, str(e)) from None
        host = urlparse(url).hostname or ""
        try:
            ipaddress.ip_address(host)
            raise HTTPException(422, "use the company's domain name, not an IP address")
        except ValueError:
            pass
        if host in ("localhost",) or host.endswith((".local", ".internal", ".localhost")):
            raise HTTPException(422, "not a public website")
        self_reported = body.metrics.model_dump(exclude_none=True) if body.metrics else None
        try:  # admins: no per-wallet or daily cap, but the queue-depth cap still applies
            vid = db.create_valuation_limited(
                url, sess.actor, per_wallet=None if sess.is_admin else s.valuations_per_day,
                global_per_day=None if sess.is_admin else s.valuations_global_per_day,
                max_active=s.valuations_max_active, self_reported=self_reported or None)
        except LimitError as e:
            raise HTTPException(429, str(e)) from None
        if sess.is_admin:
            audit(sess, "valuation_requested", vid, url=url, self_reported=bool(self_reported))
        return {"id": vid}

    @r.get("/v1/studio/valuations")
    def my_valuations(sess: Session = Depends(require_user)):
        db = ctx.need_db()
        if sess.is_admin:
            rows = db.all("SELECT * FROM studio.valuations ORDER BY created_at DESC LIMIT 100")
        else:
            rows = db.all("SELECT * FROM studio.valuations WHERE lower(requested_by)=lower(%s) "
                          "ORDER BY created_at DESC LIMIT 100", (sess.actor,))
        return [valuation_view(x) for x in rows]

    @r.get("/v1/studio/valuations/{vid}")
    def get_valuation(vid: str, sess: Session = Depends(require_user)):
        return valuation_view(load_valuation(vid, sess))

    @r.get("/v1/studio/valuations/{vid}/evidence")
    def get_evidence(vid: str, sess: Session = Depends(require_user)):
        row = load_valuation(vid, sess)
        out = []
        for e in (row.get("result") or {}).get("evidence") or []:
            at = e.get("retrieved_at")
            if isinstance(at, (int, float)):
                at = datetime.fromtimestamp(at, timezone.utc).isoformat()
            out.append({"url": e["url"], "title": e.get("title", ""), "snippet": e.get("snippet", ""),
                        "retrieved_at": at, "kind": e.get("kind", "web")})
        return out

    @r.post("/v1/studio/valuations/{vid}/decision")
    def decide(vid: str, body: DecisionBody, sess: Session = Depends(require_admin)):
        db = ctx.need_db()
        row = db.get_valuation(vid)
        if not row:
            raise HTTPException(404, "unknown valuation")
        if row["status"] != "waiting_approval":
            raise HTTPException(409, f"valuation is {row['status']}, not waiting_approval")
        overrides = body.overrides or {}
        allowed = set(QualitativeScores.model_fields)
        bad = [k for k, v in overrides.items() if k not in allowed or not 0 <= v <= 100]
        if bad:
            raise HTTPException(422, f"overrides must be {sorted(allowed)} with scores 0-100; bad: {bad}")
        try:
            ctx.runner().decide(vid, body.approved, overrides, sess.actor)
        except HTTPException:
            raise
        except Exception as e:
            log.exception("decision failed")
            raise HTTPException(500, f"decision failed: {e}") from e
        audit(sess, "valuation_approved" if body.approved else "valuation_rejected", vid,
              overrides=overrides, reason=body.reason)
        return valuation_view(db.get_valuation(vid))

    # -------------------------------------------------------------- tickers + companies (studio)
    @r.get("/v1/studio/tickers/suggest")
    def suggest(name: str = Query(min_length=1, max_length=200), sess: Session = Depends(require_user)):
        taken = [x["ticker"] for x in ctx.need_db().all("SELECT ticker FROM studio.companies")]
        return {"candidates": tickers.suggest(name, taken)}

    def company_row(cid: int) -> dict:
        row = ctx.need_db().one("SELECT * FROM studio.companies WHERE id=%s", (cid,))
        if not row:
            raise HTTPException(404, "unknown company")
        return row

    def company_by_ticker(tk: str) -> dict:
        row = ctx.need_db().one("SELECT * FROM studio.companies WHERE ticker=%s", (tk.upper(),))
        if not row:
            raise HTTPException(404, "unknown ticker")
        return row

    def company_view(c: dict) -> dict:
        db = ctx.need_db()
        hs = db.all("SELECT name, wallet, pct, shares FROM studio.holders WHERE company_id=%s ORDER BY id", (c["id"],))
        out = jsonable({k: v for k, v in c.items()})
        out["grade"] = _grade(c.get("grade"))
        out["holders"] = jsonable(hs)
        return out

    @r.post("/v1/studio/companies", status_code=201)
    def create_company(body: CompanyBody, sess: Session = Depends(require_user)):
        db = ctx.need_db()
        v = db.get_valuation(body.valuation_id)
        if not v:
            raise HTTPException(404, "unknown valuation")
        if not (sess.is_admin or is_owner(sess, v["requested_by"])):
            raise HTTPException(403, "not your valuation")
        if v["status"] != "approved":
            raise HTTPException(409, "valuation must be approved by an admin first")
        svi = (v.get("result") or {}).get("svi") or {}
        mid = float(svi.get("valuation_mid_aud") or 0)
        if mid <= 0:
            raise HTTPException(409, "valuation has no mid value")
        tk = body.ticker.strip().upper()
        if not tickers.valid(tk):
            raise HTTPException(422, "ticker must be 3 letters A-Z and not reserved")
        if not 0 < body.share_price_aud <= 1_000_000:
            raise HTTPException(422, "share_price_aud must be > 0")
        total = body.total_shares if body.total_shares is not None else round(mid / body.share_price_aud)
        if not 0 < total <= 10**15:
            raise HTTPException(422, "total_shares out of range")
        try:
            alloc = captable.allocate([h.model_dump() for h in body.holders], total)
        except captable.CapTableError as e:
            raise HTTPException(422, str(e)) from None
        if db.one("SELECT id FROM studio.companies WHERE valuation_id=%s AND status NOT IN ('rejected','failed')",
                  (v["id"],)):
            raise HTTPException(409, "a company already exists for this valuation")
        try:
            with db.tx() as c:
                row = c.execute(
                    "INSERT INTO studio.companies(ticker,name,website,valuation_id,svi,grade,valuation_aud,"
                    "share_price_aud,total_shares,status,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s) "
                    "RETURNING *",
                    (tk, body.name.strip(), v["url"], v["id"], svi.get("index"), _grade(svi.get("band")),
                     Decimal(str(mid)), Decimal(str(body.share_price_aud)), total, sess.actor),
                ).fetchone()
                for h in alloc:
                    c.execute("INSERT INTO studio.holders(company_id,name,wallet,pct,shares) VALUES (%s,%s,%s,%s,%s)",
                              (row["id"], h["name"], h["wallet"], Decimal(str(h["pct"])), h["shares"]))
        except UniqueViolation:
            raise HTTPException(409, f"ticker {tk} is taken") from None
        if sess.is_admin:
            audit(sess, "company_created", tk, company_id=row["id"])
        return company_view(row)

    @r.get("/v1/studio/companies")
    def my_companies(sess: Session = Depends(require_user)):
        db = ctx.need_db()
        rows = db.all("SELECT * FROM studio.companies WHERE lower(created_by)=lower(%s) ORDER BY id DESC",
                      (sess.actor,))
        return [company_view(c) for c in rows]

    @r.post("/v1/studio/companies/{cid}/submit")
    def submit_company(cid: int, sess: Session = Depends(require_user)):
        db = ctx.need_db()
        c = company_row(cid)
        if not (sess.is_admin or is_owner(sess, c["created_by"])):
            raise HTTPException(403, "not your company")
        require_issuer_wallet(sess)
        if c["status"] != "draft":
            raise HTTPException(409, f"company is {c['status']}, not draft")
        db.exec("UPDATE studio.companies SET status='pending_issue', error=NULL, updated_at=now() WHERE id=%s", (cid,))
        audit(sess, "company_submitted", c["ticker"], company_id=cid)
        return company_view(company_row(cid))

    # -------------------------------------------------------------- admin: approvals + lifecycle
    @r.get("/v1/admin/approvals")
    def approvals(sess: Session = Depends(require_admin)):
        db = ctx.need_db()
        vals = [valuation_view(x) for x in db.all(
            "SELECT * FROM studio.valuations WHERE status='waiting_approval' ORDER BY created_at")]
        comps = [company_view(c) for c in db.all(
            "SELECT * FROM studio.companies WHERE status IN ('pending_issue','issued') ORDER BY updated_at")]
        mints = db.all("SELECT m.*, c.ticker, c.name AS company_name FROM studio.mints m "
                       "JOIN studio.companies c ON c.id=m.company_id WHERE m.status='pending' ORDER BY m.created_at")
        divs = db.all("SELECT d.id, d.company_id, d.total_units, d.merkle_root, d.status, d.requested_by, d.created_at,"
                      " jsonb_array_length(COALESCE(d.claims,'[]'::jsonb)) AS holders, c.ticker, c.name AS company_name"
                      " FROM studio.dividends d JOIN studio.companies c ON c.id=d.company_id"
                      " WHERE d.status='pending' ORDER BY d.created_at")
        return {"valuations": vals, "companies": comps, "mints": jsonable(mints),
                "dividends": [{**jsonable(d), "total_maud": int(d["total_units"]) / 1e6} for d in divs]}

    @r.get("/v1/admin/companies")
    def all_companies(sess: Session = Depends(require_admin)):
        return [company_view(c) for c in ctx.need_db().all("SELECT * FROM studio.companies ORDER BY id DESC")]

    def transition(cid: int, where: str, new_status: str, path: str, sess: Session, action: str) -> dict:
        """Atomic status flip (single UPDATE guarded by `where`), then ask the issuer; revert on failure."""
        db = ctx.need_db()
        issuer = ctx.need_issuer()
        row = db.one(
            "WITH prev AS (SELECT id, status FROM studio.companies WHERE id=%s FOR UPDATE) "
            "UPDATE studio.companies c SET status=%s, error=NULL, updated_at=now() FROM prev "
            f"WHERE c.id = prev.id AND ({where}) RETURNING c.ticker, prev.status AS previous",
            (cid, new_status))
        if not row:
            cur = db.one("SELECT status FROM studio.companies WHERE id=%s", (cid,))
            if not cur:
                raise HTTPException(404, "unknown company")
            raise HTTPException(409, f"company is {cur['status']}")
        audit(sess, action, row["ticker"], company_id=cid, previous=row["previous"])
        try:
            issuer.post(path, {"company_id": cid})
        except IssuerError as e:
            db.exec("UPDATE studio.companies SET status=%s, error=%s, updated_at=now() WHERE id=%s AND status=%s",
                    (row["previous"], str(e)[:1000], cid, new_status))
            audit(sess, action + "_issuer_error", row["ticker"], error=str(e)[:300])
            raise HTTPException(502, str(e)) from None
        return {"id": cid, "ticker": row["ticker"], "status": new_status}

    @r.post("/v1/admin/companies/{cid}/approve-issue", status_code=202)
    def approve_issue(cid: int, sess: Session = Depends(require_admin)):
        return transition(cid, "c.status = 'pending_issue' OR (c.status = 'failed' AND c.local_token IS NULL)",
                          "issuing", "/issue", sess, "approve_issue")

    @r.post("/v1/admin/companies/{cid}/approve-anchor", status_code=202)
    def approve_anchor(cid: int, sess: Session = Depends(require_admin)):
        return transition(cid, "c.status IN ('issued', 'pending_anchor') "
                                "OR (c.status = 'failed' AND c.local_token IS NOT NULL)",
                          "anchoring", "/anchor", sess, "approve_anchor")

    @r.post("/v1/admin/companies/{cid}/reject")
    def reject_company(cid: int, body: ReasonBody, sess: Session = Depends(require_admin)):
        db = ctx.need_db()
        c = company_row(cid)
        if c["status"] not in ("draft", "pending_issue", "issued", "pending_anchor", "failed"):
            raise HTTPException(409, f"company is {c['status']}")
        db.exec("UPDATE studio.companies SET status='rejected', error=%s, updated_at=now() WHERE id=%s",
                (body.reason or "rejected by admin", cid))
        db.exec("INSERT INTO studio.events(company_id,kind,data) VALUES (%s,'rejected',%s)",
                (cid, Jsonb({"reason": body.reason, "by": sess.actor, "previous": c["status"]})))
        audit(sess, "company_rejected", c["ticker"], reason=body.reason, previous=c["status"])
        return company_view(company_row(cid))

    @r.post("/v1/admin/companies/{cid}/revalue", status_code=202)
    def revalue(cid: int, body: RevalueBody, sess: Session = Depends(require_admin)):
        db = ctx.need_db()
        c = company_row(cid)
        if c["status"] not in ONCHAIN_STATUSES or not c.get("local_token"):
            raise HTTPException(409, "only issued companies can be revalued")
        val = Decimal(str(body.valuation_aud))
        mark = (val / Decimal(int(c["total_shares"]))).quantize(Decimal("0.00000001"))
        prev = db.one("SELECT mark_aud FROM studio.marks WHERE company_id=%s ORDER BY at DESC, id DESC LIMIT 1", (cid,))
        with db.tx() as tx:
            tx.execute("UPDATE studio.companies SET valuation_aud=%s, updated_at=now() WHERE id=%s", (val, cid))
            m = tx.execute("INSERT INTO studio.marks(company_id,valuation_aud,mark_aud,source,ref) "
                           "VALUES (%s,%s,%s,'revaluation',%s) RETURNING id",
                           (cid, val, mark, body.note[:200])).fetchone()
            tx.execute("INSERT INTO studio.events(company_id,kind,chain,data) VALUES (%s,'revalued',NULL,%s)",
                       (cid, Jsonb(jsonable({"valuation_aud": val, "mark_aud": mark, "note": body.note,
                                             "by": sess.actor,
                                             "previous_mark_aud": prev["mark_aud"] if prev else None,
                                             "mark_id": m["id"]}))))
        audit(sess, "company_revalued", c["ticker"], valuation_aud=float(val), mark_aud=float(mark), note=body.note)
        issuer_status = "queued"
        try:
            ctx.need_issuer().post("/revalue", {"company_id": cid})
        except (IssuerError, HTTPException) as e:
            issuer_status = f"error: {getattr(e, 'detail', e)}"
        return {"id": cid, "ticker": c["ticker"], "valuation_aud": float(val), "mark_aud": float(mark),
                "issuer": issuer_status}

    # -------------------------------------------------------------- public company data
    def load_marks(ids: list[int] | None = None) -> dict[int, list[dict]]:
        db = ctx.need_db()
        rows = db.all("SELECT company_id, at, valuation_aud, mark_aud, source FROM studio.marks "
                      + ("WHERE company_id = ANY(%s) " if ids is not None else "") + "ORDER BY at, id",
                      (ids,) if ids is not None else None)
        out: dict[int, list[dict]] = {}
        for m in rows:
            out.setdefault(m["company_id"], []).append(m)
        return out

    def holder_counts() -> dict[int, int]:
        return {x["company_id"]: int(x["n"]) for x in ctx.need_db().all(
            "SELECT company_id, count(*) AS n FROM studio.holders GROUP BY company_id")}

    @r.get("/v1/companies")
    def list_companies():
        db = ctx.need_db()
        rows = db.all("SELECT * FROM studio.companies WHERE status = ANY(%s) ORDER BY valuation_aud DESC",
                      (list(ONCHAIN_STATUSES),))
        marks, holders, now = load_marks([c["id"] for c in rows]), holder_counts(), _utcnow()
        return [metrics.company_summary(c, marks.get(c["id"], []), holders.get(c["id"], 0), now) for c in rows]

    def cap_table(c: dict) -> tuple[list[dict], str, int | None]:
        db = ctx.need_db()
        hs = db.all("SELECT name, wallet, shares FROM studio.holders WHERE company_id=%s ORDER BY id", (c["id"],))
        extra = db.all("SELECT DISTINCT ON (lower(to_wallet)) to_wallet AS wallet, holder_name AS name "
                       "FROM studio.mints "
                       "WHERE company_id=%s AND status='minted'", (c["id"],))
        names = {h["wallet"].lower(): h["name"] for h in hs}

        def db_rows() -> list[dict]:
            return [{"name": h["name"], "wallet": h["wallet"], "shares": int(h["shares"])} for h in hs]

        wallets = [h["wallet"] for h in hs] + [e["wallet"] for e in extra if e["wallet"].lower() not in names]
        for e in extra:
            names.setdefault(e["wallet"].lower(), e["name"])
        if c.get("local_token") and ctx.chain is not None:
            try:
                bal = ctx.chain.balances(c["local_token"], wallets)
                block = ctx.chain.block_number()
                rows = [{"name": names.get(w.lower(), ""), "wallet": w, "shares": int(b)} for w, b in bal.items()]
                source = "chain"
            except Exception as e:  # RPC down -> DB snapshot
                log.warning("cap table from chain failed: %s", e)
                rows, source, block = db_rows(), "db", None
        else:
            rows, source, block = db_rows(), "db", None
        total = sum(x["shares"] for x in rows)
        for x in rows:
            x["pct"] = round(x["shares"] * 100 / total, 4) if total else 0
        rows = [x for x in rows if x["shares"] > 0 or source == "db"]
        return sorted(rows, key=lambda x: -x["shares"]), source, block

    @r.get("/v1/companies/{tk}")
    def company_detail(tk: str, request: Request):
        db = ctx.need_db()
        c = company_by_ticker(tk)
        if c["status"] not in ONCHAIN_STATUSES:
            sess = session(request)
            if not sess or not (sess.is_admin or is_owner(sess, c["created_by"])):
                raise HTTPException(404, "unknown ticker")
        marks = load_marks([c["id"]]).get(c["id"], [])
        table, source, block = cap_table(c)
        out = metrics.company_summary(c, marks, len(table), _utcnow())
        events = db.all("SELECT kind, at, chain, tx_hash, block, data FROM studio.events WHERE company_id=%s "
                        "ORDER BY at DESC, id DESC LIMIT 200", (c["id"],))
        for e in events:
            e["text"] = metrics.event_text(e)
        out.update({
            "created_by": c["created_by"], "error": c.get("error"), "valuation_id": c.get("valuation_id"),
            "cap_table": table, "cap_table_source": source, "cap_table_block": block,
            "events": jsonable(events),
            "marks": [{"at": m["at"], "mark_aud": metrics.f(m["mark_aud"]), "source": m["source"],
                       "valuation_aud": metrics.f(m["valuation_aud"])} for m in marks],
            "local": {"chain_id": s.local_chain_id, "registry": c.get("local_registry"), "token": c.get("local_token"),
                      "distributor": c.get("local_distributor"), "block": c.get("local_block")},
            "hoodi": {"chain_id": s.hoodi_chain_id, "registry": c.get("hoodi_registry"), "token": c.get("hoodi_token"),
                      "anchor_tx": c.get("hoodi_anchor_tx"), "merkle_root": c.get("merkle_root"),
                      "block": c.get("anchored_block"), "anchored_at": c.get("anchored_at")},
        })
        return out

    # -------------------------------------------------------------- mints + dividends
    def owner_or_admin(c: dict, sess: Session) -> None:
        """Mint/dividend requests: company owner or admin, AND (admin or an active issuer wallet)."""
        if not (sess.is_admin or is_owner(sess, c["created_by"])):
            raise HTTPException(403, "only the company owner or an admin can do this")
        if sess.is_admin and sess.must_change:
            raise HTTPException(403, "password change required")
        require_issuer_wallet(sess)

    @r.post("/v1/companies/{tk}/mints", status_code=201)
    def request_mint(tk: str, body: MintBody, sess: Session = Depends(require_user)):
        db = ctx.need_db()
        c = company_by_ticker(tk)
        owner_or_admin(c, sess)
        if c["status"] not in ONCHAIN_STATUSES or not c.get("local_token"):
            raise HTTPException(409, "company is not issued yet")
        try:
            wallet = captable.checksum(body.to_wallet)
        except captable.CapTableError as e:
            raise HTTPException(422, str(e)) from None
        row = db.one("INSERT INTO studio.mints(company_id,to_wallet,holder_name,shares,reason,status,requested_by) "
                     "VALUES (%s,%s,%s,%s,%s,'pending',%s) RETURNING *",
                     (c["id"], wallet, body.holder_name.strip(), body.shares, body.reason, sess.actor))
        db.exec("INSERT INTO studio.events(company_id,kind,data) VALUES (%s,'mint_requested',%s)",
                (c["id"], Jsonb({"mint_id": row["id"], "wallet": wallet, "name": body.holder_name.strip(),
                                 "shares": body.shares, "by": sess.actor})))
        audit(sess, "mint_requested", c["ticker"], mint_id=row["id"], shares=body.shares, wallet=wallet)
        return jsonable(row)

    def approve_item(table: str, item_id: int, path: str, key: str, sess: Session, action: str) -> dict:
        """pending (or failed, for a retry) -> approved atomically; the issuer executes only 'approved' rows and
        checks the chain before re-sending a retried mint/dividend."""
        db = ctx.need_db()
        issuer = ctx.need_issuer()
        row = db.one(f"WITH prev AS (SELECT id, status FROM studio.{table} WHERE id=%s FOR UPDATE) "
                     f"UPDATE studio.{table} t SET status='approved' FROM prev "
                     "WHERE t.id = prev.id AND t.status IN ('pending', 'failed') "
                     "RETURNING t.id, t.company_id, prev.status AS previous", (item_id,))
        if not row:
            exists = db.one(f"SELECT status FROM studio.{table} WHERE id=%s", (item_id,))
            if not exists:
                raise HTTPException(404, "unknown id")
            raise HTTPException(409, f"status is {exists['status']}")
        audit(sess, action, item_id, company_id=row["company_id"], previous=row["previous"])
        try:
            issuer.post(path, {key: item_id})
        except IssuerError as e:
            db.exec(f"UPDATE studio.{table} SET status=%s WHERE id=%s AND status='approved'",
                    (row["previous"], item_id))
            audit(sess, action + "_issuer_error", item_id, error=str(e)[:300])
            raise HTTPException(502, str(e)) from None
        return {"id": item_id, "status": "approved"}

    def reject_item(table: str, item_id: int, sess: Session, action: str, reason: str) -> dict:
        db = ctx.need_db()
        row = db.one(f"UPDATE studio.{table} SET status='rejected' WHERE id=%s AND status='pending' RETURNING id",
                     (item_id,))
        if not row:
            raise HTTPException(409, "not pending")
        audit(sess, action, item_id, reason=reason)
        return {"id": item_id, "status": "rejected"}

    @r.post("/v1/admin/mints/{mid}/approve", status_code=202)
    def approve_mint(mid: int, sess: Session = Depends(require_admin)):
        return approve_item("mints", mid, "/mint", "mint_id", sess, "mint_approved")

    @r.post("/v1/admin/mints/{mid}/reject")
    def reject_mint(mid: int, body: ReasonBody, sess: Session = Depends(require_admin)):
        return reject_item("mints", mid, sess, "mint_rejected", body.reason)

    @r.post("/v1/companies/{tk}/dividends", status_code=201)
    def request_dividend(tk: str, body: DividendBody, sess: Session = Depends(require_user)):
        db = ctx.need_db()
        c = company_by_ticker(tk)
        owner_or_admin(c, sess)
        if c["status"] not in ONCHAIN_STATUSES or not c.get("local_token"):
            raise HTTPException(409, "company is not issued yet")
        try:
            units = int(Decimal(str(body.total_maud)) * 1_000_000)
        except InvalidOperation:
            raise HTTPException(422, "bad total_maud") from None
        table, source, block = cap_table(c)
        names = {x["wallet"].lower(): x["name"] for x in table}
        try:
            alloc, remainder = dividend_agent.allocate({x["wallet"]: x["shares"] for x in table}, units)
        except ValueError as e:
            raise HTTPException(409, str(e)) from None
        if not alloc:
            raise HTTPException(422, "amount too small to pay any holder")
        dist = build_distribution(alloc)
        claims = [{"wallet": x["wallet"], "name": names.get(x["wallet"].lower(), ""), "amount": alloc[x["wallet"]],
                   "proof": dist.claims[x["wallet"].lower()]["proof"]} for x in table if x["wallet"] in alloc]
        row = db.one("INSERT INTO studio.dividends(company_id,total_units,merkle_root,claims,status,requested_by) "
                     "VALUES (%s,%s,%s,%s,'pending',%s) RETURNING *",
                     (c["id"], dist.total, dist.root, Jsonb(claims), sess.actor))
        audit(sess, "dividend_requested", c["ticker"], dividend_id=row["id"], total_units=dist.total)
        return {**jsonable(row), "total_maud": dist.total / 1e6, "remainder_units": remainder,
                "balances_source": source, "record_block": block, "holders": len(claims)}

    @r.post("/v1/admin/dividends/{did}/approve", status_code=202)
    def approve_dividend(did: int, sess: Session = Depends(require_admin)):
        return approve_item("dividends", did, "/dividend", "dividend_id", sess, "dividend_approved")

    @r.post("/v1/admin/dividends/{did}/reject")
    def reject_dividend(did: int, body: ReasonBody, sess: Session = Depends(require_admin)):
        return reject_item("dividends", did, sess, "dividend_rejected", body.reason)

    # -------------------------------------------------------------- platform stats
    @r.get("/v1/platform/stats")
    def stats():
        db = ctx.need_db()
        companies = db.all("SELECT * FROM studio.companies")
        events = db.all("SELECT e.* FROM studio.events e JOIN studio.companies c ON c.id = e.company_id "
                        "WHERE c.status = ANY(%s) ORDER BY e.at DESC, e.id DESC LIMIT 30", (list(ONCHAIN_STATUSES),))
        mints = db.all("SELECT company_id, shares, status, created_at FROM studio.mints")
        divs = db.all("SELECT company_id, total_units, status FROM studio.dividends")
        block = None
        if ctx.chain is not None:
            try:
                block = ctx.chain.block_number()
            except Exception:
                block = None
        return metrics.platform_stats(companies, load_marks(), holder_counts(), events, mints, divs, block)

    # -------------------------------------------------------------- issuer wallets, audit, wallets
    @r.get("/v1/admin/issuer-wallets")
    def list_issuer_wallets(sess: Session = Depends(require_admin)):
        return ctx.need_db().all("SELECT * FROM studio.issuer_wallets ORDER BY granted_at DESC NULLS LAST")

    @r.post("/v1/admin/issuer-wallets", status_code=201)
    def add_issuer_wallet(body: IssuerWalletBody, sess: Session = Depends(require_admin)):
        try:
            addr = captable.checksum(body.address)
        except captable.CapTableError as e:
            raise HTTPException(422, str(e)) from None
        if not body.label.strip():
            raise HTTPException(422, "label is required")
        row = ctx.need_db().one(
            "INSERT INTO studio.issuer_wallets(address,label,status,granted_by,granted_at) "
            "VALUES (%s,%s,'active',%s,now()) ON CONFLICT (address) DO UPDATE SET label=EXCLUDED.label, "
            "status='active', granted_by=EXCLUDED.granted_by, granted_at=now(), revoked_at=NULL RETURNING *",
            (addr, body.label.strip(), sess.actor))
        audit(sess, "issuer_wallet_granted", addr, label=body.label.strip())
        return row

    @r.post("/v1/admin/issuer-wallets/{address}/revoke")
    def revoke_issuer_wallet(address: str, sess: Session = Depends(require_admin)):
        row = ctx.need_db().one("UPDATE studio.issuer_wallets SET status='revoked', revoked_at=now() "
                                "WHERE lower(address)=lower(%s) RETURNING *", (address,))
        if not row:
            raise HTTPException(404, "unknown issuer wallet")
        audit(sess, "issuer_wallet_revoked", row["address"])
        return row

    @r.get("/v1/admin/audit")
    def audit_log(sess: Session = Depends(require_admin)):
        return ctx.need_db().all("SELECT * FROM studio.audit ORDER BY at DESC, id DESC LIMIT 200")

    @r.get("/v1/admin/wallets")
    def wallets(sess: Session = Depends(require_admin)):
        from eth_utils import to_checksum_address

        health = ctx.issuer.health() if ctx.issuer else {"ok": False, "error": "issuer not configured"}
        blank = {"address": None, "local_balance": None, "hoodi_balance": None}
        return {
            "admins": [to_checksum_address(a) for a in s.admin_wallets if len(a) == 42],
            "issuer": health.get("issuer") or blank,
            "relayer": health.get("relayer") or blank,
            "issuer_health": {k: v for k, v in health.items() if k not in ("issuer", "relayer")},
        }

    # -------------------------------------------------------------- public BlockID Chain JSON-RPC (read + raw tx)
    @r.post("/v1/rpc")
    async def rpc(request: Request):
        """Proxy to LOCAL_RPC_URL. Only eth_* (minus signing / node-account methods), net_*, web3_*; single or
        batch <= 20; body <= 256 KB; 10 s upstream timeout. debug_/txpool_/personal_/admin_/miner_ are refused."""
        if int(request.headers.get("content-length") or 0) > RPC_MAX_BODY:
            return JSONResponse(_rpc_error(None, -32600, "request too large"), status_code=413)
        raw = b""
        async for chunk in request.stream():
            raw += chunk
            if len(raw) > RPC_MAX_BODY:
                return JSONResponse(_rpc_error(None, -32600, "request too large"), status_code=413)
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return JSONResponse(_rpc_error(None, -32700, "parse error"), status_code=400)
        batch = isinstance(payload, list)
        items = payload if batch else [payload]
        if not items or len(items) > RPC_MAX_BATCH or not all(isinstance(x, dict) for x in items):
            return JSONResponse(_rpc_error(None, -32600, f"invalid request (batch of 1-{RPC_MAX_BATCH} objects)"),
                                status_code=400)
        allowed = [x for x in items if rpc_method_allowed(x.get("method"))]
        denied = [_rpc_error(x.get("id"), -32601, f"method {str(x.get('method'))[:64]!r} not allowed")
                  for x in items if not rpc_method_allowed(x.get("method"))]
        upstream: list = []
        if allowed:
            try:
                async with httpx.AsyncClient(timeout=10, transport=ctx.rpc_transport, trust_env=False) as client:
                    resp = await client.post(s.local_rpc_url, json=allowed if batch else allowed[0])
                out = resp.json()
            except (httpx.HTTPError, ValueError) as e:
                log.warning("rpc upstream error: %s", e)
                return JSONResponse(_rpc_error(None, -32603, "upstream RPC unavailable"), status_code=502)
            upstream = out if isinstance(out, list) else [out]
        if not batch:
            return upstream[0] if upstream else denied[0]
        return upstream + denied

    return r
