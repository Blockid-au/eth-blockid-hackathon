"""Agent 3 — Valuation (SVI).

LLM suggests the 5 qualitative dimension scores (flagged ai_suggested) from a REDACTED profile
(no personal names) plus cited market evidence; code computes the revenue & growth dimensions,
the index and the valuation range. A human confirms or overrides the AI-suggested scores at the
approval gate, after which the index is recomputed with basis="human".

Revenue precedence (profile.metrics_sources records which one was used):
self_reported (founder-typed) > website (stated on the company's own site) > cited_source (the company's own
revenue/ARR stated verbatim on a third-party page found by the company-financials search, see agents/research).
A cited figure is used only when the profile has no revenue and none was self-reported, and always carries a
warning.

Valuation v3: the headline range (valuation_low/mid/high_aud) is the triangulation blend (tools/triangulate.py) of
the company's verified market anchors (state["valuation_evidence"], agents/market_evidence.py), revenue x cited
multiple and the stage benchmark x SVI factor. The SVI index / band remain the quality indicator.
"""
from __future__ import annotations

from datetime import UTC, datetime

from ..config import default_multiples
from ..deps import Deps
from ..schemas import (
    CompanyFinancials,
    DimensionScore,
    MarketAnalysis,
    Narrative,
    QualitativeScores,
    StartupProfile,
    SVIResult,
    Triangulation,
    VerifiedValuationEvidence,
    self_reported_metric_fields,
)
from ..tools import svi
from ..tools.triangulate import triangulate

AGENT = "valuation"

SYSTEM_SCORES = """You are a startup analyst applying the Startup Value Index (SVI).
Score each dimension 0-100 with a short rationale and the evidence URLs you relied on:
- founder_quality: experience, domain expertise, prior exits, team completeness
- product_strength: differentiation, traction evidence, IP, technical risk
- market_attractiveness: size, growth, competition intensity (use cited market analysis)
- investment_readiness: data-room completeness, governance, cap-table clarity
- trust_verification: verifiable claims, audited numbers, KYC status, on-chain history
Be conservative: missing evidence lowers the score. Set basis to "ai_suggested" for every dimension."""

SYSTEM_NARRATIVE = """Write a concise, neutral valuation narrative for an investor memo from the SVI result.
State clearly that it is an indicative index, not financial advice or a formal valuation."""


def redact(p: StartupProfile) -> dict:
    d = p.model_dump()
    for i, f in enumerate(d["founders"], 1):
        f["name"] = f"Founder {i}"
    return d


def cited_warning(cf: CompanyFinancials) -> str:
    what = f"{cf.revenue_type or 'revenue'}{f' {cf.revenue_year}' if cf.revenue_year else ''}"
    return (f"Revenue from a third-party source found by web search (not the founder or the company's crawled "
            f"pages), not independently verified: A${cf.revenue_ttm_aud:,.0f} ({what}, "
            f"{cf.currency} at {cf.fx_rate_to_aud} AUD, FX {cf.fx_as_of}) cited from {cf.source_url}")


def apply_cited_revenue(profile: StartupProfile, market: MarketAnalysis | None,
                        self_reported: list[str]) -> tuple[dict | None, list[str]]:
    """Fill revenue_ttm_aud from verified company financials when neither the founder nor the website gave one.
    Mutates `profile` (metrics + metrics_sources). Returns ({source_url, quote} or None, warnings)."""
    cf = market.company_financials if market else None
    src = profile.metrics_sources
    if "revenue_ttm_aud" in self_reported:
        src["revenue_ttm_aud"] = "self_reported"
        return None, []
    if profile.metrics.revenue_ttm_aud > 0 and src.get("revenue_ttm_aud") != "cited_source":
        src.setdefault("revenue_ttm_aud", "website")
        return None, []
    if cf is None or not cf.usable_for_valuation or not cf.revenue_ttm_aud:
        if src.get("revenue_ttm_aud") == "cited_source":  # stale label without its source: undo
            profile.metrics.revenue_ttm_aud = 0
            src.pop("revenue_ttm_aud")
        warn = []
        if cf is not None and cf.revenue_ttm_aud and cf.revenue_type == "GMV":
            warn.append(f"Transaction volume (GMV) found at {cf.source_url} is not revenue and was not used")
        return None, warn
    profile.metrics.revenue_ttm_aud = cf.revenue_ttm_aud
    src["revenue_ttm_aud"] = "cited_source"
    return {"source_url": cf.source_url, "quote": cf.quote}, [cited_warning(cf)]


