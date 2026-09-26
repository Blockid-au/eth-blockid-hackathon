"""Issuer service end-to-end against three local anvil nodes (no Postgres: in-memory store).

- "local" anvil: chain id 262626, base fee 0, gasPrice 20 wei  -> legacy-gas path (like BlockID Chain)
- "hoodi" anvil: chain id 560048, EIP-1559 base fee            -> EIP-1559 path (like Hoodi)
- "hsk" anvil:   chain id 133, EIP-1559, 1 gwei base fee        -> like HashKey Chain testnet
Skipped when anvil or the forge artifacts are missing.
"""
from __future__ import annotations

import copy
import json
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest
from eth_account import Account
from fastapi.testclient import TestClient

from blockid_agents.issuer import artifacts
from blockid_agents.issuer.app import create_app
from blockid_agents.issuer.chain import Chain, TxFailed
from blockid_agents.issuer.config import IssuerConfig
from blockid_agents.issuer.keys import load_account
from blockid_agents.issuer.merkle import build_tree
from blockid_agents.issuer.service import Service

ANVIL = shutil.which("anvil") or str(Path.home() / ".foundry/bin/anvil")
OUT = Path(__file__).resolve().parents[2] / "contracts" / "out"
# anvil default dev keys (public test mnemonic) — deployer = #0, relayer = #1
DEV_KEYS = ["0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
            "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"]
H1, H2, H3 = ("0x1000000000000000000000000000000000000001", "0x2000000000000000000000000000000000000002",
              "0x3000000000000000000000000000000000000003")

needs_anvil = pytest.mark.skipif(not Path(ANVIL).exists() or not (OUT / "CapTableAnchor.sol").is_dir(),
                                 reason="anvil / forge artifacts not available")


# ---------------------------------------------------------------------------- in-memory store
class FakeStore:
    def __init__(self):
        self.companies: dict[int, dict] = {}
        self.holders_: list[dict] = []
        self.events: list[dict] = []
        self.marks: list[dict] = []
        self.mints: dict[int, dict] = {}
        self.dividends: dict[int, dict] = {}
        self.valuations: dict[str, dict] = {}

    def valuation(self, vid):
        return copy.deepcopy(self.valuations.get(vid))

    def company(self, cid):
        return copy.deepcopy(self.companies.get(cid))

    def update_company(self, cid, **f):
        if "sync" in f:
            f["sync"] = json.loads(json.dumps(f["sync"]))  # must be JSON-serialisable (jsonb)
        self.companies[cid].update(f)

    def holders(self, cid):
        return [copy.deepcopy(h) for h in self.holders_ if h["company_id"] == cid]

    def add_holder_shares(self, cid, wallet, name, shares):
        for h in self.holders_:
            if h["company_id"] == cid and h["wallet"].lower() == wallet.lower():
                h["shares"] += shares
                break
        else:
            self.holders_.append({"company_id": cid, "name": name, "wallet": wallet, "pct": 0, "shares": shares})
        self.companies[cid]["total_shares"] = sum(h["shares"] for h in self.holders(cid))

    def reconcile_holders(self, cid, balances):
        bal = {w.lower(): (w, int(n)) for w, n in balances.items() if int(n) > 0}
        before = [(h["wallet"].lower(), h["shares"]) for h in self.holders(cid)]
        keep, seen = [], set()
        for h in self.holders_:
            if h["company_id"] != cid:
                keep.append(h)
                continue
            w = h["wallet"].lower()
            if w in bal and w not in seen:
                seen.add(w)
                keep.append({**h, "shares": bal[w][1]})
        for w, (addr, n) in bal.items():
            if w not in seen:
                keep.append({"company_id": cid, "name": "Unlabelled holder", "wallet": addr, "pct": 0, "shares": n})
        self.holders_ = keep
        self.companies[cid]["total_shares"] = sum(n for _, n in bal.values())
        return {} if before == [(h["wallet"].lower(), h["shares"]) for h in self.holders(cid)] else {"changed": 1}

    def add_event(self, cid, kind, chain=None, tx_hash=None, block=None, data=None):
        self.events.append({"company_id": cid, "kind": kind, "chain": chain, "tx_hash": tx_hash, "block": block,
                            "data": json.loads(json.dumps(data or {}))})  # must be JSON-serialisable

    def add_mark(self, cid, valuation_aud, mark_aud, source, ref=None):
        self.marks.append({"id": len(self.marks) + 1, "company_id": cid, "valuation_aud": valuation_aud,
                           "mark_aud": mark_aud, "source": source, "ref": ref})

    def latest_mark(self, cid):
        ms = [m for m in self.marks if m["company_id"] == cid]
        return ms[-1] if ms else None

    def mint(self, mid):
        return copy.deepcopy(self.mints.get(mid))

    def claim_mint(self, mid):
        m = self.mints.get(mid)
        if not m or m["status"] != "approved":
            return None
        m["status"] = "minting"
        return copy.deepcopy(m)

    def claim_dividend(self, did):
        d = self.dividends.get(did)
        if not d or d["status"] != "approved":
            return None
        d["status"] = "paying"
        return copy.deepcopy(d)

    def update_mint(self, mid, **f):
        self.mints[mid].update(f)

    def dividend(self, did):
        return copy.deepcopy(self.dividends.get(did))

    def update_dividend(self, did, **f):
        self.dividends[did].update(json.loads(json.dumps(f)))

    def kinds(self, cid=1):
        return [e["kind"] for e in self.events if e["company_id"] == cid]


