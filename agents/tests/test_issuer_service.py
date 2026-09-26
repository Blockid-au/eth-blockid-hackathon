"""Issuer service end-to-end against two local anvil nodes (no Postgres: in-memory store).

- "local" anvil: chain id 262626, base fee 0, gasPrice 20 wei  -> legacy-gas path (like BlockID Chain)
- "hoodi" anvil: chain id 560048, EIP-1559 base fee            -> EIP-1559 path (like Hoodi)
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

    def company(self, cid):
        return copy.deepcopy(self.companies.get(cid))

    def update_company(self, cid, **f):
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
    try:
        dep, rel = Account.from_key(DEV_KEYS[0]), Account.from_key(DEV_KEYS[1])
        local = Chain("blockid", local_url, 262626, dep, receipt_timeout=30, poll_latency=0.05)
        hoodi = Chain("hoodi", hoodi_url, 560048, dep, receipt_timeout=30, poll_latency=0.05)
        local.check_chain_id()
        hoodi.check_chain_id()
        anchor, _ = hoodi.deploy("CapTableAnchor", dep.address)
        hoodi.transact(anchor.functions.grantRole(anchor.functions.ANCHOR_ROLE().call(), dep.address))
        aud, _ = local.deploy("DemoAUD", dep.address)
        cfg = IssuerConfig(internal_token="t", hoodi_captable_anchor=anchor.address, local_demo_aud=aud.address,
                           local_rpc_url=local_url, hoodi_rpc_url=hoodi_url, public_base_url="https://eth.blockid.au")
        store = FakeStore()
        svc = Service(cfg, store, local, hoodi, local.with_account(rel))
        yield {"svc": svc, "store": store, "local": local, "hoodi": hoodi, "anchor": anchor, "aud": aud, "cfg": cfg}
    finally:
        p1.kill()
        p2.kill()


def _seed(store: FakeStore, cid=1, ticker="ABC", status="issuing"):
    store.companies[cid] = {"id": cid, "ticker": ticker, "name": f"{ticker} Pty Ltd", "valuation_id": f"val-{cid}",
                            "valuation_aud": 10000, "share_price_aud": 1, "total_shares": 10000, "status": status}
    for name, w, pct, sh in [("Alice", H1, 60, 6000), ("Bob", H2, 30, 3000), ("Carol", H3, 10, 1000)]:
        store.holders_.append({"company_id": cid, "name": name, "wallet": w, "pct": pct, "shares": sh})


# ---------------------------------------------------------------------------- tests
@needs_anvil
def test_fee_modes(env):
    assert "gasPrice" in env["local"].fee_fields()
    assert "maxFeePerGas" in env["hoodi"].fee_fields()


@needs_anvil
def test_revert_raises(env):
    anchor = env["anchor"]
    with pytest.raises(TxFailed):
        env["hoodi"].transact(anchor.functions.anchor("", anchor.address, 1, 1, b"\x01" * 32, 1, ""))


@needs_anvil
def test_full_lifecycle(env):
    svc, st, L, H = env["svc"], env["store"], env["local"], env["hoodi"]
    _seed(st)

    # ---- issue on "BlockID Chain"
    svc.issue(1)
    c = st.companies[1]
    assert c["status"] == "issued", c.get("error")
    token = L.contract("BlockIDShareToken", c["local_token"])
    assert token.functions.symbol().call() == "ABC"
    assert [token.functions.balanceOf(w).call() for w in (H1, H2, H3)] == [6000, 3000, 1000]
    assert token.functions.valuationPerShareCents().call() == 100
    assert L.balance(H1) == env["cfg"].drip_wei
    assert st.kinds().count("kyc") == 3 and st.kinds().count("drip") == 3 and st.kinds().count("issued") == 3
    assert "valuation_anchored" in st.kinds() and st.marks[0]["source"] == "issuance"
    assert all(e["chain"] == "blockid" and e["tx_hash"] and e["block"] for e in st.events)

    svc.issue(1)  # wrong status now -> no-op
    assert token.functions.totalSupply().call() == 10000

    # ---- anchor on "Hoodi"
    st.companies[1]["status"] = "anchoring"
    svc.anchor(1)
    c = st.companies[1]
    assert c["status"] == "anchored", c.get("error")
    anchor = env["anchor"]
    a = anchor.functions.latest("ABC").call()
    tree = build_tree({H1: 6000, H2: 3000, H3: 1000})
    assert "0x" + a[3].hex() == tree.root == c["merkle_root"]
    assert a[0] == c["local_token"] and a[1] == 262626 and a[4] == 10000
    assert anchor.functions.verify("ABC", H1, 6000, [bytes.fromhex(p[2:]) for p in tree.proof(H1)]).call()
    mirror = H.contract("BlockIDShareToken", c["hoodi_token"])
    assert mirror.functions.paused().call() and mirror.functions.totalSupply().call() == 10000
    assert c["hoodi_anchor_tx"] and c["anchored_block"] and c["anchored_at"] and c["hoodi_registry"]
    assert [e["chain"] for e in st.events if e["kind"] in ("hoodi_mirrored", "anchored")] == ["hoodi", "hoodi"]

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
    assert anchor.functions.anchorCount("ABC").call() == 4  # +1 from the mint retry above (re-anchor is idempotent)

    # ---- failure path: bad status transitions to failed with error
    _seed(st, cid=2, ticker="XYZ", status="anchoring")
    svc.anchor(2)
    assert st.companies[2]["status"] == "failed" and "not issued" in st.companies[2]["error"]


@needs_anvil
def test_health(env):
    h = env["svc"].health()
    assert h["local"]["ok"] and h["hoodi"]["ok"] and h["local"]["chain_id"] == 262626
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
    for path, body in [("/issue", {"company_id": 1}), ("/anchor", {"company_id": 1}), ("/revalue", {"company_id": 1}),
                       ("/mint", {"mint_id": 2}), ("/dividend", {"dividend_id": 3}),
                       ("/drip", {"wallet": H1.lower()})]:
        r = cl.post(path, json=body, headers=h)
        assert r.status_code == 202, (path, r.text)
    assert cl.post("/drip", json={"wallet": "0x12"}, headers=h).status_code == 422
    assert cl.get("/health", headers=h).json()["ok"] is True
    app.state.pool.shutdown(wait=True)
    assert [c[0] for c in svc.calls] == ["issue", "anchor", "revalue", "mint", "dividend", "drip"]
