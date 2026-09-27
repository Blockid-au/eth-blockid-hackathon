"""Company admins (studio/company_admins.py + issuer/roles.py), gas allowances (studio/gas.py), locked demo password.

API tests need TEST_DATABASE_URL (throwaway Postgres; the studio schema is dropped); the on-chain role test needs
anvil + forge artifacts. Both are skipped otherwise.
"""
import copy
import json

import httpx
import pytest
from eth_account import Account
from test_issuer_service import DEV_KEYS, FakeStore, _anvil, _seed, needs_anvil
from test_studio import ADMIN_KEY, USER_KEY, needs_db, siwe_login, studio_env  # noqa: F401 (fixture)

OWNER_KEY, MGR_KEY, OUT_KEY, OWNER2_KEY = USER_KEY, "0x" + "e5" * 32, "0x" + "c3" * 32, "0x" + "f6" * 32
OWNER, MGR, OUTSIDER, OWNER2 = (Account.from_key(k).address for k in (OWNER_KEY, MGR_KEY, OUT_KEY, OWNER2_KEY))
TOKEN, REG = "0x" + "7" * 40, "0x" + "8" * 40


def _company(db, ticker: str, created_by: str | None, status: str = "anchored", issued: bool = True) -> int:
    return db.one("INSERT INTO studio.companies(ticker,name,valuation_aud,total_shares,status,created_by,local_token,"
                  "local_registry) VALUES (%s,%s,1000,1000,%s,%s,%s,%s) RETURNING id",
                  (ticker, ticker + " Pty Ltd", status, created_by, TOKEN if issued else None,
                   REG if issued else None))["id"]


@pytest.fixture
def ca(studio_env):  # noqa: F811
    env = studio_env
    db = env["db"]
    admin = env["client"]()
    siwe_login(admin, ADMIN_KEY)  # applies the schema
    a = _company(db, "AAA", OWNER)
    b = _company(db, "BBB", OUTSIDER)
    d = _company(db, "DDD", OWNER, status="draft", issued=False)
    db.apply_schema()  # backfill: created_by wallets become owners
    clients = {"admin": admin}
    for name, key in (("owner", OWNER_KEY), ("mgr", MGR_KEY), ("out", OUT_KEY), ("owner2", OWNER2_KEY)):
        clients[name] = env["client"]()
        siwe_login(clients[name], key)
    return {**env, "a": a, "b": b, "d": d, **clients}


def _admins(c, tk="AAA"):
    return {x["address"]: x for x in c.get(f"/v1/companies/{tk}/admins").json()["admins"]}