# ---------------------------------------------------------------------------- anvil fixtures
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _anvil(chain_id: int, *extra: str):
    port = _free_port()
    p = subprocess.Popen([ANVIL, "--port", str(port), "--chain-id", str(chain_id), *extra],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return p, url
        except OSError:
            time.sleep(0.1)
    p.kill()
    raise RuntimeError("anvil did not start")


@pytest.fixture(scope="module")
def env():
    if not Path(ANVIL).exists() or not (OUT / "CapTableAnchor.sol").is_dir():
        pytest.skip("anvil / artifacts missing")
    p1, local_url = _anvil(262626, "--base-fee", "0", "--gas-price", "20", "--disable-min-priority-fee")
    p2, hoodi_url = _anvil(560048)
    p3, hsk_url = _anvil(133, "--base-fee", "1000000000")
    try:
        dep, rel = Account.from_key(DEV_KEYS[0]), Account.from_key(DEV_KEYS[1])
        local = Chain("blockid", local_url, 262626, dep, receipt_timeout=30, poll_latency=0.05)
        hoodi = Chain("hoodi", hoodi_url, 560048, dep, receipt_timeout=30, poll_latency=0.05)
        hsk = Chain("hsk", hsk_url, 133, dep, receipt_timeout=30, poll_latency=0.05)
        local.check_chain_id()
        hoodi.check_chain_id()
        anchor, _ = hoodi.deploy("CapTableAnchor", dep.address)
        hoodi.transact(anchor.functions.grantRole(anchor.functions.ANCHOR_ROLE().call(), dep.address))
        hsk_anchor, _ = hsk.deploy("CapTableAnchor", dep.address)
        hsk.transact(hsk_anchor.functions.grantRole(hsk_anchor.functions.ANCHOR_ROLE().call(), dep.address))
        aud, _ = local.deploy("DemoAUD", dep.address)
        cfg = IssuerConfig(internal_token="t", hoodi_captable_anchor=anchor.address, local_demo_aud=aud.address,
                           local_rpc_url=local_url, hoodi_rpc_url=hoodi_url, public_base_url="https://eth.blockid.au",
                           hsk_rpc_url=hsk_url, hsk_chain_id=133, hsk_captable_anchor=hsk_anchor.address)
        store = FakeStore()
        svc = Service(cfg, store, local, hoodi, local.with_account(rel), hsk)
        yield {"svc": svc, "store": store, "local": local, "hoodi": hoodi, "anchor": anchor, "aud": aud, "cfg": cfg,
               "hsk": hsk, "hsk_anchor": hsk_anchor}
    finally:
        p1.kill()
        p2.kill()
        p3.kill()


def _seed(store: FakeStore, cid=1, ticker="ABC", status="issuing"):
    store.valuations[f"val-{cid}"] = {"id": f"val-{cid}", "url": f"https://{ticker.lower()}.example",
                                      "result": {"profile": {"name": ticker}, "svi": {"index": 61.5}},
                                      "self_reported": None}
    store.companies[cid] = {"id": cid, "ticker": ticker, "name": f"{ticker} Pty Ltd", "valuation_id": f"val-{cid}",
                            "valuation_aud": 10000, "share_price_aud": 1, "total_shares": 10000, "status": status}
    for name, w, pct, sh in [("Alice", H1, 60, 6000), ("Bob", H2, 30, 3000), ("Carol", H3, 10, 1000)]:
        store.holders_.append({"company_id": cid, "name": name, "wallet": w, "pct": pct, "shares": sh})


# ---------------------------------------------------------------------------- tests
@needs_anvil
def test_fee_modes(env):
    assert "gasPrice" in env["local"].fee_fields()
    assert "maxFeePerGas" in env["hoodi"].fee_fields()
    from blockid_agents.issuer.chain import TIP_CAP, TIP_FLOOR
    hf = env["hsk"].fee_fields()  # lowest-fee policy: tip clamped, maxFee = 1.25 x base + tip
    assert "maxFeePerGas" in hf and TIP_FLOOR <= hf["maxPriorityFeePerGas"] <= TIP_CAP
    assert env["hsk"].expected_gas_price() > 0
    assert env["hsk"]._bumped({"gasPrice": 100}) == {"gasPrice": 116}


@needs_anvil
def test_revert_raises(env):
    anchor = env["anchor"]
    with pytest.raises(TxFailed):
        env["hoodi"].transact(anchor.functions.anchor("", anchor.address, 1, 1, b"\x01" * 32, 1, ""))


@needs_anvil
def test_full_lifecycle(env):
    svc, st, L, H = env["svc"], env["store"], env["local"], env["hoodi"]
    _seed(st)

    # ---- ONE approval: issue on "BlockID Chain", then sync Hoodi and HSK automatically
    svc.issue(1)
    c = st.companies[1]
    assert c["status"] == "anchored", (c.get("error"), c.get("sync"))
    assert {k: c["sync"][k] for k in ("blockid", "hoodi", "hsk")} == {"blockid": "done", "hoodi": "done", "hsk": "done"}
    assert c["sync"]["errors"] == {} and c["sync"]["finished_at"] and c["sync"]["step"] is None
    token = L.contract("BlockIDShareToken", c["local_token"])
    assert token.functions.symbol().call() == "ABC"
    assert [token.functions.balanceOf(w).call() for w in (H1, H2, H3)] == [6000, 3000, 1000]
    assert token.functions.valuationPerShareCents().call() == 100
    # the valuation REPORT hash is anchored (studio/report_hash.py), on BlockID and on both mirrors
    from blockid_agents.studio.report_hash import report_hash_from_row
    rh = report_hash_from_row(st.valuations["val-1"])
    assert c["valuation_report_hash"] == rh and "0x" + token.functions.valuationReportHash().call().hex() == rh
    assert L.balance(H1) == env["cfg"].drip_wei
    assert st.kinds().count("kyc") == 3 and st.kinds().count("drip") == 3 and st.kinds().count("issued") == 3
    assert "valuation_anchored" in st.kinds() and st.marks[0]["source"] == "issuance"
    deployed = [(e["chain"], e["data"]["contract"]) for e in st.events if e["kind"] == "deployed"]
    assert deployed == [("blockid", "IdentityRegistry"), ("blockid", "BlockIDShareToken"),
                        ("blockid", "DividendDistributor"), ("hoodi", "IdentityRegistry"),
                        ("hoodi", "BlockIDShareToken"), ("hsk", "IdentityRegistry"), ("hsk", "BlockIDShareToken")]
    assert all(e["tx_hash"] and e["block"] for e in st.events if e["chain"] == "blockid")
    order = [(e["kind"], e["chain"]) for e in st.events if e["kind"] in ("hoodi_mirrored", "hsk_mirrored", "anchored")]
    assert order == [("hoodi_mirrored", "hoodi"), ("anchored", "hoodi"), ("hsk_mirrored", "hsk"), ("anchored", "hsk")]

    svc.issue(1)  # wrong status now -> no-op
    assert token.functions.totalSupply().call() == 10000

    anchor = env["anchor"]
    tree = build_tree({H1: 6000, H2: 3000, H3: 1000})
    for ch, anc, pre in ((H, anchor, ""), (env["hsk"], env["hsk_anchor"], "hsk_")):
        a = anc.functions.latest("ABC").call()
        assert "0x" + a[3].hex() == tree.root == c[pre + "merkle_root" if pre else "merkle_root"]
        assert a[0] == c["local_token"] and a[1] == 262626 and a[4] == 10000
        assert anc.functions.verify("ABC", H1, 6000, [bytes.fromhex(p[2:]) for p in tree.proof(H1)]).call()
        m = ch.contract("BlockIDShareToken", c[pre + "token" if pre else "hoodi_token"])
        assert m.functions.paused().call() and m.functions.totalSupply().call() == 10000
        assert "0x" + m.functions.valuationReportHash().call().hex() == rh
    mirror = H.contract("BlockIDShareToken", c["hoodi_token"])
    hsk_mirror = env["hsk"].contract("BlockIDShareToken", c["hsk_token"])
    assert c["hoodi_anchor_tx"] and c["anchored_block"] and c["anchored_at"] and c["hoodi_registry"]
    assert c["hsk_anchor_tx"] and c["hsk_block"] and c["hsk_anchored_at"] and c["hsk_registry"]

    # ---- mint to a new holder -> re-anchor
    new = Account.create().address
    st.mints[7] = {"id": 7, "company_id": 1, "to_wallet": new, "holder_name": "Dave", "shares": 500,
                   "reason": "ESOP", "status": "approved"}
    svc.mint(7)
    assert st.mints[7]["status"] == "minted" and st.mints[7]["tx_hash"]
    assert token.functions.balanceOf(new).call() == 500
    assert anchor.functions.anchorCount("ABC").call() == 2
    assert anchor.functions.latest("ABC").call()[4] == 10500
    assert mirror.functions.balanceOf(new).call() == 500
    assert hsk_mirror.functions.balanceOf(new).call() == 500
    assert env["hsk_anchor"].functions.anchorCount("ABC").call() == 2
    assert st.companies[1]["status"] == "anchored"
    assert st.companies[1]["total_shares"] == 10500
    first_tx = st.mints[7]["tx_hash"]
    svc.mint(7)  # not 'approved' any more -> no-op
    # re-approved after an ambiguous failure: the earlier tx is found on chain, nothing is re-sent
    st.mints[7]["status"] = "approved"
    svc.mint(7)
    assert token.functions.balanceOf(new).call() == 500 and st.companies[1]["total_shares"] == 10500
    assert st.mints[7]["status"] == "minted" and st.mints[7]["tx_hash"] == first_tx

    # ---- dividend: pro-rata plan computed by the issuer (no claims in the row)
    st.dividends[3] = {"id": 3, "company_id": 1, "total_units": 1_000_000_000, "merkle_root": None, "claims": None,
                       "status": "approved", "round_id": None}
    svc.dividend(3)
    d = st.dividends[3]
    assert d["status"] == "paid", st.companies[1].get("error")
    assert d["round_id"] == 0 and d["tx_hash"] and all(x["claimed"] and x["tx_hash"] for x in d["claims"])
    aud = env["aud"]
    assert aud.functions.balanceOf(H1).call() == 1_000_000_000 * 6000 // 10500
    assert st.kinds().count("dividend_claimed") == 4 and "dividend_created" in st.kinds()
    # retry with the round id lost (ambiguous failure): the existing on-chain round is reused, not re-created
    st.dividends[3].update(status="approved", round_id=None)
    svc.dividend(3)
    assert st.dividends[3]["status"] == "paid" and st.dividends[3]["round_id"] == 0
    assert st.kinds().count("dividend_created") == 1
    assert aud.functions.balanceOf(H1).call() == 1_000_000_000 * 6000 // 10500

    # ---- dividend with an explicit plan (list form), second round
    st.dividends[4] = {"id": 4, "company_id": 1, "total_units": 1000, "merkle_root": None, "status": "approved",
                       "round_id": None, "claims": [{"wallet": H1, "amount": 600}, {"wallet": H2, "amount": 400}]}
    svc.dividend(4)
    assert st.dividends[4]["status"] == "paid" and st.dividends[4]["round_id"] == 1

    # ---- revalue -> valuation anchored locally, mirror + cap table re-anchored
    st.add_mark(1, 21000, 2, "revaluation", "note")
    svc.revalue(1)
    assert token.functions.valuationPerShareCents().call() == 200
    assert mirror.functions.valuationPerShareCents().call() == 200
    assert hsk_mirror.functions.valuationPerShareCents().call() == 200
    assert anchor.functions.anchorCount("ABC").call() == 4  # +1 from the mint retry above (re-anchor is idempotent)
    assert env["hsk_anchor"].functions.anchorCount("ABC").call() == 4

    # ---- backfill: a token anchored with an old (non-report) hash gets the report hash on all 3 chains
    old = b"\x11" * 32
    L.transact(token.functions.anchorValuation(old, 200))
    H.transact(mirror.functions.anchorValuation(old, 200))
    env["hsk"].transact(hsk_mirror.functions.anchorValuation(old, 200))
    svc.reanchor_valuation(1)
    for tk in (token, mirror, hsk_mirror):
        assert "0x" + tk.functions.valuationReportHash().call().hex() == rh
        assert tk.functions.valuationPerShareCents().call() == 200

    # ---- failure path: anchor without a BlockID token -> failed with error
    _seed(st, cid=2, ticker="XYZ", status="anchoring")
    svc.anchor(2)
    assert st.companies[2]["status"] == "failed" and "not issued" in st.companies[2]["error"]


@needs_anvil
def test_partial_sync_insufficient_funds_then_retry(env):
    """HSK issuer wallet empty -> Hoodi still syncs, HSK fails with a clear error; admin retry syncs only HSK."""
    svc, st, hsk = env["svc"], env["store"], env["hsk"]
    _seed(st, cid=5, ticker="PQR")
    dep = hsk.address
    funded = hsk.balance(dep)
    hsk.w3.provider.make_request("anvil_setBalance", [dep, hex(10**12)])
    svc.issue(5)
    c = st.companies[5]
    assert c["status"] == "partially_anchored", c.get("error")
    assert c["sync"]["blockid"] == "done" and c["sync"]["hoodi"] == "done" and c["sync"]["hsk"] == "failed"
    assert "top up" in c["sync"]["errors"]["hsk"] and "HSK" in c["sync"]["errors"]["hsk"]
    assert "HashKey" in c["error"] and not c.get("hsk_token")
    assert ("sync_failed", "hsk") in [(e["kind"], e["chain"]) for e in st.events if e["company_id"] == 5]
    hoodi_anchors = env["anchor"].functions.anchorCount("PQR").call()

    hsk.w3.provider.make_request("anvil_setBalance", [dep, hex(funded)])
    st.companies[5]["status"] = "anchoring"  # what POST /approve-anchor does
    svc.anchor(5)
    c = st.companies[5]
    assert c["status"] == "anchored", c.get("error")
    assert c["sync"]["hsk"] == "done" and c["sync"]["errors"] == {} and c["error"] is None
    assert env["anchor"].functions.anchorCount("PQR").call() == hoodi_anchors  # Hoodi not re-run
    assert env["hsk_anchor"].functions.anchorCount("PQR").call() == 1


@needs_anvil
def test_unconfigured_chain_is_skipped(env):
    from dataclasses import replace

    base = env["svc"]
    svc = Service(replace(base.cfg, hsk_captable_anchor=""), base.store, base.local, base.hoodi, base.relayer, base.hsk)
    st = base.store
    _seed(st, cid=6, ticker="LMN")
    svc.issue(6)
    c = st.companies[6]
    assert c["status"] == "partially_anchored" and c["sync"]["hsk"] == "skipped"
    assert "not configured" in c["sync"]["errors"]["hsk"]


@needs_anvil
def test_health(env):
    h = env["svc"].health()
    assert h["local"]["ok"] and h["hoodi"]["ok"] and h["local"]["chain_id"] == 262626
    assert h["hsk"]["ok"] and h["hsk"]["chain_id"] == 133 and int(h["issuer"]["hsk_balance"]) > 0
    assert h["sync_targets"] == ["hoodi", "hsk"]
    assert int(h["issuer"]["local_balance"]) > 0


# ---------------------------------------------------------------------------- keys + app (no chain)
def test_keystore_decrypt(tmp_path):
    acct = Account.create()
    ks = Account.encrypt(acct.key, "s3cret-pw", kdf="pbkdf2", iterations=2)
    (tmp_path / "blockid-deployer").write_text(json.dumps(ks))
    (tmp_path / "deployer.password").write_text("s3cret-pw\n")
    assert load_account("blockid-deployer", tmp_path).address == acct.address
    (tmp_path / "deployer.password").write_text("wrong")
    with pytest.raises(ValueError) as e:
        load_account("blockid-deployer", tmp_path)
    assert "wrong" not in str(e.value)


def test_artifacts_load():
    if not (OUT / "CapTableAnchor.sol").is_dir():
        pytest.skip("forge build not run")
    abi, code = artifacts.load("CapTableAnchor", out_dir=str(OUT))
    assert code.startswith("0x") and any(x.get("name") == "anchor" for x in abi)


class _RecSvc:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *a: self.calls.append((name, *a))

    def health(self):
        return {"ok": True}


def test_app_auth_and_202():
    svc = _RecSvc()
    app = create_app(svc, IssuerConfig(internal_token="tok"))
    cl = TestClient(app)
    assert cl.get("/healthz").status_code == 200
    assert cl.post("/issue", json={"company_id": 1}).status_code == 401
    assert cl.post("/issue", json={"company_id": 1}, headers={"X-Internal-Token": "nope"}).status_code == 401
    h = {"X-Internal-Token": "tok"}
    for path, body in [("/issue", {"company_id": 1}), ("/anchor", {"company_id": 1}), ("/revalue", {"company_id": 1}), ("/reanchor-valuation", {"company_id": 1}),
                       ("/mint", {"mint_id": 2}), ("/dividend", {"dividend_id": 3}),
                       ("/drip", {"wallet": H1.lower()})]:
        r = cl.post(path, json=body, headers=h)
        assert r.status_code == 202, (path, r.text)
    assert cl.post("/drip", json={"wallet": "0x12"}, headers=h).status_code == 422
    assert cl.get("/health", headers=h).json()["ok"] is True
    app.state.pool.shutdown(wait=True)
    assert [c[0] for c in svc.calls] == ["issue", "anchor", "revalue", "reanchor_valuation", "mint", "dividend", "drip"]


@needs_anvil
def test_secondary_transfer_then_refresh_from_chain(env):
    """A transfer outside studio.holders used to break every re-sync ('cap table incomplete'). The paged Transfer
    scan finds the receiver, studio.holders follows the chain, and Refresh clears the error and re-syncs."""
    from web3 import Web3

    svc, st, L = env["svc"], env["store"], env["local"]
    _seed(st, cid=7, ticker="XYZ")
    svc.issue(7)
    c = st.companies[7]
    assert c["status"] == "anchored", c.get("error")
    h4 = Web3.to_checksum_address("0x4000000000000000000000000000000000000004")
    reg = L.contract("IdentityRegistry", c["local_registry"])
    token = L.contract("BlockIDShareToken", c["local_token"])
    svc._kyc(L, reg, h4, "Angel", 7)
    L.transact(token.functions.forcedTransfer(Web3.to_checksum_address(H2), h4, 500, Web3.keccak(text="t:1")))
    # the state a failed re-sync left behind
    st.companies[7].update(status="issued", error="Ethereum Hoodi: RuntimeError: cap table incomplete: "
                                                  "sum(balances)=9500 != totalSupply=10000")
    old_chunk, svc.LOG_CHUNK = svc.LOG_CHUNK, 3  # force many pages
    try:
        svc.refresh(7)
    finally:
        svc.LOG_CHUNK = old_chunk
    c = st.companies[7]
    assert c["status"] == "anchored" and c["error"] is None, (c.get("error"), c.get("sync"))
    by = {h["wallet"].lower(): h for h in st.holders(7)}
    assert by[h4.lower()]["shares"] == 500 and by[H2.lower()]["shares"] == 2500
    assert sum(h["shares"] for h in st.holders(7)) == 10000
    mirror = env["hoodi"].contract("BlockIDShareToken", c["hoodi_token"])
    assert mirror.functions.balanceOf(h4).call() == 500
    # the sender's mirror balance must go DOWN too, or the mirror supply exceeds the register (CNV bug)
    assert mirror.functions.balanceOf(Web3.to_checksum_address(H2)).call() == 2500
    assert mirror.functions.totalSupply().call() == 10000
    hsk_mirror = env["hsk"].contract("BlockIDShareToken", c["hsk_token"])
    assert hsk_mirror.functions.totalSupply().call() == 10000

    # a holder who sells everything disappears from studio.holders but must be zeroed on the mirrors as well
    L.transact(token.functions.forcedTransfer(Web3.to_checksum_address(H3), h4, 1000, Web3.keccak(text="t:2")))
    svc.reanchor(7)
    c = st.companies[7]
    assert c["status"] == "anchored", (c.get("error"), c.get("sync"))
    assert H3.lower() not in {h["wallet"].lower() for h in st.holders(7)}
    assert mirror.functions.balanceOf(Web3.to_checksum_address(H3)).call() == 0
    assert mirror.functions.balanceOf(h4).call() == 1500 and mirror.functions.totalSupply().call() == 10000
    assert "refreshed" in st.kinds(7)


def test_error_classification_points_to_the_fix():
    from blockid_agents.studio.errors import classify, company_error_info

    cnv = "RuntimeError: cap table incomplete: sum(balances)=68589675000 != totalSupply=70512750000"
    info = classify(cnv)
    assert info["code"] == "cap_table_mismatch" and info["action"] == "refresh" and info["target"] == "cap-table"
    assert info["detail"]["missing"] == 1923075000
    gas = classify("InsufficientFunds: issuer 0xabc has 0.000001 HSK on HashKey Chain testnet, needs about 0.0075 HSK")
    assert gas["action"] == "top_up" and gas["target"] == "issuer-wallets"
    assert classify("mint 12: boom")["code"] == "mint_failed"
    assert classify(None) is None and classify("weird")["code"] == "unknown"
    both = company_error_info({"error": None, "sync": {"errors": {"hsk": cnv}}})
    assert both["code"] == "cap_table_mismatch" and both["chains"]["hsk"]["code"] == "cap_table_mismatch"
