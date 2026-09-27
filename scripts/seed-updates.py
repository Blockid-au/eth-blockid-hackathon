#!/usr/bin/env python3
"""Seed business updates for demo companies over the public API (admin account), end to end:

  for each ticker: enter a baseline month + 3 monthly KPI periods with growing numbers -> prepare one monthly
  update per period (drafted by code from the numbers) -> send for approval -> approve (admin) -> wait until the
  issuer has recorded its fingerprint on BlockID Chain (status 'published', tx on scan.blockid.au).

The numbers are SAMPLE figures derived from each company's approved valuation (deterministic per ticker), and every
update carries a note saying so. Re-running is safe: published periods are skipped, pending ones are approved.

Usage (from the repo root, with the agents venv):
  agents/.venv/bin/python scripts/seed-updates.py CNV EBA [--months 3] [--end 2026-08-31] [--dry-run]
Env: BLOCKID_BASE (default https://eth.blockid.au), DEMO_ADMIN_USER / DEMO_ADMIN_PASSWORD (default admin / admin).
"""
from __future__ import annotations

import argparse
import calendar
import datetime as dt
import hashlib
import os
import random
import sys
import time

import httpx

BASE = os.environ.get("BLOCKID_BASE", "https://eth.blockid.au").rstrip("/")
API = BASE + "/api"
SCAN = "https://scan.blockid.au/tx/"
NOTE = "Sample figures for the testnet demo, generated for illustration. Not the company's real results."


def admin_session() -> httpx.Client:
    c = httpx.Client(base_url=API, headers={"Origin": BASE}, timeout=60)
    r = c.post("/v1/auth/login", json={"username": os.environ.get("DEMO_ADMIN_USER", "admin"),
                                        "password": os.environ.get("DEMO_ADMIN_PASSWORD", "admin")})
    r.raise_for_status()
    if r.json().get("must_change"):
        sys.exit("the admin account must change its password first")
    if BASE.startswith("http://"):  # local runs: the session cookie is Secure, so send it by hand
        c.headers["Cookie"] = next(v.split(";")[0] for k, v in r.headers.multi_items()
                                   if k.lower() == "set-cookie" and "bid_session=" in v.split(";")[0])
    return c


def month_ends(last: dt.date, n: int) -> list[dt.date]:
    out, d = [], last
    for _ in range(n):
        out.append(d)
        d = d.replace(day=1) - dt.timedelta(days=1)
    return out[::-1]


def last_month_end(today: dt.date) -> dt.date:
    return today.replace(day=1) - dt.timedelta(days=1)


def sample_kpis(ticker: str, valuation_aud: float, n_periods: int) -> list[dict]:
    """Deterministic, plausible monthly figures that grow: revenue ~ valuation / 20 per year."""
    rnd = random.Random(int(hashlib.sha256(ticker.encode()).hexdigest()[:12], 16))
    rev = max(valuation_aud / 20 / 12, 20_000) * rnd.uniform(0.8, 1.2)
    gm = rnd.uniform(0.55, 0.8)
    net_margin = rnd.choice([-1, 1]) * rnd.uniform(0.04, 0.14)  # clearly a loss or a profit, never ~0
    cash = rev * rnd.uniform(8, 14)
    arpu = rnd.choice([40, 120, 600, 2500])
    customers = max(rev / arpu, 12)
    team = max(rev * 12 / 260_000, 3)
    out = []
    for _ in range(n_periods):
        g = rnd.uniform(0.02, 0.09)
        rev *= 1 + g
        gm = min(0.85, gm + rnd.uniform(-0.01, 0.015))
        net_margin = min(0.25, net_margin + rnd.uniform(0.0, 0.02))
        if -0.03 < net_margin < 0.03:
            net_margin = 0.03
        net = rev * net_margin
        cash = max(cash + net + rev * rnd.uniform(-0.2, 0.3), rev)
        customers *= 1 + g + rnd.uniform(-0.01, 0.02)
        team += rnd.choice([0, 0, 1, 1, 2]) * max(1, round(team / 40))
        out.append({"revenue": round(rev), "gross_profit": round(rev * gm), "net_profit": round(net),
                    "cash": round(cash), "customers": round(customers), "headcount": round(team)})
    return out


def wait_published(c: httpx.Client, uid: str, timeout: float = 120) -> dict:
    t0 = time.time()
    while True:
        u = c.get(f"/v1/updates/{uid}").json()
        if u["status"] in ("published", "failed", "rejected") or time.time() - t0 > timeout:
            return u
        time.sleep(2)


def seed(c: httpx.Client, tk: str, ends: list[dt.date], dry: bool) -> None:
    r = c.get(f"/v1/companies/{tk}")
    if r.status_code != 200:
        print(f"{tk}: unknown or not public ({r.status_code}); skipped")
        return
    co = r.json()
    existing = {(u["cadence"], u["period_end"]): u for u in c.get(f"/v1/companies/{tk}/updates").json()["updates"]}
    figures = sample_kpis(tk, float(co["valuation_aud"]), len(ends) + 1)
    baseline_end = ends[0].replace(day=1) - dt.timedelta(days=1)
    print(f"{tk} · {co['name']} · valuation A${co['valuation_aud']:,.0f}")
    if dry:
        for end, k in zip([baseline_end, *ends], figures):
            print(f"  {end}  {k}")
        return
    r = c.put(f"/v1/companies/{tk}/kpis", json={"period_end": baseline_end.isoformat(), "values": figures[0]})
    r.raise_for_status()
    print(f"  baseline {baseline_end}: figures entered")
    for end, k in zip(ends, figures[1:]):
        key = ("monthly", end.isoformat())
        prev = existing.get(key)
        if prev and prev["status"] == "published":
            print(f"  {end}: already published ({prev['id']}); skipped")
            continue
        if prev and prev["status"] in ("pending_approval", "publishing"):
            uid = prev["id"]
        else:
            r = c.post(f"/v1/companies/{tk}/updates", json={"cadence": "monthly", "period_end": end.isoformat(),
                                                            "kpis": k, "note": NOTE})
            if r.status_code != 201:
                print(f"  {end}: prepare failed {r.status_code} {r.text[:200]}")
                continue
            u = r.json()
            uid = u["id"]
            print(f"  {end}: draft {uid} · {u['title']}")
            print(f"           {u['body']['summary']}")
            r = c.post(f"/v1/updates/{uid}/submit")
            r.raise_for_status()
        if prev is None or prev["status"] != "publishing":
            r = c.post(f"/v1/admin/updates/{uid}/approve")
            if r.status_code != 202:
                print(f"  {end}: approve failed {r.status_code} {r.text[:200]}")
                continue
        u = wait_published(c, uid)
        tx = (u.get("anchor") or {}).get("tx_hash")
        print(f"  {end}: {u['status']}" + (f" · {SCAN}{tx}" if tx else f" · {u.get('error') or ''}"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tickers", nargs="+")
    ap.add_argument("--months", type=int, default=3)
    ap.add_argument("--end", type=dt.date.fromisoformat, help="last period end (default: end of last month)")
    ap.add_argument("--dry-run", action="store_true", help="print the figures, change nothing")
    a = ap.parse_args()
    last = a.end or last_month_end(dt.date.today())
    if last.day != calendar.monthrange(last.year, last.month)[1]:
        sys.exit("--end must be the last day of a month")
    ends = month_ends(last, a.months)
    c = admin_session()
    print(f"{BASE} · periods {', '.join(e.isoformat() for e in ends)}")
    for tk in a.tickers:
        seed(c, tk.upper(), ends, a.dry_run)


if __name__ == "__main__":
    main()
