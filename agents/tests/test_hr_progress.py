"""HR v2 live progress (docs/PLAN-HR-V2.md §1, §3; contract in studio/hr.py): feed / counters / pct / heartbeat,
per-person partial results, model + search fallbacks in the feed, stalled -> re-queue -> fail, people suggestions
from the business website, and the live team summary. Offline fakes; the DB tests use TEST_DATABASE_URL."""
import threading
import time

import httpx
import pytest
from test_hr_api import JANE, TOM, hr_runner, login
from test_people import JANE as PJANE
from test_people import TEAM as PTEAM
from test_people import TOM as PTOM
from test_people import deps_for
from test_studio import USER_KEY, needs_db, studio_env  # noqa: F401 (fixture)

from blockid_agents.agents import people as pa
from blockid_agents.agents.site_intake import people_from_text, person_kind
from blockid_agents.fakes import FAKE_PEOPLE_PAGES, FakePeopleSearch, fake_people_llm
from blockid_agents.llm import FallbackLLM, LLMError, primary_provider, provider_label, reset_listener, set_listener
from blockid_agents.studio import hr_store
from blockid_agents.studio.hr_store import HrProgress, HrStore, Superseded, progress_view, summary
from blockid_agents.tools.search import SearchChain

OTHER = "0x" + "c3" * 32


class Recorder(pa.Tracker):
    def __init__(self):
        self.feed, self.people, self.phases, self.counts, self.plans = [], {}, [], {}, []

    def plan(self, people, *, fetches, searches, team):
        self.plans.append((len(people), fetches, searches, team))

    def phase(self, phase):
        self.phases.append(phase)

    def note(self, msg, *, level="info", person=None, source=None):
        self.feed.append((level, msg))

    def count(self, **inc):
        for k, v in inc.items():
            self.counts[k] = self.counts.get(k, 0) + v

    def person(self, pid, status, *, facts=None, score=None, fit=None):
        self.people.setdefault(pid, []).append((status, len(facts or []), score, fit))

    def llm_event(self, event, person=None):
        self.feed.append(("event", event.get("type")))


class Down:
    def complete_json(self, tier, system, user, schema):
        raise LLMError("429 overloaded")


class DownSearch:
    name = "brave"
    available = True

    def search(self, query, count=8):
        raise httpx.ConnectError("brave down")


# ================================================================== offline
def test_provider_labels_and_primary():
    assert provider_label("claude-cli") == "Claude" and provider_label("claude-bridge") == "Claude"
    assert provider_label("sambanova:DeepSeek-V3.1") == "DeepSeek" and provider_label("deepinfra:Qwen/Qwen3") == "Qwen"
    assert provider_label("") == "the model"
    chain = FallbackLLM([("claude-cli", Down()), ("sambanova:DeepSeek-V3.1", fake_people_llm())])
    assert primary_provider(chain) == "claude-cli"


def test_fallback_events_reach_the_listener():
    seen = []
    tok = set_listener(seen.append)
    try:
        chain = FallbackLLM([("claude-cli", Down()), ("sambanova:DeepSeek-V3.1", fake_people_llm())])
        chain.complete_json("cloud", "s", "PERSON: Tom Lee — role", pa.PersonAnalysis)
        with pytest.raises(Exception):
            SearchChain([("brave", DownSearch())]).search("q")
    finally:
        reset_listener(tok)
    assert seen[0] == {"type": "llm_fallback", "failed": "claude-cli", "next": "sambanova:DeepSeek-V3.1",
                       "error": seen[0]["error"]} and "overloaded" in seen[0]["error"]
    assert seen[1] == {"type": "llm_answered", "provider": "sambanova:DeepSeek-V3.1"}
    assert seen[2]["type"] == "search_fallback" and seen[2]["failed"] == "brave" and seen[2]["next"] is None
    # no listener -> nothing happens
    FallbackLLM([("x", Down()), ("y", fake_people_llm())]).complete_json("cloud", "s", "PERSON: Tom Lee",
                                                                        pa.PersonAnalysis)


