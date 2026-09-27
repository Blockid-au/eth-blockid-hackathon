"""Input rules the server enforces (the web app repeats them where the value is typed):

business updates   period lines up with its cadence, is over, never overlaps a sent / published update of the same
                   cadence; KPI values kept per cadence; a refused prepare never deletes stored figures; concurrent
                   prepares give 201 / 409, never 500; edits refuse an empty summary and over-long items
dividend rules     whole cents >= A$0.01, fixed <= cap, plain notes for skipped periods, announced payments listed
manual dividend    at most 6 decimals
share offering     holder cap read from the token on BlockID Chain (reserve + settle), pending mints counted, release
                   of unminted allocations only, max_holders >= current holders, >= A$0.01 per reservation,
                   concurrent PUT -> 409

Pure tests always run; API tests need TEST_DATABASE_URL (throwaway Postgres).
"""
import threading
from datetime import date, datetime, timedelta, timezone

from test_company_admins import OUTSIDER, OWNER, TOKEN, ca  # noqa: F401 (fixture)
from test_dividend_policy import POLICY, _active_policy, _auto, _holders, _publish
from test_offerings import INV, TERMS, _closes, _demo, _investor, _open, _setup
from test_studio import needs_db, studio_env  # noqa: F401 (fixture)

from blockid_agents.studio import update_draft as ud

M = 1_000_000


# ================================================================== updates: pure
def test_period_end_rules():
    ok = [("monthly", date(2026, 2, 28)), ("monthly", date(2024, 2, 29)), ("quarterly", date(2026, 3, 31)),
          ("quarterly", date(2026, 6, 30)), ("quarterly", date(2026, 9, 30)), ("quarterly", date(2026, 12, 31)),
          ("annual", date(2026, 6, 30)), ("annual", date(2026, 12, 31)), ("weekly", date(2026, 9, 9))]
    for cad, end in ok:
        assert ud.period_end_problem(cad, end) is None, (cad, end)
    assert "last day of a month" in ud.period_end_problem("monthly", date(2026, 3, 15))
    assert "last day of a month" in ud.period_end_problem("annual", date(2026, 6, 29))
    assert "31 Mar" in ud.period_end_problem("quarterly", date(2026, 8, 31))
    assert "31 Mar" in ud.period_end_problem("quarterly", date(2026, 9, 29))
    assert ud.period_end_problem("daily", date(2026, 9, 30))


# ================================================================== updates: API
def _prep(c, cadence, end, **kw):
    return c.post("/v1/companies/AAA/updates", json={"cadence": cadence, "period_end": end, **kw})


