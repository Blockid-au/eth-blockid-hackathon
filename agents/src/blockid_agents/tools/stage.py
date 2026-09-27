"""Stage classification + stage profiles (evaluation v5, docs/PLAN-EVALUATION-V5.md §1.3 / §6, docs/DECISIONS-V5.md).

Deterministic, no I/O, no LLM. Every weight, benchmark and valuation base keys off ONE stage value decided here from
evidence. Shared by the evaluation (tools/svi.py v5, the four analysts) and the valuation engine
(tools/valuation_methods.py / triangulate.py). Result shapes served to the UI: docs/EVALUATION-V5-API.md.

Stable API (additive changes only; the valuation agent imports these names)
--------------------------------------------------------------------------
    STAGES = ("idea", "pre-seed", "seed", "series-a", "growth")         # growth = Series B+
    STAGE_TABLE_VERSION = "2026-09"                                     # stored in every v5 report
    v5_enabled() -> bool                                                # env VALUATION_V5 (default off)

    classify_stage(evidence: StageEvidence | dict) -> schemas.StageDecision
        StageDecision{stage, basis: listing|round|revenue|raised|hint|human|default, reasons[], sources[],
                      signals{round,revenue,raised,hint,listing}, conflict, table_version}
    evidence_from_result(result: dict, self_reported: dict | None = None) -> StageEvidence
        builds the evidence from a stored valuation result (profile, valuation_evidence, market, self_reported)
    override_stage(decision, stage, reviewer, note="") -> StageDecision      # admin gate, basis "human"

    profile(stage) -> StageProfile            # frozen dataclass, see below (unknown stage -> "seed")
    profile_snapshot(stage, sector_key="saas") -> dict   # JSON copy stored in svi.analysis.stage_profile (/verify)
    benchmark(stage, metric, sector_key="saas", acv_aud=None) -> (P25, P50, P75, P90) | None
    score_vs_benchmark(value, bench, log=False) -> float 0..100   # 25/50/75/90 at P25/P50/P75/P90, piecewise-linear
    shrink(score, level) -> float             # 50 + (score - 50) x LEVEL_SHRINK[level]
    au_round_medians(stage) -> dict           # AU round size + pre-money P25/P50/P75 (A$), with derivation/sources
    recommended_share_price(stage) -> float   # A$ per share (DECISIONS-V5 §5)
    sector_key(sector_text, revenue_model="") -> "saas"|"marketplace"|"fintech"|"consumer"|"enterprise"|"services"|
                                                 "hardware"|"ai"
    stage_index(stage) -> int ; to_valuation_class(stage) -> "idea"|"pre_seed"|"seed"|"series_a"|"growth"

    StageProfile fields
        weights: dict[dim, float]                   # §1.1 column, sums to 1.0 (9 dimensions, DIMENSIONS order)
        bench: dict[metric, (P25, P50, P75, P90)]   # §1.3; "lower is better" metrics are listed worst -> best
        pre_money_aud: (P25, P50, P75)              # scorecard base = AU_ROUND_ADJ x US median (DECISIONS-V5 §4)
        round_size_aud: (P25, P50, P75)             # AU median deal size (Cut Through 2025)
        stage_method_weight_with_others: float      # 0.35 idea/pre-seed, 0.2 seed, 0.1 series-a/growth
        som_share: (low, high)                      # achievable share of SAM in 5 years
        plausibility: dict[metric, float]           # anti-gaming caps (tools/consistency.py)
        share_price_aud: float                      # recommended default issue price
        uncited: tuple[str, ...]                    # benchmark rows that are owner-set, not sourced

Constants
    SELF_REPORTED_FACTOR = 0.6          # owner decision 3: self-reported keeps 60% of its effect
    LEVEL_SHRINK = {0: 0, 1: 0.6, 2: 0.8, 3: 0.9, 4: 1.0}
    LEVEL_LABELS = {0: "Missing", 1: "Self-reported", 2: "Document-backed", 3: "Publicly corroborated", 4: "Connected"}
    AU_ROUND_ADJ = 0.5                  # owner decision 4 (replaceable table AU_ROUND_MEDIANS_AUD)
    DIMENSIONS, DIMENSION_LABELS, LOWER_IS_BETTER, LOG_SCALE_METRICS, SECTOR_ADJ, ACV_ADJ

Stage rules (§6.1, first applicable wins, conflicts -> the lower stage + a note):
    1. verified listing                                  -> growth
    2. latest round <= 30 months old (typed, or a verified priced-round anchor whose quote names the round):
       pre-seed/angel -> pre-seed, seed -> seed, Series A -> series-a, Series B+ -> growth.
       If the revenue band differs by >= 2 steps: the LOWER of the two, conflict=True.
    3. revenue / ARR band: 0 and no product -> idea; < A$150k -> pre-seed; < A$1.5M -> seed; < A$15M -> series-a;
       else growth
    4. raised-to-date band (only when revenue is unknown): < A$1M pre-seed, < A$5M seed, < A$30M series-a, else growth
    5. the LLM's StartupProfile.stage (hint), else "seed" (basis "default")
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from ..schemas import StageDecision

STAGES: tuple[str, ...] = ("idea", "pre-seed", "seed", "series-a", "growth")
STAGE_TABLE_VERSION = "2026-09"
DEFAULT_STAGE = "seed"
FX_USD_AUD = 1.50  # = config.FX_TO_AUD["USD"] (fixed on purpose; duplicated to keep this module import-light)

SELF_REPORTED_FACTOR = 0.6
LEVEL_SHRINK: dict[int, float] = {0: 0.0, 1: 0.6, 2: 0.8, 3: 0.9, 4: 1.0}
LEVEL_LABELS: dict[int, str] = {0: "Missing", 1: "Self-reported", 2: "Document-backed", 3: "Publicly corroborated",
                                4: "Connected"}
AU_ROUND_ADJ = 0.5
ROUND_MAX_AGE_MONTHS = 30

DIMENSIONS: tuple[str, ...] = ("founder_quality", "traction", "market", "moat", "retention", "efficiency",
                               "product_strength", "investment_readiness", "trust_verification")
DIMENSION_LABELS: dict[str, str] = {
    "founder_quality": "Founding team", "traction": "Commercial traction", "market": "Market size & timing",
    "moat": "Competitive moat", "retention": "Customer retention", "efficiency": "Capital efficiency",
    "product_strength": "Product", "investment_readiness": "Investment readiness",
    "trust_verification": "Verification",
}

# metrics where a smaller value is better (bench tuples are listed worst -> best, i.e. P25 is the largest number)
LOWER_IS_BETTER = frozenset({"burn_multiple", "cac_payback_months", "logo_churn_monthly_pct", "top_customer_share_pct"})
LOG_SCALE_METRICS = frozenset({
    "arr_aud", "revenue_aud", "revenue_ttm_aud", "sam_aud", "tam_aud", "paying_customers", "active_users",
    "active_users_monthly", "named_customers", "waitlist", "review_count", "backlog_ratio"})

# (P25, P50, P75, P90), AUD, from §1.3 (B2B SaaS default sector). Sources: see BENCH_SOURCES.
_W = {  # weights by stage, §1.1 (owner decision 2)
    "idea": (0.30, 0.16, 0.15, 0.12, 0.07, 0.04, 0.10, 0.04, 0.02),
    "pre-seed": (0.30, 0.16, 0.15, 0.12, 0.07, 0.04, 0.10, 0.04, 0.02),
    "seed": (0.30, 0.18, 0.15, 0.12, 0.09, 0.05, 0.06, 0.03, 0.02),
    "series-a": (0.30, 0.20, 0.13, 0.12, 0.10, 0.06, 0.04, 0.03, 0.02),
    "growth": (0.30, 0.20, 0.12, 0.12, 0.12, 0.08, 0.03, 0.02, 0.01),
}

_COMMON_BENCH = {  # owner-set (uncited) market / sentiment rows, same at every stage
    "sam_aud": (20e6, 100e6, 500e6, 2e9),
    "tam_aud": (200e6, 1e9, 5e9, 20e9),
    "market_cagr_pct": (3.0, 8.0, 15.0, 25.0),
    "review_rating": (3.8, 4.3, 4.6, 4.8),
    "review_count": (10.0, 50.0, 300.0, 2000.0),
    "dau_mau_pct": (10.0, 20.0, 40.0, 50.0),
    "m3_retention_pct": (30.0, 40.0, 55.0, 70.0),
    "m12_retention_pct": (15.0, 25.0, 40.0, 55.0),
    "nps": (0.0, 30.0, 50.0, 70.0),
    "top_customer_share_pct": (50.0, 30.0, 20.0, 10.0),
    "backlog_ratio": (0.1, 0.3, 0.6, 1.0),  # (contracted backlog or qualified pipeline) / ARR
    "ltv_cac": (1.0, 2.0, 3.0, 5.0),
    "integrations_count": (1.0, 5.0, 15.0, 40.0),
    "named_customers": (1.0, 3.0, 6.0, 12.0),  # customers named on the site / in cited press (verified quotes)
}

_BENCH: dict[str, dict[str, tuple[float, float, float, float]]] = {
    "idea": {
        "arr_aud": (0.0, 15e3, 60e3, 150e3), "cmgr_pct": (5.0, 10.0, 20.0, 30.0), "runway_months": (6, 12, 18, 24),
        "paying_customers": (0.0, 2.0, 5.0, 10.0),
        "pilots_paid": (0.0, 1.0, 3.0, 5.0), "lois": (0.0, 2.0, 5.0, 10.0), "waitlist": (0.0, 200.0, 1e3, 5e3),
    },
    "pre-seed": {
        "arr_aud": (0.0, 15e3, 60e3, 150e3), "cmgr_pct": (5.0, 10.0, 20.0, 30.0), "runway_months": (6, 12, 18, 24),
        "paying_customers": (0.0, 3.0, 10.0, 25.0),
        "pilots_paid": (0.0, 1.0, 3.0, 5.0), "lois": (0.0, 2.0, 5.0, 10.0), "waitlist": (0.0, 200.0, 1e3, 5e3),
    },
    "seed": {
        "arr_aud": (90e3, 450e3, 750e3, 1.5e6), "yoy_growth_pct": (40.0, 75.0, 150.0, 250.0),
        "cmgr_pct": (5.0, 10.0, 15.0, 20.0), "nrr_pct": (90.0, 100.0, 110.0, 120.0), "grr_pct": (80.0, 85.0, 90.0, 95.0),
        "logo_churn_monthly_pct": (5.0, 3.5, 2.0, 1.5), "logo_retention_6m_pct": (50.0, 60.0, 70.0, 80.0),
        "burn_multiple": (4.0, 3.0, 2.0, 1.5), "gross_margin_pct": (50.0, 65.0, 72.0, 80.0),
        "runway_months": (9, 15, 21, 27), "paying_customers": (5.0, 20.0, 50.0, 100.0),
    },
    "series-a": {
        "arr_aud": (1.5e6, 3.0e6, 6.0e6, 9e6), "yoy_growth_pct": (40.0, 100.0, 200.0, 250.0),
        "nrr_pct": (95.0, 102.0, 110.0, 120.0), "grr_pct": (85.0, 90.0, 93.0, 95.0),
        "logo_churn_monthly_pct": (4.0, 2.5, 1.5, 1.0), "burn_multiple": (3.0, 2.0, 1.2, 1.0),
        "cac_payback_months": (24.0, 18.0, 12.0, 6.0), "gross_margin_pct": (55.0, 68.0, 75.0, 82.0),
        "runway_months": (12, 18, 24, 30), "paying_customers": (30.0, 100.0, 250.0, 500.0),
    },
    "growth": {
        "arr_aud": (7.5e6, 15e6, 40e6, 100e6), "yoy_growth_pct": (30.0, 75.0, 100.0, 125.0),
        "nrr_pct": (100.0, 106.0, 115.0, 125.0), "grr_pct": (88.0, 91.0, 95.0, 97.0),
        "logo_churn_monthly_pct": (3.0, 2.0, 1.2, 0.8), "burn_multiple": (2.0, 1.5, 1.0, 0.75),
        "cac_payback_months": (24.0, 20.0, 12.0, 6.0), "gross_margin_pct": (60.0, 70.0, 78.0, 85.0),
        "runway_months": (12, 18, 24, 36), "paying_customers": (200.0, 600.0, 1500.0, 5000.0),
        "rule_of_40": (10.0, 25.0, 40.0, 60.0),
    },
}
for _s in STAGES:
    for _k, _v in _COMMON_BENCH.items():
        _BENCH[_s].setdefault(_k, _v)
    _BENCH[_s] = {k: tuple(float(x) for x in v) for k, v in _BENCH[_s].items()}

BENCH_SOURCES: dict[str, str] = {  # §9.2 keys
    "arr_aud": "S1 S5 S6 S7 (pre-seed/idea owner-set)", "yoy_growth_pct": "S2 S3 S4 S8", "cmgr_pct": "S5 S9",
    "nrr_pct": "S2 S10 S11 S12", "grr_pct": "S2 S10", "logo_churn_monthly_pct": "S13",
    "logo_retention_6m_pct": "S14", "burn_multiple": "S6 S15", "cac_payback_months": "S2 S16",
    "gross_margin_pct": "S3 S17", "runway_months": "S2", "dau_mau_pct": "S23", "m3_retention_pct": "S14 S24",
    "m12_retention_pct": "S14 S24", "top_customer_share_pct": "S47", "rule_of_40": "S34",
}
UNCITED_ROWS = ("named_customers", "sam_aud", "tam_aud", "market_cagr_pct", "review_rating", "review_count", "nps", "backlog_ratio",
                "paying_customers", "pilots_paid", "lois", "waitlist", "integrations_count", "ltv_cac")

# Retention bands depend more on ACV than stage (SaaS Capital, S10): shift NRR / GRR rows.
ACV_ADJ: tuple[tuple[float, float, float], ...] = (  # (ACV upper bound A$, NRR shift, GRR shift)
    (18_000.0, -4.0, -2.0), (150_000.0, 0.0, 0.0), (float("inf"), 5.0, 4.0))

SECTOR_ADJ: dict[str, dict[str, Any]] = {
    "saas": {},
    "marketplace": {"note": "T1 uses net revenue (GMV x take rate); R3 = supply-side GMV retention",
                    "bench": {"m12_retention_pct": (30.0, 50.0, 75.0, 100.0)}},
    "fintech": {"note": "gross margin after pass-through payment costs", "bench": {"gross_margin_pct": (35.0, 50.0,
                                                                                                         65.0, 75.0)}},
    "consumer": {"note": "T3 = monthly active users; R3 = DAU/MAU", "bench": {
        "dau_mau_pct": (10.0, 20.0, 40.0, 50.0), "m3_retention_pct": (25.0, 40.0, 55.0, 70.0)},
        "min_users": 2000},
    "enterprise": {"note": "ACV > A$150k: NRR +5, GRR +4, CAC payback +6 months", "cac_payback_shift": 6.0},
    "services": {"note": "growth benchmarks x0.6, gross margin P50 35%, NRR not scored", "growth_mult": 0.6,
                 "bench": {"gross_margin_pct": (25.0, 35.0, 45.0, 55.0)}, "no_nrr": True},
    "hardware": {"note": "growth benchmarks x0.6, gross margin P50 40%, NRR not scored", "growth_mult": 0.6,
                 "bench": {"gross_margin_pct": (28.0, 40.0, 50.0, 60.0)}, "no_nrr": True},
    "ai": {"note": "scored as SaaS; valuation comps only from AI peers"},
}

# AU scorecard bases (owner decision 4): pre-money = US median (A$ at FX 1.50) x AU_ROUND_ADJ until AU pre-money data
# is added; P25 / P75 at 0.5x / 1.85x of the median. Rows without a US source are owner-set ("set").
# Round sizes: Cut Through Venture, State of Australian Startup Funding 2025 (median deal sizes, 390 deals).
AU_ROUND_MEDIANS_AUD: dict[str, dict[str, Any]] = {
    "idea": {"us_pre_money_usd": None, "pre_money_p50": 1.5e6, "round_size_p50": 0.25e6,
             "basis": "set (owner) — half of pre-seed; no US source"},
    "pre-seed": {"us_pre_money_usd": None, "pre_money_p50": 3.0e6, "round_size_p50": 1.0e6,
                 "basis": "pre-money set (owner); round size Cut Through 2025"},
    "seed": {"us_pre_money_usd": 16e6, "round_size_p50": 2.5e6,
             "basis": "Carta US seed pre-money median US$16M (Q3 2025) x 1.50 x 0.5; round size Cut Through 2025"},
    "series-a": {"us_pre_money_usd": 48e6, "round_size_p50": 11e6,
                 "basis": "CRV/Carta US Series A pre-money median US$48M (Q1 2025) x 1.50 x 0.5; round size Cut "
                          "Through 2025"},
    "growth": {"us_pre_money_usd": None, "pre_money_p50": 200e6, "round_size_p50": 30e6,
               "basis": "pre-money set (owner); Series B+ round size Cut Through 2025"},
}
ROUND_SOURCES = ("https://carta.com/data/state-of-private-markets-q1-2026/",
                 "https://www.crv.com/content/series-a-metrics-vcs-expect",
                 "https://www.cutthrough.com/insights/state-of-australian-startup-funding-2025")


def _stage(stage: str | None) -> str:
    return stage if stage in STAGES else DEFAULT_STAGE


def au_round_medians(stage: str) -> dict:
    """{pre_money_aud: (P25, P50, P75), round_size_aud: (P25, P50, P75), basis, sources, au_round_adj}."""
    row = AU_ROUND_MEDIANS_AUD[_stage(stage)]
    p50 = (row["us_pre_money_usd"] * FX_USD_AUD * AU_ROUND_ADJ) if row.get("us_pre_money_usd") else row["pre_money_p50"]
    rs = row["round_size_p50"]
    return {"pre_money_aud": (round(p50 * 0.5, -3), round(p50, -3), round(p50 * 1.85, -3)),
            "round_size_aud": (round(rs * 0.5, -3), round(rs, -3), round(rs * 2.0, -3)),
            "basis": row["basis"], "sources": list(ROUND_SOURCES), "au_round_adj": AU_ROUND_ADJ}


SHARE_PRICE_AUD = {"idea": 0.10, "pre-seed": 0.10, "seed": 0.25, "series-a": 1.00, "growth": 1.00}
STAGE_METHOD_WEIGHT = {"idea": 0.35, "pre-seed": 0.35, "seed": 0.2, "series-a": 0.1, "growth": 0.1}
SOM_SHARE = {"idea": (0.01, 0.03), "pre-seed": (0.01, 0.03), "seed": (0.01, 0.04), "series-a": (0.02, 0.05),
             "growth": (0.03, 0.05)}
PLAUSIBILITY = {  # value above -> flag + capped at the stage P90 for scoring until an admin confirms
    "idea": {"yoy_growth_pct": 10_000, "nrr_pct": 200, "cmgr_pct": 100},
    "pre-seed": {"yoy_growth_pct": 10_000, "nrr_pct": 200, "cmgr_pct": 100},
    "seed": {"yoy_growth_pct": 3_000, "nrr_pct": 200, "cmgr_pct": 60},
    "series-a": {"yoy_growth_pct": 1_000, "nrr_pct": 200, "cmgr_pct": 40},
    "growth": {"yoy_growth_pct": 500, "nrr_pct": 180, "cmgr_pct": 25},
}


@dataclass(frozen=True)
class StageProfile:
    stage: str
    weights: MappingProxyType
    bench: MappingProxyType
    pre_money_aud: tuple[float, float, float]
    round_size_aud: tuple[float, float, float]
    stage_method_weight_with_others: float
    som_share: tuple[float, float]
    plausibility: MappingProxyType
    share_price_aud: float
    uncited: tuple[str, ...] = field(default=UNCITED_ROWS)


def _build(stage: str) -> StageProfile:
    w = dict(zip(DIMENSIONS, _W[stage], strict=True))
    assert abs(sum(w.values()) - 1.0) < 1e-9, stage
    r = au_round_medians(stage)
    return StageProfile(stage=stage, weights=MappingProxyType(w), bench=MappingProxyType(dict(_BENCH[stage])),
                        pre_money_aud=r["pre_money_aud"], round_size_aud=r["round_size_aud"],
                        stage_method_weight_with_others=STAGE_METHOD_WEIGHT[stage], som_share=SOM_SHARE[stage],
                        plausibility=MappingProxyType(dict(PLAUSIBILITY[stage])), share_price_aud=SHARE_PRICE_AUD[stage])


STAGE_PROFILES: MappingProxyType = MappingProxyType({s: _build(s) for s in STAGES})


def v5_enabled() -> bool:
    """VALUATION_V5 flag (default off). Off: every code path and stored hash is exactly v4."""
    return os.environ.get("VALUATION_V5", "0").strip().lower() in ("1", "true", "yes", "on")


def stage_index(stage: str) -> int:
    return STAGES.index(_stage(stage))


def to_valuation_class(stage: str) -> str:
    """tools/valuation_methods StageClass.cls naming (underscores)."""
    return _stage(stage).replace("-", "_")


def profile(stage: str | None) -> StageProfile:
    return STAGE_PROFILES[_stage(stage)]


def weights(stage: str | None) -> dict[str, float]:
    return dict(profile(stage).weights)


def recommended_share_price(stage: str | None) -> float:
    return SHARE_PRICE_AUD[_stage(stage)]


def acv_shift(acv_aud: float | None) -> tuple[float, float]:
    """(NRR shift, GRR shift) in points for the company's annual contract value."""
    if not acv_aud or acv_aud <= 0:
        return 0.0, 0.0
    for hi, n, g in ACV_ADJ:
        if acv_aud < hi:
            return n, g
    return 0.0, 0.0


