"""Simulated share offering (studio/offerings.py + issuer settle_offering): terms, information pack, approval, investor
reservations (caps, first come first served, holder cap, cooling-off), closing (minimum reached -> settlement,
not reached -> every reservation released), settlement through ONE issuer job (mocked issuer in the API tests; anvil
for the issuer job itself), idempotency and authorisation.

API tests need TEST_DATABASE_URL (throwaway Postgres); the issuer job test needs anvil + forge artifacts.
"""
import threading
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from eth_account import Account
from psycopg.types.json import Jsonb
from test_company_admins import OUTSIDER, OWNER, TOKEN, ca  # noqa: F401 (fixture)
from test_dividend_policy import _publish
from test_issuer_service import FakeStore, _seed, env, needs_anvil  # noqa: F401 (fixture)
from test_studio import TEST_DB, needs_db, siwe_login, studio_env  # noqa: F401 (fixture)

from blockid_agents.studio import offerings as of
from blockid_agents.studio.metrics import event_text

INV_KEYS = ["0x" + f"{i + 0x31:02x}" * 32 for i in range(10)]
INV = [Account.from_key(k).address for k in INV_KEYS]
DEMO = "0x" + "d3" * 20


# ================================================================== pure helpers
def test_amounts_and_hash():
    assert of.shares_for(100, "1.25") == 80 and of.shares_for("99.99", 1) == 99 and of.shares_for(0.5, 1) == 0
    assert of.amount_for(3, "0.3333") == Decimal("1.00") and of.amount_for(80, 1.25) == Decimal("100.00")
    a = {"b": 1, "a": [1, 2], "t": datetime(2026, 1, 1, tzinfo=timezone.utc)}
    assert of.pack_hash(a) == of.pack_hash({"t": datetime(2026, 1, 1, tzinfo=timezone.utc), "a": [1, 2], "b": 1})
    assert of.pack_hash(a).startswith("0x") and len(of.pack_hash(a)) == 66


def test_event_texts_plain():
    assert event_text({"kind": "offering_released", "data": {}}).endswith("all reservations released")
    t = event_text({"kind": "offering_settled", "data": {"shares": 1500, "investors": 2}})
    assert t == "share offering completed: 1,500 new shares issued to 2 investors (simulated payment)"
    for k in ("offering_opened", "offering_closed", "offering_released", "offering_settled"):
        txt = event_text({"kind": k, "data": {"shares": 1, "price_aud": 1, "investors": 1}}).lower()
        assert not any(w in txt for w in ("merkle", "issuer", "anchor", "relayer", "hoodi", "hashkey", "svi",
                                          "return", "yield", "guarantee"))


# ================================================================== API (Postgres)
def _closes(days: float = 10) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


TERMS = {"price_aud": 1.25, "shares_offered": 1000, "min_raise_aud": 500, "max_per_investor_shares": 400,
         "use_of_funds": "Hire two engineers and open a Sydney office."}


def _setup(ca):
    """AAA: 600 + 400 shares (OWNER, OUTSIDER), a valuation with a range + confidence, a mark, 4 published updates."""
    db = ca["db"]
    for name, w, n in (("Owner", OWNER, 600), ("Out", OUTSIDER, 400)):
        db.exec("INSERT INTO studio.holders (company_id, name, wallet, pct, shares) VALUES (%s,%s,%s,%s,%s)",
                (ca["a"], name, w, n / 10, n))
    ca["chain"].balances_by_token[TOKEN] = {OWNER.lower(): 600, OUTSIDER.lower(): 400}
    ca["chain"].caps[TOKEN] = 500  # the token's maxShareholders()
    db.exec("INSERT INTO studio.valuations (id, url, requested_by, status, result) VALUES ('val-aaa', "
            "'https://aaa.example', %s, 'approved', %s)",
            (OWNER, Jsonb({"svi": {"valuation_low_aud": 800, "valuation_mid_aud": 1000, "valuation_high_aud": 1400,
                                   "triangulation": {"confidence": "medium"}}})))
    db.exec("UPDATE studio.companies SET valuation_id='val-aaa', grade='B' WHERE id=%s", (ca["a"],))
    db.exec("INSERT INTO studio.marks (company_id, valuation_aud, mark_aud, source) VALUES (%s, 1100, 1.1, 'revaluation')",
            (ca["a"],))
    for i, m in enumerate((5, 6, 7, 8)):
        _publish(db, ca["a"], "monthly", date(2026, m, 30 if m == 6 else 31), 1000 * i,
                 at=datetime.now(timezone.utc) - timedelta(days=30 * (4 - i)))


