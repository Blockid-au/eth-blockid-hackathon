"""Startup Value Index (SVI) — deterministic scoring.

The LLM never produces the index or the valuation. It may only *suggest* qualitative
dimension scores (flagged `ai_suggested`, requiring human confirmation); revenue and growth
dimensions are computed here from reported metrics, and the valuation is plain arithmetic
over cited market multiples. Same inputs -> same output, every time (audit requirement).

Valuation range, first rule that applies (then x SVI factor):
1. revenue > 0 and verified cited revenue + last valuation of the company -> implied multiple (0.7x / 1x / 1.4x);
2. revenue > 0 and a multiple cited in the market evidence -> that multiple;
3. revenue > 0 otherwise -> config.DEFAULT_REVENUE_MULTIPLES (uncalibrated default, flagged for review);
4. no revenue -> stage benchmark range.

Valuation v3: agents/valuation.py replaces this range with the triangulation blend (tools/triangulate.py) via
apply_triangulation(); the rules above remain the v2 formula (public /verify of older reports).

Weights follow the SVI framework (7 dimensions). Stage benchmarks and multipliers are
PLACEHOLDERS to be calibrated with the SVI dissertation data before production use.
"""
from __future__ import annotations

import hashlib
import json
import math

from ..config import IMPLIED_MULTIPLE_BOUNDS, default_multiples
from ..schemas import DimensionScore, MarketAnalysis, QualitativeScores, StartupProfile, SVIResult

# v4 (2026-09-27, docs/PLAN-HR.md): the founding team is the highest-weighted dimension. When a founding-team report
# (agents/people.py) is linked, founder_quality = its team score (basis "team_report"; an admin override still wins).
WEIGHTS: dict[str, float] = {
    "founder_quality": 0.30,
    "product_strength": 0.15,
    "market_attractiveness": 0.15,
    "revenue_performance": 0.15,
    "growth_capability": 0.10,
    "investment_readiness": 0.10,
    "trust_verification": 0.05,
}
# v1-v3 weights: kept so /verify reproduces every report valued before v4 (SVIResult.weights records the set used)
WEIGHTS_V3: dict[str, float] = {
    "founder_quality": 0.20,
    "product_strength": 0.15,
    "market_attractiveness": 0.20,
    "revenue_performance": 0.20,
    "growth_capability": 0.10,
    "investment_readiness": 0.10,
    "trust_verification": 0.05,
}
WEIGHT_SETS: dict[str, dict[str, float]] = {"v4": WEIGHTS, "v3": WEIGHTS_V3}  # newest first
for _w in WEIGHT_SETS.values():
    assert abs(sum(_w.values()) - 1.0) < 1e-9

# Placeholder calibration (AUD). Replace with values derived from the SVI research dataset.
STAGE_REVENUE_BENCHMARK = {"idea": 0, "pre-seed": 50_000, "seed": 300_000, "series-a": 2_000_000, "growth": 10_000_000}
STAGE_PRE_REVENUE_RANGE = {  # used only when revenue or market multiples are missing
    "idea": (250_000, 750_000, 1_500_000),
    "pre-seed": (750_000, 2_000_000, 4_000_000),
    "seed": (2_000_000, 5_000_000, 10_000_000),
    "series-a": (8_000_000, 20_000_000, 40_000_000),
    "growth": (30_000_000, 80_000_000, 200_000_000),
}


def _clamp(x: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, x))


SELF_REPORTED_NOTE = "self-reported by the founder, not independently verified"


def _basis(fields: tuple[str, ...], self_reported) -> tuple[str, list[str]]:
    used = [f for f in fields if f in (self_reported or ())]
    return ("self_reported" if used else "computed"), used


def _label(rationale: str, used: list[str]) -> str:
    return f"{rationale} ({SELF_REPORTED_NOTE}: {', '.join(used)})" if used else rationale


def _cited_note(cited: dict) -> str:
    return f" (revenue from a cited third-party source, not verified: {cited.get('source_url', '')} — " \
           f"\"{cited.get('quote', '')}\")"


