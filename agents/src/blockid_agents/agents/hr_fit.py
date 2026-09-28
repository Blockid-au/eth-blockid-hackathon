"""Fit lenses for HR v3 (docs/PLAN-HR-V3.md §2): business, JD and current role; Claimed vs Verified fit, knockouts,
relevant years, verdict, the Fit × Trust decision, role templates and the JD fairness check. All CODE.

  Claimed fit   the model's requirement matches with CV-only evidence taken at face value
  Verified fit  CV-only evidence counts half (a self-reported component keeps half of its excess over the cap),
                a requirement resting on a contradicted CV claim counts 0
  score         = Verified fit (what the team score uses, owner decision D3)
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

TEMPLATES = Path(__file__).resolve().parent / "data" / "role_templates.json"
VERDICTS = ((75.0, "strong"), (55.0, "conditional"), (35.0, "weak"), (0.0, "not_suitable"))
VERDICT_WORD = {"strong": "Strong fit", "conditional": "Fit with conditions", "weak": "Weak fit",
                "not_suitable": "Not suitable"}
CAP_MUST_MISSING, CAP_MUST_CONTRADICTED = 60.0, 40.0
FIT_OK = 55.0
RECENT_YEARS, OLD_ROLE_WEIGHT = 5, 0.6
LENS_TITLE = {"business": "Fit to the business", "jd": "Fit to the job description",
              "current_role": "Fit to the current role"}

# Requirements that touch a protected attribute (AU: Age / Sex / Racial / Disability Discrimination Acts, Fair Work
# Act s351). Flagged to the requester and left out of scoring. Work rights, licences and language skills are lawful.
PROTECTED = [
    (r"\b(?:young|youthful|digital native|recent graduate|under \d{2}|over \d{2}|aged? (?:\d{2}|between)|"
     r"\d{2}\s*[-–]\s*\d{2} years old|max(?:imum)? age|tuổi|trẻ trung)\b", "age"),
    (r"\b(?:male|female|man|woman|men|women|gentleman|lady|ladies|nam giới|nữ giới|\bnam\b|\bnữ\b)\b", "sex / gender"),
    (r"\b(?:married|single|no children|without children|family status|marital|pregnan\w*|độc thân|có gia đình)\b",
     "family / marital status"),
    (r"\b(?:nationality|nationals? only|citizens? only|born in|ethnic\w*|race|racial|caucasian|asian only|"
     r"native (?:english )?speaker|quốc tịch)\b", "race / nationality / origin"),
    (r"\b(?:religio\w*|christian|muslim|buddhist|catholic|tôn giáo)\b", "religion"),
    (r"\b(?:able-bodied|no disabilit\w*|physically fit|healthy|good health|sức khỏe tốt)\b", "disability / health"),
    (r"\b(?:attractive|good[- ]looking|pretty|handsome|height|weight|ngoại hình)\b", "appearance"),
    (r"\b(?:political|union member\w*|đảng viên)\b", "political opinion / union"),
]
_PROT = [(re.compile(p, re.I), why) for p, why in PROTECTED]


def protected_reason(text: str) -> str | None:
    t = text or ""
    if re.search(r"work rights|visa|licen[cs]e|clearance", t, re.I) and not re.search(r"only|born", t, re.I):
        return None
    return next((why for rx, why in _PROT if rx.search(t)), None)


def split_protected(reqs: list[str]) -> tuple[list[str], list[dict]]:
    keep, flagged = [], []
    for r in reqs or []:
        why = protected_reason(r)
        if why:
            flagged.append({"text": r, "reason": f"May be discriminatory ({why}) under Australian law — left out of "
                                                 "scoring"})
        else:
            keep.append(r)
    return keep, flagged


# ------------------------------------------------------------------ templates
@lru_cache(maxsize=1)
def _templates() -> list[dict]:
    try:
        return json.loads(TEMPLATES.read_text())["roles"]
    except (OSError, ValueError, KeyError):
        return []


def stage_band(stage: str | None) -> str:
    s = (stage or "").lower().replace("_", "-").replace(" ", "-")
    if s in ("series-a", "a") or "series-a" in s:
        return "scale"
    if s in ("growth", "series-b", "series-c", "listed", "profitable-sme") or re.search(r"series-[b-z]|ipo", s):
        return "growth"
    return "early" if s in ("idea", "pre-seed", "seed", "angel") else "scale" if not s else "early"


def role_template(role: str, stage: str | None) -> dict | None:
    """The first template whose pattern matches the stated role (CEO before engineer)."""
    if not (role or "").strip():
        return None
    band = stage_band(stage)
    for t in _templates():
        if re.search(t["match"], role, re.I):
            return {"key": t["key"], "label": t["label"], "stage_band": band, "competencies": list(t[band])}
    return None


# ------------------------------------------------------------------ JD parser (one cached model call, studio/hr.py)
class JDParse(BaseModel):
    title: str = Field(default="", max_length=200)
    seniority: Literal["", "entry", "mid", "senior", "lead", "executive"] = ""
    min_years: int | None = Field(default=None, ge=0, le=40)
    domain: str = Field(default="", max_length=200)
    must: list[str] = Field(default=[], description="must-have requirements, short, <= 12")
    nice: list[str] = Field(default=[], description="nice-to-have requirements, <= 8")
    knockouts: list[str] = Field(default=[], description="hard criteria: licence, degree, clearance, work rights")
    skills: list[str] = Field(default=[], description="<= 16 skills named in the JD")


SYSTEM_JD = """You read ONE job description and return its structure. Rules:
- title as written; seniority entry / mid / senior / lead / executive from scope; min_years only when the JD states
  a number of years; domain = the industry or field in a few words.
