"""Business updates: deterministic draft maths, canonical content and its hash (pure functions, no I/O).

A founder enters KPI values for a period; `build_draft` compares them with the previous period and writes the
title, a plain-language summary, highlights and risks from the numbers alone (no language model involved, so the
API never depends on one). After a person approves the update, the issuer records `content_hash` on BlockID Chain:

    content_hash = "0x" + sha256(utf8(canonical_json(canonical_update(row, company))))

canonical_json is the same canonicalisation as the valuation report hash (studio/report_hash.py): keys sorted,
separators (",", ":"), ensure_ascii=False. The browser recomputes it from the canonical text the API returns
(web/app/src/lib/canonical.ts + sha256).

On-chain record: a 0-value transaction from the issuer to itself on BlockID Chain whose calldata is
DISCLOSURE_TAG (b"BIDU" + 0x0000) followed by the 32-byte hash (see issuer/service.py `disclose`).
"""
from __future__ import annotations

import calendar
import hashlib
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from .report_hash import canonical_json

CADENCES = ("weekly", "monthly", "quarterly", "annual")
# metric -> unit, in display order
METRICS: dict[str, str] = {
    "revenue": "AUD",
    "gross_profit": "AUD",
    "net_profit": "AUD",
    "cash": "AUD",
    "customers": "count",
    "headcount": "count",
}
LABELS = {"revenue": "Revenue", "gross_profit": "Gross profit", "net_profit": "Net profit", "cash": "Cash",
          "customers": "Customers", "headcount": "Team"}
DISCLOSURE_TAG_HEX = "424944550000"  # "BIDU" + 2-byte version 0
CANONICAL_VERSION = 1
BODY_KEYS = ("summary", "highlights", "risks", "kpis", "note")


# ------------------------------------------------------------------ periods
def _add_months(d: date, n: int) -> date:
    """Month arithmetic that keeps month ends on month ends (31 Aug - 1 month = 31 Jul, 30 Sep - 1 = 31 Aug)."""
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    last = calendar.monthrange(y, m)[1]
    eom = d.day == calendar.monthrange(d.year, d.month)[1]
    return date(y, m, last if eom else min(d.day, last))


def period_start(cadence: str, end: date) -> date:
    if cadence == "weekly":
        return end - timedelta(days=6)
    months = {"monthly": 1, "quarterly": 3, "annual": 12}[cadence]
    return _add_months(end, -months) + timedelta(days=1)


def _is_eom(d: date) -> bool:
    return d.day == calendar.monthrange(d.year, d.month)[1]


def _day(d: date) -> str:
    return f"{d.day} {d.strftime('%b')} {d.year}"


def period_label(cadence: str, end: date) -> str:
    if cadence == "monthly" and _is_eom(end):
        return f"{calendar.month_name[end.month]} {end.year}"
    if cadence == "quarterly" and _is_eom(end) and end.month % 3 == 0:
        return f"Q{end.month // 3} {end.year}"
    return {"weekly": "the week to ", "monthly": "the month to ", "quarterly": "the quarter to ",
            "annual": "the year to "}[cadence] + _day(end)


# ------------------------------------------------------------------ numbers
def num(x: Any) -> int | float | None:
    """Canonical number: int when integral, else a float rounded to 2 decimals (same text in Python and JS)."""
    if x is None:
        return None
    d = x if isinstance(x, Decimal) else Decimal(str(x))
    if not d.is_finite():
        raise ValueError("number must be finite")
    d = d.quantize(Decimal("0.01"))
    return int(d) if d == d.to_integral_value() else float(d)


def change_pct(v: float | None, prev: float | None) -> float | None:
    if v is None or prev is None or prev == 0:
        return None
    return num(Decimal(str(round((v - prev) / abs(prev) * 100, 1))))


def money(v: float) -> str:
    a = abs(v)
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if a >= div:
            s = f"{a / div:.1f}".rstrip("0").rstrip(".")
            return f"A${s}{suf}"
    return f"A${a:,.0f}"