def revenue_performance(p: StartupProfile, self_reported=None, cited: dict | None = None) -> DimensionScore:
    """`self_reported`: names of the StartupProfile.metrics fields a founder supplied (see SelfReportedMetrics).
    `cited`: {source_url, quote} when revenue_ttm_aud came from a third-party page found by search."""
    m = p.metrics
    bench = STAGE_REVENUE_BENCHMARK[p.stage]
    if m.revenue_ttm_aud <= 0:
        scale = 0.0
    elif bench == 0:
        scale = 60.0
    else:
        # 50 points at the stage benchmark, +/- 25 per 10x (log scale)
        scale = _clamp(50 + 25 * math.log10(m.revenue_ttm_aud / bench))
    margin = _clamp(m.gross_margin_pct)
    score = round(0.7 * scale + 0.3 * margin, 1)
    basis, used = _basis(("revenue_ttm_aud", "gross_margin_pct"), self_reported)
    rationale = _label(f"revenue {m.revenue_ttm_aud:,.0f} AUD vs stage benchmark {bench:,.0f}; "
                       f"gross margin {margin:.0f}%", used)
    sources: list[str] = []
    if cited and "revenue_ttm_aud" not in used:
        basis, rationale = "cited_source", rationale + _cited_note(cited)
        sources = [cited["source_url"]] if cited.get("source_url") else []
    return DimensionScore(score=score, basis=basis, rationale=rationale, sources=sources)


def growth_capability(p: StartupProfile, self_reported=None) -> DimensionScore:
    m = p.metrics
    growth = _clamp(m.revenue_growth_yoy_pct / 2)  # 200% YoY -> 100 points
    runway = _clamp(m.runway_months / 24 * 100)  # 24 months -> 100 points
    score = round(0.6 * growth + 0.4 * runway, 1)
    basis, used = _basis(("revenue_growth_yoy_pct", "runway_months"), self_reported)
    return DimensionScore(
        score=score,
        basis=basis,
        rationale=_label(f"YoY growth {m.revenue_growth_yoy_pct:.0f}%, runway {m.runway_months:.0f} months", used),
    )


def band(index: float) -> str:
    if index >= 80:
        return "A - investment grade"
    if index >= 65:
        return "B - strong"
    if index >= 50:
        return "C - developing"
    if index >= 35:
        return "D - early / high risk"
    return "E - not investable yet"


def score(profile: StartupProfile, qualitative: QualitativeScores, market: MarketAnalysis | None,
          self_reported=None, cited: dict | None = None) -> SVIResult:
    """`self_reported`: metric field names supplied by the founder (they mark the computed dimensions).
    `cited`: {source_url, quote} when the revenue is taken from a cited third-party source (see agents/valuation)."""
    dims: dict[str, DimensionScore] = {
        **{k: getattr(qualitative, k) for k in QualitativeScores.model_fields},
        "revenue_performance": revenue_performance(profile, self_reported, cited),
        "growth_capability": growth_capability(profile, self_reported),
    }
    index = round(sum(WEIGHTS[k] * dims[k].score for k in WEIGHTS), 2)

    review = [f"{k}: AI-suggested score must be confirmed" for k, d in dims.items() if d.basis == "ai_suggested"]
    review += [f"data room missing: {x}" for x in profile.missing_items]
    if cited:
        review.append(f"revenue taken from a third-party source ({cited.get('source_url', '')}) — confirm with the "
                      "company before relying on it")

    rev = profile.metrics.revenue_ttm_aud
    factor = 0.5 + index / 100  # index 50 -> 1.0x, 80 -> 1.3x, 30 -> 0.8x
    rev_label = ("self-reported " if "revenue_ttm_aud" in (self_reported or ()) else "cited-source " if cited else "")
    low, mid, high, method, extra = valuation_range(rev, factor, market, profile.stage, profile.sector, rev_label)
    review += extra

    result = SVIResult(
        index=index,
        band=band(index),
        dimensions=dims,
        weights=dict(WEIGHTS),
        valuation_low_aud=round(low, -3),
        valuation_mid_aud=round(mid, -3),
        valuation_high_aud=round(high, -3),
        method=method,
        needs_human_review=review,
    )
    result.report_sha256 = report_hash(result)
    return result


def implied_multiple(market: MarketAnalysis | None) -> tuple[float, str] | None:
    """(last valuation / revenue, source URL) when the verified company financials state both (same page, same
    currency, both converted at the same fixed rate) and the ratio is within IMPLIED_MULTIPLE_BOUNDS."""
    cf = market.company_financials if market else None
    if not cf or not cf.usable_for_valuation or not cf.revenue_ttm_aud or not cf.last_valuation_aud:
        return None
    m = cf.last_valuation_aud / cf.revenue_ttm_aud
    lo, hi = IMPLIED_MULTIPLE_BOUNDS
    return (round(m, 2), cf.source_url) if lo <= m <= hi else None


