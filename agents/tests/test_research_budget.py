"""Research budget, search provider chain (Brave -> Claude bridge), bounded site crawl and the LLM provider chain
(SambaNova / DeepInfra). All offline."""
import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from test_studio import studio_deps  # shared offline fixture

from blockid_agents.agents import competitors, research, site_intake
from blockid_agents.config import get_settings
from blockid_agents.fakes import FAKE_SITE, fake_llm
from blockid_agents.graph import build_site_valuation
from blockid_agents.llm import (
    FakeLLM,
    FallbackLLM,
    LLMError,
    SambaNovaLLM,
    cloud_chain,
    extract_json,
    track_providers,
    untrack_providers,
)
from blockid_agents.schemas import Narrative, StartupProfile
from blockid_agents.studio.db import MemoryProgress
from blockid_agents.tools import search as search_mod
from blockid_agents.tools.brave import BraveSearch, EvidenceStore
from blockid_agents.tools.search import (
    BridgeUnavailable,
    ClaudeBridgeSearch,
    SearchChain,
    SearchUnavailable,
    essential_queries,
)


# ================================================================== fakes
class CountingSearch:
    """A provider that always answers; records every query it receives."""

    def __init__(self, name="claude"):
        self.name, self.queries = name, []

    def search(self, query, count=8, **_):
        self.queries.append(query)
        slug = str(len(self.queries))
        return [{"title": f"Top alternatives: TE-FOOD and OpenSC #{slug}", "url": f"https://news.example.com/r{slug}-{i}",
                 "description": "TE-FOOD and OpenSC compete in food traceability", "query": query}
                for i in range(5)]


def bridge_transport(calls: list, status: int = 200, body: dict | None = None, exc: Exception | None = None):
    def handler(r: httpx.Request) -> httpx.Response:
        calls.append(r)
        if exc is not None:
            raise exc
        return httpx.Response(status, json=body if body is not None else {
            "results": [{"title": "A", "url": "https://a.example/x", "snippet": "about A"},
                        {"title": "insecure", "url": "http://b.example/", "snippet": "dropped"},
                        {"title": "dup", "url": "https://a.example/x", "snippet": "dup"}],
            "cost_usd": 0.03, "model": "haiku"})
    return httpx.MockTransport(handler)


def quota_brave(store, calls):
    def handler(r):
        calls.append(r.url.params.get("q"))
        return httpx.Response(200, json={"type": "search"}, headers={"x-ratelimit-remaining": "1, 0"})
    return BraveSearch("k", store, max_rps=0, transport=httpx.MockTransport(handler))


# ================================================================== budget
def run_graph(deps, vid="vb"):
    from langgraph.checkpoint.memory import InMemorySaver

    prog = MemoryProgress()
    out = build_site_valuation(deps, InMemorySaver(), prog).invoke({"job_id": vid, "url": FAKE_SITE},
                                                                   {"configurable": {"thread_id": vid}})
    return out, prog


def test_valuation_runs_exactly_three_essential_queries(tmp_path):
    """With the pre-v3 budget (3 searches, 2 pages) the three essential queries keep their priority."""
    deps = studio_deps(tmp_path)
    deps.settings = replace(deps.settings, search_max_queries=3, search_fetch_per_query=2)
    prov = CountingSearch()
    deps.search = SearchChain([("claude", prov)])
    fetched: list[str] = []
    deps.fetcher = lambda url: fetched.append(url) or f"Page {url}. TE-FOOD and OpenSC are traceability platforms."
    out, prog = run_graph(deps)
    assert out["__interrupt__"]
    assert len(prov.queries) == 3
    assert prov.queries[0].startswith("AgriTrace competitors alternatives Australia")
    assert "market size growth Australia" in prov.queries[1]
    assert prov.queries[2].startswith("AgriTrace revenue ARR funding valuation 20")
    assert all("@" not in q and "Jane" not in q for q in prov.queries)
    assert len(fetched) == 3 * deps.settings.search_fetch_per_query  # 2 pages per query, never more
    r = prog.results["vb"]
    assert [s["kind"] for s in r["searches"]] == ["competitors", "market", "company"]
    assert r["counters"]["searches"] == 3
    assert "3/3 searches · Claude web search" in prog.steps["vb"]["market"]["detail"]
    assert "1/3 searches · Claude web search" in prog.steps["vb"]["competitors"]["detail"]
    assert r["llm_providers_used"] == ["fake"]


