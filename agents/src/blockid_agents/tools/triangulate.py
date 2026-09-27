"""Valuation v3 — triangulation. Deterministic: the LLM never produces a number here.

Three methods, each built only from verified inputs (every figure quoted verbatim from a stored source, see
agents/market_evidence.py), then blended by evidence quality:

1. market_anchor     the company's own market price: a listed market cap, a priced round's post-money, a secondary
                     sale price, an investor's mark or a press-reported valuation. Newest first; anchors within 3
                     months of the newest are combined (median). Weight = kind weight x recency (older than 24
                     months -> much lower weight; config.ANCHOR_RECENCY).
2. revenue_multiple  revenue (self-reported > website > cited) x a multiple: median of verified comparable
                     companies > verified sector multiples > the market analysis' cited multiple > the uncalibrated
                     default table. Listed-company multiples applied to an unlisted company take the private-company
                     discount (config.PRIVATE_COMPANY_DISCOUNT).
3. stage_scorecard   the SVI stage benchmark x SVI factor (the pre-v3 rule for companies without revenue). Lowest
                     weight when another method exists, ignored when it is far away from them.

Blend: weighted arithmetic mean of the method values; the range is the weighted mean of the method ranges, widened
to at least a confidence-dependent half-width. Confidence (high / medium / low) comes with its reasons.

Every method stores its `inputs`, so `recompute()` rebuilds the blend from a stored report (public /verify page).
"""
from __future__ import annotations

import statistics
from datetime import date

from ..config import (
    ANCHOR_KIND_WEIGHT,
    ANCHOR_RECENCY,
    ANCHOR_UNKNOWN_DATE_FACTOR,
    FX_TO_AUD_AS_OF,
    MARKET_CAP_MAX_AGE_MONTHS,
    MULTIPLE_BOUNDS,
    MULTIPLE_SOURCE_FACTOR,
    PRIVATE_COMPANY_DISCOUNT,
    RANGE_MIN_HALF_WIDTH,
    REVENUE_METHOD_WEIGHT,
    REVENUE_SOURCE_FACTOR,
    STAGE_METHOD_WEIGHT_ALONE,
    STAGE_METHOD_WEIGHT_WITH_OTHERS,
    STAGE_OUTLIER_RATIO,
)
from ..schemas import Anchor, CompMultiple, SectorMultiple, Triangulation, ValuationMethod

VERSION = "v3"
ANCHOR_GROUP_MONTHS = 3  # anchors this close to the newest are combined (median); older ones are shown only
KIND_LABEL = {"market_cap": "market capitalisation", "priced_round": "priced funding round",
              "secondary_sale": "secondary share sale", "investor_mark": "investor mark",
              "reported_valuation": "reported valuation"}
REVENUE_LABEL = {"self_reported": "self-reported ", "cited_source": "cited-source ", "website": ""}


# ------------------------------------------------------------------ dates
def parse_as_of(text: str) -> str:
    """'25 June 2026' / 'June 2026' / '2026-06-25' / 'Q1 2026' / '2024' -> 'YYYY-MM' or 'YYYY' ('' if none)."""
    import re

    t = (text or "").strip()
    m = re.search(r"\b(20\d\d|19\d\d)-(\d\d)(?:-\d\d)?\b", t)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    months = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
    m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?:\d{1,2},?\s+)?(20\d\d|19\d\d)\b",
                  t, re.IGNORECASE)
    if m:
        return f"{m.group(2)}-{months.index(m.group(1).lower()[:3]) + 1:02d}"
    m = re.search(r"\b(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s+(20\d\d|19\d\d)\b",
                  t, re.IGNORECASE)
    if m:
        return f"{m.group(3)}-{months.index(m.group(2).lower()[:3]) + 1:02d}"
    m = re.search(r"\bQ([1-4])\s*(20\d\d)\b", t, re.IGNORECASE)
    if m:
        return f"{m.group(2)}-{int(m.group(1)) * 3 - 1:02d}"  # mid-quarter
    m = re.search(r"\b(20\d\d|19\d\d)\b", t)
    return m.group(1) if m else ""