def _fmt(metric: str, v: float) -> str:
    return money(v) if METRICS[metric] == "AUD" else f"{abs(v):,.0f}"


def _pct(p: float) -> str:
    a = abs(p)
    return (f"{a:.0f}" if a >= 10 else f"{a:.1f}".rstrip("0").rstrip(".")) + "%"


def _lower_first(s: str) -> str:
    return s[:1].lower() + s[1:] if s[:2] != s[:2].upper() else s


# ------------------------------------------------------------------ sentences
def _moved(metric: str, v: float, prev: float | None, up: str = "grew", down: str = "fell") -> str:
    label = LABELS[metric]
    if prev is None:
        return f"{label} was {_fmt(metric, v)}"
    p = change_pct(v, prev)
    if p is None:
        return f"{label} was {_fmt(metric, v)}, up from zero" if v > 0 else f"{label} was {_fmt(metric, v)}"
    if abs(p) < 0.5 or _fmt(metric, v) == _fmt(metric, prev):
        return f"{label} was steady at {_fmt(metric, v)}"
    return f"{label} {up if p > 0 else down} {_pct(p)} to {_fmt(metric, v)}"


def _net(v: float, prev: float | None) -> str:
    if v >= 0:
        if prev is None or prev == 0:
            return f"Net profit was {money(v)}"
        if prev < 0:
            return f"The business turned profitable: net profit of {money(v)}, from a loss of {money(prev)}"
        return _moved("net_profit", v, prev, up="rose")
    if prev is None or prev == 0:
        return f"Net loss was {money(v)}"
    if prev > 0:
        return f"The business made a net loss of {money(v)}, after a profit of {money(prev)}"
    p = change_pct(abs(v), abs(prev)) or 0
    if abs(p) < 0.5 or money(v) == money(prev):
        return f"Net loss was steady at {money(v)}"
    return f"Net loss {'narrowed' if abs(v) < abs(prev) else 'widened'} to {money(v)} from {money(prev)}"


def _team(v: float, prev: float | None) -> str:
    n = f"{v:,.0f}"
    if prev is None:
        return f"The team is {n} people"
    if v == prev:
        return f"The team stayed at {n} people"
    return f"The team {'grew' if v > prev else 'shrank'} from {prev:,.0f} to {n} people"


def _runway_months(cadence: str, cash: float | None, net: float | None) -> float | None:
    if cash is None or net is None or net >= 0 or cash <= 0:
        return None
    per_month = abs(net) * {"weekly": 52 / 12, "monthly": 1, "quarterly": 1 / 3, "annual": 1 / 12}[cadence]
    return cash / per_month


