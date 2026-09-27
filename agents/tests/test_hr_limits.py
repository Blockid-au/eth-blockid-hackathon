"""HR limitations (docs/PLAN-AI-GATEWAY.md §2; contract in studio/hr.py "Limitations"): user-facing error codes +
plain sentences (internal detail for platform admins only), the budgeted model fallback of people suggestions and
the percentile ETA model. Offline fakes; the DB tests use TEST_DATABASE_URL."""
import httpx
import pytest
from test_hr_api import JANE, TOM, hr_runner, login
from test_studio import ADMIN_KEY, USER_KEY, needs_db, studio_env  # noqa: F401 (fixture)

from blockid_agents.agents import people as pa
from blockid_agents.agents.site_intake import SuggestedPeople, SuggestedPerson, suggest_people_with_model
from blockid_agents.llm import FakeLLM, LLMError
from blockid_agents.studio import hr as hr_api
from blockid_agents.studio import hr_store
from blockid_agents.studio.hr_store import ERROR_TEXT, classify_error, classify_text, public_error
from blockid_agents.tools.search import SearchChain, SearchUnavailable

OTHER = "0x" + "c3" * 32
TEAM_TEXT = ("Our people. Jane Nguyen leads growth and partnerships across Victoria. Tom Lee builds the traceability "
             "platform and the mobile app.")


class Down:
    def complete_json(self, tier, system, user, schema):
        raise LLMError("all LLM backends failed for PersonAnalysis: claude-bridge: 429 | sambanova: overloaded")


class EmptySearch:
    name = "claude"
    available = True

    def search(self, query, count=8):
        return []


class DownSearch:
    name = "brave"
    available = True

    def search(self, query, count=8):
        raise httpx.ConnectError("brave down")


def people_llm(names, page=""):
    return FakeLLM({SuggestedPeople: lambda system, user: SuggestedPeople(
        people=[SuggestedPerson(full_name=n, role=r, page=page) for n, r in names])})


# ================================================================== offline: error mapping
def test_exceptions_map_to_codes_and_plain_sentences():
    assert classify_error(LLMError("claude bridge HTTP 429")) == "models_busy"
    assert classify_error(pa.NoPublicInfo("3 searches, 0 results")) == "no_public_info"
    assert classify_error(pa.SourcesUnreachable("all failed")) == "sources_unreachable"
    assert classify_error(SearchUnavailable("brave: quota")) == "sources_unreachable"
    assert classify_error(httpx.ConnectError("dns")) == "sources_unreachable"
    assert classify_error(httpx.ReadTimeout("slow")) == "timeout"
    assert classify_error(TimeoutError()) == "timeout"
    assert classify_error(KeyError("people")) == "internal"
    assert classify_error(ValueError("deadline exceeded")) == "timeout"

    class QuotaExceeded(RuntimeError):
        pass

    assert classify_error(QuotaExceeded("x")) == "models_busy"
    # rows from before codes existed: the stored internal text is classified on read
    assert classify_text("LLMError: all LLM backends failed for PersonAnalysis: ...") == "models_busy"
    assert classify_text("ReadTimeout: timed out") == "timeout"
    assert classify_text("The review stopped responding (no progress for 90 s) ...") == "stalled"
    assert classify_text("no people to analyse") == "no_people"
    assert classify_text("KeyError: 'x'") == "internal"
    for code, text in ERROR_TEXT.items():  # plain sentences: no exception names, no internals
        assert text.endswith(".") and "Error" not in text and ":" not in text and len(text) < 200, code
    assert public_error({"status": "failed", "error": "LLMError: boom"}) == ("models_busy", ERROR_TEXT["models_busy"])
    assert public_error({"status": "failed", "error": ERROR_TEXT["timeout"], "error_code": "timeout"}) == (
        "timeout", ERROR_TEXT["timeout"])
    assert public_error({"status": "done", "error": None}) == (None, None)
    assert hr_store.error_detail({"error": "LLMError: boom"}) == "LLMError: boom"
    assert hr_store.error_detail({"error": "plain", "error_code": "timeout", "error_detail": "X: y"}) == "X: y"


