"""Founding-team and person review API (hr.blockid.au) — docs/PLAN-HR.md, Phase H1; live progress, people
suggestions and the valuation link: docs/PLAN-HR-V2.md §1 and §3.

Two kinds of report share one table and one report shape:
  * team report  (mode "team")   — the founding team of a business: every person + team-level scoring.
  * person report (mode "person") — one person against a target: a BlockID business ("founder–business fit") or a
    role / job description ("role fit").
Every person gets a CV-style profile (each item cited or labelled self-reported), the quality score (plan rubric) and,
when there is a target, a fit score. The People Analyst agent (agents/people.py) does the research; CODE computes
every score from LLM-suggested, cited sub-scores.

All routes use the studio cookie session (`bid_session`). JSON bodies; ISO-8601 timestamps. Errors are
`{"detail": "..."}` (400/422 bad input, 401 not signed in, 403 not allowed, 404 unknown id, 409 wrong state,
429 daily limit).

Limitations (docs/PLAN-AI-GATEWAY.md §2)
  * Failed runs: users see a short code + one plain English sentence, never an exception. `error_code` is one of
      sources_unreachable  websites / search services could not be reached and nothing else was readable
      models_busy          every AI model was busy, rate-limited, over quota or answered invalid output
      no_public_info       searches ran but found nothing, no link was readable, nobody has a bio / CV / headline
      timeout              a call or the run took too long
      stalled              no heartbeat twice (watchdog re-queued once, then failed it)
      no_people            the report has nobody to analyse
      internal             anything else
    `error` = the sentence for that code (hr_store.ERROR_TEXT; same field the UIs already show), `error_detail` =
    the internal exception text — ONLY in ReportOut for platform admins, and in the audit log ("hr_run_failed").
    Rows written before codes existed are classified from their stored text on read.
  * People suggestions: when the name + role parser finds nobody, ONE budgeted model call (gateway profile
    `extract_json`) reads the team / about text already stored or fetched — no new search or fetch. Budget:
    SUGGEST_MODEL_PER_USER_HOUR per wallet and SUGGEST_MODEL_PER_DAY in total (per API process). Names not literally
    on the cited page are dropped; results carry "note": "suggested from <host/path>" and source "model".
  * ETA: percentile model (hr_store.step_stats): `eta_s` = remaining planned steps x p50 of each step kind over
    its last 30 samples, `eta_range_s` = [p25-based, p75-based]; planned steps scale with the number of people
    (the team step is timed per person). Defaults per step kind (DEFAULT_STEP_S, range 0.6x..1.8x) until a kind has
    3 samples.
  * Stalled detection: one step longer than STEP_MAX_S (180 s) stops the heartbeat, so a hung call shows as
    "stalled" after at most ~4.5 min; the gateway's per-call deadlines normally end it well before.

PersonIn (create / replace people / valuation start / person report):
    {
      "full_name": "Jane Doe",                       # required, 1..120 chars
      "role": "CEO",                                 # free text <= 80 (CEO, CTO, Head of Sales, ...); "" allowed
      "kind": "founder",                             # founder | cofounder | executive | employee | advisor
      "headline": "Fintech operator, ex-Afterpay",   # optional <= 200
      "full_time": true,                             # optional (null = unknown)
      "start_year": 2021,                            # optional, 1950..current year
      "equity_pct": 40.0,                            # optional, 0..100
      "urls": ["https://linkedin.com/in/jane", ...], # optional, <= 6 public http(s) URLs (LinkedIn is not fetched)
      "bio": "Ex-Atlassian PM ...",                  # optional <= 1500, shown as self-reported
      "cv": "pasted CV text ..."                     # optional <= 40000, self-reported (emails/phones redacted)
    }

Target (person reports; team reports use their business automatically):
    {"type": "business", "valuation_id": str?, "ticker": str?, "website": str?}   # one of the three
    {"type": "role", "company": str, "title": str, "description": str (<= 5000), "requirements": [str] (<= 30),
     "min_years": int?, "seniority": "entry|mid|senior|lead|executive"?, "knockouts": [str] (<= 6)}
    Requirements / knockouts that touch a protected attribute are moved to "flagged": [{"text", "reason"}] on the
    stored target and never scored (hr_fit.split_protected).

Endpoints
---------
POST   /v1/hr/teams
       {"name": str, "website": str|null, "valuation_id": str|null, "people": [PersonIn, 1..20], "consent": true,
        "run": false}                             # consent MUST be true; run=true also queues it (counts as a run)
       -> 200 ReportOut (status "draft", or "queued" when run=true)
POST   /v1/hr/people-reports
       {"person": PersonIn, "target": Target|null, "consent": true, "run": true}
       -> 200 ReportOut (mode "person"; queued unless run=false)
PUT    /v1/hr/teams/{id}/people        {"people": [PersonIn, 1..20]}  -> ReportOut (replaces all; resets to draft)
PUT    /v1/hr/teams/{id}/target        {"target": Target|null}         -> ReportOut (person reports; resets to draft)
POST   /v1/hr/jd/parse                 {"text": JD (40..12000)} -> {"title", "seniority", "min_years", "domain",
                                        "must": [str], "nice": [str], "knockouts": [str], "skills": [str],
                                        "flagged": [{"text", "reason"}]}   # one cached model call; 429 over
                                        JD_PARSE_PER_USER_HOUR, 503 when no model is available
POST   /v1/hr/teams/{id}/run           -> ReportOut (status "queued"); 429 over HR_RUNS_PER_DAY per wallet
GET    /v1/hr/teams/{id}[?share=<token>]              -> ReportOut   (works for both modes)
GET    /v1/hr/people-reports/{id}[?share=<token>]     -> ReportOut   (alias)
GET    /v1/hr/teams?mine=1                            -> {"teams": [ListItem]}  (admins: mine=0 lists every report)
GET    /v1/hr/teams/{id}/summary[?share=<token>]      -> Summary (public-safe: no personal facts)
POST   /v1/hr/teams/{id}/share                        -> {"share_token": str}  (requester/admin; rotates)
DELETE /v1/hr/teams/{id}/share                        -> {"ok": true}          (revokes the link)
DELETE /v1/hr/people/{pid}                            -> {"ok": true, "team_id": str}  (requester/admin; removal)
DELETE /v1/hr/teams/{id}                              -> {"ok": true}  (requester/admin; deletes report + evidence)
GET    /v1/hr/suggest-people?valuation_id=<id>  |  ?website=<url>
       -> {"website": str|null, "source": "site_intake|fetched|model|none",
           "people": [{"full_name", "role", "kind": "founder|cofounder|executive|employee|advisor",
                       "source_url": str|null,
                       "note"?: "suggested from agritrace.example/about"}]}   # note: model-suggested only
                                                  # <= 12, for the "Assess the founders" flow
       Signed in. valuation_id (readable by you): the founders the valuation's site intake found plus names + roles
       on the team / about / leadership pages it already read (evidence store) — no web search. Nothing found there,
       or only a website: at most ONE SSRF-safe fetch of <site>/team (source "fetched"). Still nobody: one budgeted
       model call over that stored / fetched text (source "model", see Limitations). 403/404 as for valuations.
POST   /v1/hr/teams/{id}/apply-to-valuation           -> {"applied": bool, "reason": str|null, "svi": {...}|null}
       (requester/admin; re-scores the linked valuation from the done team report — also automatic on completion)
Valuation start: POST /v1/studio/valuations also accepts
       {"url": ..., "metrics": ..., "team": {"people": [PersonIn, 1..20], "consent": true}}
       -> {"id": <valuation id>, "team_id": str}; the team runs after the valuation's research and its score becomes
       founder_quality (basis "team_report"). GET /v1/studio/valuations/{id} then has
       "team": (Summary + {"applied": bool, "reason": str|null, "applied_at": str|null}) | null — LIVE: read from the latest team report
       linked to the valuation on every GET, so it carries "progress" {phase, pct, eta_s, updated_at} while queued /
       running, the person ids + hr links and each founder's fit to THIS business (Summary below). The report's name
       starts as the site's host and becomes the company name found by the valuation when the team runs.

Readers of a report: the requester, platform admins, active company admins of the linked company, any signed-in
viewer for demo reports (requested by DEMO_WALLET), anyone with ?share=<token> (no sign-in). The Summary is also
readable by anyone who can read the linked valuation. Edit/run/delete: requester or platform admin.

ReportOut
    {
      "id": "t_ab12cd34ef56", "mode": "team|person", "name": str, "website": str|null,
      "valuation_id": str|null, "company_id": int|null, "target": TargetView|null,
      "status": "draft|queued|running|done|failed", "error": str|null,   # plain sentence (see Limitations)
      "error_code": "sources_unreachable|models_busy|no_public_info|timeout|stalled|no_people|internal"|null,
      "error_detail"?: str|null,                  # platform admins only: the internal exception text
      "consent": bool, "consented_at": str|null, "is_demo": bool, "mine": bool, "can_edit": bool,
      "share_token": str|null,                    # requester/admin only
      "report_url": "https://hr.blockid.au/r/<id>",
      "created_at": str, "updated_at": str,
      "steps": [{"at": str, "step": "queued|fetch|search|extract|team|score|done|failed", "person": str|null,
                 "msg": str}],
      "people": [{"id": int, "full_name", "role", "kind", "headline", "full_time", "start_year", "equity_pct",
                  "urls": [str], "bio": str|null, "has_cv": bool, "position": int}],
      "result": Report|null,                      # when status == "done"
      "progress": Progress|null                   # null for drafts
    }
Progress (live; docs/PLAN-HR-V2.md §1 — FIXED contract, the hr and eth UIs build on it)
    {
      "phase": "queued|reading|searching|extracting|scoring|done|failed|stalled",
      "pct": 0..100,                              # monotonic within a run (also across a watchdog restart)
      "eta_s": int|null,                          # remaining planned steps x p50 step time (see Limitations)
      "eta_range_s": [lo, hi]|null,               # p25 / p75 based range, seconds (additive; [0, 0] when done)
      "started_at": str|null, "updated_at": str|null,   # updated_at = heartbeat, <= 10 s apart while running
      "current": {"person": str|null, "step": str, "detail": str},   # e.g. "Search 2 of 3", "'Jane Doe' AgriTrace"
      "feed": [{"at": str, "level": "info|found|warn", "msg": str, "person"?: str, "source"?: url}],
                                                  # newest last, <= 60, plain words: "Read agritrace.example — 4,210
                                                  # characters saved as evidence", "Search 1/3 · … — 5 results",
                                                  # "Claude is reading 6 pages about Jane Doe", "Claude busy → using
                                                  # DeepSeek", "Checked the facts…: 3 verified facts, 1 unconfirmed",
                                                  # "Scored Jane Doe: Partial fit 62 · quality 58"
      "counters": {"pages_read", "searches", "facts_verified", "facts_unconfirmed", "people_done",
                   "people_total"},               # ints
      "partial": {"people": [{"id": int, "name": str, "role": str, "kind": str,
                              "status": "waiting|working|done|failed",
                              "facts": [{"id", "text", "quote", "url", "category", "source_id"}],  # verified so far
                              "score": num|null, "fit": num|null, "grade": str|null}]}
    }
    Saved as each person finishes, so their facts and scores show before the whole report is done. "stalled" =
    running with no heartbeat for 90 s (API view); the watchdog (worker drain + API loop) re-queues a stalled run
    once (warn line in the feed), then fails it with a clear reason in `error` and the feed.
TargetView = {"type": "business", "valuation_id", "ticker", "website", "company", "sector", "stage",
              "description"} | {"type": "role", "company", "title", "description", "requirements": [str]}

Report (result)
    {
      "version": "hr-1", "mode": "team|person",
      "team": TeamBlock|null,                      # null for person reports
      "people": [PersonCard],
      "method": {"person_weights": {...}, "fit_weights": {...}, "team_weights": {...}, "role_multipliers": {...},
                 "contribution": "0.5 x quality + 0.5 x fit (quality alone when there is no fit)",
                 "cap_without_evidence": 50, "notes": [str],
                 "models": {"person:<pid>": str, "team": str}, "search_providers": [str]},
      "sources": [{"id": "s1", "url", "title", "sha256", "kind": "page|snippet|provided", "fetched_at": str,
                   "person_id": int}],
      "counters": {"searches": int, "search_budget": int, "pages_fetched": int, "facts_verified": int,
                   "facts_unconfirmed": int, "facts_dropped_sensitive": int, "llm_calls": int},
      "searches": [{"person_id", "query", "provider", "results", "error"?}],
      "target": TargetView|null, "notes": [str]?,  # notes: e.g. "a person was removed after the analysis"
      "created_at": str
    }
TeamBlock
    {"score": 0..100, "grade": "A|B|C|D|E", "people_component": 0..100, "team_component": 0..100,
     "red_flag_penalty": >=0,
     "components": {"complementarity", "key_roles", "worked_together", "advisors_board", "concentration"}: 0..100,
     "component_detail": {"<component>": {"score", "rationale", "fact_ids": [str], "computed": bool}},
     "coverage": {"tech": bool, "commercial": bool, "domain": bool, "finance": bool},
     "strengths": [str], "gaps": [str], "risks": [str], "questions": [str],   # questions investors should ask
     "red_flags": [{"text": str, "fact_ids": [str]}]}                        # verified only
PersonCard
    {
      "person_id": int, "full_name", "role", "kind", "multiplier": float,
      "score": 0..100,                            # quality (plan rubric)
      "subscores": {"domain_fit"|"track_record"|"leadership"|"functional_depth"|"verifiability"|"commitment":
                    {"score", "suggested", "capped": bool, "weight", "rationale", "fact_ids": [str],
                     "self_reported": bool}},
      "fit": null | {"target_type": "business|role", "label": "founder–business fit|role fit", "score": 0..100,
                     "components": {"skills_match"|"domain_match"|"stage_scale_match"|"seniority_match"|
                                    "track_record_relevance"|"gaps": {same shape as a subscore}},
                     "requirements": [{"requirement", "must_have": bool,
                                       "status": "matched|partial|missing|unverified", "fact_ids": [str],
                                       "self_reported": bool, "note": str}],
                     "matched": [str], "missing": [str], "risks": [str], "interview_questions": [str]},
      HR v3 (report version "hr-2"; docs/PLAN-HR-V3.md §9): fit also carries lens / claimed_score /
      verified_score (= score) / verdict / knockouts / cap / relevant / template / alt_role and requirements[].evidence
      + claim_ids; "fits": {"business"?, "jd"?, "current_role"?}; "trust": CV Trust Index | null;
      "decision": {"quadrant", "fit_lens", "fit_score", "claimed_score", "trust_band", "reasons", "verify"};
      "cv_review": {..., "ledger": {"claims", "counts", "namesakes", "lookups"}}. Share-link / holder viewers get
      trust.score = null, claims[].conflict = null, namesakes = [] and ledger.restricted = true (owner decision D2).
      "contribution": 0..100,                     # what the team score uses (0.5 quality + 0.5 verified fit)
      "profile": CVProfile,
      "facts": [{"id": "p12f1", "text", "quote", "source_id": "s3", "url",
                 "category": "role|venture|exit|education|achievement|publication|skill|other"}],
      "self_reported": {"headline", "bio", "full_time", "equity_pct", "start_year", "has_cv": bool},
      "unconfirmed": [{"text", "quote": str|null, "url": str|null, "reason": str}],
      "strengths": [str], "gaps": [str], "questions": [str],
      "functions": ["tech"|"commercial"|"domain"|"finance"], "model": str|null,
      "notes": [str]                              # e.g. "LinkedIn not readable; typed bio used as self-reported"
    }
CVProfile (every item has "source": {"type": "verified|self_reported", "fact_ids": [str], "urls": [str]})
    {"headline": {"text", "source"}|null, "location": {"text": "City, Country", "source"}|null, "summary": str,
     "experience": [{"org", "title", "start", "end", "achievements": [str], "source"}],
     "education": [{"institution", "degree", "field", "start", "end", "source"}],
     "skills": [{"group", "items": [str], "source"}],
     "ventures": [{"name", "role", "outcome": "exit|acquired|ipo|active|closed|unknown", "year", "source"}],
     "publications": [{"title", "kind": "publication|patent|talk", "venue", "year", "source"}],
     "awards": [{"title", "year", "source"}], "links": [{"url", "label"}], "completeness_pct": 0..100}
Summary                                        # score: team score; person report: fit score (quality if no target)
    {"id", "mode", "name", "status", "valuation_id", "score": num|null, "grade": str|null,
     "people": [{"id": int, "full_name", "role", "kind", "score": num|null, "fit": num|null,   # names + roles +
                 "fit_label": str|null, "fit_matched": [str] (<=3), "fit_missing": [str] (<=3),  # numbers only;
                 "status": "waiting|working|done|failed",                                      # fit = fit to the
                 "url": "https://hr.blockid.au/r/<id>/p/<pid>" | ".../p/<id>" (person report)}],  # linked business
     "strengths": [str] (<=3), "gaps": [str] (<=3), "url": "https://hr.blockid.au/r/<id>",
     "confidence": "high|medium|low"|null,       # share of weighted points backed by verified facts (>=.75/.45)
     "error": str|null,                          # plain failure sentence when status == "failed"
     "error_code": str|null,                     # its code (see Limitations)
     "progress": {"phase", "pct", "eta_s", "eta_range_s", "updated_at"}|null}   # before "done": people from the live progress
    On the valuation (GET /v1/studio/valuations/{id} -> "team") also: "applied": bool, "reason": str|null,
    "applied_at": str|null (when the team score was applied to the valuation's founder_quality).
ListItem
    {"id", "mode", "name", "status", "valuation_id", "company_id", "score", "grade", "people_count",
     "target_type", "created_at", "updated_at"}
"""
from __future__ import annotations

