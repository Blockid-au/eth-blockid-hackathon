"""Deterministic metric maths for evaluation v5 (docs/PLAN-EVALUATION-V5.md §1.2, §3.1 "derived by code only").

Pure functions, no I/O. Every function returns None when its inputs are missing or meaningless (never a guess).
Percentages are in percent units (75.0 = 75 %).
"""
from __future__ import annotations

import math
from collections.abc import Sequence


def _ok(*xs) -> bool:
    return all(x is not None and isinstance(x, (int, float)) and math.isfinite(x) for x in xs)


def growth_pct(now: float | None, before: float | None) -> float | None:
    """(now / before − 1) × 100; None when `before` <= 0."""
    if not _ok(now, before) or before <= 0 or now < 0:
        return None
    return round((now / before - 1.0) * 100.0, 2)


def cmgr_pct(now: float | None, before: float | None, months: float | None) -> float | None:
    """Compound monthly growth rate over `months` months (YC "slope")."""
    if not _ok(now, before, months) or before <= 0 or now <= 0 or months <= 0:
        return None
    return round(((now / before) ** (1.0 / months) - 1.0) * 100.0, 2)


def cmgr_series(values: Sequence[float | None], window: int = 6) -> float | None:
    """CMGR over the last `window` months of a monthly series (uses the first positive value inside the window)."""
    vals = [v for v in values if _ok(v)]
    if len(vals) < 2:
        return None
    tail = vals[-(window + 1):]
    for i, v in enumerate(tail[:-1]):
        if v > 0:
            return cmgr_pct(tail[-1], v, len(tail) - 1 - i)
    return None


def yoy_from_series(values: Sequence[float | None]) -> float | None:
    """YoY growth of a monthly series: last month vs the same month a year earlier (needs >= 13 points)."""
    vals = list(values)
    if len(vals) < 13 or not _ok(vals[-1], vals[-13]):
        return None
    return growth_pct(vals[-1], vals[-13])


def annualised(mrr: float | None) -> float | None:
    return round(mrr * 12.0, 2) if _ok(mrr) and mrr >= 0 else None


def nrr_pct(start_mrr: float | None, expansion: float | None, contraction: float | None,
            churned: float | None) -> float | None:
    """(start + expansion − contraction − churn) / start × 100 over a cohort period."""
    if not _ok(start_mrr) or start_mrr <= 0:
        return None
    e, c, ch = (x if _ok(x) else 0.0 for x in (expansion, contraction, churned))
    return round((start_mrr + e - c - ch) / start_mrr * 100.0, 2)


def grr_pct(start_mrr: float | None, contraction: float | None, churned: float | None) -> float | None:
    if not _ok(start_mrr) or start_mrr <= 0:
        return None
    c, ch = (x if _ok(x) else 0.0 for x in (contraction, churned))
    return round(max(0.0, (start_mrr - c - ch) / start_mrr * 100.0), 2)


def logo_churn_monthly_pct(churned_customers: Sequence[float | None], customers: Sequence[float | None]) -> float | None:
    """Mean monthly logo churn = churned in month t / customers at the end of month t−1."""
    rates = []
    for i in range(1, min(len(churned_customers), len(customers))):
        ch, base = churned_customers[i], customers[i - 1]
        if _ok(ch, base) and base > 0:
            rates.append(ch / base * 100.0)
    return round(sum(rates) / len(rates), 2) if rates else None


def annual_logo_retention_from_monthly_churn(churn_pct: float | None) -> float | None:
    if not _ok(churn_pct) or not 0 <= churn_pct <= 100:
        return None
    return round(((1 - churn_pct / 100.0) ** 12) * 100.0, 2)


def burn_multiple(net_burn_12m: float | None, net_new_arr_12m: float | None) -> float | None:
    """Net burn ÷ net new ARR (Sacks). None when no new ARR (infinite) — shown as a flag, not scored."""
    if not _ok(net_burn_12m, net_new_arr_12m) or net_new_arr_12m <= 0 or net_burn_12m < 0:
        return None
    return round(net_burn_12m / net_new_arr_12m, 2)


def runway_months(cash: float | None, burn_monthly: float | None) -> float | None:
    if not _ok(cash, burn_monthly) or cash < 0:
        return None
    if burn_monthly <= 0:
        return 60.0  # not burning: shown as "default alive", capped
    return round(min(cash / burn_monthly, 600.0), 1)


def cac_payback_months(cac: float | None, arpa_monthly: float | None, gross_margin_pct: float | None) -> float | None:
    if not _ok(cac, arpa_monthly) or cac <= 0 or arpa_monthly <= 0:
        return None
    gm = gross_margin_pct / 100.0 if _ok(gross_margin_pct) and gross_margin_pct > 0 else 1.0
    return round(cac / (arpa_monthly * gm), 1)


def ltv_cac(arpa_monthly: float | None, gross_margin_pct: float | None, churn_monthly_pct: float | None,
            cac: float | None) -> float | None:
    """LTV / CAC with LTV = ARPA × GM / monthly churn (churn floored at 0.5 %/month: 16-year lifetime cap)."""
    if not _ok(arpa_monthly, churn_monthly_pct, cac) or cac <= 0 or arpa_monthly <= 0:
        return None
    gm = gross_margin_pct / 100.0 if _ok(gross_margin_pct) and gross_margin_pct > 0 else 1.0
    churn = max(churn_monthly_pct, 0.5) / 100.0
    return round(arpa_monthly * gm / churn / cac, 2)


def rule_of_40(growth_pct_: float | None, profit_margin_pct: float | None) -> float | None:
    if not _ok(growth_pct_, profit_margin_pct):
        return None
    return round(growth_pct_ + profit_margin_pct, 2)


def within(a: float | None, b: float | None, tol: float) -> bool | None:
    """|a − b| <= tol × max(|a|, |b|); None if either is missing."""
    if not _ok(a, b):
        return None
    m = max(abs(a), abs(b))
    return m == 0 or abs(a - b) <= tol * m
