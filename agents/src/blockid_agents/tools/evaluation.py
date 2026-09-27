"""Deterministic evaluation v5 (docs/PLAN-EVALUATION-V5.md §1.2, §4; shapes: docs/EVALUATION-V5-API.md).

The LLM never produces a number used here. Inputs are: founder-typed figures (L1), uploaded documents (CSV -> L2
metrics, deck -> L1 claims), claims the analysts extracted and code verified (own site L1, third-party L3), approved
KPI updates (L3), free public lookups (L3), the verified competitor list, and — for the non-computed dimensions —
the qualitative scores (LLM-suggested / team report / human). Same inputs -> same Analysis.

    evaluate(seed, *, stage_decision, self_reported, documents, competitors, qualitative, kpis, sector, today)
        -> Analysis   (all 9 dimensions, index-ready)

`seed` is an Analysis (or dict) carrying the evidence gathered by the analysts: claims, powers, lookups,
market_sizing (target customer text, ABS count), dropped, analysts meta. Re-scoring (new typed numbers or documents)
calls evaluate() again with the stored seed: no web, no LLM.
"""
from __future__ import annotations

from collections.abc import Iterable

from ..schemas import (
    Analysis,
    DimensionDetail,
    MarketSizing,
    MetricValue,
    MoatPower,
    StageDecision,
    SubMetric,
    VerifiedClaim,
)
from . import consistency
from . import metrics_calc as mc
from . import stage as st

# founder field (v1 + v2) -> (metric key, unit)
TYPED_FIELDS: dict[str, tuple[str, str]] = {
    "revenue_ttm_aud": ("revenue_ttm_aud", "AUD"), "revenue_prev_ttm_aud": ("revenue_prev_ttm_aud", "AUD"),
    "revenue_growth_yoy_pct": ("revenue_growth_yoy_pct", "%"), "arr_aud": ("arr_aud", "AUD"),
    "mrr_aud": ("mrr_aud", "AUD"), "mrr_6m_ago_aud": ("mrr_6m_ago_aud", "AUD"),
    "mrr_12m_ago_aud": ("mrr_12m_ago_aud", "AUD"), "gmv_ttm_aud": ("gmv_ttm_aud", "AUD"),
    "take_rate_pct": ("take_rate_pct", "%"), "gross_margin_pct": ("gross_margin_pct", "%"),
    "customers": ("paying_customers", "count"), "paying_customers_12m_ago": ("paying_customers_12m_ago", "count"),
    "active_users_monthly": ("active_users_monthly", "count"), "active_users_daily": ("active_users_daily", "count"),
    "waitlist": ("waitlist", "count"), "pilots_paid": ("pilots_paid", "count"), "lois": ("lois", "count"),
    "contracted_backlog_aud": ("contracted_backlog_aud", "AUD"),
    "qualified_pipeline_aud": ("qualified_pipeline_aud", "AUD"),
    "top_customer_share_pct": ("top_customer_share_pct", "%"),
    "logo_churn_monthly_pct": ("logo_churn_monthly_pct", "%"), "grr_pct": ("grr_pct", "%"), "nrr_pct": ("nrr_pct", "%"),
    "m3_retention_pct": ("m3_retention_pct", "%"), "m12_retention_pct": ("m12_retention_pct", "%"),
    "nps": ("nps", "score"), "cash_aud": ("cash_aud", "AUD"), "burn_monthly_aud": ("burn_monthly_aud", "AUD"),
    "net_new_arr_12m_aud": ("net_new_arr_12m_aud", "AUD"), "cac_aud": ("cac_aud", "AUD"),
    "arpa_monthly_aud": ("arpa_monthly_aud", "AUD"), "raised_to_date_aud": ("raised_to_date_aud", "AUD"),
    "runway_months": ("runway_months", "months"), "target_customer_count": ("target_customer_count", "count"),
    "annual_price_aud": ("annual_price_aud", "AUD"), "integrations_count": ("integrations_count", "count"),
    "employees": ("employees", "count"),
}
# claim metric (analyst extraction) -> metric key
CLAIM_METRICS: dict[str, str] = {
    "arr": "arr_aud", "revenue": "revenue_ttm_aud", "mrr": "mrr_aud", "revenue_growth_yoy": "revenue_growth_yoy_pct",
    "paying_customers": "paying_customers", "customers": "paying_customers", "active_users": "active_users_monthly",
    "mau": "active_users_monthly", "dau": "active_users_daily", "waitlist": "waitlist", "pilots_paid": "pilots_paid",
    "lois": "lois", "contracted_backlog": "contracted_backlog_aud", "pipeline": "qualified_pipeline_aud",
    "gross_margin": "gross_margin_pct", "nrr": "nrr_pct", "grr": "grr_pct", "logo_churn_monthly": "logo_churn_monthly_pct",
    "m3_retention": "m3_retention_pct", "m12_retention": "m12_retention_pct", "dau_mau": "dau_mau_pct",
    "review_rating": "review_rating", "review_count": "review_count", "nps": "nps", "tam": "tam_aud", "sam": "sam_aud",
    "cagr": "market_cagr_pct", "target_customer_count": "target_customer_count", "annual_price": "annual_price_aud",
    "integrations": "integrations_count", "top_customer_share": "top_customer_share_pct", "gmv": "gmv_ttm_aud",
    "take_rate": "take_rate_pct", "burn_monthly": "burn_monthly_aud", "cash": "cash_aud",
    "raised_to_date": "raised_to_date_aud",
}
UNITS = {k: ("AUD" if k.endswith("_aud") else "%" if k.endswith("_pct") else "count") for k in CLAIM_METRICS.values()}
UNITS.update(review_rating="rating", nps="score")

