"""Automatic dividends (docs/UPGRADE-INVESTOR-PLAN.md 3e, MVP): a standing dividend policy per company.

A company owner / manager (or a platform admin) sets the policy — "pay X% of net profit every quarter, at most Y mAUD
per payment" or a fixed amount — and sends it for approval. A platform admin approves it ONCE: that approval is the
standing human approval for every payment the policy makes, within its cap.

Automation (API process only; the worker cannot reach the issuer), `DividendAutomation.tick()`:
  1. declare  — every business update PUBLISHED after the policy became active, whose cadence matches the policy
                frequency, gets exactly one studio.dividends row (unique index on update_id):
                amount = policy_amount(net profit of that update), capped; <= 0 -> row 'skipped' (with a note).
                Otherwise status 'scheduled', source 'policy', approved_by 'policy:<id>', claims = pro-rata plan
                on the cap table at declaration (the record date), pay_after = now + veto_hours.
                Event `dividend_declared` (shown to holders as "Dividend announced").
  2. execute  — 'scheduled' rows whose pay_after has passed flip to 'approved' atomically and the issuer's existing
                POST /dividend pays them (createRound + relayer claimFor on BlockID Chain, gas 0). The issuer still
                executes only 'approved' rows. An issuer error puts the row back to 'scheduled' 10 minutes later.
During the window an owner / manager (or platform admin) can cancel: POST /v1/companies/{tk}/dividends/{id}/veto
-> 'vetoed', event `dividend_vetoed`. Everything is audited (actor 'policy:<id>' for automatic steps).

No contract changes: dividends live only on BlockID Chain (DividendDistributor already deployed per company).

Endpoints:
  GET  /v1/companies/{tk}/dividend-policy                 company admin / platform admin: policy, next payment,
                                                          the company's dividends (manual + automatic)
  PUT  /v1/companies/{tk}/dividend-policy                 {kind, ratio_pct|fixed_maud, max_maud_per_round, frequency,
                                                          veto_hours} -> draft (an active policy goes back to draft:
                                                          changes need a new approval)
  POST /v1/companies/{tk}/dividend-policy/submit          draft | rejected -> pending_approval
  POST /v1/companies/{tk}/dividend-policy/pause|resume    active <-> paused (resume only counts updates from now on)
  POST /v1/companies/{tk}/dividends/{id}/veto             scheduled -> vetoed
  POST /v1/admin/dividend-policies/{id}/approve|reject    platform admin only (queue "policies" in /v1/admin/approvals)
  GET  /v1/me/dividends, /v1/demo/dividends               ledger (paid) + upcoming across the wallet's holdings
  POST /v1/admin/dividends/run-automation                 platform admin: one automation pass now
"""
from __future__ import annotations

import calendar
import logging
import os
import threading
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal
from typing import Any, Callable, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from ..agents import dividend as dividend_agent
from ..tools.merkle import build_distribution
from . import accounts as acct
from . import update_draft as ud
from .auth import COOKIE, Session
from .company_admins import CompanyAuthz
from .db import ONCHAIN_STATUSES, jsonable
from .services import IssuerError

log = logging.getLogger(__name__)

UNITS = 1_000_000  # mAUD has 6 decimals
CENT = UNITS // 100
RETRY_AFTER = timedelta(minutes=10)
POLICY_COLS = ("id, company_id, kind, ratio_pct, fixed_maud, max_maud_per_round, frequency, veto_hours, status, "
               "reason, active_since, created_by, approved_by, approved_at, created_at, updated_at")
DIV_COLS = ("d.id, d.company_id, d.total_units, d.status, d.source, d.policy_id, d.update_id, d.pay_after, "
            "d.approved_by, d.requested_by, d.note, d.tx_hash, d.round_id, d.created_at, "
            "jsonb_array_length(COALESCE(d.claims,'[]'::jsonb)) AS holders")


