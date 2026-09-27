"""Simulated share offering (docs/UPGRADE-INVESTOR-PLAN.md 3f, testnet MVP). No money moves; no contract changes.

A company owner / manager (or a platform admin) sets the terms of one offering at a time — price per share (default:
the latest approved price), shares offered, minimum to raise, most shares per investor, closing date, use of funds —
and sends it for approval. The information pack (latest valuation with range / confidence, the last 3 published
updates, the share register before / after, standard risks) is assembled by code at submit time and frozen with a
sha256; a platform admin approves it (queue "offerings") and the offering opens.

Investors (any signed-in wallet, including the shared demo account, which never signs anything) reserve shares:
a reservation is a DB commitment, first come first served inside ONE transaction that locks the offering row, so the
offering is never oversubscribed; the per-investor cap and the company's holder cap are checked there too.
A reservation can be withdrawn during its cooling-off period (5 days from reserving) while the offering is open —
whichever ends first. Payment is simulated ("no money moves on testnet").

Close (closing date passed — background loop — or the company / a platform admin closes early):
  reserved x price >= minimum  -> 'awaiting_settlement' -> platform admin approves settlement -> one studio.mints row
                                  per investor (status 'approved', offering_id) -> issuer POST /settle-offering mints them
                                  all in ONE job, then one re-sync of the public copies -> 'settled'
  otherwise                    -> 'released': every reservation is released automatically (event offering_released)
Settlement is idempotent: mint rows are unique per (offering, wallet), the issuer executes only 'approved' rows and
checks the chain before re-sending; a failed settlement can be approved again.

Endpoints:
  GET  /v1/companies/{tk}/offering                 company admin: current offering, live pack preview, defaults, history,
                                                    reservations
  PUT  /v1/companies/{tk}/offering                 terms -> draft (new, or edit a draft / sent-back one)
  POST /v1/companies/{tk}/offering/submit          draft | rejected -> pending_approval (pack assembled + hashed)
  POST /v1/companies/{tk}/offering/cancel          draft | rejected | pending_approval -> cancelled
  POST /v1/companies/{tk}/offering/close           open -> awaiting_settlement | released (close early)
  POST /v1/admin/offerings/{id}/approve|reject     platform admin: open the offering / send it back
  POST /v1/admin/offerings/{id}/close              platform admin: close early
  POST /v1/admin/offerings/{id}/settle             platform admin: awaiting_settlement | failed -> settling -> issuer
  POST /v1/admin/offerings/{id}/release            platform admin: awaiting_settlement | failed (nothing issued yet)
                                                    -> released
  POST /v1/admin/offerings/run-automation          platform admin: close due offerings now
  GET  /v1/offerings, /v1/offerings/{id}           public (open and finished offerings; drafts for company admins)
  POST /v1/offerings/{id}/reservations             signed-in wallet {shares | amount_aud, risk_ack, name?}
  POST /v1/offerings/{id}/reservations/{rid}/withdraw
  GET  /v1/me/reservations                         the signed-in account's reservations
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from ..tools import captable
from . import accounts as acct
from . import update_draft as ud
from .auth import COOKIE, Session
from .company_admins import CompanyAuthz
from .db import ONCHAIN_STATUSES, jsonable
from .services import IssuerError

log = logging.getLogger(__name__)

COOLING_OFF_DAYS = 5
MAX_DAYS_OPEN = 180
IN_PROGRESS = ("draft", "pending_approval", "rejected", "open", "awaiting_settlement", "settling", "failed")
PUBLIC = ("open", "awaiting_settlement", "settling", "settled", "released", "failed")
EDITABLE = ("draft", "rejected")
# standard risks, shown in plain words by the web app (dict.offerings.ts "of.risk.<key>")
RISKS = ("loss", "illiquid", "dilution", "dividends", "info", "testnet")
STALE_UPDATE_DAYS = 90
PRICE_WARN = Decimal("1.2")  # a price 20% above the latest approved price is flagged in the pack
COLS = ("id, company_id, status, price_aud, shares_offered, min_raise_aud, max_per_investor_shares, max_holders, "
        "closes_at, cooling_off_days, use_of_funds, pack, pack_hash, reason, close_reason, created_by, submitted_at, "
        "approved_by, approved_at, opened_at, closed_at, closed_by, settle_approved_by, settle_approved_at, "
        "settled_at, error, created_at, updated_at")
RES_COLS = ("id, offering_id, company_id, wallet, account_id, name, shares, amount_aud, status, risk_ack_at, "
            "cooling_off_until, withdrawn_at, mint_id, created_at, updated_at")


def max_shareholders() -> int:
    """The share token's holder cap (issuer MAX_SHAREHOLDERS, fixed when the token was created; default 500)."""
    try:
        return max(1, int(os.environ.get("MAX_SHAREHOLDERS", "500")))
    except ValueError:
        return 500


def interval_from_env() -> float:
    try:
        return max(0.0, float(os.environ.get("OFFERING_AUTOMATION_SECONDS", "60")))
    except ValueError:
        return 60.0


# ------------------------------------------------------------------ pure helpers
def _dec(v: Any) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v))