def _open(ca, **terms) -> int:
    owner, admin = ca["owner"], ca["admin"]
    r = owner.put("/v1/companies/AAA/offering", json={**TERMS, "closes_at": _closes(), **terms})
    assert r.status_code == 200, r.text
    assert owner.post("/v1/companies/AAA/offering/submit").status_code == 200
    oid = r.json()["offering"]["id"]
    r = admin.post(f"/v1/admin/offerings/{oid}/approve")
    assert r.status_code == 200, r.text
    return oid


def _investor(ca, i: int):
    c = ca["client"]()
    siwe_login(c, INV_KEYS[i])
    return c


def _demo(ca):
    object.__setattr__(ca["admin"].app.state.studio.settings, "demo_wallet", DEMO)
    c = ca["client"]()
    assert c.post("/v1/auth/demo").status_code == 200
    return c


def _audit(db, action: str) -> list[dict]:
    return db.all("SELECT * FROM studio.audit WHERE action=%s ORDER BY id", (action,))


@needs_db
def test_terms_pack_authz_and_approval(ca):
    _setup(ca)
    db, owner, admin, out, mgr = ca["db"], ca["owner"], ca["admin"], ca["out"], ca["mgr"]
    anon = ca["client"]()
    body = {**TERMS, "closes_at": _closes()}
    assert anon.put("/v1/companies/AAA/offering", json=body).status_code == 401
    assert out.put("/v1/companies/AAA/offering", json=body).status_code == 403
    assert mgr.get("/v1/companies/AAA/offering").status_code == 403
    assert owner.put("/v1/companies/DDD/offering", json=body).status_code == 409          # not issued
    assert owner.put("/v1/companies/AAA/offering", json={**body, "closes_at": _closes(-1)}).status_code == 422
    assert owner.put("/v1/companies/AAA/offering", json={**body, "closes_at": _closes(400)}).status_code == 422
    assert owner.put("/v1/companies/AAA/offering", json={**body, "max_per_investor_shares": 1001}).status_code == 422
    assert owner.put("/v1/companies/AAA/offering", json={**body, "min_raise_aud": 1250.01}).status_code == 422
    assert owner.put("/v1/companies/AAA/offering", json={**body, "price_aud": 0}).status_code == 422
    assert owner.put("/v1/companies/AAA/offering", json={**body, "max_holders": 10**5}).status_code == 422
    assert owner.post("/v1/companies/AAA/offering/submit").status_code == 404

    v = owner.get("/v1/companies/AAA/offering").json()
    assert v["offering"] is None and v["defaults"]["price_aud"] == 1.1 and v["defaults"]["holders"] == 2
    assert v["you"] == "company_owner" and v["live"] is True

    r = owner.put("/v1/companies/AAA/offering", json=body)
    assert r.status_code == 200, r.text
    v = r.json()
    o, pack = v["offering"], v["pack"]
    assert o["status"] == "draft" and o["max_raise_aud"] == 1250 and o["cooling_off_days"] == 5
    assert pack["terms"]["price_aud"] == 1.25 and pack["terms"]["max_raise_aud"] == 1250
    assert pack["valuation"]["low_aud"] == 800 and pack["valuation"]["high_aud"] == 1400
    assert pack["valuation"]["confidence"] == "medium" and pack["valuation"]["price_aud"] == 1.1
    assert [u["period_label"] for u in pack["updates"]] == ["August 2026", "July 2026", "June 2026"]  # last 3 published
    assert pack["cap_table"]["before"]["total_shares"] == 1000 and pack["cap_table"]["after"]["total_shares"] == 2000
    assert pack["cap_table"]["after"]["new_pct"] == 50 and pack["cap_table"]["before"]["top"][0]["name"] == "Owner"
    assert pack["risks"] == list(of.RISKS) and pack["notices"] == [] and pack["simulated"] is True
    # a price far above the latest approved price is flagged
    assert owner.put("/v1/companies/AAA/offering", json={**body, "price_aud": 2}).json()["pack"]["notices"] == \
        ["price_above_mark"]
    assert owner.put("/v1/companies/AAA/offering", json=body).status_code == 200  # still one offering (edited)
    assert db.one("SELECT count(*) AS n FROM studio.offerings")["n"] == 1

    # drafts are private
    oid = o["id"]
    assert anon.get(f"/v1/offerings/{oid}").status_code == 404
    assert anon.get("/v1/offerings").json()["offerings"] == []
    assert owner.get(f"/v1/offerings/{oid}").json()["pack"]["terms"]["shares_offered"] == 1000

    r = owner.post("/v1/companies/AAA/offering/submit")
    assert r.json()["offering"]["status"] == "pending_approval" and r.json()["offering"]["pack_hash"].startswith("0x")
    assert owner.put("/v1/companies/AAA/offering", json=body).status_code == 409  # waiting for a decision
    stored = db.one("SELECT pack, pack_hash FROM studio.offerings WHERE id=%s", (oid,))
    assert of.pack_hash(stored["pack"]) == stored["pack_hash"]

    # only a platform admin decides (queue "offerings"); company admins do not see it
    assert [x["id"] for x in admin.get("/v1/admin/approvals").json()["offerings"]] == [oid]
    assert owner.get("/v1/admin/approvals").json()["offerings"] == []
    assert owner.post(f"/v1/admin/offerings/{oid}/approve").status_code == 403
    assert anon.post(f"/v1/admin/offerings/{oid}/approve").status_code == 401
    r = admin.post(f"/v1/admin/offerings/{oid}/reject", json={"reason": "add the office lease to the use of funds"})
    assert r.json()["status"] == "rejected" and r.json()["reason"].startswith("add the office")
    assert admin.post(f"/v1/admin/offerings/{oid}/approve").status_code == 409
    assert owner.put("/v1/companies/AAA/offering", json={**body, "use_of_funds": "Engineers + office lease"}).json()[
        "offering"]["status"] == "draft"
    owner.post("/v1/companies/AAA/offering/submit")
    # closing date passed while waiting -> cannot open
    db.exec("UPDATE studio.offerings SET closes_at=now() - interval '1 hour' WHERE id=%s", (oid,))
    assert admin.post(f"/v1/admin/offerings/{oid}/approve").status_code == 409
    db.exec("UPDATE studio.offerings SET closes_at=now() + interval '10 days' WHERE id=%s", (oid,))
    r = admin.post(f"/v1/admin/offerings/{oid}/approve")
    assert r.status_code == 200 and r.json()["status"] == "open" and r.json()["opened_at"]
    assert admin.get("/v1/admin/approvals").json()["offerings"] == []

    # public: list, detail with the frozen pack, badge on the businesses list and the company page
    lst = anon.get("/v1/offerings").json()["offerings"]
    assert [x["id"] for x in lst] == [oid] and lst[0]["ticker"] == "AAA" and "created_by" not in lst[0]
    d = anon.get(f"/v1/offerings/{oid}").json()
    assert d["pack"]["terms"]["use_of_funds"] == "Engineers + office lease" and d["progress"]["reserved_shares"] == 0
    assert "mine" not in d and "approved_by" not in d
    cos = {c["ticker"]: c for c in anon.get("/v1/companies").json()}
    assert cos["AAA"]["offering"]["id"] == oid and cos["BBB"]["offering"] is None
    assert anon.get("/v1/companies/AAA").json()["offering"]["status"] == "open"
    ev = db.all("SELECT kind, data FROM studio.events WHERE company_id=%s AND kind LIKE 'offering%%'", (ca["a"],))
    assert [e["kind"] for e in ev] == ["offering_opened"] and ev[0]["data"]["shares"] == 1000
    assert "share offering opened: 1,000 shares at A$1.25" in anon.get("/v1/companies/AAA").json()["events"][0]["text"]
    acts = [a["action"] for a in db.all("SELECT action FROM studio.audit WHERE action LIKE 'offering%%' ORDER BY id")]
    assert acts == ["offering_saved"] * 3 + ["offering_submitted", "offering_rejected", "offering_saved",
                                            "offering_submitted", "offering_approved"]
    # one offering in progress per company; it cannot be edited or cancelled once open
    assert owner.put("/v1/companies/AAA/offering", json=body).status_code == 409
    assert owner.post("/v1/companies/AAA/offering/cancel").status_code == 409


