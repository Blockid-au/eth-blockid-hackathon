"""hr.blockid.au API (studio/hr.py) + worker job (studio/hr_store.py) against a throwaway Postgres
(TEST_DATABASE_URL; skipped when unset): access rules, consent, rate limit, share links, removal, person reports,
valuation-start teams and the founder_quality blend."""
import json

from eth_account import Account
from conftest import v5_on
from test_studio import ADMIN_KEY, USER, USER_KEY, needs_db, siwe_login, studio_env  # noqa: F401 (fixture)

from blockid_agents.audit import AuditLog
from blockid_agents.deps import Deps
from blockid_agents.fakes import FakePeopleSearch, fake_llm, fake_people_fetch, fake_people_llm
from blockid_agents.studio import verify
from blockid_agents.studio.hr_store import HrRunner
from blockid_agents.studio.report_hash import canonical_report, report_view_from_row
from blockid_agents.tools.brave import EvidenceStore
from blockid_agents.tools.search import SearchChain

OTHER_KEY, CADMIN_KEY = "0x" + "c3" * 32, "0x" + "d4" * 32
CADMIN = Account.from_key(CADMIN_KEY).address
JANE = {"full_name": "Jane Nguyen", "role": "CEO", "kind": "founder", "headline": "Agri supply-chain founder",
        "full_time": True, "equity_pct": 60, "urls": ["https://agritrace.example/team"],
        "bio": "Based in Melbourne. MBA, University of Melbourne. enterprise sales. jane@agritrace.au"}
TOM = {"full_name": "Tom Lee", "role": "CTO", "kind": "cofounder"}


def settings_of(env):
    return env["client"]().app.state.studio.settings


def hr_runner(env) -> HrRunner:
    s = settings_of(env)
    from pathlib import Path
    deps = Deps(llm=fake_llm(), audit=AuditLog(Path(s.data_dir) / "hr-audit.jsonl"),
                evidence=EvidenceStore(Path(s.data_dir) / "evidence.sqlite"), settings=s,
                agent_llm={"people_analyst": fake_people_llm()},
                agent_search={"people_analyst": SearchChain([("claude", FakePeopleSearch())])},
                fetcher=fake_people_fetch)
    return HrRunner(deps, env["db"])


def login(env, key):
    c = env["client"]()
    siwe_login(c, key)
    return c


