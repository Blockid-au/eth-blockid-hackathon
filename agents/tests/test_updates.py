"""Business updates: draft maths (studio/update_draft.py), content hash stability, API flow + authz
(studio/updates.py) and the issuer's on-chain record (issuer/disclose.py).

Pure tests always run; API tests need TEST_DATABASE_URL; the real-chain test also needs anvil.
"""
import hashlib
import json
from contextlib import contextmanager
from datetime import date

import pytest
from test_company_admins import MGR, OUTSIDER, OWNER, ca  # noqa: F401 (fixture)
from test_issuer_service import DEV_KEYS, _anvil, needs_anvil
from test_studio import TEST_DB, needs_db, studio_env  # noqa: F401 (fixture)

from blockid_agents.studio import update_draft as ud
from blockid_agents.studio.report_hash import canonical_json

CO = {"ticker": "AAA", "name": "AAA Pty Ltd"}


# ================================================================== draft maths
def test_periods_and_labels():
    assert ud.period_start("monthly", date(2026, 8, 31)) == date(2026, 8, 1)
    assert ud.period_start("monthly", date(2026, 9, 30)) == date(2026, 9, 1)
    assert ud.period_start("monthly", date(2026, 3, 15)) == date(2026, 2, 16)
    assert ud.period_start("quarterly", date(2026, 9, 30)) == date(2026, 7, 1)
    assert ud.period_start("annual", date(2026, 6, 30)) == date(2025, 7, 1)
    assert ud.period_start("weekly", date(2026, 9, 7)) == date(2026, 9, 1)
    assert ud.period_label("monthly", date(2026, 8, 31)) == "August 2026"
    assert ud.period_label("quarterly", date(2026, 9, 30)) == "Q3 2026"
    assert ud.period_label("annual", date(2026, 6, 30)) == "the year to 30 Jun 2026"
    assert ud.period_label("weekly", date(2026, 9, 7)) == "the week to 7 Sep 2026"


def test_money_and_numbers():
    assert ud.money(1_234_567) == "A$1.2M" and ud.money(950_000) == "A$950k" and ud.money(3_000_000) == "A$3M"
    assert ud.money(-120_000) == "A$120k" and ud.money(850) == "A$850" and ud.money(12.3e9) == "A$12.3B"
    assert ud.num(12.0) == 12 and isinstance(ud.num(12.0), int)
    assert ud.change_pct(112, 100) == 12 and ud.change_pct(100, 0) is None and ud.change_pct(-50, -100) == 50
    with pytest.raises(ValueError):
        ud.num(float("nan"))


def test_draft_growth_month():
    cur = {"revenue": 1_120_000, "gross_profit": 700_000, "net_profit": 150_000, "cash": 3_400_000,
           "customers": 1250, "headcount": 44}
    prev = {"revenue": 1_000_000, "gross_profit": 600_000, "net_profit": 125_000, "cash": 3_240_000,
            "customers": 1136, "headcount": 40}
    d = ud.build_draft(CO, "monthly", date(2026, 8, 1), date(2026, 8, 31), cur, prev, note="  New office.  ")
    b = d["body"]
    assert d["title"] == "AAA Pty Ltd: August 2026 update"
    assert b["highlights"][0] == "Revenue grew 12% to A$1.1M"
    assert b["highlights"][1] == "Gross profit grew 17% to A$700k (gross margin 62%)"
    assert b["highlights"][2] == "Net profit rose 20% to A$150k"
    assert b["highlights"][3] == "Cash rose 4.9% to A$3.4M"
    assert b["highlights"][4] == "Customers grew 10% to 1,250"
    assert b["highlights"][5] == "The team grew from 40 to 44 people"
    assert b["summary"] == ("In August 2026, revenue grew 12% to A$1.1M, gross profit grew 17% to A$700k "
                            "(gross margin 62%) and net profit rose 20% to A$150k.")
    assert b["risks"] == [] and b["note"] == "New office."
    k = {x["metric"]: x for x in b["kpis"]}
    assert list(k) == list(ud.METRICS)
    assert k["revenue"] == {"metric": "revenue", "value": 1120000, "prev": 1000000, "change_pct": 12, "unit": "AUD"}
    assert k["customers"]["unit"] == "count" and k["cash"]["change_pct"] == 4.9