def build_draft(company: dict, cadence: str, start: date, end: date, cur: dict[str, Any],
                prev: dict[str, Any] | None = None, note: str = "") -> dict:
    """Title + body from the numbers only. cur/prev: {metric: value}; missing / None metrics are skipped."""
    if cadence not in CADENCES:
        raise ValueError(f"cadence must be one of {CADENCES}")
    prev = prev or {}
    val = {m: (None if cur.get(m) is None else num(cur[m])) for m in METRICS}
    pv = {m: (None if prev.get(m) is None else num(prev[m])) for m in METRICS}
    kpis = [{"metric": m, "value": val[m], "prev": pv[m], "change_pct": change_pct(val[m], pv[m]), "unit": u}
            for m, u in METRICS.items() if val[m] is not None]

    highlights: list[str] = []
    if val["revenue"] is not None:
        highlights.append(_moved("revenue", val["revenue"], pv["revenue"]))
    if val["gross_profit"] is not None:
        gp, gprev = val["gross_profit"], pv["gross_profit"]
        s = _moved("gross_profit", gp, gprev if gprev is None or gprev > 0 else None) if gp >= 0 else \
            f"Gross profit was negative at {money(gp)}"
        if val["revenue"]:
            s += f" (gross margin {gp / val['revenue'] * 100:.0f}%)"
        highlights.append(s)
    if val["net_profit"] is not None:
        highlights.append(_net(val["net_profit"], pv["net_profit"]))
    if val["cash"] is not None:
        highlights.append(_moved("cash", val["cash"], pv["cash"], up="rose"))
    if val["customers"] is not None:
        highlights.append(_moved("customers", val["customers"], pv["customers"]))
    if val["headcount"] is not None:
        highlights.append(_team(val["headcount"], pv["headcount"]))

    risks: list[str] = []
    chg = {k["metric"]: k["change_pct"] for k in kpis}
    if (chg.get("revenue") or 0) <= -5:
        risks.append(f"Revenue fell {_pct(chg['revenue'])} compared with the previous period.")
    n, pn = val["net_profit"], pv["net_profit"]
    if n is not None and pn is not None:
        if n < 0 < pn:
            risks.append("The business made a loss this period after a profit in the previous one.")
        elif n < 0 and pn < 0 and abs(n) >= abs(pn) * 1.1:
            risks.append("The net loss widened compared with the previous period.")
    if (chg.get("cash") or 0) <= -20:
        risks.append(f"Cash fell {_pct(chg['cash'])} in the period.")
    runway = _runway_months(cadence, val["cash"], val["net_profit"])
    if runway is not None and runway < 12:
        risks.append(f"At the current loss rate, cash covers about {max(runway, 0.1):.0f} months."
                     if runway >= 1 else "At the current loss rate, cash covers less than one month.")
    if (chg.get("customers") or 0) <= -5:
        risks.append(f"Customers fell {_pct(chg['customers'])}.")

    label = period_label(cadence, end)
    items = [_lower_first(h) for h in highlights[:3]]
    if not items:
        summary = f"No figures were entered for {label}."
    else:
        joined = items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]
        summary = f"In {label}, {joined}."
    title = f"{company.get('name') or company.get('ticker')}: {label[0].upper() + label[1:]} update"
    return {"title": title[:200],
            "body": {"summary": summary, "highlights": highlights, "risks": risks, "kpis": kpis,
                     "note": (note or "").strip()}}


# ------------------------------------------------------------------ canonical content + hash
def _iso(d: Any) -> str:
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


def canonical_body(body: dict | None) -> dict:
    b = body or {}
    kpis = [{"metric": str(k.get("metric")), "value": num(k.get("value")), "prev": num(k.get("prev")),
             "change_pct": num(k.get("change_pct")), "unit": str(k.get("unit") or "")}
            for k in (b.get("kpis") or [])]
    return {"summary": str(b.get("summary") or ""), "highlights": [str(x) for x in b.get("highlights") or []],
            "risks": [str(x) for x in b.get("risks") or []], "kpis": kpis, "note": str(b.get("note") or "")}


def canonical_update(u: dict, company: dict) -> dict:
    """What is hashed and recorded: the words and numbers investors read, plus which business and period."""
    return {
        "v": CANONICAL_VERSION,
        "type": "business_update",
        "ticker": company["ticker"],
        "company": company["name"],
        "cadence": u["cadence"],
        "period_start": _iso(u["period_start"]),
        "period_end": _iso(u["period_end"]),
        "title": u.get("title") or "",
        "body": canonical_body(u.get("body")),
    }


def canonical_text(u: dict, company: dict) -> str:
    return canonical_json(canonical_update(u, company))


def content_hash(u: dict, company: dict) -> str:
    return "0x" + hashlib.sha256(canonical_text(u, company).encode("utf-8")).hexdigest()


def disclosure_calldata(h: str) -> str:
    """0x + tag + 32-byte hash: the data field of the 0-value self-transaction on BlockID Chain."""
    hx = h[2:] if h.startswith("0x") else h
    if len(hx) != 64:
        raise ValueError("content hash must be 32 bytes")
    return "0x" + DISCLOSURE_TAG_HEX + hx.lower()
