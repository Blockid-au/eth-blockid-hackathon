"""Input rules enforced on the server as well as in the browser (fixes batch 1: wallets, transfers, sign-in, admins).

Zero address and strict EIP-55, admin-approval transfers checked like plain transfers (freeze, lock-up, KYC, cap),
Google key linked to one account only, re-adding a company admin reported as an update, admin password limits,
shareholder percentages with at most 2 decimals. API tests need TEST_DATABASE_URL; the issuer re-check needs anvil.
"""
import pytest
from eth_account import Account
from test_company_admins import _company
from test_issuer_service import _seed, env, needs_anvil  # noqa: F401 (fixture)
from test_studio import ADMIN_KEY, USER, USER_KEY, needs_db, sign, siwe_login, siwe_message, studio_env  # noqa: F401

from blockid_agents.studio import accounts as acct
from blockid_agents.studio.auth import check_password, hash_password, password_problem
from blockid_agents.studio.services import transfer_blocker
from blockid_agents.tools import captable

ZERO = "0x" + "0" * 40
BOB_KEY = "0x" + "d4" * 32
BOB = Account.from_key(BOB_KEY).address
OK = {"balance_from": 100, "balance_to": 0, "from_verified": True, "to_verified": True, "frozen_from": False,
      "frozen_to": False, "lockup_until": 0, "holders": 1, "max_holders": 0, "now": 1000}


# ------------------------------------------------------------------ pure rules
def test_checksum_refuses_zero_and_mixed_case_typos():
    with pytest.raises(captable.CapTableError, match="zero address"):
        captable.checksum(ZERO)
    with pytest.raises(captable.CapTableError, match="zero address"):
        captable.checksum("0X" + "0" * 40)
    bad = BOB[:2] + BOB[2:].swapcase()
    with pytest.raises(captable.CapTableError, match="typo"):
        captable.checksum(bad)
    assert captable.checksum(BOB.lower()) == BOB  # all-lowercase has no checksum: accepted, normalised


def test_transfer_blocker_mirrors_the_token_rules():
    assert transfer_blocker(OK, 10) is None
    assert transfer_blocker(OK, 101) == "balance"
    assert transfer_blocker(OK, 60, pending=50) == "balance"  # pending requests count
    assert transfer_blocker({**OK, "frozen_from": True}, 1) == "frozen"
    assert transfer_blocker({**OK, "frozen_to": True}, 1) == "frozen"
    assert transfer_blocker({**OK, "lockup_until": 2000}, 1) == "lockup"
    assert transfer_blocker({**OK, "from_verified": False}, 1) == "not_verified"
    assert transfer_blocker({**OK, "to_verified": False}, 1) == "not_verified"
    assert transfer_blocker({**OK, "holders": 3, "max_holders": 3}, 1) == "cap"
    # a receiver who already holds shares does not add a holder; the contract gives no relief for a leaving sender
    assert transfer_blocker({**OK, "holders": 3, "max_holders": 3, "balance_to": 5}, 1) is None
    assert transfer_blocker({**OK, "holders": 3, "max_holders": 3}, 100) == "cap"


def test_password_rules_and_long_passwords():
    assert password_problem("   " * 5) and "spaces" in password_problem("   " * 5)
    assert "10 characters" in password_problem("short")
    assert "72 bytes" in password_problem("a" * 73)
    assert "72 bytes" in password_problem("é" * 40)  # 80 bytes in UTF-8
    assert "differ" in password_problem("a-long-password", "a-long-password")
    assert password_problem("a-long-password", "old") is None
    # bcrypt 5 raises on > 72 bytes; login must answer "wrong password", not 500
    assert check_password("x" * 100, None) is False
    assert check_password("x" * 100, hash_password("right-password")) is False


# ------------------------------------------------------------------ API
def _issued(db, mode: str = "approval") -> None:
    cid = _company(db, "TRF", USER)
    db.exec("UPDATE studio.companies SET transfer_mode=%s WHERE id=%s", (mode, cid))


