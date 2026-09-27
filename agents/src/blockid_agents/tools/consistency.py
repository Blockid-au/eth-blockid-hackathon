"""Anti-gaming / consistency checks (evaluation v5, docs/PLAN-EVALUATION-V5.md §4.4). Deterministic, no I/O.

resolve(candidates, stage, lookups) takes every value we have for each metric, from every source, and returns the one
value used for scoring per metric plus ConsistencyFlags:

* cross-source: typed vs CSV vs deck vs site vs cited vs KPI. A typed value that matches an uploaded document / CSV
  within 5 % is promoted to L2 ("document-backed"); a > 20 % gap flags "figures do not match" and the LOWER value is
  used unless the higher one is L3+.
* internal arithmetic: ARR ≈ 12 × MRR (±10 %), customers × ARPA × 12 ≈ revenue (±30 %), growth from two points vs the
  typed growth %, runway ≈ cash ÷ burn, NRR ≥ GRR, GRR ≤ 100 %.
* plausibility by stage (tools/stage.PLAUSIBILITY): the value is capped at the stage top decile for scoring.
* public contradiction: ≥ 1M claimed users with no Tranco rank and < 50 app ratings.
* concentration: top customer > 20 % warning, > 50 % high (evaluation caps T3 at 50).
* ARR hygiene: "run rate" quotes are not ARR.
Flags never change a number silently: each one says what was done (action lower_used / capped / review).
"""
from __future__ import annotations

from ..schemas import ConsistencyFlag, MetricValue
from . import metrics_calc as mc
from . import stage as stage_tools

# level by source when nothing upgrades it (§4.2)
SOURCE_LEVEL = {"self_reported": 1, "deck": 1, "site": 1, "csv": 2, "cited": 3, "kpi": 3, "registry": 3,
                "lookup": 3, "connector": 4, "computed": 1, "competitors": 3, "": 1}
DOC_SOURCES = ("csv", "deck", "kpi", "connector")
MATCH_TOL = 0.05
GAP_TOL = 0.20
RUN_RATE_WORDS = ("run rate", "run-rate", "runrate", "annualised run", "annualized run")


def _f(code: str, severity: str, message: str, metrics: list[str], action: str = "") -> ConsistencyFlag:
    return ConsistencyFlag(code=code, severity=severity, message=message, metrics=metrics, action=action)


def _fmt(metric: str, v: float | None) -> str:
    if v is None:
        return "—"
    if metric.endswith("_aud"):
        return f"A${v:,.0f}"
    if metric.endswith("_pct"):
        return f"{v:.1f}%"
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def arr_hygiene(candidates: dict[str, list[MetricValue]]) -> list[ConsistencyFlag]:
    """ARR claims whose quote says 'run rate' become revenue_run_rate_aud (shown, never used as ARR)."""
    flags = []
    keep, moved = [], []
    for mv in candidates.get("arr_aud", []):
        (moved if any(w in (mv.quote or "").lower() for w in RUN_RATE_WORDS) else keep).append(mv)
    if moved:
        candidates["arr_aud"] = keep
        candidates.setdefault("revenue_run_rate_aud", []).extend(moved)
        flags.append(_f("arr_run_rate", "warning", "a quoted 'run rate' is revenue run-rate, not ARR: not used as ARR",
                        ["arr_aud"], "review"))
    return flags