@needs_db
def test_reservations_caps_holders_and_demo_account(ca):
    _setup(ca)
    db = ca["db"]
    oid = _open(ca, max_holders=4)  # 2 holders today -> room for 2 new investors
    demo = _demo(ca)
    url = f"/v1/offerings/{oid}/reservations"
    assert ca["client"]().post(url, json={"shares": 1, "risk_ack": True}).status_code == 401
    assert demo.post(url, json={"shares": 10}).status_code == 422                                  # risks not read
    assert demo.post(url, json={"shares": 10, "amount_aud": 5, "risk_ack": True}).status_code == 422
    assert demo.post(url, json={"amount_aud": 1, "risk_ack": True}).status_code == 422             # < 1 share
    assert demo.post(url, json={"shares": 401, "risk_ack": True}).status_code == 409               # per investor

    # the demo account reserves with no signature: A$250 -> 200 shares at A$1.25
    r = demo.post(url, json={"amount_aud": 250, "risk_ack": True})
    assert r.status_code == 201, r.text
    res = r.json()["reservation"]
    assert res["shares"] == 200 and res["amount_aud"] == 250 and res["status"] == "reserved" and res["can_withdraw"]
    assert res["wallet"].lower() == DEMO and res["name"] == "Demo investor"
    assert r.json()["offering"]["progress"]["reserved_shares"] == 200
    r = demo.post(url, json={"shares": 201, "risk_ack": True})
    assert r.status_code == 409 and "200 more" in r.json()["detail"]
    assert demo.post(url, json={"shares": 200, "risk_ack": True}).status_code == 201                # tops up to 400

    # holder cap: 2 holders + demo = 3; a 4th wallet fits, a 5th does not; an existing holder always fits
    i0, i1 = _investor(ca, 0), _investor(ca, 1)
    assert i0.post(url, json={"shares": 300, "risk_ack": True}).status_code == 201
    r = i1.post(url, json={"shares": 10, "risk_ack": True})
    assert r.status_code == 409 and "at most 4" in r.json()["detail"]
    assert ca["out"].post(url, json={"shares": 250, "risk_ack": True}).status_code == 201           # OUTSIDER holds
    # remaining: 1000 - 400 - 300 - 250 = 50
    r = ca["owner"].post(url, json={"shares": 51, "risk_ack": True})
    assert r.status_code == 409 and "only 50" in r.json()["detail"]
    assert ca["owner"].post(url, json={"shares": 50, "risk_ack": True}).status_code == 201
    r = i0.post(url, json={"shares": 1, "risk_ack": True})
    assert r.status_code == 409 and "all shares" in r.json()["detail"]
    d = demo.get(f"/v1/offerings/{oid}").json()
    assert d["progress"] == {**d["progress"], "reserved_shares": 1000, "remaining_shares": 0, "investors": 4,
                             "min_reached": True}
    assert d["mine_reserved_shares"] == 400 and len(d["mine"]) == 2 and d["you_hold"] is False
    mine = demo.get("/v1/me/reservations").json()["reservations"]
    assert [(x["ticker"], x["shares"], x["status"], x["offering_status"]) for x in mine] == \
        [("AAA", 200, "reserved", "open")] * 2
    assert len(_audit(db, "shares_reserved")) == 5


