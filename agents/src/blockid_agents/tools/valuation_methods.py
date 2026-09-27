"""Valuation v5 — standard valuation methods as pure, deterministic functions (docs/PLAN-VALUATION-V5.md §2, §4).

No I/O, no LLM, no clock. Floats in A$; rounding only at the very end (the blend rounds to A$1,000 like v3).

Two layers:
  * maths helpers  — cost_of_capital, fcff_series, discount, dcf_core, sensitivity, dcf_checks, percentile,
                     weighted_median, first_chicago_values, vc_post_money ... (unit-tested against known answers and
                     numpy-financial as an oracle)
  * method builders — build_<method>(inputs, p, cls) -> ValuationMethod. `inputs` is exactly what gets stored in the
                     report; /verify rebuilds every method by calling the same builder on the stored inputs
                     (METHOD_BUILDERS, used by tools/valuation_v5.recompute_v5). `p` = valuation_params.PARAMS[v].

Methodology credits: the DCF guard rules (terminal growth below the discount rate, a CAPM rate band of 5-20 %, the
terminal-value share warning, a sensitivity grid centred on the base case, mid-year convention) and the quartile
statistics for comparables follow the Anthropic financial-services skills `dcf-model` / `comps-analysis`
(github.com/anthropics/financial-services, Apache-2.0, commit 574ed36) — rules re-implemented here, no code copied.
Startup methods: Scorecard (Payne 2001), Berkus, Risk Factor Summation (Ohio TechAngels), VC method, First Chicago.
"""
from __future__ import annotations

import math
from typing import Any

from ..schemas import Check, ValuationMethod
from .valuation_params import (
    BERKUS_KEYS,
    RFS_KEYS,
    base_weight,
    evidence_factor,
)