def test_draft_losses_risks_and_missing():
    d = ud.build_draft(CO, "monthly", date(2026, 8, 1), date(2026, 8, 31),
                       {"revenue": 90_000, "net_profit": -60_000, "cash": 300_000},
                       {"revenue": 100_000, "net_profit": -40_000, "cash": 400_000})
    b = d["body"]
    assert b["highlights"] == ["Revenue fell 10% to A$90k", "Net loss widened to A$60k from A$40k",
                               "Cash fell 25% to A$300k"]
    assert b["risks"] == ["Revenue fell 10% compared with the previous period.",
                          "The net loss widened compared with the previous period.", "Cash fell 25% in the period.",
                          "At the current loss rate, cash covers about 5 months."]
    assert [x["metric"] for x in b["kpis"]] == ["revenue", "net_profit", "cash"]
    # turned profitable; first period (no previous values); nothing entered
    t = ud.build_draft(CO, "quarterly", date(2026, 7, 1), date(2026, 9, 30), {"net_profit": 20_000}, {"net_profit": -5_000})
    assert t["body"]["highlights"] == ["The business turned profitable: net profit of A$20k, from a loss of A$5k"]
    assert t["title"] == "AAA Pty Ltd: Q3 2026 update"
    f = ud.build_draft(CO, "monthly", date(2026, 8, 1), date(2026, 8, 31), {"revenue": 5000, "headcount": 3})
    assert f["body"]["highlights"] == ["Revenue was A$5k", "The team is 3 people"]
    assert f["body"]["kpis"][0]["prev"] is None and f["body"]["kpis"][0]["change_pct"] is None
    assert ud.build_draft(CO, "monthly", date(2026, 8, 1), date(2026, 8, 31), {})["body"]["summary"] == \
        "No figures were entered for August 2026."
    with pytest.raises(ValueError):
        ud.build_draft(CO, "daily", date(2026, 8, 1), date(2026, 8, 31), {})


# ================================================================== hash stability
def _row(body, **kw):
    return {"cadence": "monthly", "period_start": date(2026, 8, 1), "period_end": date(2026, 8, 31),
            "title": "AAA Pty Ltd: August 2026 update", "body": body, **kw}


def test_content_hash_stable_and_canonical():
    d = ud.build_draft(CO, "monthly", date(2026, 8, 1), date(2026, 8, 31),
                       {"revenue": 1_120_000.5, "net_profit": -3.25}, {"revenue": 1_000_000})
    row = _row(d["body"])
    h = ud.content_hash(row, CO)
    # key order, JSON round trip (as through jsonb) and extra columns do not change the hash
    shuffled = _row(json.loads(json.dumps(dict(reversed(list(d["body"].items()))))), status="published", id="x")
    assert ud.content_hash(shuffled, CO) == h
    text = ud.canonical_text(row, CO)
    assert h == "0x" + hashlib.sha256(text.encode()).hexdigest()
    assert text == canonical_json(json.loads(text))  # already canonical
    assert text.startswith('{"body":{"highlights":[') and '"type":"business_update"' in text and '"v":1' in text
    assert '"value":1120000.5' in text and '"value":-3.25' in text  # numbers print the same in Python and JS
    # any change to the words, numbers, period or business changes the hash
    edited = json.loads(json.dumps(d["body"]))
    edited["summary"] += " "
    assert ud.content_hash(_row(edited), CO) != h
    edited = json.loads(json.dumps(d["body"]))
    edited["kpis"][0]["value"] = 1_120_001
    assert ud.content_hash(_row(edited), CO) != h
    assert ud.content_hash(_row(d["body"]), {**CO, "ticker": "BBB"}) != h
    assert ud.content_hash(_row(d["body"], period_end=date(2026, 9, 30)), CO) != h
    # fixed vector: a hash recorded on chain must stay reproducible across code changes
    fixed = _row({"summary": "s", "highlights": ["a"], "risks": [], "note": "",
                  "kpis": [{"metric": "revenue", "value": 10, "prev": 8, "change_pct": 25, "unit": "AUD"}]})
    assert ud.canonical_text(fixed, CO) == (
        '{"body":{"highlights":["a"],"kpis":[{"change_pct":25,"metric":"revenue","prev":8,"unit":"AUD","value":10}],'
        '"note":"","risks":[],"summary":"s"},"cadence":"monthly","company":"AAA Pty Ltd","period_end":"2026-08-31",'
        '"period_start":"2026-08-01","ticker":"AAA","title":"AAA Pty Ltd: August 2026 update","type":"business_update",'
        '"v":1}')
    cd = ud.disclosure_calldata(h)
    assert cd == "0x424944550000" + h[2:] and len(cd) == 2 + 2 * (6 + 32)


