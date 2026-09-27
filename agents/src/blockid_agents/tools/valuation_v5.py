"""Valuation v5 — method selection, blend, confidence, football field and tokenisation proposal
(docs/PLAN-VALUATION-V5.md §3, §4, §7; docs/DECISIONS-V5.md).

    triangulate_v5(...)  gather inputs (verified evidence, SVI dimension scores, confirmed projections, confirmed or
                         AI-suggested startup ratings, admin assumptions, dated market data) -> run every method the
                         stage x data matrix allows -> blend_v5 -> Triangulation(version="v5")
    blend_v5(...)        weights = matrix x evidence factors; stage benchmark rule (v3); IVS-105 outlier rule
                         (the method furthest beyond 3x from the weighted median of all methods -> 0, repeated; a fresh own price is never excluded);
                         normalise; range widened by confidence; confidence with plain-words reasons
    recompute_v5(tri)    rebuild every method from its stored inputs (valuation_methods.METHOD_BUILDERS) and blend
                         again with PARAMS[tri.params_version] — the public /verify path

Deterministic: same inputs -> same numbers. The LLM never produces a number here.
"""
from __future__ import annotations

import copy
from typing import Any

from ..config import FX_TO_AUD_AS_OF, default_multiples, fx_to_aud
from ..schemas import Triangulation, ValuationMethod
from . import market_data
from . import valuation_methods as vm
from .valuation_params import (
    BERKUS_KEYS,
    CLASSES,
    FUNDAMENTAL_METHODS,
    MARKET_DATASET,
    PARAMS_VERSION,
    PROJECTION_LABEL,
    PROJECTION_METHODS,
    RFS_KEYS,
    STARTUP_METHODS,
    base_weight,
    params,
)

VERSION = "v5"
ORDER = ("market_anchor", "revenue_multiple", "ebitda_multiple", "precedents", "dcf", "first_chicago", "vc_method",
         "scorecard", "berkus", "rfs", "stage_scorecard")
KIND_LABEL = {"market_cap": "market capitalisation", "priced_round": "priced funding round",
              "secondary_sale": "secondary share sale", "investor_mark": "investor mark",
              "reported_valuation": "reported valuation"}
DERIVED_BERKUS = {"sound_idea": ("market_attractiveness", "market"), "prototype": ("product_strength",),
                  "quality_team": ("founder_quality",), "strategic_relationships": ("investment_readiness",),
                  "product_rollout": ("revenue_performance", "traction")}


# ================================================================== blend + confidence
def _ratio(a: float, b: float) -> float:
    return max(a, b) / max(min(a, b), 1.0)


def blend_v5(methods: list[ValuationMethod], cls: str, p, *, listed: bool = False, as_of: str = "",
             fx_as_of: str = FX_TO_AUD_AS_OF) -> Triangulation:
    by = {m.method: m for m in methods}
    stage = by.get("stage_scorecard")
    others = [m for m in methods if m is not stage and m.raw_weight > 0]
    if stage is not None:
        if not others:
            stage.raw_weight = float(p["stage_alone_weight"])
        elif stage.raw_weight > 0:
            ref = sum(m.raw_weight * m.value_aud for m in others) / sum(m.raw_weight for m in others)
            r = _ratio(stage.value_aud, ref)
            if r > p["stage_outlier_ratio"]:
                stage.raw_weight = 0.0
                stage.notes = [*stage.notes, f"not used: {r:.0f}x away from the other methods"]

    # IVS 105: investigate, don't average — exclude the most divergent method while one is > 3x from the others
    def exempt(m: ValuationMethod) -> bool:
        if m.method != "market_anchor":
            return False
        age = ((m.inputs.get("anchors") or [{}])[0]).get("age_months")
        return age is not None and age <= p["anchor_exempt_age_months"]

    while True:
        used = [m for m in methods if m.raw_weight > 0]
        if len(used) < 2:
            break
        ref = vm.weighted_median([(m.value_aud, m.raw_weight) for m in used])
        cands = [(_ratio(m.value_aud, ref), m) for m in used if not exempt(m)]
        cands = [c for c in cands if c[0] > p["outlier_ratio"]]
        if not cands:
            break
        cands.sort(key=lambda x: (-x[0], x[1].raw_weight, -ORDER.index(x[1].method)))
        r, out = cands[0]
        out.raw_weight = 0.0
        out.notes = [*out.notes, f"not used: {r:.1f}x away from the other methods (reviewed, not averaged)"]

    used = [m for m in methods if m.raw_weight > 0]
    total = sum(m.raw_weight for m in used)
    for m in methods:
        m.weight = round(m.raw_weight / total, 4) if total and m.raw_weight > 0 else 0.0
    value = sum(m.weight * m.value_aud for m in used)
    low = sum(m.weight * m.low_aud for m in used)
    high = sum(m.weight * m.high_aud for m in used)
    conf, reasons = confidence_v5(methods, p, listed=listed)
    half = p["range_min_half_width"][conf]
    low, high = min(low, value * (1 - half)), max(high, value * (1 + half))
    return Triangulation(version=VERSION, value_aud=value, low_aud=low, high_aud=high, confidence=conf,
                         confidence_reasons=reasons, methods=methods, listed=listed, as_of=as_of, fx_as_of=fx_as_of,
                         valuation_class=cls)


