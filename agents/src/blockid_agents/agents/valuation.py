"""Agent 3 — Valuation (SVI).

LLM suggests the 5 qualitative dimension scores (flagged ai_suggested) from a REDACTED profile
(no personal names) plus cited market evidence; code computes the revenue & growth dimensions,
the index and the valuation range. A human confirms or overrides the AI-suggested scores at the
approval gate, after which the index is recomputed with basis="human".
"""
from __future__ import annotations

from ..deps import Deps
from ..schemas import (
    DimensionScore,
    MarketAnalysis,
    Narrative,
    QualitativeScores,
    StartupProfile,
    SVIResult,
    self_reported_metric_fields,
)
from ..tools import svi

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


def score(state: dict, deps: Deps) -> dict:
    """AI-suggested qualitative scores + deterministic SVI maths (no narrative yet)."""
    profile = StartupProfile.model_validate(state["profile"])
    market = MarketAnalysis.model_validate(state["market"]) if state.get("market") else None
    tier = deps.settings.svi_tier  # SVI_TIER=cloud -> Claude CLI / DeepInfra; input is redacted either way

    sr = self_reported_metric_fields(state.get("self_reported"))
    note = f"\n\nSELF-REPORTED (founder-provided, NOT verified) metrics: {', '.join(sr)}" if sr else ""
    user = (f"<data>\nPROFILE: {redact(profile)}\n\nMARKET: {market.model_dump() if market else 'no market data'}"
            f"{note}\n</data>")
    q = deps.ask(AGENT, tier, SYSTEM_SCORES, user, QualitativeScores)
    for name in QualitativeScores.model_fields:  # never trust the model to self-label as human/computed
        getattr(q, name).basis = "ai_suggested"

    deps.tool(AGENT, "svi_score", company=profile.company_name)
    result = svi.score(profile, q, market, sr)
    return {"svi": result.model_dump(), "qualitative": q.model_dump(), "status": "scored"}


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
    result: SVIResult = svi.score(profile, q, market, self_reported_metric_fields(state.get("self_reported")))
    result.narrative = state["svi"].get("narrative", "")
    deps.audit.record("human", "valuation_approved", reviewer=reviewer, overrides=overrides, sha256=result.report_sha256)
    return {"svi": result.model_dump(), "qualitative": q.model_dump()}