@needs_db
def test_backfill_crud_permissions_and_last_owner(ca):
    db, owner, mgr, out, admin = ca["db"], ca["owner"], ca["mgr"], ca["out"], ca["admin"]
    anon = ca["client"]()
    # backfill + seed: the creator is the only owner
    assert {k: (v["role"], v["status"]) for k, v in _admins(owner).items()} == {OWNER: ("owner", "active")}
    assert anon.get("/v1/companies/AAA/admins").status_code == 401
    assert out.get("/v1/companies/AAA/admins").status_code == 403
    assert admin.get("/v1/companies/AAA/admins").json()["you"] == "platform_admin"
    assert owner.get("/v1/companies/AAA/admins").json()["you"] == "company_owner"

    # EIP-55: a wrong mixed-case checksum is refused, all-lowercase is normalised
    bad = MGR[:2] + MGR[2:].swapcase()
    assert owner.post("/v1/companies/AAA/admins", json={"address": bad, "role": "manager"}).status_code == 422
    r = owner.post("/v1/companies/AAA/admins", json={"address": MGR.lower(), "label": "CFO", "role": "manager"})
    assert r.status_code == 201 and r.json()["address"] == MGR and r.json()["status"] == "active"
    assert not r.json()["onchain"] and ca["calls"] == [c for c in ca["calls"] if c[0] != "/company-roles"]
    # outsiders / managers cannot manage admins; managers can read the list
    assert out.post("/v1/companies/AAA/admins", json={"address": OUTSIDER}).status_code == 403
    assert mgr.post("/v1/companies/AAA/admins", json={"address": OUTSIDER}).status_code == 403
    assert mgr.get("/v1/companies/AAA/admins").json()["you"] == "company_manager"
    assert mgr.post(f"/v1/companies/AAA/admins/{OWNER}/revoke").status_code == 403
    assert mgr.get("/v1/companies/BBB/admins").status_code == 403  # scoped to its own company

    # last-owner guard: neither revoke nor demote the only owner (platform admin included)
    assert owner.post(f"/v1/companies/AAA/admins/{OWNER}/revoke").status_code == 409
    assert admin.delete(f"/v1/companies/AAA/admins/{OWNER}").status_code == 409
    assert owner.post("/v1/companies/AAA/admins", json={"address": OWNER, "role": "manager"}).status_code == 409
    # platform admin adds a second owner, then the first owner can leave
    assert admin.post("/v1/companies/AAA/admins", json={"address": OWNER2, "role": "owner"}).status_code == 201
    assert ca["owner2"].get("/v1/companies/AAA/admins").json()["you"] == "company_owner"
    r = owner.delete(f"/v1/companies/AAA/admins/{OWNER}")
    assert r.status_code == 200 and r.json()["status"] == "revoked" and r.json()["revoked_at"]
    assert owner.get("/v1/companies/AAA/admins").status_code == 403
    assert ca["owner2"].post(f"/v1/companies/AAA/admins/{OWNER2}/revoke").status_code == 409
    assert ca["owner2"].post(f"/v1/companies/AAA/admins/{OUTSIDER}/revoke").status_code == 404
    # re-adding a revoked wallet reactivates the same row
    r = ca["owner2"].post("/v1/companies/AAA/admins", json={"address": OWNER, "role": "manager", "label": "back"})
    assert r.status_code == 201 and r.json()["status"] == "active" and r.json()["revoked_at"] is None

    # my companies
    assert [x["ticker"] for x in mgr.get("/v1/me/companies").json()] == ["AAA"]
    assert {x["ticker"]: x["role"] for x in owner.get("/v1/me/companies").json()} == {"AAA": "manager", "DDD": "owner"}
    assert out.get("/v1/me/companies").json()[0]["ticker"] == "BBB"
    assert anon.get("/v1/me/companies").status_code == 401

    rows = db.all("SELECT action, detail FROM studio.audit WHERE action LIKE 'company_admin%%' ORDER BY id")
    assert [x["action"] for x in rows][:2] == ["company_admin_added", "company_admin_added"]
    assert rows[0]["detail"]["role"] == "company_owner" and rows[1]["detail"]["role"] == "platform_admin"
    assert "company_admin_revoked" in [x["action"] for x in rows]


@needs_db
def test_onchain_grant_and_revoke_call_issuer(ca):
    db, owner, calls = ca["db"], ca["owner"], ca["calls"]
    # not issued yet -> on-chain roles refused
    assert owner.post("/v1/companies/DDD/admins", json={"address": MGR, "onchain": True}).status_code == 409
    r = owner.post("/v1/companies/AAA/admins", json={"address": MGR, "label": "ops", "role": "manager",
                                                     "onchain": True})
    assert r.status_code == 201 and r.json()["status"] == "pending_grant" and r.json()["onchain"]
    assert ("/company-roles", {"company_id": ca["a"], "address": MGR, "grant": True}) in calls
    # pending_grant confers no rights yet
    assert ca["mgr"].get("/v1/companies/AAA/admins").status_code == 403
    db.exec("UPDATE studio.company_admins SET status='active', grant_tx='0xg' WHERE address=%s", (MGR,))
    assert ca["mgr"].get("/v1/companies/AAA/admins").status_code == 200
    # adding again with onchain does not re-grant an active on-chain admin
    n = len([c for c in calls if c[0] == "/company-roles"])
    owner.post("/v1/companies/AAA/admins", json={"address": MGR, "role": "manager", "onchain": True})
    assert len([c for c in calls if c[0] == "/company-roles"]) == n
    r = owner.post(f"/v1/companies/AAA/admins/{MGR}/revoke").json()
    assert r["status"] == "revoked" and r["issuer"] == "queued"
    assert calls[-1] == ("/company-roles", {"company_id": ca["a"], "address": MGR, "grant": False})
    assert ca["mgr"].get("/v1/companies/AAA/admins").status_code == 403  # rights gone immediately

    # issuer down: 502, row stays pending_grant with the error (re-adding retries)
    from blockid_agents.studio.services import IssuerClient
    owner.app.state.studio.issuer = IssuerClient("http://issuer", "t", transport=httpx.MockTransport(
        lambda req: httpx.Response(503, text="down")))
    r = owner.post("/v1/companies/AAA/admins", json={"address": OUTSIDER, "onchain": True})
    assert r.status_code == 502
    row = db.one("SELECT status, error FROM studio.company_admins WHERE address=%s AND company_id=%s",
                 (OUTSIDER, ca["a"]))
    assert row["status"] == "pending_grant" and "503" in row["error"]