@needs_db
def test_approval_transfer_rules(studio_env):  # noqa: F811
    db, chain = studio_env["db"], studio_env["chain"]
    admin = studio_env["client"]()
    siwe_login(admin, ADMIN_KEY)  # applies the schema
    _issued(db)
    u = studio_env["client"]()
    siwe_login(u, USER_KEY)
    body = {"to_wallet": BOB, "to_name": "Bob", "shares": 10}

    def check(**kw):
        return u.post("/v1/companies/TRF/transfers/check",
                      json={"from_wallet": USER, "to_wallet": BOB, "shares": 10, **kw}).json()

    # addresses: zero, a mixed-case typo, not an address
    for w, needle in ((ZERO, "zero address"), (BOB[:2] + BOB[2:].swapcase(), "typo"), ("0x123", "not an EVM")):
        r = u.post("/v1/companies/TRF/transfers", json={**body, "to_wallet": w})
        assert r.status_code == 422 and needle in r.json()["detail"], r.text
        assert u.post("/v1/companies/TRF/transfers/check",
                      json={"from_wallet": USER, "to_wallet": w, "shares": 1}).status_code == 422
    # a name of only spaces is no name
    assert u.post("/v1/companies/TRF/transfers", json={**body, "to_name": "   "}).status_code == 422
    assert u.post("/v1/companies/TRF/kyc", json={"name": "  "}).status_code == 422

    base = dict(chain.facts)
    for change, code in (({"frozen_from": True}, "frozen"), ({"frozen_to": True}, "frozen"),
                         ({"lockup_until": base["now"] + 60}, "lockup"), ({"from_verified": False}, "not_verified"),
                         ({"to_verified": False}, "not_verified"), ({"holders": 5, "max_holders": 5}, "cap")):
        chain.facts = {**base, **change}
        c = check()
        assert c["ok"] is False and c["reason"] == code and c["mode"] == "approval" and c["via"] == "request", c
        r = u.post("/v1/companies/TRF/transfers", json=body)
        assert r.status_code == 409 and r.json()["detail"].startswith(code + ":"), r.text
    assert db.one("SELECT count(*) AS n FROM studio.transfers")["n"] == 0

    # all clear: the request is filed; pending shares count against the balance
    chain.facts = {**base, "balance_from": 15}
    assert check()["ok"] is True
    r = u.post("/v1/companies/TRF/transfers", json={**body, "to_name": "  Bob  "})
    assert r.status_code == 201 and r.json()["to_name"] == "Bob" and r.json()["status"] == "pending"
    tid = r.json()["id"]
    assert check()["reason"] == "balance"
    assert u.post("/v1/companies/TRF/transfers", json=body).json()["detail"].startswith("balance:")

    # the admin queue shows why a request would be refused now; approving it is refused and it stays pending
    chain.facts = {**base, "frozen_to": True}
    row = next(x for x in admin.get("/v1/admin/transfers").json() if x["id"] == tid)
    assert row["blocker"] == "frozen"
    r = admin.post(f"/v1/admin/transfers/{tid}/approve")
    assert r.status_code == 409 and r.json()["detail"].startswith("frozen:")
    assert db.one("SELECT status FROM studio.transfers WHERE id=%s", (tid,))["status"] == "pending"
    assert not [c for c in studio_env["calls"] if c[0] == "/transfer"]
    # chain unreadable: refuse (fail closed), the queue still loads
    chain.fail = True
    assert admin.post(f"/v1/admin/transfers/{tid}/approve").status_code == 503
    assert u.post("/v1/companies/TRF/transfers", json=body).status_code == 503
    assert next(x for x in admin.get("/v1/admin/transfers").json() if x["id"] == tid)["blocker"] is None
    chain.fail = False
    chain.facts = base
    assert next(x for x in admin.get("/v1/admin/transfers").json() if x["id"] == tid)["blocker"] is None
    assert admin.post(f"/v1/admin/transfers/{tid}/approve").status_code == 202
    assert studio_env["calls"][-1] == ("/transfer", {"transfer_id": tid})


