"""Valuation v5 — management projections upload (docs/PLAN-VALUATION-V5.md §6). Shapes: docs/VALUATION-V5-API.md §2.

Every endpoint answers 404 while VALUATION_V5=0.

  GET    /v1/studio/projection-template?format=xlsx|csv&lang=en|vi    signed in: the template file
  POST   /v1/studio/valuations/{vid}/projections                       owner / platform admin; body is ONE of
             multipart/form-data with a `file` field (.xlsx / .csv)
             raw bytes with Content-Type text/csv or the xlsx type, filename in ?filename=
             application/json ProjectionInput (the in-page grid)
         -> 201 ProjectionView (status draft) — parsed with tools/projections.py (no LLM, no formulas evaluated)
  GET    /v1/studio/valuations/{vid}/projections                       owner / admin: {latest, history, label}
  POST   /v1/studio/valuations/{vid}/projections/{pid}/confirm {attest: true}
         owner / admin: attestation "These are our management's projections, prepared with reasonable care. I
         understand BlockID does not verify them." -> confirmed (the previous one superseded), the valuation is
         re-valued deterministically (studio/finalise.rerun); approved + moved > 5 % -> back to waiting_approval.
         Refused once a company exists for the valuation (its report hash may be anchored on chain).
  DELETE /v1/studio/valuations/{vid}/projections/{pid}                 owner / admin, drafts only
  GET    /v1/studio/valuations/{vid}/projections/{pid}/export.csv      owner / admin (formula-injection escaped)

Limits: 512 KB per file, 10 uploads per valuation per day. The original file is kept (bytea) with its SHA-256 for
audit; the parsed rows are copied into the method inputs so the report hash commits to them.
Audit: projection_uploaded, projection_confirmed, projection_deleted.
"""
from __future__ import annotations

import hashlib
import json
import logging
from email.parser import BytesParser
from email.policy import default as email_default

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, ValidationError

from ..schemas import ProjectionInput
from ..tools import projections as pj
from ..tools.market_data import snapshot
from ..tools.valuation_params import MARKET_DATASET, PROJECTION_LABEL, params, v5_enabled
from .auth import COOKIE, Session
from .db import jsonable
from .finalise import company_exists, rerun, triangulation

log = logging.getLogger(__name__)

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ATTESTATION = ("These are our management's projections, prepared with reasonable care. I understand BlockID does not "
               "verify them.")
MULTIPART_OVERHEAD = 16 * 1024
COLS = ("id, valuation_id, status, filename, content_type, size_bytes, sha256, parsed, checks, template_version, "
        "uploaded_by, attested_by, attested_at, created_at")


class ConfirmBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attest: bool = False


def projection_view(row: dict, *, parsed: bool = True) -> dict:
    checks = row.get("checks") or []
    errors = sum(1 for c in checks if c.get("severity") == "error")
    out = {k: row.get(k) for k in ("id", "valuation_id", "status", "filename", "content_type", "size_bytes",
                                   "sha256", "template_version", "uploaded_by", "attested_by", "attested_at",
                                   "created_at")}
    out.update(checks=checks, errors=errors, warnings=sum(1 for c in checks if c.get("severity") == "warning"),
               can_confirm=errors == 0 and row.get("status") == "draft" and bool((row.get("parsed") or {}).get("years")),
               label=PROJECTION_LABEL, attestation=ATTESTATION)
    if parsed:
        out["parsed"] = row.get("parsed") or {}
    return jsonable(out)


def validation_context(row: dict) -> tuple[str, dict, float | None]:
    """(valuation class, industry row, revenue on the valuation) for the projection checks."""
    from ..tools import stage as stage_tools

    snap = snapshot(MARKET_DATASET)
    tri = triangulation(row)
    res = row.get("result") or {}
    prof = res.get("profile") or {}
    cls = tri.get("valuation_class") if tri.get("version") == "v5" else None
    if not cls:
        dec = stage_tools.classify_stage(stage_tools.evidence_from_result(res, row.get("self_reported") or {}))
        cls = stage_tools.to_valuation_class(dec.stage)
    ind = ((tri.get("stage") or {}).get("industry") or ((res.get("valuation_inputs") or {}).get("industry"))
           or snap.industry_for_text(f"{prof.get('sector', '')} {prof.get('description', '')}"))
    rev = float(((prof.get("metrics") or {}).get("revenue_ttm_aud")) or 0) or None
    return cls, snap.industry(ind), rev


def _multipart_file(body: bytes, content_type: str) -> tuple[bytes, str, str]:
    msg = BytesParser(policy=email_default).parsebytes(
        b"MIME-Version: 1.0\r\nContent-Type: " + content_type.encode("latin-1", "replace") + b"\r\n\r\n" + body)
    if not msg.is_multipart():
        raise HTTPException(422, "multipart body without parts")
    for part in msg.iter_parts():
        if part.get_param("name", header="content-disposition") == "file":
            data = part.get_payload(decode=True) or b""
            return data, part.get_filename() or "", part.get_content_type()
    raise HTTPException(422, "send the spreadsheet in a form field named 'file'")