def test_v3_query_plan_is_bounded_and_logged(tmp_path):
    """Default v3 budget: <= 8 searches, <= 3 pages each, every query planned by purpose and logged."""
    deps = studio_deps(tmp_path)
    assert deps.settings.search_max_queries == 8 and deps.settings.search_fetch_per_query == 3
    prov = CountingSearch()
    deps.search = SearchChain([("claude", prov)])
    fetched: list[str] = []
    deps.fetcher = lambda url: fetched.append(url) or f"Page {url}. TE-FOOD and OpenSC are traceability platforms."
    _, prog = run_graph(deps, "v8")
    r = prog.results["v8"]
    kinds = [s["kind"] for s in r["searches"]]
    assert kinds == ["competitors", "market", "company", "valuation", "comps", "comps_named"]  # not listed
    assert all(s["purpose"] and s["query"] for s in r["searches"])
    assert len(prov.queries) == len(kinds) <= 8
    assert len(fetched) <= 3 * len(kinds)
    assert r["valuation_methods"]["methods"] and r["svi"]["triangulation"]["confidence"] in ("high", "medium", "low")
    events = [json.loads(x) for x in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert sum(e["action"] == "tool:web_search" for e in events) == len(kinds)


def test_budget_is_a_hard_cap(tmp_path):
    deps = studio_deps(tmp_path)
    deps.settings = replace(deps.settings, search_max_queries=2)
    prov = CountingSearch()
    deps.search = SearchChain([("claude", prov)])
    _, prog = run_graph(deps, "vc")
    assert len(prov.queries) == 2
    assert "2/2 searches" in prog.steps["vc"]["market"]["detail"]
    # research alone (onboarding path) with a spent budget: no searches at all
    state = {"job_id": "x", "profile": fake_llm().handlers[StartupProfile]("", "").model_dump(),
             "searches": [{"kind": "a"}, {"kind": "b"}]}
    research.run(state, deps)
    assert len(prov.queries) == 2


def test_few_competitors_fill_in_without_extra_searches(tmp_path):
    deps = studio_deps(tmp_path)
    prov = CountingSearch()
    deps.search = SearchChain([("claude", prov)])
    profile = fake_llm().handlers[StartupProfile]("", "")
    out = competitors.discover({"job_id": "v1", "url": FAKE_SITE, "profile": profile.model_dump()}, deps)
    assert len(prov.queries) == 1 and len(out["searches"]) == 1
    names = [c["name"] for c in out["competitors"]]
    assert names[:2] == ["TE-FOOD", "OpenSC"]  # search-found, then the fill-in adds nothing new (dupes/self/off-topic)
    te = out["competitors"][0]
    assert te["raised_aud"] == 15_000_000 and te["url"] == "https://te-food.example/"  # homepage fetched + quote


def test_competitor_homepages_are_bounded(tmp_path, monkeypatch):
    deps = studio_deps(tmp_path)
    deps.settings = replace(deps.settings, competitor_homepages_max=1)
    deps.search = None  # search unavailable -> model suggestions, but only 1 homepage may be fetched
    seen: list = []
    monkeypatch.setattr(competitors, "_fetch_homepages",
                        lambda d, cands, timeout=8: seen.extend(cands) or [(c, None, "x") for c in cands])
    profile = fake_llm().handlers[StartupProfile]("", "")
    out = competitors.discover({"job_id": "v2", "url": FAKE_SITE, "profile": profile.model_dump()}, deps)
    assert len(seen) == 1 and out["competitors"] == []
    assert competitors.FALLBACK_WARNING in out["warnings"]


def test_snippet_is_stored_when_page_fetch_fails(tmp_path):
    deps = studio_deps(tmp_path)
    deps.search = SearchChain([("claude", CountingSearch())])

    def boom(url):
        raise RuntimeError("blocked")
    deps.fetcher = boom
    state = {"job_id": "s1", "profile": fake_llm().handlers[StartupProfile]("", "").model_dump()}
    out = research.run(state, deps)
    evs = deps.evidence.for_subject("s1")
    assert evs and all(ev.kind == "search_snippet" for ev, _ in evs)
    assert out["market"]["key_findings"]  # a snippet URL may be cited
    assert not out["market_fallback"]


def test_essential_queries_are_sanitized():
    p = fake_llm().handlers[StartupProfile]("", "")
    p.company_name = "Acme jane@acme.com Pty Ltd"
    qs = essential_queries(p, 2026)
    assert set(qs) == {"competitors", "market", "company"}
    assert all("@" not in q and len(q) <= 200 for q in qs.values())
    assert qs["company"] == "Acme revenue ARR funding valuation 2026"
    assert qs["market"].endswith("Australia 2026")


# ================================================================== provider chain
def test_provider_fallback_brave_to_claude(tmp_path):
    store = EvidenceStore(tmp_path / "e.sqlite")
    brave_calls, bridge_calls = [], []
    chain = SearchChain([("brave", quota_brave(store, brave_calls)),
                         ("claude", ClaudeBridgeSearch("http://bridge:8765", "tok", store,
                                                       transport=bridge_transport(bridge_calls)))])
    results, provider = chain.search("food traceability competitors")
    assert provider == "claude" and [r["url"] for r in results] == ["https://a.example/x"]
    assert results[0]["description"] == "about A"
    req = bridge_calls[0]
    assert req.url.path == "/search" and req.headers["X-Bridge-Token"] == "tok"
    assert json.loads(req.content) == {"query": "food traceability competitors", "count": 8}
    chain.search("another query")
    assert len(brave_calls) == 1  # Brave refusal cached -> skipped without a request
    assert len(bridge_calls) == 2


def test_bridge_query_and_count_are_capped(tmp_path):
    calls: list = []
    b = ClaudeBridgeSearch("http://bridge:8765/", "tok", transport=bridge_transport(calls))
    b.search("x" * 500, count=50)
    body = json.loads(calls[0].content)
    assert len(body["query"]) == 200 and body["count"] == 8


@pytest.mark.parametrize("kw", [{"status": 429}, {"status": 503}, {"exc": httpx.ReadTimeout("slow")},
                                {"status": 401}, {"body": {"oops": 1}}])
def test_bridge_errors_are_cached(tmp_path, kw):
    calls: list = []
    b = ClaudeBridgeSearch("http://bridge:8765", "tok", EvidenceStore(tmp_path / "e.sqlite"),
                           transport=bridge_transport(calls, **kw))
    for q in ("a", "b"):
        with pytest.raises(BridgeUnavailable):
            b.search(q)
    assert len(calls) == 1 and not b.available
    b.unavailable_until = 0  # after UNAVAILABLE_S it is tried again
    with pytest.raises(BridgeUnavailable):
        b.search("c")
    assert len(calls) == 2


def test_bridge_results_are_cached(tmp_path):
    calls: list = []
    b = ClaudeBridgeSearch("http://bridge:8765", "tok", EvidenceStore(tmp_path / "e.sqlite"),
                           transport=bridge_transport(calls))
    assert b.search("q1") == b.search("q1")
    assert len(calls) == 1


def test_chain_all_unavailable_raises_and_build_search_from_settings(tmp_path):
    store = EvidenceStore(tmp_path / "e.sqlite")
    chain = SearchChain([("brave", quota_brave(store, []))])
    with pytest.raises(SearchUnavailable):
        chain.search("x")
    s = replace(get_settings(), brave_api_key="", claude_search_url="http://172.18.0.1:8765",
                claude_search_token="t", search_providers=("brave", "claude"))
    assert search_mod.build_search(s, store).names == ["claude"]
    s = replace(s, brave_api_key="k")
    assert search_mod.build_search(s, store).names == ["brave", "claude"]
    assert search_mod.build_search(replace(s, search_providers=("claude", "brave")), store).names == ["claude", "brave"]
    assert search_mod.build_search(replace(s, brave_api_key="", claude_search_token=""), store) is None


# ================================================================== site crawl
def big_site_transport(seen: list):
    links = ["/blog/post-1", "/blog/post-2", "/careers", "/login", "/privacy", "/terms", "/pricing", "/about",
             "/customers", "/team", "/press", "/product", "/random", "/blog/post-3", "/contact"]
    home = "<html><head><title>Big</title></head><body><p>Big Co home.</p>" + "".join(
        f"<a href='{u}'>{u}</a>" for u in links) + "</body></html>"

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r.url.path)
        if r.url.path == "/robots.txt":
            return httpx.Response(404)
        body = home if r.url.path == "/" else f"<html><body><p>Page {r.url.path} text.</p></body></html>"
        return httpx.Response(200, text=body, headers={"content-type": "text/html"})
    return httpx.MockTransport(handler)