# ================================================================== API + issuer (Postgres)
class _Rec:
    def __init__(self, n):
        self.tx_hash, self.block = "0x" + f"{n:064x}", 100 + n


class FakeLocal:
    name, chain_id, address = "blockid", 262626, "0x2567Bb502ac840cF93957C60A410160a8cCb5ddf"

    def __init__(self):
        self.sent = []

    def send(self, tx):
        self.sent.append(tx)
        return _Rec(len(self.sent))


class FakeSvc:
    def __init__(self, local=None):
        from blockid_agents.issuer.store import Store

        self.store, self.local = Store(TEST_DB), local or FakeLocal()

    @contextmanager
    def _exclusive(self, key):
        yield True


def _kpis(n):
    return {"revenue": 100_000 * (1.1 ** n), "gross_profit": 60_000 * (1.1 ** n), "net_profit": -20_000 + 10_000 * n,
            "cash": 900_000 - 10_000 * n, "customers": 100 + 12 * n, "headcount": 8 + n}


@needs_db
def test_prepare_submit_approve_publish(ca):
    from blockid_agents.issuer import disclose

    db, owner, admin, out, calls = ca["db"], ca["owner"], ca["admin"], ca["out"], ca["calls"]
    anon = ca["client"]()
    ends = [date(2026, 6, 30), date(2026, 7, 31), date(2026, 8, 31)]
    # KPIs: PUT for June, then prepare July / August with the numbers in the request
    r = owner.put("/v1/companies/AAA/kpis", json={"period_end": "2026-06-30", "values": _kpis(0)})
    assert r.status_code == 200 and r.json()["saved"]["revenue"] == 100000
    assert owner.put("/v1/companies/AAA/kpis", json={"period_end": "2026-06-30",
                                                     "values": {"cash": -1}}).status_code == 422
    assert owner.put("/v1/companies/AAA/kpis", json={"period_end": "2026-06-30",
                                                     "values": {"bogus": 1}}).status_code == 422
    assert owner.put("/v1/companies/AAA/kpis", json={"period_end": "2099-01-31", "values": {}}).status_code == 422
    ids = []
    for i, end in enumerate(ends):
        body = {"cadence": "monthly", "period_end": end.isoformat(), "note": f"note {i}"}
        if i:
            body["kpis"] = _kpis(i)
        r = owner.post("/v1/companies/AAA/updates", json=body)
        assert r.status_code == 201, r.text
        u = r.json()
        assert u["status"] == "draft" and u["period_start"] == end.replace(day=1).isoformat()
        ids.append(u["id"])
    u = owner.get(f"/v1/updates/{ids[2]}").json()
    k = {x["metric"]: x for x in u["body"]["kpis"]}
    assert k["revenue"]["value"] == 121000 and k["revenue"]["prev"] == 110000 and k["revenue"]["change_pct"] == 10
    assert u["title"] == "AAA Pty Ltd: August 2026 update" and u["body"]["note"] == "note 2"
    assert owner.get("/v1/companies/AAA/kpis").json()["periods"][0]["period_end"] == "2026-08-31"

    # drafts are private
    assert anon.get("/v1/companies/AAA/updates").json()["updates"] == []
    assert anon.get(f"/v1/updates/{ids[0]}").status_code == 404
    assert out.get(f"/v1/updates/{ids[0]}").status_code == 404
    assert len(owner.get("/v1/companies/AAA/updates").json()["updates"]) == 3

    # edit, then submit; a pending update cannot be edited or re-prepared
    r = owner.patch(f"/v1/updates/{ids[0]}", json={"title": "June update", "summary": "A good month."})
    assert r.status_code == 200 and r.json()["title"] == "June update" and r.json()["body"]["summary"] == "A good month."
    assert owner.patch(f"/v1/updates/{ids[0]}", json={"title": " "}).status_code == 422
    for uid in ids:
        assert owner.post(f"/v1/updates/{uid}/submit").json()["status"] == "pending_approval"
    assert owner.post(f"/v1/updates/{ids[0]}/submit").status_code == 409
    assert owner.patch(f"/v1/updates/{ids[0]}", json={"summary": "x"}).status_code == 409
    assert owner.post("/v1/companies/AAA/updates", json={"cadence": "monthly", "period_end": "2026-06-30"}).status_code == 409

    # the queue: platform admin sees them; the company owner cannot approve its own update
    ap = admin.get("/v1/admin/approvals").json()
    assert [x["id"] for x in ap["updates"]] == ids and ap["updates"][0]["ticker"] == "AAA"
    assert owner.get("/v1/admin/approvals").json()["updates"] == []
    assert owner.post(f"/v1/admin/updates/{ids[0]}/approve").status_code == 403
    assert out.post(f"/v1/admin/updates/{ids[0]}/reject", json={"reason": "no"}).status_code == 403
    assert anon.post(f"/v1/admin/updates/{ids[0]}/approve").status_code == 401

    # reject -> editable again -> resubmit
    r = admin.post(f"/v1/admin/updates/{ids[1]}/reject", json={"reason": "check cash"})
    assert r.json()["status"] == "rejected" and r.json()["reason"] == "check cash"
    assert owner.patch(f"/v1/updates/{ids[1]}", json={"note": "Cash checked."}).json()["status"] == "draft"
    assert owner.post(f"/v1/updates/{ids[1]}/submit").json()["status"] == "pending_approval"

    # approve -> issuer asked -> the issuer job records the hash -> published
    svc = FakeSvc()
    for uid in ids:
        r = admin.post(f"/v1/admin/updates/{uid}/approve")
        assert r.status_code == 202 and r.json()["status"] == "publishing"
        assert calls[-1] == ("/disclose", {"update_id": uid})
        assert admin.post(f"/v1/admin/updates/{uid}/approve").status_code == 409
        disclose.disclose(svc, uid)
    assert [tx["to"] for tx in svc.local.sent] == [FakeLocal.address] * 3
    assert all(tx["value"] == 0 and tx["data"].startswith("0x424944550000") for tx in svc.local.sent)

    pub = anon.get("/v1/companies/AAA/updates").json()["updates"]
    assert [x["id"] for x in pub] == ids[::-1] and all(x["status"] == "published" for x in pub)
    assert "created_by" not in pub[0]
    d = anon.get(f"/v1/updates/{ids[0]}").json()
    assert d["title"] == "June update" and d["anchor"]["tx_hash"] == "0x" + f"{1:064x}" and d["anchor"]["block"] == 101
    assert "0x" + hashlib.sha256(d["canonical"].encode()).hexdigest() == d["content_hash"]
    assert d["recorded"]["calldata"] == svc.local.sent[0]["data"]
    assert json.loads(d["canonical"])["body"]["summary"] == "A good month."
    ev = db.all("SELECT kind, chain, tx_hash, data FROM studio.events WHERE kind='update_published' ORDER BY id")
    assert len(ev) == 3 and ev[0]["chain"] == "blockid" and ev[0]["data"]["update_id"] == ids[0]
    detail = anon.get("/v1/companies/AAA").json()
    assert any(e["text"] == "business update published: June update" for e in detail["events"])
    acts = [x["action"] for x in db.all("SELECT action FROM studio.audit WHERE action LIKE 'update%%' ORDER BY id")]
    assert {"update_prepared", "update_edited", "update_submitted", "update_rejected", "update_approved",
            "update_published"} <= set(acts)

    # a published update is final; re-running the issuer job does nothing
    assert owner.post("/v1/companies/AAA/updates", json={"cadence": "monthly", "period_end": "2026-06-30"}).status_code == 409
    disclose.disclose(svc, ids[0])
    assert len(svc.local.sent) == 3

    # investor feed: a holder of AAA sees its updates; others see none
    assert out.get("/v1/me/updates").json()["updates"] == []
    db.exec("INSERT INTO studio.holders (company_id, name, wallet, pct, shares) VALUES (%s,'Out',%s,1,10)",
            (ca["a"], OUTSIDER))
    assert [x["id"] for x in out.get("/v1/me/updates").json()["updates"]] == ids[::-1]
    assert anon.get("/v1/me/updates").status_code == 401


