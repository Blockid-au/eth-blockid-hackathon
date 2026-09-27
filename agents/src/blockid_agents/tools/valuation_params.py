"""Valuation v5 parameters — frozen and versioned (docs/PLAN-VALUATION-V5.md §3, §4, §6.4, §7; DECISIONS-V5.md).

Rules only: every NUMBER a method used (rates, multiples, bases, projections) is copied into that method's `inputs`,
so /verify recomputes from the stored report; these params supply the rules that turn inputs into weights and
ranges (weight matrix, evidence factors, caps, range widths). Changing anything here = a new key ("v5.1"), never an
edit of "v5": every report stores `params_version` and /verify reads `PARAMS[that version]`.

Flags (environment, read at call time):
    VALUATION_V5=1               use the v5 engine for new valuations (default off: exactly the previous behaviour)
    VALUATION_V5_REQUIRE_FINAL=1 company creation needs a finalised value (default off during rollout)
"""
from __future__ import annotations

import os
from types import MappingProxyType
from typing import Any

from .stage import SELF_REPORTED_FACTOR

PARAMS_VERSION = "v5.1"
MARKET_DATASET = "2026-09-27"  # Damodaran Jan-2026 industry rows (2026-09-26 = placeholder rows, kept unchanged)
PROJECTION_LABEL = "Based on management projections (unaudited, not verified by BlockID)."
INDICATIVE_LABEL = "Indicative value, not a formal valuation or financial advice."

CLASSES = ("idea", "pre_seed", "seed", "series_a", "growth", "profitable_sme", "listed")
STARTUP_METHODS = ("scorecard", "berkus", "rfs", "stage_scorecard")
PROJECTION_METHODS = ("dcf", "vc_method", "first_chicago")
FUNDAMENTAL_METHODS = ("revenue_multiple", "ebitda_multiple", "precedents", "dcf", "first_chicago", "vc_method")
BERKUS_KEYS = ("sound_idea", "prototype", "quality_team", "strategic_relationships", "product_rollout")
RFS_KEYS = ("management", "stage", "legislation", "manufacturing", "sales_marketing", "funding", "competition",
            "technology", "litigation", "international", "reputation", "exit")


def v5_enabled() -> bool:
    """VALUATION_V5 (default off). Same switch as tools/stage.v5_enabled."""
    return os.environ.get("VALUATION_V5", "0").strip().lower() in ("1", "true", "yes", "on")


def require_final() -> bool:
    return os.environ.get("VALUATION_V5_REQUIRE_FINAL", "0").strip().lower() in ("1", "true", "yes", "on")


def _freeze(v: Any) -> Any:
    if isinstance(v, dict):
        return MappingProxyType({k: _freeze(x) for k, x in v.items()})
    if isinstance(v, list):
        return tuple(_freeze(x) for x in v)
    return v


def thaw(v: Any) -> Any:
    """JSON-friendly copy (formula page)."""
    if isinstance(v, MappingProxyType | dict):
        return {k: thaw(x) for k, x in v.items()}
    if isinstance(v, tuple | list):
        return [thaw(x) for x in v]
    return v