def test_site_crawl_respects_site_max_pages_and_priority(tmp_path):
    assert get_settings().site_max_pages == 6
    seen: list = []
    res = site_intake.crawl("https://big.example", max_pages=6, transport=big_site_transport(seen),
                            host_ok=lambda h: h == "big.example")
    paths = [p.url.split("big.example", 1)[1] for p in res.pages]
    assert paths == ["/", "/about", "/product", "/pricing", "/customers", "/team"]
    assert not any(p in seen for p in ("/login", "/privacy", "/terms", "/blog/post-1"))
    # read_site uses SITE_MAX_PAGES
    deps = studio_deps(tmp_path)
    deps.settings = replace(deps.settings, site_max_pages=2)
    deps.site_transport, deps.host_check = big_site_transport([]), (lambda h: h == "big.example")
    out = site_intake.read_site({"job_id": "vs", "url": "https://big.example"}, deps)
    assert out["site_pages"] == 2


# ================================================================== LLM providers
def fake_openai(replies: list):
    """Minimal stand-in for openai.OpenAI: each reply is a content string or an exception to raise."""
    calls: list[dict] = []

    def create(**kw):
        calls.append(kw)
        r = replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=r))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return client, calls


def _status_error(cls, code: int, msg: str):
    req = httpx.Request("POST", "https://api.sambanova.ai/v1/chat/completions")
    return cls(msg, response=httpx.Response(code, request=req, json={"error": msg}), body=None)