def _pending(db, cid: int) -> dict:
    m = db.one("INSERT INTO studio.mints(company_id,to_wallet,holder_name,shares,status) VALUES (%s,%s,'x',5,'pending') "
               "RETURNING id", (cid, OUTSIDER))["id"]
    d = db.one("INSERT INTO studio.dividends(company_id,total_units,status,claims) VALUES (%s,100,'pending','[]') "
               "RETURNING id", (cid,))["id"]
    t = db.one("INSERT INTO studio.transfers(company_id,from_wallet,to_wallet,shares,mode,status) "
               "VALUES (%s,%s,%s,1,'approval','pending') RETURNING id", (cid, OWNER, OUTSIDER))["id"]
    return {"mint": m, "div": d, "transfer": t}


@needs_db
def test_scoped_approvals(ca):
    db, owner, mgr, out, admin, calls = ca["db"], ca["owner"], ca["mgr"], ca["out"], ca["admin"], ca["calls"]
    owner.post("/v1/companies/AAA/admins", json={"address": MGR, "role": "manager"})
    pa, pb = _pending(db, ca["a"]), _pending(db, ca["b"])
    db.exec("INSERT INTO studio.valuations(id,url,status) VALUES ('vw','https://w.example','waiting_approval')")

    ap = mgr.get("/v1/admin/approvals").json()
    assert ap["scope"] == "company" and ap["company_ids"] == [ca["a"]] and ap["valuations"] == []
    assert [m["id"] for m in ap["mints"]] == [pa["mint"]] and [d["id"] for d in ap["dividends"]] == [pa["div"]]
    full = admin.get("/v1/admin/approvals").json()
    assert full["scope"] == "platform" and len(full["mints"]) == 2 and len(full["valuations"]) == 1
    assert out.get("/v1/admin/approvals").json()["mints"][0]["id"] == pb["mint"]  # BBB's creator-owner
    assert ca["owner2"].get("/v1/admin/approvals").status_code == 403  # admin of nothing
    assert [t["id"] for t in mgr.get("/v1/admin/transfers").json()] == [pa["transfer"]]
    assert len(admin.get("/v1/admin/transfers").json()) == 2
    assert mgr.get("/v1/admin/kyc").json() == []

    # other company's items: 403; own: approved (-> issuer), audited with the role
    assert mgr.post(f"/v1/admin/mints/{pb['mint']}/approve").status_code == 403
    assert mgr.post(f"/v1/admin/dividends/{pb['div']}/approve").status_code == 403
    assert mgr.post(f"/v1/admin/transfers/{pb['transfer']}/approve").status_code == 403
    assert mgr.post("/v1/admin/mints/999999/approve").status_code == 403
    assert admin.post("/v1/admin/mints/999999/approve").status_code == 404
    assert mgr.post(f"/v1/admin/mints/{pa['mint']}/approve").status_code == 202
    assert calls[-1] == ("/mint", {"mint_id": pa["mint"]})
    assert mgr.post(f"/v1/admin/dividends/{pa['div']}/reject", json={"reason": "no"}).json()["status"] == "rejected"
    assert mgr.post(f"/v1/admin/transfers/{pa['transfer']}/approve").status_code == 202
    assert calls[-1] == ("/transfer", {"transfer_id": pa["transfer"]})
    roles = {x["action"]: x["detail"].get("role") for x in db.all("SELECT action, detail FROM studio.audit")}
    assert roles["mint_approved"] == roles["dividend_rejected"] == roles["transfer_approved"] == "company_manager"
    # four eyes: a manager cannot approve a mint they requested themselves; the platform admin still can
    own = db.one("INSERT INTO studio.mints(company_id,to_wallet,holder_name,shares,status,requested_by) "
                 "VALUES (%s,%s,'x',5,'pending',%s) RETURNING id", (ca["a"], OUTSIDER, MGR))["id"]
    r = mgr.post(f"/v1/admin/mints/{own}/approve")
    assert r.status_code == 403 and "different person" in r.json()["detail"]
    assert admin.post(f"/v1/admin/mints/{own}/approve").status_code == 202

    # revaluation scoped; issuance / re-sync / reject / transfer mode stay platform-admin only
    r = mgr.post(f"/v1/admin/companies/{ca['a']}/revalue", json={"valuation_aud": 2000, "note": "q"})
    assert r.status_code == 202 and calls[-1] == ("/revalue", {"company_id": ca["a"]})
    assert mgr.post(f"/v1/admin/companies/{ca['b']}/revalue", json={"valuation_aud": 2000}).status_code == 403
    for path in ("approve-issue", "approve-anchor", "reanchor-valuation"):
        assert mgr.post(f"/v1/admin/companies/{ca['a']}/{path}").status_code == 403
    assert mgr.post(f"/v1/admin/companies/{ca['a']}/reject", json={"reason": "x"}).status_code == 403
    assert mgr.post(f"/v1/admin/companies/{ca['a']}/transfer-mode", json={"mode": "free"}).status_code == 403
    assert mgr.get("/v1/admin/companies").status_code == 403

    # company admins may request mints / dividends for their company without an issuer wallet
    m = mgr.post("/v1/companies/AAA/mints", json={"to_wallet": OWNER2, "holder_name": "Angel", "shares": 10})
    assert m.status_code == 201
    assert mgr.post("/v1/companies/BBB/mints", json={"to_wallet": OWNER2, "holder_name": "A", "shares": 1}
                    ).status_code == 403
    # private data: the draft company is visible to its admins only
    assert ca["client"]().get("/v1/companies/DDD").status_code == 404
    assert mgr.get("/v1/companies/DDD").status_code == 404
    assert owner.get("/v1/companies/DDD").status_code == 200
    owner.post("/v1/companies/DDD/admins", json={"address": MGR, "role": "manager"})
    assert mgr.get("/v1/companies/DDD").status_code == 200