def pick(metric: str, cands: list[MetricValue]) -> tuple[MetricValue | None, list[ConsistencyFlag]]:
    """One value per metric from all sources (rules in the module docstring)."""
    cands = [c for c in cands if c is not None and c.value is not None]
    if not cands:
        return None, []
    flags: list[ConsistencyFlag] = []
    for c in cands:
        if not c.level:
            c.level = SOURCE_LEVEL.get(c.source, 1)
    typed = [c for c in cands if c.source == "self_reported"]
    docs = [c for c in cands if c.source in DOC_SOURCES]
    for t in typed:  # typed backed by a document within 5 % -> L2
        if any(mc.within(t.value, d.value, MATCH_TOL) for d in docs):
            t.level = max(t.level, 2)
            t.note = (t.note + "; " if t.note else "") + "matches an uploaded document"
    best = max(cands, key=lambda c: (c.level, c.source != "self_reported"))
    lo = min(cands, key=lambda c: c.value)
    hi = max(cands, key=lambda c: c.value)
    lower_better = metric in stage_tools.LOWER_IS_BETTER
    if len(cands) > 1 and mc.within(lo.value, hi.value, GAP_TOL) is False:
        # the conservative value: lower for "higher is better", higher for "lower is better"
        cons, opt = (hi, lo) if lower_better else (lo, hi)
        chosen = opt if opt.level >= 3 and opt.level > cons.level else cons
        flags.append(_f("cross_source_gap", "warning",
                        f"figures do not match for {metric}: {_fmt(metric, lo.value)} ({lo.source or 'unknown'}) vs "
                        f"{_fmt(metric, hi.value)} ({hi.source or 'unknown'}); using {_fmt(metric, chosen.value)}",
                        [metric], "lower_used"))
        return chosen.model_copy(), flags
    return best.model_copy(), flags


def resolve(candidates: dict[str, list[MetricValue]], stage: str, lookups: dict | None = None,
            sector_key: str = "saas") -> tuple[dict[str, MetricValue], list[ConsistencyFlag]]:
    cands = {k: [c.model_copy() for c in v] for k, v in (candidates or {}).items()}
    flags = arr_hygiene(cands)
    out: dict[str, MetricValue] = {}
    for metric, lst in cands.items():
        mv, fl = pick(metric, lst)
        flags += fl
        if mv is not None:
            out[metric] = mv
    flags += arithmetic(out)
    flags += plausibility(out, stage)
    flags += public_contradiction(out, lookups or {})
    flags += concentration(out)
    return out, flags


def _v(out: dict[str, MetricValue], k: str) -> float | None:
    mv = out.get(k)
    return mv.value if mv is not None else None


def arithmetic(out: dict[str, MetricValue]) -> list[ConsistencyFlag]:
    flags = []
    arr, mrr = _v(out, "arr_aud"), _v(out, "mrr_aud")
    if mc.within(arr, (mrr or 0) * 12 if mrr is not None else None, 0.10) is False:
        flags.append(_f("arr_vs_mrr", "warning", f"ARR {_fmt('arr_aud', arr)} is not 12 × MRR "
                        f"({_fmt('mrr_aud', mrr)})", ["arr_aud", "mrr_aud"], "review"))
    cust, arpa, rev = _v(out, "paying_customers"), _v(out, "arpa_monthly_aud"), _v(out, "revenue_ttm_aud") or arr
    if cust and arpa and rev and mc.within(cust * arpa * 12, rev, 0.30) is False:
        flags.append(_f("customers_x_arpa", "warning", f"customers × ARPA × 12 = {_fmt('revenue_aud', cust * arpa * 12)}"
                        f" does not match revenue {_fmt('revenue_aud', rev)}",
                        ["paying_customers", "arpa_monthly_aud", "revenue_ttm_aud"], "review"))
    typed_g = out.get("revenue_growth_yoy_pct")
    two_pt = mc.growth_pct(_v(out, "revenue_ttm_aud"), _v(out, "revenue_prev_ttm_aud"))
    if typed_g is not None and two_pt is not None and abs((typed_g.value or 0) - two_pt) > max(10.0,
                                                                                               0.2 * abs(two_pt)):
        flags.append(_f("growth_vs_points", "warning", f"typed growth {typed_g.value:.0f}% but the two revenue figures "
                        f"give {two_pt:.0f}%: the computed value is used", ["yoy_growth_pct"], "lower_used"))
    rw, cash, burn = _v(out, "runway_months"), _v(out, "cash_aud"), _v(out, "burn_monthly_aud")
    calc = mc.runway_months(cash, burn)
    if rw is not None and calc is not None and calc < 60 and mc.within(rw, calc, 0.25) is False:
        flags.append(_f("runway_vs_cash", "warning", f"runway {rw:.0f} months but cash ÷ burn = {calc:.0f} months",
                        ["runway_months"], "lower_used"))
        out["runway_months"] = out["runway_months"].model_copy(update={"value": min(rw, calc)})
    nrr, grr = _v(out, "nrr_pct"), _v(out, "grr_pct")
    if nrr is not None and grr is not None and nrr < grr:
        flags.append(_f("nrr_below_grr", "warning", f"NRR {nrr:.0f}% is below GRR {grr:.0f}% (impossible)",
                        ["nrr_pct", "grr_pct"], "review"))
    if grr is not None and grr > 100:
        flags.append(_f("grr_over_100", "high", f"GRR {grr:.0f}% is above 100% (impossible): capped at 100",
                        ["grr_pct"], "capped"))
        out["grr_pct"] = out["grr_pct"].model_copy(update={"value": 100.0})
    churn = _v(out, "logo_churn_monthly_pct")
    if churn is not None and grr is not None:
        implied = mc.annual_logo_retention_from_monthly_churn(churn)
        if implied is not None and grr > 0 and implied > grr + 25:
            flags.append(_f("churn_vs_grr", "info", f"monthly logo churn {churn:.1f}% implies {implied:.0f}% annual "
                            f"logo retention, far above GRR {grr:.0f}%", ["logo_churn_monthly_pct", "grr_pct"]))
    return flags


