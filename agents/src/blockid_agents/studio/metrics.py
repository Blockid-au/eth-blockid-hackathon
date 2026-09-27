"""Marks, price changes and platform statistics (pure functions over studio rows).

mark = SVI-derived value per share: 1.00 at issuance (A$1 issue price), new_valuation / total_shares
after a revaluation. `mark_at(t)` is the latest mark at or before t; before the first mark the
first mark (or the issue price) is used, so young companies show change relative to issuance.
"""
from __future__ import annotations

import statistics
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from ..issuer import syncstate

ONCHAIN = ("issued", "pending_anchor", "anchoring", "anchored", "partially_anchored")


def f(x) -> float | None:
    if x is None:
        return None
    return float(x) if isinstance(x, (Decimal, int, float)) else float(Decimal(str(x)))


def _last_at(marks: list[dict], t: datetime, key: str):
    val = None
    for m in marks:  # sorted by at asc
        if m["at"] <= t:
            val = m[key]
        else:
            break
    return val


def mark_at(c: dict, marks: list[dict], t: datetime) -> float:
    v = _last_at(marks, t, "mark_aud")
    if v is None:
        v = marks[0]["mark_aud"] if marks else c.get("share_price_aud") or 1
    return f(v)


def valuation_at(c: dict, marks: list[dict], t: datetime) -> float | None:
    """None before the company existed on chain."""
    if t < issued_at(c, marks):
        return None
    v = _last_at(marks, t, "valuation_aud")
    return f(v if v is not None else c["valuation_aud"])


def issued_at(c: dict, marks: list[dict]) -> datetime:
    return marks[0]["at"] if marks else c["created_at"]


def pct_change(new: float, old: float) -> float:
    return round((new / old - 1) * 100, 2) if old else 0.0


def grade_letter(c: dict) -> str | None:
    g = (c.get("grade") or "").strip()
    return g[:1].upper() if g else None


def company_summary(c: dict, marks: list[dict], holders: int, now: datetime) -> dict:
    mark = mark_at(c, marks, now)
    spark = [round(mark_at(c, marks, _end_of(now.date() - timedelta(days=29 - i))), 4) for i in range(30)]
    return {
        "id": c["id"],
        "ticker": c["ticker"],
        "name": c["name"],
        "website": c.get("website"),
        "grade": grade_letter(c),
        "svi": f(c.get("svi")),
        "valuation_aud": f(c["valuation_aud"]),
        "share_price_aud": f(c.get("share_price_aud")),
        "total_shares": int(c["total_shares"]),
        "mark_aud": round(mark, 4),
        "change_7d": pct_change(mark, mark_at(c, marks, now - timedelta(days=7))),
        "change_30d": pct_change(mark, mark_at(c, marks, now - timedelta(days=30))),
        "spark_30d": spark,
        "holders": holders,
        "status": c["status"],
        "local_token": c.get("local_token"),
        "hoodi_token": c.get("hoodi_token"),
        "hsk_token": c.get("hsk_token"),
        "anchored": c["status"] == "anchored" or bool(c.get("hoodi_anchor_tx")),
        "sync": syncstate.view(c),
    }


def _end_of(d: date) -> datetime:
    return datetime.combine(d, time.max, tzinfo=timezone.utc)


EVENT_TEXT = {
    "issued": "shares issued",
    "kyc": "investor KYC-registered",
    "drip": "gas drip",
    "minted": "new shares minted",
    "valuation_anchored": "valuation anchored on BlockID Chain",
    "revalued": "revalued",
    "hoodi_mirrored": "cap table mirrored to Hoodi",
    "hsk_mirrored": "cap table mirrored to HashKey Chain",
    "anchored": "cap table anchored",
    "deployed": "contract deployed",
    "sync_started": "chain sync started",
    "sync_failed": "chain sync failed",
    "sync_skipped": "chain sync skipped",
    "submitted": "submitted for approval",
    "issue_approved": "issuance approved",
    "resync_requested": "re-sync requested",
    "refresh_requested": "refresh from chain requested",
    "refreshed": "cap table refreshed from BlockID Chain",
    "dividend_created": "dividend round created",
    "dividend_claimed": "dividend claimed",
    "mint_requested": "mint requested",
    "rejected": "rejected",
    "update_published": "business update published",
}