- must: the key requirements (<= 12, each a short phrase); nice: nice-to-haves (<= 8); knockouts: hard criteria
  only (a licence, a degree, a security clearance, work rights) — they also appear in must.
- skills: up to 16 tools / skills named in the JD.
- Copy requirements faithfully even if they mention age, gender, nationality, family, religion, health or looks —
  the platform flags those; do not invent any. Write in the JD's language."""


def clean_jd(j: JDParse) -> dict:
    def short(xs, n):
        return [" ".join(x.split())[:300] for x in xs if x and x.strip()][:n]

    must, f1 = split_protected(short(j.must, 12))
    nice, f2 = split_protected(short(j.nice, 8))
    ko, f3 = split_protected(short(j.knockouts, 6))
    seen: set[str] = set()
    flagged = [f for f in [*f1, *f2, *f3] if not (f["text"] in seen or seen.add(f["text"]))]
    return {"title": j.title.strip()[:200], "seniority": j.seniority, "min_years": j.min_years,
            "domain": j.domain.strip()[:200], "must": must, "nice": nice, "knockouts": ko,
            "skills": short(j.skills, 16), "flagged": flagged}


# ------------------------------------------------------------------ model suggestions for v3 fit
class RoleRelevance(BaseModel):
    role: int = Field(ge=1, le=40, description="number of the role in the CV TIMELINE list")
    relevance: Literal["high", "medium", "low"] = "low"
    reason: str = Field(default="", max_length=200)


class AltRole(BaseModel):
    role: str = Field(max_length=120)
    score: float = Field(ge=0, le=100)
    reason: str = Field(default="", max_length=300)


# ------------------------------------------------------------------ computation
def _matches(req: str, items: list[str]) -> bool:
    from .people import fold

    a = fold(req)
    return any(fold(x) and (fold(x) in a or a in fold(x)) for x in items)