@needs_db
def test_free_mode_check_uses_the_same_rules(studio_env):  # noqa: F811
    db, chain = studio_env["db"], studio_env["chain"]
    siwe_login(studio_env["client"](), ADMIN_KEY)
    _issued(db, mode="free")
    u = studio_env["client"]()
    chain.facts = {**chain.facts, "to_verified": False}
    c = u.post("/v1/companies/TRF/transfers/check", json={"from_wallet": USER, "to_wallet": BOB, "shares": 1}).json()
    assert c["ok"] is False and c["reason"] == "not_verified" and c["via"] == "wallet" and c["mode"] == "free"
    # tx_hash must look like a transaction hash
    siwe_login(u, USER_KEY)
    r = u.post("/v1/companies/TRF/transfers", json={"to_wallet": BOB, "to_name": "Bob", "shares": 1, "tx_hash": "0x12"})
    assert r.status_code == 422


def _google(c, key, sub, monkeypatch):
    monkeypatch.setattr(acct, "verify_google", lambda cred, cid: acct.GoogleIdentity(sub, f"{sub}@x.co", sub, None))
    n = c.get("/v1/auth/nonce").json()["nonce"]
    m = siwe_message(Account.from_key(key).address, n)
    return c.post("/v1/auth/google", json={"credential": "x", "message": m, "signature": sign(m, key)})


@needs_db
def test_google_key_belongs_to_one_account(studio_env, monkeypatch):  # noqa: F811
    db = studio_env["db"]
    siwe_login(studio_env["client"](), ADMIN_KEY)
    r = _google(studio_env["client"](), BOB_KEY, "g-ana", monkeypatch)
    assert r.status_code == 200 and r.json()["new_wallet"] is False and r.json()["wallets"] == []
    # a second Google account on the same browser key: refused, nothing linked
    r = _google(studio_env["client"](), BOB_KEY, "g-ben", monkeypatch)
    assert r.status_code == 409 and "another account" in r.json()["detail"]
    assert db.one("SELECT count(*) AS n FROM studio.accounts WHERE subject='g-ben'")["n"] == 0
    # the same account again: fine, nothing new
    r = _google(studio_env["client"](), BOB_KEY, "g-ana", monkeypatch)
    assert r.status_code == 200 and r.json()["new_wallet"] is False
    # the same account on a new browser (new key): signed in, told about the wallet it already has
    r = _google(studio_env["client"](), USER_KEY, "g-ana", monkeypatch)
    assert r.status_code == 200 and r.json()["new_wallet"] is True and r.json()["wallets"] == [BOB]
    r = _google(studio_env["client"](), USER_KEY, "g-ana", monkeypatch)
    assert r.json()["new_wallet"] is False  # only the first time


@needs_db
def test_readding_a_company_admin_is_an_update(studio_env):  # noqa: F811
    db = studio_env["db"]
    admin = studio_env["client"]()
    siwe_login(admin, ADMIN_KEY)
    _company(db, "ADM", USER)
    db.apply_schema()  # creator becomes owner
    owner = studio_env["client"]()
    siwe_login(owner, USER_KEY)
    r = owner.post("/v1/companies/ADM/admins", json={"address": BOB, "label": "CFO", "role": "owner"})
    assert r.status_code == 201 and r.json()["updated"] is False and r.json()["previous_role"] is None
    r = owner.post("/v1/companies/ADM/admins", json={"address": BOB.lower(), "role": "manager"})
    assert r.json()["updated"] is True and r.json()["previous_role"] == "owner" and r.json()["role"] == "manager"
    assert r.json()["label"] == "CFO"  # an empty label keeps the old one
    assert owner.post("/v1/companies/ADM/admins", json={"address": ZERO}).status_code == 422
    assert admin.post("/v1/admin/issuer-wallets", json={"address": ZERO, "label": "x"}).status_code == 422