POWER_LABELS = {"network_effects": "Network effects", "switching_costs": "Switching costs",
                "ip_data": "Proprietary data / IP", "scale": "Scale / cost advantage", "brand": "Brand / reputation",
                "counter_positioning": "Licences, exclusives, counter-positioning",
                "competition": "Competitive intensity (inverse)"}
POWER_WEIGHTS = {"network_effects": 0.20, "switching_costs": 0.20, "ip_data": 0.15, "scale": 0.10, "brand": 0.10,
                 "counter_positioning": 0.10, "competition": 0.15}
POWER_CAPS = {"network_effects": 2, "switching_costs": 2, "ip_data": 3, "scale": 1, "brand": 2,
              "counter_positioning": 3, "competition": 3}
LEVEL_POINTS = {0: 0.0, 1: 35.0, 2: 70.0, 3: 100.0}
SOURCE_TIER_POINTS = {1: 90.0, 2: 70.0, 3: 50.0, 4: 30.0}
CODE_DIMS = ("traction", "market", "moat", "retention", "efficiency")
LLM_DIMS = ("founder_quality", "product_strength", "investment_readiness")
FOUNDER_LLM_CAP = 50.0  # founder_quality without a team report: the LLM suggestion is capped (§1.1)


# ------------------------------------------------------------------ candidates
def _mv(value, unit: str, source: str, level: int = 0, **kw) -> MetricValue:
    return MetricValue(value=float(value), unit=unit, source=source, level=level, **kw)


def typed_candidates(self_reported: dict | None) -> dict[str, list[MetricValue]]:
    sr = self_reported or {}
    as_of = sr.get("as_of") or {}
    out: dict[str, list[MetricValue]] = {}
    for field, (metric, unit) in TYPED_FIELDS.items():
        v = sr.get(field)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        out.setdefault(metric, []).append(_mv(v, unit, "self_reported", 1, as_of=str(as_of.get(field, ""))[:7],
                                              note="self-reported"))
    return out


def document_candidates(documents: Iterable[dict] | None) -> dict[str, list[MetricValue]]:
    out: dict[str, list[MetricValue]] = {}
    for d in documents or []:
        parsed = d.get("parsed") or {}
        if d.get("kind") == "metrics_csv":
            high = any(f.get("severity") == "high" for f in parsed.get("flags") or [])
            months = parsed.get("months") or []
            for k, v in (parsed.get("metrics") or {}).items():
                if v is None or k.startswith("cmgr_basis"):
                    continue
                metric = "yoy_growth_pct" if k == "yoy_growth_pct" else k
                out.setdefault(metric, []).append(_mv(
                    v, "AUD" if k.endswith("_aud") else "%" if k.endswith("_pct") else "x" if k == "burn_multiple"
                    else "months" if k.endswith("_months") else "count", "csv", 1 if high else 2,
                    as_of=months[-1] if months else "", source_url=f"doc:{d.get('doc_id', '')}",
                    note="computed from the uploaded metrics CSV" + (" (forensic flags: level 1)" if high else "")))
    return out


def claim_candidates(claims: Iterable[VerifiedClaim]) -> dict[str, list[MetricValue]]:
    out: dict[str, list[MetricValue]] = {}
    for c in claims:
        metric = CLAIM_METRICS.get(c.metric)
        if metric is None or c.subject == "competitor":
            continue
        v = c.value_aud if metric.endswith("_aud") else c.value
        if v is None:
            continue
        src = "deck" if c.source_url.startswith("doc:") else ("site" if c.level <= 1 else "cited")
        out.setdefault(metric, []).append(_mv(v, UNITS.get(metric, ""), src, c.level, as_of=c.as_of,
                                              source_url=c.source_url, quote=c.quote))
    return out


def merge(*cands: dict[str, list[MetricValue]]) -> dict[str, list[MetricValue]]:
    out: dict[str, list[MetricValue]] = {}
    for c in cands:
        for k, v in (c or {}).items():
            out.setdefault(k, []).extend(v)
    return out


def _derived(m: dict[str, MetricValue], key: str, value: float | None, unit: str, inputs: list[str],
             note: str) -> None:
    if value is None:
        return
    lv = [m[i].level for i in inputs if i in m]
    m[key] = MetricValue(value=value, unit=unit, source="computed", level=min(lv) if lv else 1, note=note,
                         as_of=max((m[i].as_of for i in inputs if i in m), default=""))