def _verified_fundamental(m: ValuationMethod) -> bool:
    ev = m.inputs.get("evidence") or []
    if m.method == "revenue_multiple":
        return m.inputs.get("multiple_source") in ("comps_3plus", "comps_1_2", "sector_cited")
    if m.method in ("ebitda_multiple", "precedents"):
        actual = any(k in ev for k in ("audited", "management_actuals"))
        verified_mult = any(k in ev for k in ("comps_3plus", "comps_1_2", "deals_3plus", "deals_1_2", "sector_cited"))
        return actual and verified_mult
    return False


def confidence_v5(methods: list[ValuationMethod], p, *, listed: bool) -> tuple[str, list[str]]:
    c = p["confidence"]
    reasons: list[str] = []
    used = [m for m in methods if m.weight > 0]
    anchor = next((m for m in used if m.method == "market_anchor"), None)
    a_age, kind = None, None
    if anchor is not None:
        lead = (anchor.inputs.get("anchors") or [{}])[0]
        a_age, kind = lead.get("age_months"), lead.get("kind")
        if kind == "market_cap":
            reasons.append("listed company: current market capitalisation found and verified in a source")
        elif a_age is None:
            reasons.append("the company's own valuation was found, but the source gives no date")
        else:
            reasons.append(f"the company's own {KIND_LABEL.get(kind, 'valuation')} was found and verified "
                           f"({a_age:.0f} months old)")
    else:
        reasons.append("no verified valuation, funding round or market cap of the company itself was found")
    fund = [m for m in used if m.method in FUNDAMENTAL_METHODS]
    verified = [m for m in fund if _verified_fundamental(m)]
    proj = [m for m in used if m.method in PROJECTION_METHODS]
    startup_share = sum(m.weight for m in used if m.method in STARTUP_METHODS)
    for m in fund:
        if m.method == "revenue_multiple":
            src = m.inputs.get("multiple_source")
            reasons.append({"comps_3plus": f"revenue multiple from {m.inputs.get('n')} comparable companies",
                            "comps_1_2": f"revenue multiple from only {m.inputs.get('n')} comparable company(ies)",
                            "sector_cited": "revenue multiple from a sector figure stated in a source",
                            "market_analysis": "revenue multiple reported by the market analysis (not quote-checked)",
                            "default": "revenue multiple is an uncalibrated default"}.get(src, "revenue multiple"))
    if proj:
        reasons.append("part of the value rests on the business's own projections (unaudited)")
    if startup_share > 0:
        reasons.append(f"startup methods (scorecard / milestones / risk factors) carry {startup_share:.0%} of the value")
    excluded = [m for m in methods if m.raw_weight == 0 and any(n.startswith("not used: ") and "away" in n
                                                               for n in m.notes)]
    if excluded:
        reasons.append(f"{len(excluded)} method(s) far from the others were reviewed and left out")
    if len(used) > 1:
        vals = [m.value_aud for m in used]
        spread = max(vals) / max(min(vals), 1.0)
        reasons.append(f"methods used are x{spread:.1f} apart")
    else:
        spread = 1.0

    conf = "low"
    if anchor is not None and kind == "market_cap" and anchor.weight >= c["anchor_share_high"] or (anchor is not None and a_age is not None and a_age <= 24 and anchor.weight >= c["anchor_share_high"]
          and spread <= c["anchor_agree_ratio"]):
        conf = "high"
    else:
        actual_fund = [m for m in verified if m.method != "revenue_multiple" or m.inputs.get("n", 0) >= 3
                       or m.inputs.get("multiple_source") == "sector_cited"]
        many = sum(1 for m in fund if any(k in (m.inputs.get("evidence") or []) for k in ("comps_3plus", "deals_3plus"))
                   or (m.method == "revenue_multiple" and m.inputs.get("multiple_source") == "comps_3plus"))
        if len(actual_fund) >= 2 and many >= 1 and _spread(actual_fund) <= c["fundamental_agree_ratio"]:
            conf = "high"
        elif anchor is not None or verified:
            conf = "medium"
    if conf == "high" and startup_share > c["startup_share_cap_medium"]:
        conf = "medium"
        reasons.append("capped at medium: startup methods carry more than half of the value")
    return conf, reasons