def benchmark(stage: str | None, metric: str, sector_key: str = "saas",
              acv_aud: float | None = None) -> tuple[float, float, float, float] | None:
    """Stage benchmark (P25, P50, P75, P90) for `metric` with the sector / ACV adjustments; None = not benchmarked at
    this stage (the sub-metric is shown, not scored)."""
    s = _stage(stage)
    adj = SECTOR_ADJ.get(sector_key or "saas", {})
    b = (adj.get("bench") or {}).get(metric) or _BENCH[s].get(metric)
    if b is None:
        return None
    b = tuple(float(x) for x in b)
    if metric in ("yoy_growth_pct", "cmgr_pct") and adj.get("growth_mult"):
        b = tuple(x * adj["growth_mult"] for x in b)
    if metric in ("nrr_pct", "grr_pct"):
        if adj.get("no_nrr"):
            return None
        n, g = acv_shift(acv_aud)
        if sector_key == "enterprise":
            n, g = max(n, 5.0), max(g, 4.0)
        d = n if metric == "nrr_pct" else g
        b = tuple(x + d for x in b)
        if metric == "grr_pct":
            b = tuple(min(x, 100.0) for x in b)
    if metric == "cac_payback_months" and adj.get("cac_payback_shift"):
        b = tuple(x + adj["cac_payback_shift"] for x in b)
    return b  # type: ignore[return-value]