# ================================================================== maths helpers (pure)


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolation percentile (Excel PERCENTILE.INC / numpy 'linear'); q in [0, 1]."""
    xs = sorted(float(v) for v in values)
    if not xs:
        raise ValueError("percentile of an empty list")
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q
    lo = math.floor(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def weighted_median(pairs: list[tuple[float, float]]) -> float:
    """(value, weight) pairs -> the value where the cumulative weight first reaches half (ties: mean of the two)."""
    rows = sorted((float(v), float(w)) for v, w in pairs if w > 0)
    if not rows:
        raise ValueError("weighted median of nothing")
    total = sum(w for _, w in rows)
    acc = 0.0
    for i, (v, w) in enumerate(rows):
        acc += w
        if abs(acc - total / 2) < 1e-12 and i + 1 < len(rows):
            return (v + rows[i + 1][0]) / 2
        if acc > total / 2:
            return v
    return rows[-1][0]


def cost_of_capital(*, rf: float, beta_u: float, erp: float, crp: float = 0.0, size_premium: float = 0.0,
                    tax_rate: float = 0.25, debt_to_equity: float = 0.0, kd_pre_tax: float | None = None) -> dict:
    """CAPM cost of equity (+ country and size premiums) and WACC. No debt -> WACC = Ke.
    beta_L = beta_U x (1 + (1 - t) x D/E) (Hamada)."""
    beta_l = beta_u * (1 + (1 - tax_rate) * debt_to_equity)
    ke = rf + beta_l * erp + crp + size_premium
    if debt_to_equity > 0 and kd_pre_tax is not None:
        e_share = 1 / (1 + debt_to_equity)
        rate = e_share * ke + (1 - e_share) * kd_pre_tax * (1 - tax_rate)
    else:
        rate = ke
    return {"rf": rf, "beta_u": beta_u, "beta_l": round(beta_l, 6), "erp": erp, "crp": crp,
            "size_premium": size_premium, "tax_rate": tax_rate, "debt_to_equity": debt_to_equity,
            "kd_pre_tax": kd_pre_tax, "ke": round(ke, 6), "rate": round(rate, 6)}


def fcff_series(rows: list[dict], *, tax_rate: float, base_revenue: float, base_nwc: float | None = None,
                nwc_pct: float = 0.10) -> list[dict]:
    """FCFF = EBIT - tax + D&A - capex - change in NWC, per projected year.
    tax: the row's `tax` if given, else max(EBIT, 0) x tax_rate. Change in NWC: `change_nwc` if given, else the
    difference of `nwc` balances (when the previous balance is known), else nwc_pct x change in revenue."""
    out: list[dict] = []
    prev_rev, prev_nwc = base_revenue, base_nwc
    for r in rows:
        rev = float(r["revenue"])
        ebitda = rev - float(r["cogs"]) - float(r["opex"])
        ebit = ebitda - float(r["d_and_a"])
        tax = float(r["tax"]) if r.get("tax") is not None else max(ebit, 0.0) * tax_rate
        if r.get("change_nwc") is not None:
            d_nwc = float(r["change_nwc"])
        elif r.get("nwc") is not None and prev_nwc is not None:
            d_nwc = float(r["nwc"]) - prev_nwc
        else:
            d_nwc = nwc_pct * (rev - prev_rev)
        fcff = ebit - tax + float(r["d_and_a"]) - float(r["capex"]) - d_nwc
        out.append({"year": r.get("year"), "revenue": rev, "ebitda": ebitda, "ebit": ebit, "tax": tax,
                    "d_and_a": float(r["d_and_a"]), "capex": float(r["capex"]), "change_nwc": d_nwc, "fcff": fcff})
        prev_rev = rev
        if r.get("nwc") is not None:
            prev_nwc = float(r["nwc"])
        elif prev_nwc is not None:
            prev_nwc = prev_nwc + d_nwc
    return out


def discount(t: float, rate: float) -> float:
    return 1.0 / (1.0 + rate) ** t


def dcf_core(fcff: list[float], rate: float, *, terminal: str, g: float | None = None,
             exit_multiple: float | None = None, final_ebitda: float | None = None, mid_year: bool = True,
             net_debt: float = 0.0) -> dict:
    """EV = sum PV(FCFF) + PV(TV). Mid-year: year t discounted at t - 0.5; Gordon TV at N - 0.5, exit TV at N.
    Raises ValueError when the terminal value cannot be computed (g >= rate, or a missing exit input)."""
    n = len(fcff)
    if n == 0:
        raise ValueError("no projected cash flows")
    if rate <= 0:
        raise ValueError("discount rate must be positive")
    shift = 0.5 if mid_year else 0.0
    pv = [f * discount(t - shift, rate) for t, f in enumerate(fcff, 1)]
    if terminal == "gordon":
        if g is None or g >= rate:
            raise ValueError("terminal growth must be below the discount rate")
        tv = fcff[-1] * (1 + g) / (rate - g)
        pv_tv = tv * discount(n - shift, rate)
    elif terminal == "exit":
        if not exit_multiple or final_ebitda is None:
            raise ValueError("exit multiple terminal value needs a multiple and the final-year EBITDA")
        tv = final_ebitda * exit_multiple
        pv_tv = tv * discount(n, rate)
    else:
        raise ValueError(f"unknown terminal method {terminal!r}")
    ev = sum(pv) + pv_tv
    return {"pv_fcff": sum(pv), "pv_each": pv, "tv": tv, "pv_tv": pv_tv, "ev": ev,
            "tv_share": (pv_tv / ev) if ev > 0 else None, "equity": ev - net_debt}


def sensitivity(fcff: list[float], rate: float, *, terminal: str, g: float | None, exit_multiple: float | None,
                final_ebitda: float | None, net_debt: float, d_rate: float, d_g: float, d_exit: float,
                mid_year: bool = True) -> dict:
    """5 x 5 equity values: rows = rate - 2d .. rate + 2d, columns = g - 2dg .. g + 2dg (or exit multiple).
    The centre cell is the base case. Impossible cells (g >= rate, rate <= 0) are None."""
    rates = [round(rate + d_rate * (i - 2), 6) for i in range(5)]
    if terminal == "gordon":
        cols = [round((g or 0.0) + d_g * (j - 2), 6) for j in range(5)]
    else:
        cols = [round((exit_multiple or 0.0) + d_exit * (j - 2), 6) for j in range(5)]
    grid: list[list[float | None]] = []
    for r in rates:
        row: list[float | None] = []
        for c in cols:
            try:
                if terminal == "gordon":
                    v = dcf_core(fcff, r, terminal="gordon", g=c, net_debt=net_debt, mid_year=mid_year)["equity"]
                else:
                    v = dcf_core(fcff, r, terminal="exit", exit_multiple=c, final_ebitda=final_ebitda,
                                 net_debt=net_debt, mid_year=mid_year)["equity"] if c > 0 else None
            except ValueError:
                v = None
            row.append(None if v is None else round(v, 2))
        grid.append(row)
    key = "gs" if terminal == "gordon" else "exit_multiples"
    return {"rates": rates, key: cols, "values": grid}


def dcf_checks(*, rate: float, rate_kind: str, g: float | None, terminal: str, tv_share: float | None,
               fcff: list[float], p) -> list[Check]:
    """Ported rules (Anthropic dcf-model skill) + BlockID caps."""
    out: list[Check] = []
    if terminal == "gordon" and g is not None and g >= rate:
        out.append(Check(code="g_ge_rate", severity="error",
                         message=f"Terminal growth {g:.1%} is not below the discount rate {rate:.1%}: DCF not used."))
    lo, hi = p["capm_rate_band"]
    if rate_kind == "capm" and not lo <= rate <= hi:
        out.append(Check(code="rate_band", severity="warning",
                         message=f"Discount rate {rate:.1%} is outside the usual 5-20 % band."))
    if rate_kind == "startup" and rate > p["vc_rate_max"]:
        out.append(Check(code="rate_band", severity="warning", message=f"Discount rate {rate:.0%} is very high."))
    if tv_share is not None and tv_share > p["tv_share_warn"]:
        out.append(Check(code="tv_share", severity="warning",
                         message=f"{tv_share:.0%} of the value is the terminal value (above 75 %): the result leans "
                                 "on the long-run assumption."))
    if fcff and fcff[-1] <= 0 and terminal == "gordon":
        out.append(Check(code="negative_terminal_fcff", severity="error",
                         message="Cash flow in the final year is negative: a growing-perpetuity value is not possible."))
    return out


def scale_rows(rows: list[dict], base_revenue: float, k: float) -> list[dict]:
    """First Chicago scenario: each year's revenue growth x k (the first year's level x k when there is no base
    revenue); every other line keeps its share of revenue."""
    out: list[dict] = []
    prev_orig, prev_new = base_revenue, base_revenue
    for i, r in enumerate(rows):
        rev = float(r["revenue"])
        if prev_orig > 0:
            growth = rev / prev_orig - 1
            new_rev = max(prev_new * (1 + growth * k), 0.0)
        else:
            new_rev = rev * k if i == 0 else rev
        ratio = new_rev / rev if rev > 0 else 0.0
        nr = dict(r)
        nr["revenue"] = new_rev
        for key in ("cogs", "opex", "d_and_a", "capex"):
            nr[key] = float(r[key]) * ratio
        for key in ("tax", "nwc", "change_nwc"):
            if r.get(key) is not None:
                nr[key] = float(r[key]) * ratio
        out.append(nr)
        prev_orig, prev_new = rev, new_rev
    return out


def vc_post_money(exit_value: float, *, target_multiple: float | None = None, target_irr: float | None = None,
                  years: float = 5.0, retention: float = 1.0) -> float:
    """Post-money today = exit value x retention / target money multiple, or / (1 + target IRR)^years."""
    if target_multiple:
        return exit_value * retention / target_multiple
    if target_irr is not None:
        return exit_value * retention / (1 + target_irr) ** years
    raise ValueError("vc method needs a target multiple or a target IRR")


def clean_share_count(value_aud: float, price: float, sig_figs: int, bounds: tuple[int, int]) -> int:
    """value / price rounded to `sig_figs` significant figures, inside [min, max]."""
    raw = value_aud / price
    if raw <= 0:
        return int(bounds[0])
    digits = int(math.floor(math.log10(raw)))
    step = 10 ** max(digits - sig_figs + 1, 0)
    n = int(round(raw / step) * step)
    return int(min(max(n, bounds[0]), bounds[1]))


# ================================================================== method builders (inputs -> ValuationMethod)


def _raw(p, method: str, cls: str, inputs: dict, extra: float = 1.0) -> float:
    """base weight (stage x method matrix) x evidence factors x extra, then an admin override (<= 2x the rule)."""
    rule = base_weight(p, method, cls) * evidence_factor(p, inputs.get("evidence") or []) * extra
    ov = inputs.get("weight_override")
    if ov is not None:
        cap = p["max_weight_override_ratio"] * base_weight(p, method, cls)
        return round(min(max(float(ov), 0.0), cap), 6)
    return round(rule, 6)


def _not_run(method: str, label: str, inputs: dict, checks: list[Check], note: str) -> ValuationMethod:
    return ValuationMethod(method=method, label=label, value_aud=0.0, low_aud=0.0, high_aud=0.0, raw_weight=0.0,
                           inputs=inputs, checks=checks, notes=[note])


def _dcf_eval(inputs: dict, rows: list[dict], p) -> dict:
    """Shared by dcf and first_chicago: FCFF, EV/equity, terminal fallback, checks, grid."""
    rb = inputs["rate_build"]
    rate = float(rb["rate"])
    fc = fcff_series(rows, tax_rate=float(inputs["tax_rate"]), base_revenue=float(inputs.get("base_revenue") or 0),
                     base_nwc=inputs.get("base_nwc"), nwc_pct=float(inputs.get("nwc_pct", p["nwc_default_pct_of_delta_revenue"])))
    fcff = [x["fcff"] for x in fc]
    terminal = inputs.get("terminal", "gordon")
    g = inputs.get("g")
    exit_m = inputs.get("exit_multiple")
    final_ebitda = fc[-1]["ebitda"] if fc else None
    net_debt = float(inputs.get("net_debt_aud") or 0)
    notes: list[str] = []
    if terminal == "gordon" and fcff and fcff[-1] <= 0 and exit_m and (final_ebitda or 0) > 0:
        terminal = "exit"
        notes.append("final-year cash flow is negative: exit multiple used for the terminal value")
    checks = dcf_checks(rate=rate, rate_kind=inputs.get("rate_kind", "capm"), g=g, terminal=terminal, tv_share=None,
                        fcff=fcff, p=p)
    if any(c.severity == "error" for c in checks):
        return {"error": True, "checks": checks, "fc": fc, "notes": notes, "terminal": terminal}
    try:
        core = dcf_core(fcff, rate, terminal=terminal, g=g, exit_multiple=exit_m, final_ebitda=final_ebitda,
                        net_debt=net_debt, mid_year=bool(inputs.get("mid_year", True)))
    except ValueError as e:
        checks.append(Check(code="dcf_error", severity="error", message=str(e)))
        return {"error": True, "checks": checks, "fc": fc, "notes": notes, "terminal": terminal}
    checks += [c for c in dcf_checks(rate=rate, rate_kind="", g=None, terminal="", tv_share=core["tv_share"],
                                     fcff=[], p=p)]
    return {"error": False, "checks": checks, "fc": fc, "core": core, "notes": notes, "terminal": terminal,
            "fcff": fcff, "final_ebitda": final_ebitda, "net_debt": net_debt, "rate": rate}


def build_dcf(inputs: dict, p, cls: str) -> ValuationMethod:
    rows = inputs["rows"]
    label_rate = "cost of capital" if inputs.get("rate_kind") == "capm" else "venture discount rate"
    r = _dcf_eval(inputs, rows, p)
    label = f"discounted cash flow ({label_rate} {float(inputs['rate_build']['rate']):.1%}, {len(rows)} years)"
    if r["error"]:
        return _not_run("dcf", label, inputs, r["checks"], "not used: " + r["checks"][-1].message)
    core = r["core"]
    grid = sensitivity(r["fcff"], r["rate"], terminal=r["terminal"], g=inputs.get("g"),
                       exit_multiple=inputs.get("exit_multiple"), final_ebitda=r["final_ebitda"],
                       net_debt=r["net_debt"], d_rate=p["sensitivity_d_rate"], d_g=p["sensitivity_d_g"],
                       d_exit=p["sensitivity_d_exit"], mid_year=bool(inputs.get("mid_year", True)))
    value = core["equity"]
    low = grid["values"][4][0]
    high = grid["values"][0][4]
    low = value * 0.75 if low is None else min(low, value)
    high = value * 1.25 if high is None else max(high, value)
    extra = p["evidence_factors"]["tv_share_high"] if (core["tv_share"] or 0) > p["tv_share_warn"] else 1.0
    notes = list(r["notes"])
    if value <= 0:
        notes.append("not used: the cash flows give no positive equity value")
        raw = 0.0
    else:
        raw = _raw(p, "dcf", cls, inputs, extra)
    if inputs.get("projection_based", True):
        notes.append("based on management projections (unaudited, not verified by BlockID)")
    info = {"fcff": [round(x["fcff"], 2) for x in r["fc"]], "ebitda": [round(x["ebitda"], 2) for x in r["fc"]],
            "pv_fcff": round(core["pv_fcff"], 2), "tv": round(core["tv"], 2), "pv_tv": round(core["pv_tv"], 2),
            "ev": round(core["ev"], 2), "tv_share": None if core["tv_share"] is None else round(core["tv_share"], 4),
            "terminal_used": r["terminal"], "sensitivity": grid}
    if inputs.get("rows_uploaded"):
        try:
            u = _dcf_eval(inputs, inputs["rows_uploaded"], p)
            info["uncapped_value_aud"] = None if u["error"] else round(u["core"]["equity"], 2)
        except (KeyError, ValueError, TypeError):
            info["uncapped_value_aud"] = None
    return ValuationMethod(method="dcf", label=label, value_aud=max(value, 0.0), low_aud=max(low, 0.0),
                           high_aud=max(high, 0.0), raw_weight=raw, inputs={**inputs, "result": info},
                           checks=r["checks"], notes=notes, sources=list(inputs.get("sources") or []))


def build_first_chicago(inputs: dict, p, cls: str) -> ValuationMethod:
    scen = inputs["scenarios"]  # [[name, probability, growth factor k], ...]
    label = "scenario-weighted cash flows (First Chicago: " + " / ".join(f"{s[0]} {s[1]:.0%}" for s in scen) + ")"
    total_p = sum(float(s[1]) for s in scen)
    if abs(total_p - 1.0) > 1e-9:
        return _not_run("first_chicago", label, inputs,
                        [Check(code="probabilities", severity="error", message="scenario probabilities must sum to 1")],
                        "not used: scenario probabilities do not sum to 1")
    values: list[dict] = []
    checks: list[Check] = []
    for name, prob, k in scen:
        rows = scale_rows(inputs["rows"], float(inputs.get("base_revenue") or 0), float(k))
        r = _dcf_eval(inputs, rows, p)
        if r["error"]:
            checks += r["checks"]
            v = 0.0
        else:
            v = max(r["core"]["equity"], 0.0)
            checks += [c for c in r["checks"] if c.code == "tv_share"][:1] if name == "base" else []
        values.append({"scenario": name, "probability": float(prob), "k": float(k), "value_aud": round(v, 2)})
    value = sum(v["probability"] * v["value_aud"] for v in values)
    if value <= 0:
        return _not_run("first_chicago", label, inputs, checks, "not used: no scenario gives a positive value")
    low = min(v["value_aud"] for v in values)
    high = max(v["value_aud"] for v in values)
    notes = ["based on management projections (unaudited, not verified by BlockID)"]
    return ValuationMethod(method="first_chicago", label=label, value_aud=value, low_aud=min(low, value),
                           high_aud=max(high, value), raw_weight=_raw(p, "first_chicago", cls, inputs),
                           inputs={**inputs, "result": {"scenarios": values}}, checks=checks, notes=notes,
                           sources=list(inputs.get("sources") or []))


def _quartiles(ms: list[float]) -> tuple[float, float, float]:
    if len(ms) == 1:
        return ms[0] * 0.7, ms[0], ms[0] * 1.4
    return percentile(ms, 0.25), percentile(ms, 0.5), percentile(ms, 0.75)


def build_ebitda_multiple(inputs: dict, p, cls: str) -> ValuationMethod:
    """Trading comparables on EBITDA: LTM EBITDA x (25th / median / 75th multiple) x (1 - DLOM) - net debt.
    `multiples` (points) or `band` [low, mid, high]; the DLOM applies only to listed-peer multiples."""
    ebitda = float(inputs["ebitda_aud"])
    dlom = float(inputs.get("dlom") or 0)
    nd = float(inputs.get("net_debt_aud") or 0)
    if inputs.get("multiples"):
        lo, mid, hi = _quartiles([float(x) for x in inputs["multiples"]])
    else:
        lo, mid, hi = (float(x) for x in inputs["band"])
    k = 1 - dlom
    label = (f"EBITDA multiple ({lo:.1f}x / {mid:.1f}x / {hi:.1f}x, {inputs.get('detail', '')}"
             + (f"; listed-to-private discount {dlom:.0%}" if dlom else "") + ")")
    if ebitda <= 0:
        return _not_run("ebitda_multiple", label, inputs, [], "not used: EBITDA is not positive")
    value, low, high = ebitda * mid * k - nd, ebitda * lo * k - nd, ebitda * hi * k - nd
    notes = []
    if "industry_table_uncalibrated" in (inputs.get("evidence") or []):
        notes.append("industry multiple table is being calibrated (BlockID parameter)")
    if inputs.get("listed_blend"):
        notes.append(f"size-adjusted: {inputs['listed_blend']['share']:.0%} listed-peer multiple, the rest the private "
                     "transaction range for a business of this size")
    if value <= 0:
        return _not_run("ebitda_multiple", label, inputs, [], "not used: net debt exceeds the value")
    return ValuationMethod(method="ebitda_multiple", label=label, value_aud=value, low_aud=max(low, 0.0),
                           high_aud=high, raw_weight=_raw(p, "ebitda_multiple", cls, inputs),
                           inputs=inputs, notes=notes, sources=list(inputs.get("sources") or []))


def build_precedents(inputs: dict, p, cls: str) -> ValuationMethod:
    """Transaction multiples (control price, no DLOM): recency-weighted median of verified deals; 25th / 75th
    percentiles (one deal: x0.7 / x1.4); else the cited sector range `band`."""
    metric = float(inputs["metric_aud"])
    basis = inputs.get("basis", "ebitda")
    nd = float(inputs.get("net_debt_aud") or 0)
    deals = inputs.get("deals") or []
    if deals:
        pairs = []
        for d in deals:
            age = d.get("age_months")
            w = next(f for lim, f in p["deal_recency_weights"] if (age if age is not None else 1e8) <= lim)
            pairs.append((float(d["multiple"]), w))
        mid = weighted_median(pairs)
        ms = [float(d["multiple"]) for d in deals]
        lo, _, hi = _quartiles(ms)
        lo, hi = min(lo, mid), max(hi, mid)
        detail = f"{len(deals)} verified transaction(s)"
    else:
        lo, mid, hi = (float(x) for x in inputs["band"])
        detail = inputs.get("detail", "cited sector range")
    label = f"precedent transactions ({basis}: {lo:.1f}x / {mid:.1f}x / {hi:.1f}x, {detail})"
    if metric <= 0:
        return _not_run("precedents", label, inputs, [], f"not used: {basis} is not positive")
    value, low, high = metric * mid - nd, metric * lo - nd, metric * hi - nd
    if value <= 0:
        return _not_run("precedents", label, inputs, [], "not used: net debt exceeds the value")
    sources = list(dict.fromkeys([*(d.get("source_url") for d in deals if d.get("source_url")),
                                  *(inputs.get("sources") or [])]))
    return ValuationMethod(method="precedents", label=label, value_aud=value, low_aud=max(low, 0.0), high_aud=high,
                           raw_weight=_raw(p, "precedents", cls, inputs), inputs=inputs, sources=sources)


def build_vc_method(inputs: dict, p, cls: str) -> ValuationMethod:
    """Pre-money = exit value x retention / target multiple - new investment (or / (1 + IRR)^years). Low/high from
    the target band (the higher target gives the lower value)."""
    exit_value = float(inputs["exit_metric_aud"]) * float(inputs["exit_multiple"])
    inv = float(inputs.get("investment_aud") or 0)
    ret = float(inputs.get("retention", 1.0))
    years = float(inputs.get("years_to_exit", 5))
    if inputs.get("target_irr") is not None:
        irr = float(inputs["target_irr"])
        vals = [vc_post_money(exit_value, target_irr=x, years=years, retention=ret) - inv
                for x in (irr + 0.1, irr, max(irr - 0.1, 0.0))]
        label = f"venture capital method (exit A${exit_value:,.0f} in {years:g} years, target return {irr:.0%} a year)"
    else:
        t_lo, t_mid, t_hi = (float(x) for x in inputs["target_multiples"])
        vals = [vc_post_money(exit_value, target_multiple=t, retention=ret) - inv for t in (t_hi, t_mid, t_lo)]
        label = (f"venture capital method (exit A${exit_value:,.0f} in {years:g} years, target "
                 f"{t_lo:g}x-{t_hi:g}x)")
    low, value, high = vals
    if value <= 0:
        return _not_run("vc_method", label, inputs, [], "not used: the exit value does not cover the investment")
    return ValuationMethod(method="vc_method", label=label, value_aud=value, low_aud=max(low, 0.0), high_aud=high,
                           raw_weight=_raw(p, "vc_method", cls, inputs), inputs=inputs,
                           notes=["based on management projections (unaudited, not verified by BlockID)"]
                           if inputs.get("projection_based", True) else [],
                           sources=list(inputs.get("sources") or []))


def scorecard_factor(lines: dict, weights) -> float:
    return sum(float(weights[k]) * (0.5 + float(lines[k]["score"]) / 100) for k in weights)


def build_scorecard(inputs: dict, p, cls: str) -> ValuationMethod:
    """Payne scorecard: base pre-money x sum(weight x (0.5 + score / 100)); score 50 = the stage's typical company."""
    base = float(inputs["base_pre_money_aud"])
    w = inputs.get("weights") or p["scorecard_weights"]
    f = scorecard_factor(inputs["lines"], w)
    value = base * f
    hw = float(inputs.get("half_width", p["startup_range_half_width"]))
    label = f"scorecard vs typical {inputs.get('stage', '')} company (base A${base:,.0f} x {f:.2f})"
    notes = []
    if "ai_suggested" in (inputs.get("evidence") or []):
        notes.append("some scores are suggested and not yet confirmed by a reviewer: weight reduced")
    return ValuationMethod(method="scorecard", label=label, value_aud=value, low_aud=value * (1 - hw),
                           high_aud=value * (1 + hw), raw_weight=_raw(p, "scorecard", cls, inputs),
                           inputs={**inputs, "factor": round(f, 6)}, notes=notes,
                           sources=list(inputs.get("sources") or []))