@needs_db
def test_first_come_first_served_never_oversubscribed(ca):
    _setup(ca)
    oid = _open(ca, shares_offered=1000, max_per_investor_shares=300, min_raise_aud=0)
    clients = [_investor(ca, i) for i in range(8)]
    codes: list[int] = []

    def go(c):
        codes.append(c.post(f"/v1/offerings/{oid}/reservations", json={"shares": 300, "risk_ack": True}).status_code)

    ts = [threading.Thread(target=go, args=(c,)) for c in clients]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sorted(codes) == [201] * 3 + [409] * 5
    tot = ca["db"].one("SELECT sum(shares) AS s FROM studio.reservations WHERE offering_id=%s AND status='reserved'",
                       (oid,))["s"]
    assert tot == 900  # 3 x 300; the 4th would oversell (only 100 left)


@needs_db
def test_cooling_off_and_withdraw(ca):
    _setup(ca)
    db = ca["db"]
    oid = _open(ca, min_raise_aud=0)
    demo, i0 = _demo(ca), _investor(ca, 0)
    rid = demo.post(f"/v1/offerings/{oid}/reservations", json={"shares": 100, "risk_ack": True}).json()["reservation"]["id"]
    until = db.one("SELECT cooling_off_until, created_at FROM studio.reservations WHERE id=%s", (rid,))
    assert timedelta(days=4, hours=23) < until["cooling_off_until"] - until["created_at"] <= timedelta(days=5, seconds=5)
    w = f"/v1/offerings/{oid}/reservations/{rid}/withdraw"
    assert i0.post(w).status_code == 404                                   # not theirs
    r = demo.post(w)
    assert r.status_code == 200 and r.json()["reservation"]["status"] == "withdrawn"
    assert demo.post(w).status_code == 409                                 # already withdrawn
    # cooling-off over -> firm
    rid2 = demo.post(f"/v1/offerings/{oid}/reservations", json={"shares": 100, "risk_ack": True}).json()["reservation"]["id"]
    db.exec("UPDATE studio.reservations SET cooling_off_until=now() - interval '1 minute' WHERE id=%s", (rid2,))
    r = demo.post(f"/v1/offerings/{oid}/reservations/{rid2}/withdraw")
    assert r.status_code == 409 and "cooling-off" in r.json()["detail"]
    assert demo.get("/v1/me/reservations").json()["reservations"][0]["can_withdraw"] is False
    # the cooling-off never outlasts the offering: a reservation made 2 days before close ends at the close
    db.exec("UPDATE studio.offerings SET closes_at=now() + interval '2 days' WHERE id=%s", (oid,))
    res = i0.post(f"/v1/offerings/{oid}/reservations", json={"shares": 100, "risk_ack": True}).json()["reservation"]
    close = db.one("SELECT closes_at FROM studio.offerings WHERE id=%s", (oid,))["closes_at"]
    assert datetime.fromisoformat(res["cooling_off_until"]) == close
    # closed -> nothing can be withdrawn any more
    assert ca["owner"].post("/v1/companies/AAA/offering/close").status_code == 200
    r = i0.post(f"/v1/offerings/{oid}/reservations/{res['id']}/withdraw")
    assert r.status_code == 409 and "closed" in r.json()["detail"]
    assert i0.post(f"/v1/offerings/{oid}/reservations", json={"shares": 1, "risk_ack": True}).status_code == 409
    assert [a["detail"]["shares"] for a in _audit(db, "reservation_withdrawn")] == [100]