def profile_snapshot(stage: str | None, sector_key: str = "saas", acv_aud: float | None = None) -> dict:
    """The exact profile values a report used (stored in svi.analysis.stage_profile so /verify never depends on the
    live table)."""
    p = profile(stage)
    d: dict[str, Any] = {"stage": p.stage, "stage_method_weight_with_others": p.stage_method_weight_with_others,
                         "share_price_aud": p.share_price_aud}
    d["weights"] = dict(p.weights)
    d["plausibility"] = dict(p.plausibility)
    d["bench"] = {m: list(benchmark(p.stage, m, sector_key, acv_aud) or ()) for m in p.bench
                  if benchmark(p.stage, m, sector_key, acv_aud) is not None}
    d["pre_money_aud"], d["round_size_aud"] = list(p.pre_money_aud), list(p.round_size_aud)
    d["som_share"], d["uncited"] = list(p.som_share), list(p.uncited)
    d.update(table_version=STAGE_TABLE_VERSION, sector_key=sector_key or "saas",
             level_shrink={str(k): v for k, v in LEVEL_SHRINK.items()})
    return d


# ------------------------------------------------------------------ scoring helpers
def _t(x: float, log: bool) -> float:
    return math.log10(max(x, 0.0) + 1.0) if log else x


def score_vs_benchmark(value: float | None, bench, log: bool = False) -> float | None:
    """0..100: 25 at P25, 50 at P50, 75 at P75, 90 at P90, piecewise-linear between (log10(x+1) for money / counts);
    below P25 falls linearly to 0 with the P25->P50 slope, above P90 rises to 100 with the P75->P90 slope. Works for
    lower-is-better rows (tuple listed worst -> best). None when value or bench is missing."""
    if value is None or bench is None or len(bench) != 4:
        return None
    xs = [_t(float(b), log) for b in bench]
    ys = [25.0, 50.0, 75.0, 90.0]
    v = _t(float(value), log)
    inc = xs[-1] >= xs[0]
    if not inc:  # mirror so x increases
        xs, v = [-x for x in xs], -v
    if v <= xs[0]:
        slope = (ys[1] - ys[0]) / (xs[1] - xs[0]) if xs[1] != xs[0] else 0.0
        out = ys[0] - (xs[0] - v) * slope if slope else (25.0 if v == xs[0] else 0.0)
    elif v >= xs[3]:
        slope = (ys[3] - ys[2]) / (xs[3] - xs[2]) if xs[3] != xs[2] else 0.0
        out = ys[3] + (v - xs[3]) * slope if slope else 90.0
    else:
        out = 50.0
        for i in range(3):
            if xs[i] <= v <= xs[i + 1]:
                span = xs[i + 1] - xs[i]
                out = ys[i] + ((v - xs[i]) / span * (ys[i + 1] - ys[i]) if span else 0.0)
                break
    return round(max(0.0, min(100.0, out)), 2)


