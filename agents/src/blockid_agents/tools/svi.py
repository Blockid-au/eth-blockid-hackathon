"""Startup Value Index (SVI) — deterministic scoring.

The LLM never produces the index or the valuation. It may only *suggest* qualitative
dimension scores (flagged `ai_suggested`, requiring human confirmation); revenue and growth
dimensions are computed here from reported metrics, and the valuation is plain arithmetic
over cited market multiples. Same inputs -> same output, every time (audit requirement).

Weights follow the SVI framework (7 dimensions). Stage benchmarks and multipliers are
PLACEHOLDERS to be calibrated with the SVI dissertation data before production use.
"""
from __future__ import annotations

import hashlib
import json
import math

from ..schemas import DimensionScore, MarketAnalysis, QualitativeScores, StartupProfile, SVIResult

WEIGHTS: dict[str, float] = {
    "founder_quality": 0.20,
    "product_strength": 0.15,
    "market_attractiveness": 0.20,
    "revenue_performance": 0.20,
    "growth_capability": 0.10,
    "investment_readiness": 0.10,
    "trust_verification": 0.05,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9

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


def revenue_performance(p: StartupProfile, self_reported=None) -> DimensionScore:
    """`self_reported`: names of the StartupProfile.metrics fields a founder supplied (see SelfReportedMetrics)."""
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
    return DimensionScore(
        score=score,
        basis=basis,
        rationale=_label(f"revenue {m.revenue_ttm_aud:,.0f} AUD vs stage benchmark {bench:,.0f}; "
                         f"gross margin {margin:.0f}%", used),
    )


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
          self_reported=None) -> SVIResult:
    """`self_reported`: metric field names supplied by the founder (they mark the computed dimensions)."""
    dims: dict[str, DimensionScore] = {
        **{k: getattr(qualitative, k) for k in QualitativeScores.model_fields},
        "revenue_performance": revenue_performance(profile, self_reported),
        "growth_capability": growth_capability(profile, self_reported),
    }
    index = round(sum(WEIGHTS[k] * dims[k].score for k in WEIGHTS), 2)

    review = [f"{k}: AI-suggested score must be confirmed" for k, d in dims.items() if d.basis == "ai_suggested"]
    review += [f"data room missing: {x}" for x in profile.missing_items]

    rev = profile.metrics.revenue_ttm_aud
    factor = 0.5 + index / 100  # index 50 -> 1.0x, 80 -> 1.3x, 30 -> 0.8x
    if rev > 0 and market and market.revenue_multiple_median:
        lo_m = market.revenue_multiple_low or market.revenue_multiple_median * 0.6
        hi_m = market.revenue_multiple_high or market.revenue_multiple_median * 1.5
        low, mid, high = rev * lo_m * factor, rev * market.revenue_multiple_median * factor, rev * hi_m * factor
        method = (
            ("self-reported " if "revenue_ttm_aud" in (self_reported or ()) else "")
            + f"revenue multiple ({lo_m:.1f}x / {market.revenue_multiple_median:.1f}x / {hi_m:.1f}x, cited market data) "
            f"x SVI factor {factor:.2f}"
        )
        if market.confidence == "low":
            review.append("market multiples have LOW confidence — verify sources before use")
    else:
        b_low, b_mid, b_high = STAGE_PRE_REVENUE_RANGE[profile.stage]
        low, mid, high = b_low * factor, b_mid * factor, b_high * factor
        method = f"stage benchmark range ({profile.stage}, placeholder calibration) x SVI factor {factor:.2f}"
        review.append("valuation uses stage benchmark (no revenue or no cited multiple)")

    result = SVIResult(
        index=index,
        band=band(index),
        dimensions=dims,
        weights=WEIGHTS,
        valuation_low_aud=round(low, -3),
        valuation_mid_aud=round(mid, -3),
        valuation_high_aud=round(high, -3),
        method=method,
        needs_human_review=review,
    )
    result.report_sha256 = report_hash(result)
    return result


def report_hash(result: SVIResult) -> str:
    payload = result.model_dump(exclude={"report_sha256", "narrative"})
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