def _spread(ms: list[ValuationMethod]) -> float:
    vals = [m.value_aud for m in ms]
    return max(vals) / max(min(vals), 1.0) if vals else 1.0


def football_field(methods: list[ValuationMethod]) -> list[dict]:
    out = []
    for m in methods:
        reason = next((n for n in reversed(m.notes) if n.startswith("not used")), None) if m.weight == 0 else None
        if m.weight == 0 and reason is None:
            reason = "not used at this stage" if m.raw_weight == 0 else None
        out.append({"method": m.method, "label": m.label, "low_aud": round(m.low_aud, 2),
                    "mid_aud": round(m.value_aud, 2), "high_aud": round(m.high_aud, 2), "weight": m.weight,
                    "used": m.weight > 0, "reason": reason, "projection_based": m.method in PROJECTION_METHODS})
    return out


def tokenisation_proposal(value: float, low: float, high: float, stage: str, *, shares_fd: int | None,
                          planned_raise: float, p) -> dict:
    """Plan §7.1 + owner decision 5 (stage default price A$0.10 / 0.25 / 1.00)."""
    from .stage import recommended_share_price

    default_price = float(recommended_share_price(stage))
    bounds = tuple(p["share_bounds"])
    if shares_fd:
        shares, basis = int(shares_fd), "existing_shares"
    else:
        shares = vm.clean_share_count(value, default_price, int(p["share_count_sig_figs"]), bounds)
        basis = "new_company"
    price = round(value / shares, 4) if shares else default_price
    out = {"pre_money_aud": round(value, -3), "low_aud": round(low, -3), "high_aud": round(high, -3), "stage": stage,
           "basis": basis, "fd_shares_existing": int(shares_fd) if shares_fd else None,
           "default_price_for_stage_aud": default_price, "recommended_price_per_share_aud": price,
           "total_shares": shares, "offer_price_low_aud": round(low / shares, 4) if shares else None,
           "offer_price_high_aud": price, "raise_aud": 0.0, "new_shares": 0, "post_money_aud": 0.0,
           "dilution_pct": 0.0}
    if planned_raise and planned_raise > 0 and price > 0:
        new = int(planned_raise // price)
        out.update(raise_aud=round(planned_raise, 2), new_shares=new, post_money_aud=round(value + planned_raise, -3),
                   dilution_pct=round(new * 100 / (shares + new), 2) if shares + new else 0.0)
    return out


# ================================================================== recompute (public /verify)
def recompute_v5(tri: dict) -> dict:
    """{low, mid, high, confidence, methods[]} rebuilt from stored inputs with PARAMS[params_version]."""
    p = params((tri or {}).get("params_version") or PARAMS_VERSION)
    cls = (tri or {}).get("valuation_class") or "seed"
    methods: list[ValuationMethod] = []
    for m in (tri or {}).get("methods") or []:
        name = m.get("method")
        if name not in vm.METHOD_BUILDERS:
            continue
        built = vm.build(name, copy.deepcopy(m.get("inputs") or {}), p, cls)
        if built is not None:
            methods.append(built)
    t = blend_v5(methods, cls, p, listed=bool((tri or {}).get("listed")), as_of=(tri or {}).get("as_of", ""))
    return {"low": round(t.low_aud, -3), "mid": round(t.value_aud, -3), "high": round(t.high_aud, -3),
            "confidence": t.confidence,
            "methods": [{"method": m.method, "value_aud": round(m.value_aud, 2), "low_aud": round(m.low_aud, 2),
                         "high_aud": round(m.high_aud, 2), "weight": m.weight} for m in t.methods]}


# ================================================================== gathering inputs (new valuations)
def _dim(dims: dict, *names: str, default: float = 50.0) -> tuple[float, str]:
    for n in names:
        d = dims.get(n)
        if d is None:
            continue
        sc = d.get("score") if isinstance(d, dict) else getattr(d, "score", None)
        basis = d.get("basis") if isinstance(d, dict) else getattr(d, "basis", "")
        if sc is not None:
            return float(sc), str(basis or "")
    return default, "default"


def projection_rows_aud(parsed: dict) -> tuple[list[dict], list[dict], float]:
    """(actual rows, projected rows used — after caps, AUD) and the FX rate. `years_used` wins over `years`."""
    rate = float(parsed.get("fx_rate_to_aud") or fx_to_aud(parsed.get("currency", "AUD")) or 0)
    rows = parsed.get("years_used") or parsed.get("years") or []
    keys = ("revenue", "cogs", "opex", "ebitda", "d_and_a", "tax", "capex", "nwc", "change_nwc")

    def conv(r: dict) -> dict:
        out = {k: (None if r.get(k) is None else round(float(r[k]) * rate, 2)) for k in keys}
        out.update(year=r.get("year"), actual=bool(r.get("actual")), headcount=r.get("headcount"),
                   customers=r.get("customers"))
        return out

    conv_rows = [conv(r) for r in rows]
    return [r for r in conv_rows if r["actual"]], [r for r in conv_rows if not r["actual"]], rate


def _uploaded_projected(parsed: dict, rate: float) -> list[dict]:
    rows = [r for r in (parsed.get("years") or []) if not r.get("actual")]
    keys = ("revenue", "cogs", "opex", "d_and_a", "tax", "capex", "nwc", "change_nwc")
    return [{**{k: (None if r.get(k) is None else round(float(r[k]) * rate, 2)) for k in keys}, "year": r.get("year")}
            for r in rows]


def _ebitda(r: dict) -> float:
    return float(r["revenue"]) - float(r["cogs"]) - float(r["opex"])


def triangulate_v5(*, profile, market, ve, dims: dict, svi_index: float, self_reported: dict | None,
                   v5_inputs: dict | None, projection: dict | None, stage_ranges: dict,
                   as_of: str, params_version: str = PARAMS_VERSION, dataset: str = MARKET_DATASET,
                   stage_decision: dict | None = None) -> Triangulation:
    """profile: StartupProfile; market: MarketAnalysis | None; ve: VerifiedValuationEvidence; dims: SVI dimension
    scores; v5_inputs: {industry, startup_factors, factors_basis, deals, stage_override, class_override,
    assumptions}; projection: confirmed projection record {parsed, checks, sha256, attested_by, attested_at}."""
    from . import stage as stage_tools
    from .triangulate import anchors_as_inputs, choose_multiple

    p = params(params_version)
    snap = market_data.snapshot(dataset)
    vi = v5_inputs or {}
    asm = dict(vi.get("assumptions") or {})

    # ---------------------------------------------------------------- stage + class
    result_like = {"profile": profile.model_dump(), "valuation_evidence": ve.model_dump(),
                   "market": market.model_dump() if market else None}
    if stage_decision:  # evaluation v5 decided the stage (svi.analysis.stage): one stage for score and value
        decision = stage_tools.StageDecision.model_validate(stage_decision)
    else:
        decision = stage_tools.classify_stage(stage_tools.evidence_from_result(result_like, self_reported or {},
                                                                               today=as_of or ""))
    if vi.get("stage_override"):
        decision = stage_tools.StageDecision.model_validate(vi["stage_override"]) \
            if isinstance(vi["stage_override"], dict) else decision
    stage = decision.stage
    rev = float(profile.metrics.revenue_ttm_aud or 0)
    rsrc = profile.metrics_sources.get("revenue_ttm_aud", "website")

    parsed = (projection or {}).get("parsed") or {}
    checks = (projection or {}).get("checks") or []
    actual_rows, proj_rows, fx_rate = projection_rows_aud(parsed) if parsed else ([], [], 1.0)
    has_proj = bool(proj_rows) and not any(c.get("severity") == "error" for c in checks)
    proj_warn = any(c.get("severity") == "warning" for c in checks)
    last_actual = actual_rows[-1] if actual_rows else None
    ebitda_actual = _ebitda(last_actual) if last_actual else None
    actual_basis = "audited" if parsed.get("audited") else "management_actuals"
    growth = profile.metrics.revenue_growth_yoy_pct if profile.metrics.revenue_growth_yoy_pct else None
    if len(actual_rows) >= 2 and actual_rows[-2]["revenue"]:
        growth = (actual_rows[-1]["revenue"] / actual_rows[-2]["revenue"] - 1) * 100
    if rev <= 0 and last_actual and last_actual["revenue"] > 0:
        rev, rsrc = float(last_actual["revenue"]), actual_basis
    cls, cls_reasons = vm.classify_valuation_class(
        stage=stage, listed=ve.listing is not None, ebitda_last_actual=ebitda_actual, revenue_aud=rev,
        growth_pct=growth, raised_aud=profile.metrics.raised_to_date_aud or None)
    if vi.get("class_override") in CLASSES:
        cls_reasons = [f"class set by a reviewer: {vi['class_override']}", *cls_reasons]
        cls = vi["class_override"]

    country = snap.country_code(profile.country)
    crow = snap.country(country)
    industry = vi.get("industry") if vi.get("industry") in snap.industry_keys() else \
        snap.industry_for_text(f"{profile.sector} {profile.description}")
    irow = snap.industry(industry)
    ind_basis = "industry_table" if snap.data.get("industries_status") == "verified" else "industry_table_uncalibrated"
    dlom = float(asm.get("dlom", p["dlom"]))
    net_debt = (float(parsed.get("debt") or 0) - float(parsed.get("cash") or 0)) * fx_rate if parsed else 0.0
    proj_ev = ["projection_warn" if proj_warn else "projection_ok"]
    proj_meta = {"projection_sha256": (projection or {}).get("sha256"), "projection_based": True}
    methods: list[ValuationMethod] = []

    def ov(name: str) -> dict:
        w = asm.get(f"weights.{name}")
        return {"weight_override": float(w)} if w is not None else {}

    # 1. own market price (v3 rule)
    if ve.anchors:
        a = vm.build("market_anchor", {"anchors": anchors_as_inputs(ve.anchors)}, p, cls)
        if a is not None:
            a.inputs = {**a.inputs, **ov("market_anchor")}
            methods.append(a)
    # 2. revenue x multiple (v3 multiple choice)
    mm = ((market.revenue_multiple_low, market.revenue_multiple_median, market.revenue_multiple_high)
          if market and market.revenue_multiple_median else None)
    mult = choose_multiple(ve.comps, ve.sector_multiples, mm, default_multiples(profile.sector), ve.listing is not None)
    cf = market.company_financials if market else None
    if rev > 0 and base_weight(p, "revenue_multiple", cls) > 0:
        inp = {"revenue_aud": rev, "revenue_source": rsrc, "multiple_source": mult["source"],
               "low_multiple": round(mult["low"], 4), "median_multiple": round(mult["median"], 4),
               "high_multiple": round(mult["high"], 4), "multiples": mult.get("multiples", []),
               "discount": mult.get("discount") or 0.0, "n": mult.get("n", 0), "detail": mult.get("detail", ""),
               "multiple_sources": mult.get("sources", []),
               "revenue_ref": cf.source_url if (rsrc == "cited_source" and cf) else "", **ov("revenue_multiple")}
        m = vm.build("revenue_multiple", inp, p, cls)
        if m is not None:
            methods.append(m)
    # 3. EBITDA multiple (listed peers, DLOM) — needs actual EBITDA
    if ebitda_actual and ebitda_actual > 0 and base_weight(p, "ebitda_multiple", cls) > 0:
        em = float(asm.get("ebitda.multiple", irow["ev_ebitda"]))
        methods.append(vm.build("ebitda_multiple", {
            "ebitda_aud": round(ebitda_actual, 2), "ebitda_year": last_actual["year"],
            "band": [round(em * 0.7, 4), em, round(em * 1.4, 4)], "dlom": dlom, "net_debt_aud": round(net_debt, 2),
            "industry": industry, "detail": f"{irow['label']} listed peers",
            "evidence": [actual_basis, ind_basis], "sources": [snap.data["industries_source"]],
            **ov("ebitda_multiple")}, p, cls))
    # 4. precedent transactions (verified deals, else the cited AU private-business range)
    if base_weight(p, "precedents", cls) > 0:
        deals = [d for d in (vi.get("deals") or []) if d.get("multiple")]
        e_deals = [d for d in deals if d.get("basis") == "ebitda"]
        r_deals = [d for d in deals if d.get("basis") == "revenue"]
        if ebitda_actual and ebitda_actual > 0:
            inp = {"metric_aud": round(ebitda_actual, 2), "basis": "ebitda", "net_debt_aud": round(net_debt, 2),
                   **ov("precedents")}
            if e_deals:
                inp.update(deals=e_deals, evidence=[actual_basis, "deals_3plus" if len(e_deals) >= 3 else "deals_1_2"])
            else:
                key, band = snap.precedent_band(industry, ebitda_actual)
                inp.update(band=list(band), band_key=key, detail=f"Australian private-business range ({key})",
                           evidence=[actual_basis, "sector_cited"],
                           sources=list(snap.data["precedent_bands_sources"]))
            methods.append(vm.build("precedents", inp, p, cls))
        elif r_deals and rev > 0:
            methods.append(vm.build("precedents", {
                "metric_aud": rev, "basis": "revenue", "net_debt_aud": round(net_debt, 2), "deals": r_deals,
                "evidence": [rsrc if rsrc in p["evidence_factors"] else "self_reported",
                             "deals_3plus" if len(r_deals) >= 3 else "deals_1_2"], **ov("precedents")}, p, cls))
    # 5. projection methods
    if has_proj:
        base_rev = float(last_actual["revenue"]) if last_actual else 0.0
        base_nwc = last_actual.get("nwc") if last_actual else None
        pos_ebitda = bool(ebitda_actual and ebitda_actual > 0)
        capm = cls in ("profitable_sme", "listed") or (cls == "growth" and pos_ebitda)
        tax_rate = float(asm.get("dcf.tax_rate", crow["tax_rate"]))
        if capm:
            pre_ev = (ebitda_actual * irow["ev_ebitda"] * (1 - dlom)) if pos_ebitda else \
                (base_rev or proj_rows[0]["revenue"]) * irow["ev_sales"] * (1 - dlom)
            rb = vm.cost_of_capital(
                rf=float(asm.get("dcf.rf", crow["rf"])), beta_u=float(asm.get("dcf.beta_u", irow["beta_u"])),
                erp=float(asm.get("dcf.erp", crow["erp"])), crp=float(asm.get("dcf.crp", crow["crp"])),
                size_premium=float(asm.get("dcf.size_premium", snap.size_premium(pre_ev))), tax_rate=tax_rate)
            rb.update(country=country, industry=industry, basis="CAPM: rf + beta x ERP + country + size premium")
            rate_kind = "capm"
        else:
            r0 = float(asm.get("dcf.rate", p["startup_discount_rates"].get(cls, 0.40)))
            rb = {"rate": r0, "basis": f"venture discount rate for {cls.replace('_', '-')} (includes illiquidity)"}
            rate_kind = "startup"
        g = float(asm.get("dcf.g", min(p["terminal_g_default"], p["terminal_g_cap"], float(crow["rf"]))))
        key, band = snap.precedent_band(industry, max(ebitda_actual or 0, 0))
        exit_m = float(asm.get("dcf.exit_multiple", band[1]))
        common = {"rows": [{k: r[k] for k in ("year", "revenue", "cogs", "opex", "d_and_a", "tax", "capex", "nwc",
                                              "change_nwc")} for r in proj_rows],
                  "base_revenue": base_rev, "base_nwc": base_nwc, "tax_rate": tax_rate, "rate_build": rb,
                  "rate_kind": rate_kind, "terminal": asm.get("dcf.terminal", "gordon"), "g": g,
                  "exit_multiple": exit_m, "net_debt_aud": round(net_debt, 2), "mid_year": True,
                  "nwc_pct": p["nwc_default_pct_of_delta_revenue"], "evidence": list(proj_ev), **proj_meta}
        uploaded = _uploaded_projected(parsed, fx_rate)
        if uploaded != common["rows"] and any(c.get("used_value") is not None for c in checks):
            common["rows_uploaded"] = uploaded
        if base_weight(p, "dcf", cls) > 0:
            methods.append(vm.build("dcf", {**common, **ov("dcf")}, p, cls))
        if base_weight(p, "first_chicago", cls) > 0:
            methods.append(vm.build("first_chicago", {
                **{k: v for k, v in common.items() if k != "rows_uploaded"},
                "scenarios": [list(s) for s in p["first_chicago"]["scenarios"]], **ov("first_chicago")}, p, cls))
        if base_weight(p, "vc_method", cls) > 0:
            k = 1 - (mult.get("discount") or 0.0)
            tm = asm.get("vc.target_multiple")
            targets = list(p["vc_target_multiples"].get(cls, [10.0, 12.5, 15.0]))
            if tm is not None:
                targets = [float(tm) * 0.8, float(tm), float(tm) * 1.2]
            methods.append(vm.build("vc_method", {
                "exit_metric_aud": round(float(proj_rows[-1]["revenue"]), 2), "exit_basis": "revenue",
                "exit_multiple": float(asm.get("vc.exit_multiple", round(mult["median"] * k, 4))),
                "exit_multiple_source": mult["source"],
                "years_to_exit": float(asm.get("vc.years_to_exit", len(proj_rows))),
                "target_multiples": targets, "retention": 1.0,
                "investment_aud": round(float(parsed.get("planned_raise") or 0) * fx_rate, 2),
                "evidence": list(proj_ev), **proj_meta, **ov("vc_method")}, p, cls))
    # 6. startup methods
    sp = stage_tools.profile(stage)
    base_pm = float(asm.get("scorecard.base_pre_money", sp.pre_money_aud[1]))
    sf = vi.get("startup_factors") or {}
    f_basis = vi.get("factors_basis") or ("ai_suggested" if sf else "")
    comp_r = (sf.get("rfs") or {}).get("competition")
    if asm.get("competition") is not None:
        comp_r = {"rating": int(asm["competition"])}
    if base_weight(p, "scorecard", cls) > 0:
        lines: dict[str, dict] = {}
        bases: set[str] = set()
        for key, names in (("team", ("founder_quality",)), ("opportunity", ("market_attractiveness", "market")),
                           ("product", ("product_strength",))):
            sc, b = _dim(dims, *names)
            lines[key] = {"score": sc, "source": f"{names[0]} ({b})"}
            bases.add(b)
        if comp_r is not None:
            lines["competition"] = {"score": 50 + 25 * int(comp_r.get("rating", 0)),
                                    "source": f"competition risk rating ({f_basis or 'human'})"}
            bases.add("human" if asm.get("competition") is not None else f_basis)
        else:
            sc, b = _dim(dims, "moat")
            lines["competition"] = {"score": sc, "source": "moat" if b != "default" else "no rating: neutral 50"}
        if rev > 0:
            sc, b = _dim(dims, "revenue_performance", "traction")
            lines["marketing"] = {"score": sc, "source": f"revenue / traction ({b})"}
        else:
            bk = (sf.get("berkus") or {}).get("strategic_relationships")
            lines["marketing"] = {"score": float(bk["score"]) if bk else 50.0,
                                  "source": "strategic relationships" if bk else "no revenue: neutral 50"}
        runway = float(profile.metrics.runway_months or 0)
        lines["need_investment"] = {"score": min(runway / 24, 1) * 100 if runway > 0 else 50.0,
                                    "source": f"runway {runway:.0f} months" if runway > 0 else "runway unknown: 50"}
        s1, b1 = _dim(dims, "investment_readiness")
        s2, b2 = _dim(dims, "trust_verification")
        lines["other"] = {"score": (s1 + s2) / 2, "source": "readiness + verification"}
        bases |= {b1, b2}
        methods.append(vm.build("scorecard", {
            "stage": stage, "base_pre_money_aud": base_pm,
            "base_source": ("admin assumption" if "scorecard.base_pre_money" in asm
                            else f"AU {stage} pre-money median (tools/stage table {stage_tools.STAGE_TABLE_VERSION})"),
            "lines": lines, "weights": dict(p["scorecard_weights"]),
            "evidence": ["ai_suggested"] if "ai_suggested" in bases else [], **ov("scorecard")}, p, cls))
    if base_weight(p, "berkus", cls) > 0 and (cls != "seed" or rev < p["berkus_revenue_limit_seed_aud"]):
        bk = sf.get("berkus") or {}
        scores, src = {}, {}
        for k in BERKUS_KEYS:
            if k in bk:
                scores[k], src[k] = float(bk[k]["score"]), f_basis or "ai_suggested"
            else:
                scores[k], b = _dim(dims, *DERIVED_BERKUS[k])
                src[k] = f"derived from {DERIVED_BERKUS[k][0]} ({b})"
        for k in BERKUS_KEYS:
            if asm.get(f"berkus.{k}") is not None:
                scores[k], src[k] = float(asm[f"berkus.{k}"]), "human"
        ev_b = ["ai_suggested"] if any(v == "ai_suggested" for v in src.values()) else \
            (["derived"] if not bk else [])
        methods.append(vm.build("berkus", {"scores": scores, "score_basis": src,
                                           "cap_per_factor_aud": float(p["berkus_cap_per_factor_aud"]),
                                           "evidence": ev_b, **ov("berkus")}, p, cls))
    rf_r = dict(sf.get("rfs") or {})
    ratings = {k: int(v["rating"]) for k, v in rf_r.items() if k in RFS_KEYS}
    for k in RFS_KEYS:
        if asm.get(f"rfs.{k}") is not None:
            ratings[k] = int(asm[f"rfs.{k}"])
    if base_weight(p, "rfs", cls) > 0 and ratings:
        methods.append(vm.build("rfs", {"base_pre_money_aud": base_pm, "ratings": ratings,
                                        "step_ratio": float(p["rfs_step_ratio"]),
                                        "evidence": ["ai_suggested"] if f_basis == "ai_suggested" and not all(
                                            asm.get(f"rfs.{k}") is not None for k in ratings) else [],
                                        **ov("rfs")}, p, cls))
    # 7. v3 stage benchmark (fallback / cross-check)
    if base_weight(p, "stage_scorecard", cls) > 0 or cls == "idea" and not any(
            m.method == "scorecard" for m in methods):
        bench = stage_ranges.get(stage) or stage_ranges.get("seed")
        methods.append(vm.build("stage_scorecard", {"stage": stage, "benchmark": list(bench),
                                                    "svi_factor": round(0.5 + svi_index / 100, 4)}, p, cls))

    methods = [m for m in methods if m is not None]
    methods.sort(key=lambda m: ORDER.index(m.method))
    tri = blend_v5(methods, cls, p, listed=ve.listing is not None, as_of=ve.as_of or as_of)
    if ve.listing:
        tri.listing = f"{ve.listing.exchange}: {ve.listing.ticker}"
    tri.params_version = params_version
    tri.market_dataset = dataset
    tri.stage = {**decision.model_dump(), "valuation_class": cls, "class_reasons": cls_reasons,
                 "industry": industry, "industry_label": irow["label"], "country": country,
                 "market_dataset_sha256": snap.sha256}
    tri.football_field = football_field(tri.methods)
    if any(m.method in PROJECTION_METHODS for m in methods):
        rest = [x for x in (vm.build(m.method, copy.deepcopy(m.inputs), p, cls) for m in methods
                            if m.method not in PROJECTION_METHODS) if x is not None]
        wp = blend_v5(rest, cls, p, listed=ve.listing is not None) if rest else None
        tri.without_projections = ({"value_aud": round(wp.value_aud, -3), "low_aud": round(wp.low_aud, -3),
                                    "high_aud": round(wp.high_aud, -3)} if wp and wp.value_aud > 0 else None)
        tri.projections = {"sha256": (projection or {}).get("sha256"),
                           "attested_by": (projection or {}).get("attested_by"),
                           "attested_at": (projection or {}).get("attested_at"), "label": PROJECTION_LABEL,
                           "warnings": sum(1 for c in checks if c.get("severity") == "warning")}
    shares_fd = parsed.get("shares_fd") if parsed else None
    tri.tokenisation = tokenisation_proposal(tri.value_aud, tri.low_aud, tri.high_aud, stage, shares_fd=shares_fd,
                                             planned_raise=float(parsed.get("planned_raise") or 0) * fx_rate
                                             if parsed else 0.0, p=p)
    return tri


def current_assumptions(tri: dict) -> dict[str, Any]:
    """The editable assumption values a v5 triangulation actually used (admin editor)."""
    out: dict[str, Any] = {"valuation_class": tri.get("valuation_class"),
                           "stage": (tri.get("stage") or {}).get("stage"),
                           "industry": (tri.get("stage") or {}).get("industry")}
    for m in tri.get("methods") or []:
        inp = m.get("inputs") or {}
        if m.get("method") == "dcf":
            rb = inp.get("rate_build") or {}
            out.update({f"dcf.{k}": rb.get(k) for k in ("rf", "beta_u", "erp", "crp", "size_premium") if k in rb})
            out.update({"dcf.tax_rate": inp.get("tax_rate"), "dcf.g": inp.get("g"), "dcf.terminal": inp.get("terminal"),
                        "dcf.exit_multiple": inp.get("exit_multiple")})
        elif m.get("method") == "vc_method":
            out.update({"vc.exit_multiple": inp.get("exit_multiple"), "vc.years_to_exit": inp.get("years_to_exit"),
                        "vc.target_multiple": (inp.get("target_multiples") or [None, None])[1]})
        elif m.get("method") == "scorecard":
            out["scorecard.base_pre_money"] = inp.get("base_pre_money_aud")
        elif m.get("method") == "berkus":
            out.update({f"berkus.{k}": v for k, v in (inp.get("scores") or {}).items()})
        elif m.get("method") == "rfs":
            out.update({f"rfs.{k}": v for k, v in (inp.get("ratings") or {}).items()})
        elif m.get("method") == "ebitda_multiple":
            out["dlom"] = inp.get("dlom")
        if inp.get("weight_override") is not None:
            out[f"weights.{m.get('method')}"] = inp["weight_override"]
    return out