def shrink(score: float, level: int) -> float:
    """Evidence shrink toward 50 (§4.2): L1 keeps 60% of the distance, L2 80%, L3 90%, L4 100%."""
    return round(50.0 + (score - 50.0) * LEVEL_SHRINK.get(int(level), 0.0), 2)


# ------------------------------------------------------------------ sector
_SECTOR_TERMS = (
    ("marketplace", ("marketplace", "two-sided", "gig ", "on-demand", "peer-to-peer")),
    ("fintech", ("fintech", "payment", "banking", "lending", "neobank", "insurtech", "financial technology")),
    ("consumer", ("consumer app", "social", "mobile game", "dating", "b2c", "consumer subscription")),
    ("hardware", ("hardware", "device", "robot", "manufactur", "medtech device", "iot")),
    ("services", ("consulting", "agency", "services firm", "professional services", "recruitment")),
    ("ai", ("artificial intelligence", " ai ", "ai-native", "genai", "llm", "machine learning")),
)


def sector_key(sector: str, revenue_model: str = "", acv_aud: float | None = None) -> str:
    rm = (revenue_model or "").lower()
    if rm == "marketplace":
        return "marketplace"
    if rm in ("services", "hardware"):
        return rm
    if acv_aud and acv_aud > 150_000:
        return "enterprise"
    s = f" {(sector or '').lower()} "
    for key, terms in _SECTOR_TERMS:
        if any(t in s for t in terms):
            return key
    return "saas"