@needs_db
def test_seed_owner_on_create(ca):
    from blockid_agents.studio.company_admins import seed_owner

    db = ca["db"]
    cid = _company(db, "EEE", None)
    with db.tx() as c:
        seed_owner(c, cid, MGR.lower())
        seed_owner(c, cid, "admin")  # password admins are never seeded
    assert db.all("SELECT address, role FROM studio.company_admins WHERE company_id=%s", (cid,)) == \
        [{"address": MGR, "role": "owner"}]


@needs_db
def test_gas_drip_once_per_day_and_daily_cap(ca, monkeypatch):
    from blockid_agents.studio.gas import GasDripper, allowance_wei

    db, calls = ca["db"], ca["calls"]
    # SIWE sign-in queued a drip for each new wallet (background task), with the default 1 BLKD allowance
    drips = [c[1] for c in calls if c[0] == "/drip"]
    assert {"wallet": OWNER, "amount_wei": 10**18} in drips and len({d["wallet"] for d in drips}) == len(drips)
    siwe_login(ca["client"](), OWNER_KEY)  # second sign-in within 24 h: no second drip
    assert len([c for c in calls if c[0] == "/drip"]) == len(drips)

    db.exec("DELETE FROM studio.gas_drips")
    monkeypatch.setenv("GAS_DRIP_DAILY_MAX", "2")
    monkeypatch.setenv("GAS_DRIP_BLKD", "9")  # capped at 5 BLKD
    assert allowance_wei() == 5 * 10**18
    g = GasDripper(ca["admin"].app.state.studio)
    w = [Account.from_key("0x" + f"{i:02x}" * 32).address for i in (0x31, 0x32, 0x33)]
    assert g.drip(w[0]) is True and g.drip(w[0]) is False  # once per 24 h
    assert calls[-1] == ("/drip", {"wallet": w[0], "amount_wei": 5 * 10**18})
    assert g.drip(w[1].lower(), "holder", ca["a"]) is True
    assert calls[-1] == ("/drip", {"wallet": w[1], "amount_wei": 5 * 10**18, "company_id": ca["a"]})
    assert g.drip(w[2]) is False  # global cap reached
    db.exec("UPDATE studio.gas_drips SET created_at = now() - interval '25 hours'")
    assert g.drip(w[2]) is True and g.drip(w[0]) is True  # a day later
    assert g.drip("not-an-address") is False
    monkeypatch.setenv("GAS_DRIP_BLKD", "0")
    db.exec("DELETE FROM studio.gas_drips")
    assert g.drip(w[0]) is False  # disabled

    # issuer down: the reservation is released (next sign-in retries), nothing raises
    from blockid_agents.studio.services import IssuerClient
    monkeypatch.setenv("GAS_DRIP_BLKD", "1")
    ca["admin"].app.state.studio.issuer = IssuerClient("http://issuer", "t", transport=httpx.MockTransport(
        lambda req: httpx.Response(503, text="down")))
    assert g.drip(w[0]) is False
    assert db.one("SELECT count(*) AS n FROM studio.gas_drips")["n"] == 0