@needs_db
def test_team_report_lifecycle_and_access(studio_env):
    env = studio_env
    u, o, a = login(env, USER_KEY), login(env, OTHER_KEY), login(env, ADMIN_KEY)
    anon = env["client"]()
    body = {"name": "AgriTrace Pty Ltd", "website": "https://agritrace.example", "people": [JANE, TOM]}
    assert u.post("/v1/hr/teams", json={**body, "consent": False}).status_code == 422
    bad = {**body, "consent": True, "people": [{**JANE, "urls": ["http://127.0.0.1/admin"]}]}
    assert u.post("/v1/hr/teams", json=bad).status_code == 422
    assert u.post("/v1/hr/teams", json={**body, "consent": True, "people": [{**JANE, "kind": "boss"}]}
                  ).status_code == 422
    assert anon.post("/v1/hr/teams", json={**body, "consent": True}).status_code == 401
    r = u.post("/v1/hr/teams", json={**body, "consent": True})
    assert r.status_code == 200, r.text
    t = r.json()
    tid = t["id"]
    assert t["status"] == "draft" and t["mode"] == "team" and t["mine"] and t["can_edit"] and t["consent"]
    assert [p["full_name"] for p in t["people"]] == ["Jane Nguyen", "Tom Lee"]
    assert "jane@agritrace.au" not in json.dumps(t)  # founder-typed contact details redacted before storage
    assert t["report_url"].endswith(f"/r/{tid}")

    # readers: requester / admin yes; others, anonymous no
    assert o.get(f"/v1/hr/teams/{tid}").status_code == 403
    assert anon.get(f"/v1/hr/teams/{tid}").status_code == 401
    assert a.get(f"/v1/hr/teams/{tid}").json()["can_edit"] is True
    assert o.post(f"/v1/hr/teams/{tid}/run").status_code == 403

    # run -> worker -> done
    assert u.post(f"/v1/hr/teams/{tid}/run").json()["status"] == "queued"
    assert u.post(f"/v1/hr/teams/{tid}/run").status_code == 409
    assert u.put(f"/v1/hr/teams/{tid}/people", json={"people": [JANE]}).status_code == 409
    assert hr_runner(env).drain() == 1
    t = u.get(f"/v1/hr/teams/{tid}").json()
    assert t["status"] == "done", t["error"]
    res = t["result"]
    assert 0 <= res["team"]["score"] <= 100 and res["team"]["grade"] in "ABCDE"
    assert [s["step"] for s in t["steps"]][0] == "queued" and t["steps"][-1]["step"] == "done"
    assert "team_inputs" not in res and res["counters"]["facts_verified"] >= 2
    assert {c["full_name"] for c in res["people"]} == {"Jane Nguyen", "Tom Lee"}

    # public-safe summary: no facts / quotes / sources
    sm = u.get(f"/v1/hr/teams/{tid}/summary").json()
    assert sm["score"] == res["team"]["score"] and len(sm["strengths"]) <= 3
    assert "quote" not in json.dumps(sm) and "facts" not in sm and "FarmLink" not in json.dumps(sm)
    assert o.get(f"/v1/hr/teams/{tid}/summary").status_code == 403

    # share link: anonymous read with the token only
    tok = u.post(f"/v1/hr/teams/{tid}/share").json()["share_token"]
    assert anon.get(f"/v1/hr/teams/{tid}", params={"share": tok}).json()["share_token"] is None
    assert anon.get(f"/v1/hr/teams/{tid}", params={"share": tok + "x"}).status_code == 401
    assert o.get(f"/v1/hr/teams/{tid}/summary", params={"share": tok}).status_code == 200
    assert u.delete(f"/v1/hr/teams/{tid}/share").json() == {"ok": True}
    assert anon.get(f"/v1/hr/teams/{tid}", params={"share": tok}).status_code == 401

    # company admins of the linked company can read
    db = env["db"]
    cid = db.one("INSERT INTO studio.companies(ticker,name,valuation_aud,total_shares,status) "
                 "VALUES ('AGT','AgriTrace',1000000,1000000,'draft') RETURNING id")["id"]
    db.exec("INSERT INTO studio.company_admins(company_id,address,role,status) VALUES (%s,%s,'manager','active')",
            (cid, CADMIN))
    db.exec("UPDATE studio.hr_teams SET company_id=%s WHERE id=%s", (cid, tid))
    ca = login(env, CADMIN_KEY)
    got = ca.get(f"/v1/hr/teams/{tid}").json()
    assert got["status"] == "done" and got["can_edit"] is False and got["share_token"] is None
    assert ca.delete(f"/v1/hr/people/{got['people'][0]['id']}").status_code == 403

    # demo reports: readable by any signed-in viewer
    object.__setattr__(settings_of(env), "demo_wallet", USER)
    try:
        assert o.get(f"/v1/hr/teams/{tid}").json()["is_demo"] is True
    finally:
        object.__setattr__(settings_of(env), "demo_wallet", "")

    # lists
    assert [x["id"] for x in u.get("/v1/hr/teams", params={"mine": 1}).json()["teams"]] == [tid]
    assert o.get("/v1/hr/teams").json()["teams"] == []
    assert tid in [x["id"] for x in a.get("/v1/hr/teams", params={"mine": 0}).json()["teams"]]

    # removal request: the person, their facts and their stored evidence go; the team score is recomputed
    ev = hr_runner(env).deps.evidence
    tom = next(p for p in t["people"] if p["full_name"] == "Tom Lee")
    assert ev.for_subject(f"hr:{tid}:{tom['id']}")
    assert u.delete(f"/v1/hr/people/{tom['id']}").json() == {"ok": True, "team_id": tid}
    assert ev.for_subject(f"hr:{tid}:{tom['id']}") == []
    t2 = u.get(f"/v1/hr/teams/{tid}").json()
    assert [p["full_name"] for p in t2["people"]] == ["Jane Nguyen"]
    assert [c["full_name"] for c in t2["result"]["people"]] == ["Jane Nguyen"]
    assert "Tom Lee" not in json.dumps(t2["result"]["people"]) and "Tom Lee" not in json.dumps(t2["result"]["sources"])
    assert db.one("SELECT count(*) AS n FROM studio.audit WHERE action='hr_person_removed'")["n"] == 1

    # daily run limit per wallet (admins exempt)
    object.__setattr__(settings_of(env), "hr_runs_per_day", 1)
    try:
        t3 = u.post("/v1/hr/teams", json={**body, "consent": True}).json()
        assert u.post(f"/v1/hr/teams/{t3['id']}/run").status_code == 429
        assert a.post(f"/v1/hr/teams/{t3['id']}/run").json()["status"] == "queued"
    finally:
        object.__setattr__(settings_of(env), "hr_runs_per_day", 5)

    # delete the report
    assert o.delete(f"/v1/hr/teams/{tid}").status_code == 403
    assert u.delete(f"/v1/hr/teams/{tid}").json() == {"ok": True}
    assert u.get(f"/v1/hr/teams/{tid}").status_code == 404