def build_berkus(inputs: dict, p, cls: str) -> ValuationMethod:
    cap = float(inputs["cap_per_factor_aud"])
    scores = inputs["scores"]
    value = sum(min(max(float(scores.get(k, 0)), 0.0), 100.0) / 100 * cap for k in BERKUS_KEYS)
    hw = float(inputs.get("half_width", p["startup_range_half_width"]))
    label = f"Berkus method (5 milestones, up to A${cap:,.0f} each)"
    if value <= 0:
        return _not_run("berkus", label, inputs, [], "not used: no milestone reached")
    notes = ["milestone ratings suggested, not yet confirmed: weight reduced"] \
        if "ai_suggested" in (inputs.get("evidence") or []) else []
    return ValuationMethod(method="berkus", label=label, value_aud=value, low_aud=value * (1 - hw),
                           high_aud=value * (1 + hw), raw_weight=_raw(p, "berkus", cls, inputs), inputs=inputs,
                           notes=notes, sources=list(inputs.get("sources") or []))


def build_rfs(inputs: dict, p, cls: str) -> ValuationMethod:
    base = float(inputs["base_pre_money_aud"])
    step = base * float(inputs.get("step_ratio", p["rfs_step_ratio"]))
    ratings = inputs["ratings"]
    total = sum(max(-2, min(2, int(ratings.get(k, 0)))) for k in RFS_KEYS)
    value = max(base + total * step, base * float(p["rfs_floor_ratio"]))
    hw = float(inputs.get("half_width", p["startup_range_half_width"]))
    label = f"risk factor summation (12 risks, net {total:+d} steps of A${step:,.0f} on A${base:,.0f})"
    notes = ["risk ratings suggested, not yet confirmed: weight reduced"] \
        if "ai_suggested" in (inputs.get("evidence") or []) else []
    return ValuationMethod(method="rfs", label=label, value_aud=value, low_aud=value * (1 - hw),
                           high_aud=value * (1 + hw), raw_weight=_raw(p, "rfs", cls, inputs),
                           inputs={**inputs, "net_steps": total}, notes=notes,
                           sources=list(inputs.get("sources") or []))