@needs_db
def test_password_locked_demo(studio_env, monkeypatch):  # noqa: F811
    monkeypatch.setenv("ADMIN_PASSWORD_LOCKED", "1")
    p = studio_env["client"]()
    r = p.post("/v1/auth/login", json={"username": "admin", "password": "admin"})
    assert r.json() == {"role": "admin", "must_change": False}
    assert p.get("/v1/auth/me").json()["must_change"] is False
    assert p.get("/v1/admin/audit").status_code == 200  # must_change ignored
    r = p.post("/v1/auth/change-password", json={"current": "admin", "new": "a-long-new-password"})
    assert r.status_code == 403 and r.json()["detail"] == "Password changes are disabled on the public demo"


# ================================================================== issuer: on-chain roles (anvil)
class RoleStore(FakeStore):
    def __init__(self):
        super().__init__()
        self.admins: dict[int, dict] = {}

    def company_admin(self, cid, address):
        for a in self.admins.values():
            if a["company_id"] == cid and a["address"].lower() == address.lower():
                return copy.deepcopy(a)
        return None

    def update_company_admin(self, aid, **f):
        self.admins[aid].update(json.loads(json.dumps(f)))


def test_company_role_request_validation():
    from fastapi.testclient import TestClient

    from blockid_agents.issuer.app import create_app
    from blockid_agents.issuer.config import IssuerConfig

    calls = []

    class Svc:
        def __getattr__(self, name):
            return lambda *a, **k: calls.append((name, a))

    app = create_app(Svc(), IssuerConfig(internal_token="tok"))
    cl = TestClient(app)
    h = {"X-Internal-Token": "tok"}
    body = {"company_id": 1, "address": OWNER.lower(), "grant": True}
    assert cl.post("/company-roles", json=body).status_code == 401
    r = cl.post("/company-roles", json=body, headers=h)
    assert r.status_code == 202 and r.json()["address"] == OWNER and r.json()["grant"] is True
    assert cl.post("/company-roles", json={**body, "address": "0x12"}, headers=h).status_code == 422
    assert cl.post("/drip", json={"wallet": OWNER, "amount_wei": 6 * 10**18}, headers=h).status_code == 422
    assert cl.post("/drip", json={"wallet": OWNER, "amount_wei": 10**18}, headers=h).json()["amount_wei"] == 10**18