def test_analyse_reports_every_step_to_the_tracker(tmp_path):
    llm = FallbackLLM([("claude-cli", Down()), ("sambanova:DeepSeek-V3.1", fake_people_llm())])
    deps = deps_for(tmp_path, llm=llm,
                    search=None)
    deps.agent_search["people_analyst"] = SearchChain([("brave", DownSearch()), ("claude", FakePeopleSearch())])
    rec = Recorder()
    res = pa.analyse(PTEAM, [PJANE, PTOM], deps, tracker=rec)
    msgs = [m for _, m in rec.feed]
    joined = "\n".join(msgs)
    assert rec.plans == [(2, 1, res["counters"]["searches"], True)]  # 1 readable link (LinkedIn is not)
    assert "Skipped linkedin.com" in joined and "Read agritrace.example" in joined
    assert any(m.startswith("Search 1/") and "result" in m for m in msgs)
    assert "Claude is reading" in joined and "Claude busy → using DeepSeek" not in joined  # tracker renders it
    assert ("event", "llm_fallback") in rec.feed and ("event", "search_fallback") in rec.feed
    assert "DeepSeek answered in" in joined
    assert "Checked the facts about Jane Nguyen: 1 verified fact" in joined
    assert any(m.startswith("Scored Jane Nguyen: ") and "fit" in m for m in msgs)
    assert msgs[-1].startswith("Scored the team:")
    assert rec.phases[:2] == ["reading", "searching"] and "extracting" in rec.phases and rec.phases[-1] == "scoring"
    # partial results: each person reported done with their verified facts and scores, in order
    jane = rec.people[1][-1]
    assert jane[0] == "done" and jane[1] == len(res["people"][0]["facts"]) and jane[2] == res["people"][0]["score"]
    assert jane[3] == res["people"][0]["fit"]["score"]
    assert rec.counts["people_done"] == 2 and rec.counts["searches"] == res["counters"]["searches"]
    assert rec.counts["facts_verified"] == res["counters"]["facts_verified"]
    assert rec.counts["pages_read"] >= 1


def test_people_from_team_page_text():
    got = people_from_text(FAKE_PEOPLE_PAGES["https://agritrace.example/team"], ("AgriTrace",))
    assert got == [{"full_name": "Jane Nguyen", "role": "CEO & co-founder"}, {"full_name": "Tom Lee", "role": "CTO"}]
    got = people_from_text("Meet the team. Maya Chen — CEO & Co-founder. Tom Nguyen, CTO. Priya Shah | Head of Sales. "
                           "Board advisor: Liam O'Brien. Our CEO Summit 2024 was great. Do Van Long, Founder and CEO. "
                           "Email maya@x.io")
    assert [p["full_name"] for p in got] == ["Maya Chen", "Tom Nguyen", "Priya Shah", "Liam O'Brien", "Do Van Long"]
    assert [person_kind(p["role"]) for p in got] == ["founder", "executive", "executive", "advisor", "founder"]
    assert people_from_text("") == [] and people_from_text("Our CEO and CTO team") == []


# ================================================================== Postgres
class Slow:
    """The fake People Analyst model, slow enough for heartbeats and mid-run snapshots."""

    def __init__(self, delay: float):
        self.inner, self.delay = fake_people_llm(), delay

    def complete_json(self, tier, system, user, schema):
        time.sleep(self.delay)
        return self.inner.complete_json(tier, system, user, schema)


def make_team(env, people=(JANE, TOM)) -> str:
    u = login(env, USER_KEY)
    r = u.post("/v1/hr/teams", json={"name": "AgriTrace Pty Ltd", "website": "https://agritrace.example",
                                     "people": list(people), "consent": True, "run": True})
    assert r.status_code == 200, r.text
    return r.json()["id"]