def build_projections_router(ctx) -> APIRouter:
    r = APIRouter()

    def session(request: Request) -> Session | None:
        sid = request.cookies.get(COOKIE)
        return ctx.sessions.get(sid) if sid else None

    def require_user(sess: Session | None = Depends(session)) -> Session:
        if sess is None:
            raise HTTPException(401, "sign in required")
        return sess

    def need_v5() -> None:
        if not v5_enabled():
            raise HTTPException(404, "valuation v5 is not enabled")

    def load(vid: str, sess: Session) -> dict:
        need_v5()
        row = ctx.need_db().get_valuation(vid)
        if not row:
            raise HTTPException(404, "unknown valuation")
        if not (sess.is_admin and not sess.must_change) and \
                (row.get("requested_by") or "").lower() != sess.actor.lower():
            raise HTTPException(403, "not your valuation")
        return row

    def load_projection(vid: str, pid: int) -> dict:
        p = ctx.need_db().one(f"SELECT {COLS} FROM studio.valuation_projections WHERE id=%s AND valuation_id=%s",
                              (pid, vid))
        if not p:
            raise HTTPException(404, "unknown projection")
        return p

    @r.get("/v1/studio/projection-template")
    def template(format: str = Query(default="xlsx", pattern="^(xlsx|csv)$"),
                 lang: str = Query(default="en", pattern="^(en|vi)$"), sess: Session = Depends(require_user)):
        need_v5()
        if format == "xlsx":
            data, mt = pj.template_xlsx(lang), XLSX_TYPE
        else:
            data, mt = pj.template_csv(lang), "text/csv; charset=utf-8"
        name = f"blockid-projections-v{pj.TEMPLATE_VERSION}{'-vi' if lang == 'vi' else ''}.{format}"
        return Response(data, media_type=mt, headers={"Content-Disposition": f'attachment; filename="{name}"',
                                                      "X-Content-Type-Options": "nosniff"})

    @r.post("/v1/studio/valuations/{vid}/projections", status_code=201)
    async def upload(vid: str, request: Request, filename: str = Query(default="", max_length=200),
                     sess: Session = Depends(require_user)):
        db = ctx.need_db()
        row = load(vid, sess)
        p = params()
        lim = int(p["projection"]["max_bytes"])
        if row["status"] not in ("waiting_approval", "approved"):
            raise HTTPException(409, f"the valuation is {row['status']}: add projections once it is ready for review")
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > lim + MULTIPART_OVERHEAD:
            raise HTTPException(413, f"the file is larger than {lim // 1024} KB")
        body = b""
        async for chunk in request.stream():
            body += chunk
            if len(body) > lim + MULTIPART_OVERHEAD:
                raise HTTPException(413, f"the file is larger than {lim // 1024} KB")
        n = db.one("SELECT count(*) AS n FROM studio.valuation_projections WHERE valuation_id=%s AND "
                   "created_at > now() - interval '1 day'", (vid,))["n"]
        if n >= p["projection"]["uploads_per_day"]:
            raise HTTPException(429, "limit of 10 uploads per valuation per day reached; try again tomorrow")
        ct = (request.headers.get("content-type") or "").lower()
        checks: list = []
        inp = None
        kind = "json"
        if ct.startswith("application/json"):
            try:
                inp = ProjectionInput.model_validate(json.loads(body or b"{}"))
            except (ValueError, ValidationError) as e:
                msg = "; ".join(f"{'.'.join(str(x) for x in er.get('loc', ()))}: {er.get('msg')}"
                                for er in (e.errors()[:5] if isinstance(e, ValidationError) else [])) or "invalid JSON"
                raise HTTPException(422, msg[:500]) from None
            data, fname, ctype = json.dumps(inp.model_dump(), sort_keys=True).encode(), "grid.json", "application/json"
        else:
            if ct.startswith("multipart/form-data"):
                data, fname, ctype = _multipart_file(body, request.headers.get("content-type") or "")
            else:
                data, fname, ctype = body, filename, ct.split(";")[0]
            try:
                inp, errs, kind = pj.parse_upload(data, fname, p)
            except pj.ProjectionError as e:
                code = 413 if "larger than" in str(e) else 415 if ("only .xlsx" in str(e) or "macro" in str(e)
                                                                   or "old Excel" in str(e)) else 422
                db.audit(sess.actor, "projection_rejected", vid, reason=str(e)[:300], filename=pj.clean_text(fname, 120))
                raise HTTPException(code, str(e)) from None
            checks = [c.model_dump() for c in errs]
        parsed: dict = {}
        if inp is not None:
            cls, irow, rev = validation_context(row)
            vchecks, used = pj.validate(inp, cls=cls, industry_row=irow, revenue_ref_aud=rev, p=p)
            checks += [c.model_dump() for c in vchecks]
            parsed = pj.parsed_record(inp, used)
        sha = hashlib.sha256(data).hexdigest()
        new = db.one(f"INSERT INTO studio.valuation_projections (valuation_id, status, filename, content_type, "
                     f"size_bytes, sha256, file, parsed, checks, template_version, uploaded_by) VALUES "
                     f"(%s,'draft',%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING {COLS}",
                     (vid, pj.clean_text(fname, 200) or None, pj.clean_text(ctype, 100) or None, len(data), sha, data,
                      Jsonb(jsonable(parsed)), Jsonb(jsonable(checks)), pj.TEMPLATE_VERSION, sess.actor))
        db.audit(sess.actor, "projection_uploaded", vid, projection_id=new["id"], sha256=sha, kind=kind,
                 errors=sum(1 for c in checks if c["severity"] == "error"),
                 warnings=sum(1 for c in checks if c["severity"] == "warning"))
        return projection_view(new)

    @r.get("/v1/studio/valuations/{vid}/projections")
    def list_projections(vid: str, sess: Session = Depends(require_user)):
        load(vid, sess)
        rows = ctx.need_db().all(f"SELECT {COLS} FROM studio.valuation_projections WHERE valuation_id=%s "
                                 "ORDER BY id DESC LIMIT 50", (vid,))
        return {"latest": projection_view(rows[0]) if rows else None,
                "history": [projection_view(x, parsed=False) for x in rows], "label": PROJECTION_LABEL,
                "attestation": ATTESTATION}

    @r.post("/v1/studio/valuations/{vid}/projections/{pid}/confirm")
    def confirm(vid: str, pid: int, body: ConfirmBody, sess: Session = Depends(require_user)):
        db = ctx.need_db()
        row = load(vid, sess)
        pr = load_projection(vid, pid)
        if body.attest is not True:
            raise HTTPException(422, "tick the attestation: " + ATTESTATION)
        if pr["status"] != "draft":
            raise HTTPException(409, f"this projection is {pr['status']}")
        if any(c.get("severity") == "error" for c in pr.get("checks") or []) or not (pr.get("parsed") or {}).get("years"):
            raise HTTPException(409, "fix the errors in the file and upload it again")
        if row["status"] not in ("waiting_approval", "approved"):
            raise HTTPException(409, f"the valuation is {row['status']}")
        if company_exists(db, vid):
            raise HTTPException(409, "a company was already created from this valuation (its report hash may be "
                                     "anchored); projections can be added at the next revaluation")
        with db.tx() as c:
            c.execute("UPDATE studio.valuation_projections SET status='superseded' WHERE valuation_id=%s AND "
                      "status='confirmed'", (vid,))
            got = c.execute("UPDATE studio.valuation_projections SET status='confirmed', attested_by=%s, "
                            "attested_at=now() WHERE id=%s AND status='draft' RETURNING attested_at",
                            (sess.actor, pid)).fetchone()
            if not got:
                raise HTTPException(409, "the projection changed meanwhile; reload")
        vi = dict((row.get("result") or {}).get("valuation_inputs") or {})
        vi["projection"] = {"id": pid, "parsed": pr["parsed"], "checks": pr["checks"], "sha256": pr["sha256"],
                            "attested_by": sess.actor, "attested_at": got["attested_at"].isoformat()}
        out = rerun(db, row, jsonable(vi), actor=sess.actor, reason="projection confirmed",
                    audit_action="projection_confirmed", projection_id=pid, sha256=pr["sha256"])
        moved = out["moved"]
        back = False
        status = out["row"]["status"]
        if status == "approved" and abs(moved) > params()["rerun_move_to_review"]:
            db.set_valuation_status(vid, "waiting_approval")
            db.audit(sess.actor, "valuation_back_to_review", vid, reason=f"projection moved the value {moved:+.1%}")
            back, status = True, "waiting_approval"
        return jsonable({"projection": projection_view(load_projection(vid, pid)), "valuation_status": status,
                         "value_before_aud": out["before"], "value_after_aud": out["after"],
                         "moved_pct": round(moved * 100, 2), "back_to_review": back})

    @r.delete("/v1/studio/valuations/{vid}/projections/{pid}")
    def delete(vid: str, pid: int, sess: Session = Depends(require_user)):
        db = ctx.need_db()
        load(vid, sess)
        if not db.one("DELETE FROM studio.valuation_projections WHERE id=%s AND valuation_id=%s AND status='draft' "
                      "RETURNING id", (pid, vid)):
            raise HTTPException(409, "only a draft projection can be deleted")
        db.audit(sess.actor, "projection_deleted", vid, projection_id=pid)
        return {"ok": True}

    @r.get("/v1/studio/valuations/{vid}/projections/{pid}/export.csv")
    def export(vid: str, pid: int, sess: Session = Depends(require_user)):
        load(vid, sess)
        pr = load_projection(vid, pid)
        return Response(pj.export_csv(pr.get("parsed") or {}), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="projections-{pid}.csv"',
                                 "X-Content-Type-Options": "nosniff"})

    return r