def test_nothing_to_analyse_stops_before_any_model_call():
    nobody = [{"id": 1, "full_name": "Ann Example", "role": "CEO"}]
    with pytest.raises(pa.NoPublicInfo):
        pa.check_evidence(nobody, {1: []}, [{"error": "claude: no results; brave: no results"}], 0)
    with pytest.raises(pa.SourcesUnreachable):
        pa.check_evidence(nobody, {1: []}, [{"error": "brave: ConnectError"}, {"error": "claude: 503"}], 0)
    pa.check_evidence(nobody, {1: []}, [], 0)  # no search configured: links / bios only, unchanged behaviour
    pa.check_evidence([{**nobody[0], "bio": "Ex-Atlassian PM"}], {1: []}, [{"error": "x: no results"}], 0)
    pa.check_evidence(nobody, {1: [("ev", "text")]}, [{"results": 3}], 0)


# ================================================================== offline: model suggestions
def test_model_suggestions_only_keep_names_on_the_page():
    llm = people_llm([("Jane Nguyen", "Growth"), ("Tom Lee", ""), ("Ghost Person", "CEO"), ("AgriTrace Team", ""),
                      ("Jane Nguyen", "dup")], page="https://agritrace.example/about")
    got = suggest_people_with_model(llm, [("https://agritrace.example/", "Welcome"),
                                          ("https://agritrace.example/about", TEAM_TEXT + " jane@agritrace.au")],
                                    ("AgriTrace",))
    assert got == [{"full_name": "Jane Nguyen", "role": "Growth", "source_url": "https://agritrace.example/about"},
                   {"full_name": "Tom Lee", "role": "", "source_url": "https://agritrace.example/about"}]
    assert llm.calls == [("cloud", "SuggestedPeople")]  # exactly one call
    assert suggest_people_with_model(llm, [("https://x.example/team", "  ")]) == [] and len(llm.calls) == 1

    seen = {}

    class ProfileLLM:
        def complete_json(self, tier, system, user, schema, profile=None):
            seen["profile"] = profile
            assert "jane@" not in user  # contacts stripped before the model sees the text
            return SuggestedPeople(people=[])

    suggest_people_with_model(ProfileLLM(), [("https://agritrace.example/team", TEAM_TEXT + " jane@agritrace.au")])
    assert seen == {"profile": "extract_json"}


# ================================================================== offline: ETA percentiles
def test_eta_estimate_range_scales_with_people():
    st = hr_store.default_stats()
    lo1, mid1, hi1 = hr_store.estimate_range(st, fetches=0, searches=3, people=1, team=True)
    lo3, mid3, hi3 = hr_store.estimate_range(st, fetches=0, searches=9, people=3, team=True)
    assert lo1 < mid1 < hi1 and lo3 < mid3 < hi3 and mid3 > 2.5 * mid1
    d = hr_store.DEFAULT_STEP_S
    assert mid3 == pytest.approx(9 * d["search"] + 3 * d["person_model"] + d["team_model"])  # defaults = 3 people
    assert hr_store._pct([1, 2, 3, 4], 0.5) == 2.5 and hr_store._pct([5], 0.25) == 5


