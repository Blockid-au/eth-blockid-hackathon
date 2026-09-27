"""Market Sizer (evaluation v5, docs/PLAN-EVALUATION-V5.md §1.2 "Market", §2).

Bottom-up first: the model only names WHO pays (target customer, with a verbatim quote from the site) and — for
Australian business customers — the ANZSIC division + size band; code looks the count up in the local ABS Counts of
Australian Businesses table (June 2025) and multiplies by the annual price (pricing page claim or founder input).
Top-down TAM and CAGR are kept only with a verbatim quote naming the figure; each source gets a quality tier
(government 1 … blog / vendor PR 4). No figure without a quote.
"""
from __future__ import annotations

import re

from ..schemas import MarketSizeClaims, MarketSizing, MetricValue
from ..tools import lookups
from .analysts import ask, digest, quote_found, source_tier

AGENT = "market_sizer"
ALLOWED = {"tam", "sam", "cagr", "target_customer_count", "annual_price"}
PATTERN = re.compile(r"market|billion|million|\bCAGR\b|compound annual|growth rate|businesses|companies in|"
                     r"number of|pric|per month|per year|/mo|/yr|annual|subscription|plan|customers|serve|for ", re.IGNORECASE)
SYSTEM = """You extract MARKET SIZE facts for the named startup from the numbered evidence.
- target_customer: who pays for the product, <= 12 words, as the evidence describes them, with customer_quote (a
  verbatim excerpt from the company's own website describing its customers) and customer_source_url.
- If the target customers are Australian businesses: anzsic_division = the ANZSIC division letter (A-S) they belong
  to (e.g. dental clinics -> Q, builders -> E, cafes -> H, accountants -> M) and size_band (all, employing,
  non_employing, 1-19, 20-199, 200+). Otherwise leave both empty.
- claims (only numbers the evidence states): tam (market size of the segment, subject market), cagr (segment growth %,
  subject market), target_customer_count (number of potential customers, subject market), annual_price (the
  startup's price per customer per year or per month, subject company — give the number and unit as written), sam.
  source_url copied exactly; quote verbatim (<= 300 chars) containing the number; period as written.
Never compute, convert or estimate. Empty is fine."""
MONTHLY = re.compile(r"per month|/\s?mo\b|monthly|a month|/month", re.IGNORECASE)


def run(ctx: dict) -> dict:
    deps, profile, v, typed = ctx["deps"], ctx["profile"], ctx["verifier"], ctx["typed"]
    text = digest(ctx["pool"], PATTERN)
    ms = MarketSizing()
    metrics: dict[str, MetricValue] = {}
    if not text:
        return {"claims": [], "dropped": [], "market_sizing": ms, "metrics": metrics}
    out = ask(deps, AGENT, SYSTEM, f"Startup: {profile.company_name} — {profile.sector}; country {profile.country}"
              f"\n\n<data>\n{text}\n</data>", MarketSizeClaims)
    if out is None:
        return {"claims": [], "dropped": [], "market_sizing": ms, "metrics": metrics, "error": "extraction failed"}
    claims, dropped = v.claims(out.claims, "market_size", ALLOWED, limit=8)
    kept = []
    for c in claims:
        if c.metric == "annual_price" and c.value_aud is not None and MONTHLY.search(c.quote):
            c.value_aud = round(c.value_aud * 12, 2)  # code annualises a monthly price stated in the quote
            c.period = (c.period + " (×12 from monthly)").strip()
        if c.metric in ("tam", "cagr") and c.subject != "market":
            c.subject = "market"
        kept.append(c)
    tiers = [source_tier(c.source_url) for c in kept if c.metric in ("tam", "cagr", "target_customer_count")]
    ms.source_tier = min(tiers) if tiers else 0
    # bottom-up count from the ABS table (AU business customers only), the customer description must be verified
    cq_ok = bool(out.customer_quote) and quote_found(out.customer_quote, v.texts.get(out.customer_source_url, []))
    if out.target_customer and cq_ok:
        ms.target_customer = out.target_customer[:120]
    elif out.target_customer:
        dropped.append("market_size: target customer description not verified on the page")
    if cq_ok and out.anzsic_division and (profile.country or "AU").upper() in ("AU", "AUS") \
            and not typed.get("target_customer_count"):
        hit = lookups.abs_count(out.anzsic_division, out.size_band or "employing")
        if hit:
            ms.target_customers_source = f"abs:{hit['code']}:{hit['band']}"
            ms.source_tier = 1 if not ms.source_tier else min(ms.source_tier, 1)
            metrics["target_customer_count"] = MetricValue(
                value=float(hit["count"]), unit="count", level=3, source="registry", source_url=hit["source_url"],
                as_of=hit["as_of"], note=f"{hit['note']} — division chosen for: {ms.target_customer}"[:300])
    deps.audit.record(AGENT, "claims_verified", kept=len(kept), dropped=len(dropped),
                      abs=bool(metrics.get("target_customer_count")))
    return {"claims": kept, "dropped": dropped, "market_sizing": ms, "metrics": metrics}