@needs_db
def test_minimum_not_reached_releases_everything(ca):
    _setup(ca)
    db = ca["db"]
    oid = _open(ca, min_raise_aud=1000)  # 800 shares needed at A$1.25
    demo, i0 = _demo(ca), _investor(ca, 0)
    for c in (demo, i0):
        assert c.post(f"/v1/offerings/{oid}/reservations", json={"shares": 300, "risk_ack": True}).status_code == 201
    svc = ca["admin"].app.state.studio.offerings
    assert svc.tick() == {"closed": []}  # not due yet
    later = datetime.now(timezone.utc) + timedelta(days=11)
    assert svc.tick(now=later) == {"closed": [oid]}
    assert svc.tick(now=later) == {"closed": []}  # once
    o = db.one("SELECT status, close_reason, closed_by FROM studio.offerings WHERE id=%s", (oid,))
    assert o == {"status": "released", "close_reason": "closing_date", "closed_by": "automation"}
    assert {x["status"] for x in db.all("SELECT status FROM studio.reservations WHERE offering_id=%s", (oid,))} == \
        {"released"}
    ev = db.one("SELECT data FROM studio.events WHERE kind='offering_released'")["data"]
    assert ev["shares"] == 600 and ev["released"] == 2 and ev["early"] is False
    a = _audit(db, "offering_released")[0]
    assert a["actor"] == "automation" and a["detail"]["released"] == 2
    assert [x["status"] for x in demo.get("/v1/me/reservations").json()["reservations"]] == ["released"]
    assert ca["admin"].post(f"/v1/admin/offerings/{oid}/settle").status_code == 409
    assert ca["calls"] == [c for c in ca["calls"] if c[0] != "/settle-offering"]
    # a new offering can be set up afterwards
    assert ca["owner"].put("/v1/companies/AAA/offering", json={**TERMS, "closes_at": _closes()}).status_code == 200