@needs_db
def test_live_progress_feed_pct_heartbeat_and_partial_results(studio_env):
    env = studio_env
    db, u = env["db"], login(env, USER_KEY)
    tid = make_team(env)
    q = u.get(f"/v1/hr/teams/{tid}").json()["progress"]
    assert q["phase"] == "queued" and q["pct"] == 0 and q["eta_s"] > 0 and q["started_at"] is None
    assert q["counters"] == {"pages_read": 0, "searches": 0, "facts_verified": 0, "facts_unconfirmed": 0,
                             "people_done": 0, "people_total": 2}
    assert [(p["name"], p["status"]) for p in q["partial"]["people"]] == [("Jane Nguyen", "waiting"),
                                                                          ("Tom Lee", "waiting")]
    assert q["feed"][-1]["msg"].startswith("Queued")

    runner = hr_runner(env)
    runner.heartbeat_s = 0.2
    runner.deps.agent_llm["people_analyst"] = Slow(1.2)
    snaps: list[dict] = []
    stop = threading.Event()

    def poll():
        while not stop.is_set():
            row = db.one("SELECT * FROM studio.hr_teams WHERE id=%s", (tid,))
            snaps.append(row)
            time.sleep(0.05)

    th = threading.Thread(target=poll, daemon=True)
    th.start()
    try:
        assert runner.drain() == 1
    finally:
        stop.set()
        th.join()
    running = [s for s in snaps if s["status"] == "running" and s["progress"]]
    assert running, "no snapshot while running"
    # pct monotonic, 0..100
    pcts = [s["progress"]["pct"] for s in running]
    assert pcts == sorted(pcts) and 0 <= pcts[0] and pcts[-1] <= 100
    # heartbeat while one long model call runs: several distinct heartbeats with the same current step
    in_call = [s for s in running if s["progress"]["current"]["step"] == "Reading the sources"]
    assert len({s["heartbeat_at"] for s in in_call}) >= 3
    gaps = [(b["heartbeat_at"] - a["heartbeat_at"]).total_seconds() for a, b in zip(running, running[1:])]
    assert max(gaps) < 10
    # partial results: Jane done (facts + score) while the report is still running
    mid = next(s for s in running if s["progress"]["counters"]["people_done"] == 1)
    pj = next(p for p in mid["progress"]["partial"]["people"] if p["name"] == "Jane Nguyen")
    assert pj["status"] == "done" and pj["facts"] and pj["score"] is not None and pj["fit"] is not None
    assert pj["grade"] in "ABCDE" and "quote" in pj["facts"][0]
    assert mid["result"] is None
    pv = progress_view(mid)
    assert pv["phase"] in ("extracting", "scoring") and pv["eta_s"] >= 1
    sm = summary(mid, "https://hr.blockid.au")  # live summary mid-run: ids, statuses, partial numbers, no facts
    assert sm["progress"]["phase"] == pv["phase"] and sm["score"] is None
    assert [(p["full_name"], p["status"]) for p in sm["people"]][0] == ("Jane Nguyen", "done")
    assert sm["people"][0]["fit"] == pj["fit"] and "facts" not in sm["people"][0]

    t = u.get(f"/v1/hr/teams/{tid}").json()
    p = t["progress"]
    assert t["status"] == "done" and p["phase"] == "done" and p["pct"] == 100 and p["eta_s"] == 0
    assert p["counters"]["people_done"] == 2 and p["counters"]["searches"] == t["result"]["counters"]["searches"]
    assert p["counters"]["facts_verified"] == t["result"]["counters"]["facts_verified"]
    assert p["counters"]["pages_read"] >= 1 and len(p["feed"]) <= 60
    msgs = [f["msg"] for f in p["feed"]]
    assert any(m.startswith("Read agritrace.example") for m in msgs)
    assert any(m.startswith("Search 1/") for m in msgs)
    assert any(" is reading " in m and "Jane Nguyen" in m for m in msgs)
    assert any(m.startswith("Checked the facts about Tom Lee") for m in msgs)
    assert msgs[-1].startswith("Report written — team score")
    assert all(f["level"] in ("info", "found", "warn") and f["at"] for f in p["feed"])
    assert {x["status"] for x in p["partial"]["people"]} == {"done"}
    # step timings stored -> the next run's ETA uses them
    kinds = {r["kind"] for r in db.all("SELECT DISTINCT kind FROM studio.hr_step_timings")}
    assert {"fetch", "search", "person_model", "team_model"} <= kinds
    med = hr_store.step_medians(db)
    assert med["person_model"] == hr_store.DEFAULT_STEP_S["person_model"]  # < 3 samples: default kept
    db.exec("INSERT INTO studio.hr_step_timings(kind, seconds) VALUES ('person_model', 2), ('person_model', 2)")
    assert 1.0 < hr_store.step_medians(db)["person_model"] < 2.5


