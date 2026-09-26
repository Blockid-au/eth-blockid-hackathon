#!/usr/bin/env python3
"""Full end-to-end demo on the live BlockID stack, from zero to the last step, with a complete log.

  valuation (AI agents) -> admin approves -> ticker + shareholders -> one issuance approval
  -> BlockID EVM register + Hoodi + HashKey sync -> /verify -> new round (mint) -> dividend (relayer claims)
  -> new investor KYC -> shareholder transfer signed by the holder's own wallet -> revaluations over time

Every approval is given by the demo admin account (the script plays founder, holders and admin). Holder wallets
are generated here and their keys kept in ~/.blockid/demo-wallets.json (testnet only, never committed).
Output: docs/demo-run/<TICKER>-<date>.md|json and web/app/public/demo-run/latest.md|json (served at /demo-run/).

Usage (from the repo root, with the agents venv):
  agents/.venv/bin/python scripts/demo_e2e.py --url https://www.canva.com --name Canva [--revenue-aud 3900000000]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import time

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

BASE = os.environ.get("BLOCKID_BASE", "https://eth.blockid.au")
API = BASE + "/api"
LOCAL_RPC = os.environ.get("LOCAL_RPC_URL", "http://127.0.0.1:8545")
SCAN, HOODI_SCAN, HSK_SCAN = "https://scan.blockid.au", "https://hoodi.etherscan.io", "https://testnet-explorer.hskchain.net"
ROOT = pathlib.Path(__file__).resolve().parent.parent
WALLETS = pathlib.Path.home() / ".blockid" / "demo-wallets.json"
ERC20 = [{"name": "transfer", "type": "function", "stateMutability": "nonpayable",
          "inputs": [{"name": "to", "type": "address"}, {"name": "value", "type": "uint256"}], "outputs": [{"type": "bool"}]},
         {"name": "balanceOf", "type": "function", "stateMutability": "view",
          "inputs": [{"name": "a", "type": "address"}], "outputs": [{"type": "uint256"}]}]


# ------------------------------------------------------------------ log
class RunLog:
    def __init__(self):
        self.t0 = time.time()
        self.steps: list[dict] = []

    def step(self, title: str, **data):
        e = {"n": len(self.steps) + 1, "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
             "elapsed_s": round(time.time() - self.t0, 1), "title": title, **data}
        self.steps.append(e)
        print(f"[{e['elapsed_s']:7.1f}s] {e['n']:02d}. {title}", flush=True)
        for k, v in data.items():
            if k != "raw":
                print(f"            {k}: {json.dumps(v, ensure_ascii=False)[:300]}", flush=True)
        return e


def tx_links(events: list[dict]) -> list[str]:
    out = []
    for ev in events:
        h, ch = ev.get("tx_hash"), ev.get("chain")
        if not h:
            continue
        base = {"blockid": SCAN, "hoodi": HOODI_SCAN, "hsk": HSK_SCAN}.get(ch, SCAN)
        out.append(f"{ev.get('kind')} ({ch}): {base}/tx/{h}")
    return out


# ------------------------------------------------------------------ http + auth
def client() -> httpx.Client:
    return httpx.Client(base_url=API, headers={"Origin": BASE}, timeout=90)


def admin_session() -> httpx.Client:
    c = client()
    r = c.post("/v1/auth/login", json={"username": os.environ.get("DEMO_ADMIN_USER", "admin"),
                                        "password": os.environ.get("DEMO_ADMIN_PASSWORD", "admin")})
    r.raise_for_status()
    return c


def siwe_session(acct) -> httpx.Client:
    """Sign in exactly like MetaMask does: EIP-4361 message, personal_sign."""
    c = client()
    nonce = c.get("/v1/auth/nonce").json()["nonce"]
    now = dt.datetime.now(dt.timezone.utc)
    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"  # noqa: E731
    msg = (f"eth.blockid.au wants you to sign in with your Ethereum account:\n{acct.address}\n\n"
           f"Sign in to BlockID Startup Passport.\n\nURI: https://eth.blockid.au\nVersion: 1\nChain ID: 262626\n"
           f"Nonce: {nonce}\nIssued At: {iso(now)}\nExpiration Time: {iso(now + dt.timedelta(minutes=10))}")
    sig = Account.sign_message(encode_defunct(text=msg), acct.key).signature.hex()
    r = c.post("/v1/auth/siwe", json={"message": msg, "signature": sig if sig.startswith("0x") else "0x" + sig})
    r.raise_for_status()
    return c


def ok(r: httpx.Response) -> dict:
    if r.status_code >= 400:
        raise SystemExit(f"HTTP {r.status_code} {r.request.method} {r.request.url}: {r.text[:500]}")
    return r.json() if r.content else {}


def poll(fn, done, timeout: float = 900, every: float = 5, label: str = ""):
    t = time.time()
    while True:
        v = fn()
        if done(v):
            return v
        if time.time() - t > timeout:
            raise SystemExit(f"timeout waiting for {label}")
        time.sleep(every)


# ------------------------------------------------------------------ wallets
def demo_wallets(names: list[str]) -> dict:
    data = json.loads(WALLETS.read_text()) if WALLETS.exists() else {}
    for n in names:
        if n not in data:
            a = Account.create()
            data[n] = {"address": a.address, "key": a.key.hex()}
    WALLETS.parent.mkdir(parents=True, exist_ok=True)
    WALLETS.write_text(json.dumps(data, indent=2))
    os.chmod(WALLETS, 0o600)
    return {n: Account.from_key(data[n]["key"]) for n in names}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--revenue-aud", type=float, default=None, help="optional self-reported revenue (TTM, A$)")
    ap.add_argument("--dividend-maud", type=int, default=100_000)
    args = ap.parse_args()
    log = RunLog()
    admin = admin_session()
    W = demo_wallets(["founder", "cofounder", "esop", "series_a", "buyer"])
    log.step("Demo wallets ready (holders sign with their own keys)",
             wallets={k: v.address for k, v in W.items()})

    # 1. valuation
    body = {"url": args.url}
    if args.revenue_aud:
        body["metrics"] = {"revenue_ttm_aud": args.revenue_aud}
    vid = ok(admin.post("/v1/studio/valuations", json=body))["id"]
    log.step("Valuation requested (AI agents start)", valuation_id=vid, url=args.url, self_reported=body.get("metrics"))
    v = poll(lambda: ok(admin.get(f"/v1/studio/valuations/{vid}")),
             lambda x: x["status"] in ("waiting_approval", "failed"), timeout=1200, every=10, label="valuation")
    if v["status"] == "failed":
        raise SystemExit(f"valuation failed: {v.get('error')}")
    svi = v["svi"]
    log.step("Valuation ready — waiting for admin",
             agent_steps=[f"{s['key']}: {s['detail']}" for s in v["steps"]],
             searches=[f"{s.get('kind')}: {s.get('query')} ({s.get('provider')})" for s in v.get("searches") or []],
             competitors=[c["name"] for c in v.get("competitors") or []],
             svi=f"{svi['index']} ({svi['band']})",
             range_aud=[svi["valuation_low_aud"], svi["valuation_mid_aud"], svi["valuation_high_aud"]],
             method=svi["method"], llm=v.get("llm_providers_used"), warnings=v.get("warnings"),
             report=f"{BASE}/v/{vid}")
    ok(admin.post(f"/v1/studio/valuations/{vid}/decision", json={"approved": True}))
    log.step("Admin approved the valuation (human gate 1)")

    # 2. ticker + holders
    cands = ok(admin.get("/v1/studio/tickers/suggest", params={"name": args.name}))["candidates"]
    ticker = next(c["ticker"] for c in cands if c["available"])
    holders = [{"name": "Founder", "wallet": W["founder"].address, "pct": 50},
               {"name": "Co-founder", "wallet": W["cofounder"].address, "pct": 30},
               {"name": "ESOP pool", "wallet": W["esop"].address, "pct": 20}]
    co = ok(admin.post("/v1/studio/companies", json={"valuation_id": vid, "name": args.name, "ticker": ticker,
                                                     "holders": holders}))
    ok(admin.post(f"/v1/studio/companies/{co['id']}/submit"))
    log.step("Company created and submitted", ticker=ticker, ticker_candidates=[c["ticker"] for c in cands],
             total_shares=co["total_shares"], share_price_aud=co.get("share_price_aud", 1),
             holders=[f"{h['name']} {h['pct']}% {h['wallet']}" for h in holders])

    # 3. one issuance approval -> BlockID -> Hoodi -> HashKey
    ok(admin.post(f"/v1/admin/companies/{co['id']}/approve-issue"))
    log.step("Admin approved issuance (human gate 2) — issuer runs all chains")
    seen = set()

    def watch():
        d = ok(admin.get(f"/v1/companies/{ticker}"))
        st = (d.get("sync") or {}).get("step") or {}
        key = (d["status"], st.get("chain"), st.get("action"), st.get("n"))
        if key not in seen:
            seen.add(key)
            print(f"            … {d['status']} {st.get('chain') or ''} {st.get('action') or ''} {st.get('n') or ''}", flush=True)
        return d

    d = poll(watch, lambda x: x["status"] in ("anchored", "partially_anchored", "failed"), timeout=1500, every=4,
             label="issuance")
    log.step("Issued on BlockID EVM and synced", status=d["status"], sync={k: d["sync"].get(k) for k in ("blockid", "hoodi", "hsk")},
             tokens={"blockid": d["local"]["token"], "hoodi": (d.get("hoodi") or {}).get("token"), "hsk": (d.get("hsk") or {}).get("token")},
             explorers=[f"{SCAN}/token/{d['local']['token']}", f"{HOODI_SCAN}/token/{(d.get('hoodi') or {}).get('token')}",
                        f"{HSK_SCAN}/address/{(d.get('hsk') or {}).get('token')}"],
             transactions=tx_links(d.get("events") or [])[:40])
    vf = ok(admin.get(f"/v1/verify/{ticker}"))
    log.step("Report hash verified on all chains", report_hash=vf["report_hash"],
             onchain={x["chain"]: x["match"] for x in vf["onchain"]}, page=f"{BASE}/verify/{ticker}")

    # 4. new round: mint to a new investor (KYC + issue by the issuer)
    supply = d["total_shares"]
    new_shares = max(1, supply // 10)
    m = ok(admin.post(f"/v1/companies/{ticker}/mints", json={"to_wallet": W["series_a"].address, "holder_name": "Series A fund",
                                                            "shares": new_shares, "reason": "Series A round (demo)"}))
    ok(admin.post(f"/v1/admin/mints/{m['id']}/approve"))
    d = poll(lambda: ok(admin.get(f"/v1/companies/{ticker}")), lambda x: x["total_shares"] == supply + new_shares,
             timeout=900, label="mint")
    log.step("New round minted (dilution) and re-anchored", new_shares=new_shares, total_shares=d["total_shares"],
             cap_table=[f"{h['name']}: {h['shares']:,} ({h['pct']:.2f}%)" for h in d["cap_table"]])

    # 5. dividend: pro-rata Merkle round in mAUD, relayer claims for every holder (holders pay no gas)
    n_claim0 = sum(1 for e in d["events"] if e["kind"] == "dividend_claimed")
    dv = ok(admin.post(f"/v1/companies/{ticker}/dividends", json={"total_maud": args.dividend_maud}))
    ok(admin.post(f"/v1/admin/dividends/{dv['id']}/approve"))
    d = poll(lambda: ok(admin.get(f"/v1/companies/{ticker}")),
             lambda x: sum(1 for e in x["events"] if e["kind"] == "dividend_claimed") >= n_claim0 + len(x["cap_table"]),
             timeout=900, label="dividend")
    claims = [e for e in d["events"] if e["kind"] == "dividend_claimed"][: len(d["cap_table"])]
    log.step("Dividend paid to every shareholder (relayer paid the gas)", total_maud=args.dividend_maud,
             merkle_root=dv.get("merkle_root"), claims=[e.get("text") for e in claims], transactions=tx_links(claims))

    # 6. new investor KYC, then a transfer signed by the co-founder's own wallet
    buyer = siwe_session(W["buyer"])
    k = ok(buyer.post(f"/v1/companies/{ticker}/kyc", json={"name": "Angel investor"}))
    if k.get("status") != "verified":
        ok(admin.post(f"/v1/admin/kyc/{k['id']}/approve"))
    poll(lambda: ok(admin.post(f"/v1/companies/{ticker}/transfers/check",
                               json={"from_wallet": W["cofounder"].address, "to_wallet": W["buyer"].address, "shares": 1})),
         lambda x: x.get("to_verified"), timeout=600, label="buyer KYC")
    log.step("New investor passed KYC (on-chain IdentityRegistry)", wallet=W["buyer"].address)
    w3 = Web3(Web3.HTTPProvider(LOCAL_RPC))
    tok = w3.eth.contract(address=Web3.to_checksum_address(d["local"]["token"]), abi=ERC20)
    amount = int(tok.functions.balanceOf(W["cofounder"].address).call()) // 10
    frm = W["cofounder"]
    tx = tok.functions.transfer(W["buyer"].address, amount).build_transaction({
        "from": frm.address, "nonce": w3.eth.get_transaction_count(frm.address), "chainId": 262626,
        "gasPrice": w3.eth.gas_price, "gas": 200_000})
    h = w3.eth.send_raw_transaction(Account.sign_transaction(tx, frm.key).raw_transaction)
    rc = w3.eth.wait_for_transaction_receipt(h, timeout=120)
    txh = "0x" + bytes(h).hex().removeprefix("0x")
    holder = siwe_session(frm)
    rec = ok(holder.post(f"/v1/companies/{ticker}/transfers", json={"to_wallet": W["buyer"].address, "to_name": "Angel investor",
                                                                   "shares": amount, "tx_hash": txh, "note": "Secondary sale (demo)"}))
    try:
        d = poll(lambda: ok(admin.get(f"/v1/companies/{ticker}")),
                 lambda x: any(h_["wallet"].lower() == W["buyer"].address.lower() for h_ in x["cap_table"]), timeout=300,
                 label="transfer in cap table")
    except SystemExit as e:  # the on-chain transfer is final; the cap-table view may refresh later
        d = ok(admin.get(f"/v1/companies/{ticker}"))
        log.step("Warning: buyer not yet shown in the cap-table view", detail=str(e))
    log.step("Shareholder transfer signed by the co-founder's wallet and recorded", shares=amount,
             from_wallet=frm.address, to_wallet=W["buyer"].address, tx=f"{SCAN}/tx/{txh}", status=rec.get("status"),
             block=int(rc["blockNumber"]),
             cap_table=[f"{h_['name']}: {h_['shares']:,} ({h_['pct']:.2f}%)" for h_ in d["cap_table"]])

    # 7. revaluations over time (mark = valuation / shares), each re-anchored on the chains
    val = float(d["valuation_aud"])
    for pct, note in ((12, "Quarterly SVI re-run: revenue growth"), (-4, "Market multiple compression"),
                      (18, "New enterprise contracts")):
        val = round(val * (1 + pct / 100))
        r = ok(admin.post(f"/v1/admin/companies/{co['id']}/revalue", json={"valuation_aud": val, "note": note}))
        log.step(f"Revaluation {pct:+d}% — {note}", valuation_aud=val, mark_aud=r.get("mark_aud"), issuer=r.get("issuer"))
        time.sleep(20)
    d = poll(lambda: ok(admin.get(f"/v1/companies/{ticker}")), lambda x: len(x.get("marks") or []) >= 4, timeout=300, label="marks")
    log.step("Value over time", marks=[f"{m_['at'][:19]} A${float(m_['mark_aud']):.4f}/share ({m_['source']})" for m_ in d["marks"]],
             change_7d=d.get("change_7d"), valuation_aud=d["valuation_aud"])

    vf = ok(admin.get(f"/v1/verify/{ticker}"))
    stats = ok(admin.get("/v1/platform/stats"))
    log.step("Final state", company=f"{BASE}/c/{ticker}", verify=f"{BASE}/verify/{ticker}",
             onchain_match={x["chain"]: x["match"] for x in vf["onchain"]},
             events=len(d["events"]), platform={k: stats["kpis"][k] for k in ("companies", "tokens", "total_valuation_aud")})

    # ---- write the log
    date = dt.date.today().isoformat()
    out = {"ticker": ticker, "company": args.name, "url": args.url, "started": log.steps[0]["at"],
           "duration_s": round(time.time() - log.t0), "steps": log.steps}
    md = [f"# Demo run — {args.name} ({ticker}), {date}", "",
          f"Full end-to-end run on the live stack ({BASE}), from AI valuation to issuance on three chains, a new round, "
          f"a dividend, a holder-signed transfer and revaluations. Duration {out['duration_s']} s. "
          "Testnet demo, not an offer of securities.", ""]
    for s in log.steps:
        md.append(f"## {s['n']}. {s['title']}  ")
        md.append(f"*{s['at']} · +{s['elapsed_s']} s*")
        md.append("")
        for k2, v2 in s.items():
            if k2 in ("n", "at", "elapsed_s", "title"):
                continue
            if isinstance(v2, list):
                md.append(f"- **{k2}**:")
                md += [f"  - {x}" for x in v2]
            elif isinstance(v2, dict):
                md.append(f"- **{k2}**: " + ", ".join(f"{a}={b}" for a, b in v2.items()))
            else:
                md.append(f"- **{k2}**: {v2}")
        md.append("")
    for folder in (ROOT / "docs" / "demo-run", ROOT / "web" / "app" / "public" / "demo-run"):
        folder.mkdir(parents=True, exist_ok=True)
    (ROOT / "docs" / "demo-run" / f"{ticker}-{date}.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    (ROOT / "docs" / "demo-run" / f"{ticker}-{date}.md").write_text("\n".join(md))
    (ROOT / "web" / "app" / "public" / "demo-run" / "latest.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    (ROOT / "web" / "app" / "public" / "demo-run" / "latest.md").write_text("\n".join(md))
    print(f"\nlog: docs/demo-run/{ticker}-{date}.md  ·  {BASE}/c/{ticker}")


if __name__ == "__main__":
    sys.exit(main())