_V5: dict[str, Any] = {
    # ---------------------------------------------------------------- §3.2 base weight matrix (0 = not run)
    "base_weights": {
        #                   idea  pre_seed seed  series_a growth  sme   listed
        "scorecard":       {"idea": 1.0, "pre_seed": 1.0, "seed": 0.6, "series_a": 0.2},
        "berkus":          {"idea": 0.8, "pre_seed": 0.8, "seed": 0.3},
        "rfs":             {"idea": 0.8, "pre_seed": 0.8, "seed": 0.5, "series_a": 0.2},
        "vc_method":       {"pre_seed": 0.4, "seed": 0.8, "series_a": 0.8, "growth": 0.4},
        "revenue_multiple": {"seed": 0.4, "series_a": 0.8, "growth": 1.0, "profitable_sme": 0.4, "listed": 0.3},
        "ebitda_multiple": {"growth": 0.3, "profitable_sme": 1.0, "listed": 0.3},
        "precedents":      {"series_a": 0.3, "growth": 0.6, "profitable_sme": 0.8},
        "dcf":             {"growth": 0.6, "profitable_sme": 1.0, "listed": 0.3},
        "first_chicago":   {"seed": 0.2, "series_a": 0.4},
        "stage_scorecard": {"pre_seed": 0.1, "seed": 0.1, "series_a": 0.1, "growth": 0.1},
    },
    # v3 kind x recency weight x this scale: the v5 matrix puts the revenue method at 1.0 where v3 had 0.6, so the
    # own-price anchor is scaled by 1 / 0.6 to keep v3's anchor : revenue balance (IPEV: a fresh priced round stays the
    # leading calibration point; plan §2.1)
    "anchor_weight_scale": 1.6667,
    "berkus_revenue_limit_seed_aud": 250_000.0,   # seed: Berkus only below this revenue
    "stage_alone_weight": 1.0,                    # v3 rule: the stage benchmark alone carries the value
    "stage_outlier_ratio": 5.0,                   # v3 rule for stage_scorecard
    # ---------------------------------------------------------------- §3.3 evidence-quality factors
    "evidence_factors": {
        # self-reported: owner decision 3 (keeps 60 % of its effect) = tools/stage.SELF_REPORTED_FACTOR
        "audited": 1.0, "management_actuals": 0.9, "verified_cited": 0.9, "self_reported": SELF_REPORTED_FACTOR,
        "website": 0.9,
        "cited_source": 0.9, "projection_ok": 0.7, "projection_warn": 0.4,
        "comps_3plus": 1.0, "comps_1_2": 0.8, "deals_3plus": 1.0, "deals_1_2": 0.8, "sector_cited": 0.7,
        "market_analysis": 0.5, "industry_table": 0.6, "industry_table_uncalibrated": 0.5, "default": 0.25,
        "ai_suggested": 0.5, "human": 1.0, "derived": 0.8, "tv_share_high": 0.8,
    },
    "outlier_ratio": 3.0,          # IVS 105: > 3x from the weighted median of the other methods -> weight 0
    "anchor_exempt_age_months": 24,  # a verified own price this fresh is never excluded as an outlier
    "range_min_half_width": {"high": 0.10, "medium": 0.20, "low": 0.35},  # unchanged v3 behaviour
    "startup_range_half_width": 0.25,
    "max_weight_override_ratio": 2.0,  # admin weight override <= 2x the rule weight
    # ---------------------------------------------------------------- DCF (§2.3 decisions, Anthropic dcf-model checks)
    "terminal_g_default": 0.025,
    "terminal_g_cap": 0.03,        # g <= min(3 %, rf)
    "capm_rate_band": [0.05, 0.20],  # outside -> warning (CAPM WACC only)
    "vc_rate_max": 0.70,
    "tv_share_warn": 0.75,
    "sensitivity_d_rate": 0.01,    # grid steps: rate -2..+2 pp, g -1..+1 pp (0.5 pp), exit multiple -2..+2x (1x)
    "sensitivity_d_g": 0.005,
    "sensitivity_d_exit": 1.0,
    "startup_discount_rates": {"idea": 0.60, "pre_seed": 0.60, "seed": 0.50, "series_a": 0.40, "growth": 0.30},
    "nwc_default_pct_of_delta_revenue": 0.10,
    "first_chicago": {"scenarios": [["worst", 0.25, 0.5], ["base", 0.5, 1.0], ["best", 0.25, 1.25]]},
    # ---------------------------------------------------------------- VC method (§2.1)
    "vc_target_multiples": {"pre_seed": [30.0, 40.0, 50.0], "seed": [20.0, 25.0, 30.0], "series_a": [10.0, 12.5, 15.0],
                            "growth": [3.0, 4.0, 5.0], "idea": [30.0, 40.0, 50.0]},  # [low, mid, high] money multiple
    # ---------------------------------------------------------------- startup methods (§2.1, §2.5)
    "scorecard_weights": {"team": 0.30, "opportunity": 0.25, "product": 0.15, "competition": 0.10,
                          "marketing": 0.10, "need_investment": 0.05, "other": 0.05},
    "berkus_cap_per_factor_aud": 750_000.0,   # US$500k x FX 1.50 (Berkus: adjust for geography)
    "rfs_step_ratio": 0.125,                  # US$250k per step on a US$2M base -> step = 12.5 % of the base
    "rfs_floor_ratio": 0.2,
    # scorecard / RFS base = tools/stage.profile(stage).pre_money_aud P50 (AU = half of US medians, owner decision 4)
    # ---------------------------------------------------------------- multiples
    "dlom": 0.25,                  # listed-peer multiples only (never on DCF / precedents)
    "ebitda_multiple_bounds": [1.0, 40.0],
    "revenue_multiple_bounds": [0.3, 40.0],
    "deal_recency_weights": [[24, 1.0], [48, 0.7], [1e9, 0.4]],
    # ---------------------------------------------------------------- confidence (§4.2)
    "confidence": {"anchor_share_high": 0.5, "anchor_agree_ratio": 2.0, "fundamental_agree_ratio": 1.5,
                   "startup_share_cap_medium": 0.5},
    # ---------------------------------------------------------------- projections (§6.4)
    "projection": {
        "max_bytes": 512 * 1024, "max_uncompressed_bytes": 20 * 1024 * 1024, "max_zip_entries": 200,
        "max_rows": 200, "max_cols": 20, "max_sheets": 3, "min_projected_years": 3, "max_projected_years": 5,
        "max_actual_years": 3, "text_max": 500, "uploads_per_day": 10,
        "growth_cap_y1": {"idea": 3.0, "pre_seed": 3.0, "seed": 2.0, "series_a": 1.5, "growth": 0.8,
                          "profitable_sme": 0.25, "listed": 0.25},
        "growth_cap_decay": 0.8,
        "jump_from_actual": 3.0, "jump_from_actual_sme": 1.5,
        "margin_cap_pp_over_p90": 0.10,
        "revenue_per_fte_max_ratio": 3.0, "revenue_per_fte_norm_aud": 250_000.0,
        "capex_vs_da_min": 0.5, "actuals_mismatch": 0.20, "hockey_stick_share": 0.80,
        "identity_tolerance": 0.01,
    },
    # ---------------------------------------------------------------- tokenisation / finalise (§7, decisions 5 + 7)
    # default issue price by stage: tools/stage.recommended_share_price (owner decision 5)
    "share_count_sig_figs": 3,
    "share_bounds": [10_000, 10**15],
    "price_free_band": 0.20,       # founder may move the price +/-20 % with a note
    "price_hard_min_ratio": 0.2,   # beyond these even an admin cannot approve
    "price_hard_max_ratio": 5.0,
    "final_valid_days": 90,
    "final_min_confidence": "medium",
    "offer_price_warn": 1.2,
    "revalue_kpi_deviation": 0.25,
    "rerun_move_to_review": 0.05,
}

