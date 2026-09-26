#!/usr/bin/env python3
"""Regenerate docs/DEPLOYMENTS.md from the live sources of truth (read-only).

Company rows come from studio.companies / studio.holders (Postgres); every token row is then checked
on-chain (name, symbol, totalSupply, paused) on BlockID Chain, Ethereum Hoodi and HashKey Chain testnet.
Platform and demo contracts come from contracts/deployments/out/*.json.

Usage (on the app VM):  agents/.venv/bin/python scripts/export-deployments.py
Needs: sudo docker (Postgres container), /opt/blockid/app.env (HOODI_RPC_URL, HSK_RPC_URL), web3.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path

from web3 import Web3

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "DEPLOYMENTS.md"
PG = ["sudo", "docker", "exec", "blockid-app-postgres-1", "psql", "-U", "blockid", "-d", "blockid", "-At", "-c"]

CHAINS = {
    "blockid": {"name": "BlockID Chain", "id": 262626, "rpc": "http://127.0.0.1:8545",
                "explorer": "https://scan.blockid.au", "note": "register of record (live, transferable)"},
    "hoodi": {"name": "Ethereum Hoodi", "id": 560048, "rpc_env": "HOODI_RPC_URL",
              "explorer": "https://hoodi.etherscan.io", "note": "paused mirror + Merkle anchor"},
    "hsk": {"name": "HashKey Chain testnet", "id": 133, "rpc_env": "HSK_RPC_URL",
            "explorer": "https://testnet-explorer.hskchain.net", "note": "paused mirror + Merkle anchor"},
}
ERC20 = [{"type": "function", "name": n, "stateMutability": "view", "inputs": [], "outputs": [{"type": t}]}
         for n, t in (("name", "string"), ("symbol", "string"), ("totalSupply", "uint256"), ("decimals", "uint8"),
                      ("paused", "bool"))]


def env_file() -> dict[str, str]:
    raw = subprocess.run(["sudo", "cat", "/opt/blockid/app.env"], capture_output=True, text=True, check=True).stdout
    return dict(line.split("=", 1) for line in raw.splitlines() if "=" in line and not line.startswith("#"))


def sql_json(query: str):
    out = subprocess.run(PG + [f"select coalesce(json_agg(t), '[]') from ({query}) t"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def token_info(w3: Web3, addr: str) -> dict:
    c = w3.eth.contract(address=Web3.to_checksum_address(addr), abi=ERC20)

    def get(fn):
        try:
            return getattr(c.functions, fn)().call()
        except Exception:  # noqa: BLE001 - e.g. paused() on a plain ERC-20
            return None
    return {k: get(k) for k in ("name", "symbol", "totalSupply", "decimals", "paused")}


def link(chain: str, addr: str | None, kind: str = "token") -> str:
    if not addr:
        return "–"
    return f"[`{addr[:6]}…{addr[-4:]}`]({CHAINS[chain]['explorer']}/{kind}/{addr})"


def main() -> None:
    env = env_file()
    w3s = {k: Web3(Web3.HTTPProvider(v.get("rpc") or env[v["rpc_env"]], request_kwargs={"timeout": 30}))
           for k, v in CHAINS.items()}
    companies = sql_json("select c.id, ticker, name, status, total_shares, share_price_aud, svi, grade, transfer_mode, "
                         "local_token, local_registry, local_distributor, hoodi_token, hoodi_registry, hsk_token, "
                         "hsk_registry, (select count(*) from studio.holders h where h.company_id=c.id) holders "
                         "from studio.companies c order by c.id")
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    L = [f"# Deployments and tokens",
         "",
         f"_Generated {now} by `scripts/export-deployments.py` from Postgres + live on-chain reads. "
         "Do not edit by hand; re-run the script._",
         "",
         "## Networks", "",
         "| Chain | Chain ID | Explorer | Role |", "|---|---|---|---|"]
    for k, c in CHAINS.items():
        L.append(f"| {c['name']} | {c['id']} | {c['explorer']} | {c['note']} |")

    mismatches = []
    L += ["", "## Company share tokens", "",
          "Each company is issued on BlockID Chain (live token, KYC-gated) and mirrored to Hoodi and HashKey "
          "testnet as a **paused** token whose balances follow BlockID Chain; every change re-anchors a Merkle "
          "root of the cap table. Supply is checked on all three chains at generation time.", "",
          "| Ticker | Company | Status | Holders | Total supply | BlockID Chain | Hoodi | HSK testnet | Supply check |",
          "|---|---|---|---|---|---|---|---|---|"]
    for c in companies:
        sup = {}
        for chain, col in (("blockid", "local_token"), ("hoodi", "hoodi_token"), ("hsk", "hsk_token")):
            if c[col]:
                sup[chain] = token_info(w3s[chain], c[col])["totalSupply"]
        ok = len(set(sup.values())) == 1 and sup.get("blockid") == c["total_shares"] if sup else None
        if sup and not ok:
            mismatches.append(f"{c['ticker']}: db={c['total_shares']} chain={sup}")
        check = "–" if ok is None else ("✅ equal on " + str(len(sup)) + " chains" if ok else "⚠️ mismatch")
        L.append(f"| **{c['ticker']}** | {c['name']} | {c['status']} | {c['holders']} | {int(c['total_shares']):,} | "
                 f"{link('blockid', c['local_token'])} | {link('hoodi', c['hoodi_token'])} | "
                 f"{link('hsk', c['hsk_token'])} | {check} |")

    L += ["", "### Full addresses", "", "| Ticker | Contract | BlockID Chain | Hoodi | HSK testnet |", "|---|---|---|---|---|"]
    for c in companies:
        if not c["local_token"]:
            continue
        L.append(f"| {c['ticker']} | Share token | `{c['local_token']}` | `{c['hoodi_token'] or '–'}` | "
                 f"`{c['hsk_token'] or '–'}` |")
        L.append(f"| {c['ticker']} | Identity registry | `{c['local_registry']}` | `{c['hoodi_registry'] or '–'}` | "
                 f"`{c['hsk_registry'] or '–'}` |")
        L.append(f"| {c['ticker']} | Dividend distributor | `{c['local_distributor']}` | – | – |")

    L += ["", "## Platform and demo contracts", ""]
    for f in sorted((ROOT / "contracts" / "deployments" / "out").glob("*.json")):
        data = json.loads(f.read_text())
        if not isinstance(data, dict):
            continue
        rows = [(k, v) for k, v in data.items() if isinstance(v, str) and v.startswith("0x") and len(v) == 42]
        if rows:
            L += [f"**`{f.name}`** (chain {data.get('chainId', '?')})", "", "| Name | Address |", "|---|---|"]
            L += [f"| {k} | `{v}` |" for k, v in rows] + [""]

    fm = json.loads(subprocess.run(["curl", "-s", "127.0.0.1:1317/cosmos/evm/feemarket/v1/params"],
                                   capture_output=True, text=True).stdout or "{}").get("params", {})
    props = json.loads(subprocess.run(["curl", "-s", "127.0.0.1:1317/cosmos/gov/v1/proposals"],
                                      capture_output=True, text=True).stdout or "{}").get("proposals", [])
    L += ["## BlockID Chain gas", "",
          f"- `eth_gasPrice` = {w3s['blockid'].eth.gas_price} wei; node `minimum-gas-prices = 0ablkd`.",
          f"- feemarket: `no_base_fee={fm.get('no_base_fee')}`, `base_fee={fm.get('base_fee')}`, "
          f"`min_gas_price={fm.get('min_gas_price')}`.",
          "- Native token: **BLKD** (base denom `ablkd`, 18 decimals)."]
    for p in props:
        L.append(f"- Governance proposal #{p['id']} “{p.get('title')}”: {p['status'].replace('PROPOSAL_STATUS_', '')}"
                 f" (voting ends {p.get('voting_end_time', '')[:16].replace('T', ' ')} UTC).")
    if mismatches:
        L += ["", "## ⚠️ Supply mismatches", ""] + [f"- {m}" for m in mismatches]
    OUT.write_text("\n".join(L) + "\n")
    print(f"wrote {OUT} ({len(companies)} companies, {len(mismatches)} mismatches)")


if __name__ == "__main__":
    main()
