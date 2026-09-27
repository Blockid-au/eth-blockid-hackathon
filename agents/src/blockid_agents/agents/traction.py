"""Traction Analyst (evaluation v5, docs/PLAN-EVALUATION-V5.md §2): cited revenue / growth / customers / pipeline.

One `extract_json` call (TractionClaims) over a keyword-windowed digest of evidence already stored for the valuation
(site pages, research pages, the conditional "traction" search). Code verifies every claim (agents/analysts.Verifier)
and every named customer (quote on the page names the customer). No score comes from the model.
"""
from __future__ import annotations

import re

from ..schemas import TractionClaims, VerifiedClaim
from .analysts import ask, digest, quote_found

AGENT = "traction_analyst"
ALLOWED = {"arr", "revenue", "mrr", "revenue_growth_yoy", "paying_customers", "customers", "active_users", "mau",
           "dau", "waitlist", "pilots_paid", "lois", "contracted_backlog", "pipeline", "gross_margin", "gmv",
           "take_rate", "raised_to_date"}
PATTERN = re.compile(r"revenue|\bARR\b|\bMRR\b|recurring|customers?|clients?|users|subscribers|case stud|trusted by|"
                     r"partner|contract|pilot|waitlist|letter of intent|\bLOI|growth|grew|\bYoY\b|year[- ]on[- ]year|"
                     r"per cent|%|pipeline|backlog|GMV|take rate|margin", re.IGNORECASE)
SYSTEM = """You extract COMMERCIAL TRACTION facts about the named startup from the numbered evidence.
Return claims only when the evidence states the number. For each claim:
- metric: one of arr, revenue, mrr, revenue_growth_yoy, paying_customers, active_users, dau, waitlist, pilots_paid,
  lois, contracted_backlog, pipeline, gross_margin, gmv, take_rate, raised_to_date
- value as stated (plain number in `unit`: 'A$2.4m' -> 2400000 unit AUD; '140%' -> 140 unit %; '500 customers' ->
  500 unit count); period as written; source_url copied exactly from the evidence list; quote = a verbatim excerpt
  (<= 300 chars) of that source that contains the number; subject = company.
- "run rate" is not ARR (use metric revenue). GMV / payment volume is gmv, never revenue.
logos: named customer organisations of THIS startup, each with a verbatim quote that names it.
revenue_model: subscription / transactional / marketplace / services / hardware / other, only if the evidence says.
Never compute or estimate. Empty lists are fine."""


def run(ctx: dict) -> dict:
    deps, profile, v = ctx["deps"], ctx["profile"], ctx["verifier"]
    text = digest(ctx["pool"], PATTERN)
    if not text:
        return {"claims": [], "dropped": [], "revenue_model": ""}
    out = ask(deps, AGENT, SYSTEM, f"Startup: {profile.company_name} — {profile.sector}; country {profile.country}"
              f"\n\n<data>\n{text}\n</data>", TractionClaims)
    if out is None:
        return {"claims": [], "dropped": [], "error": "extraction failed", "revenue_model": ""}
    claims, dropped = v.claims(out.claims, "traction", ALLOWED, limit=12)
    seen = set()
    for lg in out.logos[:12]:
        name = (lg.name or "").strip()
        if not name or name.lower() in seen:
            continue
        texts = v.texts.get(lg.source_url, [])
        if not texts or not quote_found(lg.quote, texts, 6) or name.lower() not in lg.quote.lower():
            dropped.append(f"traction: customer {name!r}: quote not verified")
            continue
        if v.name and v.name in name.lower():
            continue  # the company itself
        seen.add(name.lower())
        claims.append(VerifiedClaim(metric="customer_logo", value=None, unit="name", period="", as_of="",
                                    source_url=lg.source_url, quote=lg.quote[:300], subject="company",
                                    level=v.level_for(lg.source_url), analyst="traction"))
    rm = out.revenue_model if out.revenue_model and out.revenue_model_quote and any(
        quote_found(out.revenue_model_quote, t) for t in v.texts.values()) else ""
    deps.audit.record(AGENT, "claims_verified", kept=len(claims), dropped=len(dropped))
    return {"claims": claims, "dropped": dropped, "revenue_model": rm}