# ---------------------------------------------------------------- v5.1 (27 Sep 2026, docs/V5-READINESS.md "Calibration")
# Only NEW keys (rules used when gathering inputs; every number is still copied into the method inputs, so v5 reports
# recompute exactly as before). "v5" above is never edited.
_V5_1: dict[str, Any] = {
    **_V5,
    # VC method (Sahlman, HBS 9-288-006, 1987: target returns seed 50-70 %, first stage 40-60 %, second 35-50 %):
    # target IRR by class = the venture discount rate of the class (startup_discount_rates) +/- 10 pp over the
    # projection years, and the founders' retention to exit after the later rounds' dilution (Carta software medians
    # 2025: seed 19.5 %, Series A 18 %, B 14 %, C 10 %) — replaces v5's 20-30x money multiples without retention,
    # which valued the synthetic seed case 4.7x below the scorecard.
    "vc_target_irr_band": 0.10,
    "vc_retention": {"idea": 0.51, "pre_seed": 0.51, "seed": 0.63, "series_a": 0.77, "growth": 0.90},
    "vc_retention_basis": "Carta median dilution per round, software, 2025 (seed 19.5 %, A 18 %, B 14 %, C 10 %): "
                          "retention to exit = product of (1 - dilution) of the rounds still to come (to Series C)",
    # venture-rate DCF / First Chicago (pre-profit classes): a 30-60 % rate applies until exit, so the terminal value is
    # an exit at listed peers' EV/EBITDA (Damodaran, positive-EBITDA firms) less the marketability discount — a
    # Gordon perpetuity at a venture rate (v5) gave near-zero values (First Chicago 91x below the seed blend)
    "startup_terminal": "exit",
    # revenue multiple: a cited single sector figure / market-analysis multiple / 1-2 comps / the default table is
    # blended (geometric) with the dated Damodaran EV/Sales of listed peers (less DLOM) by company size — listed-peer
    # aggregates describe listed-scale companies: share 0 at <= A$10M revenue, rising with log10(revenue) to at most
    # 0.5 at >= A$1B. The multiple keeps its own evidence factor.
    "revenue_listed_blend": {"from_aud": 10e6, "full_aud": 1e9, "max_share": 0.5,
                             "sources": ("sector_cited", "market_analysis", "comps_1_2", "default")},
    # EBITDA multiple (listed peers): the same size rule — listed-peer EV/EBITDA (less DLOM) and the private
    # transaction range for the company's size and sector (precedent band) blended geometrically, listed share 0 at
    # <= A$10M revenue rising to 0.5 at >= A$1B (small listed companies and private businesses trade well below the
    # large-cap aggregates). Calibrated on 5 AU micro-caps (in-sample: docs/V5-READINESS.md).
    "ebitda_listed_blend": {"from_aud": 10e6, "full_aud": 1e9, "max_share": 0.5},
    # stage benchmark (stage_scorecard): the AU stage pre-money table (tools/stage.au_round_medians P25/P50/P75)
    # instead of the v3 placeholder range; when funding raised to date is known, post-money ~ capital raised /
    # (1.6 x last-round dilution): cumulative capital ~ 1.6x the last round when rounds step up ~2.5x, dilution
    # 10-18 % (Carta Series A-C medians) -> 3.5x / 4.5x / 6x capital raised
    "stage_benchmark_source": "au_stage_table",
    "funding_implied_multiples": [3.5, 4.5, 6.0],
    "funding_implied_min_aud": 250_000.0,
}

PARAMS: MappingProxyType = MappingProxyType({"v5": _freeze(_V5), "v5.1": _freeze(_V5_1)})


def params(version: str = PARAMS_VERSION) -> MappingProxyType:
    try:
        return PARAMS[version or PARAMS_VERSION]
    except KeyError:
        raise ValueError(f"unknown valuation params version {version!r}") from None


def base_weight(p: MappingProxyType, method: str, cls: str) -> float:
    return float(p["base_weights"].get(method, {}).get(cls, 0.0))


def evidence_factor(p: MappingProxyType, keys: list[str] | tuple[str, ...]) -> float:
    f = 1.0
    for k in keys or ():
        f *= float(p["evidence_factors"].get(k, 1.0))
    return f
