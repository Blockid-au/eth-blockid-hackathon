"""Valuation v5 — finalise the value before shares are proposed (docs/PLAN-VALUATION-V5.md §7, §8.3;
docs/DECISIONS-V5.md #5, #7, #8). Full request / response shapes: docs/VALUATION-V5-API.md.

Everything here answers 404 while VALUATION_V5=0 (and the guards used by routes.py / offerings.py do nothing).

Endpoints
  GET  /v1/studio/valuations/{vid}/tokenisation                 owner / admin  -> TokenisationView
  POST /v1/studio/valuations/{vid}/finalise                     owner / platform admin
       {price_per_share_aud?, note?, reason?, allow_low_confidence?, override_reason?}
       -> 200 TokenisationView (final written) | 202 TokenisationView (price beyond +/-20 %: PriceRequest pending)
  POST /v1/studio/valuations/{vid}/price-requests/{rid}/cancel  requester / platform admin
  GET  /v1/admin/price-requests?status=pending                  platform admin (queue)
  POST /v1/admin/price-requests/{rid}/approve  {note?}          platform admin, never the requester (four-eyes)
  POST /v1/admin/price-requests/{rid}/reject   {reason}         platform admin
  GET  /v1/admin/valuations/{vid}/assumptions                   platform admin -> {current, allowed, changes}
  PATCH /v1/admin/valuations/{vid}/assumptions {changes, reason} platform admin (four-eyes once finalised)
  POST /v1/admin/assumption-changes/{id}/approve | /reject      a second platform admin
  POST /v1/admin/valuations/{vid}/rerun-v5 {reason}             platform admin: re-value a stored v1-v4 report with
                                                                the v5 methods (deterministic; back to review)

Rules (owner decisions)
  * price: recommended = tokenisation proposal (stage default A$0.10 idea/pre-seed, 0.25 seed, 1.00 later, share count
    rounded to 3 significant figures). The founder may choose a price within +/-20 % with a note; beyond that a
    written reason (>= 20 chars) and a platform admin's approval (never the requester's own); hard limits 0.2x-5x.
    Recommended and chosen are always both stored and shown.
  * confidence: minimum medium; a platform admin can override low with a reason (>= 10 chars).
  * validity: 90 days; a final is "stale" when the report changed after finalising (hash differs) -> re-finalise.
  * assumptions (WACC, multiples, weights, ratings, stage, industry): platform admin only, reason >= 10 chars, audit
    row per change, deterministic recompute, status back to waiting_approval; after finalising a second admin must
    approve (the change then clears the final). Refused once a company exists (its report hash may be anchored).
"""
from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from ..tools import stage as stage_tools
from ..tools.valuation_params import (
    BERKUS_KEYS,
    CLASSES,
    RFS_KEYS,
    params,
    require_final,
    v5_enabled,
)
from .auth import COOKIE, Session
from .db import jsonable
from .report_hash import report_hash_from_row

log = logging.getLogger(__name__)

CONF_RANK = {"low": 0, "medium": 1, "high": 2}
FINAL_VERSION = 1


# ------------------------------------------------------------------ bodies
class Body(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")


class FinaliseBody(Body):
    price_per_share_aud: float | None = Field(default=None, gt=0, le=1_000_000)
    note: str = Field(default="", max_length=500)
    reason: str = Field(default="", max_length=2000)
    allow_low_confidence: bool = False
    override_reason: str = Field(default="", max_length=1000)


class NoteBody(Body):
    note: str = Field(default="", max_length=500)


class ReasonBody(Body):
    reason: str = Field(default="", max_length=1000)


class AssumptionsBody(Body):
    changes: dict[str, Any] = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=10, max_length=1000)


# ------------------------------------------------------------------ pure helpers
def _now() -> datetime:
    return datetime.now(UTC)