def derive(m: dict[str, MetricValue], revenue_model: str) -> None:
    """Derived metrics (code only): ARR from MRR, growth from two points, CMGR, runway, burn multiple, payback."""
    v = {k: x.value for k, x in m.items()}
    if "arr_aud" not in m and "mrr_aud" in m and revenue_model in ("subscription", "") and v["mrr_aud"]:
        _derived(m, "arr_aud", mc.annualised(v["mrr_aud"]), "AUD", ["mrr_aud"], "12 × MRR")
    if revenue_model == "marketplace" and "gmv_ttm_aud" in m and "take_rate_pct" in m and "revenue_ttm_aud" not in m:
        _derived(m, "revenue_ttm_aud", round(v["gmv_ttm_aud"] * v["take_rate_pct"] / 100, 2), "AUD",
                 ["gmv_ttm_aud", "take_rate_pct"], "net revenue = GMV × take rate")
    if "yoy_growth_pct" not in m or m["yoy_growth_pct"].level < 2:
        g, ins = None, []
        if "revenue_ttm_aud" in m and "revenue_prev_ttm_aud" in m:
            g, ins = mc.growth_pct(v["revenue_ttm_aud"], v["revenue_prev_ttm_aud"]), ["revenue_ttm_aud",
                                                                                       "revenue_prev_ttm_aud"]
        elif "mrr_aud" in m and "mrr_12m_ago_aud" in m:
            g, ins = mc.growth_pct(v["mrr_aud"], v["mrr_12m_ago_aud"]), ["mrr_aud", "mrr_12m_ago_aud"]
        if g is not None:
            _derived(m, "yoy_growth_pct", g, "%", ins, "computed from two figures")
        elif "yoy_growth_pct" not in m and "revenue_growth_yoy_pct" in m:
            m["yoy_growth_pct"] = m["revenue_growth_yoy_pct"].model_copy()
    if "cmgr_pct" not in m and "mrr_aud" in m and "mrr_6m_ago_aud" in m:
        _derived(m, "cmgr_pct", mc.cmgr_pct(v["mrr_aud"], v["mrr_6m_ago_aud"], 6), "%", ["mrr_aud", "mrr_6m_ago_aud"],
                 "CMGR over 6 months")
    v = {k: x.value for k, x in m.items()}
    if "runway_months" not in m and "cash_aud" in m and "burn_monthly_aud" in m:
        _derived(m, "runway_months", mc.runway_months(v["cash_aud"], v["burn_monthly_aud"]), "months",
                 ["cash_aud", "burn_monthly_aud"], "cash ÷ monthly burn")
    if "burn_multiple" not in m and "burn_monthly_aud" in m and "net_new_arr_12m_aud" in m:
        _derived(m, "burn_multiple", mc.burn_multiple(v["burn_monthly_aud"] * 12, v["net_new_arr_12m_aud"]), "x",
                 ["burn_monthly_aud", "net_new_arr_12m_aud"], "net burn ÷ net new ARR")
    if "cac_payback_months" not in m and "cac_aud" in m and "arpa_monthly_aud" in m:
        _derived(m, "cac_payback_months", mc.cac_payback_months(v["cac_aud"], v["arpa_monthly_aud"],
                                                                v.get("gross_margin_pct")), "months",
                 ["cac_aud", "arpa_monthly_aud"], "CAC ÷ (ARPA × gross margin)")
    if "ltv_cac" not in m and "cac_aud" in m and "arpa_monthly_aud" in m and "logo_churn_monthly_pct" in m:
        _derived(m, "ltv_cac", mc.ltv_cac(v["arpa_monthly_aud"], v.get("gross_margin_pct"),
                                          v["logo_churn_monthly_pct"], v["cac_aud"]), "x",
                 ["cac_aud", "arpa_monthly_aud", "logo_churn_monthly_pct"], "LTV ÷ CAC")
    rev = v.get("arr_aud") or v.get("revenue_ttm_aud")
    backlog = v.get("contracted_backlog_aud") or v.get("qualified_pipeline_aud")
    if backlog and rev:
        src = "contracted_backlog_aud" if v.get("contracted_backlog_aud") else "qualified_pipeline_aud"
        _derived(m, "backlog_ratio", round(backlog / rev, 3), "x", [src], f"{src.replace('_aud', '')} ÷ revenue")
    if "active_users_daily" in m and "active_users_monthly" in m and v["active_users_monthly"]:
        _derived(m, "dau_mau_pct", round(v["active_users_daily"] / v["active_users_monthly"] * 100, 2), "%",
                 ["active_users_daily", "active_users_monthly"], "DAU ÷ MAU")


# ------------------------------------------------------------------ dimension scoring
def _sub(key: str, metric: str, label: str, weight: float, mv: MetricValue | None, stage: str, sector: str,
         acv: float | None, bench_metric: str | None = None, applicable: bool = True) -> SubMetric:
    bm = bench_metric or metric
    bench = st.benchmark(stage, bm, sector, acv)
    sm = SubMetric(key=key, metric=metric, label=label, weight=weight, value=mv,
                   benchmark=list(bench) if bench else None, lower_is_better=bm in st.LOWER_IS_BETTER)
    if not applicable or ((mv is None or mv.value is None) and bench is None):
        sm.status = "not_applicable"
    elif mv is None or mv.value is None:
        sm.status = "missing"
    elif bench is None:
        sm.status, sm.note = "not_benchmarked", f"not benchmarked at the {stage} stage (shown only)"
    else:
        sm.score_raw = st.score_vs_benchmark(mv.value, bench, log=bm in st.LOG_SCALE_METRICS or metric in st.LOG_SCALE_METRICS)
        sm.score = st.shrink(sm.score_raw, mv.level or 1)
        sm.status = "scored"
    return sm


