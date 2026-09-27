"""Retention Analyst (evaluation v5, docs/PLAN-EVALUATION-V5.md §2): cited NRR / GRR / churn / reviews / NPS.

One `extract_json` call (RetentionClaims) over stored evidence (site testimonials, review pages from the conditional
"reviews" search). App Store rating/count come from the free iTunes lookup (tools/lookups.py), not from the model.
"""
from __future__ import annotations

import re

from ..schemas import RetentionClaims
from .analysts import ask, digest

AGENT = "retention_analyst"
ALLOWED = {"nrr", "grr", "logo_churn_monthly", "m3_retention", "m12_retention", "dau_mau", "review_rating",
           "review_count", "nps", "top_customer_share"}
PATTERN = re.compile(r"retention|\bNRR\b|\bGRR\b|churn|renew|net revenue|reviews?|rating|stars?|out of 5|/5|\bNPS\b|"
                     r"net promoter|customers since|cohort|G2|Capterra|Trustpilot|App Store|Google Play", re.IGNORECASE)
SYSTEM = """You extract CUSTOMER RETENTION facts about the named startup from the numbered evidence.
Claims only when the evidence states the number:
- metric: nrr, grr, logo_churn_monthly, m3_retention, m12_retention, dau_mau (all in %), review_rating (e.g. 4.6
  out of 5 -> 4.6 unit rating), review_count (count), nps (score), top_customer_share (%)
- a review rating must be for THIS startup's product on a review site or app store page.
- value as stated, unit, period as written, source_url copied exactly, quote verbatim (<= 300 chars) containing the
  number, subject = company. Never compute or estimate. An empty list is fine."""


def run(ctx: dict) -> dict:
    deps, profile, v = ctx["deps"], ctx["profile"], ctx["verifier"]
    text = digest(ctx["pool"], PATTERN)
    if not text:
        return {"claims": [], "dropped": []}
    out = ask(deps, AGENT, SYSTEM, f"Startup: {profile.company_name} — {profile.sector}\n\n<data>\n{text}\n</data>",
              RetentionClaims)
    if out is None:
        return {"claims": [], "dropped": [], "error": "extraction failed"}
    claims, dropped = v.claims(out.claims, "retention", ALLOWED, limit=10)
    ok = []
    for c in claims:  # bounds a model cannot talk its way around
        if c.metric == "review_rating" and not (0 < (c.value or 0) <= 5):
            dropped.append(f"retention: review_rating {c.value}: not on a 5-point scale")
        elif c.metric in ("nrr",) and not (0 < (c.value or 0) <= 300):
            dropped.append(f"retention: nrr {c.value}: out of range")
        else:
            ok.append(c)
    deps.audit.record(AGENT, "claims_verified", kept=len(ok), dropped=len(dropped))
    return {"claims": ok, "dropped": dropped}
