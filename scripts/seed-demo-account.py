#!/usr/bin/env python3
"""Give the shared demo investor account (DEMO_WALLET) something to show.

Runs against the live API with the admin/admin demo login, through the normal admin-approved flows:
  1. (no company role: the demo account is shared with every visitor, so it never becomes a company owner /
     manager — it would be able to approve requests; see CompanyAuthz.check_approver);
  2. requests and approves share mints to the demo wallet (the issuer registers KYC and re-syncs the mirrors:
     each mint costs one Hoodi + one HashKey sync, so keep the list short while HSK gas is low);
  3. requests and approves a dividend on EBA, so the demo portfolio shows dividends received.

Re-running skips companies the demo wallet already holds.

Usage: agents/.venv/bin/python scripts/seed-demo-account.py [--no-dividend]
"""
import sys
import time

import httpx

API = "https://eth.blockid.au/api"
DEMO = "0xFCC187E60719aE3E810Ca40A5F1Cf5309cC3cc0D"
MINTS = [("EBA", 100_000), ("CNV", 50_000), ("GAA", 20_000)]
DIVIDEND = ("EBA", 20_000)  # mAUD, pro-rata to every EBA holder


def main() -> None:
    c = httpx.Client(base_url=API, headers={"Origin": "https://eth.blockid.au"}, timeout=60)
    r = c.post("/v1/auth/login", json={"username": "admin", "password": "admin"})
    r.raise_for_status()
    held = {p["ticker"] for p in c.get("/v1/demo/holdings").json().get("positions", [])}
    for tk, n in MINTS:
        if tk in held:  # re-running is safe: no second allocation
            print("mint", tk, "skipped: the demo wallet already holds", tk)
            continue
        r = c.post(f"/v1/companies/{tk}/mints", json={"to_wallet": DEMO, "holder_name": "Demo investor", "shares": n,
                                                      "reason": "Demo investor allocation (testnet)"})
        print("mint", tk, n, r.status_code, r.text[:160])
        if r.status_code == 201:
            before = (c.get(f"/v1/companies/{tk}").json().get("sync") or {}).get("started_at")
            a = c.post(f"/v1/admin/mints/{r.json()['id']}/approve")
            print("  approve", a.status_code, a.text[:160])
            wait_minted(c, tk, before)
    if "--no-dividend" not in sys.argv:
        tk, total = DIVIDEND
        r = c.post(f"/v1/companies/{tk}/dividends", json={"total_maud": total})
        print("dividend", tk, total, r.status_code, r.text[:160])
        if r.status_code == 201:
            a = c.post(f"/v1/admin/dividends/{r.json()['id']}/approve")
            print("  approve", a.status_code, a.text[:160])
    time.sleep(20)
    h = c.get("/v1/demo/holdings").json()
    for p in h["positions"]:
        print(f"{p['ticker']}: {p['shares']} shares, {p['pct']:.4f}%, A${p['value_aud']:,.0f}, dividends {p['dividends_maud']}")


def wait_minted(c: httpx.Client, tk: str, before: str | None, timeout: int = 600) -> None:
    """Wait until the demo wallet holds `tk` and the re-sync of the public copies has finished."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(10)
        s = c.get(f"/v1/companies/{tk}").json().get("sync") or {}
        held = {p["ticker"] for p in c.get("/v1/demo/holdings").json().get("positions", [])}
        if tk in held and not s.get("step"):  # minted on BlockID Chain and the public copies re-synced
            print("  synced", {k: s.get(k) for k in ("blockid", "hoodi", "hsk")})
            return
    print("  still syncing after", timeout, "s")


if __name__ == "__main__":
    main()