def age_months(as_of: str, today: date) -> float | None:
    """Months between an 'YYYY-MM' / 'YYYY' date and `today` (a bare year counts from its middle, July)."""
    if not as_of:
        return None
    parts = as_of.split("-")
    try:
        y, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 7
    except ValueError:
        return None
    months = (today.year - y) * 12 + (today.month - m)
    return float(max(months, 0)) if months >= -1 else None  # a future date is not a valid anchor date


def recency_factor(age: float | None) -> float:
    if age is None:
        return ANCHOR_UNKNOWN_DATE_FACTOR
    return next(f for limit, f in ANCHOR_RECENCY if age <= limit)


# ------------------------------------------------------------------ method 1: market anchors
def effective_kind(kind: str, age: float | None) -> str:
    if kind == "market_cap" and (age is None or age > MARKET_CAP_MAX_AGE_MONTHS):
        return "reported_valuation"  # a stale market cap is just a historical value
    return kind


def anchor_method(anchors: list[dict]) -> ValuationMethod | None:
    """anchors: [{kind, amount_aud, age_months, source_url?, as_of?, amount?, currency?, fx_rate_to_aud?}]."""
    rows = [dict(a, kind=effective_kind(a["kind"], a.get("age_months"))) for a in anchors if a.get("amount_aud")]
    if not rows:
        return None
    fresh_caps = [a for a in rows if a["kind"] == "market_cap"]
    if fresh_caps:  # listed: today's market cap is the market price
        group = fresh_caps
    else:
        rows.sort(key=lambda a: (a.get("age_months") is None, a.get("age_months") or 0,
                                 -ANCHOR_KIND_WEIGHT.get(a["kind"], 0.5)))
        newest = rows[0].get("age_months")
        group = [a for a in rows if newest is None and a is rows[0]
                 or newest is not None and a.get("age_months") is not None
                 and a["age_months"] - newest <= ANCHOR_GROUP_MONTHS]
    group = _dedupe(group)
    values = sorted(a["amount_aud"] for a in group)
    value = statistics.median(values)
    lead = group[0]
    age = lead.get("age_months")
    raw = max(ANCHOR_KIND_WEIGHT.get(a["kind"], 0.5) * recency_factor(a.get("age_months")) for a in group)
    half = 0.10 if (age is not None and age <= 12) else 0.20 if (age is not None and age <= 24) else 0.30
    if lead["kind"] == "market_cap":
        half = 0.10
    low, high = min(values[0], value * (1 - half)), max(values[-1], value * (1 + half))
    notes = []
    if age is None:
        notes.append("the source gives no date for this valuation: weight reduced")
    elif age > 24:
        notes.append(f"latest valuation is {age:.0f} months old: weight reduced")
    unused = [a for a in rows if a not in group]
    if unused:
        notes.append(f"{len(unused)} older valuation(s) shown but not used")
    label = f"{KIND_LABEL.get(lead['kind'], lead['kind'])}" + (f" ({lead.get('as_of')})" if lead.get("as_of") else "")
    if len(group) > 1:
        label = f"median of {len(group)} recent valuations"
    return ValuationMethod(
        method="market_anchor", label=label, value_aud=value, low_aud=low, high_aud=high, raw_weight=round(raw, 4),
        inputs={"anchors": [{k: a.get(k) for k in ("kind", "amount", "currency", "amount_aud", "fx_rate_to_aud",
                                                   "as_of", "age_months", "source_url")} for a in group],
                "rule": "median of anchors within 3 months of the newest; listed market cap wins when fresh",
                "half_width": half},
        sources=list(dict.fromkeys(a["source_url"] for a in group if a.get("source_url"))),
        notes=notes)