def _fixed(key: str, metric: str, label: str, weight: float, points: float | None, level: int,
           mv: MetricValue | None = None, note: str = "") -> SubMetric:
    """A sub-metric scored by a rubric (points already reflect the evidence level: no second shrink)."""
    sm = SubMetric(key=key, metric=metric, label=label, weight=weight, value=mv, note=note)
    if points is None:
        sm.status = "missing"
    else:
        sm.score_raw = sm.score = round(points, 2)
        sm.status = "scored"
        if sm.value is None:
            sm.value = MetricValue(value=round(points, 2), unit="points", level=level, source="computed")
    return sm


def _dimension(key: str, weight: float, subs: list[SubMetric], flags: list[str] | None = None,
               not_applicable_note: str = "") -> DimensionDetail:
    applicable = [s for s in subs if s.status not in ("not_applicable", "not_benchmarked")]
    scored = [s for s in applicable if s.status in ("scored", "capped") and s.score is not None]
    tot = sum(s.weight for s in applicable)
    cov_w = sum(s.weight for s in scored)
    coverage = round(cov_w / tot, 3) if tot else 0.0
    d = DimensionDetail(key=key, label=st.DIMENSION_LABELS[key], weight=weight, score=40.0, sub_metrics=subs,
                        coverage=coverage, cap=round(40 + 60 * coverage, 2), flags=flags or [], basis="computed")
    if not applicable:
        d.status, d.rationale = "not_applicable", not_applicable_note or "not applicable at this stage yet"
        d.cap = 40.0
        return d
    if not scored:
        d.status, d.rationale = "not_enough_data", "Not enough data"
        return d
    raw = sum(s.score * s.weight for s in scored) / cov_w
    d.score_raw = round(raw, 2)
    d.score = round(min(raw, d.cap), 1)
    d.level = round(sum((s.value.level if s.value else 0) * s.weight for s in scored) / cov_w, 2)
    top = max(applicable, key=lambda s: s.weight)
    top_level = top.value.level if (top.value and top in scored) else 0
    d.confidence = "high" if coverage >= 0.7 and top_level >= 2 else "medium" if coverage >= 0.4 else "low"
    d.status = "scored"
    parts = [f"{s.label} {s.score:.0f}" for s in scored]
    d.rationale = f"{'; '.join(parts)} (coverage {coverage:.0%}" + (f", capped at {d.cap:.0f}" if raw > d.cap else "") \
        + ")"
    return d


TIPS = {
    "sam_aud": "Add your target customer (who pays), how many there are and your annual price (Market tab)",
    "tam_aud": "Cite an industry or government market-size figure for your segment",
    "market_cagr_pct": "Cite the growth rate (CAGR) of your segment from an industry or government source",
    "source_tier": "Use government / industry-body sources for the market figures",
    "nrr_pct": "Add net revenue retention (or upload monthly MRR movements as a CSV)",
    "grr_pct": "Add gross revenue retention or monthly logo churn (or upload a metrics CSV)",
    "review_rating": "Link your app-store or review-site page (ratings count toward retention)",
    "nps": "Add your NPS or link a review site",
    "burn_multiple": "Add monthly burn and net new ARR (or upload a metrics CSV)",
    "runway_months": "Add cash and monthly burn",
}


def _improve(d: DimensionDetail) -> list[str]:
    out = []
    for s in sorted(d.sub_metrics, key=lambda x: -x.weight):
        if s.status == "missing":
            if d.key == "moat":
                out.append(f"Show evidence of {s.label.lower()} (public page, registry number or document)")
            else:
                out.append(TIPS.get(s.metric) or f"Add {s.label.lower()} (typed, or upload a metrics CSV / deck to "
                           "have it document-backed)")
        elif s.status == "scored" and s.value and s.value.level <= 1 and (s.score_raw or 0) > 50:
            out.append(f"Back {s.label.lower()} with a document: self-reported figures keep only 60% of their effect")
    return out[:3]


def _mget(m: dict[str, MetricValue], *keys: str) -> tuple[str, MetricValue | None]:
    for k in keys:
        if k in m and m[k].value is not None:
            return k, m[k]
    return keys[0], None


