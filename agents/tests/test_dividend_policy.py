"""Automatic dividends (studio/dividend_policy.py): amount maths + cap, policy authz and approval, declaration on a
published update (once per update), the veto window, and execution through the (mocked) issuer only after pay_after.

Pure tests always run; API tests need TEST_DATABASE_URL (throwaway Postgres).
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
from psycopg.types.json import Jsonb
from test_company_admins import MGR, OUTSIDER, OWNER, TOKEN, ca  # noqa: F401 (fixture)
from test_studio import needs_db, studio_env  # noqa: F401 (fixture)

from blockid_agents.studio import dividend_policy as dp
from blockid_agents.studio.metrics import event_text

M = 1_000_000


# ================================================================== pure maths
def test_amount_ratio_fixed_cap_and_rounding():
    ratio = {"kind": "payout_ratio", "ratio_pct": 30, "max_maud_per_round": 20_000}
    assert dp.policy_amount_units(ratio, 50_000) == 15_000 * M
    assert dp.policy_amount_units(ratio, 100_000) == 20_000 * M          # capped
    assert dp.policy_amount_units(ratio, 0) == 0 and dp.policy_amount_units(ratio, -5_000) == 0
    assert dp.policy_amount_units(ratio, None) == 0
    assert dp.policy_amount_units(ratio, 10.01) == 300 * 10_000          # 3.003 -> 3.00 (whole cents, down)
    assert dp.policy_amount_units({**ratio, "ratio_pct": "12.5"}, "1000") == 125 * M  # numeric from Postgres
    fixed = {"kind": "fixed", "fixed_maud": 5_000, "max_maud_per_round": 4_000}
    assert dp.policy_amount_units(fixed, 1_000_000) == 4_000 * M          # capped
    assert dp.policy_amount_units({**fixed, "max_maud_per_round": 10_000}, 3_000) == 3_000 * M  # never above profit
    assert dp.policy_amount_units(fixed, -1) == 0


def test_next_period_and_net_profit():
    assert dp.next_period_end("quarterly", date(2026, 9, 27)) == date(2026, 9, 30)
    assert dp.next_period_end("quarterly", date(2026, 10, 1)) == date(2026, 12, 31)
    assert dp.next_period_end("monthly", date(2026, 2, 3)) == date(2026, 2, 28)
    body = {"kpis": [{"metric": "revenue", "value": 9}, {"metric": "net_profit", "value": -3.5}]}
    assert dp.net_profit_of({"body": body}) == -3.5 and dp.net_profit_of({"body": {}}) is None


def test_event_text():
    e = {"kind": "dividend_declared", "data": {"total_units": 1234 * M, "period": "Q3 2026",
                                               "pay_after": "2026-10-02T01:00:00+00:00"}}
    assert event_text(e) == "dividend of 1,234.00 mAUD announced for Q3 2026, paid from 2026-10-02"
    assert event_text({"kind": "dividend_vetoed", "data": {"total_units": 5 * M}}) == \
        "announced dividend of 5.00 mAUD cancelled by the company"


# ================================================================== API (Postgres)
POLICY = {"kind": "payout_ratio", "ratio_pct": 30, "max_maud_per_round": 20_000, "frequency": "quarterly",
          "veto_hours": 24}


def _publish(db, cid: int, cadence: str, end: date, net_profit, at: datetime | None = None) -> str:
    uid = "upd_" + uuid.uuid4().hex[:12]
    kpis = [{"metric": "revenue", "value": 500_000, "prev": None, "change_pct": None, "unit": "AUD"}]
    if net_profit is not None:
        kpis.append({"metric": "net_profit", "value": net_profit, "prev": None, "change_pct": None, "unit": "AUD"})
    db.exec("INSERT INTO studio.updates (id, company_id, cadence, period_start, period_end, status, title, body, "
            "published_at) VALUES (%s,%s,%s,%s,%s,'published','t',%s,%s)",
            (uid, cid, cadence, end.replace(day=1), end, Jsonb({"summary": "", "highlights": [], "risks": [],
                                                                "kpis": kpis, "note": ""}),
             at or datetime.now(timezone.utc)))
    return uid


def _holders(ca):
    db = ca["db"]
    for name, w, n in (("Owner", OWNER, 600), ("Out", OUTSIDER, 400)):
        db.exec("INSERT INTO studio.holders (company_id, name, wallet, pct, shares) VALUES (%s,%s,%s,%s,%s)",
                (ca["a"], name, w, n / 10, n))
    ca["chain"].balances_by_token[TOKEN] = {OWNER.lower(): 600, OUTSIDER.lower(): 400}


def _auto(ca):
    return ca["admin"].app.state.studio.automation


@needs_db
def test_policy_authz_and_approval(ca):
    owner, admin, out, mgr = ca["owner"], ca["admin"], ca["out"], ca["mgr"]
    anon = ca["client"]()
    assert anon.put("/v1/companies/AAA/dividend-policy", json=POLICY).status_code == 401
    assert out.put("/v1/companies/AAA/dividend-policy", json=POLICY).status_code == 403
    assert mgr.put("/v1/companies/AAA/dividend-policy", json=POLICY).status_code == 403   # not a company admin yet
    assert out.get("/v1/companies/AAA/dividend-policy").status_code == 403
    assert owner.put("/v1/companies/DDD/dividend-policy", json=POLICY).status_code == 409  # not issued
    assert owner.put("/v1/companies/AAA/dividend-policy", json={**POLICY, "ratio_pct": None}).status_code == 422
    assert owner.put("/v1/companies/AAA/dividend-policy", json={**POLICY, "ratio_pct": 101}).status_code == 422
    assert owner.put("/v1/companies/AAA/dividend-policy", json={**POLICY, "veto_hours": 0}).status_code == 422
    assert owner.put("/v1/companies/AAA/dividend-policy", json={**POLICY, "frequency": "weekly"}).status_code == 422
    assert owner.get("/v1/companies/AAA/dividend-policy").json()["policy"] is None
    assert owner.post("/v1/companies/AAA/dividend-policy/submit").status_code == 404

    r = owner.put("/v1/companies/AAA/dividend-policy", json=POLICY)
    assert r.status_code == 200, r.text
    p = r.json()["policy"]
    assert p["status"] == "draft" and p["ratio_pct"] == 30 and p["max_maud_per_round"] == 20000 and p["veto_hours"] == 24
    assert owner.post("/v1/companies/AAA/dividend-policy/pause").status_code == 409  # not active
    assert owner.post("/v1/companies/AAA/dividend-policy/submit").json()["policy"]["status"] == "pending_approval"
    assert owner.put("/v1/companies/AAA/dividend-policy", json=POLICY).status_code == 409  # waiting for a decision

    # only a platform admin approves; the company's own admins do not see the queue item
    pid = p["id"]
    assert [x["id"] for x in admin.get("/v1/admin/approvals").json()["policies"]] == [pid]
    assert owner.get("/v1/admin/approvals").json()["policies"] == []
    assert owner.post(f"/v1/admin/dividend-policies/{pid}/approve").status_code == 403
    assert anon.post(f"/v1/admin/dividend-policies/{pid}/approve").status_code == 401
    r = admin.post(f"/v1/admin/dividend-policies/{pid}/reject", json={"reason": "cap too high"})
    assert r.json()["status"] == "rejected" and r.json()["reason"] == "cap too high"
    assert admin.post(f"/v1/admin/dividend-policies/{pid}/approve").status_code == 409
    assert owner.post("/v1/companies/AAA/dividend-policy/submit").json()["policy"]["status"] == "pending_approval"
    r = admin.post(f"/v1/admin/dividend-policies/{pid}/approve")
    assert r.status_code == 200 and r.json()["status"] == "active" and r.json()["approved_at"]
    assert admin.get("/v1/admin/approvals").json()["policies"] == []
    v = owner.get("/v1/companies/AAA/dividend-policy").json()
    assert v["next"]["cadence"] == "quarterly" and v["next"]["veto_hours"] == 24 and v["you"] == "company_owner"

    # a manager can pause / resume; editing an active policy needs a new approval
    assert owner.post("/v1/companies/AAA/admins", json={"address": MGR, "role": "manager"}).status_code == 201
    assert mgr.post("/v1/companies/AAA/dividend-policy/pause").json()["policy"]["status"] == "paused"
    assert mgr.post("/v1/companies/AAA/dividend-policy/resume").json()["policy"]["status"] == "active"
    assert out.post("/v1/companies/AAA/dividend-policy/pause").status_code == 403
    r = mgr.put("/v1/companies/AAA/dividend-policy", json={**POLICY, "kind": "fixed", "fixed_maud": 1000})
    assert r.json()["policy"]["status"] == "draft" and r.json()["policy"]["approved_at"] is None
    acts = {x["action"] for x in ca["db"].all("SELECT action FROM studio.audit WHERE action LIKE 'dividend_policy%%'")}
    assert acts == {"dividend_policy_saved", "dividend_policy_submitted", "dividend_policy_rejected",
                    "dividend_policy_approved", "dividend_policy_paused", "dividend_policy_resumed"}


def _active_policy(ca, **kw) -> int:
    ca["owner"].put("/v1/companies/AAA/dividend-policy", json={**POLICY, **kw})
    pid = ca["owner"].post("/v1/companies/AAA/dividend-policy/submit").json()["policy"]["id"]
    assert ca["admin"].post(f"/v1/admin/dividend-policies/{pid}/approve").status_code == 200
    return pid


@needs_db
def test_declare_veto_window_and_execute(ca):
    db, owner, admin, out, calls = ca["db"], ca["owner"], ca["admin"], ca["out"], ca["calls"]
    _holders(ca)
    old = _publish(db, ca["a"], "quarterly", date(2026, 6, 30), 90_000,
                   at=datetime.now(timezone.utc) - timedelta(days=2))          # before the policy: never paid
    pid = _active_policy(ca)
    auto = _auto(ca)
    q3 = _publish(db, ca["a"], "quarterly", date(2026, 9, 30), 100_000)       # 30% = 30k -> capped at 20k
    _publish(db, ca["a"], "monthly", date(2026, 9, 30), 50_000)               # other cadence: ignored
    loss = _publish(db, ca["a"], "quarterly", date(2026, 3, 31), -10_000)     # loss: skipped
    bbb = _publish(db, ca["b"], "quarterly", date(2026, 9, 30), 100_000)      # BBB has no policy
    t0 = datetime.now(timezone.utc)
    made = auto.declare(t0)
    assert len(made) == 2 and auto.declare(t0) == [] and auto.declare(t0 + timedelta(hours=1)) == []  # once per update
    rows = {r["update_id"]: r for r in db.all("SELECT * FROM studio.dividends ORDER BY id")}
    assert set(rows) == {q3, loss} and old not in rows and bbb not in rows
    d = rows[q3]
    assert d["status"] == "scheduled" and d["source"] == "policy" and d["policy_id"] == pid
    assert d["approved_by"] == f"policy:{pid}" and d["total_units"] == 20_000 * M
    assert d["pay_after"] == t0 + timedelta(hours=24)
    assert {c["wallet"]: c["amount"] for c in d["claims"]} == {OWNER: 12_000 * M, OUTSIDER: 8_000 * M}
    assert rows[loss]["status"] == "skipped" and rows[loss]["total_units"] == 0 and "no profit" in rows[loss]["note"]

    # not in the manual admin queue; holders see it as upcoming
    assert admin.get("/v1/admin/approvals").json()["dividends"] == []
    h = out.get("/v1/me/holdings").json()["positions"][0]
    assert h["upcoming"][0]["amount_maud"] == 8000 and h["upcoming"][0]["period_label"] == "Q3 2026"
    led = out.get("/v1/me/dividends").json()
    assert led["upcoming"][0]["ticker"] == "AAA" and led["upcoming"][0]["amount_maud"] == 8000 and led["paid"] == []
    nxt = owner.get("/v1/companies/AAA/dividend-policy").json()["next"]
    assert nxt["period_end"] >= "2026-12-31" and nxt["period_label"] != "Q3 2026"  # Q3 is already announced
    ev = [e for e in ca["client"]().get("/v1/companies/AAA").json()["events"] if e["kind"] == "dividend_declared"]
    assert len(ev) == 1 and ev[0]["text"].startswith("dividend of 20,000.00 mAUD announced for Q3 2026")

    # inside the veto window nothing is paid; after it the issuer is asked (and only then)
    assert auto.execute_due(t0 + timedelta(hours=23, minutes=59)) == []
    assert not [c for c in calls if c[0] == "/dividend"]
    assert auto.execute_due(t0 + timedelta(hours=24, seconds=1)) == [d["id"]]
    assert [c for c in calls if c[0] == "/dividend"] == [("/dividend", {"dividend_id": d["id"]})]
    assert db.one("SELECT status FROM studio.dividends WHERE id=%s", (d["id"],))["status"] == "approved"
    assert auto.execute_due(t0 + timedelta(days=3)) == []                      # not sent twice
    assert owner.post(f"/v1/companies/AAA/dividends/{d['id']}/veto").status_code == 409  # too late
    acts = [x["action"] for x in db.all("SELECT action FROM studio.audit WHERE actor=%s ORDER BY id",
                                        (f"policy:{pid}",))]
    assert acts.count("dividend_declared") == 1 and "dividend_skipped" in acts and "dividend_auto_approved" in acts

    # veto: the company cancels an announced payment during the window; it is never paid
    q4 = _publish(db, ca["a"], "quarterly", date(2026, 12, 31), 10_000)       # 30% = 3k
    t1 = datetime.now(timezone.utc)
    [did] = auto.declare(t1)
    assert db.one("SELECT total_units FROM studio.dividends WHERE id=%s", (did,))["total_units"] == 3_000 * M
    assert out.post(f"/v1/companies/AAA/dividends/{did}/veto").status_code == 403
    assert ca["client"]().post(f"/v1/companies/AAA/dividends/{did}/veto").status_code == 401
    assert owner.post(f"/v1/companies/BBB/dividends/{did}/veto").status_code == 403
    r = owner.post(f"/v1/companies/AAA/dividends/{did}/veto", json={"reason": "cash needed"})
    assert r.status_code == 200
    got = {x["id"]: x for x in r.json()["dividends"]}
    assert got[did]["status"] == "vetoed" and got[did]["period_label"] == "Q4 2026" and got[did]["note"] == "cash needed"
    assert owner.post(f"/v1/companies/AAA/dividends/{did}/veto").status_code == 409
    assert auto.execute_due(t1 + timedelta(days=2)) == []
    assert len([c for c in calls if c[0] == "/dividend"]) == 1
    assert auto.declare(t1) == []                                              # a vetoed update is not re-declared
    assert out.get("/v1/me/holdings").json()["positions"][0]["upcoming"] == []
    assert db.one("SELECT count(*) AS n FROM studio.events WHERE kind='dividend_vetoed'")["n"] == 1
    assert q4


@needs_db
def test_paused_policy_issuer_error_and_ledger(ca):
    db, owner, admin, out = ca["db"], ca["owner"], ca["admin"], ca["out"]
    _holders(ca)
    _active_policy(ca, kind="fixed", fixed_maud=1_000, ratio_pct=None, frequency="monthly", veto_hours=2)
    auto = _auto(ca)
    # paused: nothing declared, and updates published while paused are not paid after resuming
    owner.post("/v1/companies/AAA/dividend-policy/pause")
    _publish(db, ca["a"], "monthly", date(2026, 8, 31), 50_000)
    assert auto.declare() == []
    owner.post("/v1/companies/AAA/dividend-policy/resume")
    assert auto.declare() == []
    sep = _publish(db, ca["a"], "monthly", date(2026, 9, 30), 50_000, at=datetime.now(timezone.utc) + timedelta(seconds=1))
    t0 = datetime.now(timezone.utc)
    [did] = auto.declare(t0)
    assert db.one("SELECT total_units, update_id FROM studio.dividends WHERE id=%s", (did,)) == \
        {"total_units": 1_000 * M, "update_id": sep}

    # issuer down: back to scheduled, retried later (never before pay_after)
    from blockid_agents.studio.services import IssuerClient

    ctx = admin.app.state.studio
    good = ctx.issuer
    ctx.issuer = IssuerClient("http://issuer", "t", transport=httpx.MockTransport(lambda req: httpx.Response(503)))
    assert auto.execute_due(t0 + timedelta(hours=3)) == []
    row = db.one("SELECT status, pay_after, note FROM studio.dividends WHERE id=%s", (did,))
    assert row["status"] == "scheduled" and row["pay_after"] == t0 + timedelta(hours=3) + dp.RETRY_AFTER
    assert "503" in row["note"]
    ctx.issuer = good
    assert auto.execute_due(t0 + timedelta(hours=3, minutes=5)) == []
    assert auto.tick(t0 + timedelta(hours=3, minutes=11)) == {"declared": [], "executed": [did]}

    # the issuer paid: ledger lists each payment with its transaction
    db.exec("INSERT INTO studio.events (company_id, kind, chain, tx_hash, data) VALUES "
            "(%s,'dividend_claimed','blockid',%s,%s)",
            (ca["a"], "0x" + "ab" * 32, Jsonb({"dividend_id": did, "wallet": OUTSIDER, "amount": 400 * M})))
    led = out.get("/v1/me/dividends").json()
    assert led["total_maud"] == 400 and led["paid"][0]["tx_hash"] == "0x" + "ab" * 32
    assert led["paid"][0]["ticker"] == "AAA" and led["paid"][0]["company"] == "AAA Pty Ltd"
    assert ca["client"]().get("/v1/me/dividends").status_code == 401
    assert ca["client"]().get("/v1/demo/dividends").json()["demo"] is True

    # platform admin can run one pass on demand; others cannot
    assert out.post("/v1/admin/dividends/run-automation").status_code == 403
    assert admin.post("/v1/admin/dividends/run-automation").json() == {"declared": [], "executed": []}