def report_hash(result: SVIResult) -> str:
    exclude = {"report_sha256", "narrative"} | ({"triangulation"} if result.triangulation is None else set())
    payload = result.model_dump(exclude=exclude)  # pre-v3 reports keep their original hash
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

FORMULA_VERSION = "v4"  # v4: v3 + new WEIGHTS (founder_quality 0.30); v3: triangulation (tools/triangulate.py)
TRIANGULATION_VERSION = "v3"  # valuation-range rules (unchanged by v4); v2 rules below remain the fallback
LEGACY_FORMULA_VERSION = "v2"  # v2: implied multiple > cited multiple (0.7x-1.4x spread if single) > default > stage


def apply_triangulation(result: SVIResult, tri) -> SVIResult:
    """v3: the headline range comes from the triangulation blend (tools/triangulate.py); the SVI index and
    dimensions stay as the quality indicator. Recomputes the report hash."""
    from .triangulate import headline_method

    result.triangulation = tri
    result.valuation_low_aud = round(tri.low_aud, -3)
    result.valuation_mid_aud = round(tri.value_aud, -3)
    result.valuation_high_aud = round(tri.high_aud, -3)
    result.method = headline_method(tri, result.method)
    result.needs_human_review = list(dict.fromkeys(
        [*result.needs_human_review, *(f"valuation confidence {tri.confidence}: {r}" for r in tri.confidence_reasons
                                      if tri.confidence != "high")]))
    result.report_sha256 = report_hash(result)
    return result


def valuation_range(rev: float, factor: float, market: MarketAnalysis | None, stage: str, sector: str,
                    rev_label: str = "") -> tuple[float, float, float, str, list[str]]:
    """Current (v2) valuation range rules, shared by score() and the /verify recompute."""
    implied = implied_multiple(market)
    review: list[str] = []
    if rev > 0 and implied:
        # 1. the company's own last round: cited last valuation / cited revenue (same verified source)
        med, src = implied
        lo_m, hi_m = med * 0.7, med * 1.4
        low, mid, high = rev * lo_m * factor, rev * med * factor, rev * hi_m * factor
        method = (f"{rev_label}revenue x implied multiple from cited last round: {med:.1f}x "
                  f"(range 0.7x-1.4x: {lo_m:.1f}x / {med:.1f}x / {hi_m:.1f}x; {src}) x SVI factor {factor:.2f}")
        review.append("implied multiple from a cited last-round valuation — confirm the round and revenue basis")
    elif rev > 0 and market and market.revenue_multiple_median:
        med = market.revenue_multiple_median
        lo_m = market.revenue_multiple_low or med * 0.6
        hi_m = market.revenue_multiple_high or med * 1.5
        # Sources often cite a single multiple, so low = median = high collapses the range to one number.
        # A valuation is a range: fall back to a fixed spread and say so in the method.
        spread = lo_m >= med * 0.95 or hi_m <= med * 1.05
        if spread:
            lo_m, hi_m = min(lo_m, med * 0.7), max(hi_m, med * 1.4)
        low, mid, high = rev * lo_m * factor, rev * med * factor, rev * hi_m * factor
        method = (
            rev_label
            + f"revenue multiple ({lo_m:.1f}x / {med:.1f}x / {hi_m:.1f}x, cited market data"
            + ("; single cited multiple, range set to 0.7x-1.4x of it" if spread else "")
            + f") x SVI factor {factor:.2f}"
        )
        if market.confidence == "low":
            review.append("market multiples have LOW confidence — verify sources before use")
    elif rev > 0:
        # 3. revenue but no cited or implied multiple: conservative default table (config, uncalibrated)
        key, (lo_m, med, hi_m) = default_multiples(sector or "")
        low, mid, high = rev * lo_m * factor, rev * med * factor, rev * hi_m * factor
        method = (f"{rev_label}revenue x default multiple ({lo_m:.1f}x / {med:.1f}x / {hi_m:.1f}x, {key}; "
                  f"uncalibrated default, see ROADMAP calibration) x SVI factor {factor:.2f}")
        review.append("multiple is a default, not cited")
    else:
        # 4. no revenue: stage benchmark range
        b_low, b_mid, b_high = STAGE_PRE_REVENUE_RANGE[stage if stage in STAGE_PRE_REVENUE_RANGE else "seed"]
        low, mid, high = b_low * factor, b_mid * factor, b_high * factor
        method = f"stage benchmark range ({stage}, placeholder calibration) x SVI factor {factor:.2f}"
        review.append("valuation uses stage benchmark (no revenue)")

    return low, mid, high, method, review