def traction(m: dict[str, MetricValue], stage: str, sector: str, acv: float | None, revenue_model: str,
             claims: list[VerifiedClaim], flags_by_metric: dict[str, list[str]], w: float) -> DimensionDetail:
    recurring = revenue_model in ("subscription", "")
    k1, t1 = _mget(m, "arr_aud", "revenue_ttm_aud") if recurring else _mget(m, "revenue_ttm_aud", "arr_aud")
    subs = [_sub("T1", k1, "Revenue scale (ARR / revenue)", 0.30, t1, stage, sector, acv, bench_metric="arr_aud")]
    kg, tg = _mget(m, "yoy_growth_pct")
    use_cmgr = tg is None or st.benchmark(stage, "yoy_growth_pct", sector) is None
    if use_cmgr and "cmgr_pct" in m:
        subs.append(_sub("T2", "cmgr_pct", "Growth (monthly, CMGR)", 0.40, m["cmgr_pct"], stage, sector, acv))
    else:
        subs.append(_sub("T2", "yoy_growth_pct", "Growth (year on year)", 0.40, tg, stage, sector, acv))
    logos = [c for c in claims if c.metric == "customer_logo"]
    kc, cust = _mget(m, "paying_customers")
    if sector == "consumer" and "active_users_monthly" in m:
        t3 = _sub("T3", "active_users_monthly", "Monthly active users", 0.15, m["active_users_monthly"], stage, sector,
                  acv, bench_metric="waitlist")
    elif cust is not None:
        t3 = _sub("T3", "paying_customers", "Paying customers", 0.15, cust, stage, sector, acv)
    elif logos:
        lv = max(c.level for c in logos)
        t3 = _sub("T3", "named_customers", "Named customers (verified)", 0.15,
                  MetricValue(value=len(logos), unit="count", level=lv, source="site" if lv <= 1 else "cited",
                              source_url=logos[0].source_url, quote=logos[0].quote), stage, sector, acv)
    else:
        t3 = _sub("T3", "paying_customers", "Paying customers", 0.15, None, stage, sector, acv)
    share = m.get("top_customer_share_pct")
    if t3.score is not None and share is not None and (share.value or 0) > 50:
        t3.score, t3.status, t3.note = min(t3.score, 50.0), "capped", "one customer > 50% of revenue: capped at 50"
    subs.append(t3)
    if stage in ("idea", "pre-seed") and not m.get("backlog_ratio"):
        best = None
        for k, lbl in (("pilots_paid", "Paid pilots"), ("lois", "Letters of intent"), ("waitlist", "Waitlist")):
            if k in m:
                s = _sub("T4", k, lbl, 0.15, m[k], stage, sector, acv)
                if best is None or (s.score or 0) > (best.score or 0):
                    best = s
        subs.append(best or _sub("T4", "pilots_paid", "Pilots, LOIs or waitlist", 0.15, None, stage, sector, acv))
    else:
        t4 = _sub("T4", "backlog_ratio", "Contracted backlog / pipeline vs revenue", 0.15, m.get("backlog_ratio"),
                  stage, sector, acv)
        if t4.score is not None and (t4.value.level if t4.value else 0) < 2 and t4.score > 60:
            t4.score, t4.status, t4.note = 60.0, "capped", "forward signal capped at 60 unless documented"
        subs.append(t4)
    d = _dimension("traction", w, subs, flags_by_metric.get("traction"))
    d.evidence = [c for c in claims if c.analyst in ("traction", "deck") and c.subject == "company"][:12]
    return d


def market(m: dict[str, MetricValue], ms: MarketSizing, stage: str, sector: str, acv: float | None,
           claims: list[VerifiedClaim], w: float) -> DimensionDetail:
    sam = m.get("sam_aud")
    subs = [_sub("M1", "sam_aud", "Serviceable market (bottom-up)", 0.40, sam, stage, sector, acv),
            _sub("M2", "tam_aud", "Total market (cited, cross-check)", 0.15, m.get("tam_aud"), stage, sector, acv),
            _sub("M3", "market_cagr_pct", "Market growth (cited CAGR)", 0.25, m.get("market_cagr_pct"), stage, sector,
                 acv)]
    rev = (m.get("arr_aud") or m.get("revenue_ttm_aud"))
    if sam is not None and sam.value and rev is not None and rev.value:
        share = rev.value / sam.value
        pts = 20.0 if share > 0.20 else 50.0 if share > 0.05 else 75.0
        subs.append(_fixed("M4", "som_realism", "SOM realism (revenue vs SAM)", 0.10, pts, min(sam.level, rev.level),
                           note=f"current revenue is {share:.1%} of SAM"))
        if share > 0.20:
            ms.warnings.append("current revenue is above 20% of the bottom-up SAM: the SAM looks mis-sized")
    else:
        subs.append(SubMetric(key="M4", metric="som_realism", label="SOM realism (revenue vs SAM)", weight=0.10,
                              status="not_applicable", note="needs revenue and a bottom-up SAM"))
    tier = ms.source_tier
    subs.append(_fixed("M5", "source_tier", "Source quality", 0.10, SOURCE_TIER_POINTS.get(tier) if tier else None,
                       3 if tier and tier <= 2 else 1, note=f"tier {tier}" if tier else "no cited market source"))
    d = _dimension("market", w, subs)
    d.flags = list(ms.warnings)
    d.evidence = [c for c in claims if c.analyst == "market_size"][:10]
    return d


def competition_points(competitors: list[dict], raised_aud: float | None) -> tuple[float | None, str]:
    if not competitors:
        return None, "no verified competitors (competitive intensity unknown)"
    n = len(competitors)
    pts = 75.0 - 4.0 * max(0, n - 3)
    funded = [c.get("raised_aud") or 0 for c in competitors]
    top = max(funded) if funded else 0
    note = f"{n} competitors"
    if top and raised_aud and top > 10 * raised_aud:
        pts -= 15
        note += f"; the best-funded raised {top / max(raised_aud, 1):.0f}× the company"
    elif top and not raised_aud and top > 10e6:
        pts -= 10
        note += f"; a competitor raised A${top / 1e6:,.0f}M"
    return max(15.0, min(85.0, pts)), note