import hmac
import ipaddress
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..agents.hr_fit import JDParse, SYSTEM_JD, clean_jd, split_protected
from ..agents.people import redact
from . import urlcheck
from .auth import COOKIE, Session
from .company_admins import CompanyAuthz
from .db import ONCHAIN_STATUSES, LimitError, jsonable
from .hr_store import HrStore, apply_to_valuation, error_detail, progress_view, public_error, summary

log = logging.getLogger(__name__)
SUGGEST_MODEL_PER_USER_HOUR = 5  # model-assisted people suggestions per wallet per hour (per API process)
JD_PARSE_PER_USER_HOUR = 20  # model JD reads per wallet per hour (identical JDs are served from a 30-day cache)
SUGGEST_MODEL_PER_DAY = 200  # and in total per day (per API process)


# ------------------------------------------------------------------ bodies
class Body(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")


def _check_url(u: str) -> str:
    u = (u or "").strip()
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.hostname or len(u) > 500:
        raise ValueError("urls must be public http(s) links")
    h = p.hostname.lower()
    try:
        ipaddress.ip_address(h)
        raise ValueError("urls must use a domain name, not an IP address")
    except ValueError as e:
        if "domain name" in str(e):
            raise
    if h == "localhost" or h.endswith((".local", ".internal", ".localhost")) or "." not in h:
        raise ValueError("urls must be public http(s) links")
    return u


class PersonIn(Body):
    full_name: str = Field(min_length=1, max_length=120)
    role: str = Field(default="", max_length=80)
    kind: Literal["founder", "cofounder", "executive", "employee", "advisor"] = "employee"
    headline: str | None = Field(default=None, max_length=200)
    full_time: bool | None = None
    start_year: int | None = Field(default=None, ge=1950)
    equity_pct: float | None = Field(default=None, ge=0, le=100)
    urls: list[str] = Field(default_factory=list, max_length=6)
    bio: str | None = Field(default=None, max_length=1500)
    cv: str | None = Field(default=None, max_length=40000)

    @field_validator("full_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v or any(ch.isdigit() for ch in v) or "@" in v:
            raise ValueError("full_name must be a person's name")
        return v

    @field_validator("start_year")
    @classmethod
    def _year(cls, v: int | None) -> int | None:
        if v is not None and v > datetime.now(timezone.utc).year:
            raise ValueError("start_year cannot be in the future")
        return v

    @field_validator("urls")
    @classmethod
    def _urls(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(_check_url(u) for u in v))


class BusinessTarget(Body):
    type: Literal["business"]
    valuation_id: str | None = Field(default=None, max_length=64)
    ticker: str | None = Field(default=None, max_length=12)
    website: str | None = Field(default=None, max_length=500)


class RoleTarget(Body):
    type: Literal["role"]
    company: str = Field(default="", max_length=200)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    requirements: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(default_factory=list,
                                                                                    max_length=30)
    # HR v3 (docs/PLAN-HR-V3.md §2.2): from the JD parser or typed; knockouts are hard must-haves
    min_years: int | None = Field(default=None, ge=0, le=40)
    seniority: Literal["entry", "mid", "senior", "lead", "executive"] | None = None
    knockouts: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(default_factory=list, max_length=6)


class JDBody(Body):
    text: str = Field(min_length=40, max_length=12_000)


Target = Annotated[BusinessTarget | RoleTarget, Field(discriminator="type")]


class TeamStart(Body):
    """`team` in POST /v1/studio/valuations."""
    people: list[PersonIn] = Field(min_length=1, max_length=20)
    consent: bool


class TeamCreate(Body):
    name: str = Field(min_length=1, max_length=200)
    website: str | None = Field(default=None, max_length=500)
    valuation_id: str | None = Field(default=None, max_length=64)
    people: list[PersonIn] = Field(min_length=1, max_length=20)
    consent: bool
    run: bool = False


class PersonReportCreate(Body):
    person: PersonIn
    target: Target | None = None
    consent: bool
    run: bool = True


class PeopleBody(Body):
    people: list[PersonIn] = Field(min_length=1, max_length=20)


class TargetBody(Body):
    target: Target | None = None


def _people_dicts(people: list[PersonIn]) -> list[dict]:
    """Emails / phone numbers are redacted from founder-typed text before it is stored."""
    out = []
    for p in people:
        d = p.model_dump()
        for k in ("headline", "bio", "cv", "role"):
            if d.get(k):
                d[k] = redact(d[k]).strip()
        out.append(d)
    return out


def _need_consent(consent: bool) -> None:
    if consent is not True:
        raise HTTPException(422, "consent: confirm that the listed people agreed to this review")


# ------------------------------------------------------------------ valuation start hook (routes.py)
def create_team_for_valuation(ctx, sess: Session, vid: str, url: str, team: TeamStart) -> str:
    """Called by POST /v1/studio/valuations with `team`: a team report linked to the new valuation, queued now;
    the worker runs it once the valuation's research is done (HrStore.claim) and then blends its score."""
    _need_consent(team.consent)
    db = ctx.need_db()
    store = HrStore(db)
    host = (urlparse(url).hostname or url).removeprefix("www.")
    tid = store.create(mode="team", name=host, website=url, valuation_id=vid, company_id=None, target=None,
                       requested_by=sess.actor, people=_people_dicts(team.people))
    try:
        store.queue_run(tid, sess.actor, per_wallet=None, max_active=None)  # part of the valuation request
    except LimitError as e:  # pragma: no cover - fresh draft cannot be queued already
        raise HTTPException(429, str(e)) from None
    db.audit(sess.actor, "hr_team_created", tid, valuation_id=vid, people=len(team.people), consent=True)
    return tid


# ------------------------------------------------------------------ router
def build_hr_router(ctx) -> APIRouter:
    r = APIRouter()
    s = ctx.settings
    authz = CompanyAuthz(ctx)

    def session(request: Request) -> Session | None:
        sid = request.cookies.get(COOKIE)
        return ctx.sessions.get(sid) if sid else None

    def require_user(sess: Session | None = Depends(session)) -> Session:
        if sess is None:
            raise HTTPException(401, "sign in required")
        return sess

    def store() -> HrStore:
        return HrStore(ctx.need_db())

    def is_admin(sess: Session | None) -> bool:
        return bool(sess) and sess.is_admin and not sess.must_change

    def is_owner(sess: Session | None, t: dict) -> bool:
        return bool(sess) and (t.get("requested_by") or "").lower() == sess.actor.lower()

    def is_demo(t: dict) -> bool:
        return bool(s.demo_wallet) and (t.get("requested_by") or "").lower() == s.demo_wallet.lower()

    def share_ok(t: dict, share: str | None) -> bool:
        return bool(share and t.get("share_token")) and hmac.compare_digest(share, t["share_token"])

    def can_edit(sess: Session | None, t: dict) -> bool:
        return is_admin(sess) or is_owner(sess, t)

    def can_read(sess: Session | None, t: dict, share: str | None) -> bool:
        if share_ok(t, share) or can_edit(sess, t):
            return True
        if sess is None:
            return False
        if is_demo(t):
            return True
        cid = store().linked_company(t)
        return bool(cid) and authz.admin_role(sess, cid) is not None

    def can_read_valuation(sess: Session | None, vid: str | None) -> bool:
        """Same rule as GET /v1/studio/valuations/{id}: admin, requester, or any signed-in viewer once listed."""
        if not vid or sess is None:
            return False
        db = ctx.need_db()
        v = db.get_valuation(vid)
        if not v:
            return False
        if is_admin(sess) or (v.get("requested_by") or "").lower() == sess.actor.lower():
            return True
        return bool(db.one("SELECT 1 AS x FROM studio.companies WHERE valuation_id=%s AND status = ANY(%s) LIMIT 1",
                           (vid, list(ONCHAIN_STATUSES))))

    def load(tid: str) -> dict:
        t = store().team(tid[:40])
        if not t:
            raise HTTPException(404, "unknown report")
        return t

    def load_edit(tid: str, sess: Session) -> dict:
        t = load(tid)
        if not can_edit(sess, t):
            raise HTTPException(403, "only the requester or a platform admin can change this report")
        return t

    def full_detail(sess: Session | None, t: dict) -> bool:
        """Claim conflicts, namesakes and the trust number: requester, platform / company admins, demo reports.
        Share-link and holder viewers see bands only (owner decision D2)."""
        if can_edit(sess, t) or is_demo(t):
            return True
        cid = store().linked_company(t) if sess is not None else None
        return bool(cid) and authz.admin_role(sess, cid) is not None

    def view(t: dict, sess: Session | None) -> dict:
        ppl = store().people(t["id"])
        edit = can_edit(sess, t)
        return jsonable({
            "id": t["id"], "mode": t.get("mode") or "team", "name": t["name"], "website": t.get("website"),
            "valuation_id": t.get("valuation_id"), "company_id": store().linked_company(t),
            "target": t.get("target"), "status": t["status"], "error": public_error(t)[1],
            "error_code": public_error(t)[0],
            **({"error_detail": error_detail(t)} if is_admin(sess) else {}),
            "consent": bool(t.get("consent")), "consented_at": t.get("consented_at"), "is_demo": is_demo(t),
            "mine": is_owner(sess, t), "can_edit": edit, "share_token": t.get("share_token") if edit else None,
            "report_url": f"{s.hr_public_url}/r/{t['id']}", "created_at": t.get("created_at"),
            "updated_at": t.get("updated_at"), "steps": t.get("steps") or [],
            "people": [{"id": p["id"], "full_name": p["full_name"], "role": p["role"], "kind": p["kind"],
                        "headline": p.get("headline"), "full_time": p.get("full_time"),
                        "start_year": p.get("start_year"), "equity_pct": p.get("equity_pct"),
                        "urls": p.get("urls") or [], "bio": p.get("bio"),
                        "has_cv": bool((p.get("cv") or "").strip()), "position": p["position"]} for p in ppl],
            "result": _public_result(t.get("result"), full=full_detail(sess, t)),
            "progress": progress_view(t),
        })

    def audit(sess: Session, action: str, target: str, **detail) -> None:
        ctx.need_db().audit(sess.actor, action, target, role="platform_admin" if sess.is_admin else "user", **detail)

    def queue(t: dict, sess: Session) -> None:
        try:
            store().queue_run(t["id"], sess.actor, per_wallet=None if is_admin(sess) else s.hr_runs_per_day,
                              max_active=s.hr_max_active)
        except LimitError as e:
            code = 409 if "already" in str(e) else 429
            raise HTTPException(code, str(e)) from None
        audit(sess, "hr_run_requested", t["id"], mode=t.get("mode"))

    def check_business_target(tg: BusinessTarget, sess: Session) -> dict:
        db = ctx.need_db()
        if not (tg.valuation_id or tg.ticker or tg.website):
            raise HTTPException(422, "target: give valuation_id, ticker or website")
        if tg.valuation_id and not can_read_valuation(sess, tg.valuation_id):
            raise HTTPException(403, "target valuation: not readable by you")
        if tg.ticker:
            c = db.one("SELECT id, status, created_by FROM studio.companies WHERE ticker=%s", (tg.ticker.upper(),))
            if not c:
                raise HTTPException(404, "target: unknown ticker")
            if c["status"] not in ONCHAIN_STATUSES and not (is_admin(sess) or (c.get("created_by") or "").lower()
                                                            == sess.actor.lower()):
                raise HTTPException(403, "target: that business is not listed")
        if tg.website:
            try:
                _check_url(tg.website)
            except ValueError as e:
                raise HTTPException(422, f"target.website: {e}") from None
        return tg.model_dump(exclude_none=True)

    def target_dict(tg, sess: Session) -> dict | None:
        if tg is None:
            return None
        if isinstance(tg, BusinessTarget):
            return check_business_target(tg, sess)
        d = tg.model_dump()
        # requirements touching a protected attribute are shown back as warnings and never scored
        d["requirements"], f1 = split_protected(d["requirements"])
        d["knockouts"], f2 = split_protected(d["knockouts"])
        d["flagged"] = f1 + f2
        return d

    # -------------------------------------------------------------- create
    @r.post("/v1/hr/teams")
    def create_team(body: TeamCreate, sess: Session = Depends(require_user)):
        _need_consent(body.consent)
        db = ctx.need_db()
        website = None
        if body.website:
            try:
                website = _check_url(body.website)
            except ValueError as e:
                raise HTTPException(422, f"website: {e}") from None
        cid = None
        if body.valuation_id:
            if not can_read_valuation(sess, body.valuation_id):
                raise HTTPException(403, "valuation: not readable by you")
            v = db.get_valuation(body.valuation_id)
            website = website or v.get("url")
            c = db.one("SELECT id FROM studio.companies WHERE valuation_id=%s AND status NOT IN ('rejected','failed') "
                       "ORDER BY id DESC LIMIT 1", (body.valuation_id,))
            cid = c["id"] if c else None
        tid = store().create(mode="team", name=" ".join(body.name.split()), website=website,
                             valuation_id=body.valuation_id, company_id=cid, target=None, requested_by=sess.actor,
                             people=_people_dicts(body.people))
        audit(sess, "hr_team_created", tid, valuation_id=body.valuation_id, people=len(body.people), consent=True)
        t = load(tid)
        if body.run:
            queue(t, sess)
            t = load(tid)
        return view(t, sess)

    @r.post("/v1/hr/people-reports")
    def create_person_report(body: PersonReportCreate, sess: Session = Depends(require_user)):
        _need_consent(body.consent)
        target = target_dict(body.target, sess)
        vid = (target or {}).get("valuation_id")
        tid = store().create(mode="person", name=body.person.full_name, website=(target or {}).get("website"),
                             valuation_id=vid, company_id=None, target=target, requested_by=sess.actor,
                             people=_people_dicts([body.person]))
        audit(sess, "hr_person_report_created", tid, target_type=(target or {}).get("type"), consent=True)
        t = load(tid)
        if body.run:
            queue(t, sess)
            t = load(tid)
        return view(t, sess)

    # -------------------------------------------------------------- edit + run
    @r.put("/v1/hr/teams/{tid}/people")
    def replace_people(tid: str, body: PeopleBody, sess: Session = Depends(require_user)):
        t = load_edit(tid, sess)
        if (t.get("mode") or "team") == "person" and len(body.people) != 1:
            raise HTTPException(422, "a person report has exactly one person")
        try:
            store().replace_people(t["id"], _people_dicts(body.people))
        except LimitError as e:
            raise HTTPException(409, str(e)) from None
        audit(sess, "hr_people_replaced", t["id"], people=len(body.people))
        return view(load(tid), sess)

    @r.put("/v1/hr/teams/{tid}/target")
    def set_target(tid: str, body: TargetBody, sess: Session = Depends(require_user)):
        t = load_edit(tid, sess)
        if (t.get("mode") or "team") != "person":
            raise HTTPException(409, "a team report's target is its business (valuation_id / website)")
        try:
            store().set_target(t["id"], target_dict(body.target, sess))
        except LimitError as e:
            raise HTTPException(409, str(e)) from None
        return view(load(tid), sess)

    @r.post("/v1/hr/teams/{tid}/run")
    def run(tid: str, sess: Session = Depends(require_user)):
        t = load_edit(tid, sess)
        queue(t, sess)
        return view(load(tid), sess)

    # -------------------------------------------------------------- read
    @r.get("/v1/hr/teams")
    def list_teams(mine: int = Query(default=1, ge=0, le=1), sess: Session = Depends(require_user)):
        db = ctx.need_db()
        if mine == 0 and is_admin(sess):
            rows = db.all("SELECT * FROM studio.hr_teams ORDER BY created_at DESC LIMIT 200")
        else:
            rows = db.all("SELECT * FROM studio.hr_teams WHERE lower(requested_by)=lower(%s) "
                          "ORDER BY created_at DESC LIMIT 200", (sess.actor,))
        counts = {x["team_id"]: int(x["n"]) for x in db.all(
            "SELECT team_id, count(*) AS n FROM studio.hr_people WHERE team_id = ANY(%s) GROUP BY team_id",
            ([t["id"] for t in rows],))}
        out = []
        for t in rows:
            sm = summary(t, s.hr_public_url)
            out.append({"id": t["id"], "mode": t.get("mode") or "team", "name": t["name"], "status": t["status"],
                        "valuation_id": t.get("valuation_id"), "company_id": t.get("company_id"),
                        "score": sm["score"], "grade": sm["grade"], "people_count": counts.get(t["id"], 0),
                        "target_type": (t.get("target") or {}).get("type") or ("business" if t.get("mode") != "person"
                                                                               else None),
                        "created_at": t.get("created_at"), "updated_at": t.get("updated_at")})
        return jsonable({"teams": out})

    def get_report(tid: str, share: str | None, sess: Session | None) -> dict:
        t = load(tid)
        if not can_read(sess, t, share):
            raise HTTPException(401 if sess is None else 403, "sign in required" if sess is None
                                else "not allowed to read this report")
        return view(t, sess)

    @r.get("/v1/hr/teams/{tid}")
    def get_team(tid: str, share: str | None = Query(default=None, max_length=64),
                 sess: Session | None = Depends(session)):
        return get_report(tid, share, sess)

    @r.get("/v1/hr/people-reports/{tid}")
    def get_person_report(tid: str, share: str | None = Query(default=None, max_length=64),
                          sess: Session | None = Depends(session)):
        return get_report(tid, share, sess)

    @r.get("/v1/hr/teams/{tid}/summary")
    def get_summary(tid: str, share: str | None = Query(default=None, max_length=64),
                    sess: Session | None = Depends(session)):
        t = load(tid)
        if not (can_read(sess, t, share) or can_read_valuation(sess, t.get("valuation_id"))):
            raise HTTPException(401 if sess is None else 403, "sign in required" if sess is None
                                else "not allowed to read this report")
        return jsonable(summary(t, s.hr_public_url))

    # -------------------------------------------------------------- people suggestions (eth "Assess the founders")
    def evidence_store():
        if ctx.evidence is not None:
            return ctx.evidence
        runner = getattr(ctx, "_runner", None)
        if runner is not None and getattr(runner, "deps", None) is not None:
            return runner.deps.evidence
        from ..tools.brave import EvidenceStore

        path = Path(s.data_dir) / "evidence.sqlite"
        return EvidenceStore(path) if path.exists() else None

    @r.get("/v1/hr/suggest-people")
    def suggest_people(request: Request, valuation_id: str | None = Query(default=None, max_length=64),
                       website: str | None = Query(default=None, max_length=500),
                       sess: Session = Depends(require_user)):
        from ..agents.people import names_person
        from ..agents.site_intake import page_rank, people_from_text, person_kind, site_subject

        db = ctx.need_db()
        found: dict[str, dict] = {}
        exclude: tuple[str, ...] = ()

        def add(name: str, role: str, url: str | None) -> None:
            name = " ".join((name or "").split())[:120]
            if not name or any(ch.isdigit() for ch in name) or "@" in name or len(found) >= 12:
                return
            key = name.lower()
            if key in found:
                old = found[key]["role"]
                if role and (not old or ("founder" in role.lower() and "founder" not in old.lower())):
                    found[key].update(role=redact(role).strip()[:80], kind=person_kind(role))
                return
            role = redact(role or "").strip()[:80]
            found[key] = {"full_name": name, "role": role, "kind": person_kind(role), "source_url": url}

        site = None
        pages: list = []  # (EvidenceItem, text) site intake already stored
        if valuation_id:
            v = db.get_valuation(valuation_id)
            if not v:
                raise HTTPException(404, "unknown valuation")
            if not can_read_valuation(sess, valuation_id):
                raise HTTPException(403, "valuation: not readable by you")
            site = v.get("url")
            prof = (v.get("result") or {}).get("profile") or {}
            host_label = (urlparse(site or "").hostname or "").removeprefix("www.").split(".")[0]
            exclude = tuple(x for x in (prof.get("company_name"), host_label) if x)
            ev = evidence_store()
            if ev is not None:
                try:
                    pages = sorted(ev.for_subject(site_subject(valuation_id), limit=12),
                                   key=lambda x: (page_rank(x[0].url), x[0].url))
                except Exception:  # noqa: BLE001 - suggestions are best effort
                    log.exception("hr suggestions evidence")
            docs = sorted(prof.get("documents_reviewed") or [], key=page_rank)
            for f in prof.get("founders") or []:
                where = next((e.url for e, text in pages if names_person(text or "", f.get("name") or "")), None)
                add(f.get("name") or "", f.get("role") or "", where or (docs[0] if docs else site))
            for e, text in pages:
                if page_rank(e.url) <= 1 or not found:
                    for p in people_from_text(text or "", exclude):
                        add(p["full_name"], p["role"], e.url)
        elif website:
            try:
                site = _check_url(website)
            except ValueError as e:
                raise HTTPException(422, f"website: {e}") from None
            exclude = ((urlparse(site).hostname or "").removeprefix("www.").split(".")[0],)
        else:
            raise HTTPException(422, "give valuation_id or website")
        source = "site_intake" if found else "none"
        texts: list[tuple[str, str]] = [(e.url, text or "") for e, text in pages]
        if not found and site:  # at most one fetch of the obvious team page, SSRF-safe
            if not ctx.url_limiter.allow("hr-suggest:" + sess.actor.lower()):
                raise HTTPException(429, "too many look-ups; wait a minute and try again")
            pu = urlparse(site)
            team_url = f"{pu.scheme}://{pu.netloc}/team"
            text = ""
            try:
                from ..tools.brave import fetch_page

                text = (ctx.page_fetcher or fetch_page)(team_url) or ""
            except Exception as e:  # noqa: BLE001 - 404, blocked host, timeout: no suggestions
                log.info("hr suggestions: %s not readable: %s", team_url, str(e)[:200])
            for p in people_from_text(text, exclude):
                add(p["full_name"], p["role"], team_url)
            source = "fetched" if found else "none"
            if text.strip():
                texts.append((team_url, text))
        if not found and texts:  # heuristic found nobody: ONE budgeted model call over the text we already have
            for p in model_suggestions(sess, texts, exclude, valuation_id or site):
                add(p["full_name"], p["role"], p["source_url"])
                if p["full_name"].lower() in found:
                    found[p["full_name"].lower()]["note"] = p["note"]
            if found:
                source = "model"
        return {"website": site, "source": source, "people": list(found.values())[:12]}

    suggest_user_limit = urlcheck.RateLimiter(limit=SUGGEST_MODEL_PER_USER_HOUR, window_s=3600)
    suggest_day_limit = urlcheck.RateLimiter(limit=SUGGEST_MODEL_PER_DAY, window_s=86_400)

    def suggest_llm():
        """The People Analyst's model chain (tests set ctx.suggest_llm); None when no runner is configured."""
        llm = getattr(ctx, "suggest_llm", None)
        if llm is not None:
            return llm
        try:
            deps = ctx.runner().deps
        except Exception:  # noqa: BLE001 - 503 runner not configured: no model suggestions
            return None
        return deps.agent_llm.get("people_analyst", deps.llm)

    def model_suggestions(sess: Session, texts: list[tuple[str, str]], exclude: tuple[str, ...],
                          target: str | None) -> list[dict]:
        from ..agents.site_intake import page_rank, suggest_people_with_model
        from ..llm import last_provider

        team_about = [(u, t) for u, t in texts if page_rank(u) <= 1]
        texts = team_about or texts
        llm = suggest_llm()
        if llm is None or not suggest_user_limit.allow(sess.actor.lower()) or not suggest_day_limit.allow("all"):
            return []
        try:
            got = suggest_people_with_model(llm, texts, exclude, tier=s.hr_tier)
        except Exception as e:  # noqa: BLE001 - busy / invalid output: the user just gets no suggestions
            log.info("hr model suggestions failed: %s", str(e)[:300])
            ctx.need_db().audit(sess.actor, "hr_suggest_model", target, ok=False, error=str(e)[:300])
            return []
        ctx.need_db().audit(sess.actor, "hr_suggest_model", target, ok=True, people=len(got),
                            pages=len(texts), provider=last_provider() or None)
        for p in got:
            u = urlparse(p["source_url"])
            p["note"] = f"suggested from {(u.hostname or '').removeprefix('www.')}{u.path.rstrip('/')}"
        return got

    # -------------------------------------------------------------- JD parser (docs/PLAN-HR-V3.md §2.2)
    jd_user_limit = urlcheck.RateLimiter(limit=JD_PARSE_PER_USER_HOUR, window_s=3600)
    jd_memo: dict[str, dict] = {}  # per API process, when the evidence DB is not reachable

    @r.post("/v1/hr/jd/parse")
    def parse_jd(body: JDBody, sess: Session = Depends(require_user)):
        import hashlib

        from ..agents.site_intake import complete_profile
        from ..deps import UNTRUSTED_NOTE

        text = redact(body.text)
        key = "hr:jd:" + hashlib.sha256(text.encode()).hexdigest()
        ev = evidence_store()
        hit = jd_memo.get(key)
        if hit is None and ev is not None:
            try:
                hit = ev.cache_get(key, 30 * 86_400)
            except Exception:  # noqa: BLE001
                hit = None
        if hit:
            return {**hit, "cached": True}
        llm = suggest_llm()
        if llm is None:
            raise HTTPException(503, "the JD reader is not available right now")
        if not is_admin(sess) and not jd_user_limit.allow(sess.actor.lower()):
            raise HTTPException(429, "too many JD reads this hour — try again later")
        try:
            got = complete_profile(llm, "extract_json", s.hr_tier, f"{SYSTEM_JD}\n\n{UNTRUSTED_NOTE}",
                                   f"<data>\n{text[:12_000]}\n</data>", JDParse)
        except Exception as e:  # noqa: BLE001 - busy / invalid output
            log.info("hr jd parse failed: %s", str(e)[:300])
            ctx.need_db().audit(sess.actor, "hr_jd_parse", None, ok=False, error=str(e)[:300])
            raise HTTPException(503, "the JD reader is busy — add the requirements by hand or try again") from None
        out = clean_jd(got)
        ctx.need_db().audit(sess.actor, "hr_jd_parse", None, ok=True, must=len(out["must"]),
                            flagged=len(out["flagged"]))
        if len(jd_memo) >= 500:
            jd_memo.clear()
        jd_memo[key] = out
        if ev is not None:
            try:
                ev.cache_put(key, out)
            except Exception:  # noqa: BLE001
                pass
        return {**out, "cached": False}

    # -------------------------------------------------------------- share, delete, blend
    @r.post("/v1/hr/teams/{tid}/share")
    def share(tid: str, sess: Session = Depends(require_user)):
        t = load_edit(tid, sess)
        tok = store().rotate_share(t["id"])
        audit(sess, "hr_share_link", t["id"])
        return {"share_token": tok, "url": f"{s.hr_public_url}/r/{t['id']}?share={tok}"}

    @r.delete("/v1/hr/teams/{tid}/share")
    def unshare(tid: str, sess: Session = Depends(require_user)):
        t = load_edit(tid, sess)
        ctx.need_db().exec("UPDATE studio.hr_teams SET share_token=NULL, updated_at=now() WHERE id=%s", (t["id"],))
        audit(sess, "hr_share_revoked", t["id"])
        return {"ok": True}

    def drop_evidence(prefix: str) -> None:
        """Best effort: the evidence DB lives in BLOCKID_DATA_DIR (shared with the worker in production)."""
        try:
            from ..tools.brave import EvidenceStore

            path = Path(s.data_dir) / "evidence.sqlite"
            if path.exists():
                EvidenceStore(path).delete_subject(prefix, prefix=True)
        except Exception:
            log.exception("hr evidence delete")

    @r.delete("/v1/hr/people/{pid}")
    def delete_person(pid: int, sess: Session = Depends(require_user)):
        db = ctx.need_db()
        p = db.one("SELECT id, team_id, full_name FROM studio.hr_people WHERE id=%s", (pid,))
        if not p:
            raise HTTPException(404, "unknown person")
        t = load_edit(p["team_id"], sess)
        if t["status"] in ("queued", "running"):
            raise HTTPException(409, "the report is running; try again when it is done")
        from ..agents.people import recompute_team

        db.exec("DELETE FROM studio.hr_people WHERE id=%s", (pid,))
        drop_evidence(f"hr:{t['id']}:{pid}")
        res = t.get("result")
        if res:
            res = dict(res)
            res["people"] = [c for c in res.get("people") or [] if c.get("person_id") != pid]
            used = {f.get("source_id") for c in res["people"] for f in c.get("facts") or []}
            res["sources"] = [x for x in res.get("sources") or [] if x.get("id") in used]
            res["searches"] = [x for x in res.get("searches") or [] if x.get("person_id") != pid]
            (res.get("method") or {}).get("models", {}).pop(f"person:{pid}", None)
            if res.get("team") is not None:
                rest = {x["id"]: x for x in store().people(t["id"])}
                res["team"] = recompute_team(res, rest)
                res.setdefault("notes", []).append("A person was removed after the analysis; team texts may still "
                                                   "refer to them until the report is re-run.")
            store().set_result(t["id"], res)
        audit(sess, "hr_person_removed", t["id"], person_id=pid)  # the name is not written to the audit log
        t = load(t["id"])
        if t.get("valuation_id") and t["status"] == "done" and (t.get("mode") or "team") == "team":
            apply_to_valuation(db, t, s.hr_public_url)
        return {"ok": True, "team_id": t["id"]}

    @r.delete("/v1/hr/teams/{tid}")
    def delete_team(tid: str, sess: Session = Depends(require_user)):
        t = load_edit(tid, sess)
        if t["status"] in ("queued", "running"):
            raise HTTPException(409, "the report is running; try again when it is done")
        db = ctx.need_db()
        db.exec("DELETE FROM studio.hr_teams WHERE id=%s", (t["id"],))
        drop_evidence(f"hr:{t['id']}:")
        if t.get("valuation_id"):
            v = db.get_valuation(t["valuation_id"])
            if v and ((v.get("result") or {}).get("team") or {}).get("id") == t["id"]:
                db.merge_result(t["valuation_id"], {"team": None})
        audit(sess, "hr_team_deleted", t["id"])
        return {"ok": True}

    @r.post("/v1/hr/teams/{tid}/apply-to-valuation")
    def apply(tid: str, sess: Session = Depends(require_user)):
        t = load_edit(tid, sess)
        if not t.get("valuation_id"):
            raise HTTPException(409, "the report is not linked to a valuation")
        if t["status"] != "done":
            raise HTTPException(409, f"the report is {t['status']}, not done")
        out = apply_to_valuation(ctx.need_db(), t, s.hr_public_url)
        audit(sess, "hr_apply_to_valuation", t["id"], valuation_id=t["valuation_id"], applied=out["applied"])
        return jsonable(out)

    return r


def _public_result(res: dict | None, *, full: bool = True) -> dict | None:
    """The stored report minus internal inputs; without `full`, claim conflicts, namesakes and the trust number are
    removed (bands and statuses stay)."""
    if not res:
        return None
    out = {k: v for k, v in res.items() if k not in ("team_inputs",)}
    if full:
        return out
    cards = []
    for c in out.get("people") or []:
        c = dict(c)
        if c.get("trust"):
            c["trust"] = {**c["trust"], "score": None}
        rv = c.get("cv_review")
        if rv and rv.get("ledger"):
            lg = rv["ledger"]
            c["cv_review"] = {**rv, "ledger": {**lg, "namesakes": [], "restricted": True,
                                               "claims": [{**x, "conflict": None} for x in lg.get("claims") or []]}}
        cards.append(c)
    return {**out, "people": cards}