@needs_db
def test_close_early_settle_idempotent_and_authz(ca):
    _setup(ca)
    db, owner, admin = ca["db"], ca["owner"], ca["admin"]
    oid = _open(ca)
    demo, i0 = _demo(ca), _investor(ca, 0)
    assert demo.post(f"/v1/offerings/{oid}/reservations", json={"shares": 200, "risk_ack": True}).status_code == 201
    assert demo.post(f"/v1/offerings/{oid}/reservations", json={"shares": 100, "risk_ack": True}).status_code == 201
    assert i0.post(f"/v1/offerings/{oid}/reservations", json={"shares": 150, "risk_ack": True}).status_code == 201
    assert admin.post(f"/v1/admin/offerings/{oid}/settle").status_code == 409  # still open
    assert ca["out"].post("/v1/companies/AAA/offering/close").status_code == 403
    r = owner.post("/v1/companies/AAA/offering/close")
    assert r.status_code == 200 and r.json()["offering"]["status"] == "awaiting_settlement"
    assert owner.post("/v1/companies/AAA/offering/close").status_code == 409
    assert admin.post(f"/v1/admin/offerings/{oid}/close").status_code == 409
    assert db.one("SELECT close_reason FROM studio.offerings WHERE id=%s", (oid,))["close_reason"] == "closed_early"
    assert "450 shares reserved by 2 investors" in event_text(db.one("SELECT kind, data FROM studio.events "
                                                                     "WHERE kind='offering_closed'"))
    assert [x["id"] for x in admin.get("/v1/admin/approvals").json()["offerings"]] == [oid]

    # settle: platform admin only
    assert owner.post(f"/v1/admin/offerings/{oid}/settle").status_code == 403
    assert demo.post(f"/v1/admin/offerings/{oid}/settle").status_code == 403
    r = admin.post(f"/v1/admin/offerings/{oid}/settle")
    assert r.status_code == 202, r.text
    assert r.json() == {"id": oid, "status": "settling", "investors": 2, "shares": 450}
    assert [c for c in ca["calls"] if c[0] == "/settle-offering"] == [("/settle-offering", {"offering_id": oid})]
    mints = db.all("SELECT to_wallet, shares, status, offering_id, requested_by FROM studio.mints ORDER BY id")
    assert [(m["to_wallet"].lower(), m["shares"], m["status"]) for m in mints] == \
        [(DEMO, 300, "approved"), (INV[0].lower(), 150, "approved")]
    assert all(m["offering_id"] == oid and m["requested_by"] == f"offering:{oid}" for m in mints)
    assert admin.get("/v1/admin/approvals").json()["mints"] == []             # not in the Mints queue
    assert admin.post(f"/v1/admin/offerings/{oid}/settle").status_code == 409  # already settling: no second job
    assert admin.post(f"/v1/admin/offerings/{oid}/release").status_code == 409

    # the issuer job failed half-way: one allocation minted, one failed -> approving again retries only the rest,
    # never creates a second row per investor
    db.exec("UPDATE studio.mints SET status='minted', tx_hash='0xabc' WHERE lower(to_wallet)=%s", (DEMO,))
    db.exec("UPDATE studio.mints SET status='failed' WHERE lower(to_wallet)=%s", (INV[0].lower(),))
    db.exec("UPDATE studio.offerings SET status='failed', error='boom' WHERE id=%s", (oid,))
    assert admin.post(f"/v1/admin/offerings/{oid}/settle").status_code == 202
    assert {m["to_wallet"].lower(): m["status"] for m in db.all("SELECT * FROM studio.mints")} == \
        {DEMO: "minted", INV[0].lower(): "approved"}
    assert db.one("SELECT count(*) AS n FROM studio.mints")["n"] == 2
    assert db.one("SELECT error FROM studio.offerings WHERE id=%s", (oid,))["error"] is None

    # the issuer finishes (issuer/store.py on the same database): allocations minted -> reservations allocated
    from blockid_agents.issuer.store import Store
    st = Store(TEST_DB)
    assert {m["status"] for m in st.offering_mints(oid)} == {"minted", "approved"}
    db.exec("UPDATE studio.mints SET status='minted' WHERE offering_id=%s", (oid,))
    st.finish_offering(oid)
    st.finish_offering(oid)  # idempotent
    assert db.one("SELECT status, settled_at FROM studio.offerings WHERE id=%s", (oid,))["status"] == "settled"
    res = demo.get("/v1/me/reservations").json()["reservations"]
    assert {(x["status"], x["offering_status"]) for x in res} == {("allocated", "settled")} and all(x["mint_id"] for x in res)
    assert admin.post(f"/v1/admin/offerings/{oid}/settle").status_code == 409
    acts = [a["action"] for a in db.all("SELECT action FROM studio.audit WHERE action LIKE 'offering_settle%%'")]
    assert acts == ["offering_settle_approved", "offering_settle_approved"]