@needs_db
def test_person_report_with_role_and_business_targets(studio_env):
    env = studio_env
    u, o = login(env, USER_KEY), login(env, OTHER_KEY)
    role = {"type": "role", "company": "Acme", "title": "Head of Supply Chain", "description": "Lead ops",
            "requirements": ["agri-food supply chain expertise", "enterprise sales", "regulatory affairs"]}
    r = u.post("/v1/hr/people-reports", json={"person": JANE, "target": role, "consent": True})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["mode"] == "person" and rep["status"] == "queued" and rep["target"]["type"] == "role"
    assert u.put(f"/v1/hr/teams/{rep['id']}/people", json={"people": [JANE, TOM]}).status_code in (409, 422)
    assert hr_runner(env).drain() == 1
    done = u.get(f"/v1/hr/people-reports/{rep['id']}").json()
    card = done["result"]["people"][0]
    assert done["status"] == "done" and done["result"]["team"] is None
    assert card["fit"]["label"] == "role fit" and card["profile"]["completeness_pct"] > 0
    sm = u.get(f"/v1/hr/teams/{rep['id']}/summary").json()
    assert sm["mode"] == "person" and sm["score"] == card["fit"]["score"]
    items = u.get("/v1/hr/teams").json()["teams"]
    assert items[0]["mode"] == "person" and items[0]["target_type"] == "role"
    # a business target must be readable by the caller
    vid = env["db"].create_valuation("https://agritrace.example", USER)
    biz = {"type": "business", "valuation_id": vid}
    assert o.post("/v1/hr/people-reports", json={"person": TOM, "target": biz, "consent": True}).status_code == 403
    assert u.post("/v1/hr/people-reports", json={"person": TOM, "target": {"type": "business"},
                                                  "consent": True}).status_code == 422
    ok = u.post("/v1/hr/people-reports", json={"person": TOM, "target": biz, "consent": True, "run": False}).json()
    assert ok["status"] == "draft" and ok["valuation_id"] == vid
    # a person report never blends into a valuation
    assert u.post(f"/v1/hr/teams/{ok['id']}/apply-to-valuation").status_code == 409


