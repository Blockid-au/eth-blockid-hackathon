#!/usr/bin/env python3
"""End-to-end demo data for the shared demo investor (DEMO_WALLET), through the normal approved flows, then checks.

Run after scripts/seed-demo-account.py (shares + an EBA dividend) and scripts/seed-updates.py EBA CNV GAA:
  1. SETTLE ticker (default BLC): an offering is opened (admin sets terms, submits, approves), the demo account
     reserves shares, the offering is closed early and settled -> the issuer mints the shares to the demo wallet.
  2. OPEN ticker (default EBA): an offering is opened and left open, and the demo account reserves shares in it,
     so anyone who presses "Try it now" can also join as a shareholder.
  3. Checks what the demo account shows: holdings, updates, dividends, reservations, offerings.
Re-running is safe: an offering already in progress is reused.

Usage: agents/.venv/bin/python scripts/demo-full-flow.py [--settle BLC] [--open EBA] [--check-only]
Env: BLOCKID_BASE (default https://eth.blockid.au), DEMO_ADMIN_USER / DEMO_ADMIN_PASSWORD (default admin / admin).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx

BASE = os.environ.get("BLOCKID_BASE", "https://eth.blockid.au").rstrip("/")
API = BASE + "/api"
FAILS: list[str] = []


def client() -> httpx.Client:
    return httpx.Client(base_url=API, headers={"Origin": BASE}, timeout=60)


def admin() -> httpx.Client:
    c = client()
    r = c.post("/v1/auth/login", json={"username": os.environ.get("DEMO_ADMIN_USER", "admin"),
                                        "password": os.environ.get("DEMO_ADMIN_PASSWORD", "admin")})
    r.raise_for_status()
    return c


def demo() -> httpx.Client:
    c = client()
    r = c.post("/v1/auth/demo")
    r.raise_for_status()
    print("demo session", r.json()["address"])
    return c


def ok(r: httpx.Response, what: str, codes=(200, 201, 202)) -> dict:
    print(f"  {what}: {r.status_code} {r.text[:140]}")
    if r.status_code not in codes:
        FAILS.append(f"{what}: {r.status_code} {r.text[:200]}")
        return {}
    return r.json() if r.content else {}


def open_offering(a: httpx.Client, tk: str, shares: int, per_investor: int, days: int, use: str) -> dict:
    """Current offering of `tk`, opened (terms -> submit -> approve) if there is none in progress."""
    cur = a.get(f"/v1/companies/{tk}/offering").json()
    o = cur.get("offering")
    if o and o["status"] in ("open", "awaiting_settlement", "settling"):
        print(f"{tk}: offering {o['id']} already {o['status']}")
        return o
    price = cur["defaults"]["price_aud"]
    terms = {"price_aud": price, "shares_offered": shares, "min_raise_aud": round(price * per_investor / 10, 2),
             "max_per_investor_shares": per_investor,
             "closes_at": (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(),
             "use_of_funds": use}
    print(f"{tk}: opening an offering of {shares:,} shares at A${price}")
    ok(a.put(f"/v1/companies/{tk}/offering", json=terms), "terms")
    o = ok(a.post(f"/v1/companies/{tk}/offering/submit"), "submit").get("offering") or {}
    if o.get("id"):
        o = ok(a.post(f"/v1/admin/offerings/{o['id']}/approve"), "approve")
    return a.get(f"/v1/companies/{tk}/offering").json().get("offering") or {}


def reserve(d: httpx.Client, o: dict, shares: int) -> None:
    mine = [x for x in d.get("/v1/me/reservations").json().get("reservations", [])
            if x.get("offering_id") == o["id"] and x.get("status") in ("reserved", "allocated")]
    if mine:
        print(f"  demo already reserved {mine[0].get('shares')} shares in offering {o['id']}")
        return
    ok(d.post(f"/v1/offerings/{o['id']}/reservations",
              json={"shares": shares, "risk_ack": True, "name": "Demo investor"}), f"reserve {shares:,}")


def settle(a: httpx.Client, d: httpx.Client, tk: str) -> None:
    o = open_offering(a, tk, 200_000, 50_000, 30, "Demo round: product build-out and first pilot customers (testnet).")
    if not o:
        return
    if o["status"] == "open":
        reserve(d, o, 25_000)
        o = ok(a.post(f"/v1/admin/offerings/{o['id']}/close"), "close early")
    if o.get("status") == "awaiting_settlement":
        ok(a.post(f"/v1/admin/offerings/{o['id']}/settle"), "settle")
        t0 = time.time()
        while time.time() - t0 < 900:
            time.sleep(15)
            cur = a.get(f"/v1/offerings/{o['id']}").json()
            status = cur.get("status")
            s = a.get(f"/v1/companies/{tk}").json().get("sync") or {}
            print(f"  {int(time.time() - t0)}s offering {status} · sync {s.get('step') or 'idle'}")
            if status == "settled" and not s.get("step"):  # minted, and the public copies re-synced
                break
            if status == "failed":
                FAILS.append(f"{tk} settlement failed: {cur}")
                break


def check(d: httpx.Client, expect: list[str]) -> None:
    print("checks (what 'Try it now' shows)")
    h = d.get("/v1/demo/holdings").json()
    held = {p["ticker"]: p for p in h.get("positions", [])}
    for tk in expect:
        p = held.get(tk)
        print(f"  holding {tk}: " + (f"{p['shares']:,} shares, {p['pct']:.4f}%, A${p['value_aud']:,.0f}" if p else "MISSING"))
        if not p:
            FAILS.append(f"demo wallet holds no {tk}")
    u = d.get("/v1/demo/updates").json().get("updates", [])
    print(f"  updates: {len(u)} published")
    if not u:
        FAILS.append("no published updates for the demo portfolio")
    dv = d.get("/v1/demo/dividends").json()
    print(f"  dividends: {len(dv.get('paid', []))} paid, {len(dv.get('upcoming', []))} upcoming, "
          f"total {dv.get('total_maud')} mAUD")
    if not dv.get("paid") and not dv.get("upcoming"):
        FAILS.append("no dividends for the demo portfolio")
    r = d.get("/v1/me/reservations").json().get("reservations", [])
    print(f"  reservations: {[(x.get('ticker'), x.get('shares'), x.get('status')) for x in r]}")
    offs = d.get("/v1/offerings").json().get("offerings", [])
    print(f"  offerings: {[(x.get('ticker'), x.get('status')) for x in offs]}")
    if not any(x.get("status") == "open" for x in offs):
        FAILS.append("no open offering to join")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--settle", default="BLC")
    ap.add_argument("--open", default="EBA")
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()
    a, d = admin(), demo()
    if not args.check_only:
        settle(a, d, args.settle)
        o = open_offering(a, args.open, 500_000, 100_000, 60,
                          "Grow the investor platform: pilots with Australian and Vietnamese businesses (testnet).")
        if o.get("status") == "open":
            reserve(d, o, 20_000)
    check(d, ["EBA", "CNV", "GAA", args.settle])
    print("\nRESULT:", "PASS" if not FAILS else "FAIL")
    for f in FAILS:
        print("  -", f)
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