@needs_db
def test_settle_issuer_unreachable_reverts_and_admin_release(ca):
    _setup(ca)
    db, admin = ca["db"], ca["admin"]
    oid = _open(ca, min_raise_aud=0)
    demo = _demo(ca)
    assert demo.post(f"/v1/offerings/{oid}/reservations", json={"shares": 10, "risk_ack": True}).status_code == 201
    admin.post(f"/v1/admin/offerings/{oid}/close")
    ctx = admin.app.state.studio
    real, ctx.issuer = ctx.issuer, None
    try:
        assert admin.post(f"/v1/admin/offerings/{oid}/settle").status_code == 503
    finally:
        ctx.issuer = real

    class Down:
        def post(self, path, body):
            from blockid_agents.studio.services import IssuerError
            raise IssuerError("issuer unreachable")

    ctx.issuer = Down()
    try:
        assert admin.post(f"/v1/admin/offerings/{oid}/settle").status_code == 502
    finally:
        ctx.issuer = real
    o = db.one("SELECT status, error FROM studio.offerings WHERE id=%s", (oid,))
    assert o["status"] == "awaiting_settlement" and "unreachable" in o["error"]
    # the admin decides not to settle: everything released, the prepared allocation is cancelled
    r = admin.post(f"/v1/admin/offerings/{oid}/release", json={"reason": "company withdrew"})
    assert r.json() == {"id": oid, "status": "released", "released": 1}
    assert db.one("SELECT status FROM studio.mints WHERE offering_id=%s", (oid,))["status"] == "rejected"
    assert [x["status"] for x in demo.get("/v1/me/reservations").json()["reservations"]] == ["released"]
    assert len(_audit(db, "offering_settle_issuer_error")) == 1 and len(_audit(db, "offering_released_by_admin")) == 1


@needs_db
def test_cancel_before_open(ca):
    _setup(ca)
    owner = ca["owner"]
    owner.put("/v1/companies/AAA/offering", json={**TERMS, "closes_at": _closes()})
    owner.post("/v1/companies/AAA/offering/submit")
    r = owner.post("/v1/companies/AAA/offering/cancel")
    assert r.status_code == 200 and r.json()["offering"] is None and r.json()["history"][0]["status"] == "cancelled"
    assert ca["admin"].get("/v1/admin/approvals").json()["offerings"] == []
    assert owner.post("/v1/companies/AAA/offering/cancel").status_code == 404


# ================================================================== issuer job (anvil)
class OfferingStore(FakeStore):
    def __init__(self):
        super().__init__()
        self.offerings: dict[int, dict] = {}
        self.reservations: list[dict] = []

    def offering(self, oid):
        return dict(self.offerings[oid]) if oid in self.offerings else None

    def offering_mints(self, oid):
        return [dict(m) for m in self.mints.values() if m.get("offering_id") == oid]

    def fail_offering(self, oid, error):
        for m in self.mints.values():
            if m.get("offering_id") == oid and m["status"] in ("approved", "minting"):
                m["status"] = "failed"
        if self.offerings[oid]["status"] == "settling":
            self.offerings[oid].update(status="failed", error=error)

    def finish_offering(self, oid):
        for r in self.reservations:
            if r["offering_id"] == oid and r["status"] == "reserved":
                r["status"] = "allocated"
        if self.offerings[oid]["status"] == "settling":
            self.offerings[oid]["status"] = "settled"