def relevant_experience(roles: list[dict], rel: list[RoleRelevance], min_years: int | None) -> dict | None:
    """Months of high-relevance roles + half of medium ones, older than 5 years x 0.6 (code; roles from the CV)."""
    if not roles or not rel:
        return None
    now = datetime.now(UTC).year
    out, months = [], 0.0
    for r in rel:
        if not 1 <= r.role <= len(roles):
            continue
        ro = roles[r.role - 1]
        m = float(ro.get("months") or 0)
        end = (ro.get("end") or "").strip().lower()
        y = re.search(r"(?:19|20)\d\d", end)
        ey = now if end in ("", "present", "current", "now", "nay", "hiện tại") else int(y.group(0)) if y else 0
        w = {"high": 1.0, "medium": 0.5, "low": 0.0}[r.relevance] * (
            1.0 if ey >= now - RECENT_YEARS else OLD_ROLE_WEIGHT)
        months += m * w
        out.append({"org": ro.get("org") or "", "title": ro.get("title") or "", "relevance": r.relevance,
                    "reason": r.reason[:200], "months": int(m)})
    if not out:
        return None
    return {"years": round(months / 12, 1), "min_years": min_years, "roles": out[:12]}


def lens_fit(base: dict, lens: str, *, claims: dict[str, dict], req_claims: dict[str, list[str]],
             knockouts: list[str] | None = None, relevant: dict | None = None, template: dict | None = None,
             alt: AltRole | None = None, title: str = "") -> dict:
    """v1 fit dict (people.fit_score) -> v3 lens fit. `claims`: ledger claims by id; `req_claims`: requirement text ->
    claim ids the model cited for it."""
    from .people import CAP_WITHOUT_EVIDENCE, FIT_WEIGHTS, REQ_VALUE

    ko = knockouts or []
    reqs = []
    for r in base.get("requirements") or []:
        cids = [c for c in req_claims.get(r["requirement"], []) if c in claims]
        st = {claims[c]["status"] for c in cids}
        if r["fact_ids"]:
            ev = "verified"
        elif cids and st <= {"contradicted"}:
            ev = "contradicted"
        elif cids or r.get("self_reported"):
            ev = "cv_only"
        else:
            ev = "none"
        reqs.append({**r, "evidence": ev, "claim_ids": cids,
                     "knockout": bool(ko and _matches(r["requirement"], ko)), "must_have": r["must_have"] or bool(
                         ko and _matches(r["requirement"], ko))})

    def req_value(r: dict, verified: bool) -> float:
        v = REQ_VALUE.get(r["status"], 0.0)
        if not verified:
            return v
        return v if r["evidence"] == "verified" else v * 0.5 if r["evidence"] == "cv_only" else 0.0

    must = [r for r in reqs if r["must_have"]] or reqs

    def gaps(verified: bool) -> float:
        return round(100 * sum(req_value(r, verified) for r in must) / len(must), 1) if must else CAP_WITHOUT_EVIDENCE

    def comp_score(c: dict, verified: bool) -> float:
        s = float(c["score"])
        if verified and c.get("self_reported") and not c.get("fact_ids") and s > CAP_WITHOUT_EVIDENCE:
            return CAP_WITHOUT_EVIDENCE + 0.5 * (s - CAP_WITHOUT_EVIDENCE)
        return s

    comps = base.get("components") or {}
    tot = sum(FIT_WEIGHTS.values())

    def total(verified: bool) -> float:
        return round(sum(FIT_WEIGHTS[k] * (gaps(verified) if k == "gaps" else comp_score(comps[k], verified))
                         for k in FIT_WEIGHTS if k in comps) / tot, 1)

    claimed, verified = total(False), total(True)
    missing_must = [r["requirement"] for r in must if r["must_have"] and r["status"] == "missing"]
    contra_must = [r["requirement"] for r in must if r["must_have"] and r["evidence"] == "contradicted"]
    short = relevant and relevant.get("min_years") and relevant["years"] < 0.7 * relevant["min_years"]
    kos = [*missing_must, *contra_must] + ([f"At least {relevant['min_years']} years of relevant experience "
                                             f"(about {relevant['years']:g} found)"] if short else [])
    cap = CAP_MUST_CONTRADICTED if contra_must else CAP_MUST_MISSING if kos else None
    if cap is not None:
        verified = min(verified, cap)
    if missing_must or short:  # the claimed fit takes the CV at face value: only real gaps cap it
        claimed = min(claimed, CAP_MUST_MISSING)
    verdict = next(v for lo, v in VERDICTS if verified >= lo)
    if kos and verdict == "strong":
        verdict = "conditional"
    alt_role = None
    if alt is not None and alt.score >= 70 and alt.score >= verified + 10:
        alt_role = {"role": alt.role[:120], "score": round(alt.score, 1), "reason": alt.reason[:300],
                    "model_suggested": True}
    comps_out = dict(comps)
    if "gaps" in comps_out:
        comps_out["gaps"] = {**comps_out["gaps"], "score": gaps(True), "suggested": gaps(False)}
    return {**base, "lens": lens, "title": title or LENS_TITLE[lens], "score": verified, "claimed_score": claimed,
            "verified_score": verified, "verdict": verdict, "verdict_label": VERDICT_WORD[verdict],
            "components": comps_out, "requirements": reqs, "knockouts": kos[:8], "cap": cap,
            "relevant": relevant, "template": ({k: template[k] for k in ("key", "label", "stage_band")}
                                               if template else None), "alt_role": alt_role,
            "matched": [r["requirement"] for r in reqs if r["status"] in ("matched", "partial")],
            "missing": [r["requirement"] for r in reqs if r["status"] == "missing"]}