@needs_db
def test_authz_and_tamper(ca):
    from blockid_agents.issuer import disclose

    db, owner, admin, out, mgr = ca["db"], ca["owner"], ca["admin"], ca["out"], ca["mgr"]
    anon = ca["client"]()
    body = {"cadence": "monthly", "period_end": "2026-08-31", "kpis": {"revenue": 1000}}
    assert anon.post("/v1/companies/AAA/updates", json=body).status_code == 401
    assert out.post("/v1/companies/AAA/updates", json=body).status_code == 403   # outsider
    assert mgr.post("/v1/companies/AAA/updates", json=body).status_code == 403   # not yet a company admin
    assert out.put("/v1/companies/AAA/kpis", json={"period_end": "2026-08-31", "values": {}}).status_code == 403
    assert out.get("/v1/companies/AAA/kpis").status_code == 403
    assert owner.post("/v1/companies/DDD/updates", json=body).status_code == 409  # not issued yet
    assert owner.post("/v1/companies/AAA/updates", json={"cadence": "monthly", "period_end": "2026-05-31"}).status_code == 422
    # a manager added by the owner can draft and submit, but not approve
    assert owner.post("/v1/companies/AAA/admins", json={"address": MGR, "role": "manager"}).status_code == 201
    u = mgr.post("/v1/companies/AAA/updates", json=body).json()
    assert u["status"] == "draft" and u["created_by"] == MGR
    assert out.patch(f"/v1/updates/{u['id']}", json={"summary": "hacked"}).status_code == 403
    assert out.post(f"/v1/updates/{u['id']}/submit").status_code == 403
    assert mgr.post(f"/v1/updates/{u['id']}/submit").status_code == 200
    assert mgr.post(f"/v1/admin/updates/{u['id']}/approve").status_code == 403
    # platform admin can draft for any company (BBB is not the owner's)
    assert admin.post("/v1/companies/BBB/updates", json=body).status_code == 201
    assert owner.get("/v1/companies/BBB/updates").json()["updates"] == []  # BBB drafts are private to BBB admins

    # tamper: the row changes after approval -> the issuer refuses, the update fails, nothing is sent
    assert admin.post(f"/v1/admin/updates/{u['id']}/approve").status_code == 202
    db.exec("UPDATE studio.updates SET title='changed' WHERE id=%s", (u["id"],))
    svc = FakeSvc()
    disclose.disclose(svc, u["id"])
    row = db.one("SELECT status, error FROM studio.updates WHERE id=%s", (u["id"],))
    assert row["status"] == "failed" and "changed after it was approved" in row["error"] and not svc.local.sent
    # failed -> back in the queue; re-approving recomputes the hash of what is there now
    assert [x["id"] for x in admin.get("/v1/admin/approvals").json()["updates"]] == [u["id"]]
    assert admin.post(f"/v1/admin/updates/{u['id']}/approve").status_code == 202
    disclose.disclose(svc, u["id"])
    assert db.one("SELECT status FROM studio.updates WHERE id=%s", (u["id"],))["status"] == "published"

    # issuer unreachable: 502 and the update goes back to waiting
    import httpx

    from blockid_agents.studio.services import IssuerClient

    v = owner.post("/v1/companies/AAA/updates", json={**body, "period_end": "2026-07-31"}).json()
    owner.post(f"/v1/updates/{v['id']}/submit")
    admin.app.state.studio.issuer = IssuerClient("http://issuer", "t", transport=httpx.MockTransport(
        lambda req: httpx.Response(503, text="down")))
    assert admin.post(f"/v1/admin/updates/{v['id']}/approve").status_code == 502
    row = db.one("SELECT status, error FROM studio.updates WHERE id=%s", (v["id"],))
    assert row["status"] == "pending_approval" and "503" in row["error"]