@needs_anvil
def test_issuer_settles_in_one_job_then_one_resync(env):  # noqa: F811
    svc, L = env["svc"], env["local"]
    st = OfferingStore()
    svc.store = st
    _seed(st, cid=5, ticker="OFR")
    svc.issue(5)
    c = st.companies[5]
    assert c["status"] == "anchored", c.get("error")
    token = L.contract("BlockIDShareToken", c["local_token"])
    anchor = env["anchor"]
    n0 = anchor.functions.anchorCount("OFR").call()
    a, b = Account.create().address, Account.create().address
    st.offerings[9] = {"id": 9, "company_id": 5, "status": "settling", "price_aud": Decimal("1.25")}
    st.mints[91] = {"id": 91, "company_id": 5, "to_wallet": a, "holder_name": "Ann", "shares": 300, "status": "approved",
                    "reason": "Share offering #9", "offering_id": 9}
    st.mints[92] = {"id": 92, "company_id": 5, "to_wallet": b, "holder_name": "Ben", "shares": 150, "status": "approved",
                    "reason": "Share offering #9", "offering_id": 9}
    st.reservations += [{"offering_id": 9, "wallet": a, "status": "reserved"}, {"offering_id": 9, "wallet": b,
                                                                                  "status": "reserved"}]
    svc.settle_offering(9)
    assert st.offerings[9]["status"] == "settled", st.offerings[9]
    assert token.functions.balanceOf(a).call() == 300 and token.functions.balanceOf(b).call() == 150
    assert {m["status"] for m in st.mints.values() if m.get("offering_id") == 9} == {"minted"}
    assert all(r["status"] == "allocated" for r in st.reservations)
    assert anchor.functions.anchorCount("OFR").call() == n0 + 1          # ONE re-sync for the whole offering
    assert env["hsk_anchor"].functions.anchorCount("OFR").call() == n0 + 1
    kinds = [e["kind"] for e in st.events if e["company_id"] == 5]
    assert kinds.count("offering_settled") == 1
    settled = next(e for e in st.events if e["kind"] == "offering_settled")["data"]
    assert settled["shares"] == 450 and settled["investors"] == 2 and settled["reserved_aud"] == "562.50"
    assert [e["data"].get("offering_id") for e in st.events if e["kind"] == "minted"][-2:] == [9, 9]
    assert st.companies[5]["total_shares"] == 10450

    # idempotent: a repeated call is a no-op; a retried job (status settling again, rows re-approved) never issues twice
    svc.settle_offering(9)
    st.offerings[9]["status"] = "settling"
    st.mints[92]["status"] = "approved"
    svc.settle_offering(9)
    assert token.functions.balanceOf(b).call() == 150 and token.functions.totalSupply().call() == 10450
    assert st.offerings[9]["status"] == "settled"

    # failure: company without a token -> offering failed, allocations failed (approve again to retry)
    st.companies[6] = {**st.companies[5], "id": 6, "local_token": None}
    st.offerings[10] = {"id": 10, "company_id": 6, "status": "settling", "price_aud": 1}
    st.mints[101] = {"id": 101, "company_id": 6, "to_wallet": a, "holder_name": "Ann", "shares": 1, "status": "approved",
                     "reason": "", "offering_id": 10}
    svc.settle_offering(10)
    assert st.offerings[10]["status"] == "failed" and "not issued" in st.offerings[10]["error"]
    assert st.mints[101]["status"] == "failed"


def test_issuer_settle_endpoint_needs_token_and_queues_one_job():
    from fastapi.testclient import TestClient
    from test_issuer_service import _RecSvc

    from blockid_agents.issuer.app import create_app
    from blockid_agents.issuer.config import IssuerConfig

    svc = _RecSvc()
    app = create_app(svc, IssuerConfig(internal_token="tok"))
    cl = TestClient(app)
    assert cl.post("/settle-offering", json={"offering_id": 3}).status_code == 401
    assert cl.post("/settle-offering", json={}, headers={"X-Internal-Token": "tok"}).status_code == 422
    r = cl.post("/settle-offering", json={"offering_id": 3}, headers={"X-Internal-Token": "tok"})
    assert r.status_code == 202 and r.json() == {"accepted": True, "op": "settle-offering", "offering_id": 3}
    app.state.pool.shutdown(wait=True)
    assert svc.calls == [("settle_offering", 3)]