def build_revenue_multiple(inputs: dict, p, cls: str) -> ValuationMethod | None:
    """v3 revenue x multiple (same maths and inputs); v5 weight = matrix x multiple source x revenue source."""
    from .triangulate import MULTIPLE_SOURCE_FACTOR, revenue_method

    mult = {"source": inputs.get("multiple_source", "default"), "median": float(inputs.get("median_multiple") or 0),
            "low": float(inputs.get("low_multiple") or 0), "high": float(inputs.get("high_multiple") or 0),
            "discount": float(inputs.get("discount") or 0), "n": inputs.get("n", 0), "detail": inputs.get("detail", ""),
            "multiples": inputs.get("multiples") or [], "sources": inputs.get("multiple_sources") or []}
    v3_src = mult["source"] if mult["source"] in MULTIPLE_SOURCE_FACTOR else "default"  # v3 maths, v5 source
    m = revenue_method(float(inputs.get("revenue_aud") or 0), inputs.get("revenue_source", ""),
                       {**mult, "source": v3_src}, inputs.get("revenue_ref", ""))
    if m is None:
        return None
    if v3_src != mult["source"]:
        m.inputs["multiple_source"] = mult["source"]
        m.notes = [n for n in m.notes if n != "multiple is a default, not cited"]
    if inputs.get("listed_blend"):
        lb = inputs["listed_blend"]
        m.notes.append(f"{lb['share']:.0%} of the multiple from listed peers at this company size "
                       f"({lb['industry_ev_sales']:g}x EV/Sales, Damodaran)")
    ev = p["evidence_factors"]
    src_f = ev.get(mult["source"], 0.25)
    rev_f = ev.get(inputs.get("revenue_source", ""), 0.8)
    rule = base_weight(p, "revenue_multiple", cls) * src_f * rev_f
    ov = inputs.get("weight_override")
    m.raw_weight = round(min(float(ov), p["max_weight_override_ratio"] * base_weight(p, "revenue_multiple", cls))
                         if ov is not None else rule, 6)
    m.inputs = {**m.inputs, **{k: inputs[k] for k in ("detail", "multiple_sources", "revenue_ref", "weight_override",
                                                      "listed_blend") if k in inputs}}
    return m