def amount_for(shares: int, price: Any) -> Decimal:
    """A$ for a number of shares, to the cent."""
    return (Decimal(int(shares)) * _dec(price)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def shares_for(amount_aud: Any, price: Any) -> int:
    """Whole shares an A$ amount buys (rounded down)."""
    p = _dec(price)
    if p <= 0:
        return 0
    return int((_dec(amount_aud) / p).to_integral_value(rounding=ROUND_DOWN))


def pack_hash(pack: dict) -> str:
    """sha256 of the canonical JSON of the information pack (sorted keys, no spaces)."""
    text = json.dumps(jsonable(pack), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "0x" + hashlib.sha256(text.encode()).hexdigest()


def _utc(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def open_offerings(db, company_ids: list[int] | None = None) -> dict[int, dict]:
    """company id -> {id, status, closes_at} of its open offering (Home list / company page badge)."""
    rows = db.all("SELECT id, company_id, status, closes_at FROM studio.offerings WHERE status='open'"
                  + (" AND company_id = ANY(%s)" if company_ids is not None else ""),
                  (company_ids,) if company_ids is not None else None)
    return {r["company_id"]: jsonable({"id": r["id"], "status": r["status"], "closes_at": r["closes_at"]})
            for r in rows}


def pending_offerings(db, ids: list[int] | None = None) -> list[dict]:
    """Offerings waiting for a platform admin (GET /v1/admin/approvals 'offerings'): to open (pending_approval) or to
    settle (awaiting_settlement, or failed for a retry). Company admins see none."""
    if ids is not None:
        return []
    rows = db.all(f"SELECT {', '.join('o.' + c for c in COLS.split(', '))}, c.ticker, c.name AS company_name "
                  "FROM studio.offerings o JOIN studio.companies c ON c.id=o.company_id "
                  "WHERE o.status IN ('pending_approval','awaiting_settlement','failed') ORDER BY o.updated_at, o.id")
    out = []
    for r in rows:
        v = view(r)
        v.update(ticker=r["ticker"], company_name=r["company_name"], progress=progress(db, r))
        out.append(v)
    return out


def view(o: dict, *, pack: bool = True) -> dict:
    out = {k: o.get(k) for k in COLS.split(", ") if k != "pack" or pack}
    price = _dec(o["price_aud"])
    out["max_raise_aud"] = amount_for(o["shares_offered"], price)
    return jsonable(out)


def progress(db, o: dict, conn=None) -> dict:
    q = ("SELECT COALESCE(sum(shares),0) AS s, count(DISTINCT lower(wallet)) AS n FROM studio.reservations "
         "WHERE offering_id=%s AND status IN ('reserved','allocated')")
    agg = (conn.execute(q, (o["id"],)).fetchone() if conn is not None else db.one(q, (o["id"],)))
    reserved = int(agg["s"])
    price = _dec(o["price_aud"])
    raised = amount_for(reserved, price)
    minimum = _dec(o["min_raise_aud"])
    return jsonable({
        "reserved_shares": reserved, "investors": int(agg["n"]),
        "remaining_shares": max(0, int(o["shares_offered"]) - reserved), "reserved_aud": raised,
        "pct_of_offer": round(reserved * 100 / int(o["shares_offered"]), 2) if o["shares_offered"] else 0,
        "pct_of_min": round(float(raised * 100 / minimum), 2) if minimum > 0 else 100.0,
        "min_reached": reserved > 0 and raised >= minimum,
    })


# ------------------------------------------------------------------ service (pack, close, automation)
class OfferingService:
    """Pack assembly and closing; the background loop closes offerings whose closing date has passed. Every status
    change is a guarded UPDATE under a row lock, so any number of threads / processes can run it."""

    def __init__(self, ctx, cap_table: Callable[[dict], tuple[list[dict], str, int | None]]):
        self.ctx = ctx
        self.cap_table = cap_table
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -------------------------------------------------------------- information pack
    def latest_mark(self, c: dict) -> tuple[Decimal, Any]:
        m = self.ctx.need_db().one("SELECT mark_aud, at FROM studio.marks WHERE company_id=%s "
                                   "ORDER BY at DESC, id DESC LIMIT 1", (c["id"],))
        if m:
            return _dec(m["mark_aud"]), m["at"]
        return _dec(c.get("share_price_aud") or 1), c.get("updated_at")

    def holders_now(self, company_id: int, conn=None) -> set[str]:
        q = "SELECT DISTINCT lower(wallet) AS w FROM studio.holders WHERE company_id=%s AND shares > 0"
        rows = conn.execute(q, (company_id,)).fetchall() if conn is not None else self.ctx.need_db().all(q, (company_id,))
        return {r["w"] for r in rows}

    def holder_limit(self, o: dict) -> int:
        cap = max_shareholders()
        return min(int(o["max_holders"]), cap) if o.get("max_holders") else cap

    def build_pack(self, c: dict, o: dict, now: datetime | None = None) -> dict:
        db = self.ctx.need_db()
        now = now or datetime.now(timezone.utc)
        mark, mark_at = self.latest_mark(c)
        price = _dec(o["price_aud"])
        offered = int(o["shares_offered"])
        val_row = db.one("SELECT result, updated_at FROM studio.valuations WHERE id=%s",
                         (c.get("valuation_id"),)) if c.get("valuation_id") else None
        svi = ((val_row or {}).get("result") or {}).get("svi") or {}
        tri = svi.get("triangulation") or {}
        valuation = {
            "value_aud": c["valuation_aud"], "price_aud": mark, "as_of": mark_at, "grade": (c.get("grade") or "")[:1]
            or None, "low_aud": svi.get("valuation_low_aud"), "mid_aud": svi.get("valuation_mid_aud"),
            "high_aud": svi.get("valuation_high_aud"), "confidence": tri.get("confidence"),
            "report_date": (val_row or {}).get("updated_at"), "report_hash": c.get("valuation_report_hash"),
            "valuation_id": c.get("valuation_id"),
        }
        ups = db.all("SELECT id, cadence, period_end, title, body, published_at, content_hash FROM studio.updates "
                     "WHERE company_id=%s AND status='published' ORDER BY published_at DESC NULLS LAST, "
                     "period_end DESC LIMIT 3", (c["id"],))
        updates = [{"id": u["id"], "title": u["title"], "cadence": u["cadence"],
                    "period_label": ud.period_label(u["cadence"], u["period_end"]), "published_at": u["published_at"],
                    "summary": (ud.canonical_body(u.get("body")).get("summary") or "")[:600],
                    "content_hash": u["content_hash"]} for u in ups]
        table, _, _ = self.cap_table(c)
        total = sum(int(x["shares"]) for x in table)
        after_total = total + offered
        top = sorted(table, key=lambda x: -int(x["shares"]))[:5]
        cap = {
            "before": {"total_shares": total, "holders": len(table),
                       "top": [{"name": x.get("name") or "", "shares": int(x["shares"]),
                                "pct": round(int(x["shares"]) * 100 / total, 4) if total else 0} for x in top]},
            "after": {"total_shares": after_total, "new_shares": offered,
                      "new_pct": round(offered * 100 / after_total, 4) if after_total else 0,
                      "top": [{"name": x.get("name") or "", "shares": int(x["shares"]),
                               "pct": round(int(x["shares"]) * 100 / after_total, 4) if after_total else 0}
                              for x in top]},
        }
        notices = []
        if mark > 0 and price > mark * PRICE_WARN:
            notices.append("price_above_mark")
        if not updates:
            notices.append("no_updates")
        elif updates[0]["published_at"] and _utc(updates[0]["published_at"]) < now - timedelta(days=STALE_UPDATE_DAYS):
            notices.append("stale_updates")
        return jsonable({
            "version": 1,
            "company": {"ticker": c["ticker"], "name": c["name"], "website": c.get("website")},
            "terms": {"price_aud": price, "shares_offered": offered, "max_raise_aud": amount_for(offered, price),
                      "min_raise_aud": _dec(o["min_raise_aud"]), "max_per_investor_shares":
                      int(o["max_per_investor_shares"]), "closes_at": o["closes_at"],
                      "cooling_off_days": int(o.get("cooling_off_days") or COOLING_OFF_DAYS),
                      "max_holders": self.holder_limit(o),
                      "price_vs_mark_pct": round(float((price / mark - 1) * 100), 2) if mark > 0 else None,
                      "use_of_funds": o.get("use_of_funds") or ""},
            "valuation": valuation, "updates": updates, "cap_table": cap, "risks": list(RISKS),
            "notices": notices, "simulated": True, "assembled_at": now,
        })

    # -------------------------------------------------------------- close
    def close(self, oid: int, actor: str, role: str, *, early: bool, now: datetime | None = None) -> dict | None:
        """open -> awaiting_settlement (minimum reached) or released (not reached: every reservation released).
        None when the offering is not open (closed meanwhile)."""
        db = self.ctx.need_db()
        now = now or datetime.now(timezone.utc)
        with db.tx() as tx:
            o = tx.execute(f"SELECT {COLS} FROM studio.offerings WHERE id=%s FOR UPDATE", (oid,)).fetchone()
            if not o or o["status"] != "open":
                return None
            p = progress(db, o, conn=tx)
            reached = bool(p["min_reached"])
            new = "awaiting_settlement" if reached else "released"
            why = "closed_early" if early else "closing_date"
            tx.execute("UPDATE studio.offerings SET status=%s, closed_at=%s, closed_by=%s, close_reason=%s, "
                       "updated_at=now() WHERE id=%s", (new, now, actor, why, oid))
            released = 0
            if not reached:
                released = tx.execute("UPDATE studio.reservations SET status='released', updated_at=now() "
                                      "WHERE offering_id=%s AND status='reserved'", (oid,)).rowcount
            data = {"offering_id": oid, "shares": p["reserved_shares"], "investors": p["investors"],
                    "reserved_aud": p["reserved_aud"], "min_raise_aud": _dec(o["min_raise_aud"]), "early": early,
                    "simulated": True}
            if not reached:
                data["released"] = released
            tx.execute("INSERT INTO studio.events (company_id, kind, data, at) VALUES (%s,%s,%s,%s)",
                       (o["company_id"], "offering_closed" if reached else "offering_released",
                        Jsonb(jsonable(data)), now))
            c = tx.execute("SELECT ticker FROM studio.companies WHERE id=%s", (o["company_id"],)).fetchone()
        db.audit(actor, "offering_closed" if reached else "offering_released", c["ticker"] if c else None,
                 role=role, company_id=o["company_id"], offering_id=oid, reason=why, **{
                     k: data[k] for k in ("shares", "investors", "reserved_aud")}, released=released)
        return {"id": oid, "status": new, "progress": p}

    def close_due(self, now: datetime | None = None) -> list[int]:
        now = now or datetime.now(timezone.utc)
        due = self.ctx.need_db().all("SELECT id FROM studio.offerings WHERE status='open' AND closes_at <= %s "
                                     "ORDER BY closes_at, id LIMIT 50", (now,))
        out = []
        for d in due:
            try:
                if self.close(d["id"], "automation", "system", early=False, now=now):
                    out.append(d["id"])
            except Exception:  # one bad row must not stop the others
                log.exception("closing offering %s failed", d["id"])
        return out

    def tick(self, now: datetime | None = None) -> dict:
        return {"closed": self.close_due(now)}

    def start(self, interval_s: float) -> None:
        if interval_s <= 0 or self._thread is not None or self.ctx.db is None:
            return

        def loop() -> None:
            while not self._stop.wait(interval_s):
                try:
                    self.tick()
                except Exception:  # DB down etc.: try again next time
                    log.exception("offering automation tick failed")

        self._thread = threading.Thread(target=loop, name="offering-automation", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


# ------------------------------------------------------------------ HTTP bodies
class _Body(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")


class TermsBody(_Body):
    price_aud: float = Field(gt=0, le=1_000_000)
    shares_offered: int = Field(gt=0, le=10**12)
    min_raise_aud: float = Field(ge=0, le=10**13)
    max_per_investor_shares: int = Field(gt=0, le=10**12)
    closes_at: datetime
    use_of_funds: str = Field(default="", max_length=2000)
    max_holders: int | None = Field(default=None, ge=1, le=100_000)


class ReserveBody(_Body):
    shares: int | None = Field(default=None, gt=0, le=10**12)
    amount_aud: float | None = Field(default=None, gt=0, le=10**13)
    risk_ack: bool = False
    name: str = Field(default="", max_length=120)


class ReasonBody(_Body):
    reason: str = Field(default="", max_length=1000)


# ------------------------------------------------------------------ router
def build_offerings_router(ctx, svc: OfferingService) -> APIRouter:
    r = APIRouter()
    authz = CompanyAuthz(ctx)

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

    def company_by_id(cid: int) -> dict:
        return ctx.need_db().one("SELECT * FROM studio.companies WHERE id=%s", (cid,))

    def audit(actor: str, role: str, action: str, c: dict, **detail) -> None:
        ctx.need_db().audit(actor, action, c["ticker"], company_id=c["id"], role=role, **detail)

    def live(c: dict) -> bool:
        return c["status"] in ONCHAIN_STATUSES and bool(c.get("local_token"))

    def current(cid: int) -> dict | None:
        return ctx.need_db().one(f"SELECT {COLS} FROM studio.offerings WHERE company_id=%s AND status = ANY(%s) "
                                 "ORDER BY id DESC LIMIT 1", (cid, list(IN_PROGRESS)))

    def load(oid: int) -> dict:
        o = ctx.need_db().one(f"SELECT {COLS} FROM studio.offerings WHERE id=%s", (oid,))
        if not o:
            raise HTTPException(404, "unknown offering")
        return o

    def check_terms(body: TermsBody, now: datetime) -> datetime:
        closes = _utc(body.closes_at)
        if closes <= now + timedelta(minutes=5):
            raise HTTPException(422, "the closing date must be in the future")
        if closes > now + timedelta(days=MAX_DAYS_OPEN):
            raise HTTPException(422, f"the closing date must be within {MAX_DAYS_OPEN} days")
        if body.max_per_investor_shares > body.shares_offered:
            raise HTTPException(422, "the most per investor cannot be more than the shares offered")
        if Decimal(str(body.min_raise_aud)) > amount_for(body.shares_offered, body.price_aud):
            raise HTTPException(422, "the minimum to raise cannot be more than all the shares offered are worth")
        if body.max_holders is not None and body.max_holders > max_shareholders():
            raise HTTPException(422, f"this share register allows at most {max_shareholders()} shareholders")
        return closes

    def reservations_of(oid: int) -> list[dict]:
        return jsonable(ctx.need_db().all(f"SELECT {RES_COLS} FROM studio.reservations WHERE offering_id=%s "
                                          "ORDER BY id", (oid,)))

    def company_view(c: dict, role: str) -> dict:
        db = ctx.need_db()
        o = current(c["id"])
        mark, _ = svc.latest_mark(c)
        holders = len(svc.holders_now(c["id"]))
        out: dict[str, Any] = {
            "ticker": c["ticker"], "company_id": c["id"], "name": c["name"], "you": role, "live": live(c),
            "defaults": {"price_aud": mark, "cooling_off_days": COOLING_OFF_DAYS, "holders": holders,
                         "max_holders": max_shareholders(), "total_shares": int(c["total_shares"])},
            "offering": None, "pack": None, "progress": None, "reservations": [],
        }
        if o:
            out["offering"] = view(o, pack=False)
            out["pack"] = o["pack"] if o["status"] not in EDITABLE and o.get("pack") else svc.build_pack(c, o)
            out["progress"] = progress(db, o)
            out["reservations"] = reservations_of(o["id"])
        out["history"] = jsonable([{**view(x, pack=False), "progress": progress(db, x)} for x in db.all(
            f"SELECT {COLS} FROM studio.offerings WHERE company_id=%s AND NOT (status = ANY(%s)) "
            "ORDER BY id DESC LIMIT 20", (c["id"], list(IN_PROGRESS)))])
        return jsonable(out)

    # -------------------------------------------------------------- company side
    @r.get("/v1/companies/{tk}/offering")
    def get_company_offering(tk: str, sess: Session = Depends(require_user)):
        c = company(tk)
        return company_view(c, authz.check(sess, c["id"]))

    @r.put("/v1/companies/{tk}/offering")
    def put_terms(tk: str, body: TermsBody, sess: Session = Depends(require_user)):
        db = ctx.need_db()
        c = company(tk)
        role = authz.check(sess, c["id"])
        if not live(c):
            raise HTTPException(409, "an offering can be set up once the shares are issued")
        now = datetime.now(timezone.utc)
        closes = check_terms(body, now)
        o = current(c["id"])
        if o and o["status"] not in EDITABLE:
            raise HTTPException(409, f"the current offering is {o['status']}; it cannot be changed now")
        vals = (Decimal(str(body.price_aud)), body.shares_offered, Decimal(str(body.min_raise_aud)),
                body.max_per_investor_shares, body.max_holders, closes, body.use_of_funds.strip())
        if o:
            row = db.one("UPDATE studio.offerings SET price_aud=%s, shares_offered=%s, min_raise_aud=%s, "
                         "max_per_investor_shares=%s, max_holders=%s, closes_at=%s, use_of_funds=%s, status='draft', "
                         "pack=NULL, pack_hash=NULL, updated_at=now() WHERE id=%s AND status IN ('draft','rejected') "
                         f"RETURNING {COLS}", (*vals, o["id"]))
            if not row:
                raise HTTPException(409, "the offering changed meanwhile; reload")
        else:
            row = db.one("INSERT INTO studio.offerings (company_id, price_aud, shares_offered, min_raise_aud, "
                         "max_per_investor_shares, max_holders, closes_at, use_of_funds, cooling_off_days, status, "
                         f"created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s) RETURNING {COLS}",
                         (c["id"], *vals, COOLING_OFF_DAYS, sess.actor))
        audit(sess.actor, role, "offering_saved", c, offering_id=row["id"], price_aud=body.price_aud,
              shares_offered=body.shares_offered, min_raise_aud=body.min_raise_aud,
              max_per_investor_shares=body.max_per_investor_shares, max_holders=body.max_holders, closes_at=closes,
              previous=o["status"] if o else None)
        return company_view(c, role)

    @r.post("/v1/companies/{tk}/offering/submit")
    def submit(tk: str, sess: Session = Depends(require_user)):
        db = ctx.need_db()
        c = company(tk)
        role = authz.check(sess, c["id"])
        o = current(c["id"])
        if not o:
            raise HTTPException(404, "no offering yet; set the terms first")
        if o["status"] not in EDITABLE:
            raise HTTPException(409, f"offering is {o['status']}, not a draft")
        if _utc(o["closes_at"]) <= datetime.now(timezone.utc) + timedelta(minutes=5):
            raise HTTPException(409, "the closing date has passed; change it first")
        pack = svc.build_pack(c, o)
        h = pack_hash(pack)
        row = db.one("UPDATE studio.offerings SET status='pending_approval', pack=%s, pack_hash=%s, reason=NULL, "
                     "submitted_at=now(), updated_at=now() WHERE id=%s AND status IN ('draft','rejected') "
                     "RETURNING id", (Jsonb(pack), h, o["id"]))
        if not row:
            raise HTTPException(409, "the offering changed meanwhile; reload")
        audit(sess.actor, role, "offering_submitted", c, offering_id=o["id"], pack_hash=h)
        return company_view(c, role)

    @r.post("/v1/companies/{tk}/offering/cancel")
    def cancel(tk: str, sess: Session = Depends(require_user)):
        db = ctx.need_db()
        c = company(tk)
        role = authz.check(sess, c["id"])
        o = current(c["id"])
        row = db.one("UPDATE studio.offerings SET status='cancelled', updated_at=now() WHERE id=%s "
                     "AND status IN ('draft','rejected','pending_approval') RETURNING id", (o["id"] if o else 0,))
        if not row:
            raise HTTPException(409 if o else 404, f"offering is {o['status']}; only one that has not opened can be "
                                                   "cancelled" if o else "no offering yet")
        audit(sess.actor, role, "offering_cancelled", c, offering_id=o["id"], previous=o["status"])
        return company_view(c, role)

    def close_now(o: dict, sess: Session, role: str) -> dict:
        res = svc.close(o["id"], sess.actor, role, early=True)
        if res is None:
            cur = load(o["id"])
            raise HTTPException(409, f"offering is {cur['status']}, not open")
        return res

    @r.post("/v1/companies/{tk}/offering/close")
    def close_company(tk: str, sess: Session = Depends(require_user)):
        c = company(tk)
        role = authz.check(sess, c["id"])
        o = current(c["id"])
        if not o:
            raise HTTPException(404, "no offering yet")
        close_now(o, sess, role)
        return company_view(c, role)

    # -------------------------------------------------------------- platform admin
    @r.post("/v1/admin/offerings/{oid}/approve")
    def approve(oid: int, sess: Session = Depends(require_admin)):
        db = ctx.need_db()
        o = load(oid)
        if o["status"] != "pending_approval":
            raise HTTPException(409, f"offering is {o['status']}, not waiting for approval")
        if _utc(o["closes_at"]) <= datetime.now(timezone.utc) + timedelta(minutes=5):
            raise HTTPException(409, "the closing date has passed; send it back so the company can change it")
        c = company_by_id(o["company_id"])
        if not live(c):
            raise HTTPException(409, "the company's shares are not live")
        row = db.one("UPDATE studio.offerings SET status='open', approved_by=%s, approved_at=now(), opened_at=now(), "
                     f"updated_at=now() WHERE id=%s AND status='pending_approval' RETURNING {COLS}", (sess.actor, oid))
        if not row:
            raise HTTPException(409, "the offering changed meanwhile; reload")
        db.exec("INSERT INTO studio.events (company_id, kind, data) VALUES (%s,'offering_opened',%s)",
                (c["id"], Jsonb(jsonable({"offering_id": oid, "shares": int(row["shares_offered"]),
                                          "price_aud": row["price_aud"], "closes_at": row["closes_at"],
                                          "min_raise_aud": row["min_raise_aud"], "pack_hash": row["pack_hash"],
                                          "simulated": True}))))
        audit(sess.actor, "platform_admin", "offering_approved", c, offering_id=oid, pack_hash=row["pack_hash"])
        return view(row, pack=False)

    @r.post("/v1/admin/offerings/{oid}/reject")
    def reject(oid: int, body: ReasonBody | None = None, sess: Session = Depends(require_admin)):
        db = ctx.need_db()
        reason = (body.reason.strip() if body else "") or "sent back by admin"
        row = db.one("UPDATE studio.offerings SET status='rejected', reason=%s, updated_at=now() "
                     f"WHERE id=%s AND status='pending_approval' RETURNING {COLS}", (reason, oid))
        if not row:
            o = load(oid)
            raise HTTPException(409, f"offering is {o['status']}, not waiting for approval")
        audit(sess.actor, "platform_admin", "offering_rejected", company_by_id(row["company_id"]), offering_id=oid,
              reason=reason)
        return view(row, pack=False)

    @r.post("/v1/admin/offerings/{oid}/close")
    def close_admin(oid: int, sess: Session = Depends(require_admin)):
        return close_now(load(oid), sess, "platform_admin")

    @r.post("/v1/admin/offerings/{oid}/settle", status_code=202)
    def settle(oid: int, sess: Session = Depends(require_admin)):
        """The settlement approval: one mint row per investor (approved), then ONE issuer job mints them all and
        re-syncs the public copies once. Retry-safe: rows are unique per (offering, wallet)."""
        db = ctx.need_db()
        issuer = ctx.need_issuer()
        with db.tx() as tx:
            o = tx.execute(f"SELECT {COLS} FROM studio.offerings WHERE id=%s FOR UPDATE", (oid,)).fetchone()
            if not o:
                raise HTTPException(404, "unknown offering")
            if o["status"] not in ("awaiting_settlement", "failed"):
                raise HTTPException(409, f"offering is {o['status']}, not waiting for settlement")
            allocs = tx.execute("SELECT min(wallet) AS wallet, sum(shares) AS shares, max(name) AS name "
                                "FROM studio.reservations WHERE offering_id=%s AND status='reserved' "
                                "GROUP BY lower(wallet) ORDER BY min(id)", (oid,)).fetchall()
            if not allocs and not tx.execute("SELECT 1 FROM studio.mints WHERE offering_id=%s LIMIT 1",
                                             (oid,)).fetchone():
                raise HTTPException(409, "no reservations to settle")
            for a in allocs:
                tx.execute("INSERT INTO studio.mints (company_id, to_wallet, holder_name, shares, reason, status, "
                           "requested_by, offering_id) VALUES (%s,%s,%s,%s,%s,'approved',%s,%s) "
                           "ON CONFLICT (offering_id, lower(to_wallet)) WHERE offering_id IS NOT NULL DO NOTHING",
                           (o["company_id"], a["wallet"], a["name"] or "Investor", int(a["shares"]),
                            f"Share offering #{oid}", f"offering:{oid}", oid))
            tx.execute("UPDATE studio.mints SET status='approved' WHERE offering_id=%s AND status='failed'", (oid,))
            tx.execute("UPDATE studio.offerings SET status='settling', settle_approved_by=%s, settle_approved_at=now(), "
                       "error=NULL, updated_at=now() WHERE id=%s", (sess.actor, oid))
            n = tx.execute("SELECT count(*) AS n, COALESCE(sum(shares),0) AS s FROM studio.mints WHERE offering_id=%s",
                           (oid,)).fetchone()
        c = company_by_id(o["company_id"])
        audit(sess.actor, "platform_admin", "offering_settle_approved", c, offering_id=oid, previous=o["status"],
              investors=int(n["n"]), shares=int(n["s"]))
        try:
            issuer.post("/settle-offering", {"offering_id": oid})
        except IssuerError as e:
            db.exec("UPDATE studio.offerings SET status=%s, error=%s, updated_at=now() WHERE id=%s AND status='settling'",
                    (o["status"], str(e)[:1000], oid))
            audit(sess.actor, "platform_admin", "offering_settle_issuer_error", c, offering_id=oid, error=str(e)[:300])
            raise HTTPException(502, str(e)) from None
        return {"id": oid, "status": "settling", "investors": int(n["n"]), "shares": int(n["s"])}

    @r.post("/v1/admin/offerings/{oid}/release")
    def release(oid: int, body: ReasonBody | None = None, sess: Session = Depends(require_admin)):
        """Do not settle: release every reservation (only while nothing has been issued for this offering)."""
        db = ctx.need_db()
        with db.tx() as tx:
            o = tx.execute(f"SELECT {COLS} FROM studio.offerings WHERE id=%s FOR UPDATE", (oid,)).fetchone()
            if not o:
                raise HTTPException(404, "unknown offering")
            if o["status"] not in ("awaiting_settlement", "failed"):
                raise HTTPException(409, f"offering is {o['status']}, not waiting for settlement")
            if tx.execute("SELECT 1 FROM studio.mints WHERE offering_id=%s AND status IN ('minted','minting') LIMIT 1",
                          (oid,)).fetchone():
                raise HTTPException(409, "some shares were already issued for this offering; approve the settlement "
                                         "again to finish it")
            tx.execute("UPDATE studio.mints SET status='rejected' WHERE offering_id=%s AND status IN ('approved','failed')",
                       (oid,))
            n = tx.execute("UPDATE studio.reservations SET status='released', updated_at=now() WHERE offering_id=%s "
                           "AND status='reserved'", (oid,)).rowcount
            tx.execute("UPDATE studio.offerings SET status='released', reason=%s, updated_at=now() WHERE id=%s",
                       ((body.reason.strip() if body else "") or "released by admin", oid))
            tx.execute("INSERT INTO studio.events (company_id, kind, data) VALUES (%s,'offering_released',%s)",
                       (o["company_id"], Jsonb({"offering_id": oid, "released": n, "by_admin": True,
                                                "simulated": True})))
        audit(sess.actor, "platform_admin", "offering_released_by_admin", company_by_id(o["company_id"]),
              offering_id=oid, released=n, reason=body.reason if body else "")
        return {"id": oid, "status": "released", "released": n}

    @r.post("/v1/admin/offerings/run-automation")
    def run_automation(sess: Session = Depends(require_admin)):
        out = svc.tick()
        ctx.need_db().audit(sess.actor, "offering_automation_run", None, role="platform_admin", **out)
        return out

    # -------------------------------------------------------------- investors
    def my_wallets(sess: Session | None) -> list[str]:
        if not sess:
            return []
        return [w.lower() for w in acct.account_wallets(ctx.need_db(), sess.account_id, sess.address)]

    def public_view(o: dict, c: dict, sess: Session | None, *, full: bool) -> dict:
        db = ctx.need_db()
        out = view(o, pack=full)
        out.update(ticker=c["ticker"], company_name=c["name"], website=c.get("website"),
                   grade=(c.get("grade") or "")[:1] or None, progress=progress(db, o),
                   holder_limit=svc.holder_limit(o))
        if full and not o.get("pack"):
            out["pack"] = svc.build_pack(c, o)  # a draft seen by its company admins: live preview
        if not (sess and authz.role(sess, c["id"])):  # who did what stays with the company and the admins
            for k in ("created_by", "approved_by", "settle_approved_by", "closed_by", "error"):
                out.pop(k, None)
        mine = my_wallets(sess)
        if mine:
            now = datetime.now(timezone.utc)
            rows = db.all(f"SELECT {RES_COLS} FROM studio.reservations WHERE offering_id=%s AND lower(wallet) = ANY(%s) "
                          "ORDER BY id", (o["id"], mine))
            out["mine"] = [{**jsonable(x), "can_withdraw": can_withdraw(o, x, now)} for x in rows]
            held = {w for w in svc.holders_now(c["id"])}
            out["mine_reserved_shares"] = sum(int(x["shares"]) for x in rows if x["status"] == "reserved")
            out["you_hold"] = any(w in held for w in mine)
        return jsonable(out)

    def can_withdraw(o: dict, res: dict, now: datetime) -> bool:
        return (res["status"] == "reserved" and o["status"] == "open" and _utc(o["closes_at"]) > now
                and _utc(res["cooling_off_until"]) > now)

    def readable(o: dict, sess: Session | None) -> dict:
        c = company_by_id(o["company_id"])
        if o["status"] not in PUBLIC and not (sess and authz.role(sess, c["id"])):
            raise HTTPException(404, "unknown offering")
        return c

    @r.get("/v1/offerings")
    def list_offerings(request: Request):
        db = ctx.need_db()
        sess = session(request)
        rows = db.all(f"SELECT {', '.join('o.' + x for x in COLS.split(', '))} FROM studio.offerings o "
                      "WHERE o.status = ANY(%s) ORDER BY (o.status='open') DESC, o.closes_at DESC, o.id DESC LIMIT 100",
                      (list(PUBLIC),))
        cos = {x["id"]: x for x in db.all("SELECT * FROM studio.companies WHERE id = ANY(%s)",
                                          ([x["company_id"] for x in rows] or [0],))}
        return {"offerings": [public_view(o, cos[o["company_id"]], sess, full=False) for o in rows],
                "simulated": True}

    @r.get("/v1/offerings/{oid}")
    def get_offering(oid: int, request: Request):
        sess = session(request)
        o = load(oid)
        c = readable(o, sess)
        return public_view(o, c, sess, full=True)

    @r.post("/v1/offerings/{oid}/reservations", status_code=201)
    def reserve(oid: int, body: ReserveBody, sess: Session = Depends(require_user)):
        db = ctx.need_db()
        if not sess.address:
            raise HTTPException(403, "sign in with a wallet (or the demo account) to reserve shares")
        if not body.risk_ack:
            raise HTTPException(422, "please confirm that you have read the risks")
        if (body.shares is None) == (body.amount_aud is None):
            raise HTTPException(422, "give either a number of shares or an amount in A$")
        try:
            wallet = captable.checksum(sess.address.lower())  # trusted session address; EIP-55 form
        except captable.CapTableError as e:
            raise HTTPException(422, str(e)) from None
        now = datetime.now(timezone.utc)
        with db.tx() as tx:
            # the row lock serialises every reservation of this offering: first come, first served, never oversold
            o = tx.execute(f"SELECT {COLS} FROM studio.offerings WHERE id=%s FOR UPDATE", (oid,)).fetchone()
            if not o or o["status"] not in PUBLIC:
                raise HTTPException(404, "unknown offering")
            if o["status"] != "open" or _utc(o["closes_at"]) <= now:
                raise HTTPException(409, "this offering is closed")
            price = _dec(o["price_aud"])
            shares = body.shares if body.shares is not None else shares_for(body.amount_aud, price)
            if shares < 1:
                raise HTTPException(422, f"the amount is less than one share (A${price} per share)")
            agg = tx.execute("SELECT COALESCE(sum(shares),0) AS s, COALESCE(sum(shares) FILTER "
                             "(WHERE lower(wallet)=lower(%s)),0) AS mine FROM studio.reservations "
                             "WHERE offering_id=%s AND status='reserved'", (wallet, oid)).fetchone()
            remaining = int(o["shares_offered"]) - int(agg["s"])
            if remaining <= 0:
                raise HTTPException(409, "all shares in this offering are reserved")
            if shares > remaining:
                raise HTTPException(409, f"only {remaining:,} shares are left")
            room = int(o["max_per_investor_shares"]) - int(agg["mine"])
            if shares > room:
                raise HTTPException(409, f"each investor can reserve at most {int(o['max_per_investor_shares']):,} "
                                         f"shares; you can add {max(room, 0):,} more")
            held = svc.holders_now(o["company_id"], conn=tx)
            reserved_wallets = {x["w"] for x in tx.execute(
                "SELECT DISTINCT lower(wallet) AS w FROM studio.reservations WHERE offering_id=%s AND status='reserved'",
                (oid,)).fetchall()}
            w = wallet.lower()
            if w not in held and w not in reserved_wallets:
                limit = svc.holder_limit(o)
                if len(held | reserved_wallets) + 1 > limit:
                    raise HTTPException(409, f"this business can have at most {limit:,} shareholders and that "
                                             "number is reached")
            name = body.name.strip() or ("Demo investor" if sess.auth_method == "demo" else
                                         f"Investor {wallet[:6]}…{wallet[-4:]}")
            until = min(now + timedelta(days=int(o["cooling_off_days"] or COOLING_OFF_DAYS)), _utc(o["closes_at"]))
            row = tx.execute(
                "INSERT INTO studio.reservations (offering_id, company_id, wallet, account_id, name, shares, amount_aud, "
                f"status, risk_ack_at, cooling_off_until) VALUES (%s,%s,%s,%s,%s,%s,%s,'reserved',%s,%s) "
                f"RETURNING {RES_COLS}",
                (oid, o["company_id"], wallet, sess.account_id, name, shares, amount_for(shares, price), now,
                 until)).fetchone()
        c = company_by_id(o["company_id"])
        audit(sess.actor, "investor", "shares_reserved", c, offering_id=oid, reservation_id=row["id"], wallet=wallet,
              shares=shares, amount_aud=amount_for(shares, price), simulated=True)
        return {"reservation": {**jsonable(row), "can_withdraw": can_withdraw(o, row, now)},
                "offering": public_view(load(oid), c, sess, full=False)}

    @r.post("/v1/offerings/{oid}/reservations/{rid}/withdraw")
    def withdraw(oid: int, rid: int, sess: Session = Depends(require_user)):
        db = ctx.need_db()
        mine = my_wallets(sess)
        now = datetime.now(timezone.utc)
        with db.tx() as tx:
            o = tx.execute(f"SELECT {COLS} FROM studio.offerings WHERE id=%s FOR UPDATE", (oid,)).fetchone()
            res = tx.execute(f"SELECT {RES_COLS} FROM studio.reservations WHERE id=%s AND offering_id=%s FOR UPDATE",
                             (rid, oid)).fetchone()
            if not o or not res or res["wallet"].lower() not in mine:
                raise HTTPException(404, "unknown reservation")
            if res["status"] != "reserved":
                raise HTTPException(409, f"this reservation is {res['status']}")
            if o["status"] != "open" or _utc(o["closes_at"]) <= now:
                raise HTTPException(409, "the offering has closed; reservations can no longer be withdrawn")
            if _utc(res["cooling_off_until"]) <= now:
                raise HTTPException(409, "the cooling-off period for this reservation has ended")
            row = tx.execute("UPDATE studio.reservations SET status='withdrawn', withdrawn_at=%s, updated_at=now() "
                             f"WHERE id=%s RETURNING {RES_COLS}", (now, rid)).fetchone()
        audit(sess.actor, "investor", "reservation_withdrawn", company_by_id(o["company_id"]), offering_id=oid,
              reservation_id=rid, wallet=res["wallet"], shares=int(res["shares"]))
        return {"reservation": {**jsonable(row), "can_withdraw": False}}

    @r.get("/v1/me/reservations")
    def my_reservations(sess: Session = Depends(require_user)):
        mine = my_wallets(sess)
        if not mine:
            return {"reservations": []}
        now = datetime.now(timezone.utc)
        rows = ctx.need_db().all(
            f"SELECT {', '.join('r.' + x for x in RES_COLS.split(', '))}, o.status AS offering_status, o.closes_at, "
            "o.price_aud, c.ticker, c.name AS company_name FROM studio.reservations r "
            "JOIN studio.offerings o ON o.id=r.offering_id JOIN studio.companies c ON c.id=r.company_id "
            "WHERE lower(r.wallet) = ANY(%s) ORDER BY r.created_at DESC, r.id DESC LIMIT 200", (mine,))
        out = []
        for x in rows:
            o = {"status": x["offering_status"], "closes_at": x["closes_at"]}
            out.append({**jsonable(x), "can_withdraw": can_withdraw(o, x, now)})
        return {"reservations": out}

    return r