def moat(powers: list[MoatPower], competitors: list[dict], m: dict[str, MetricValue], typed: dict,
         lookups: dict, w: float) -> tuple[DimensionDetail, list[MoatPower]]:
    by = {p.key: p.model_copy(deep=True) for p in powers}
    for k in POWER_WEIGHTS:
        by.setdefault(k, MoatPower(key=k, label=POWER_LABELS[k], weight=POWER_WEIGHTS[k]))
    sr = typed or {}

    def claim(k: str, level: int, note: str) -> None:
        p = by[k]
        if level > p.level:
            p.level, p.note = level, note

    if sr.get("patents") or sr.get("trademarks"):
        claim("ip_data", 1, "patents / trade marks typed by the founder (not yet checked in the registry)")
    if sr.get("licences"):
        claim("counter_positioning", 1, "licences typed by the founder")
    if sr.get("exclusive_contracts"):
        claim("counter_positioning", 1, "exclusive contracts typed by the founder")
    ic = m.get("integrations_count")
    if ic is not None and (ic.value or 0) >= 5:
        claim("switching_costs", 2 if ic.level >= 2 or ic.source in ("site", "cited") else 1,
              f"{ic.value:.0f} integrations ({ic.source})")
    app = lookups.get("app_store") or {}
    if (app.get("rating_count") or 0) >= 100 and (app.get("rating") or 0) >= 4.0:
        claim("brand", 2, f"App Store rating {app['rating']:.1f} from {app['rating_count']:,} ratings")
    subs: list[SubMetric] = []
    for k, p in by.items():
        p.weight, p.label, p.level_cap = POWER_WEIGHTS[k], POWER_LABELS[k], POWER_CAPS[k]
        if k == "competition":
            raised = (m.get("raised_to_date_aud").value if m.get("raised_to_date_aud") else None)
            pts, note = competition_points(competitors, raised)
            p.points, p.note, p.level = (pts or 0.0), note, (3 if pts is not None else 0)
            subs.append(_fixed(f"Mo:{k}", k, p.label, p.weight, pts, 3, note=note))
            continue
        p.level = min(p.level, p.level_cap)
        p.points = LEVEL_POINTS[p.level]
        subs.append(_fixed(f"Mo:{k}", k, p.label, p.weight, p.points if p.level > 0 else None, p.level,
                           note=p.note))
    d = _dimension("moat", w, subs)
    d.evidence = [c for p in by.values() for c in p.evidence][:12]
    return d, [by[k] for k in POWER_WEIGHTS]


def retention(m: dict[str, MetricValue], stage: str, sector: str, acv: float | None, has_customers: bool,
              claims: list[VerifiedClaim], w: float) -> DimensionDetail:
    consumer = sector in ("consumer", "marketplace")
    no_nrr = st.SECTOR_ADJ.get(sector, {}).get("no_nrr", False)
    subs = [_sub("R1", "nrr_pct", "Net revenue retention", 0.30, m.get("nrr_pct"), stage, sector, acv,
                 applicable=not consumer and not no_nrr)]
    if "grr_pct" in m:
        r2 = _sub("R2", "grr_pct", "Gross revenue retention", 0.25, m["grr_pct"], stage, sector, acv,
                  applicable=not consumer)
    elif "logo_churn_monthly_pct" in m:
        r2 = _sub("R2", "logo_churn_monthly_pct", "Monthly logo churn", 0.25, m["logo_churn_monthly_pct"], stage,
                  sector, acv, applicable=not consumer)
    else:
        r2 = _sub("R2", "grr_pct", "Gross revenue / logo retention", 0.25, None, stage, sector, acv,
                  applicable=not consumer)
    subs.append(r2)
    r3k, r3 = _mget(m, "m3_retention_pct", "dau_mau_pct", "m12_retention_pct")
    subs.append(_sub("R3", r3k, "Usage retention (cohorts / DAU÷MAU)", 0.20, r3, stage, sector, acv,
                     applicable=consumer or r3 is not None))
    rating, count = m.get("review_rating"), m.get("review_count")
    if rating is not None and (count is None or (count.value or 0) >= 10):
        r4 = _sub("R4", "review_rating", "Customer sentiment (reviews)", 0.15, rating, stage, sector, acv)
        if count is not None:
            r4.note = f"{count.value:,.0f} ratings"
    else:
        r4 = _sub("R4", "nps", "Customer sentiment (reviews / NPS)", 0.15, m.get("nps"), stage, sector, acv)
    subs.append(r4)
    subs.append(_sub("R5", "top_customer_share_pct", "Customer concentration", 0.10, m.get("top_customer_share_pct"),
                     stage, sector, acv, applicable=has_customers))
    if not has_customers and not any(s.status == "scored" for s in subs):
        for s in subs:
            s.status = "not_applicable"
        return _dimension("retention", w, subs, not_applicable_note="not applicable yet: no customers")
    d = _dimension("retention", w, subs)
    d.evidence = [c for c in claims if c.analyst == "retention"][:10]
    return d