def triangulation_for(profile: StartupProfile, market: MarketAnalysis | None, state: dict,
                      index: float) -> Triangulation:
    """Deterministic v3 blend from verified inputs only (see tools/triangulate.py)."""
    ve = (VerifiedValuationEvidence.model_validate(state["valuation_evidence"]) if state.get("valuation_evidence")
          else VerifiedValuationEvidence(as_of=datetime.now(UTC).date().isoformat()))
    rev = profile.metrics.revenue_ttm_aud
    rsrc = profile.metrics_sources.get("revenue_ttm_aud", "website")
    cf = market.company_financials if market else None
    ref = cf.source_url if (rsrc == "cited_source" and cf) else ""
    mm = ((market.revenue_multiple_low, market.revenue_multiple_median, market.revenue_multiple_high)
          if market and market.revenue_multiple_median else None)
    stage = profile.stage if profile.stage in svi.STAGE_PRE_REVENUE_RANGE else "seed"
    tri = triangulate(anchors=ve.anchors, listed=ve.listing is not None, revenue_aud=rev, revenue_source=rsrc,
                      revenue_ref=ref, comps=ve.comps, sectors=ve.sector_multiples, market_multiples=mm,
                      default=default_multiples(profile.sector), stage=stage,
                      stage_benchmark=svi.STAGE_PRE_REVENUE_RANGE[stage], svi_factor=0.5 + index / 100,
                      as_of=ve.as_of)
    if ve.listing:
        tri.listing = f"{ve.listing.exchange}: {ve.listing.ticker}"
    return tri


def score(state: dict, deps: Deps) -> dict:
    """AI-suggested qualitative scores + deterministic SVI maths (no narrative yet)."""
    profile = StartupProfile.model_validate(state["profile"])
    market = MarketAnalysis.model_validate(state["market"]) if state.get("market") else None
    tier = deps.settings.svi_tier  # SVI_TIER=cloud -> Claude CLI / DeepInfra; input is redacted either way

    sr = self_reported_metric_fields(state.get("self_reported"))
    cited, warns = apply_cited_revenue(profile, market, sr)
    note = f"\n\nSELF-REPORTED (founder-provided, NOT verified) metrics: {', '.join(sr)}" if sr else ""
    if cited:
        note += f"\n\nrevenue_ttm_aud comes from a CITED THIRD-PARTY source ({cited['source_url']}), not the company"
    user = (f"<data>\nPROFILE: {redact(profile)}\n\nMARKET: {market.model_dump() if market else 'no market data'}"
            f"{note}\n</data>")
    q = deps.ask(AGENT, tier, SYSTEM_SCORES, user, QualitativeScores)
    for name in QualitativeScores.model_fields:  # never trust the model to self-label as human/computed
        getattr(q, name).basis = "ai_suggested"

    deps.tool(AGENT, "svi_score", company=profile.company_name)
    result = svi.score(profile, q, market, sr, cited)
    svi.apply_triangulation(result, triangulation_for(profile, market, state, result.index))
    deps.audit.record(AGENT, "triangulated", confidence=result.triangulation.confidence,
              methods=[m.method for m in result.triangulation.methods if m.weight > 0])
    out = {"svi": result.model_dump(), "qualitative": q.model_dump(), "status": "scored",
           "profile": profile.model_dump()}
    if warns:
        out["warnings"] = list(dict.fromkeys([*(state.get("warnings") or []), *warns]))
    return out


def narrate(state: dict, deps: Deps) -> dict:
    result = SVIResult.model_validate(state["svi"])
    narr = deps.ask(AGENT, deps.settings.svi_tier, SYSTEM_NARRATIVE, f"<data>\n{result.model_dump_json()}\n</data>",
                    Narrative)
    result.narrative = narr.summary
    deps.tool(AGENT, "hash_report", sha256=result.report_sha256)
    return {"svi": result.model_dump(), "status": "valued"}


def run(state: dict, deps: Deps) -> dict:
    out = score(state, deps)
    return {**out, **narrate({**state, **out}, deps)}


def apply_overrides(state: dict, overrides: dict[str, float], reviewer: str, deps: Deps) -> dict:
    """Called after the human gate. Confirmed scores become basis='human'; the index is recomputed."""
    profile = StartupProfile.model_validate(state["profile"])
    market = MarketAnalysis.model_validate(state["market"]) if state.get("market") else None
    q = QualitativeScores.model_validate(state["qualitative"])
    for name in QualitativeScores.model_fields:
        d: DimensionScore = getattr(q, name)
        if name in overrides:
            d.score = float(overrides[name])
            d.rationale = f"{d.rationale} [set by {reviewer}]"
        else:
            d.rationale = f"{d.rationale} [confirmed by {reviewer}]"
        d.basis = "human"
    sr = self_reported_metric_fields(state.get("self_reported"))
    cited, _ = apply_cited_revenue(profile, market, sr)
    result: SVIResult = svi.score(profile, q, market, sr, cited)
    svi.apply_triangulation(result, triangulation_for(profile, market, state, result.index))
    result.narrative = state["svi"].get("narrative", "")
    deps.audit.record("human", "valuation_approved", reviewer=reviewer, overrides=overrides, sha256=result.report_sha256)
    return {"svi": result.model_dump(), "qualitative": q.model_dump()}