# ------------------------------------------------------------------ stage classification
@dataclass
class RoundSignal:
    round_type: str  # free text: "Series A", "seed", "pre-seed", "angel", "Series C", ...
    as_of: str = ""  # YYYY-MM or YYYY ("" unknown)
    source: str = ""  # URL or "self_reported"


@dataclass
class StageEvidence:
    listed: bool = False
    listing_ref: str = ""
    rounds: list[RoundSignal] = field(default_factory=list)
    revenue_aud: float | None = None  # ARR or TTM revenue; None = unknown (0 = known zero)
    revenue_source: str = ""
    product_live: bool | None = None
    raised_to_date_aud: float | None = None
    hint: str = ""  # StartupProfile.stage (LLM)
    today: str = ""  # YYYY-MM-DD (default: now)


_ROUND_RE = [
    (re.compile(r"\bseries\s*[b-h]\b|\bseries\s*[b-h]\d?\b|\bgrowth round\b|\bpre-?ipo\b", re.IGNORECASE), "growth"),
    (re.compile(r"\bseries\s*a\b", re.IGNORECASE), "series-a"),
    (re.compile(r"\bpre[-\s]?seed\b|\bangel\b|\bfriends and family\b", re.IGNORECASE), "pre-seed"),
    (re.compile(r"\bseed\b", re.IGNORECASE), "seed"),
]