def decision(fits: dict[str, dict], trust: dict | None, ledger: dict | None,
             verifiability: float | None) -> dict | None:
    """Fit × Trust quadrant with up to 3 reasons and 3 things to verify (code)."""
    lens = next((k for k in ("jd", "business", "current_role") if fits.get(k)), None)
    if lens is None:
        return None
    f = fits[lens]
    if trust:
        band = trust["band"]
    elif verifiability is not None:
        band = "high" if verifiability >= 70 else "medium" if verifiability >= 45 else "low"
    else:
        band = "medium"
    fit_ok, trust_ok = f["verified_score"] >= FIT_OK, band != "low"
    gap = f["claimed_score"] - f["verified_score"]
    if fit_ok and trust_ok:
        q = "proceed"
    elif fit_ok or (f["claimed_score"] >= FIT_OK and gap >= 10):
        q = "verify_first"
    elif trust_ok:
        q = "other_role"
    else:
        q = "stop"
    reasons = [f"{f['verdict_label']} — {f['title'].lower()}: verified {f['verified_score']:.0f}"
               + (f", {gap:.0f} more if the CV is taken at face value" if gap >= 5 else "")]
    if trust:
        reasons.append(f"CV trust {trust['band']}: {trust['summary']}")
    good = [r["requirement"] for r in f["requirements"] if r["must_have"] and r["status"] == "matched"
            and r["evidence"] == "verified"]
    if f["knockouts"]:
        reasons.append("Missing or in conflict: " + "; ".join(f["knockouts"][:2]))
    elif good:
        reasons.append("Verified key strengths: " + "; ".join(good[:2]))
    cr = fits.get("current_role")
    if cr and lens != "current_role":
        reasons.append(f"Current role ({(cr.get('template') or {}).get('label') or 'stated role'}): "
                       f"{cr['verdict_label'].lower()} {cr['verified_score']:.0f}")
    verify = []
    for c in (ledger or {}).get("claims") or []:
        if c["status"] == "contradicted":
            verify.append(f"Conflict on '{c['text']}' — ask for proof")
    for r in f["requirements"]:
        if r["must_have"] and r["evidence"] in ("cv_only", "none") and r["status"] in ("matched", "partial"):
            verify.append(f"'{r['requirement']}' rests on the CV only — check references or proof")
    for c in (ledger or {}).get("claims") or []:
        if c["status"] == "not_found" and c["importance"] >= 2:
            verify.append(f"No public trace of '{c['text']}' — confirm with a reference")
    return {"quadrant": q, "fit_lens": lens, "fit_score": f["verified_score"], "claimed_score": f["claimed_score"],
            "trust_band": band, "reasons": reasons[:3], "verify": list(dict.fromkeys(verify))[:3]}
