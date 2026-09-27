"""Evaluation v5 Studio API: founder inputs v2, documents, re-score, metric verification, KPI revaluation suggestion.

docs/EVALUATION-V5-API.md §3 (shapes) · docs/PLAN-EVALUATION-V5.md §3 / Phase E3 / Phase E5.

Everything except GET /v1/studio/evaluation/config answers 404 while VALUATION_V5 is off. Re-scoring is
deterministic (tools/evaluation.py + tools/svi.apply_v5): no web search, no page fetch; the only model call is the
one-off deck extraction for a newly uploaded deck (agents/deck_reader.py). Anything that changes a valuation result
is refused (409) once a company was created from the valuation (its report hash may be anchored on-chain) — same
rule as the founding-team blend (studio/hr_store.apply_to_valuation).

Documents: the browser reads the file and sends text (deck / statements, <= 60k chars) or CSV text / rows (metrics,
<= 120 rows) plus the SHA-256 of the original bytes; the server stores the text (contacts redacted), never the file.
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
from collections import defaultdict
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..schemas import MetricValue, SelfReportedMetrics, SelfReportedMetricsV2
from ..tools import csv_metrics
from ..tools import stage as stage_tools
from .auth import COOKIE, Session
from .db import jsonable

log = logging.getLogger(__name__)

MAX_DOCS = 5
MAX_TEXT_CHARS = 60_000
BLENDABLE = ("waiting_approval", "approved")
DOC_KINDS = ("deck", "metrics_csv", "financials")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)")

# wizard field groups (§3.1): key -> (group, unit, first stage shown)
FIELD_GROUPS: dict[str, tuple[str, str, str]] = {
    **{k: ("revenue", u, st) for k, u, st in (
        ("revenue_ttm_aud", "AUD", "idea"), ("revenue_prev_ttm_aud", "AUD", "seed"), ("arr_aud", "AUD", "seed"),
        ("mrr_aud", "AUD", "seed"), ("mrr_6m_ago_aud", "AUD", "seed"), ("mrr_12m_ago_aud", "AUD", "seed"),
        ("revenue_model", "enum", "idea"), ("gmv_ttm_aud", "AUD", "seed"), ("take_rate_pct", "%", "seed"),
        ("gross_margin_pct", "%", "seed"), ("revenue_growth_yoy_pct", "%", "seed"))},
    **{k: ("customers", u, st) for k, u, st in (
        ("customers", "count", "idea"), ("paying_customers_12m_ago", "count", "seed"),
        ("active_users_monthly", "count", "idea"), ("active_users_daily", "count", "idea"),
        ("waitlist", "count", "idea"), ("pilots_paid", "count", "idea"), ("lois", "count", "idea"),
        ("contracted_backlog_aud", "AUD", "seed"), ("qualified_pipeline_aud", "AUD", "seed"),
        ("top_customer_share_pct", "%", "seed"), ("public_logos", "list", "idea"))},
    **{k: ("retention", u, "seed") for k, u in (
        ("logo_churn_monthly_pct", "%"), ("grr_pct", "%"), ("nrr_pct", "%"), ("m3_retention_pct", "%"),
        ("m12_retention_pct", "%"), ("nps", "score"))},
    **{k: ("efficiency", u, "seed") for k, u in (
        ("cash_aud", "AUD"), ("burn_monthly_aud", "AUD"), ("net_new_arr_12m_aud", "AUD"), ("cac_aud", "AUD"),
        ("arpa_monthly_aud", "AUD"), ("raised_to_date_aud", "AUD"), ("runway_months", "months"),
        ("employees", "count"))},
    **{k: ("market", u, "idea") for k, u in (
        ("target_customer", "text"), ("target_customer_count", "count"), ("target_count_source_url", "url"),
        ("annual_price_aud", "AUD"), ("geographies", "list"))},
    **{k: ("moat", u, "idea") for k, u in (
        ("patents", "list"), ("trademarks", "list"), ("licences", "list"), ("integrations_count", "count"),
        ("exclusive_contracts", "count"), ("moat_note", "text"))},
    **{k: ("round", u, "idea") for k, u in (
        ("last_round_type", "text"), ("last_round_date", "YYYY-MM"), ("last_round_post_money_aud", "AUD"),
        ("lead_investor", "text"))},
}


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MetricsBody(_Body):
    metrics: SelfReportedMetricsV2


class StagePreviewBody(_Body):
    metrics: SelfReportedMetricsV2 | None = None


class DocumentBody(_Body):
    kind: Literal["deck", "metrics_csv", "financials"]
    filename: str = Field(min_length=1, max_length=200)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    text: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    # metrics CSV: rows as string[][] or the CSV text itself (docs/EVALUATION-V5-API.md §3; the web app sends text)
    rows: list[list[str]] | str | None = None

    @field_validator("rows")
    @classmethod
    def _rows_size(cls, v):
        if isinstance(v, str) and len(v) > MAX_TEXT_CHARS:
            raise ValueError(f"CSV text too long (max {MAX_TEXT_CHARS:,} characters)")
        if isinstance(v, list) and len(v) > csv_metrics.MAX_ROWS + 1:
            raise ValueError(f"too many rows (max {csv_metrics.MAX_ROWS} months)")
        return v


class VerifyBody(_Body):
    metric: str = Field(min_length=2, max_length=60)
    level: Literal[2, 3]
    note: str = Field(default="", max_length=500)


def redact(text: str) -> str:
    return _PHONE.sub("[phone]", _EMAIL.sub("[email]", text or ""))


def self_reported_v2(raw: dict | None) -> dict | None:
    """Validate founder figures with the v2 schema when VALUATION_V5 is on, else with v1 (unchanged behaviour)."""
    if raw is None:
        return None
    model = SelfReportedMetricsV2 if stage_tools.v5_enabled() else SelfReportedMetrics
    return model.model_validate(raw).model_dump(exclude_none=True)


# ------------------------------------------------------------------ KPI history (approved, disclosed updates)
def kpi_candidates(db, company_id: int) -> dict[str, list[MetricValue]]:
    """Level-3 ("disclosed") metrics from KPI values of PUBLISHED business updates (studio/updates.py)."""
    rows = db.all(
        "SELECT k.metric, k.value, k.period_end, k.cadence FROM studio.kpi_values k JOIN studio.updates u "
        "ON u.company_id=k.company_id AND u.period_end=k.period_end AND u.cadence=k.cadence "
        "WHERE k.company_id=%s AND u.status='published' ORDER BY k.period_end", (company_id,))
    return kpis_to_metrics(rows)


def kpis_to_metrics(rows: list[dict]) -> dict[str, list[MetricValue]]:
    series: dict[tuple[str, str], list[tuple[date, float]]] = defaultdict(list)
    for r in rows:
        series[(r["metric"], r["cadence"])].append((r["period_end"], float(r["value"])))
    per_year = {"monthly": 12, "quarterly": 4, "annual": 1}
    out: dict[str, list[MetricValue]] = {}

    def add(metric: str, value: float, unit: str, as_of: date, note: str) -> None:
        out.setdefault(metric, []).append(MetricValue(value=round(value, 2), unit=unit, level=3, source="kpi",
                                                      as_of=as_of.isoformat()[:7], note=note))
    for cad, n in per_year.items():
        rev = sorted(series.get(("revenue", cad), []))
        if len(rev) >= n:
            add("revenue_ttm_aud", sum(v for _, v in rev[-n:]), "AUD", rev[-1][0],
                f"sum of the last {n} {cad} revenue figures in published updates")
            if len(rev) >= 2 * n:
                add("revenue_prev_ttm_aud", sum(v for _, v in rev[-2 * n:-n]), "AUD", rev[-n - 1][0],
                    "previous 12 months, published updates")
            gp = dict(series.get(("gross_profit", cad), []))
            if all(d in gp for d, _ in rev[-n:]) and sum(v for _, v in rev[-n:]) > 0:
                add("gross_margin_pct", sum(gp[d] for d, _ in rev[-n:]) / sum(v for _, v in rev[-n:]) * 100, "%",
                    rev[-1][0], "gross profit ÷ revenue, published updates")
            np_ = dict(series.get(("net_profit", cad), []))
            if cad == "monthly" and rev[-1][0] in np_ and np_[rev[-1][0]] < 0:
                add("burn_monthly_aud", -np_[rev[-1][0]], "AUD", rev[-1][0], "net loss of the latest month")
    for metric, key, unit in (("customers", "paying_customers", "count"), ("cash", "cash_aud", "AUD"),
                              ("headcount", "employees", "count")):
        latest = max((pt for (m, _), pts in series.items() if m == metric for pt in pts), default=None)
        if latest:
            add(key, latest[1], unit, latest[0], "latest published update")
    return out


def evidence_summary(analysis: dict) -> dict:
    """For the offering pack (E5): evaluation confidence, stage, verification-level summary and the level of the
    revenue figure used ("price based on self-reported revenue" when it is L1)."""
    metrics = analysis.get("metrics") or {}
    rev = metrics.get("arr_aud") or metrics.get("revenue_ttm_aud")
    counts: dict[str, int] = defaultdict(int)
    for mv in metrics.values():
        counts[stage_tools.LEVEL_LABELS.get(int(mv.get("level") or 0), "Missing")] += 1
    return {"confidence": analysis.get("confidence"), "stage": (analysis.get("stage") or {}).get("stage"),
            "trust_share": analysis.get("trust_share"), "levels": dict(counts),
            "revenue_level": int(rev["level"]) if rev else None,
            "revenue_level_label": stage_tools.LEVEL_LABELS.get(int(rev["level"])) if rev else None,
            "warning": "price based on self-reported revenue" if rev and int(rev["level"]) <= 1 else None}


# ------------------------------------------------------------------ router
def build_evaluation_router(ctx) -> APIRouter:
    from .company_admins import CompanyAuthz

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

    def need_v5() -> None:
        if not stage_tools.v5_enabled():
            raise HTTPException(404, "evaluation v5 is not enabled")

    def owned(vid: str, sess: Session) -> dict:
        db = ctx.need_db()
        row = db.get_valuation(vid)
        if not row:
            raise HTTPException(404, "unknown valuation")
        if not (sess.is_admin or ((row.get("requested_by") or "").lower() == sess.actor.lower())):
            raise HTTPException(403, "not your valuation")
        return row

    def unlocked(row: dict) -> None:
        if row["status"] not in BLENDABLE:
            raise HTTPException(409, f"valuation is {row['status']}; numbers can be added once the report is ready")
        if ctx.need_db().one("SELECT 1 AS x FROM studio.companies WHERE valuation_id=%s AND status NOT IN "
                             "('rejected','failed') LIMIT 1", (row["id"],)):
            raise HTTPException(409, "a company was already created from this valuation (its report hash may be "
                                     "anchored): start a new valuation or a revaluation instead")

    def docs_of(vid: str, with_text: bool = False) -> list[dict]:
        cols = "id, valuation_id, kind, filename, sha256, parsed, uploaded_by, created_at" + (", text" if with_text
                                                                                               else "")
        rows = ctx.need_db().all(f"SELECT {cols} FROM studio.valuation_documents WHERE valuation_id=%s "
                                 "ORDER BY created_at, id", (vid,))
        return [{**x, "doc_id": x["id"]} for x in rows]

    def audit(sess: Session, action: str, target: str, **detail) -> None:
        ctx.need_db().audit(sess.actor, action, target, role="platform_admin" if sess.is_admin else "user", **detail)

    def rescore(row: dict, sess: Session, *, read_decks: bool = True) -> dict:
        """Deterministic v5 re-score of a stored result; reads any new deck once (1 LLM call per deck)."""
        from ..agents import analysts, deck_reader

        db = ctx.need_db()
        res = dict(row.get("result") or {})
        if not (res.get("svi") or {}).get("analysis"):
            raise HTTPException(409, "this valuation has no v5 evaluation (valued before VALUATION_V5): start a new "
                                     "valuation")
        docs = docs_of(row["id"], with_text=read_decks)
        for d in docs:
            if read_decks and d["kind"] == "deck" and "claims" not in (d.get("parsed") or {}):
                deps = getattr(ctx.runner(), "deps", None)
                if deps is None:
                    continue
                parsed = {**(d.get("parsed") or {}),
                          **deck_reader.read_deck(str(d["id"]), d.get("text") or "", res["profile"], deps,
                                                  res.get("site_url") or row.get("url") or "")}
                db.exec("UPDATE studio.valuation_documents SET parsed=%s WHERE id=%s", (Jsonb(jsonable(parsed)),
                                                                                         d["id"]))
                d["parsed"] = parsed
        prev = (res.get("svi") or {}).get("index")
        sr = row.get("self_reported") or res.get("self_reported") or {}
        new = analysts.rescore_v5({**res, "self_reported": sr}, self_reported=sr, documents=docs)
        from ..tools.consistency import stability

        flag = stability(prev, new["index"], typed_only=not docs)
        if flag is not None:
            new["analysis"]["flags"].append(flag.model_dump())
            new["needs_human_review"] = list(dict.fromkeys([*new["needs_human_review"], f"consistency: {flag.message}"]))
            from ..schemas import SVIResult
            from ..tools.svi import report_hash

            new["report_sha256"] = report_hash(SVIResult.model_validate(new))
        db.merge_result(row["id"], {"svi": new, "self_reported": sr or None})
        audit(sess, "valuation_rescored", row["id"], index=new["index"], previous_index=prev,
              stage=new["analysis"]["stage"]["stage"], documents=len(docs))
        return new

    def view(vid: str) -> dict:
        row = ctx.need_db().get_valuation(vid)
        res = row.get("result") or {}
        return {"id": vid, "status": row["status"], "svi": res.get("svi"),
                "self_reported": row.get("self_reported") or res.get("self_reported") or None,
                "documents": [{k: d[k] for k in ("doc_id", "kind", "filename", "sha256", "created_at")}
                              for d in docs_of(vid)]}

    # -------------------------------------------------------------- public config (wizard + benchmark bars)
    @r.get("/v1/studio/evaluation/config")
    def config():
        return {
            "enabled": stage_tools.v5_enabled(), "stages": list(stage_tools.STAGES),
            "table_version": stage_tools.STAGE_TABLE_VERSION,
            "weights_by_stage": {s: stage_tools.weights(s) for s in stage_tools.STAGES},
            "benchmarks_by_stage": {s: stage_tools.profile_snapshot(s)["bench"] for s in stage_tools.STAGES},
            "lower_is_better": sorted(stage_tools.LOWER_IS_BETTER),
            "level_labels": {str(k): v for k, v in stage_tools.LEVEL_LABELS.items()},
            "level_shrink": {str(k): v for k, v in stage_tools.LEVEL_SHRINK.items()},
            "dimension_labels": dict(stage_tools.DIMENSION_LABELS),
            "fields": [{"key": k, "group": g, "unit": u, "min_stage": ms} for k, (g, u, ms) in FIELD_GROUPS.items()],
            "documents": {"kinds": list(DOC_KINDS), "max_per_valuation": MAX_DOCS, "max_chars": MAX_TEXT_CHARS,
                          "csv_max_rows": csv_metrics.MAX_ROWS, "csv_columns": list(csv_metrics.COLUMNS),
                          "csv_template": "/templates/metrics-monthly.csv"},
            "share_price_by_stage": dict(stage_tools.SHARE_PRICE_AUD),
            "au_round_medians": {s: stage_tools.au_round_medians(s) for s in stage_tools.STAGES},
        }

    @r.post("/v1/studio/evaluation/stage-preview")
    def stage_preview(body: StagePreviewBody, sess: Session = Depends(require_user)):
        need_v5()
        sr = body.metrics.model_dump(exclude_none=True) if body.metrics else {}
        return stage_tools.classify_stage(stage_tools.evidence_from_result({}, sr)).model_dump()

    # -------------------------------------------------------------- typed numbers
    @r.put("/v1/studio/valuations/{vid}/metrics")
    def put_metrics(vid: str, body: MetricsBody, sess: Session = Depends(require_user)):
        need_v5()
        row = owned(vid, sess)
        unlocked(row)
        sr = body.metrics.model_dump(exclude_none=True)
        ctx.need_db().exec("UPDATE studio.valuations SET self_reported=%s, updated_at=now() WHERE id=%s",
                           (Jsonb(sr) if sr else None, vid))
        row["self_reported"] = sr
        rescore(row, sess, read_decks=False)
        return view(vid)

    @r.post("/v1/studio/valuations/{vid}/rescore")
    def post_rescore(vid: str, sess: Session = Depends(require_user)):
        need_v5()
        row = owned(vid, sess)
        unlocked(row)
        rescore(row, sess)
        return view(vid)

    # -------------------------------------------------------------- documents
    @r.post("/v1/studio/valuations/{vid}/documents", status_code=201)
    def add_document(vid: str, body: DocumentBody, sess: Session = Depends(require_user)):
        need_v5()
        row = owned(vid, sess)
        unlocked(row)
        db = ctx.need_db()
        if len(docs_of(vid)) >= MAX_DOCS:
            raise HTTPException(409, f"at most {MAX_DOCS} documents per valuation: delete one first")
        text, parsed = "", {}
        if body.kind == "metrics_csv":
            payload: Any = body.rows if body.rows is not None else (body.text or "")
            if not payload:
                raise HTTPException(422, "send the CSV as text or rows")
            try:
                parsed = csv_metrics.parse(payload)
            except ValueError as e:
                raise HTTPException(422, str(e)) from None
            text = body.text if body.text is not None else (
                body.rows if isinstance(body.rows, str) else "\n".join(",".join(r) for r in body.rows or []))
        else:
            if not (body.text or "").strip():
                raise HTTPException(422, "send the document text (the browser extracts it)")
            text = redact(body.text or "")
            parsed = {"chars": len(text)}
        text = text[:MAX_TEXT_CHARS]
        did = db.one("INSERT INTO studio.valuation_documents (valuation_id, kind, filename, sha256, text, parsed, "
                     "uploaded_by, text_sha256) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                     (vid, body.kind, body.filename, body.sha256.lower(), text, Jsonb(jsonable(parsed)), sess.actor,
                      hashlib.sha256(text.encode()).hexdigest()))["id"]
        audit(sess, "valuation_document_added", vid, doc_id=did, kind=body.kind, sha256=body.sha256.lower())
        return {"doc_id": did, "kind": body.kind, "filename": body.filename, "sha256": body.sha256.lower(),
                "parsed": parsed}

    @r.get("/v1/studio/valuations/{vid}/documents")
    def list_documents(vid: str, sess: Session = Depends(require_user)):
        need_v5()
        owned(vid, sess)
        return [{k: d[k] for k in ("doc_id", "kind", "filename", "sha256", "parsed", "uploaded_by", "created_at")}
                for d in docs_of(vid)]

    @r.delete("/v1/studio/valuations/{vid}/documents/{doc_id}")
    def delete_document(vid: str, doc_id: int, sess: Session = Depends(require_user)):
        need_v5()
        row = owned(vid, sess)
        unlocked(row)
        n = ctx.need_db().exec("DELETE FROM studio.valuation_documents WHERE id=%s AND valuation_id=%s",
                               (doc_id, vid))
        if not n:
            raise HTTPException(404, "unknown document")
        audit(sess, "valuation_document_deleted", vid, doc_id=doc_id)
        return {"deleted": True}

    # -------------------------------------------------------------- admin: mark a metric verified
    @r.post("/v1/studio/valuations/{vid}/metrics/verify")
    def verify_metric(vid: str, body: VerifyBody, sess: Session = Depends(require_admin)):
        need_v5()
        db = ctx.need_db()
        row = db.get_valuation(vid)
        if not row:
            raise HTTPException(404, "unknown valuation")
        unlocked(row)
        res = row.get("result") or {}
        metrics = ((res.get("svi") or {}).get("analysis") or {}).get("metrics") or {}
        if body.metric not in metrics:
            raise HTTPException(422, f"unknown metric {body.metric!r} for this valuation")
        ver = {**(res.get("metric_verifications") or {}),
               body.metric: {"level": body.level, "note": body.note, "by": sess.actor}}
        db.merge_result(vid, {"metric_verifications": ver})
        audit(sess, "valuation_metric_verified", vid, metric=body.metric, level=body.level, note=body.note)
        rescore(db.get_valuation(vid), sess, read_decks=False)
        return view(vid)

    # -------------------------------------------------------------- E5: revaluation suggestion from approved KPIs
    @r.post("/v1/admin/companies/{cid}/revalue-suggestion")
    def revalue_suggestion(cid: int, sess: Session = Depends(require_user)):
        """Deterministic re-score of the company's valuation with approved, published KPI updates (level L3); the
        stage is re-evaluated. Nothing is applied: the admin reviews and then calls /revalue with the value."""
        from ..agents import analysts

        need_v5()
        db = ctx.need_db()
        c = db.one("SELECT * FROM studio.companies WHERE id=%s", (cid,))
        if not c:
            raise HTTPException(404, "unknown company")
        role = authz.check(sess, cid)
        row = db.get_valuation(c["valuation_id"]) if c.get("valuation_id") else None
        if not row or not (row.get("result") or {}).get("profile"):
            raise HTTPException(409, "the company has no stored valuation to re-score")
        kpis = kpi_candidates(db, cid)
        if not kpis:
            raise HTTPException(409, "no published business updates with KPI values yet")
        res = row.get("result") or {}
        prev_stage = (((res.get("svi") or {}).get("analysis") or {}).get("stage") or {}).get("stage") \
            or (res.get("profile") or {}).get("stage")
        sr = row.get("self_reported") or res.get("self_reported") or {}
        try:
            new = analysts.rescore_v5({**res, "self_reported": sr}, self_reported=sr, kpis=kpis, allow_empty_seed=True)
        except Exception as e:
            log.exception("revalue suggestion")
            raise HTTPException(409, f"could not re-score: {e}") from None
        st_new = new["analysis"]["stage"]["stage"]
        note = (f"moved from {prev_stage} to {st_new}: weights and benchmarks changed" if prev_stage and
                prev_stage != st_new else f"same stage ({st_new})")
        prev_val = float(c.get("valuation_aud") or 0)
        out = {"company_id": cid, "ticker": c["ticker"], "suggested_valuation_aud": new["valuation_mid_aud"],
               "suggested_low_aud": new["valuation_low_aud"], "suggested_high_aud": new["valuation_high_aud"],
               "previous_valuation_aud": prev_val, "index": new["index"], "stage": st_new,
               "previous_stage": prev_stage, "stage_changed": bool(prev_stage and prev_stage != st_new), "note": note,
               "kpi_metrics": {k: v[-1].model_dump() for k, v in kpis.items()},
               "confidence": new["analysis"]["confidence"], "requires_admin_approval": True}
        db.exec("INSERT INTO studio.events(company_id,kind,chain,data) VALUES (%s,'revaluation_suggested',NULL,%s)",
                (cid, Jsonb(jsonable({k: out[k] for k in ("suggested_valuation_aud", "previous_valuation_aud",
                                                             "stage", "previous_stage", "note", "index")}
                                     | {"by": sess.actor, "ref": secrets.token_hex(4)}))))
        db.audit(sess.actor, "revaluation_suggested", c["ticker"], role=role, value=out["suggested_valuation_aud"],
                 stage=st_new, previous_stage=prev_stage)
        return out

    return r


def parse_metrics_or_422(raw: dict | None) -> dict | None:
    try:
        return self_reported_v2(raw)
    except ValidationError as e:
        raise HTTPException(422, e.errors()[:5]) from None
