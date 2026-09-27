#!/usr/bin/env python3
"""BlockID values itself: the first real case, run through the normal approved flow on the live stack.

  1. Valuation of https://eth.blockid.au with the real team (Do Van Long 80 %, Truong Quoc Tuan 20 %) and honest
     self-reported figures (no revenue, no customers yet) -> admin decision.
  2. Company "BlockID (to be incorporated as BlockID Pty Ltd)": 1,000,000 shares, Long 80 % / Tuan 20 %
     -> submit -> approve issue (BlockID EVM) -> approve anchor (Ethereum Hoodi + HashKey testnet).
  3. Offering: 100,000 new shares at the valuation price, max 10,000 per investor, max 45 holders (Pty cap),
     60 days, test money (mAUD) only -> submit -> approve. Left open so judges can join with "Try it now".
  4. The shared demo account reserves 5,000 shares, so the demo shows a live position.
Docs: docs/SELF-VALUATION.md. Re-running is safe: state is kept in ~/.blockid/self-case.json and reused.

Dry run by default (prints the plan, no sign-in, no writes). Real run:
  agents/.venv/bin/python scripts/blockid-self-case.py --apply --consent [--tuan-wallet 0x...] [--ticker BID]
Env: BLOCKID_BASE (default https://eth.blockid.au), DEMO_ADMIN_USER / DEMO_ADMIN_PASSWORD (default admin / admin).
Without --tuan-wallet a new wallet is created for Tuan's shares and its key saved to ~/.blockid/tuan-custody-wallet.json
(mode 600) until he gives his own address (then move the shares with an approved transfer).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

BASE = os.environ.get("BLOCKID_BASE", "https://eth.blockid.au").rstrip("/")
API = BASE + "/api"
STATE = Path.home() / ".blockid" / "self-case.json"
CUSTODY = Path.home() / ".blockid" / "tuan-custody-wallet.json"
LONG_WALLET = "0xc309691C60957A55bB619383A06d3F69A94f4585"  # owner MetaMask (docs memory: ADMIN_WALLETS)
NAME = "BlockID (to be incorporated as BlockID Pty Ltd)"
TOTAL_SHARES = 1_000_000
TICKERS = ["BID", "BLK", "BPP", "IDP"]
NOTE = ("Self-assessment by the BlockID team (first real case). Pre-revenue; product live on test networks. "
        "Testnet demo. Not an offer of securities or financial advice.")

TEAM = [
    {"full_name": "Do Van Long", "role": "Co-founder & CEO", "kind": "cofounder", "equity_pct": 80, "full_time": True,
     "headline": "Founder & CEO of Vietnam Blockchain Corporation and Auschain Pty Ltd",
     "urls": ["https://australiablockchain.au/post/5666448/ceo-of-vbc-achieved-i-star-2022",
              "https://vietnamblockchain.asia/", "https://australiablockchain.au/"],
     "bio": ("Founded Vietnam Blockchain Corporation in 2016 (blockchain solutions for agriculture, supply chain, "
             "fintech and public services) and Auschain Pty Ltd in Sydney. Built Agridential traceability. "
             "Recognised in I-Star 2022 among the top 10 supporters of startup activities. Built BlockID Business "
             "Passport and presented it at EAG Global Buildathon Sydney (Sep 2026).")},
    {"full_name": "Truong Quoc Tuan", "role": "Co-founder", "kind": "cofounder", "equity_pct": 20,
     "headline": "Investment professional, Dragon Capital Group",
     "urls": ["https://www.linkedin.com/in/tuantruong858/"],
     "bio": ("Investment background at Dragon Capital Group; studied at the University of Hawai'i Shidler College "
             "of Business; based in Sydney. Co-founder of BlockID, investor side of the product.")},
]
METRICS = {"revenue_ttm_aud": 0, "customers": 0, "employees": 2}


def log(msg: str) -> None:
    print(msg, flush=True)


def load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save_state(s: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=2))


def ok(r: httpx.Response, what: str, codes=(200, 201, 202)) -> dict:
    log(f"  {what}: {r.status_code} {r.text[:160]}")
    if r.status_code not in codes:
        sys.exit(f"FAILED at {what}: {r.status_code} {r.text[:400]}")
    return r.json() if r.content else {}


def client() -> httpx.Client:
    return httpx.Client(base_url=API, headers={"Origin": BASE}, timeout=90)


def admin() -> httpx.Client:
    c = client()
    ok(c.post("/v1/auth/login", json={"username": os.environ.get("DEMO_ADMIN_USER", "admin"),
                                      "password": os.environ.get("DEMO_ADMIN_PASSWORD", "admin")}), "admin sign-in")
    return c


def tuan_wallet(arg: str | None, apply: bool) -> str:
    if arg:
        return arg
    if CUSTODY.exists():
        return json.loads(CUSTODY.read_text())["address"]
    if not apply:
        return "<new custody wallet created on --apply>"
    from eth_account import Account

    acct = Account.create()
    CUSTODY.parent.mkdir(parents=True, exist_ok=True)
    CUSTODY.write_text(json.dumps({"address": acct.address, "private_key": acct.key.hex(),
                                   "note": "Holds Truong Quoc Tuan's BlockID shares until he gives his own wallet."}))
    CUSTODY.chmod(0o600)
    log(f"  created custody wallet for Tuan: {acct.address} (key in {CUSTODY}, mode 600)")
    return acct.address


def wait(c: httpx.Client, path: str, done: set[str], fail: set[str], field: str = "status", minutes: int = 40) -> dict:
    t0 = time.time()
    while time.time() - t0 < minutes * 60:
        d = c.get(path).json()
        st = d.get(field)
        log(f"  {int(time.time() - t0)}s {path} -> {st}")
        if st in done:
            return d
        if st in fail:
            sys.exit(f"FAILED: {path} is {st}: {json.dumps(d)[:400]}")
        time.sleep(15)
    sys.exit(f"TIMEOUT waiting for {path}")


def pick_ticker(a: httpx.Client, prefer: str | None) -> str:
    for tk in ([prefer] if prefer else []) + TICKERS:
        r = a.get("/v1/studio/tickers/check", params={"ticker": tk, "name": "BlockID"}).json()
        if r.get("ok"):
            return tk
        log(f"  ticker {tk}: {r.get('reason')}")
    sys.exit("no free ticker; pass --ticker XYZ")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="really run it (default: dry run)")
    ap.add_argument("--consent", action="store_true", help="both co-founders agree to the team check")
    ap.add_argument("--tuan-wallet")
    ap.add_argument("--ticker")
    ap.add_argument("--offer-shares", type=int, default=100_000)
    ap.add_argument("--demo-shares", type=int, default=5_000)
    args = ap.parse_args()
    st = load_state()
    tw = tuan_wallet(args.tuan_wallet, args.apply)
    log(f"Target {BASE} · state {st or '(new)'}")
    log(f"Team: Do Van Long 80 % -> {LONG_WALLET}; Truong Quoc Tuan 20 % -> {tw}")
    if not args.apply:
        log("DRY RUN. Steps: valuation (team + self-reported: revenue 0, customers 0, employees 2) -> approve -> "
            f"company '{NAME}' {TOTAL_SHARES:,} shares -> issue -> anchor -> offering {args.offer_shares:,} shares "
            f"(max 10,000 each, 45 holders, 60 days, test mAUD) -> demo reserves {args.demo_shares:,}. "
            "Re-run with --apply --consent.")
        return
    if not args.consent:
        sys.exit("--consent is required: both co-founders must agree to the team check (Privacy Act).")
    a = admin()

    # 1. valuation
    if not st.get("valuation_id"):
        body = {"url": BASE, "metrics": METRICS, "team": {"people": TEAM, "consent": True}}
        st["valuation_id"] = ok(a.post("/v1/studio/valuations", json=body), "start valuation")["id"]
        save_state(st)
    vid = st["valuation_id"]
    v = wait(a, f"/v1/studio/valuations/{vid}", {"waiting_approval", "approved"}, {"failed", "rejected"})
    if v["status"] == "waiting_approval":
        ok(a.post(f"/v1/studio/valuations/{vid}/decision", json={"approved": True, "reason": NOTE}), "approve valuation")
    svi = (a.get(f"/v1/studio/valuations/{vid}").json().get("result") or {}).get("svi") or {}
    mid = float(svi.get("valuation_mid_aud") or 0)
    log(f"  SVI {svi.get('index')} band {svi.get('band')} mid A${mid:,.0f}")

    # 2. company -> issue -> anchor
    if not st.get("company_id"):
        tk = pick_ticker(a, args.ticker)
        price = round(mid / TOTAL_SHARES, 4)
        body = {"valuation_id": vid, "name": NAME, "ticker": tk, "share_price_aud": price, "total_shares": TOTAL_SHARES,
                "holders": [{"name": "Do Van Long", "wallet": LONG_WALLET, "pct": 80},
                            {"name": "Truong Quoc Tuan", "wallet": tw, "pct": 20}]}
        c = ok(a.post("/v1/studio/companies", json=body), f"create company {tk} at A${price}/share")
        st.update(company_id=c["id"], ticker=tk)
        save_state(st)
    cid, tk = st["company_id"], st["ticker"]
    cur = a.get(f"/v1/companies/{tk}").json()
    if cur.get("status") == "draft":
        ok(a.post(f"/v1/studio/companies/{cid}/submit"), "submit")
        cur = a.get(f"/v1/companies/{tk}").json()
    if cur.get("status") == "pending_issue":  # ONE approval: issue on BlockID EVM, then Hoodi + HSK sync on their own
        ok(a.post(f"/v1/admin/companies/{cid}/approve-issue"), "approve issue")
    elif cur.get("status") in ("issued", "failed") and cur.get("local_block"):  # re-run: retry the public copies
        ok(a.post(f"/v1/admin/companies/{cid}/approve-anchor"), "retry anchor")
    wait(a, f"/v1/companies/{tk}", {"anchored"}, {"failed", "rejected"})

    # 3. offering (test money only)
    off = a.get(f"/v1/companies/{tk}/offering").json()
    o = off.get("offering")
    if not o or o["status"] not in ("open", "awaiting_settlement", "settling", "settled"):
        price = off["defaults"]["price_aud"]
        terms = {"price_aud": price, "shares_offered": args.offer_shares, "min_raise_aud": round(price * 10_000, 2),
                 "max_per_investor_shares": 10_000, "max_holders": 45,
                 "closes_at": (datetime.now(timezone.utc) + timedelta(days=60)).isoformat(),
                 "use_of_funds": ("Testnet demonstration round for BlockID (to be incorporated as BlockID Pty Ltd): "
                                  "product launch, first paying customers, legal set-up. Test money (mAUD) only; "
                                  "no real money moves. Not an offer of securities or financial advice.")}
        ok(a.put(f"/v1/companies/{tk}/offering", json=terms), f"offering terms {args.offer_shares:,} @ A${price}")
        o = ok(a.post(f"/v1/companies/{tk}/offering/submit"), "submit offering").get("offering") or {}
        if o.get("id"):
            ok(a.post(f"/v1/admin/offerings/{o['id']}/approve"), "approve offering")
        o = a.get(f"/v1/companies/{tk}/offering").json().get("offering") or {}
    st["offering_id"] = o.get("id")
    save_state(st)

    # 4. demo account joins
    d = client()
    ok(d.post("/v1/auth/demo"), "demo sign-in")
    mine = [x for x in d.get("/v1/me/reservations").json().get("reservations", [])
            if x.get("offering_id") == o.get("id") and x.get("status") in ("reserved", "allocated")]
    if o.get("status") == "open" and not mine:
        ok(d.post(f"/v1/offerings/{o['id']}/reservations",
                  json={"shares": args.demo_shares, "risk_ack": True, "name": "Demo investor"}),
           f"demo reserves {args.demo_shares:,}")

    log("\nDONE")
    log(f"  report      {BASE}/v/{vid}/report")
    log(f"  company     {BASE}/c/{tk}/overview")
    log(f"  offering    {BASE}/i/offerings/{o.get('id')}")
    log(f"  verify      {BASE}/verify/{tk}")
    log("  next: add the valuation id to BILLING_FREE_ALLOWLIST; set origin=self when the origin flag is deployed; "
        "point the Home 'We valued ourselves first' card at the report.")


if __name__ == "__main__":
    main()