@needs_db
def test_stalled_run_requeued_once_then_failed(studio_env):
    env = studio_env
    db, u = env["db"], login(env, USER_KEY)
    tid = make_team(env, [JANE])
    store = HrStore(db)
    t = store.claim()
    assert t["id"] == tid and t["attempt"] == 1
    tr = HrProgress(db, tid, t["attempt"], prev=t["progress"])
    tr.note("working")
    fresh = u.get(f"/v1/hr/teams/{tid}").json()["progress"]
    assert fresh["phase"] == "reading" and fresh["feed"][-1]["msg"] == "working"
    assert store.watchdog() == {"requeued": [], "failed": []}  # heartbeat is fresh

    db.exec("UPDATE studio.hr_teams SET heartbeat_at = now() - interval '2 minutes' WHERE id=%s", (tid,))
    p = u.get(f"/v1/hr/teams/{tid}").json()["progress"]
    assert p["phase"] == "stalled" and p["eta_s"] is None and "No progress" in p["current"]["detail"]
    assert u.get(f"/v1/hr/teams/{tid}/summary").json()["progress"]["phase"] == "stalled"

    assert store.watchdog() == {"requeued": [tid], "failed": []}
    t1 = u.get(f"/v1/hr/teams/{tid}").json()
    assert t1["status"] == "queued" and t1["progress"]["phase"] == "queued"
    assert t1["progress"]["feed"][-1]["level"] == "warn" and "restarted" in t1["progress"]["feed"][-1]["msg"]
    assert any(f["msg"] == "working" for f in t1["progress"]["feed"])  # the feed survives the restart
    # the worker that lost the run can no longer write
    with pytest.raises(Superseded):
        tr.note("late")
    assert store.finish(tid, {"people": []}, attempt=1) is False

    t2 = store.claim()
    assert t2["attempt"] == 2
    db.exec("UPDATE studio.hr_teams SET heartbeat_at = now() - interval '2 minutes' WHERE id=%s", (tid,))
    assert store.watchdog() == {"requeued": [], "failed": [tid]}
    t3 = u.get(f"/v1/hr/teams/{tid}").json()
    assert t3["status"] == "failed" and "stopped responding" in t3["error"]
    assert t3["progress"]["phase"] == "failed" and t3["progress"]["feed"][-1]["level"] == "warn"
    assert "stopped responding" in t3["progress"]["feed"][-1]["msg"]
    # a new run by the requester starts clean (requeue budget reset) and completes
    assert u.post(f"/v1/hr/teams/{tid}/run").json()["status"] == "queued"
    assert db.one("SELECT requeues FROM studio.hr_teams WHERE id=%s", (tid,))["requeues"] == 0
    assert hr_runner(env).drain() == 1
    done = u.get(f"/v1/hr/teams/{tid}").json()
    assert done["status"] == "done" and done["progress"]["pct"] == 100


@needs_db
def test_worker_drain_runs_the_watchdog(studio_env):
    env = studio_env
    db = env["db"]
    tid = make_team(env, [TOM])
    HrStore(db).claim()
    db.exec("UPDATE studio.hr_teams SET heartbeat_at = now() - interval '5 minutes' WHERE id=%s", (tid,))
    assert hr_runner(env).drain() == 1  # re-queued by the watchdog, then run to completion
    row = db.one("SELECT status, requeues FROM studio.hr_teams WHERE id=%s", (tid,))
    assert row == {"status": "done", "requeues": 1}
    # the API loop does the same job
    w = hr_store.HrWatchdog(db)
    assert w.tick() == {"requeued": [], "failed": []}


@needs_db
def test_suggest_people_from_the_business_website(studio_env):
    env = studio_env
    u, o = login(env, USER_KEY), login(env, OTHER)
    anon = env["client"]()
    ctx = u.app.state.studio
    ctx.evidence = env["runner"].deps.evidence
    fetched: list[str] = []

    def fetch(url):
        fetched.append(url)
        if url == "https://agritrace.example/team":
            return FAKE_PEOPLE_PAGES[url]
        raise httpx.ConnectError("404")

    ctx.page_fetcher = fetch
    assert anon.get("/v1/hr/suggest-people", params={"website": "https://agritrace.example"}).status_code == 401
    assert u.get("/v1/hr/suggest-people").status_code == 422
    assert u.get("/v1/hr/suggest-people", params={"website": "http://127.0.0.1"}).status_code == 422
    assert u.get("/v1/hr/suggest-people", params={"valuation_id": "v_nope"}).status_code == 404

    r = u.post("/v1/studio/valuations", json={"url": "agritrace.example"})
    vid = r.json()["id"]
    assert env["runner"].drain() == 1
    got = u.get("/v1/hr/suggest-people", params={"valuation_id": vid}).json()
    assert got["source"] == "site_intake" and got["website"].startswith("https://agritrace.example")
    assert [(p["full_name"], p["role"], p["kind"]) for p in got["people"]][:2] == [
        ("Jane Nguyen", "CEO", "executive"), ("Tom Lee", "CTO", "executive")]
    assert all(p["source_url"].startswith("https://agritrace.example") for p in got["people"])
    assert fetched == []  # no web access: the pages site intake already read
    assert o.get("/v1/hr/suggest-people", params={"valuation_id": vid}).status_code == 403

    got = u.get("/v1/hr/suggest-people", params={"website": "https://agritrace.example"}).json()
    assert fetched == ["https://agritrace.example/team"]  # exactly one fetch
    assert got == {"website": "https://agritrace.example", "source": "fetched", "people": [
        {"full_name": "Jane Nguyen", "role": "CEO & co-founder", "kind": "founder",
         "source_url": "https://agritrace.example/team"},
        {"full_name": "Tom Lee", "role": "CTO", "kind": "executive", "source_url": "https://agritrace.example/team"}]}
    fetched.clear()
    got = u.get("/v1/hr/suggest-people", params={"website": "https://nothing.example"}).json()
    assert got == {"website": "https://nothing.example", "source": "none", "people": []}
    assert fetched == ["https://nothing.example/team"]