GOOD = '{"summary": "ok", "strengths": ["a"], "concerns": []}'


def test_extract_json_handles_think_blocks_fences_and_prose():
    assert json.loads(extract_json("<think>hmm {not json}</think>\n```json\n" + GOOD + "\n```"))["summary"] == "ok"
    assert json.loads(extract_json("Here you go: " + GOOD + " Hope it helps"))["summary"] == "ok"
    assert extract_json(GOOD) == GOOD


def test_sambanova_parses_and_uses_json_mode():
    client, calls = fake_openai(["<think>x</think>```json\n" + GOOD + "\n```"])
    llm = SambaNovaLLM("u", "k", "DeepSeek-V3.1", client=client)
    assert llm.complete_json("cloud", "sys", "user", Narrative).summary == "ok"
    assert calls[0]["model"] == "DeepSeek-V3.1" and calls[0]["response_format"] == {"type": "json_object"}


def test_sambanova_drops_json_mode_on_400_and_retries_once():
    import openai

    client, calls = fake_openai([_status_error(openai.BadRequestError, 400, "Model did not output valid JSON"), GOOD])
    llm = SambaNovaLLM("u", "k", "Meta-Llama-3.3-70B-Instruct", client=client)
    assert llm.complete_json("cloud", "s", "u", Narrative).summary == "ok"
    assert "response_format" in calls[0] and "response_format" not in calls[1]


def test_sambanova_one_retry_then_fall_through_and_429_cooldown():
    import openai

    req = httpx.Request("POST", "https://x")
    client, calls = fake_openai([openai.APITimeoutError(request=req), openai.APITimeoutError(request=req), GOOD])
    llm = SambaNovaLLM("u", "k", "m-timeout", client=client)
    with pytest.raises(LLMError):
        llm.complete_json("cloud", "s", "u", Narrative)
    assert len(calls) == 2  # first try + one retry

    SambaNovaLLM._cooldown.pop("m-429", None)
    client, calls = fake_openai([_status_error(openai.RateLimitError, 429, "daily limit"), GOOD])
    llm = SambaNovaLLM("u", "k", "m-429", client=client)
    with pytest.raises(LLMError, match="rate-limited"):
        llm.complete_json("cloud", "s", "u", Narrative)
    with pytest.raises(LLMError, match="cooling down"):  # parked: no request at all
        llm.complete_json("cloud", "s", "u", Narrative)
    assert len(calls) == 1
    SambaNovaLLM._cooldown.pop("m-429", None)


