"""Monthly metrics CSV -> computed metrics + forensics (evaluation v5, docs/PLAN-EVALUATION-V5.md §3.2 / §4.4).

The browser parses the file and sends CSV text (or rows); the server never stores the file, only the text, its
SHA-256 and this parse. Template: docs/templates/metrics-monthly.csv

    month, revenue_aud, mrr_aud, new_mrr, expansion_mrr, contraction_mrr, churned_mrr, customers, new_customers,
    churned_customers, active_users, cash_aud, burn_aud

Header aliases map Stripe ("MRR by month"), Baremetrics and ChartMogul exports onto these columns. Every number is
computed here (tools/metrics_calc.py); forensics raise ConsistencyFlags, never an automatic penalty.
"""
from __future__ import annotations

import csv
import io
import math
import re
from datetime import UTC, datetime

from . import metrics_calc as mc

MAX_ROWS = 120
MAX_CHARS = 200_000
COLUMNS = ("month", "revenue_aud", "mrr_aud", "new_mrr", "expansion_mrr", "contraction_mrr", "churned_mrr",
           "customers", "new_customers", "churned_customers", "active_users", "cash_aud", "burn_aud")
NON_NEGATIVE = frozenset(COLUMNS[1:]) - {"burn_aud"}

_ALIASES = {
    "month": ("month", "date", "period", "monthstart", "yearmonth", "startdate"),
    "revenue_aud": ("revenueaud", "revenue", "totalrevenue", "netrevenue", "sales", "income"),
    "mrr_aud": ("mrraud", "mrr", "monthlyrecurringrevenue", "endingmrr", "mrrend", "totalmrr"),
    "new_mrr": ("newmrr", "newbusinessmrr", "newbusiness", "new"),
    "expansion_mrr": ("expansionmrr", "expansion", "upgrades", "upgrademrr"),
    "contraction_mrr": ("contractionmrr", "contraction", "downgrades", "downgrademrr"),
    "churned_mrr": ("churnedmrr", "churnmrr", "churn", "churned", "cancellations", "cancellationmrr"),
    "customers": ("customers", "subscribers", "activecustomers", "payingcustomers", "customercount", "accounts"),
    "new_customers": ("newcustomers", "newsubscribers", "newaccounts"),
    "churned_customers": ("churnedcustomers", "cancelledcustomers", "churnedsubscribers", "lostcustomers"),
    "active_users": ("activeusers", "mau", "monthlyactiveusers", "users"),
    "cash_aud": ("cashaud", "cash", "cashbalance", "bankbalance"),
    "burn_aud": ("burnaud", "burn", "netburn", "cashburn"),
}
_ALIAS_TO_COL = {a: c for c, al in _ALIASES.items() for a in al}
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


def _hkey(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (h or "").lower().replace("(aud)", "").replace("a$", "").replace("$", ""))


def map_headers(headers: list[str]) -> dict[int, str]:
    out: dict[int, str] = {}
    for i, h in enumerate(headers):
        col = _ALIAS_TO_COL.get(_hkey(h))
        if col and col not in out.values():
            out[i] = col
    return out


def parse_month(s: str) -> str | None:
    t = (s or "").strip().lower()
    m = re.match(r"^(\d{4})[-/.](\d{1,2})(?:[-/.]\d{1,2})?", t)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.match(r"^(\d{1,2})[-/.](\d{4})$", t)
    if m and 1 <= int(m.group(1)) <= 12:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    m = re.match(r"^(?:\d{1,2}[-/.])?(\d{1,2})[-/.](\d{4})$", t)  # dd/mm/yyyy
    if m and 1 <= int(m.group(1)) <= 12:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    m = re.match(r"^([a-z]{3})[a-z]*[\s\-']+(\d{2,4})$", t)
    if m and m.group(1) in _MONTHS:
        y = int(m.group(2))
        y = y + 2000 if y < 100 else y
        return f"{y}-{_MONTHS.index(m.group(1)) + 1:02d}"
    return None


def parse_number(s: str) -> float | None:
    t = (s or "").strip()
    if t in ("", "-", "—", "n/a", "na", "null"):
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = re.sub(r"[()\s$A-Za-z,%]", "", t.replace("A$", "").replace("AU$", "").replace("US$", ""))
    try:
        v = float(t)
    except ValueError:
        raise ValueError("not a number") from None
    if not math.isfinite(v):
        raise ValueError("not a number")
    return -v if neg else v


def _rows_from(payload: str | list) -> list[list[str]]:
    if isinstance(payload, str):
        if len(payload) > MAX_CHARS:
            raise ValueError(f"CSV too large (max {MAX_CHARS:,} characters)")
        return [r for r in csv.reader(io.StringIO(payload)) if any(c.strip() for c in r)]
    return [[str(c) for c in r] for r in payload if isinstance(r, (list, tuple)) and any(str(c).strip() for c in r)]