# ================================================================== DB
@needs_db
def test_failed_run_shows_code_and_plain_sentence_detail_for_admins_only(studio_env):
    env = studio_env
    db, u, a = env["db"], login(env, USER_KEY), login(env, ADMIN_KEY)
    tid = u.post("/v1/hr/teams", json={"name": "AgriTrace Pty Ltd", "website": "https://agritrace.example",
                                       "people": [JANE, TOM], "consent": True, "run": True}).json()["id"]
    runner = hr_runner(env)
    runner.deps.agent_llm["people_analyst"] = Down()
    assert runner.drain() == 1
    t = u.get(f"/v1/hr/teams/{tid}").json()
    assert t["status"] == "failed" and t["error_code"] == "models_busy" and t["error"] == ERROR_TEXT["models_busy"]
    assert "error_detail" not in t and "LLMError" not in str(t)  # nothing internal reaches the requester
    assert t["progress"]["phase"] == "failed" and t["progress"]["eta_range_s"] is None
    assert t["progress"]["current"]["detail"] == ERROR_TEXT["models_busy"]
    ta = a.get(f"/v1/hr/teams/{tid}").json()
    assert ta["error"] == ERROR_TEXT["models_busy"] and ta["error_detail"].startswith("LLMError: all LLM backends")
    sm = u.get(f"/v1/hr/teams/{tid}/summary").json()
    assert sm["error"] == ERROR_TEXT["models_busy"] and sm["error_code"] == "models_busy"
    aud = db.one("SELECT * FROM studio.audit WHERE action='hr_run_failed' AND target=%s", (tid,))
    assert aud["detail"]["code"] == "models_busy" and "429" in aud["detail"]["detail"]
    # a re-run clears the error
    assert u.post(f"/v1/hr/teams/{tid}/run").json()["error_code"] is None

    # a row from before error codes: internal text stored in `error` -> plain for users, raw for admins
    db.exec("UPDATE studio.hr_teams SET status='failed', error='ReadTimeout: timed out', error_code=NULL, "
            "error_detail=NULL WHERE id=%s", (tid,))
    t = u.get(f"/v1/hr/teams/{tid}").json()
    assert (t["error_code"], t["error"]) == ("timeout", ERROR_TEXT["timeout"])
    assert a.get(f"/v1/hr/teams/{tid}").json()["error_detail"] == "ReadTimeout: timed out"


@needs_db
def test_no_public_info_and_unreachable_sources(studio_env):
    env = studio_env
    u = login(env, USER_KEY)
    nobody = {"full_name": "Ann Example", "role": "CEO", "kind": "founder"}
    for search, code in ((EmptySearch(), "no_public_info"), (DownSearch(), "sources_unreachable")):
        tid = u.post("/v1/hr/people-reports", json={"person": nobody, "consent": True}).json()["id"]
        runner = hr_runner(env)
        runner.deps.agent_search["people_analyst"] = SearchChain([(search.name, search)])
        llm = runner.deps.agent_llm["people_analyst"]
        before = len(llm.calls)
        assert runner.drain() == 1
        t = u.get(f"/v1/hr/people-reports/{tid}").json()
        assert (t["status"], t["error_code"], t["error"]) == ("failed", code, ERROR_TEXT[code])
        assert len(llm.calls) == before  # stopped before any model call