def stage_from_round(text: str) -> str | None:
    """'Series A' -> series-a, 'pre-seed'/'angel' -> pre-seed, 'seed' -> seed, 'Series B'+ -> growth; None if the
    text names no round."""
    for rx, st in _ROUND_RE:
        if rx.search(text or ""):
            return st
    return None


def stage_from_revenue(rev: float, product_live: bool | None = None) -> str:
    if rev <= 0:
        return "idea" if product_live is False else "pre-seed"
    if rev < 150_000:
        return "pre-seed"
    if rev < 1_500_000:
        return "seed"
    if rev < 15_000_000:
        return "series-a"
    return "growth"


def stage_from_raised(raised: float) -> str:
    if raised < 1_000_000:
        return "pre-seed"
    if raised < 5_000_000:
        return "seed"
    if raised < 30_000_000:
        return "series-a"
    return "growth"


def _months_between(as_of: str, today: str) -> float | None:
    m = re.match(r"^(\d{4})(?:-(\d{2}))?", as_of or "")
    t = re.match(r"^(\d{4})-(\d{2})", today or "")
    if not m or not t:
        return None
    y, mo = int(m.group(1)), int(m.group(2) or 6)
    return (int(t.group(1)) - y) * 12 + (int(t.group(2)) - mo)


def _fmt_aud(x: float) -> str:
    return f"A${x / 1e6:,.2f}M" if x >= 1e6 else f"A${x:,.0f}"


