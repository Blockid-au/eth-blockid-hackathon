"""GET /v1/me/active-jobs (studio/active_jobs.py): the signed-in user's queued / running valuations and HR reports,
plus the ones that finished in the last 30 minutes, with absolute links on the right host. TEST_DATABASE_URL."""
from test_hr_api import JANE, OTHER_KEY, TOM, login
from test_studio import USER, USER_KEY, needs_db, studio_env  # noqa: F401 (fixture)

from blockid_agents.studio.active_jobs import valuation_progress
from blockid_agents.studio.auth import COOKIE
from blockid_agents.studio.db import STEP_KEYS

DEMO = "0x" + "de" * 20


def jobs(c):
    r = c.get("/v1/me/active-jobs")
    assert r.status_code == 200, r.text
    return r.json()["jobs"]


def test_valuation_progress_from_steps():
    steps = [{"key": k, "status": "pending"} for k in STEP_KEYS]
    assert valuation_progress(steps) == ("read_site", 0)
    steps[0]["status"], steps[1]["status"], steps[2]["status"] = "done", "done", "running"
    assert valuation_progress(steps) == ("competitors", 42)
    assert valuation_progress([{"key": k, "status": "done"} for k in STEP_KEYS])[1] == 99  # never 100 until done


@needs_db
def test_active_jobs_lifecycle_and_scope(studio_env):
    env, db = studio_env, studio_env["db"]
    assert env["client"]().get("/v1/me/active-jobs").status_code == 401
    u, o = login(env, USER_KEY), login(env, OTHER_KEY)
    assert jobs(u) == []

    vid = u.post("/v1/studio/valuations", json={"url": "agritrace.example"}).json()["id"]
    j = jobs(u)
    assert len(j) == 1 and j[0]["kind"] == "valuation" and j[0]["id"] == vid
    assert j[0]["status"] == "queued" and j[0]["phase"] == "queued" and j[0]["pct"] == 0 and j[0]["eta_s"] > 0
    assert j[0]["title"] == "agritrace.example" and j[0]["url"] == f"https://eth.blockid.au/v/{vid}/research"
    assert jobs(o) == []  # only the requester's jobs

    db.exec("UPDATE studio.valuations SET status='running' WHERE id=%s", (vid,))
    db.set_step(vid, "read_site", "done")
    db.set_step(vid, "profile", "running")
    j = jobs(u)[0]
    assert j["status"] == "running" and j["phase"] == "profile" and 0 < j["pct"] < 100

    db.exec("UPDATE studio.valuations SET status='waiting_approval', result=%s::jsonb, updated_at=now() WHERE id=%s",
            ('{"profile": {"name": "AgriTrace Pty Ltd"}}', vid))
    j = jobs(u)[0]
    assert j["status"] == "done" and j["raw_status"] == "waiting_approval" and j["pct"] == 100 and j["eta_s"] == 0
    assert j["title"] == "AgriTrace Pty Ltd" and j["url"].endswith(f"/v/{vid}/report") and j["finished_at"]

    db.exec("UPDATE studio.valuations SET updated_at=now() - interval '31 minutes' WHERE id=%s", (vid,))
    assert jobs(u) == []  # finished long ago: gone from the tray

    # HR: a queued team report and a person report (person = hr_person on /p/<id>)
    t = u.post("/v1/hr/teams", json={"name": "AgriTrace", "people": [JANE, TOM], "consent": True, "run": True}).json()
    p = u.post("/v1/hr/people-reports", json={"person": JANE, "consent": True}).json()
    j = {x["id"]: x for x in jobs(u)}
    assert j[t["id"]]["kind"] == "hr_team" and j[t["id"]]["status"] == "queued"
    assert j[t["id"]]["url"] == f"https://hr.blockid.au/r/{t['id']}" and j[t["id"]]["title"] == "AgriTrace"
    assert j[p["id"]]["kind"] == "hr_person" and j[p["id"]]["url"] == f"https://hr.blockid.au/p/{p['id']}"
    assert j[p["id"]]["title"] == "Jane Nguyen"

    db.exec("UPDATE studio.hr_teams SET status='running', started_at=now(), heartbeat_at=now(), "
            "progress='{\"phase\": \"searching\", \"pct\": 40, \"eta_s\": 60}'::jsonb WHERE id=%s", (t["id"],))
    db.exec("UPDATE studio.hr_teams SET status='done', finished_at=now() WHERE id=%s", (p["id"],))
    got = jobs(u)
    assert [x["id"] for x in got] == [t["id"], p["id"]]  # running first, then finished
    assert got[0]["phase"] == "searching" and got[0]["pct"] == 40 and 0 < got[0]["eta_s"] <= 60
    assert got[1]["status"] == "done" and got[1]["pct"] == 100 and got[1]["finished_at"]

    db.exec("UPDATE studio.hr_teams SET status='failed', finished_at=now() - interval '2 hours' WHERE id=%s",
            (p["id"],))
    assert [x["id"] for x in jobs(u)] == [t["id"]]
    assert jobs(o) == []


@needs_db
def test_active_jobs_demo_session_sees_jobs_of_its_address(studio_env):
    env, db = studio_env, studio_env["db"]
    vid = db.create_valuation("https://harbourline.example", DEMO)
    c = env["client"]()
    sid = c.app.state.studio.sessions.create("user", address=DEMO, auth_method="demo")
    c.cookies.set(COOKIE, sid)
    got = jobs(c)
    assert [x["id"] for x in got] == [vid] and got[0]["status"] == "queued"
    assert jobs(login(env, USER_KEY)) == [] and USER.lower() != DEMO