@needs_db
def test_suggestions_fall_back_to_one_budgeted_model_call(studio_env, monkeypatch):
    env = studio_env
    u, o = login(env, USER_KEY), login(env, OTHER)
    ctx = u.app.state.studio
    fetched: list[str] = []

    def fetch(url):
        fetched.append(url)
        if url == "https://agritrace.example/team":
            return TEAM_TEXT  # names but no "Name — Role" pattern: the parser finds nobody
        raise httpx.ConnectError("404")

    ctx.page_fetcher = fetch
    ctx.suggest_llm = people_llm([("Jane Nguyen", "Growth lead"), ("Invented Person", "CTO")],
                                 page="https://agritrace.example/team")
    monkeypatch.setattr(hr_api, "SUGGEST_MODEL_PER_USER_HOUR", 2)
    # the router (and its limiters) is built per app: rebuild one with the smaller budget
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(hr_api.build_hr_router(ctx))
    app.state.studio = ctx
    c = TestClient(app, base_url="https://testserver", cookies=dict(u.cookies))
    got = c.get("/v1/hr/suggest-people", params={"website": "https://agritrace.example"}).json()
    assert got == {"website": "https://agritrace.example", "source": "model", "people": [
        {"full_name": "Jane Nguyen", "role": "Growth lead", "kind": "employee",
         "source_url": "https://agritrace.example/team", "note": "suggested from agritrace.example/team"}]}
    assert fetched == ["https://agritrace.example/team"] and len(ctx.suggest_llm.calls) == 1  # no extra fetch
    c.get("/v1/hr/suggest-people", params={"website": "https://agritrace.example"})
    third = c.get("/v1/hr/suggest-people", params={"website": "https://agritrace.example"}).json()
    assert third["source"] == "none" and third["people"] == []  # per-user budget spent: no model call
    assert len(ctx.suggest_llm.calls) == 2
    oc = TestClient(app, base_url="https://testserver", cookies=dict(o.cookies))
    assert oc.get("/v1/hr/suggest-people", params={"website": "https://agritrace.example"}).json()["source"] == "model"
    # a model failure is quiet (no suggestions), audited
    ctx.suggest_llm = Down()
    ctx.suggest_llm.calls = []
    assert oc.get("/v1/hr/suggest-people", params={"website": "https://agritrace.example"}).json()["people"] == []
    rows = env["db"].all("SELECT detail FROM studio.audit WHERE action='hr_suggest_model' ORDER BY id")
    assert [r["detail"]["ok"] for r in rows] == [True, True, True, False]


@needs_db
def test_eta_percentiles_defaults_and_range_in_progress(studio_env):
    env = studio_env
    db, u = env["db"], login(env, USER_KEY)
    st = hr_store.step_stats(db)
    assert st == hr_store.default_stats()  # no history: defaults per step kind
    db.exec("INSERT INTO studio.hr_step_timings(kind, seconds) VALUES ('person_model', 10), ('person_model', 20)")
    assert hr_store.step_stats(db)["person_model"] == hr_store.default_stats()["person_model"]  # < 3 samples
    db.exec("INSERT INTO studio.hr_step_timings(kind, seconds) VALUES ('person_model', 30), ('person_model', 40), "
            "('person_model', 50)")
    assert hr_store.step_stats(db)["person_model"] == pytest.approx((20, 30, 40))
    # team_model is timed per person of its run: 30 s for 3 people and 20 s for 2 -> 10 s per person
    db.exec("INSERT INTO studio.hr_step_timings(kind, seconds, people) VALUES ('team_model', 30, 3), "
            "('team_model', 20, 2), ('team_model', 10, 1)")
    assert hr_store.step_stats(db)["team_model"] == pytest.approx((10, 10, 10))
    assert hr_store.step_medians(db)["person_model"] == pytest.approx(30)  # the old median helper still works

    one = u.post("/v1/hr/teams", json={"name": "A One", "people": [TOM], "consent": True, "run": True}).json()
    two = u.post("/v1/hr/teams", json={"name": "A Two", "people": [TOM, {**TOM, "full_name": "Kim Park"}],
                                       "consent": True, "run": True}).json()
    p1, p2 = one["progress"], two["progress"]
    lo1, hi1 = p1["eta_range_s"]
    assert lo1 < p1["eta_s"] < hi1 and p2["eta_s"] > p1["eta_s"] and p2["eta_range_s"][1] > hi1
    sm = u.get(f"/v1/hr/teams/{one['id']}/summary").json()
    assert sm["progress"]["eta_range_s"] == p1["eta_range_s"]

    assert hr_runner(env).drain() == 2
    done = u.get(f"/v1/hr/teams/{one['id']}").json()["progress"]
    assert done["eta_s"] == 0 and done["eta_range_s"] == [0, 0]
    ppl = {r["people"] for r in db.all("SELECT people FROM studio.hr_step_timings WHERE team_id=%s", (two["id"],))}
    assert ppl == {2}