def _flag(code: str, severity: str, message: str, metrics: list[str] | None = None, action: str = "") -> dict:
    return {"code": code, "severity": severity, "message": message, "metrics": metrics or [], "action": action}


def parse(payload: str | list, today: str = "") -> dict:
    """-> {rows, months, series{col: [..]}, metrics{..}, flags[..], errors[..], mapped_headers{header: col}}.
    Raises ValueError for an unusable file (no header / no month column / too many rows)."""
    rows = _rows_from(payload)
    if len(rows) < 2:
        raise ValueError("the CSV needs a header row and at least one month")
    if len(rows) - 1 > MAX_ROWS:
        raise ValueError(f"too many rows (max {MAX_ROWS} months)")
    header = rows[0]
    hmap = map_headers(header)
    if "month" not in hmap.values():
        raise ValueError("no month column (expected 'month' as YYYY-MM)")
    errors: list[str] = []
    recs: list[dict] = []
    for n, r in enumerate(rows[1:], start=2):
        rec: dict = {}
        for i, col in hmap.items():
            cell = r[i] if i < len(r) else ""
            if col == "month":
                m = parse_month(cell)
                if not m:
                    errors.append(f"row {n}: month {cell!r} is not a month (use YYYY-MM)")
                rec["month"] = m
                continue
            try:
                rec[col] = parse_number(cell)
            except ValueError:
                errors.append(f"row {n}: {col} is not a number")
                rec[col] = None
        if rec.get("month"):
            recs.append(rec)
    flags: list[dict] = []
    # forensics: duplicates, order, gaps, future months, negatives
    months = [r["month"] for r in recs]
    if len(set(months)) != len(months):
        flags.append(_flag("csv_duplicate_rows", "high", "the CSV repeats a month (duplicated rows)", ["month"],
                           "review"))
    data_rows = [tuple(r.get(c) for c in COLUMNS[1:]) for r in recs]
    if len(set(data_rows)) < len(data_rows) and any(any(v for v in d if v) for d in data_rows):
        flags.append(_flag("csv_duplicate_values", "warning", "two or more months have identical figures",
                           [], "review"))
    by_month: dict[str, dict] = {}
    for r in recs:
        by_month.setdefault(r["month"], r)
    ordered = [by_month[m] for m in sorted(by_month)]
    today = today or datetime.now(UTC).strftime("%Y-%m")
    future = [r["month"] for r in ordered if r["month"] > today[:7]]
    if future:
        flags.append(_flag("csv_future_months", "high", f"months in the future: {', '.join(future[:3])}", ["month"],
                           "review"))
        ordered = [r for r in ordered if r["month"] <= today[:7]]
    gaps = _gaps([r["month"] for r in ordered])
    if gaps:
        flags.append(_flag("csv_month_gaps", "info", f"{gaps} missing month(s) in the series", ["month"]))
    for col in sorted(NON_NEGATIVE):
        if any((r.get(col) or 0) < 0 for r in ordered):
            flags.append(_flag("csv_negative_values", "warning", f"negative values in {col}", [col], "review"))
    series = {c: [r.get(c) for r in ordered] for c in COLUMNS[1:] if any(r.get(c) is not None for r in ordered)}
    metrics = compute(series)
    flags += forensics(series)
    return {"rows": len(ordered), "months": [r["month"] for r in ordered], "series": series, "metrics": metrics,
            "flags": flags, "errors": errors[:50], "mapped_headers": {header[i]: c for i, c in hmap.items()}}


def _gaps(months: list[str]) -> int:
    def idx(m: str) -> int:
        return int(m[:4]) * 12 + int(m[5:7])

    return sum(max(0, idx(b) - idx(a) - 1) for a, b in zip(months, months[1:], strict=False))


def _last(xs: list | None):
    for v in reversed(xs or []):
        if v is not None:
            return v
    return None