def build_market_anchor(inputs: dict, p, cls: str) -> ValuationMethod | None:
    from .triangulate import anchor_method

    m = anchor_method(inputs.get("anchors") or [])
    if m is not None:
        m.raw_weight = round(m.raw_weight * float(p["anchor_weight_scale"]), 6)
    return m


def build_stage_scorecard(inputs: dict, p, cls: str) -> ValuationMethod:
    """v3 stage benchmark x SVI factor; its weight is set in the blend (alone 1.0, else the matrix, 0 if > 5x)."""
    from .triangulate import stage_method

    b = inputs.get("benchmark") or [0, 0, 0]
    m = stage_method(inputs.get("stage", ""), (b[0], b[1], b[2]), float(inputs.get("svi_factor") or 0))
    m.raw_weight = base_weight(p, "stage_scorecard", cls)
    basis = inputs.get("benchmark_basis")
    if basis:  # v5.1: a calibrated benchmark (AU stage table, or funding raised), not the v3 placeholder
        m.inputs["benchmark_basis"] = basis
        m.inputs.update({k: inputs[k] for k in ("raised_aud", "raised_source") if k in inputs})
        m.notes = [basis]
        if inputs.get("benchmark_sources"):
            m.inputs["benchmark_sources"] = list(inputs["benchmark_sources"])
            m.sources = list(inputs["benchmark_sources"])
        if str(basis).startswith("funding"):
            m.label = f"funding-implied value ({inputs.get('stage', '')}) x quality score factor " \
                      f"{float(inputs.get('svi_factor') or 0):.2f}"
    return m