def efficiency(m: dict[str, MetricValue], stage: str, sector: str, acv: float | None, w: float) -> DimensionDetail:
    subs = [_sub("E1", "burn_multiple", "Burn multiple", 0.30, m.get("burn_multiple"), stage, sector, acv),
            _sub("E2", "runway_months", "Runway", 0.25, m.get("runway_months"), stage, sector, acv),
            _sub("E3", "gross_margin_pct", "Gross margin", 0.25, m.get("gross_margin_pct"), stage, sector, acv,
                 applicable=stage not in ("idea",)),
            _sub("E4", "cac_payback_months", "CAC payback", 0.10, m.get("cac_payback_months"), stage, sector, acv),
            _sub("E5", "ltv_cac", "LTV / CAC", 0.05, m.get("ltv_cac"), stage, sector, acv),
            _sub("E6", "rule_of_40", "Rule of 40", 0.05, m.get("rule_of_40"), stage, sector, acv,
                 applicable=stage == "growth")]
    return _dimension("efficiency", w, subs)


# ------------------------------------------------------------------ market sizing (bottom-up)
def market_sizing(seed: MarketSizing | None, m: dict[str, MetricValue], stage: str) -> MarketSizing:
    ms = (seed or MarketSizing()).model_copy(deep=True)
    ms.warnings = [w for w in ms.warnings if "mis-sized" not in w and "top-down" not in w]
    cnt, price = m.get("target_customer_count"), m.get("annual_price_aud")
    if cnt is not None and price is not None and cnt.value and price.value:
        ms.target_customers, ms.annual_price_aud = cnt.value, price.value
        ms.target_customers_source = ms.target_customers_source if cnt.source == "registry" else (
            cnt.source_url or cnt.source)
        ms.annual_price_source = price.source_url or price.source
        ms.sam_aud = round(cnt.value * price.value, -3)
        m["sam_aud"] = MetricValue(value=ms.sam_aud, unit="AUD", source="computed", level=min(cnt.level, price.level),
                                   note="target customers × annual price")
    elif "sam_aud" in m:
        ms.sam_aud = m["sam_aud"].value
    tam = m.get("tam_aud")
    if tam is not None:
        ms.tam_aud, ms.tam_source_url, ms.tam_quote = tam.value, tam.source_url, tam.quote
        if ms.sam_aud and tam.value and tam.value > 10 * ms.sam_aud:
            ms.warnings.append("the top-down figure covers a much wider market than the bottom-up SAM (> 10×): the "
                               "bottom-up SAM is used")
    cagr = m.get("market_cagr_pct")
    if cagr is not None:
        ms.cagr_pct, ms.cagr_source_url = cagr.value, cagr.source_url
    lo, hi = st.profile(stage).som_share
    ms.som_share = [lo, hi]
    ms.som_aud_5y = [round(ms.sam_aud * lo, -3), round(ms.sam_aud * hi, -3)] if ms.sam_aud else []
    return ms


# ------------------------------------------------------------------ entry point
def _qual_dim(key: str, qd: dict | None, w: float, has_team: bool) -> DimensionDetail:
    qd = qd or {}
    score = float(qd.get("score", 40.0))
    basis = qd.get("basis", "ai_suggested")
    rationale = qd.get("rationale", "")
    if key == "founder_quality" and basis == "ai_suggested" and score > FOUNDER_LLM_CAP:
        score, rationale = FOUNDER_LLM_CAP, rationale + f" (no founding-team report: capped at {FOUNDER_LLM_CAP:.0f})"
    status = {"team_report": "team_report", "human": "human"}.get(basis, "ai_suggested")
    d = DimensionDetail(key=key, label=st.DIMENSION_LABELS[key], weight=w, score=round(score, 1), status=status,
                        basis=basis, rationale=rationale, coverage=1.0 if qd else 0.0,
                        confidence="high" if basis in ("team_report", "human") else "medium" if qd else "low",
                        level=3.0 if basis == "team_report" else 1.0)
    if key == "founder_quality" and basis != "team_report" and not has_team:
        d.improve = ["Add the founding team (hr.blockid.au review) — the team is 30% of the score"]
    return d