def _dedupe(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for a in rows:
        if not any(abs(a["amount_aud"] - b["amount_aud"]) <= 0.02 * b["amount_aud"] and a.get("kind") == b.get("kind")
                   for b in out):
            out.append(a)
    return out


def anchors_as_inputs(anchors: list[Anchor]) -> list[dict]:
    return [a.model_dump() for a in anchors]


# ------------------------------------------------------------------ method 2: revenue x multiple
def choose_multiple(comps: list[CompMultiple], sectors: list[SectorMultiple], market_multiples: tuple | None,
                    default: tuple[str, tuple[float, float, float]], listed: bool) -> dict:
    """{source, low, median, high, discount, n, sources[], detail}. Order: comps > sector > market analysis > default."""
    lo_b, hi_b = MULTIPLE_BOUNDS
    comps = [c for c in comps if lo_b <= c.multiple <= hi_b]
    sectors = [s for s in sectors if lo_b <= s.multiple <= hi_b]
    if comps:
        ms = sorted(c.multiple for c in comps)
        med = statistics.median(ms)
        public_share = sum(c.public for c in comps) / len(comps)
        return {"source": "comps_3plus" if len(comps) >= 3 else "comps_1_2", "median": med,
                "low": max(ms[0], med * 0.6) if len(ms) > 1 else med * 0.7,
                "high": min(ms[-1], med * 1.6) if len(ms) > 1 else med * 1.4,
                "discount": PRIVATE_COMPANY_DISCOUNT if (public_share >= 0.5 and not listed) else 0.0,
                "n": len(comps), "multiples": ms, "sources": list(dict.fromkeys(c.source_url for c in comps)),
                "detail": "median of comparable companies: " + ", ".join(f"{c.name} {c.multiple:g}x" for c in comps)}
    if sectors:
        ms = sorted(s.multiple for s in sectors)
        med = statistics.median(ms)
        public_share = sum(s.public for s in sectors) / len(sectors)
        return {"source": "sector_cited", "median": med,
                "low": min(ms[0], med * 0.7), "high": max(ms[-1], med * 1.4),
                "discount": PRIVATE_COMPANY_DISCOUNT if (public_share >= 0.5 and not listed) else 0.0,
                "n": len(sectors), "multiples": ms, "sources": list(dict.fromkeys(s.source_url for s in sectors)),
                "detail": "sector multiple(s) stated in sources: " + ", ".join(f"{s.multiple:g}x" for s in sectors)}
    if market_multiples and market_multiples[1]:
        lo, med, hi = market_multiples
        lo, hi = lo or med * 0.6, hi or med * 1.5
        if lo >= med * 0.95 or hi <= med * 1.05:
            lo, hi = min(lo, med * 0.7), max(hi, med * 1.4)
        return {"source": "market_analysis", "median": med, "low": lo, "high": hi, "discount": 0.0, "n": 1,
                "multiples": [med], "sources": [], "detail": "multiple reported by the cited market analysis"}
    key, (lo, med, hi) = default
    return {"source": "default", "median": med, "low": lo, "high": hi, "discount": 0.0, "n": 0, "multiples": [],
            "sources": [], "detail": f"uncalibrated default table ({key}): no multiple found in the sources"}


def revenue_method(revenue_aud: float, revenue_source: str, mult: dict,
                   revenue_ref: str = "") -> ValuationMethod | None:
    if not revenue_aud or revenue_aud <= 0:
        return None
    d = mult.get("discount") or 0.0
    k = 1 - d
    raw = REVENUE_METHOD_WEIGHT * MULTIPLE_SOURCE_FACTOR[mult["source"]] * REVENUE_SOURCE_FACTOR.get(revenue_source, 0.8)
    label = (f"{REVENUE_LABEL.get(revenue_source, '')}revenue multiple ({mult['low']:.1f}x / {mult['median']:.1f}x / "
             f"{mult['high']:.1f}x, {mult['detail']}" + (f"; private-company discount {d:.0%}" if d else "") + ")")
    notes = []
    if mult["source"] == "default":
        notes.append("multiple is a default, not cited")
    if revenue_source == "self_reported":
        notes.append("revenue is self-reported, not independently verified")
    return ValuationMethod(
        method="revenue_multiple", label=label, value_aud=revenue_aud * mult["median"] * k,
        low_aud=revenue_aud * mult["low"] * k, high_aud=revenue_aud * mult["high"] * k, raw_weight=round(raw, 4),
        inputs={"revenue_aud": revenue_aud, "revenue_source": revenue_source, "multiple_source": mult["source"],
                "low_multiple": round(mult["low"], 4), "median_multiple": round(mult["median"], 4),
                "high_multiple": round(mult["high"], 4), "multiples": mult.get("multiples", []),
                "discount": d, "n": mult.get("n", 0)},
        sources=list(dict.fromkeys([*([revenue_ref] if revenue_ref else []), *mult.get("sources", [])])),
        notes=notes)


# ------------------------------------------------------------------ method 3: stage / scorecard
def stage_method(stage: str, benchmark: tuple[float, float, float], svi_factor: float) -> ValuationMethod:
    lo, mid, hi = benchmark
    return ValuationMethod(
        method="stage_scorecard", label=f"stage benchmark ({stage}) x quality score factor {svi_factor:.2f}",
        value_aud=mid * svi_factor, low_aud=lo * svi_factor, high_aud=hi * svi_factor, raw_weight=0.0,
        inputs={"stage": stage, "benchmark": list(benchmark), "svi_factor": round(svi_factor, 4)},
        notes=["placeholder stage calibration"])


# ------------------------------------------------------------------ blend + confidence
def blend(methods: list[ValuationMethod], *, listed: bool = False, as_of: str = "",
          fx_as_of: str = FX_TO_AUD_AS_OF) -> Triangulation:
    anchor = next((m for m in methods if m.method == "market_anchor"), None)
    rev = next((m for m in methods if m.method == "revenue_multiple"), None)
    stage = next((m for m in methods if m.method == "stage_scorecard"), None)
    others = [m for m in (anchor, rev) if m is not None and m.raw_weight > 0]
    if stage is not None:
        if not others:
            stage.raw_weight = STAGE_METHOD_WEIGHT_ALONE
        else:
            ref = sum(m.raw_weight * m.value_aud for m in others) / sum(m.raw_weight for m in others)
            ratio = max(stage.value_aud, ref) / max(min(stage.value_aud, ref), 1.0)
            if ratio > STAGE_OUTLIER_RATIO:
                stage.raw_weight = 0.0
                stage.notes = [*stage.notes, f"not used: {ratio:.0f}x away from the market-based methods"]
            else:
                stage.raw_weight = STAGE_METHOD_WEIGHT_WITH_OTHERS
    used = [m for m in methods if m.raw_weight > 0]
    total = sum(m.raw_weight for m in used)
    for m in methods:
        m.weight = round(m.raw_weight / total, 4) if total and m.raw_weight > 0 else 0.0
    value = sum(m.weight * m.value_aud for m in used)
    low = sum(m.weight * m.low_aud for m in used)
    high = sum(m.weight * m.high_aud for m in used)
    conf, reasons = confidence(anchor, rev, stage, listed)
    half = RANGE_MIN_HALF_WIDTH[conf]
    low, high = min(low, value * (1 - half)), max(high, value * (1 + half))
    return Triangulation(version=VERSION, value_aud=value, low_aud=low, high_aud=high, confidence=conf,
                         confidence_reasons=reasons, methods=methods, listed=listed, as_of=as_of, fx_as_of=fx_as_of)


def confidence(anchor: ValuationMethod | None, rev: ValuationMethod | None, stage: ValuationMethod | None,
               listed: bool) -> tuple[str, list[str]]:
    reasons: list[str] = []
    a_age, kind = None, None
    if anchor is not None:
        lead = (anchor.inputs.get("anchors") or [{}])[0]
        a_age = lead.get("age_months")
        kind = lead.get("kind")
        if kind == "market_cap":
            reasons.append("listed company: current market capitalisation found and verified in a source")
        elif a_age is None:
            reasons.append("the company's own valuation was found, but the source gives no date")
        else:
            reasons.append(f"the company's own {KIND_LABEL.get(kind, 'valuation')} was found and verified "
                           f"({a_age:.0f} months old)")
    else:
        reasons.append("no verified valuation, funding round or market cap of the company itself was found")
    if rev is not None:
        src = rev.inputs.get("multiple_source")
        reasons.append({"comps_3plus": f"revenue multiple from {rev.inputs.get('n')} comparable companies",
                        "comps_1_2": f"revenue multiple from only {rev.inputs.get('n')} comparable company(ies)",
                        "sector_cited": "revenue multiple from a sector figure stated in a source",
                        "market_analysis": "revenue multiple reported by the market analysis (not quote-checked)",
                        "default": "revenue multiple is an uncalibrated default"}[src])
    elif stage is not None and stage.raw_weight > 0:
        reasons.append("no revenue figure: the stage benchmark carries the value")
    disagree = False
    if anchor is not None and rev is not None and anchor.raw_weight > 0 and rev.raw_weight > 0:
        ratio = max(anchor.value_aud, rev.value_aud) / max(min(anchor.value_aud, rev.value_aud), 1.0)
        disagree = ratio > 2.0
        reasons.append(f"methods {'disagree' if disagree else 'agree'} (x{ratio:.1f} apart)")

    if anchor is not None and kind == "market_cap" and anchor.weight >= 0.5:
        return "high", reasons  # a current market cap is the market price; other methods only frame it
    fresh_anchor = anchor is not None and a_age is not None and a_age <= 24
    if fresh_anchor and (anchor.weight >= 0.5 or listed) and not disagree:
        return "high", reasons
    good_rev = rev is not None and rev.inputs.get("multiple_source") in ("comps_3plus", "comps_1_2", "sector_cited")
    if anchor is not None or good_rev:
        return "medium", reasons
    return "low", reasons


def headline_method(tri: Triangulation, legacy: str = "") -> str:
    used = sorted((m for m in tri.methods if m.weight > 0), key=lambda m: -m.weight)
    if len(used) == 1:
        return f"{used[0].label} (confidence {tri.confidence})"
    parts = " + ".join(f"{m.label} [{m.weight:.0%}]" for m in used)
    return f"blend of {len(used)} methods: {parts} (confidence {tri.confidence})"


# ------------------------------------------------------------------ public entry points
def triangulate(*, anchors: list[Anchor], listed: bool, revenue_aud: float, revenue_source: str, revenue_ref: str,
                comps: list[CompMultiple], sectors: list[SectorMultiple], market_multiples: tuple | None,
                default: tuple[str, tuple[float, float, float]], stage: str,
                stage_benchmark: tuple[float, float, float], svi_factor: float, as_of: str) -> Triangulation:
    methods: list[ValuationMethod] = []
    a = anchor_method(anchors_as_inputs(anchors))
    if a is not None:
        methods.append(a)
    r = revenue_method(revenue_aud, revenue_source, choose_multiple(comps, sectors, market_multiples, default, listed),
                       revenue_ref)
    if r is not None:
        methods.append(r)
    methods.append(stage_method(stage, stage_benchmark, svi_factor))
    return blend(methods, listed=listed, as_of=as_of)


def recompute(tri: dict) -> dict:
    """Rebuild every method from its stored inputs and blend again (used by the public verifier).
    Returns {low, mid, high, confidence}. Valuation v5 reports (version "v5") are rebuilt by tools/valuation_v5."""
    if (tri or {}).get("version") == "v5":
        from .valuation_v5 import recompute_v5

        return recompute_v5(tri)
    methods: list[ValuationMethod] = []
    listed = bool((tri or {}).get("listed"))
    for m in (tri or {}).get("methods") or []:
        inp = m.get("inputs") or {}
        if m.get("method") == "market_anchor":
            a = anchor_method(inp.get("anchors") or [])
            if a:
                methods.append(a)
        elif m.get("method") == "revenue_multiple":
            mult = {"source": inp.get("multiple_source", "default"), "median": float(inp.get("median_multiple") or 0),
                    "low": float(inp.get("low_multiple") or 0), "high": float(inp.get("high_multiple") or 0),
                    "discount": float(inp.get("discount") or 0), "n": inp.get("n", 0), "detail": "",
                    "multiples": inp.get("multiples") or []}
            r = revenue_method(float(inp.get("revenue_aud") or 0), inp.get("revenue_source", ""), mult)
            if r:
                methods.append(r)
        elif m.get("method") == "stage_scorecard":
            b = inp.get("benchmark") or [0, 0, 0]
            methods.append(stage_method(inp.get("stage", ""), (b[0], b[1], b[2]), float(inp.get("svi_factor") or 0)))
    t = blend(methods, listed=listed, as_of=(tri or {}).get("as_of", ""))
    return {"low": round(t.low_aud, -3), "mid": round(t.value_aud, -3), "high": round(t.high_aud, -3),
            "confidence": t.confidence}