@needs_db
@needs_anvil
def test_disclose_on_a_real_chain(ca):
    """The recorded transaction: 0 value, issuer -> issuer, calldata = tag + sha256 of the canonical text."""
    from eth_account import Account

    from blockid_agents.issuer import disclose
    from blockid_agents.issuer.chain import Chain

    proc, url = _anvil(262626)
    try:
        chain = Chain("blockid", url, 262626, Account.from_key(DEV_KEYS[0]), poll_latency=0.1)
        owner, admin = ca["owner"], ca["admin"]
        u = owner.post("/v1/companies/AAA/updates", json={"cadence": "monthly", "period_end": "2026-08-31",
                                                          "kpis": {"revenue": 5000, "customers": 12}}).json()
        owner.post(f"/v1/updates/{u['id']}/submit")
        h = admin.post(f"/v1/admin/updates/{u['id']}/approve").json()["content_hash"]
        disclose.disclose(FakeSvc(chain), u["id"])
        d = admin.get(f"/v1/updates/{u['id']}").json()
        assert d["status"] == "published" and d["content_hash"] == h
        tx = chain.w3.eth.get_transaction(d["anchor"]["tx_hash"])
        assert tx["from"] == tx["to"] == chain.address and tx["value"] == 0
        assert "0x" + bytes(tx["input"]).hex() == "0x424944550000" + h[2:]
        assert "0x" + hashlib.sha256(d["canonical"].encode()).hexdigest() == h
    finally:
        proc.kill()