def _dt(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    if isinstance(v, str) and v:
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def triangulation(row: dict) -> dict:
    return (((row or {}).get("result") or {}).get("svi") or {}).get("triangulation") or {}


def is_v5(row: dict) -> bool:
    return triangulation(row).get("version") == "v5"


def final_state(row: dict, now: datetime | None = None) -> str:
    """none | valid | expired | stale (the report changed after finalising)."""
    f = (row or {}).get("final")
    if not f:
        return "none"
    if report_hash_from_row(row) != f.get("report_hash"):
        return "stale"
    until = _dt(f.get("valid_until"))
    if until is None or until <= (now or _now()):
        return "expired"
    return "valid"


def price_rules(p) -> dict:
    return {"free_band_pct": round(float(p["price_free_band"]) * 100, 2),
            "hard_min_ratio": float(p["price_hard_min_ratio"]), "hard_max_ratio": float(p["price_hard_max_ratio"]),
            "validity_days": int(p["final_valid_days"]), "min_confidence": p["final_min_confidence"],
            "default_price_by_stage": {s: stage_tools.recommended_share_price(s) for s in stage_tools.STAGES}}


def build_final(row: dict, price: float, *, actor: str, note: str = "", reason: str | None = None,
                request_id: int | None = None, approved_by: str | None = None, low_override: dict | None = None,
                now: datetime | None = None) -> dict:
    """The frozen ValuationFinal for a chosen price. Raises ValueError (plain words) when out of bounds."""
    tri = triangulation(row)
    prop = tri.get("tokenisation") or {}
    p = params(tri.get("params_version") or "v5")
    svi = (row.get("result") or {}).get("svi") or {}
    value = float(svi.get("valuation_mid_aud") or prop.get("pre_money_aud") or 0)
    low = float(svi.get("valuation_low_aud") or prop.get("low_aud") or 0)
    high = float(svi.get("valuation_high_aud") or prop.get("high_aud") or 0)
    if value <= 0:
        raise ValueError("the valuation has no value to finalise")
    rec = float(prop.get("recommended_price_per_share_aud") or 0)
    if rec <= 0:
        raise ValueError("the valuation has no recommended price")
    fd = prop.get("fd_shares_existing")
    total = int(fd) if fd else int(round(value / price))
    lo_b, hi_b = p["share_bounds"]
    if not lo_b <= total <= hi_b:
        raise ValueError(f"that price gives {total:,} shares; the share count must be between {lo_b:,} and {hi_b:,}")
    now = now or _now()
    dev = (price / rec - 1) * 100
    stage = (tri.get("stage") or {}).get("stage") or prop.get("stage")
    proj = tri.get("projections") or {}
    rev = next((m.get("inputs", {}).get("revenue_aud") for m in tri.get("methods") or []
                if m.get("method") == "revenue_multiple"), None)
    return {
        "version": FINAL_VERSION, "valuation_id": row["id"], "report_hash": report_hash_from_row(row),
        "formula_version": tri.get("version"), "params_version": tri.get("params_version"),
        "stage": stage, "valuation_class": tri.get("valuation_class"), "confidence": tri.get("confidence"),
        "pre_money_aud": value, "low_aud": low, "high_aud": high,
        "recommended_price_per_share_aud": rec, "price_per_share_aud": round(price, 4),
        "price_deviation_pct": round(dev, 2), "price_note": note or None, "price_reason": reason or None,
        "price_request_id": request_id, "price_approved_by": approved_by,
        "total_shares": total, "fd_shares_existing": int(fd) if fd else None,
        "implied_value_aud": round(price * total, 2),
        "offer_price_low_aud": round(low / total, 4), "offer_price_high_aud": round(max(value / total, price), 4),
        "revenue_used_aud": rev, "based_on_projections": bool(proj), "projection_sha256": proj.get("sha256"),
        "finalised_by": actor, "finalised_at": now.isoformat(),
        "valid_until": (now + timedelta(days=int(p["final_valid_days"]))).isoformat(),
        "low_confidence_override": low_override,
    }


def check_price(rec: float, price: float, p) -> str:
    """'free' (within the band) | 'approval' (beyond, needs admin) | raises ValueError beyond the hard limits."""
    ratio = price / rec
    if ratio < p["price_hard_min_ratio"] or ratio > p["price_hard_max_ratio"]:
        raise ValueError(f"the price must stay between {p['price_hard_min_ratio']:g}x and "
                         f"{p['price_hard_max_ratio']:g}x the recommended A${rec:,.4f}")
    return "free" if abs(ratio - 1) <= p["price_free_band"] + 1e-9 else "approval"


# ------------------------------------------------------------------ guards used by routes.py / offerings.py
def company_create_guard(db, v: dict, body) -> dict | None:
    """POST /v1/studio/companies with VALUATION_V5=1: defaults from a valid final; a different price / share count
    -> 422; expired / stale final -> 409; no final -> None (unchanged behaviour) unless VALUATION_V5_REQUIRE_FINAL=1.
    Returns {share_price_aud, total_shares, valuation_aud} or None."""
    if not v5_enabled():
        return None
    st = final_state(v)
    if st == "none":
        if require_final():
            raise HTTPException(409, "finalise the valuation first (value, price per share and share count)")
        return None
    if st == "expired":
        raise HTTPException(409, "the finalised value has expired (valid 90 days): finalise it again")
    if st == "stale":
        raise HTTPException(409, "the valuation changed after it was finalised: finalise it again")
    f = v["final"]
    sent = getattr(body, "model_fields_set", set())
    if "share_price_aud" in sent and abs(float(body.share_price_aud) - float(f["price_per_share_aud"])) > 5e-5:
        raise HTTPException(422, f"the finalised price is A${f['price_per_share_aud']:,.4f} per share; change it "
                                 "through finalise (POST /v1/studio/valuations/{id}/finalise)")
    if body.total_shares is not None and int(body.total_shares) != int(f["total_shares"]):
        raise HTTPException(422, f"the finalised share count is {int(f['total_shares']):,}; change it through "
                                 "finalise")
    return {"share_price_aud": float(f["price_per_share_aud"]), "total_shares": int(f["total_shares"]),
            "valuation_aud": float(f["pre_money_aud"]), "final": f}


def company_final(db, c: dict) -> tuple[dict | None, dict | None]:
    """(valuation row, final) for a company (None, None when v5 is off or the company has no valuation)."""
    if not v5_enabled() or not c.get("valuation_id"):
        return None, None
    row = db.one("SELECT id, url, status, result, self_reported, final, created_at, updated_at FROM studio.valuations "
                 "WHERE id=%s", (c["valuation_id"],))
    return row, (row or {}).get("final")


def offering_default_price(db, c: dict, mark, mark_at):
    """(default offer price, final or None): the final price when it is newer than the latest mark."""
    row, f = company_final(db, c)
    if not f:
        return mark, None
    fat = _dt(f.get("finalised_at"))
    mat = _dt(mark_at) if not isinstance(mark_at, datetime) else mark_at
    if mat is not None and mat.tzinfo is None:
        mat = mat.replace(tzinfo=UTC)
    if fat is not None and (mat is None or fat >= mat):
        return Decimal(str(f["price_per_share_aud"])), f
    return mark, f


def kpi_revenue_annual(db, company_id: int) -> tuple[float | None, str | None]:
    """Latest revenue KPI, annualised by its cadence (weekly x52, monthly x12, quarterly x4, annual x1)."""
    row = db.one("SELECT value, cadence, period_end FROM studio.kpi_values WHERE company_id=%s AND metric='revenue' "
                 "ORDER BY period_end DESC, id DESC LIMIT 1", (company_id,))
    if not row:
        return None, None
    k = {"weekly": 52, "monthly": 12, "quarterly": 4, "annual": 1}.get(row.get("cadence") or "monthly", 12)
    return float(row["value"]) * k, str(row["period_end"])


def offering_submit_guard(db, c: dict, price) -> None:
    """409 with a plain reason when the finalised value can no longer back an offering (plan §7.2)."""
    if not v5_enabled():
        return
    row, f = company_final(db, c)
    if not f:
        if require_final():
            raise HTTPException(409, "finalise the valuation before offering shares")
        return
    st = final_state(row)
    if st == "expired":
        raise HTTPException(409, "the finalised value has expired (valid 90 days): revaluation needed")
    if st == "stale":
        raise HTTPException(409, "the valuation changed after it was finalised: finalise it again")
    cur = (triangulation(row).get("stage") or {}).get("stage")
    if cur and f.get("stage") and cur != f["stage"]:
        raise HTTPException(409, f"the stage changed since finalising ({f['stage']} -> {cur}): revaluation needed")
    newer = db.one("SELECT id FROM studio.valuations WHERE url=%s AND status='approved' AND id<>%s AND "
                   "created_at > %s LIMIT 1", (row["url"], row["id"], row.get("created_at") or _now()))
    if newer:
        raise HTTPException(409, "a newer approved valuation of this business exists: revaluation needed")
    rev_used = f.get("revenue_used_aud")
    kpi, period = kpi_revenue_annual(db, c["id"])
    p = params(f.get("params_version") or "v5")
    if rev_used and kpi is not None and abs(kpi / float(rev_used) - 1) > p["revalue_kpi_deviation"]:
        raise HTTPException(409, f"latest reported revenue (A${kpi:,.0f} a year, period ending {period}) differs more "
                                 f"than 25 % from the revenue in the valuation (A${float(rev_used):,.0f}): "
                                 "revaluation needed")
    total = int(c.get("total_shares") or f.get("total_shares") or 0)
    if total > 0 and float(price) > float(f["high_aud"]) / total + 5e-5:
        raise HTTPException(409, f"the price is above the top of the finalised range (A${float(f['high_aud']) / total:,.4f}"
                                 " per share)")


def pack_valuation_extra(db, c: dict) -> dict:
    """Extra keys for the offering information pack's `valuation` block (empty when v5 is off / no v5 report)."""
    row, f = company_final(db, c)
    if row is None or not is_v5(row):
        return {}
    tri = triangulation(row)
    proj = tri.get("projections") or {}
    return {"final": f, "football_field": tri.get("football_field") or [],
            "based_on_projections": bool(proj), "projection_sha256": proj.get("sha256"),
            "projection_attested_by": proj.get("attested_by"), "projection_attested_at": proj.get("attested_at"),
            "projection_label": proj.get("label"), "valuation_class": tri.get("valuation_class")}


# ------------------------------------------------------------------ assumptions
def allowed_assumptions() -> dict[str, Any]:
    from ..tools.market_data import snapshot
    from ..tools.valuation_params import MARKET_DATASET

    out: dict[str, Any] = {
        "stage": list(stage_tools.STAGES), "valuation_class": list(CLASSES),
        "industry": list(snapshot(MARKET_DATASET).industry_keys()), "confirm_startup_factors": [True],
        "dcf.rf": [0.0, 0.15], "dcf.beta_u": [0.3, 3.0], "dcf.erp": [0.02, 0.15], "dcf.crp": [0.0, 0.15],
        "dcf.size_premium": [0.0, 0.15], "dcf.tax_rate": [0.0, 0.5], "dcf.g": [-0.02, 0.03], "dcf.rate": [0.05, 0.9],
        "dcf.terminal": ["gordon", "exit"], "dcf.exit_multiple": [1.0, 40.0], "ebitda.multiple": [1.0, 40.0],
        "vc.target_multiple": [2.0, 100.0], "vc.years_to_exit": [1.0, 10.0], "vc.exit_multiple": [0.3, 40.0],
        "scorecard.base_pre_money": [50_000.0, 5e9], "dlom": [0.0, 0.6], "competition": [-2, 2],
    }
    out.update({f"berkus.{k}": [0.0, 100.0] for k in BERKUS_KEYS})
    out.update({f"rfs.{k}": [-2, 2] for k in RFS_KEYS})
    out.update({f"weights.{m}": [0.0, 10.0] for m in ("market_anchor", "revenue_multiple", "ebitda_multiple",
                                                     "precedents", "dcf", "first_chicago", "vc_method", "scorecard",
                                                     "berkus", "rfs", "stage_scorecard")})
    return out


def check_assumption(path: str, value: Any, allowed: dict) -> Any:
    if path not in allowed:
        raise ValueError(f"{path}: not an editable assumption")
    rule = allowed[path]
    if path in ("stage", "valuation_class", "industry", "dcf.terminal"):
        if value not in rule:
            raise ValueError(f"{path}: must be one of {rule}")
        return value
    if path == "confirm_startup_factors":
        if value is not True:
            raise ValueError("confirm_startup_factors: send true")
        return True
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(float(value)):
        raise ValueError(f"{path}: must be a number")
    lo, hi = rule
    if not lo <= float(value) <= hi:
        raise ValueError(f"{path}: must be between {lo:g} and {hi:g}")
    if path.startswith("rfs.") or path == "competition":
        if float(value) != int(value):
            raise ValueError(f"{path}: whole steps only (-2..+2)")
        return int(value)
    return float(value)


def apply_assumption(vi: dict, tri: dict, path: str, value: Any, actor: str, reason: str) -> None:
    """Write one checked change into valuation_inputs (in place)."""
    if path == "stage":
        vi["stage_override"] = stage_tools.override_stage(
            {k: v for k, v in (tri.get("stage") or {}).items() if k in stage_tools.StageDecision.model_fields}
            or None, value, actor, reason[:200]).model_dump()
    elif path == "valuation_class":
        vi["class_override"] = value
    elif path == "industry":
        vi.update(industry=value, industry_basis="human", industry_rationale=f"set by {actor}: {reason[:200]}")
    elif path == "confirm_startup_factors":
        vi.update(factors_basis="human", factors_confirmed_by=actor)
    else:
        a = dict(vi.get("assumptions") or {})
        a[path] = value
        vi["assumptions"] = a


# ------------------------------------------------------------------ re-run + persistence
def rerun(db, row: dict, vi: dict, *, actor: str, reason: str, audit_action: str, **audit_detail) -> dict:
    """Deterministic v5 re-valuation of a stored row with new valuation_inputs; persisted; approved -> back to
    waiting_approval when the value moves (or always for assumption changes: move_threshold 0)."""
    from ..agents.valuation_agent import rerun_methods

    res = {**(row.get("result") or {}), "self_reported": row.get("self_reported")}
    before = float(((res.get("svi") or {}).get("valuation_mid_aud")) or 0)
    vi = {**vi, "rerun_at": _now().isoformat(), "rerun_by": actor}
    res["valuation_inputs"] = vi
    patch = rerun_methods(res)
    if patch is None:
        raise HTTPException(409, "this valuation has no stored scores to re-value")
    patch["valuation_methods"] = patch["svi"].get("triangulation")  # the API's copy of svi.triangulation
    db.merge_result(row["id"], patch)
    after = float(patch["svi"].get("valuation_mid_aud") or 0)
    moved = (after / before - 1) if before else 1.0
    new = db.get_valuation(row["id"])
    db.audit(actor, audit_action, row["id"], reason=reason, value_before=before, value_after=after,
             report_hash=report_hash_from_row(new), **audit_detail)
    return {"row": new, "before": before, "after": after, "moved": moved}


def company_exists(db, vid: str) -> bool:
    return bool(db.one("SELECT 1 AS x FROM studio.companies WHERE valuation_id=%s AND status NOT IN "
                       "('rejected','failed') LIMIT 1", (vid,)))


# ------------------------------------------------------------------ router
def build_finalise_router(ctx) -> APIRouter:
    r = APIRouter()

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

    def need_v5() -> None:
        if not v5_enabled():
            raise HTTPException(404, "valuation v5 is not enabled")

    def load(vid: str, sess: Session) -> dict:
        need_v5()
        db = ctx.need_db()
        row = db.get_valuation(vid)
        if not row:
            raise HTTPException(404, "unknown valuation")
        if not (sess.is_admin and not sess.must_change) and \
                (row.get("requested_by") or "").lower() != sess.actor.lower():
            raise HTTPException(403, "not your valuation")
        return row

    def pending(vid: str) -> dict | None:
        return ctx.need_db().one("SELECT * FROM studio.valuation_price_requests WHERE valuation_id=%s AND "
                                 "status='pending'", (vid,))

    def view(row: dict, sess: Session | None = None) -> dict:
        tri = triangulation(row)
        p = params(tri.get("params_version") or "v5")
        st = final_state(row)
        pend = pending(row["id"])
        blockers: list[str] = []
        if row["status"] != "approved":
            blockers.append(f"the valuation is {row['status']}: an admin must approve it first")
        if not is_v5(row):
            blockers.append("the valuation uses an earlier formula: an admin can re-value it with the standard "
                            "methods (v5)")
        if tri.get("confidence") and CONF_RANK[tri["confidence"]] < CONF_RANK[p["final_min_confidence"]]:
            blockers.append(f"confidence is {tri['confidence']}: at least {p['final_min_confidence']} is needed "
                            "(a platform admin can override with a reason)")
        if st == "valid":
            blockers.append("already finalised; re-finalising needs a new approval or an expired final")
        if pend:
            blockers.append("a price change is waiting for a platform admin")
        hard = [b for b in blockers if not b.startswith("confidence")]
        return jsonable({"valuation_id": row["id"], "valuation_status": row["status"],
                         "confidence": tri.get("confidence"), "proposal": tri.get("tokenisation"),
                         "final": row.get("final"), "final_state": st, "pending_request": pend,
                         "can_finalise": not hard and (not blockers or bool(sess and sess.is_admin)),
                         "blockers": blockers, "rules": price_rules(p)})

    def write_final(row: dict, final: dict) -> dict:
        db = ctx.need_db()
        got = db.one("UPDATE studio.valuations SET final=%s, updated_at=updated_at WHERE id=%s AND status='approved' "
                     "RETURNING id", (Jsonb(jsonable(final)), row["id"]))
        if not got:
            raise HTTPException(409, "the valuation changed meanwhile; reload")
        return db.get_valuation(row["id"])

    # -------------------------------------------------------------- owner side
    @r.get("/v1/studio/valuations/{vid}/tokenisation")
    def get_tokenisation(vid: str, sess: Session = Depends(require_user)):
        return view(load(vid, sess), sess)

    @r.post("/v1/studio/valuations/{vid}/finalise")
    def finalise(vid: str, body: FinaliseBody, sess: Session = Depends(require_user)):
        from fastapi.responses import JSONResponse

        db = ctx.need_db()
        row = load(vid, sess)
        if row["status"] != "approved":
            raise HTTPException(409, f"the valuation is {row['status']}: it must be approved first")
        if not is_v5(row):
            raise HTTPException(409, "the valuation uses an earlier formula: ask an admin to re-value it (v5)")
        tri = triangulation(row)
        p = params(tri.get("params_version") or "v5")
        if final_state(row) == "valid":
            raise HTTPException(409, "already finalised; re-finalising needs a new approval (or wait for expiry)")
        if pending(vid):
            raise HTTPException(409, "a price change is already waiting for a platform admin")
        low_override = None
        if CONF_RANK[tri.get("confidence", "low")] < CONF_RANK[p["final_min_confidence"]]:
            if not (sess.is_admin and body.allow_low_confidence and len(body.override_reason.strip()) >= 10):
                raise HTTPException(409, f"confidence is {tri.get('confidence')}: at least "
                                         f"{p['final_min_confidence']} is needed (a platform admin can override with "
                                         "allow_low_confidence and a reason of at least 10 characters)")
            low_override = {"by": sess.actor, "reason": body.override_reason.strip()}
        rec = float((tri.get("tokenisation") or {}).get("recommended_price_per_share_aud") or 0)
        if rec <= 0:
            raise HTTPException(409, "the valuation has no recommended price")
        price = float(body.price_per_share_aud or rec)
        price = round(price, 4)
        try:
            kind = check_price(rec, price, p)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        note = body.note.strip()
        role = "platform_admin" if sess.is_admin else "owner"
        if kind == "free":
            if abs(price - rec) > 5e-5 and len(note) < 3:
                raise HTTPException(422, "add a short note explaining the price you chose")
            try:
                final = build_final(row, price, actor=sess.actor, note=note, low_override=low_override)
            except ValueError as e:
                raise HTTPException(422, str(e)) from None
            new = write_final(row, final)
            db.audit(sess.actor, "valuation_finalised", vid, role=role, price=price, recommended=rec,
                     deviation_pct=final["price_deviation_pct"], total_shares=final["total_shares"],
                     report_hash=final["report_hash"], low_confidence_override=bool(low_override))
            return view(new, sess)
        reason = body.reason.strip()
        if len(reason) < 20:
            raise HTTPException(422, f"a price more than {p['price_free_band']:.0%} from the recommended A${rec:,.4f} "
                                     "needs a written reason (at least 20 characters) and a platform admin's approval")
        try:
            build_final(row, price, actor=sess.actor)  # bounds check now, not at approval time
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        try:
            req = db.one("INSERT INTO studio.valuation_price_requests (valuation_id, status, recommended_price_aud, "
                         "requested_price_aud, deviation_pct, reason, note, requested_by, requested_role, report_hash, "
                         "low_override) VALUES (%s,'pending',%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                         (vid, Decimal(str(rec)), Decimal(str(price)), Decimal(str(round((price / rec - 1) * 100, 2))),
                          reason, note or None, sess.actor, role, report_hash_from_row(row),
                          Jsonb(low_override) if low_override else None))
        except UniqueViolation:
            raise HTTPException(409, "a price change is already waiting for a platform admin") from None
        db.audit(sess.actor, "valuation_price_requested", vid, role=role, request_id=req["id"], price=price,
                 recommended=rec, low_confidence_override=bool(low_override))
        return JSONResponse(view(db.get_valuation(vid), sess), status_code=202)

    @r.post("/v1/studio/valuations/{vid}/price-requests/{rid}/cancel")
    def cancel_request(vid: str, rid: int, sess: Session = Depends(require_user)):
        db = ctx.need_db()
        row = load(vid, sess)
        req = db.one("SELECT * FROM studio.valuation_price_requests WHERE id=%s AND valuation_id=%s", (rid, vid))
        if not req:
            raise HTTPException(404, "unknown price request")
        if not (sess.is_admin or req["requested_by"].lower() == sess.actor.lower()):
            raise HTTPException(403, "only the requester or a platform admin can cancel it")
        if not db.one("UPDATE studio.valuation_price_requests SET status='cancelled', decided_by=%s, decided_at=now() "
                      "WHERE id=%s AND status='pending' RETURNING id", (sess.actor, rid)):
            raise HTTPException(409, f"the request is {req['status']}")
        db.audit(sess.actor, "valuation_price_request_cancelled", vid, request_id=rid)
        return view(row, sess)

    # -------------------------------------------------------------- platform admin: price approvals
    @r.get("/v1/admin/price-requests")
    def list_requests(status: str = Query(default="pending", pattern="^(pending|approved|rejected|cancelled|all)$"),
                      sess: Session = Depends(require_admin)):
        need_v5()
        q = ("SELECT r.*, v.url, (SELECT c.name FROM studio.companies c WHERE c.valuation_id=v.id ORDER BY c.id DESC "
             "LIMIT 1) AS company_name, v.result->'profile'->>'company_name' AS business_name "
             "FROM studio.valuation_price_requests r JOIN studio.valuations v ON v.id=r.valuation_id ")
        rows = ctx.need_db().all(q + ("" if status == "all" else "WHERE r.status=%s ") + "ORDER BY r.id DESC LIMIT 200",
                                 None if status == "all" else (status,))
        return jsonable(rows)

    def load_request(rid: int) -> tuple[dict, dict]:
        db = ctx.need_db()
        req = db.one("SELECT * FROM studio.valuation_price_requests WHERE id=%s", (rid,))
        if not req:
            raise HTTPException(404, "unknown price request")
        return req, db.get_valuation(req["valuation_id"])

    @r.post("/v1/admin/price-requests/{rid}/approve")
    def approve_request(rid: int, body: NoteBody | None = None, sess: Session = Depends(require_admin)):
        need_v5()
        db = ctx.need_db()
        req, row = load_request(rid)
        if req["status"] != "pending":
            raise HTTPException(409, f"the request is {req['status']}")
        if req["requested_by"].lower() == sess.actor.lower():
            raise HTTPException(403, "a different platform admin must approve this price (four-eyes)")
        if row["status"] != "approved":
            raise HTTPException(409, f"the valuation is {row['status']}")
        if report_hash_from_row(row) != req["report_hash"]:
            raise HTTPException(409, "the valuation changed since the request; ask the business to request again")
        if final_state(row) == "valid":
            raise HTTPException(409, "the valuation is already finalised")
        low = req.get("low_override")
        tri = triangulation(row)
        p = params(tri.get("params_version") or "v5")
        if CONF_RANK[tri.get("confidence", "low")] < CONF_RANK[p["final_min_confidence"]] and low is None:
            raise HTTPException(409, "confidence is below the minimum and no override was given with the request")
        try:
            final = build_final(row, float(req["requested_price_aud"]), actor=req["requested_by"],
                                note=req.get("note") or "",
                                reason=req["reason"], request_id=rid, approved_by=sess.actor, low_override=low)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        if not db.one("UPDATE studio.valuation_price_requests SET status='approved', decided_by=%s, decided_at=now(), "
                      "decision_reason=%s WHERE id=%s AND status='pending' RETURNING id",
                      (sess.actor, (body.note if body else "") or None, rid)):
            raise HTTPException(409, "the request changed meanwhile; reload")
        new = write_final(row, final)
        db.audit(sess.actor, "valuation_price_approved", row["id"], role="platform_admin", request_id=rid,
                 price=final["price_per_share_aud"], recommended=final["recommended_price_per_share_aud"],
                 requested_by=req["requested_by"])
        db.audit(req["requested_by"], "valuation_finalised", row["id"], price=final["price_per_share_aud"],
                 total_shares=final["total_shares"], report_hash=final["report_hash"], approved_by=sess.actor)
        return view(new, sess)

    @r.post("/v1/admin/price-requests/{rid}/reject")
    def reject_request(rid: int, body: ReasonBody, sess: Session = Depends(require_admin)):
        need_v5()
        db = ctx.need_db()
        req, row = load_request(rid)
        if len(body.reason.strip()) < 5:
            raise HTTPException(422, "give a reason (at least 5 characters)")
        if not db.one("UPDATE studio.valuation_price_requests SET status='rejected', decided_by=%s, decided_at=now(), "
                      "decision_reason=%s WHERE id=%s AND status='pending' RETURNING id",
                      (sess.actor, body.reason.strip(), rid)):
            raise HTTPException(409, f"the request is {req['status']}")
        db.audit(sess.actor, "valuation_price_rejected", row["id"], request_id=rid, reason=body.reason.strip())
        return view(db.get_valuation(row["id"]), sess)

    # -------------------------------------------------------------- platform admin: assumptions (four-eyes)
    @r.get("/v1/admin/valuations/{vid}/assumptions")
    def get_assumptions(vid: str, sess: Session = Depends(require_admin)):
        from ..tools.valuation_v5 import current_assumptions

        row = load(vid, sess)
        changes = ctx.need_db().all("SELECT * FROM studio.valuation_assumption_changes WHERE valuation_id=%s "
                                    "ORDER BY id DESC LIMIT 200", (vid,))
        vi = (row.get("result") or {}).get("valuation_inputs") or {}
        return jsonable({"current": current_assumptions(triangulation(row)) if is_v5(row) else {},
                         "overrides": vi.get("assumptions") or {}, "allowed": allowed_assumptions(),
                         "changes": changes, "final_state": final_state(row)})

    def apply_changes(row: dict, changes: dict[str, Any], actor: str, reason: str, *, approved_by: str | None,
                      change_ids: list[int] | None = None) -> dict:
        db = ctx.need_db()
        tri = triangulation(row)
        vi = dict((row.get("result") or {}).get("valuation_inputs") or {})
        for path, value in changes.items():
            apply_assumption(vi, tri, path, value, actor, reason)
        h0 = report_hash_from_row(row)
        out = rerun(db, row, vi, actor=approved_by or actor, reason=reason, audit_action="valuation_assumption_changed",
                    changes=changes, changed_by=actor, approved_by=approved_by)
        new = out["row"]
        if new["status"] == "approved":
            db.set_valuation_status(row["id"], "waiting_approval")
        if new.get("final"):
            db.exec("UPDATE studio.valuations SET final=NULL WHERE id=%s", (row["id"],))
            db.audit(approved_by or actor, "valuation_final_cleared", row["id"], reason="assumption changed")
        h1 = report_hash_from_row(db.get_valuation(row["id"]))
        if change_ids:
            db.exec("UPDATE studio.valuation_assumption_changes SET status='applied', approved_by=%s, decided_at=now(),"
                    " report_hash_before=%s, report_hash_after=%s WHERE id = ANY(%s)", (approved_by, h0, h1, change_ids))
        else:
            from ..tools.valuation_v5 import current_assumptions

            cur = current_assumptions(tri) if is_v5(row) else {}
            for path, value in changes.items():
                old = cur.get(path)
                db.exec("INSERT INTO studio.valuation_assumption_changes (valuation_id, path, old, new, reason, actor, "
                        "status, report_hash_before, report_hash_after) VALUES (%s,%s,%s,%s,%s,%s,'applied',%s,%s)",
                        (row["id"], path, Jsonb(old), Jsonb(value), reason, actor, h0, h1))
        return out

    @r.patch("/v1/admin/valuations/{vid}/assumptions")
    def patch_assumptions(vid: str, body: AssumptionsBody, sess: Session = Depends(require_admin)):
        from ..tools.valuation_v5 import current_assumptions

        db = ctx.need_db()
        row = load(vid, sess)
        if row["status"] not in ("waiting_approval", "approved"):
            raise HTTPException(409, f"the valuation is {row['status']}")
        if not is_v5(row):
            raise HTTPException(409, "re-value this report with v5 first (POST /v1/admin/valuations/{id}/rerun-v5)")
        if company_exists(db, vid):
            raise HTTPException(409, "a company was already created from this valuation (its report hash may be "
                                     "anchored): revalue the company instead")
        allowed = allowed_assumptions()
        try:
            changes = {k: check_assumption(k, v, allowed) for k, v in body.changes.items()}
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        reason = body.reason.strip()
        if final_state(row) == "valid":  # four-eyes: a second platform admin applies it
            cur = current_assumptions(triangulation(row))
            ids = []
            for path, value in changes.items():
                got = db.one("INSERT INTO studio.valuation_assumption_changes (valuation_id, path, old, new, reason, "
                             "actor, status, report_hash_before) VALUES (%s,%s,%s,%s,%s,%s,'pending',%s) RETURNING id",
                             (vid, path, Jsonb(cur.get(path)), Jsonb(value), reason, sess.actor,
                              report_hash_from_row(row)))
                ids.append(got["id"])
            db.audit(sess.actor, "valuation_assumption_requested", vid, changes=changes, reason=reason, ids=ids)
            return jsonable({"applied": False, "pending": True, "change_ids": ids,
                             "valuation": triangulation(row)})
        out = apply_changes(row, changes, sess.actor, reason, approved_by=None)
        return jsonable({"applied": True, "pending": False, "change_ids": [],
                         "valuation": triangulation(db.get_valuation(vid)),
                         "value_before_aud": out["before"], "value_after_aud": out["after"]})

    @r.post("/v1/admin/assumption-changes/{cid}/approve")
    def approve_change(cid: int, sess: Session = Depends(require_admin)):
        need_v5()
        db = ctx.need_db()
        ch = db.one("SELECT * FROM studio.valuation_assumption_changes WHERE id=%s", (cid,))
        if not ch:
            raise HTTPException(404, "unknown change")
        if ch["status"] != "pending":
            raise HTTPException(409, f"the change is {ch['status']}")
        if ch["actor"].lower() == sess.actor.lower():
            raise HTTPException(403, "a different platform admin must approve this change (four-eyes)")
        row = db.get_valuation(ch["valuation_id"])
        if company_exists(db, row["id"]):
            raise HTTPException(409, "a company was already created from this valuation")
        if report_hash_from_row(row) != ch.get("report_hash_before"):
            raise HTTPException(409, "the valuation changed since this change was proposed; propose it again")
        out = apply_changes(row, {ch["path"]: ch["new"]}, ch["actor"], ch["reason"], approved_by=sess.actor,
                            change_ids=[cid])
        return jsonable({"applied": True, "valuation": triangulation(out["row"]),
                         "value_before_aud": out["before"], "value_after_aud": out["after"]})

    @r.post("/v1/admin/assumption-changes/{cid}/reject")
    def reject_change(cid: int, body: ReasonBody, sess: Session = Depends(require_admin)):
        need_v5()
        db = ctx.need_db()
        if not db.one("UPDATE studio.valuation_assumption_changes SET status='rejected', approved_by=%s, "
                      "decided_at=now() WHERE id=%s AND status='pending' RETURNING id", (sess.actor, cid)):
            raise HTTPException(409, "no pending change with that id")
        db.audit(sess.actor, "valuation_assumption_rejected", str(cid), reason=body.reason)
        return {"ok": True}

    @r.post("/v1/admin/valuations/{vid}/rerun-v5")
    def rerun_v5(vid: str, body: ReasonBody, sess: Session = Depends(require_admin)):
        db = ctx.need_db()
        row = load(vid, sess)
        if row["status"] not in ("waiting_approval", "approved"):
            raise HTTPException(409, f"the valuation is {row['status']}")
        if company_exists(db, vid):
            raise HTTPException(409, "a company was already created from this valuation (its report hash may be "
                                     "anchored): existing companies keep their report")
        if len(body.reason.strip()) < 10:
            raise HTTPException(422, "give a reason (at least 10 characters)")
        vi = dict((row.get("result") or {}).get("valuation_inputs") or {})
        out = rerun(db, row, vi, actor=sess.actor, reason=body.reason.strip(), audit_action="valuation_rerun_v5")
        if out["row"]["status"] == "approved":
            db.set_valuation_status(vid, "waiting_approval")
        if out["row"].get("final"):
            db.exec("UPDATE studio.valuations SET final=NULL WHERE id=%s", (vid,))
        return jsonable({"valuation": triangulation(db.get_valuation(vid)), "value_before_aud": out["before"],
                         "value_after_aud": out["after"], "status": db.get_valuation(vid)["status"]})

    return r