METHOD_BUILDERS = {
    "market_anchor": build_market_anchor,
    "revenue_multiple": build_revenue_multiple,
    "stage_scorecard": build_stage_scorecard,
    "ebitda_multiple": build_ebitda_multiple,
    "precedents": build_precedents,
    "dcf": build_dcf,
    "first_chicago": build_first_chicago,
    "vc_method": build_vc_method,
    "scorecard": build_scorecard,
    "berkus": build_berkus,
    "rfs": build_rfs,
}


def build(method: str, inputs: dict, p, cls: str) -> ValuationMethod | None:
    m = METHOD_BUILDERS[method](inputs, p, cls)
    if m is not None and method in ("market_anchor", "stage_scorecard") and inputs.get("weight_override") is not None:
        m.raw_weight = round(min(max(float(inputs["weight_override"]), 0.0),
                                 p["max_weight_override_ratio"] * max(m.raw_weight, 0.1)), 6)
        m.inputs = {**m.inputs, "weight_override": inputs["weight_override"]}
    return m


# ================================================================== valuation class (stage x business model)


def classify_valuation_class(*, stage: str, listed: bool, ebitda_last_actual: float | None, revenue_aud: float,
                             growth_pct: float | None, raised_aud: float | None) -> tuple[str, list[str]]:
    """Plan §3.1 on top of the evidence-based stage (tools/stage.classify_stage):
    listed (verified listing) > profitable_sme (revenue and positive EBITDA in the last actual year, growth < 30 %,
    funding < 1x revenue) > the stage itself (idea / pre_seed / seed / series_a / growth)."""
    reasons: list[str] = []
    if listed:
        return "listed", ["verified listing: the market price leads"]
    if (revenue_aud > 0 and ebitda_last_actual is not None and ebitda_last_actual > 0
            and (growth_pct is None or growth_pct < 30) and (not raised_aud or raised_aud < revenue_aud)):
        reasons.append(f"profitable business: EBITDA A${ebitda_last_actual:,.0f} in the last actual year, growth "
                       + (f"{growth_pct:.0f} %" if growth_pct is not None else "unknown")
                       + ", funding below one year of revenue")
        return "profitable_sme", reasons
    from .stage import to_valuation_class

    return to_valuation_class(stage), reasons


def as_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default
