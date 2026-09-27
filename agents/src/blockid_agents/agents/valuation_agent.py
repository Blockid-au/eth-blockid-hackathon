"""Valuation Agent (valuation v5, docs/PLAN-VALUATION-V5.md §5). Graph node `valuation_methods`, after `svi`.

The model only EXTRACTS and CITES inputs; code computes every number (tools/valuation_v5.py):
  1. industry pick      -> IndustryPick: one key of the dated market dataset (code picks beta / multiples / margins);
                           unknown key -> keyword fallback
  2. startup factors    -> StartupFactors (idea .. series-a only): Berkus milestone scores 0-100 and 12 risk ratings
                           -2..+2, each with evidence URLs; URLs not in this valuation's stored evidence are dropped.
                           basis "ai_suggested" (weight x 0.5) until a platform admin confirms them — at the approval
                           gate (the reviewer confirms everything) or in PATCH /v1/admin/valuations/{vid}/assumptions
  3. precedent deals    -> DealClaims (series-a / growth): kept only when the quote is verbatim on a stored page and
                           states the multiple (or the price and the revenue / EBITDA), the date is on the page, the
                           multiple is inside bounds and the target is not the company itself
At most 3 model calls and one `precedents` web search on the shared budget (Series A / growth only; deals come from
pages fetched for this valuation), never a value,
weight, rate or projection. No personal names are sent (valuation.redact). Every failure degrades to "no input".
Behind VALUATION_V5: with the flag off the node is not in the graph and nothing here runs.
"""
from __future__ import annotations

import re
from datetime import UTC, date, datetime

from ..deps import Deps
from ..schemas import (
    DealClaims,
    IndustryPick,
    MarketAnalysis,
    StartupFactors,
    StartupProfile,
    SVIResult,
    Triangulation,
    VerifiedValuationEvidence,
)
from ..tools import market_data, svi
from ..tools.valuation_params import MARKET_DATASET, params
from ..tools.valuation_v5 import triangulate_v5

AGENT = "valuation_methods"
DEAL_TERMS = re.compile(r"acqui|takeover|bought|merger|purchase[ds]? |sold to|EBITDA multiple|times EBITDA|x EBITDA",
                        re.IGNORECASE)
MULTIPLE_WORDS = re.compile(r"\d\s*(?:x|×)(?![a-z])|\btimes\b|multiple", re.IGNORECASE)
EBITDA_WORDS = re.compile(r"EBITDA|earnings", re.IGNORECASE)
REVENUE_WORDS = re.compile(r"revenue|sales|\bARR\b|turnover", re.IGNORECASE)
EARLY = ("idea", "pre-seed", "seed", "series-a")
DEAL_STAGES = ("series-a", "growth")

SYSTEM_INDUSTRY = """Pick the ONE industry from the list that best describes the business's main revenue.
Answer with the key exactly as listed and one sentence why. If nothing fits, answer "general"."""

SYSTEM_FACTORS = """You rate a startup for two standard early-stage valuation checklists. You never give a value.
berkus (score 0-100 each = how far the milestone is achieved, from the evidence only):
  sound_idea (basic value, product risk), prototype (technology risk), quality_team (execution risk),
  strategic_relationships (market risk: partners, distribution, key customers), product_rollout (production /
  sales risk: launched, paying customers).
rfs (rating -2 very high risk .. 0 normal .. +2 very low risk, vs a typical startup at this stage):
  management, stage, legislation, manufacturing, sales_marketing, funding, competition, technology, litigation,
  international, reputation, exit.
For each item give a short rationale and the evidence URLs you relied on (copied exactly from the list). Missing
evidence = a cautious rating (berkus <= 30, rfs <= 0). Leave out items you cannot judge."""

SYSTEM_DEALS = """From the numbered pages, list acquisitions of businesses comparable to the startup below where the
page states the price multiple paid (e.g. "6.5 times EBITDA") or both the price and the target's revenue or EBITDA.
Copy the quote character for character (<= 300 chars) and the deal date exactly as written. Plain numbers in the
stated currency. Never the startup itself. Empty list if none."""


# ------------------------------------------------------------------ evidence helpers
def _evidence(deps: Deps, vid: str) -> list[tuple]:
    from .competitors import comp_subject
    from .site_intake import site_subject

    out, seen = [], set()
    for subject in (site_subject(vid), vid, comp_subject(vid)):
        for ev, text in deps.evidence.for_subject(subject, limit=300):
            if ev.url not in seen:
                seen.add(ev.url)
                out.append((ev, text or ""))
    return out