def classify_stage(evidence: StageEvidence | dict) -> StageDecision:
    """Deterministic stage from evidence (rules in the module docstring). Pure function."""
    from datetime import UTC, datetime

    ev = evidence if isinstance(evidence, StageEvidence) else _evidence_from_dict(evidence)
    today = ev.today or datetime.now(UTC).date().isoformat()
    reasons: list[str] = []
    sources: list[str] = []
    signals: dict[str, str] = {}
    if ev.hint in STAGES:
        signals["hint"] = ev.hint

    # 2. latest dated (<= 30 months) round; undated rounds count only if no dated one exists
    round_stage, round_src = None, ""
    dated = []
    for r in ev.rounds:
        st = stage_from_round(r.round_type)
        if not st:
            continue
        age = _months_between(r.as_of, today)
        if age is not None and age > ROUND_MAX_AGE_MONTHS:
            reasons.append(f"{r.round_type} round ({r.as_of}) is older than {ROUND_MAX_AGE_MONTHS} months: not used")
            continue
        dated.append((r.as_of or "", STAGES.index(st), st, r))
    if dated:
        dated.sort(key=lambda x: (x[0], x[1]), reverse=True)
        _, _, round_stage, r = dated[0]
        round_src = r.source
        signals["round"] = round_stage
    rev_stage = None
    if ev.revenue_aud is not None:
        rev_stage = stage_from_revenue(float(ev.revenue_aud), ev.product_live)
        signals["revenue"] = rev_stage
    raised_stage = None
    if ev.raised_to_date_aud:
        raised_stage = stage_from_raised(float(ev.raised_to_date_aud))
        signals["raised"] = raised_stage

    def done(stage: str, basis: str, conflict: bool = False) -> StageDecision:
        return StageDecision(stage=stage, basis=basis, reasons=reasons, sources=[s for s in sources if s],
                             signals=signals, conflict=conflict, table_version=STAGE_TABLE_VERSION)

    # 1. listing
    if ev.listed:
        signals["listing"] = "growth"
        reasons.insert(0, f"listed company ({ev.listing_ref or 'verified listing'}): growth stage")
        sources.append(ev.listing_ref)
        return done("growth", "listing")
    if round_stage:
        reasons.insert(0, f"latest round: {dated[0][3].round_type}"
                          + (f" ({dated[0][3].as_of})" if dated[0][3].as_of else "") + f" -> {round_stage}")
        sources.append(round_src)
        if rev_stage and abs(STAGES.index(rev_stage) - STAGES.index(round_stage)) >= 2:
            low = min(rev_stage, round_stage, key=STAGES.index)
            reasons.append(f"round says {round_stage} but revenue {_fmt_aud(ev.revenue_aud or 0)} looks like "
                           f"{rev_stage}: using the lower stage ({low})")
            return done(low, "round" if low == round_stage else "revenue", conflict=True)
        return done(round_stage, "round")
    if rev_stage and (ev.revenue_aud or 0) > 0:
        reasons.insert(0, f"revenue {_fmt_aud(ev.revenue_aud or 0)}"
                          + (f" ({ev.revenue_source})" if ev.revenue_source else "") + f" -> {rev_stage}")
        return done(rev_stage, "revenue")
    if raised_stage:
        reasons.insert(0, f"raised to date {_fmt_aud(ev.raised_to_date_aud or 0)} -> {raised_stage}"
                          + (" (no revenue figure)" if rev_stage is None else " (no revenue yet)"))
        if rev_stage == "idea" and raised_stage != "pre-seed":
            reasons.append("no product live: capped at pre-seed")
            return done("pre-seed", "raised", conflict=True)
        return done(raised_stage, "raised")
    if rev_stage:  # known zero revenue, nothing else
        reasons.insert(0, "no revenue yet" + (" and no product live" if ev.product_live is False else "")
                       + f" -> {rev_stage}")
        return done(rev_stage, "revenue")
    if ev.hint in STAGES:
        reasons.insert(0, f"no round, revenue or funding evidence: using the website reading ({ev.hint})")
        return done(ev.hint, "hint")
    reasons.insert(0, f"no stage evidence: default {DEFAULT_STAGE}")
    return done(DEFAULT_STAGE, "default")