@needs_db
def test_update_periods_line_up_are_over_and_never_overlap(ca):
    owner, admin, db = ca["owner"], ca["admin"], ca["db"]
    k = {"kpis": {"revenue": 1000, "net_profit": 10}}
    r = _prep(owner, "monthly", "2026-03-15", **k)
    assert r.status_code == 422 and "last day of a month" in r.json()["detail"]
    assert _prep(owner, "quarterly", "2026-08-31", **k).status_code == 422
    assert owner.put("/v1/companies/AAA/kpis", json={"cadence": "quarterly", "period_end": "2026-08-31",
                                                     "values": {"revenue": 1}}).status_code == 422
    # not finished yet: a period ending far ahead, and the month in progress
    today = datetime.now(timezone.utc).date()
    this_month_end = (today.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    r = _prep(owner, "monthly", this_month_end.isoformat(), **k)
    assert r.status_code == 422 and "not finished" in r.json()["detail"]
    assert _prep(owner, "weekly", (today + timedelta(days=2)).isoformat(), **k).status_code == 422
    assert db.one("SELECT count(*) AS n FROM studio.updates")["n"] == 0

    # weekly: a week that shares days with a SENT weekly update is refused, naming that period; drafts do not block
    w1 = _prep(owner, "weekly", "2026-08-07", **k).json()
    assert _prep(owner, "weekly", "2026-08-10", **k).status_code == 201       # overlaps a draft only: allowed
    assert owner.post(f"/v1/updates/{w1['id']}/submit").status_code == 200
    r = _prep(owner, "weekly", "2026-08-12", **k)
    assert r.status_code == 409 and "2026-08-01 to 2026-08-07" in r.json()["detail"] and "pending approval" in \
        r.json()["detail"]
    # the draft that overlaps cannot be sent while the other one holds those days
    d2 = db.one("SELECT id FROM studio.updates WHERE period_end='2026-08-10'")["id"]
    assert owner.post(f"/v1/updates/{d2}/submit").status_code == 409
    assert _prep(owner, "weekly", "2026-08-14", **k).status_code == 201        # 8-14 Aug: no shared day
    # another cadence may cover the same days
    assert _prep(owner, "monthly", "2026-08-31", **k).status_code == 201
    # annual periods ending 30 Jun and 31 Dec overlap
    a = _prep(owner, "annual", "2025-06-30", **k).json()
    owner.post(f"/v1/updates/{a['id']}/submit")
    admin.post(f"/v1/admin/updates/{a['id']}/approve")
    r = _prep(owner, "annual", "2025-12-31", **k)
    assert r.status_code == 409 and "annual" in r.json()["detail"]
    assert _prep(owner, "annual", "2026-06-30", **k).status_code == 201       # the next year: fine


@needs_db
def test_kpis_kept_per_cadence_and_refused_prepare_keeps_figures(ca):
    owner, db = ca["owner"], ca["db"]
    put = owner.put("/v1/companies/AAA/kpis", json={"cadence": "monthly", "period_end": "2026-08-31",
                                                    "values": {"revenue": 100_000, "cash": 50_000}})
    assert put.status_code == 200 and put.json()["cadence"] == "monthly"
    # a weekly figure for the week ending the same day does not overwrite the monthly one
    assert owner.put("/v1/companies/AAA/kpis", json={"cadence": "weekly", "period_end": "2026-08-31",
                                                     "values": {"revenue": 25_000}}).status_code == 200
    periods = owner.get("/v1/companies/AAA/kpis").json()["periods"]
    by = {(p["cadence"], p["period_end"]): p["values"] for p in periods}
    assert by[("monthly", "2026-08-31")] == {"revenue": 100000, "cash": 50000}
    assert by[("weekly", "2026-08-31")] == {"revenue": 25000}
    # a monthly draft uses the monthly figures only
    u = _prep(owner, "monthly", "2026-08-31").json()
    assert {x["metric"]: x["value"] for x in u["body"]["kpis"]} == {"revenue": 100000, "cash": 50000}
    # a request that clears one figure but carries a bad one is refused and deletes nothing
    r = _prep(owner, "monthly", "2026-08-31", kpis={"revenue": None, "cash": -5})
    assert r.status_code == 422
    assert {x["metric"] for x in db.all("SELECT metric FROM studio.kpi_values WHERE cadence='monthly'")} == \
        {"revenue", "cash"}
    # clearing every figure is refused before anything is removed
    assert _prep(owner, "monthly", "2026-08-31", kpis={"revenue": None, "cash": None}).status_code == 422
    assert db.one("SELECT count(*) AS n FROM studio.kpi_values WHERE cadence='monthly'")["n"] == 2
    # cleared on purpose (with another figure left): removed
    assert _prep(owner, "monthly", "2026-08-31", kpis={"cash": None}).status_code == 201
    assert [x["metric"] for x in db.all("SELECT metric FROM studio.kpi_values WHERE cadence='monthly'")] == ["revenue"]


@needs_db
def test_prepare_races_and_status_guard(ca):
    owner, db = ca["owner"], ca["db"]
    clients = [ca["client"]() for _ in range(6)]
    from test_company_admins import OWNER_KEY
    from test_studio import siwe_login
    for c in clients:
        siwe_login(c, OWNER_KEY)
    codes: list[int] = []

    def go(c):
        codes.append(_prep(c, "monthly", "2026-07-31", kpis={"revenue": 1000}).status_code)

    ts = [threading.Thread(target=go, args=(c,)) for c in clients]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert set(codes) <= {201, 409} and 201 in codes
    assert db.one("SELECT count(*) AS n FROM studio.updates WHERE period_end='2026-07-31'")["n"] == 1
    # once sent, it cannot be rebuilt (and its figures are not touched)
    uid = db.one("SELECT id FROM studio.updates WHERE period_end='2026-07-31'")["id"]
    assert owner.post(f"/v1/updates/{uid}/submit").status_code == 200
    r = _prep(owner, "monthly", "2026-07-31", kpis={"revenue": None, "cash": 5})
    assert r.status_code == 409
    assert db.one("SELECT value FROM studio.kpi_values WHERE metric='revenue' AND period_end='2026-07-31'")["value"] == 1000


@needs_db
def test_edit_refuses_empty_summary_and_long_items(ca):
    owner = ca["owner"]
    u = _prep(owner, "monthly", "2026-06-30", kpis={"revenue": 1000}).json()
    r = owner.patch(f"/v1/updates/{u['id']}", json={"summary": "   "})
    assert r.status_code == 422 and "summary" in r.json()["detail"]
    r = owner.patch(f"/v1/updates/{u['id']}", json={"highlights": ["ok", "x" * 501]})
    assert r.status_code == 422 and "highlight 2 is 501 characters" in r.json()["detail"]
    r = owner.patch(f"/v1/updates/{u['id']}", json={"risks": ["y" * 500], "summary": "Fine."})
    assert r.status_code == 200 and r.json()["body"]["risks"] == ["y" * 500]


@needs_db
def test_kpi_cadence_migration_on_an_old_table(ca):
    db, a = ca["db"], ca["a"]
    # the table as it was before the cadence column
    db.exec("DROP INDEX studio.kpi_values_cadence_uidx")
    db.exec("ALTER TABLE studio.kpi_values DROP COLUMN cadence")
    db.exec("ALTER TABLE studio.kpi_values ADD CONSTRAINT kpi_values_company_id_metric_period_end_key "
            "UNIQUE (company_id, metric, period_end)")
    for end, m in ((date(2026, 6, 30), "revenue"), (date(2026, 5, 31), "revenue"), (date(2026, 9, 30), "cash")):
        db.exec("INSERT INTO studio.kpi_values (company_id, period_end, metric, value) VALUES (%s,%s,%s,1)",
                (a, end, m))
    _publish(db, a, "quarterly", date(2026, 6, 30), 1)                     # only a quarterly update ends 30 Jun
    _publish(db, a, "quarterly", date(2026, 9, 30), 1)                     # both cadences end 30 Sep
    _publish(db, a, "monthly", date(2026, 9, 30), 1)
    db.apply_schema()
    db.apply_schema()  # idempotent
    got = {(x["period_end"], x["metric"]): x["cadence"] for x in db.all("SELECT * FROM studio.kpi_values")}
    assert got == {(date(2026, 6, 30), "revenue"): "quarterly", (date(2026, 5, 31), "revenue"): "monthly",
                   (date(2026, 9, 30), "cash"): "monthly"}
    assert not db.one("SELECT 1 AS x FROM pg_constraint WHERE conname='kpi_values_company_id_metric_period_end_key'")
    db.exec("INSERT INTO studio.kpi_values (company_id, cadence, period_end, metric, value) "
            "VALUES (%s,'weekly','2026-06-30','revenue',2)", (a,))                 # same day, other cadence: fine


# ================================================================== dividend rules
@needs_db
def test_rule_amounts_whole_cents_and_fixed_not_above_cap(ca):
    owner = ca["owner"]
    url = "/v1/companies/AAA/dividend-policy"
    fixed = {"kind": "fixed", "frequency": "quarterly", "veto_hours": 24}
    r = owner.put(url, json={**fixed, "fixed_maud": 0.001, "max_maud_per_round": 100})
    assert r.status_code == 422 and "at least A$0.01" in r.json()["detail"]
    r = owner.put(url, json={**fixed, "fixed_maud": 5, "max_maud_per_round": 10.005})
    assert r.status_code == 422 and "2 decimals" in r.json()["detail"]
    r = owner.put(url, json={**fixed, "fixed_maud": 50, "max_maud_per_round": 20})
    assert r.status_code == 422 and "cannot be more than" in r.json()["detail"]
    assert owner.put(url, json={**POLICY, "ratio_pct": 101}).status_code == 422
    assert owner.put(url, json={**POLICY, "veto_hours": 169}).status_code == 422
    assert owner.put(url, json={**POLICY, "max_maud_per_round": 0.004}).status_code == 422
    assert owner.put(url, json={**fixed, "fixed_maud": 12.5, "max_maud_per_round": 12.5}).status_code == 200


@needs_db
def test_skipped_notes_and_announced_list(ca):
    db, owner = ca["db"], ca["owner"]
    _active_policy(ca, ratio_pct=1)
    auto = _auto(ca)
    tiny = _publish(db, ca["a"], "quarterly", date(2026, 3, 31), 0.5)      # 1% of A$0.50 -> A$0.005 -> 0
    nobody = _publish(db, ca["a"], "quarterly", date(2025, 12, 31), 100_000)  # no shareholders on chain yet
    loss = _publish(db, ca["a"], "quarterly", date(2025, 9, 30), -5)
    auto.declare()
    notes = {r["update_id"]: r["note"] for r in db.all("SELECT update_id, note FROM studio.dividends")}
    assert "rounds to A$0.00" in notes[tiny]
    assert notes[nobody] == "no shareholders to pay"
    assert notes[loss] == "no profit this period"
    _holders(ca)
    q = _publish(db, ca["a"], "quarterly", date(2026, 6, 30), 100_000)
    auto.declare()
    v = owner.get("/v1/companies/AAA/dividend-policy").json()
    did = db.one("SELECT id FROM studio.dividends WHERE update_id=%s", (q,))["id"]
    assert [x["id"] for x in v["announced"]] == [did] and v["announced"][0]["total_maud"] == 1000
    # pausing keeps the announced payment (the page says so); cancelling it uses the veto
    v = owner.post("/v1/companies/AAA/dividend-policy/pause").json()
    assert [x["id"] for x in v["announced"]] == [did]
    v = owner.post(f"/v1/companies/AAA/dividends/{did}/veto", json={"reason": "rule paused"}).json()
    assert v["announced"] == []


@needs_db
def test_manual_dividend_decimals(ca):
    owner = ca["owner"]
    _holders(ca)
    r = owner.post("/v1/companies/AAA/dividends", json={"total_maud": 1.0000001})
    assert r.status_code == 422 and "6 decimals" in r.json()["detail"]
    r = owner.post("/v1/companies/AAA/dividends", json={"total_maud": 10.01})
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["total_maud"] + j["remainder_units"] / M == 10.01


# ================================================================== share offering
@needs_db
def test_holder_cap_read_from_the_token(ca):
    _setup(ca)
    db, chain = ca["db"], ca["chain"]
    chain.caps[TOKEN] = 4                                   # the token allows 4; 2 hold shares today
    db.exec("INSERT INTO studio.mints (company_id, to_wallet, holder_name, shares, status, requested_by) "
            "VALUES (%s,%s,'Later',5,'pending','x')", (ca["a"], INV[5]))   # waiting mint to a new wallet: 1 slot
    oid = _open(ca, min_raise_aud=0)
    url = f"/v1/offerings/{oid}/reservations"
    demo, i0 = _demo(ca), _investor(ca, 0)
    assert demo.post(url, json={"shares": 10, "risk_ack": True}).status_code == 201       # 2 + 1 pending + 1 = 4
    r = i0.post(url, json={"shares": 10, "risk_ack": True})
    assert r.status_code == 409 and "at most 4" in r.json()["detail"]
    assert ca["out"].post(url, json={"shares": 10, "risk_ack": True}).status_code == 201  # already holds
    # the waiting mint is rejected: a slot frees up
    db.exec("UPDATE studio.mints SET status='rejected' WHERE offering_id IS NULL")
    assert i0.post(url, json={"shares": 10, "risk_ack": True}).status_code == 201
    # the register cannot be read: refuse rather than guess
    chain.fail = True
    r = _investor(ca, 1).post(url, json={"shares": 10, "risk_ack": True})
    assert r.status_code == 503
    chain.fail = False
    # the admin queue shows the chain numbers next to Settle
    ca["admin"].post(f"/v1/admin/offerings/{oid}/close")
    item = ca["admin"].get("/v1/admin/approvals").json()["offerings"][0]
    assert item["register"] == {"count": 2, "cap": 4, "new": 2, "other_pending": 0, "after": 4, "fits": True}
    # someone else became a holder meanwhile (e.g. a transfer): settling would pass the cap -> refused before any mint
    chain.balances_by_token[TOKEN][INV[7].lower()] = 1
    r = ca["admin"].post(f"/v1/admin/offerings/{oid}/settle")
    assert r.status_code == 409 and "at most 4" in r.json()["detail"] and "3 now on BlockID Chain" in r.json()["detail"]
    assert db.one("SELECT count(*) AS n FROM studio.mints WHERE offering_id=%s", (oid,))["n"] == 0
    assert db.one("SELECT status FROM studio.offerings WHERE id=%s", (oid,))["status"] == "awaiting_settlement"
    assert ca["admin"].get("/v1/admin/approvals").json()["offerings"][0]["register"]["fits"] is False


@needs_db
def test_release_after_a_partial_settlement(ca):
    _setup(ca)
    db, admin = ca["db"], ca["admin"]
    oid = _open(ca, min_raise_aud=0)
    demo, i0 = _demo(ca), _investor(ca, 0)
    for c in (demo, i0):
        assert c.post(f"/v1/offerings/{oid}/reservations", json={"shares": 100, "risk_ack": True}).status_code == 201
    admin.post(f"/v1/admin/offerings/{oid}/close")
    assert admin.post(f"/v1/admin/offerings/{oid}/settle").status_code == 202
    # the issuer job stopped half-way: demo minted, i0 failed (e.g. the token refused it)
    db.exec("UPDATE studio.mints SET status='minted', tx_hash='0xabc' WHERE offering_id=%s AND lower(to_wallet)=%s",
            (oid, "0x" + "d3" * 20))
    db.exec("UPDATE studio.mints SET status='minting' WHERE offering_id=%s AND lower(to_wallet)=%s",
            (oid, INV[0].lower()))
    db.exec("UPDATE studio.offerings SET status='failed', error='ShareholderCapReached' WHERE id=%s", (oid,))
    r = admin.post(f"/v1/admin/offerings/{oid}/release")
    assert r.status_code == 409 and "right now" in r.json()["detail"]        # a mint is still running
    db.exec("UPDATE studio.mints SET status='failed' WHERE status='minting'")
    r = admin.post(f"/v1/admin/offerings/{oid}/release", json={"reason": "cap reached"})
    assert r.status_code == 200 and r.json() == {"id": oid, "status": "settled", "released": 1, "allocated": 1}
    res = {x["wallet"].lower(): x["status"] for x in db.all("SELECT * FROM studio.reservations WHERE offering_id=%s",
                                                            (oid,))}
    assert res == {"0x" + "d3" * 20: "allocated", INV[0].lower(): "released"}
    assert {m["status"] for m in db.all("SELECT status FROM studio.mints WHERE offering_id=%s", (oid,))} == \
        {"minted", "rejected"}
    ev = db.one("SELECT data FROM studio.events WHERE kind='offering_settled'")["data"]
    assert ev["partial"] is True and ev["shares"] == 100 and ev["released"] == 1
    assert ("/reanchor", {"company_id": ca["a"]}) in ca["calls"]
    assert admin.post(f"/v1/admin/offerings/{oid}/settle").status_code == 409


@needs_db
def test_offering_terms_and_reservation_minimums(ca):
    _setup(ca)
    owner, db = ca["owner"], ca["db"]
    body = {**TERMS, "closes_at": _closes()}
    r = owner.put("/v1/companies/AAA/offering", json={**body, "max_holders": 1})
    assert r.status_code == 422 and "already has 2 shareholders" in r.json()["detail"]
    r = owner.put("/v1/companies/AAA/offering", json={**body, "max_holders": 501})
    assert r.status_code == 422 and "at most 500" in r.json()["detail"]
    v = owner.get("/v1/companies/AAA/offering").json()["defaults"]
    assert v["holders"] == 2 and v["max_holders"] == 500 and v["max_days_open"] == 180
    # concurrent first saves: one offering, the others 409 (never 500)
    clients = [ca["client"]() for _ in range(5)]
    from test_company_admins import OWNER_KEY
    from test_studio import siwe_login
    for c in clients:
        siwe_login(c, OWNER_KEY)
    codes: list[int] = []
    ts = [threading.Thread(target=lambda c=c: codes.append(
        c.put("/v1/companies/AAA/offering", json={**body, "max_holders": 2}).status_code)) for c in clients]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert set(codes) <= {200, 409} and 200 in codes
    assert db.one("SELECT count(*) AS n FROM studio.offerings")["n"] == 1
    db.exec("DELETE FROM studio.offerings")
    # a tiny price: each reservation must be worth at least A$0.01
    oid = _open(ca, price_aud=0.001, min_raise_aud=0)
    demo = _demo(ca)
    r = demo.post(f"/v1/offerings/{oid}/reservations", json={"shares": 4, "risk_ack": True})
    assert r.status_code == 422 and "at least A$0.01" in r.json()["detail"] and "5 shares" in r.json()["detail"]
    r = demo.post(f"/v1/offerings/{oid}/reservations", json={"shares": 5, "risk_ack": True})
    assert r.status_code == 201 and r.json()["reservation"]["amount_aud"] == 0.01