def _excerpts(text: str, rx: re.Pattern, window: int = 250, limit: int = 2000) -> str:
    spans: list[list[int]] = []
    for m in rx.finditer(text or ""):
        a, b = max(0, m.start() - window), min(len(text), m.end() + window)
        if spans and a <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], b)
        else:
            spans.append([a, b])
    return " … ".join(text[a:b] for a, b in spans)[:limit]


# ------------------------------------------------------------------ 1. industry
def pick_industry(profile: StartupProfile, deps: Deps) -> tuple[str, str, str]:
    """(industry key, basis ai_suggested|keyword, rationale)."""
    snap = market_data.snapshot(MARKET_DATASET)
    keys = snap.industry_keys()
    fallback = snap.industry_for_text(f"{profile.sector} {profile.description}")
    listing = "\n".join(f"- {k}: {snap.industry(k)['label']}" for k in keys)
    try:
        pick = deps.ask(AGENT, deps.settings.svi_tier, SYSTEM_INDUSTRY,
                        f"INDUSTRIES:\n{listing}\n\n<data>\nBUSINESS: {profile.company_name} — sector: "
                        f"{profile.sector}\n{profile.description[:1500]}\n</data>", IndustryPick)
    except Exception as e:  # noqa: BLE001 - optional enrichment
        deps.audit.record(AGENT, "industry_pick_error", error=str(e)[:300])
        return fallback, "keyword", "keyword match on the sector description"
    key = (pick.industry or "").strip()
    if key not in keys:
        return fallback, "keyword", f"model answer {key[:40]!r} not in the list: keyword match used"
    return key, "ai_suggested", pick.rationale[:300]


# ------------------------------------------------------------------ 2. startup factors
def suggest_factors(profile: StartupProfile, market: MarketAnalysis | None, evidence: list[tuple], stage: str,
                    deps: Deps) -> tuple[dict, list[str]]:
    """StartupFactors as a JSON dict with unknown source URLs removed; ([], dropped notes)."""
    from .valuation import redact

    urls = {ev.url for ev, _ in evidence}
    ev_list = "\n".join(f"- {ev.url} — {ev.title[:100]}" for ev, _ in evidence[:40])
    user = (f"STAGE: {stage}\n<data>\nPROFILE: {redact(profile)}\n\nMARKET: "
            f"{market.market_summary[:1500] if market else 'no market analysis'}\n\nEVIDENCE URLS:\n{ev_list}\n</data>")
    try:
        f = deps.ask(AGENT, deps.settings.svi_tier, SYSTEM_FACTORS, user, StartupFactors)
    except Exception as e:  # noqa: BLE001
        deps.audit.record(AGENT, "startup_factors_error", error=str(e)[:300])
        return {}, []
    dropped: list[str] = []
    out = f.model_dump()
    for group in ("berkus", "rfs"):
        for k, item in out[group].items():
            bad = [u for u in item.get("sources") or [] if u not in urls]
            if bad:
                dropped.append(f"{group}.{k}: {len(bad)} source URL(s) not in the evidence removed")
            item["sources"] = [u for u in item.get("sources") or [] if u in urls]
    return out, dropped


# ------------------------------------------------------------------ 3. precedent deals
def extract_deals(profile: StartupProfile, evidence: list[tuple], today: date, deps: Deps) -> tuple[list[dict],
                                                                                                    list[str]]:
    pages = [(ev, t) for ev, t in evidence if DEAL_TERMS.search(f"{ev.snippet} {t}")][:20]
    if not pages:
        return [], []
    listing = "\n\n".join(f"[{i}] {ev.title}\nURL: {ev.url}\n" + _excerpts(f"{ev.snippet} {t}", DEAL_TERMS)
                          for i, (ev, t) in enumerate(pages, 1))
    try:
        claims = deps.ask(AGENT, deps.settings.svi_tier, SYSTEM_DEALS,
                          f"Startup: {profile.company_name} — {profile.sector}; country {profile.country}\n\n"
                          f"<data>\n{listing}\n</data>", DealClaims)
    except Exception as e:  # noqa: BLE001
        deps.audit.record(AGENT, "deal_claims_error", error=str(e)[:300])
        return [], []
    return verify_deals(claims, evidence, profile, today)