# ------------------------------------------------------------------ pure maths
def _dec(v: Any) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def policy_amount_units(policy: dict, net_profit_aud: Any) -> int:
    """mAUD units to pay for one period (1 mAUD = A$1 on testnet). Never more than the profit, never more than the cap,
    rounded down to whole cents; 0 when there is no profit."""
    np_ = _dec(net_profit_aud)
    if np_ is None or np_ <= 0:
        return 0
    cap = _dec(policy.get("max_maud_per_round")) or Decimal(0)
    if policy["kind"] == "payout_ratio":
        amt = np_ * (_dec(policy.get("ratio_pct")) or Decimal(0)) / 100
    else:
        amt = min(_dec(policy.get("fixed_maud")) or Decimal(0), np_)
    amt = max(Decimal(0), min(amt, cap))
    units = int((amt * UNITS).to_integral_value(rounding=ROUND_DOWN))
    return units - units % CENT


def net_profit_of(update: dict) -> Any:
    body = ud.canonical_body(update.get("body"))
    for k in body.get("kpis") or []:
        if isinstance(k, dict) and k.get("metric") == "net_profit":
            return k.get("value")
    return None


def next_period_end(frequency: str, today: date) -> date:
    """The end of the current month / calendar quarter (the next period a payment can come from)."""
    m = today.month if frequency == "monthly" else ((today.month - 1) // 3 + 1) * 3
    return date(today.year, m, calendar.monthrange(today.year, m)[1])


def plan_claims(table: list[dict], units: int) -> tuple[list[dict], str, int, int]:
    """Pro-rata plan on a cap table -> (claims, merkle_root, total, remainder). Raises ValueError (no holders)."""
    names = {x["wallet"].lower(): x.get("name", "") for x in table}
    alloc, remainder = dividend_agent.allocate({x["wallet"]: x["shares"] for x in table}, units)
    if not alloc:
        return [], "", 0, units
    dist = build_distribution(alloc)
    claims = [{"wallet": x["wallet"], "name": names.get(x["wallet"].lower(), ""), "amount": alloc[x["wallet"]],
               "proof": dist.claims[x["wallet"].lower()]["proof"]} for x in table if x["wallet"] in alloc]
    return claims, dist.root, dist.total, remainder


def policy_view(p: dict | None) -> dict | None:
    if not p:
        return None
    return jsonable({k: p.get(k) for k in POLICY_COLS.split(", ")})


def pending_policies(db, ids: list[int] | None = None) -> list[dict]:
    """Policies waiting for a platform admin (GET /v1/admin/approvals 'policies'); company scope sees none."""
    if ids is not None:
        return []
    rows = db.all(f"SELECT {', '.join('p.' + c for c in POLICY_COLS.split(', '))}, c.ticker, c.name AS company_name "
                  "FROM studio.dividend_policies p JOIN studio.companies c ON c.id=p.company_id "
                  "WHERE p.status='pending_approval' ORDER BY p.updated_at, p.id")
    return jsonable(rows)


def upcoming_for(db, company_ids: list[int], wallets_low: list[str]) -> dict[int, list[dict]]:
    """Declared (scheduled) dividends of these companies with this wallet's share, by company id."""
    if not company_ids or not wallets_low:
        return {}
    rows = db.all("SELECT d.id, d.company_id, d.total_units, d.pay_after, d.claims, d.created_at, u.cadence, "
                  "u.period_end FROM studio.dividends d LEFT JOIN studio.updates u ON u.id=d.update_id "
                  "WHERE d.status='scheduled' AND d.company_id = ANY(%s) ORDER BY d.pay_after", (company_ids,))
    out: dict[int, list[dict]] = {}
    for r in rows:
        mine = sum(int(c.get("amount") or 0) for c in (r["claims"] or [])
                   if isinstance(c, dict) and str(c.get("wallet", "")).lower() in wallets_low)
        if mine <= 0:
            continue
        out.setdefault(r["company_id"], []).append(jsonable({
            "dividend_id": r["id"], "amount_maud": mine / UNITS, "total_maud": int(r["total_units"]) / UNITS,
            "pay_after": r["pay_after"], "declared_at": r["created_at"],
            "period_label": ud.period_label(r["cadence"], r["period_end"]) if r.get("period_end") else None}))
    return out


# ------------------------------------------------------------------ automation
class DividendAutomation:
    """Declares policy dividends for published updates and hands due ones to the issuer. Safe to call from any number
    of threads / processes: the declaration is unique per update and every status change is a guarded UPDATE."""

    def __init__(self, ctx, cap_table: Callable[[dict], tuple[list[dict], str, int | None]]):
        self.ctx = ctx
        self.cap_table = cap_table
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _audit(self, actor: str, action: str, target: str, **detail) -> None:
        self.ctx.need_db().audit(actor, action, target, role="policy", **detail)

    def declare(self, now: datetime | None = None) -> list[int]:
        """New dividend rows (scheduled or skipped) for published updates not handled yet. Returns their ids."""
        db = self.ctx.need_db()
        now = now or datetime.now(timezone.utc)
        rows = db.all(
            "SELECT u.id AS update_id, u.company_id, u.cadence, u.period_end, u.body, u.published_at, "
            f"{', '.join('p.' + c + ' AS p_' + c for c in POLICY_COLS.split(', '))}, "
            "c.ticker, c.status AS company_status, c.local_token "
            "FROM studio.updates u JOIN studio.dividend_policies p ON p.company_id=u.company_id "
            "JOIN studio.companies c ON c.id=u.company_id "
            "WHERE u.status='published' AND p.status='active' AND u.cadence=p.frequency "
            "AND u.published_at IS NOT NULL AND p.active_since IS NOT NULL AND u.published_at >= p.active_since "
            "AND NOT EXISTS (SELECT 1 FROM studio.dividends d WHERE d.update_id=u.id) "
            "ORDER BY u.published_at, u.id LIMIT 50")
        made: list[int] = []
        for r in rows:
            try:
                did = self._declare_one(r, now)
            except Exception:  # one bad company must not stop the others
                log.exception("dividend declaration for update %s failed", r["update_id"])
                continue
            if did is not None:
                made.append(did)
        return made

    def _declare_one(self, r: dict, now: datetime) -> int | None:
        db = self.ctx.need_db()
        p = {c: r["p_" + c] for c in POLICY_COLS.split(", ")}
        actor, period = f"policy:{p['id']}", ud.period_label(r["cadence"], r["period_end"])
        profit = _dec(net_profit_of(r))
        units = policy_amount_units(p, profit)
        claims, root, note = [], None, None
        if profit is None:
            note = "no net profit in this update"
        elif profit <= 0:
            note = "no profit this period"
        elif units <= 0:
            note = "the amount for this period rounds to A$0.00, so nothing is paid"
        elif r["company_status"] not in ONCHAIN_STATUSES or not r.get("local_token"):
            note, units = "shares are not issued on BlockID Chain", 0
        else:
            table, _, _ = self.cap_table(db.one("SELECT * FROM studio.companies WHERE id=%s", (r["company_id"],)))
            try:
                claims, root, total, _ = plan_claims(table, units)
            except ValueError:  # nobody holds shares at the record date
                note, units = "no shareholders to pay", 0
            else:
                if not claims:
                    note, units = "the amount is too small to give any shareholder at least 1 cent", 0
                else:
                    units = total
        status = "scheduled" if units > 0 else "skipped"
        pay_after = now + timedelta(hours=int(p["veto_hours"])) if units > 0 else None
        row = db.one(
            "INSERT INTO studio.dividends (company_id, total_units, merkle_root, claims, status, requested_by, "
            "policy_id, update_id, pay_after, source, approved_by, note, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'policy',%s,%s,%s) "
            "ON CONFLICT (update_id) WHERE update_id IS NOT NULL DO NOTHING RETURNING id",
            (r["company_id"], units, root, Jsonb(claims), status, actor, p["id"], r["update_id"], pay_after,
             actor if units > 0 else None, note, now))
        if not row:
            return None  # declared meanwhile by another tick
        did = row["id"]
        if units > 0:
            db.exec("INSERT INTO studio.events (company_id, kind, data, at) VALUES (%s,'dividend_declared',%s,%s)",
                    (r["company_id"], Jsonb(jsonable({
                        "dividend_id": did, "total_units": units, "pay_after": pay_after, "update_id": r["update_id"],
                        "period": period, "policy_id": p["id"], "holders": len(claims)})), now))
            self._audit(actor, "dividend_declared", r["ticker"], company_id=r["company_id"], dividend_id=did,
                        update_id=r["update_id"], total_units=units, pay_after=pay_after, holders=len(claims),
                        net_profit=net_profit_of(r))
        else:
            self._audit(actor, "dividend_skipped", r["ticker"], company_id=r["company_id"], dividend_id=did,
                        update_id=r["update_id"], reason=note, net_profit=net_profit_of(r))
        return did

    def execute_due(self, now: datetime | None = None) -> list[int]:
        """Scheduled dividends past their veto window -> approved -> issuer POST /dividend. Returns ids handed over."""
        db = self.ctx.need_db()
        now = now or datetime.now(timezone.utc)
        due = db.all("SELECT id FROM studio.dividends WHERE status='scheduled' AND pay_after IS NOT NULL "
                     "AND pay_after <= %s ORDER BY pay_after, id LIMIT 20", (now,))
        if not due:
            return []
        issuer = self.ctx.issuer
        if issuer is None:
            log.warning("%d dividend(s) due but the issuer service is not configured", len(due))
            return []
        sent: list[int] = []
        for d in due:
            row = db.one("UPDATE studio.dividends SET status='approved' WHERE id=%s AND status='scheduled' "
                         "AND pay_after <= %s RETURNING id, company_id, policy_id, total_units, approved_by",
                         (d["id"], now))
            if not row:
                continue  # vetoed meanwhile
            actor = row["approved_by"] or f"policy:{row['policy_id']}"
            self._audit(actor, "dividend_auto_approved", str(row["id"]), company_id=row["company_id"],
                        dividend_id=row["id"], total_units=int(row["total_units"]))
            try:
                issuer.post("/dividend", {"dividend_id": row["id"]})
                sent.append(row["id"])
            except IssuerError as e:
                db.exec("UPDATE studio.dividends SET status='scheduled', pay_after=%s, note=%s "
                        "WHERE id=%s AND status='approved'", (now + RETRY_AFTER, f"issuer: {e}"[:300], row["id"]))
                self._audit(actor, "dividend_auto_approved_issuer_error", str(row["id"]), error=str(e)[:300])
        return sent

    def tick(self, now: datetime | None = None) -> dict:
        return {"declared": self.declare(now), "executed": self.execute_due(now)}

    # background loop in the API process
    def start(self, interval_s: float) -> None:
        if interval_s <= 0 or self._thread is not None or self.ctx.db is None:
            return

        def loop() -> None:
            while not self._stop.wait(interval_s):
                try:
                    self.tick()
                except Exception:  # DB down etc.: try again next time
                    log.exception("dividend automation tick failed")

        self._thread = threading.Thread(target=loop, name="dividend-automation", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


def interval_from_env() -> float:
    try:
        return max(0.0, float(os.environ.get("DIVIDEND_AUTOMATION_SECONDS", "60")))
    except ValueError:
        return 60.0


# ------------------------------------------------------------------ HTTP
class _Body(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")


class PolicyBody(_Body):
    kind: Literal["payout_ratio", "fixed"]
    ratio_pct: float | None = Field(default=None, gt=0, le=100)
    fixed_maud: float | None = Field(default=None, gt=0, le=10**9)
    max_maud_per_round: float = Field(gt=0, le=10**9)
    frequency: Literal["monthly", "quarterly"] = "quarterly"
    veto_hours: int = Field(default=24, ge=1, le=168)


class ReasonBody(_Body):
    reason: str = Field(default="", max_length=1000)


def check_money(label: str, v: float | None) -> None:
    """A$ amounts of a rule: at least 1 cent and whole cents (anything smaller would round to A$0.00 for ever)."""
    d = Decimal(str(v))
    if d < Decimal("0.01"):
        raise HTTPException(422, f"{label} must be at least A$0.01")
    if d != d.quantize(Decimal("0.01")):
        raise HTTPException(422, f"{label} can have at most 2 decimals (whole cents)")


def build_dividend_policy_router(ctx, automation: DividendAutomation) -> APIRouter:
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

    def audit(sess: Session, role: str, action: str, c: dict, **detail) -> None:
        ctx.need_db().audit(sess.actor, action, c["ticker"], company_id=c["id"], role=role, **detail)

    def policy_of(cid: int) -> dict | None:
        return ctx.need_db().one(f"SELECT {POLICY_COLS} FROM studio.dividend_policies WHERE company_id=%s", (cid,))

    def dividends_of(cid: int) -> list[dict]:
        rows = ctx.need_db().all(
            f"SELECT {DIV_COLS}, u.cadence, u.period_end FROM studio.dividends d "
            "LEFT JOIN studio.updates u ON u.id=d.update_id WHERE d.company_id=%s ORDER BY d.created_at DESC, d.id DESC "
            "LIMIT 50", (cid,))
        out = []
        for x in rows:
            v = {k: x[k] for k in x if k not in ("cadence", "period_end")}
            v["total_maud"] = int(x["total_units"]) / UNITS
            v["period_label"] = ud.period_label(x["cadence"], x["period_end"]) if x.get("period_end") else None
            out.append(v)
        return jsonable(out)

    def view(c: dict, role: str) -> dict:
        p = policy_of(c["id"])
        nxt = None
        if p and p["status"] == "active":
            # the next period that has not been published yet (the current one may already be paid / announced)
            last = ctx.need_db().one("SELECT max(period_end) AS e FROM studio.updates WHERE company_id=%s "
                                     "AND cadence=%s AND status IN ('publishing','published')",
                                     (c["id"], p["frequency"]))
            today = datetime.now(timezone.utc).date()
            end = next_period_end(p["frequency"], max(today, last["e"] + timedelta(days=1)) if last and last["e"]
                                  else today)
            nxt = {"period_end": end.isoformat(), "period_label": ud.period_label(p["frequency"], end),
                   "cadence": p["frequency"], "veto_hours": p["veto_hours"],
                   "max_maud": float(p["max_maud_per_round"])}
        # announced (scheduled) payments are paid when their window ends even if the rule is paused or changed
        # afterwards; the web app says so and offers to cancel them (veto, one by one)
        announced = ctx.need_db().all("SELECT id, total_units, pay_after FROM studio.dividends WHERE company_id=%s "
                                      "AND status='scheduled' ORDER BY pay_after, id", (c["id"],))
        return jsonable({"ticker": c["ticker"], "company_id": c["id"], "you": role,
                         "live": c["status"] in ONCHAIN_STATUSES and bool(c.get("local_token")),
                         "policy": policy_view(p), "next": nxt, "dividends": dividends_of(c["id"]),
                         "announced": [{"id": x["id"], "total_maud": int(x["total_units"]) / UNITS,
                                        "pay_after": x["pay_after"]} for x in announced]})

    @r.get("/v1/companies/{tk}/dividend-policy")
    def get_policy(tk: str, sess: Session = Depends(require_user)):
        c = company(tk)
        return view(c, authz.check(sess, c["id"]))

    @r.put("/v1/companies/{tk}/dividend-policy")
    def put_policy(tk: str, body: PolicyBody, sess: Session = Depends(require_user)):
        db = ctx.need_db()
        c = company(tk)
        role = authz.check(sess, c["id"])
        if c["status"] not in ONCHAIN_STATUSES or not c.get("local_token"):
            raise HTTPException(409, "a dividend policy can be set once the shares are issued")
        if body.kind == "payout_ratio" and body.ratio_pct is None:
            raise HTTPException(422, "ratio_pct is required for a payout ratio")
        if body.kind == "fixed" and body.fixed_maud is None:
            raise HTTPException(422, "fixed_maud is required for a fixed amount")
        check_money("the most per payment", body.max_maud_per_round)
        if body.kind == "fixed":
            check_money("the fixed amount", body.fixed_maud)
            if Decimal(str(body.fixed_maud)) > Decimal(str(body.max_maud_per_round)):
                raise HTTPException(422, "the fixed amount cannot be more than the most per payment")
        ratio = body.ratio_pct if body.kind == "payout_ratio" else None
        fixed = body.fixed_maud if body.kind == "fixed" else None
        prev = policy_of(c["id"])
        if prev and prev["status"] == "pending_approval":
            raise HTTPException(409, "the policy is waiting for approval; wait for the decision before changing it")
        row = db.one(
            "INSERT INTO studio.dividend_policies (company_id, kind, ratio_pct, fixed_maud, max_maud_per_round, "
            "frequency, veto_hours, status, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,'draft',%s) "
            "ON CONFLICT (company_id) DO UPDATE SET kind=EXCLUDED.kind, ratio_pct=EXCLUDED.ratio_pct, "
            "fixed_maud=EXCLUDED.fixed_maud, max_maud_per_round=EXCLUDED.max_maud_per_round, "
            "frequency=EXCLUDED.frequency, veto_hours=EXCLUDED.veto_hours, status='draft', reason=NULL, "
            "active_since=NULL, approved_by=NULL, approved_at=NULL, created_by=EXCLUDED.created_by, updated_at=now() "
            f"RETURNING {POLICY_COLS}",
            (c["id"], body.kind, ratio, fixed, body.max_maud_per_round, body.frequency, body.veto_hours, sess.actor))
        audit(sess, role, "dividend_policy_saved", c, policy_id=row["id"], kind=body.kind, ratio_pct=ratio,
              fixed_maud=fixed, max_maud_per_round=body.max_maud_per_round, frequency=body.frequency,
              veto_hours=body.veto_hours, previous=prev["status"] if prev else None)
        return view(c, role)

    def move(tk: str, sess: Session, frm: tuple[str, ...], to: str, action: str, extra: str = "") -> dict:
        db = ctx.need_db()
        c = company(tk)
        role = authz.check(sess, c["id"])
        row = db.one(f"UPDATE studio.dividend_policies SET status=%s, updated_at=now(){extra} "
                     "WHERE company_id=%s AND status = ANY(%s) RETURNING id", (to, c["id"], list(frm)))
        if not row:
            p = policy_of(c["id"])
            raise HTTPException(409 if p else 404, f"policy is {p['status']}" if p else "no dividend policy yet")
        audit(sess, role, action, c, policy_id=row["id"])
        return view(c, role)

    @r.post("/v1/companies/{tk}/dividend-policy/submit")
    def submit_policy(tk: str, sess: Session = Depends(require_user)):
        return move(tk, sess, ("draft", "rejected"), "pending_approval", "dividend_policy_submitted", ", reason=NULL")

    @r.post("/v1/companies/{tk}/dividend-policy/pause")
    def pause_policy(tk: str, sess: Session = Depends(require_user)):
        return move(tk, sess, ("active",), "paused", "dividend_policy_paused")

    @r.post("/v1/companies/{tk}/dividend-policy/resume")
    def resume_policy(tk: str, sess: Session = Depends(require_user)):
        # only updates published from now on count (nothing from the paused time is paid retroactively)
        return move(tk, sess, ("paused",), "active", "dividend_policy_resumed", ", active_since=now()")

    @r.post("/v1/admin/dividend-policies/{pid}/approve")
    def approve_policy(pid: int, sess: Session = Depends(require_admin)):
        db = ctx.need_db()
        row = db.one("UPDATE studio.dividend_policies SET status='active', approved_by=%s, approved_at=now(), "
                     "active_since=now(), reason=NULL, updated_at=now() WHERE id=%s AND status='pending_approval' "
                     f"RETURNING {POLICY_COLS}", (sess.actor, pid))
        if not row:
            p = db.one("SELECT status FROM studio.dividend_policies WHERE id=%s", (pid,))
            raise HTTPException(409 if p else 404, f"policy is {p['status']}" if p else "unknown policy")
        c = db.one("SELECT * FROM studio.companies WHERE id=%s", (row["company_id"],))
        audit(sess, "platform_admin", "dividend_policy_approved", c, policy_id=pid,
              terms={k: row[k] for k in ("kind", "ratio_pct", "fixed_maud", "max_maud_per_round", "frequency",
                                         "veto_hours")})
        return policy_view(row)

    @r.post("/v1/admin/dividend-policies/{pid}/reject")
    def reject_policy(pid: int, body: ReasonBody, sess: Session = Depends(require_admin)):
        db = ctx.need_db()
        row = db.one("UPDATE studio.dividend_policies SET status='rejected', reason=%s, updated_at=now() "
                     f"WHERE id=%s AND status='pending_approval' RETURNING {POLICY_COLS}",
                     (body.reason.strip() or "rejected by admin", pid))
        if not row:
            p = db.one("SELECT status FROM studio.dividend_policies WHERE id=%s", (pid,))
            raise HTTPException(409 if p else 404, f"policy is {p['status']}" if p else "unknown policy")
        c = db.one("SELECT * FROM studio.companies WHERE id=%s", (row["company_id"],))
        audit(sess, "platform_admin", "dividend_policy_rejected", c, policy_id=pid, reason=body.reason)
        return policy_view(row)

    @r.post("/v1/companies/{tk}/dividends/{did}/veto")
    def veto(tk: str, did: int, body: ReasonBody | None = None, sess: Session = Depends(require_user)):
        db = ctx.need_db()
        c = company(tk)
        role = authz.check(sess, c["id"])
        row = db.one("UPDATE studio.dividends SET status='vetoed', note=%s WHERE id=%s AND company_id=%s "
                     "AND status='scheduled' RETURNING id, total_units, update_id",
                     ((body.reason.strip() if body else "") or "cancelled by the company", did, c["id"]))
        if not row:
            d = db.one("SELECT status FROM studio.dividends WHERE id=%s AND company_id=%s", (did, c["id"]))
            raise HTTPException(409 if d else 404, f"dividend is {d['status']}; only an announced payment "
                                                   "can be cancelled" if d else "unknown dividend")
        db.exec("INSERT INTO studio.events (company_id, kind, data) VALUES (%s,'dividend_vetoed',%s)",
                (c["id"], Jsonb({"dividend_id": did, "total_units": int(row["total_units"]),
                                 "update_id": row["update_id"], "by": sess.actor})))
        audit(sess, role, "dividend_vetoed", c, dividend_id=did, total_units=int(row["total_units"]),
              reason=body.reason if body else "")
        return view(c, role)

    @r.post("/v1/admin/dividends/run-automation")
    def run_automation(sess: Session = Depends(require_admin)):
        """Run one automation pass now (normally every DIVIDEND_AUTOMATION_SECONDS). Only declares for published
        updates under an approved policy and pays rows whose veto window has passed: it never skips the window."""
        out = automation.tick()
        ctx.need_db().audit(sess.actor, "dividend_automation_run", None, role="platform_admin", **out)
        return out

    # -------------------------------------------------------------- investor ledger
    def ledger(wallets: list[str]) -> dict:
        low = [w.lower() for w in wallets if w]
        if not low:
            return {"wallets": [], "paid": [], "upcoming": [], "total_maud": 0}
        db = ctx.need_db()
        paid = db.all("SELECT e.at, e.tx_hash, e.chain, e.data, c.ticker, c.name FROM studio.events e "
                      "JOIN studio.companies c ON c.id=e.company_id WHERE e.kind='dividend_claimed' "
                      "AND lower(e.data->>'wallet') = ANY(%s) ORDER BY e.at DESC, e.id DESC LIMIT 1000", (low,))
        rows = [{"at": x["at"], "ticker": x["ticker"], "company": x["name"], "tx_hash": x["tx_hash"],
                 "wallet": (x["data"] or {}).get("wallet"), "dividend_id": (x["data"] or {}).get("dividend_id"),
                 "amount_maud": int((x["data"] or {}).get("amount") or 0) / UNITS} for x in paid]
        ids = [x["company_id"] for x in db.all(
            "SELECT DISTINCT company_id FROM studio.dividends WHERE status='scheduled'")]
        names = {x["id"]: x for x in db.all("SELECT id, ticker, name FROM studio.companies WHERE id = ANY(%s)",
                                            (ids or [0],))}
        up = [{**u, "ticker": names[cid]["ticker"], "company": names[cid]["name"]}
              for cid, us in upcoming_for(db, ids, low).items() for u in us]
        up.sort(key=lambda u: u["pay_after"] or "")
        return jsonable({"wallets": wallets, "paid": rows, "upcoming": up,
                         "total_maud": round(sum(x["amount_maud"] for x in rows), 6)})

    @r.get("/v1/me/dividends")
    def my_dividends(sess: Session = Depends(require_user)):
        return ledger(acct.account_wallets(ctx.need_db(), sess.account_id, sess.address))

    @r.get("/v1/demo/dividends")
    def demo_dividends():
        w = s.demo_holder or s.demo_wallet
        if not w:
            row = ctx.need_db().one("SELECT wallet FROM studio.holders GROUP BY wallet "
                                    "ORDER BY count(DISTINCT company_id) DESC, wallet LIMIT 1")
            w = row["wallet"] if row else ""
        return {**ledger([w] if w else []), "demo": True}

    return r