def evaluate(seed: Analysis | dict | None, *, stage_decision: StageDecision | dict, self_reported: dict | None = None,
             documents: list[dict] | None = None, competitors: list[dict] | None = None,
             qualitative: dict | None = None, kpis: dict[str, list[MetricValue]] | None = None,
             sector: str = "", revenue_model: str = "", verifications: dict[str, dict] | None = None) -> Analysis:
    """`verifications`: {metric: {level: 2|3, note, by}} set by an admin (POST .../metrics/verify)."""
    seed_a = Analysis.model_validate(seed) if isinstance(seed, dict) else (seed or None)
    sd = StageDecision.model_validate(stage_decision) if isinstance(stage_decision, dict) else stage_decision
    stage = sd.stage
    sr = self_reported or {}
    claims = list(seed_a.claims) if seed_a else []
    seen = {(c.source_url, c.metric, c.quote) for c in claims}
    for d in documents or []:  # deck claims verified at upload / rescore time are stored on the document
        for c in (d.get("parsed") or {}).get("claims") or []:
            vc = VerifiedClaim.model_validate(c)
            if (vc.source_url, vc.metric, vc.quote) not in seen:
                seen.add((vc.source_url, vc.metric, vc.quote))
                claims.append(vc)
    doc_ids = {f"doc:{d.get('doc_id')}" for d in documents or []}
    claims = [c for c in claims if not c.source_url.startswith("doc:") or c.source_url in doc_ids]  # deleted docs
    rm = sr.get("revenue_model") or revenue_model or (seed_a.revenue_model if seed_a else "")
    extra = {}
    if seed_a:
        for k, mv in (seed_a.metrics or {}).items():  # lookups / registry values stored by the analysts
            if mv.source in ("lookup", "registry", "competitors") and mv.value is not None:
                extra.setdefault(k, []).append(mv)
    cands = merge(typed_candidates(sr), document_candidates(documents), claim_candidates(claims), extra, kpis or {})
    acv0 = next((c.value for c in cands.get("annual_price_aud", []) if c.value), None)
    skey = st.sector_key(sector, rm, acv0)
    resolved, flags = consistency.resolve(cands, stage, seed_a.lookups if seed_a else {}, skey)
    for metric, ver in (verifications or {}).items():
        if metric in resolved and int(ver.get("level", 0)) > resolved[metric].level:
            mv = resolved[metric]
            resolved[metric] = mv.model_copy(update={
                "level": min(3, int(ver["level"])),
                "note": (mv.note + "; " if mv.note else "") + f"verified by {ver.get('by', 'admin')}"
                        + (f": {ver['note']}" if ver.get("note") else "")})
    derive(resolved, rm)
    flags += consistency.plausibility(resolved, stage) if "yoy_growth_pct" in resolved and not any(
        f.code == "implausible" and "yoy_growth_pct" in f.metrics for f in flags) else []
    ms = market_sizing(seed_a.market_sizing if seed_a else None, resolved, stage)
    acv = ms.annual_price_aud or acv0
    weights = st.weights(stage)
    by_dim: dict[str, list[str]] = {}
    for f in flags:
        for mt in f.metrics:
            dim = ("retention" if mt in ("nrr_pct", "grr_pct", "logo_churn_monthly_pct", "top_customer_share_pct")
                   else "efficiency" if mt in ("runway_months", "burn_multiple", "gross_margin_pct")
                   else "traction")
            by_dim.setdefault(dim, []).append(f.message)
    has_customers = any(k in resolved for k in ("paying_customers", "arr_aud", "revenue_ttm_aud",
                                                "active_users_monthly"))
    dims: dict[str, DimensionDetail] = {}
    dims["traction"] = traction(resolved, stage, skey, acv, rm, claims, by_dim, weights["traction"])
    dims["market"] = market(resolved, ms, stage, skey, acv, claims, weights["market"])
    dims["moat"], powers = moat(list(seed_a.powers) if seed_a else [], competitors or [], resolved, sr,
                                seed_a.lookups if seed_a else {}, weights["moat"])
    dims["retention"] = retention(resolved, stage, skey, acv, has_customers, claims, weights["retention"])
    dims["efficiency"] = efficiency(resolved, stage, skey, acv, weights["efficiency"])
    for k in ("retention", "efficiency"):
        dims[k].flags = list(dict.fromkeys(dims[k].flags + by_dim.get(k, [])))
    # trust_verification: share of scored weight (dimension weight × sub-metric weight) at level >= 2
    tot = hi = 0.0
    for k in CODE_DIMS:
        for s in dims[k].sub_metrics:
            if s.status in ("scored", "capped") and s.value is not None:
                wt = weights[k] * s.weight
                tot += wt
                hi += wt if s.value.level >= 2 else 0.0
    share = round(hi / tot, 3) if tot else 0.0
    dims["trust_verification"] = DimensionDetail(
        key="trust_verification", label=st.DIMENSION_LABELS["trust_verification"],
        weight=weights["trust_verification"], score=round(100 * share, 1) if tot else 40.0,
        status="scored" if tot else "not_enough_data", basis="computed", coverage=1.0 if tot else 0.0,
        rationale=f"{share:.0%} of the scored inputs are document-backed or better" if tot else "Not enough data",
        confidence="high" if tot else "low",
        improve=["Upload a metrics CSV or connect a data source to raise verification"] if share < 0.5 else [])
    q = qualitative or {}
    has_team = (q.get("founder_quality") or {}).get("basis") == "team_report"
    for k in LLM_DIMS:
        dims[k] = _qual_dim(k, q.get(k), weights[k], has_team)
    for k in CODE_DIMS:
        dims[k].improve = _improve(dims[k])
    ordered = {k: dims[k] for k in st.DIMENSIONS}
    gains = []
    for k, d in ordered.items():
        for tip in d.improve:
            gains.append((d.weight * max(0.0, 75.0 - d.score), tip))
    top = [t for _, t in sorted(gains, key=lambda x: -x[0])]
    code_cov = [ordered[k].coverage for k in ("traction", "market", "retention")]
    conf = ("high" if share >= 0.5 and min(code_cov) >= 0.7 else
            "medium" if sum(code_cov) / len(code_cov) >= 0.4 else "low")
    return Analysis(
        stage=sd, stage_profile=st.profile_snapshot(stage, skey, acv), sector_key=skey, revenue_model=rm or "",
        dimensions=ordered, metrics=resolved, claims=claims, dropped=list(seed_a.dropped) if seed_a else [],
        flags=flags, powers=powers, market_sizing=ms, lookups=seed_a.lookups if seed_a else {}, trust_share=share,
        confidence=conf, top_improvements=list(dict.fromkeys(top))[:3],
        documents=[{k: d.get(k) for k in ("doc_id", "kind", "filename", "sha256")} for d in documents or []],
        analysts=seed_a.analysts if seed_a else {})