@needs_anvil
def test_issuer_grants_and_revokes_company_roles_on_anvil():
    from blockid_agents.issuer import roles
    from blockid_agents.issuer.chain import Chain
    from blockid_agents.issuer.config import IssuerConfig
    from blockid_agents.issuer.service import Service

    p, url = _anvil(262626, "--base-fee", "0", "--gas-price", "20", "--disable-min-priority-fee")
    try:
        dep = Account.from_key(DEV_KEYS[0])
        local = Chain("blockid", url, 262626, dep, receipt_timeout=30, poll_latency=0.05)
        st = RoleStore()
        svc = Service(IssuerConfig(internal_token="t", local_rpc_url=url, hoodi_rpc_url="", hsk_rpc_url=""), st, local)
        _seed(st)
        svc.issue(1)
        c = st.companies[1]
        assert c["local_token"] and c["local_registry"], c.get("error")
        token, reg = local.contract("BlockIDShareToken", c["local_token"]), local.contract("IdentityRegistry",
                                                                                           c["local_registry"])
        plan = roles.role_plan(token, reg)
        assert [(x[0], x[2]) for x in plan] == [("BlockIDShareToken", "ISSUER_ROLE"), ("BlockIDShareToken", "PAUSER_ROLE"),
                                                ("BlockIDShareToken", "TRANSFER_AGENT_ROLE"),
                                                ("IdentityRegistry", "KYC_AGENT_ROLE")]

        def holds(addr):
            return [ct.functions.hasRole(rid, addr).call() for _, ct, _, rid in plan]

        st.admins[7] = {"id": 7, "company_id": 1, "address": MGR, "status": "active", "onchain": False}
        roles.company_roles(svc, 1, MGR, True)  # not pending_grant -> nothing happens
        assert holds(MGR) == [False] * 4
        st.admins[7]["status"] = "pending_grant"
        roles.company_roles(svc, 1, MGR, True)
        a = st.admins[7]
        assert holds(MGR) == [True] * 4 and a["status"] == "active" and a["onchain"] and a["grant_tx"].startswith("0x")
        assert [e["data"]["role"] for e in st.events if e["kind"] == "role_granted"] == \
            ["ISSUER_ROLE", "PAUSER_ROLE", "TRANSFER_AGENT_ROLE", "KYC_AGENT_ROLE"]
        assert all(e["chain"] == "blockid" and e["tx_hash"] for e in st.events if e["kind"] == "role_granted")
        assert local.balance(MGR) > 0  # gas drip for the new admin
        # the new admin can use its role directly (pause), the issuer keeps its own roles
        mgr_chain = local.with_account(Account.from_key(MGR_KEY))
        mgr_chain.transact(token.functions.pause())
        assert token.functions.paused().call()
        local.transact(token.functions.unpause())
        assert holds(dep.address) == [True] * 4

        st.admins[7]["status"] = "revoked"
        roles.company_roles(svc, 1, MGR, False)
        assert holds(MGR) == [False] * 4 and not st.admins[7]["onchain"] and st.admins[7]["revoke_tx"]
        assert len([e for e in st.events if e["kind"] == "role_revoked"]) == 4
        # the issuer never touches its own roles
        st.admins[8] = {"id": 8, "company_id": 1, "address": dep.address, "status": "revoked", "onchain": True}
        roles.company_roles(svc, 1, dep.address, False)
        assert holds(dep.address) == [True] * 4 and "own roles" in st.admins[8]["error"]
        assert st.kinds()[-1] == "role_revoke_failed"
    finally:
        p.kill()