def test_provider_order_and_skipping_missing_keys():
    base = replace(get_settings(), claude_cli_enabled=False, sambanova_api_key="s", deepinfra_api_key="d",
                   sambanova_models=("DeepSeek-V3.1", "Meta-Llama-3.3-70B-Instruct"),
                   deepinfra_models=("Qwen/Qwen3-235B-A22B-Instruct-2507",))
    names = [n for n, _ in cloud_chain(base)]
    assert names == ["sambanova:DeepSeek-V3.1", "sambanova:Meta-Llama-3.3-70B-Instruct",
                     "deepinfra:Qwen/Qwen3-235B-A22B-Instruct-2507"]
    names = [n for n, _ in cloud_chain(replace(base, llm_provider_order=("deepinfra", "sambanova")))]
    assert names[0].startswith("deepinfra:") and names[-1].startswith("sambanova:")
    assert all(n.startswith("deepinfra:") for n, _ in cloud_chain(replace(base, sambanova_api_key="")))
    with_cli = [n for n, _ in cloud_chain(replace(base, claude_cli_enabled=True))]
    assert with_cli[0] == "claude-cli"
    later = [n for n, _ in cloud_chain(replace(base, claude_cli_enabled=True,
                                                llm_provider_order=("sambanova", "claude")))]
    assert later[-1] == "claude-cli" and "deepinfra" not in " ".join(later)


def test_fallback_records_which_provider_answered():
    bad = FakeLLM({})
    good = FakeLLM({Narrative: lambda s, u: Narrative(summary="x", strengths=[], concerns=[])})
    chain = FallbackLLM([("sambanova:DeepSeek-V3.1", bad), ("deepinfra:qwen", good)])
    used, tok = track_providers()
    try:
        chain.complete_json("cloud", "s", "u", Narrative)
    finally:
        untrack_providers(tok)
    assert used[-1] == "deepinfra:qwen"


def test_claude_bridge_llm_answers_and_cools_down_on_failure():
    import httpx

    from blockid_agents.llm import ClaudeBridgeLLM, LLMError
    from blockid_agents.schemas import Narrative

    seen = []

    def ok(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"structured_output": {"summary": "s", "strengths": [], "concerns": []},
                                         "model": "sonnet", "cost_usd": 0.01})

    llm = ClaudeBridgeLLM("http://bridge:8765", "tok", transport=httpx.MockTransport(ok))
    assert llm.complete_json("cloud", "sys", "user", Narrative).summary == "s"
    assert seen[0]["user"] == "user" and seen[0]["schema"]["title"] == "Narrative"

    calls = []
    busy = ClaudeBridgeLLM("http://bridge:8765", "tok", transport=httpx.MockTransport(
        lambda r: calls.append(1) or httpx.Response(429, json={"detail": "cap"})))
    with pytest.raises(LLMError):
        busy.complete_json("cloud", "s", "u", Narrative)
    with pytest.raises(LLMError, match="cooling down"):  # parked: no second HTTP call
        busy.complete_json("cloud", "s", "u", Narrative)
    assert len(calls) == 1


def test_claude_bridge_sits_between_free_and_paid_providers():
    s = replace(get_settings(), claude_cli_enabled=False, sambanova_api_key="s", deepinfra_api_key="d",
                sambanova_models=("gpt-oss-120b",), deepinfra_models=("deepseek-ai/DeepSeek-V4-Flash",),
                claude_search_url="http://bridge:8765", claude_search_token="t",
                llm_provider_order=("sambanova", "claude_bridge", "deepinfra"))
    assert [n for n, _ in cloud_chain(s)] == ["sambanova:gpt-oss-120b", "claude-bridge",
                                            "deepinfra:deepseek-ai/DeepSeek-V4-Flash"]
    assert "claude-bridge" not in [n for n, _ in cloud_chain(replace(s, claude_search_token=""))]