def override_stage(decision: StageDecision | dict | None, stage: str, reviewer: str, note: str = "") -> StageDecision:
    if stage not in STAGES:
        raise ValueError(f"unknown stage {stage!r}")
    d = StageDecision.model_validate(decision) if decision else StageDecision(stage=stage, basis="human")
    prev = d.stage
    reasons = [f"set to {stage} by {reviewer}" + (f": {note}" if note else "")
               + (f" (evidence said {prev})" if prev != stage else ""), *d.reasons]
    return StageDecision(stage=stage, basis="human", reasons=reasons, sources=d.sources, signals=d.signals,
                         conflict=d.conflict, table_version=d.table_version or STAGE_TABLE_VERSION)


def _evidence_from_dict(d: dict) -> StageEvidence:
    rounds = [r if isinstance(r, RoundSignal) else RoundSignal(**{k: r.get(k, "") for k in ("round_type", "as_of",
                                                                                         "source")})
              for r in (d.get("rounds") or [])]
    return StageEvidence(listed=bool(d.get("listed")), listing_ref=d.get("listing_ref", ""), rounds=rounds,
                         revenue_aud=d.get("revenue_aud"), revenue_source=d.get("revenue_source", ""),
                         product_live=d.get("product_live"), raised_to_date_aud=d.get("raised_to_date_aud"),
                         hint=d.get("hint", ""), today=d.get("today", ""))


def evidence_from_result(result: dict, self_reported: dict | None = None, today: str = "") -> StageEvidence:
    """StageEvidence from a stored valuation result / graph state: verified listing and priced-round anchors
    (valuation_evidence), typed last round + revenue/ARR + raised (self_reported, v1 or v2 keys), the profile's
    revenue and LLM stage hint, verified company financials (funding raised)."""
    result = result or {}
    sr = self_reported if self_reported is not None else (result.get("self_reported") or {})
    prof = result.get("profile") or {}
    metrics = prof.get("metrics") or {}
    ve = result.get("valuation_evidence") or {}
    cf = (result.get("market") or {}).get("company_financials") or {}
    listing = ve.get("listing")
    rounds = []
    if sr.get("last_round_type"):
        rounds.append(RoundSignal(str(sr["last_round_type"]), str(sr.get("last_round_date") or "")[:7],
                                  "self_reported"))
    for a in ve.get("anchors") or []:
        if a.get("kind") == "priced_round" and stage_from_round(a.get("quote", "")):
            rounds.append(RoundSignal(a.get("quote", "")[:120], a.get("as_of", ""), a.get("source_url", "")))
    rev, rsrc = None, ""
    for key, src in (("arr_aud", "self_reported ARR"), ("revenue_ttm_aud", "self_reported")):
        if sr.get(key) is not None:
            rev, rsrc = float(sr[key]), src
            break
    if rev is None and float(metrics.get("revenue_ttm_aud") or 0) > 0:
        rev = float(metrics["revenue_ttm_aud"])
        rsrc = (prof.get("metrics_sources") or {}).get("revenue_ttm_aud", "website")
    if rev is None and cf.get("usable_for_valuation") and cf.get("revenue_ttm_aud"):
        rev, rsrc = float(cf["revenue_ttm_aud"]), "cited_source"
    raised = sr.get("raised_to_date_aud")
    if raised is None:
        raised = cf.get("funding_raised_total_aud") or metrics.get("raised_to_date_aud") or None
    return StageEvidence(listed=bool(listing),
                         listing_ref=f"{listing['exchange']}: {listing['ticker']}" if listing else "",
                         rounds=rounds, revenue_aud=rev, revenue_source=rsrc,
                         product_live=result.get("product_live"),
                         raised_to_date_aud=float(raised) if raised else None, hint=prof.get("stage", ""),
                         today=today or (ve.get("as_of") or ""))