def plausibility(out: dict[str, MetricValue], stage: str) -> list[ConsistencyFlag]:
    flags = []
    caps = stage_tools.profile(stage).plausibility
    for metric, cap in caps.items():
        mv = out.get(metric)
        if mv is None or mv.value is None or mv.value <= cap:
            continue
        b = stage_tools.benchmark(stage, metric)
        top = b[3] if b else cap
        flags.append(_f("implausible", "high", f"{metric} {_fmt(metric, mv.value)} is above the plausible bound for "
                        f"{stage} ({_fmt(metric, cap)}): scored as the stage top decile ({_fmt(metric, top)}) until an "
                        f"admin confirms", [metric], "capped"))
        out[metric] = mv.model_copy(update={"value": top, "note": (mv.note + "; " if mv.note else "")
                                            + f"capped from {_fmt(metric, mv.value)}"})
    gm = out.get("gross_margin_pct")
    return flags + ([_f("gross_margin_high", "info", "gross margin above 95% is unusual outside software",
                        ["gross_margin_pct"])] if gm is not None and (gm.value or 0) > 95 else [])


def public_contradiction(out: dict[str, MetricValue], lookups: dict) -> list[ConsistencyFlag]:
    users = _v(out, "active_users_monthly")
    if not users or users < 1_000_000:
        return []
    tranco = (lookups.get("tranco") or {}).get("rank")
    ratings = (lookups.get("app_store") or {}).get("rating_count")
    if tranco is None and (ratings is None or ratings < 50):
        return [_f("public_contradiction", "high", f"{users:,.0f} monthly users claimed, but the site is not in the "
                   "Tranco top-1M and the app has fewer than 50 ratings", ["active_users_monthly"], "review")]
    return []


def concentration(out: dict[str, MetricValue]) -> list[ConsistencyFlag]:
    share = _v(out, "top_customer_share_pct")
    if share is None:
        return []
    if share > 50:
        return [_f("concentration_high", "high", f"one customer is {share:.0f}% of revenue (customer base score "
                   "capped at 50)", ["top_customer_share_pct"], "capped")]
    if share > 20:
        return [_f("concentration", "warning", f"top customer is {share:.0f}% of revenue", ["top_customer_share_pct"])]
    return []


def stability(prev_index: float | None, new_index: float, typed_only: bool) -> ConsistencyFlag | None:
    """A re-score that raises the index > 15 points from typed numbers alone needs admin review."""
    if prev_index is not None and typed_only and new_index - prev_index > 15:
        return _f("rescore_jump", "high", f"the score rose {new_index - prev_index:.1f} points from typed figures "
                  "alone: admin review required", [], "review")
    return None