@needs_db
def test_admin_password_limits(studio_env):  # noqa: F811
    p = studio_env["client"]()
    assert p.post("/v1/auth/login", json={"username": "nobody", "password": "x" * 150}).status_code == 401
    assert p.post("/v1/auth/login", json={"username": "admin", "password": "admin"}).status_code == 200
    for new, needle in (("x" * 73, "72 bytes"), (" " * 12, "spaces"), ("admin", "10 characters")):
        r = p.post("/v1/auth/change-password", json={"current": "admin", "new": new})
        assert r.status_code == 422 and needle in r.json()["detail"], r.text
    assert p.post("/v1/auth/change-password", json={"current": "admin", "new": "x" * 72}).json() == {"ok": True}


@needs_db
def test_shareholder_rules_on_create(studio_env):  # noqa: F811
    runner = studio_env["runner"]
    u, a = studio_env["client"](), studio_env["client"]()
    siwe_login(u, USER_KEY)
    siwe_login(a, ADMIN_KEY)
    vid = u.post("/v1/studio/valuations", json={"url": "agritrace.example"}).json()["id"]
    assert runner.drain() == 1
    assert a.post(f"/v1/studio/valuations/{vid}/decision", json={"approved": True}).status_code == 200

    def create(holders, total=None):
        return u.post("/v1/studio/companies", json={"valuation_id": vid, "name": "AgriTrace", "ticker": "AGT",
                                                    "holders": holders, "total_shares": total})
    r = create([{"name": "A", "wallet": USER, "pct": 33.333}, {"name": "B", "wallet": BOB, "pct": 66.667}])
    assert r.status_code == 422 and "2 decimals" in r.json()["detail"]
    r = create([{"name": "A", "wallet": ZERO, "pct": 100}])
    assert r.status_code == 422 and "zero address" in r.json()["detail"]
    r = create([{"name": "   ", "wallet": USER, "pct": 100}])
    assert r.status_code == 422 and "name" in r.json()["detail"]
    r = create([{"name": "A", "wallet": USER, "pct": 50}, {"name": "B", "wallet": USER.lower(), "pct": 50}])
    assert r.status_code == 422 and "duplicate" in r.json()["detail"]
    r = create([{"name": "A", "wallet": USER, "pct": 99.5}, {"name": "B", "wallet": BOB, "pct": 0.5}], total=10)
    assert r.status_code == 422 and "0 shares" in r.json()["detail"]


# ------------------------------------------------------------------ issuer: checked again right before sending
@needs_anvil
def test_issuer_rechecks_before_forced_transfer(env):  # noqa: F811
    from web3 import Web3

    from blockid_agents.issuer.transfers import blocker

    svc, st, L = env["svc"], env["store"], env["local"]
    _seed(st, cid=31, ticker="RCK")
    svc.issue(31)
    c = st.companies[31]
    assert c["status"] == "anchored", c.get("error")
    token = L.contract("BlockIDShareToken", c["local_token"])
    reg = L.contract("IdentityRegistry", c["local_registry"])
    holders = {h["name"]: Web3.to_checksum_address(h["wallet"]) for h in st.holders(31)}
    alice, bob = holders["Alice"], holders["Bob"]
    new = Web3.to_checksum_address("0x5000000000000000000000000000000000000005")
    assert blocker(L, token, reg, alice, bob, 10) is None
    assert blocker(L, token, reg, alice, new, 10).startswith("not_verified:")  # no auto-KYC of the receiver
    assert blocker(L, token, reg, alice, bob, 10**9).startswith("balance:")
    L.transact(token.functions.setFrozen(alice, True))
    try:
        assert blocker(L, token, reg, alice, bob, 10).startswith("frozen:")
    finally:
        L.transact(token.functions.setFrozen(alice, False))
    assert blocker(L, token, reg, alice, bob, 10) is None