def compute(series: dict[str, list]) -> dict:
    """Metrics from monthly series (only those the data supports)."""
    out: dict[str, float] = {}
    mrr = series.get("mrr_aud")
    rev = series.get("revenue_aud")
    n = max((len(v) for v in series.values()), default=0)
    if mrr and _last(mrr) is not None:
        out["mrr_aud"] = _last(mrr)
        out["arr_aud"] = mc.annualised(_last(mrr))
    if rev and n >= 12 and all(v is not None for v in rev[-12:]):
        out["revenue_ttm_aud"] = round(sum(rev[-12:]), 2)
        if n >= 24 and all(v is not None for v in rev[-24:-12]):
            out["revenue_prev_ttm_aud"] = round(sum(rev[-24:-12]), 2)
    base = mrr or rev
    if base:
        yoy = mc.yoy_from_series(base)
        if yoy is None and out.get("revenue_prev_ttm_aud"):
            yoy = mc.growth_pct(out["revenue_ttm_aud"], out["revenue_prev_ttm_aud"])
        if yoy is not None:
            out["yoy_growth_pct"] = yoy
        cm = mc.cmgr_series(base, window=6)
        if cm is not None:
            out["cmgr_pct"] = cm
    elif series.get("active_users"):
        cm = mc.cmgr_series(series["active_users"], window=6)
        if cm is not None:
            out["cmgr_pct"] = cm
            out["cmgr_basis_users"] = 1.0
    if mrr and len(mrr) >= 13 and mrr[-13]:
        mv = {k: [x or 0.0 for x in (series.get(k) or [0.0] * len(mrr))[-12:]]
              for k in ("expansion_mrr", "contraction_mrr", "churned_mrr")}
        if any(series.get(k) for k in mv):
            nrr = mc.nrr_pct(mrr[-13], sum(mv["expansion_mrr"]), sum(mv["contraction_mrr"]), sum(mv["churned_mrr"]))
            grr = mc.grr_pct(mrr[-13], sum(mv["contraction_mrr"]), sum(mv["churned_mrr"]))
            if nrr is not None:
                out["nrr_pct"] = nrr
            if grr is not None:
                out["grr_pct"] = grr
    cust = series.get("customers")
    if cust and _last(cust) is not None:
        out["paying_customers"] = _last(cust)
        if len(cust) >= 13 and cust[-13] is not None:
            out["paying_customers_12m_ago"] = cust[-13]
    if cust and series.get("churned_customers"):
        ch = mc.logo_churn_monthly_pct(series["churned_customers"][-12:], cust[-12:])
        if ch is not None:
            out["logo_churn_monthly_pct"] = ch
    if series.get("active_users") and _last(series["active_users"]) is not None:
        out["active_users_monthly"] = _last(series["active_users"])
    burn = series.get("burn_aud")
    if burn and mrr:
        w = min(12, len(mrr) - 1, len(burn) - 1)
        if w >= 3 and mrr[-1 - w] is not None and mrr[-1] is not None:
            net_new_arr = (mrr[-1] - mrr[-1 - w]) * 12
            b = sum(x for x in burn[-w:] if x is not None)
            bm = mc.burn_multiple(b, net_new_arr)
            if bm is not None:
                out["burn_multiple"] = bm
            out["net_new_arr_12m_aud"] = round(net_new_arr * 12 / w, 2)
    if burn:
        recent = [x for x in burn[-3:] if x is not None]
        if recent:
            out["burn_monthly_aud"] = round(sum(recent) / len(recent), 2)
    if series.get("cash_aud") and _last(series["cash_aud"]) is not None:
        out["cash_aud"] = _last(series["cash_aud"])
        if out.get("burn_monthly_aud") is not None:
            rw = mc.runway_months(out["cash_aud"], out["burn_monthly_aud"])
            if rw is not None:
                out["runway_months"] = rw
    return out


def forensics(series: dict[str, list]) -> list[dict]:
    flags: list[dict] = []
    for col in ("mrr_aud", "revenue_aud", "customers"):
        xs = [x for x in (series.get(col) or []) if x is not None]
        if len(xs) >= 6 and all(x > 0 for x in xs):
            g = [b / a - 1 for a, b in zip(xs, xs[1:], strict=False)]
            mean = sum(g) / len(g)
            sd = math.sqrt(sum((x - mean) ** 2 for x in g) / len(g))
            if abs(mean) > 0.005 and sd / abs(mean) < 0.02:
                flags.append(_flag("csv_smooth_series", "warning",
                                   f"{col} grows at an almost identical rate every month (real data is noisier)",
                                   [col], "review"))
    values = [x for v in series.values() for x in v if x is not None and x != 0]
    if len(values) >= 12:
        rnd = sum(1 for x in values if abs(x) >= 1000 and x % 1000 == 0) / len(values)
        if rnd > 0.8:
            flags.append(_flag("csv_round_numbers", "info", f"{rnd:.0%} of the figures are round thousands", []))
    if len(values) >= 50:
        p = benford_p(values)
        if p is not None and p < 0.001:
            flags.append(_flag("csv_benford", "info", "first-digit distribution differs from Benford's law "
                               "(information only)", []))
    return flags


def benford_p(values: list[float]) -> float | None:
    """Chi-square test of first digits vs Benford (8 d.o.f.); returns an approximate p-value."""
    counts = [0] * 9
    for v in values:
        s = f"{abs(v):e}"
        d = int(s[0])
        if 1 <= d <= 9:
            counts[d - 1] += 1
    n = sum(counts)
    if n < 50:
        return None
    chi = sum((c - n * math.log10(1 + 1 / (d + 1))) ** 2 / (n * math.log10(1 + 1 / (d + 1)))
              for d, c in enumerate(counts))
    # Wilson-Hilferty approximation of the chi-square survival function, k = 8
    k = 8.0
    z = ((chi / k) ** (1 / 3) - (1 - 2 / (9 * k))) / math.sqrt(2 / (9 * k))
    return 0.5 * math.erfc(z / math.sqrt(2))