def verify_deals(claims: DealClaims, evidence: list[tuple], profile: StartupProfile, today: date) -> tuple[list[dict],
                                                                                                         list[str]]:
    from ..config import fx_to_aud
    from ..tools.triangulate import age_months, parse_as_of
    from .competitors import _norm, quote_in, short_name
    from .research import amount_in_quote

    p = params()
    texts: dict[str, list[str]] = {}
    for ev, t in evidence:
        texts.setdefault(ev.url, []).extend([t or "", ev.snippet or ""])
    name = _norm(short_name(profile.company_name))
    kept, dropped = [], []
    for c in claims.deals[:8]:
        why, m = "", None
        basis_rx = EBITDA_WORDS if c.basis == "ebitda" else REVENUE_WORDS
        if name and name in _norm(c.target):
            why = "the company itself"
        elif c.source_url not in texts:
            why = "source URL not in evidence"
        elif not any(quote_in(c.quote, t) for t in texts[c.source_url]):
            why = "quote not found on the page"
        elif fx_to_aud(c.currency) is None:
            why = f"currency {c.currency!r} not in FX table"
        elif not _norm(c.target) or not any(_norm(c.target) in _norm(t) for t in texts[c.source_url]):
            why = "page does not name the target"
        elif not basis_rx.search(c.quote):
            why = f"quote does not mention {c.basis}"
        elif c.multiple and amount_in_quote(c.multiple, c.quote, tol=0.001) and MULTIPLE_WORDS.search(c.quote):
            m = c.multiple
        else:
            metric = c.ebitda if c.basis == "ebitda" else c.revenue
            if c.ev and metric and amount_in_quote(c.ev, c.quote) and amount_in_quote(metric, c.quote):
                m = c.ev / metric
            else:
                why = "quote does not state the multiple (or the price and the metric)"
        lo, hi = p["ebitda_multiple_bounds"] if c.basis == "ebitda" else p["revenue_multiple_bounds"]
        if not why and not lo <= (m or 0) <= hi:
            why = f"multiple {m:g}x outside bounds"
        as_of = ""
        if not why:
            if len(c.date_text.strip()) >= 4 and any(quote_in(c.date_text, t, min_len=4) for t in texts[c.source_url]):
                as_of = parse_as_of(c.date_text)
            as_of = as_of or parse_as_of(c.quote)
            if not as_of:
                why = "no deal date on the page"
        if why:
            dropped.append(f"deal {c.target[:60]} ({c.source_url}): {why}")
            continue
        if any(_norm(d["target"]) == _norm(c.target) for d in kept):
            continue
        kept.append({"target": c.target[:120], "acquirer": c.acquirer[:120], "multiple": round(m, 3),
                     "basis": c.basis, "as_of": as_of, "age_months": age_months(as_of, today),
                     "source_url": c.source_url, "quote": c.quote[:300]})
    return kept, dropped


# ------------------------------------------------------------------ deterministic v5 triangulation (hook)
def triangulation_v5(result: SVIResult, profile: StartupProfile, market: MarketAnalysis | None, state: dict,
                     reviewer: str | None = None) -> Triangulation:
    """The v5 blend for a scored SVI result. Called from agents/valuation.py (score, apply_team_score,
    apply_overrides) when VALUATION_V5=1. `reviewer` (approval gate): AI-suggested startup ratings count as
    confirmed from now on (state["valuation_inputs"] is updated in place so the caller can persist it)."""
    ve = (VerifiedValuationEvidence.model_validate(state["valuation_evidence"]) if state.get("valuation_evidence")
          else VerifiedValuationEvidence(as_of=datetime.now(UTC).date().isoformat()))
    vi = dict(state.get("valuation_inputs") or {})
    if reviewer and vi.get("startup_factors") and vi.get("factors_basis", "ai_suggested") == "ai_suggested":
        vi["factors_basis"] = "human"
        vi["factors_confirmed_by"] = reviewer
    if reviewer and vi.get("industry_basis") == "ai_suggested":
        vi["industry_basis"] = "human"
    if isinstance(state, dict) and (vi or state.get("valuation_inputs") is not None):
        state["valuation_inputs"] = vi
    dims = {k: (d.model_dump() if hasattr(d, "model_dump") else d) for k, d in result.dimensions.items()}
    an = getattr(result, "analysis", None)
    sd = (an.stage.model_dump() if hasattr(an, "stage") else (an or {}).get("stage")) if an else None
    return triangulate_v5(stage_decision=sd, profile=profile, market=market, ve=ve, dims=dims, svi_index=result.index,
                          self_reported=state.get("self_reported"), v5_inputs=vi, projection=vi.get("projection"),
                          stage_ranges=svi.STAGE_PRE_REVENUE_RANGE,
                          as_of=ve.as_of or datetime.now(UTC).date().isoformat())