def event_text(e: dict) -> str:
    d = e.get("data") or {}
    if d.get("text"):
        return str(d["text"])
    base = EVENT_TEXT.get(e["kind"], e["kind"].replace("_", " "))
    if e["kind"] in ("issued", "minted") and d.get("shares"):
        return f"{int(d['shares']):,} shares to {d.get('name') or d.get('wallet', '')}".strip()
    if e["kind"] == "revalued" and d.get("mark_aud"):
        return f"revalued to A${float(d['mark_aud']):.4f}/share"
    if e["kind"] == "anchored":
        return f"cap table anchored on {syncstate.LABELS.get(str(e.get('chain')), e.get('chain') or 'Hoodi')}"
    if e["kind"] == "deployed" and d.get("contract"):
        return f"{d['contract']} deployed on {syncstate.LABELS.get(str(e.get('chain')), e.get('chain') or '')}"
    if e["kind"] in ("sync_failed", "sync_skipped") and d.get("error"):
        return f"{syncstate.LABELS.get(str(e.get('chain')), e.get('chain'))}: {d['error']}"[:300]
    if e["kind"] == "update_published" and d.get("title"):
        return f"business update published: {d['title']}"[:300]
    if e["kind"] == "dividend_created" and d.get("total_units"):
        return f"dividend round {int(d['total_units']) / 1e6:,.2f} mAUD"
    return base


def platform_stats(companies: list[dict], marks: dict[int, list[dict]], holders: dict[int, int],
                   events: list[dict], mints: list[dict], dividends: list[dict], block: int | None,
                   now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    live = [c for c in companies if c["status"] in ONCHAIN]
    sums = [company_summary(c, marks.get(c["id"], []), holders.get(c["id"], 0), now) for c in live]
    by_id = {c["id"]: c for c in companies}

    vals = [s["valuation_aud"] for s in sums]
    tx_value = sum(int(c["total_shares"]) * f(c.get("share_price_aud") or 1) for c in live)
    for m in mints:
        if m["status"] == "minted" and m["company_id"] in by_id:
            c = by_id[m["company_id"]]
            tx_value += int(m["shares"]) * mark_at(c, marks.get(c["id"], []), m["created_at"])
    tx_value += sum(int(d["total_units"]) for d in dividends if d["status"] == "paid") / 1e6

    days = [now.date() - timedelta(days=364 - i) for i in range(365)]
    value_series, count_series = [], []
    for d in days:
        t = _end_of(d)
        v = [valuation_at(c, marks.get(c["id"], []), t) for c in live]
        v = [x for x in v if x is not None]
        value_series.append(round(sum(v), 2))
        count_series.append(len(v))

    grades = {g: 0 for g in "ABCDE"}
    for s in sums:
        if s["grade"] in grades:
            grades[s["grade"]] += 1

    movers = sorted(sums, key=lambda s: -abs(s["change_30d"]))[:10]
    activity = []
    for e in events:
        c = by_id.get(e.get("company_id"))
        if c is None or c["status"] not in ONCHAIN:
            continue
        activity.append({"at": e["at"], "ticker": c["ticker"] if c else None, "kind": e["kind"],
                         "text": event_text(e), "tx_hash": e.get("tx_hash"), "chain": e.get("chain")})

    return {
        "as_of": now.isoformat(),
        "block": block,
        "kpis": {
            "companies": len(live),
            "tokens": sum(1 for c in live if c.get("local_token")) + sum(1 for c in live if c.get("hoodi_token"))
            + sum(1 for c in live if c.get("hsk_token")),
            "shares": sum(int(c["total_shares"]) for c in live),
            "tx_value_aud": round(tx_value, 2),
            "total_valuation_aud": round(sum(vals), 2),
            "avg_valuation_aud": round(sum(vals) / len(vals), 2) if vals else 0,
            "median_valuation_aud": round(statistics.median(vals), 2) if vals else 0,
            "avg_mark": round(sum(s["mark_aud"] for s in sums) / len(sums), 4) if sums else 0,
            "anchored": sum(1 for s in sums if s["anchored"]),
            "anchored_total": len(live),
        },
        "series": {"days": [d.isoformat() for d in days], "value_aud": value_series, "companies": count_series},
        "grades": grades,
        "movers": [{"ticker": s["ticker"], "name": s["name"], "change_30d": s["change_30d"]} for s in movers],
        "activity": activity,
    }