@needs_db
def test_team_at_valuation_start_feeds_founder_quality(studio_env):
    env = studio_env
    u, o, a = login(env, USER_KEY), login(env, OTHER_KEY), login(env, ADMIN_KEY)
    db, runner = env["db"], env["runner"]
    n0 = db.one("SELECT count(*) AS n FROM studio.valuations")["n"]
    no = u.post("/v1/studio/valuations", json={"url": "agritrace.example",
                                               "team": {"people": [JANE, TOM], "consent": False}})
    assert no.status_code == 422 and db.one("SELECT count(*) AS n FROM studio.valuations")["n"] == n0
    r = u.post("/v1/studio/valuations", json={"url": "agritrace.example", "team": {"people": [JANE, TOM],
                                                                                   "consent": True}})
    assert r.status_code == 202, r.text
    vid, tid = r.json()["id"], r.json()["team_id"]
    hr = hr_runner(env)
    assert hr.drain() == 0  # waits for the valuation's research
    assert runner.drain() == 1
    v0 = u.get(f"/v1/studio/valuations/{vid}").json()
    assert v0["status"] == "waiting_approval"
    # HR v2: the valuation's team is live — queued with progress, person ids + hr links before the run
    tm0 = v0["team"]
    assert tm0["id"] == tid and tm0["status"] == "queued" and tm0["applied"] is False and tm0["score"] is None
    assert tm0["progress"]["phase"] == "queued" and tm0["progress"]["pct"] == 0 and tm0["progress"]["eta_s"] > 0
    assert [p["full_name"] for p in tm0["people"]] == ["Jane Nguyen", "Tom Lee"]
    assert all(p["status"] == "waiting" and p["url"].endswith(f"/r/{tid}/p/{p['id']}") for p in tm0["people"])
    assert hr.drain() == 1
    t = u.get(f"/v1/hr/teams/{tid}").json()
    assert t["status"] == "done" and t["name"] == "AgriTrace Pty Ltd" and t["valuation_id"] == vid
    v = u.get(f"/v1/studio/valuations/{vid}").json()
    fq = v["svi"]["dimensions"]["founder_quality"]
    assert fq["basis"] == "team_report" and fq["score"] == t["result"]["team"]["score"]
    assert v["team"]["applied"] is True and v["team"]["id"] == tid and v["team"]["url"].endswith(f"/r/{tid}")
    assert v["team"]["progress"] == {**v["team"]["progress"], "phase": "done", "pct": 100, "eta_s": 0}
    assert v["team"]["applied_at"] and v["team"]["confidence"] in ("high", "medium", "low")
    assert v["team"]["error"] is None and tm0["applied_at"] is None and tm0["confidence"] is None
    ids = {p["id"] for p in t["people"]}
    for p in v["team"]["people"]:  # each founder's fit to THIS business, with a link to their hr page
        assert p["id"] in ids and p["url"].endswith(f"/r/{tid}/p/{p['id']}") and p["status"] == "done"
        assert p["fit"] is not None and p["fit_label"] == "founder–business fit" and len(p["fit_matched"]) <= 3
    assert {k: d["score"] for k, d in v["svi"]["dimensions"].items() if k != "founder_quality"} == \
        {k: d["score"] for k, d in v0["svi"]["dimensions"].items() if k != "founder_quality"}
    assert v["svi"]["weights"]["founder_quality"] == 0.30
    # the stored report still verifies with the public formula
    r1 = verify.recompute(canonical_report(report_view_from_row(db.get_valuation(vid))))
    assert all(r1["matches_report"].values()) and r1["formula_version"] == ("v5" if v5_on() else "v4"), r1
    # summary readable via the valuation rule; strangers cannot
    assert u.get(f"/v1/hr/teams/{tid}/summary").status_code == 200
    assert o.get(f"/v1/hr/teams/{tid}/summary").status_code == 403

    # admin approves without overriding founder_quality -> the team score stays
    v = a.post(f"/v1/studio/valuations/{vid}/decision", json={"approved": True}).json()
    assert v["status"] == "approved"
    assert v["svi"]["dimensions"]["founder_quality"]["basis"] == "team_report"
    assert v["svi"]["dimensions"]["product_strength"]["basis"] == "human"
    assert all(verify.recompute(canonical_report(report_view_from_row(db.get_valuation(vid))))[
        "matches_report"].values())
    assert u.post(f"/v1/hr/teams/{tid}/apply-to-valuation").json()["applied"] is True
    # once a company exists the anchored report is not changed
    db.exec("INSERT INTO studio.companies(ticker,name,valuation_id,valuation_aud,total_shares,status) "
            "VALUES ('AGR','AgriTrace',%s,1000000,1000000,'draft')", (vid,))
    out = u.post(f"/v1/hr/teams/{tid}/apply-to-valuation").json()
    assert out["applied"] is False and "company" in out["reason"]