def run(state: dict, deps: Deps) -> dict:
    """Graph node: LLM extraction (≤ 3 calls) -> deterministic v5 blend -> svi (headline range + hash) updated."""
    from ..tools import stage as stage_tools

    profile = StartupProfile.model_validate(state["profile"])
    market = MarketAnalysis.model_validate(state["market"]) if state.get("market") else None
    result = SVIResult.model_validate(state["svi"])
    vid = state.get("job_id", "")
    evidence = _evidence(deps, vid) if vid else []
    today = datetime.now(UTC).date()
    decision = stage_tools.classify_stage(stage_tools.evidence_from_result(state, state.get("self_reported") or {}))
    vi = dict(state.get("valuation_inputs") or {})
    deps.tool(AGENT, "value_methods", company=profile.company_name, stage=decision.stage)
    key, basis, why = pick_industry(profile, deps)
    vi.update(industry=key, industry_basis=basis, industry_rationale=why)
    dropped: list[str] = []
    if decision.stage in EARLY:
        factors, d1 = suggest_factors(profile, market, evidence, decision.stage, deps)
        if factors:
            vi.update(startup_factors=factors, factors_basis="ai_suggested")
        dropped += d1
    searches = [dict(x) for x in state.get("searches") or []]
    if decision.stage in DEAL_STAGES:
        if vid and search_precedents(profile, vid, searches, today, deps):
            evidence = _evidence(deps, vid)
        deals, d2 = extract_deals(profile, evidence, today, deps)
        vi["deals"] = deals
        dropped += d2
    vi["dropped"] = dropped
    vi["agent_version"] = 1
    st = {**state, "valuation_inputs": vi}
    tri = triangulation_v5(result, profile, market, st)
    svi.apply_triangulation(result, tri)
    deps.audit.record(AGENT, "valued_v5", stage=decision.stage, valuation_class=tri.valuation_class,
                      confidence=tri.confidence, methods=[m.method for m in tri.methods if m.weight > 0],
                      deals=len(vi.get("deals") or []), dropped=len(dropped))
    return {"svi": result.model_dump(), "valuation_inputs": st["valuation_inputs"], "searches": searches}


def search_precedents(profile: StartupProfile, vid: str, searches: list[dict], today: date, deps: Deps) -> int:
    """One `precedents` search on the shared budget (tools/search.VALUATION_QUERY_PLAN, after the analysts' kinds):
    pages stored as this valuation's evidence so extract_deals can cite them. Returns the number of pages stored."""
    from ..tools.brave import fetch_page
    from ..tools.search import budgeted_search, precedents_query, store_result

    q = precedents_query(profile, today.year)
    results = budgeted_search(deps, AGENT, searches, "precedents", q)
    fetch = deps.fetcher or fetch_page
    n = 0
    for i, r in enumerate((results or [])[: deps.settings.search_fetch_per_query + 2]):
        if store_result(deps, AGENT, r, q, vid, fetch if i < deps.settings.search_fetch_per_query else None):
            n += 1
    return n


def rerun_methods(result: dict, *, reviewer: str | None = None) -> dict | None:
    """Deterministic re-valuation of a STORED result (no LLM, no web): after a projection is confirmed or an
    admin assumption changes. Returns {"svi", "valuation_inputs"} or None when the result cannot be re-scored."""
    from ..schemas import self_reported_metric_fields
    from .valuation import apply_cited_revenue

    if not (result.get("profile") and result.get("svi")):
        return None
    profile = StartupProfile.model_validate(result["profile"])
    market = MarketAnalysis.model_validate(result["market"]) if result.get("market") else None
    apply_cited_revenue(profile, market, self_reported_metric_fields(result.get("self_reported")))
    res = SVIResult.model_validate(result["svi"])
    st = dict(result)
    tri = triangulation_v5(res, profile, market, st, reviewer=reviewer)
    svi.apply_triangulation(res, tri)
    return {"svi": res.model_dump(), "valuation_inputs": st.get("valuation_inputs") or {}}
