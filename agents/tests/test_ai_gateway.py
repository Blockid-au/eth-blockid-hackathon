"""AI gateway (ai_gateway.py, docs/PLAN-AI-GATEWAY.md §1): deadlines, hedging, circuit breaker, demote / skip
thresholds, pacing, fair queue, profile ordering, context pre-check, result cache, search routing — offline fakes.
The Postgres ledger and the admin API run against TEST_DATABASE_URL (skipped when unset)."""
import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_studio import ADMIN_KEY, USER_KEY, needs_db, siwe_login, studio_env  # noqa: F401 (fixture)

from blockid_agents import ai_gateway as gwm
from blockid_agents.ai_gateway import (
    CallRecord,
    CircuitBreaker,
    FairLimiter,
    Gateway,
    MemoryLedger,
    TokenBucket,
    parse_rate_headers,
    profile_for,
    user_scope,
)
from blockid_agents.config import get_settings
from blockid_agents.llm import (
    FakeLLM,
    LLMError,
    OpenAICompatLLM,
    RateLimited,
    RoutedLLM,
    SchemaError,
    TierRouter,
    build_agent_llms,
    build_llm,
    current_call,
    primary_provider,
    reset_listener,
    set_listener,
    track_providers,
    untrack_providers,
)
from blockid_agents.schemas import Narrative, QualitativeScores

SAMBA = "sambanova:DeepSeek-V3.1"
SAMBA2 = "sambanova:DeepSeek-V3.2"
FLASH = "deepinfra:deepseek-ai/DeepSeek-V4-Flash"
CLAUDE = "claude-bridge"


def settings(**kw):
    base = dict(llm_backend="hosted", ai_routing="dynamic", ai_hedge=True, ai_hedge_delay_s=0.05, ai_hedge_min_s=0.05,
                ai_hedge_max_s=0.05, ai_pacing_wait_s=0.0, ai_queue_wait_s=1.0, ai_cache_ttl_hours=0,
                sambanova_timeout=2.0, ai_deadline_deepinfra_s=2.0, ai_deadline_claude_s=2.0, ai_stats_ttl_s=0,
                database_url="", sambanova_api_key="", deepinfra_api_key="", claude_search_token="",
                brave_api_key="", claude_cli_enabled=False, ai_bridge_poll=False)
    base.update(kw)
    return replace(get_settings(), **base)


def narr(text="x"):
    return Narrative(summary=text, strengths=[], concerns=[])


class Ok:
    def __init__(self, text="ok", delay=0.0):
        self.text, self.delay, self.calls = text, delay, 0

    def complete_json(self, tier, system, user, schema):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        return narr(self.text)


class Fail:
    def __init__(self, exc=None):
        self.exc, self.calls = exc or LLMError("503 overloaded"), 0

    def complete_json(self, tier, system, user, schema):
        self.calls += 1
        raise self.exc


class Hang:
    """Blocks until the gateway cancels the call (closes its "connection"), like a hung HTTP read."""

    def __init__(self, answer_after: float | None = None):
        self.cancelled = threading.Event()
        self.answer_after = answer_after
        self.calls = 0

    def complete_json(self, tier, system, user, schema):
        self.calls += 1
        ctx = current_call()
        ev = threading.Event()
        ctx.on_cancel(ev.set)
        ev.wait(self.answer_after if self.answer_after is not None else 10)
        if ev.is_set():
            self.cancelled.set()
            raise LLMError("connection closed")
        return narr("slow")


def router(gw, backends, **kw):
    return RoutedLLM(backends, gw, **{"interactive": False, **kw})


# ================================================================== profiles / helpers
def test_profile_mapping_and_context_precheck():
    assert profile_for("PersonAnalysis") == "extract_json" and profile_for("TeamAnalysis") == "reason_score"
    assert profile_for("Narrative", "cloud_max") == "reason_score"
    assert profile_for("CompetitorList", "cloud", 40_000) == "long_context"
    gw = Gateway(settings(), MemoryLedger())
    plan = gw.plan("long_context", [SAMBA2, SAMBA, FLASH], 40_000)
    assert SAMBA2 not in plan.order and "context window" in plan.status[SAMBA2][1]
    assert set(plan.order) == {SAMBA, FLASH}
    assert SAMBA2 in gw.plan("extract_json", [SAMBA2, SAMBA], 3_000).order


def test_dynamic_order_priors_ledger_pins_and_static():
    gw = Gateway(settings(), MemoryLedger())
    names = [CLAUDE, SAMBA, FLASH]
    order = gw.plan("extract_json", names, 5000).order
    assert order[0] == SAMBA  # free + strong first; the scarce subscription and the paid model after it
    # the ledger shows DeepSeek failing half its calls and slow: it drops below DeepSeek-V4-Flash
    for i in range(30):
        gw.record(CallRecord(SAMBA, "ok" if i % 2 else "error", schema_ok=True if i % 2 else None, latency_s=55))
    assert gw.plan("extract_json", names, 5000).order[0] != SAMBA
    # HR: Claude pinned first for reason_score while healthy
    assert gw.plan("reason_score", names, 5000, pins=(CLAUDE,)).order[0] == CLAUDE
    # AI_ROUTING=static: env order, health still applies
    st = Gateway(settings(ai_routing="static"), MemoryLedger())
    assert st.plan("extract_json", names, 5000).order == names


def test_parse_rate_headers_openai_style_and_brave():
    now = 1_000_000.0
    rl = parse_rate_headers({"x-ratelimit-limit-requests": "60", "x-ratelimit-remaining-requests": "12",
                             "x-ratelimit-reset-requests": "20s", "x-ratelimit-limit-requests-day": "12000",
                             "x-ratelimit-remaining-requests-day": "300",
                             "x-ratelimit-reset-requests-day": "3h0m0s"}, now)
    assert rl["minute"] == {"remaining": 12, "limit": 60, "reset_at": now + 20}
    assert rl["day"]["remaining"] == 300 and rl["day"]["reset_at"] == now + 3 * 3600
    b = parse_rate_headers({"X-RateLimit-Limit": "1, 2000", "X-RateLimit-Remaining": "0, 5",
                            "X-RateLimit-Reset": "1, 86400"}, now)
    assert b == {"month": {"remaining": 5, "limit": 2000, "reset_at": now + 86400}}
    assert parse_rate_headers(None, now) == {}


# ================================================================== quota windows
def test_demote_at_80_skip_at_95_and_reset():
    t = [1_700_000_000.0]
    gw = Gateway(settings(), MemoryLedger(), clock=lambda: t[0])
    for _ in range(48):  # 48 / 60 rpm = 80 %
        gw.record(CallRecord(SAMBA, "ok", at=t[0]))
    assert gw.status(SAMBA)[0] == "demoted" and "per-minute" in gw.status(SAMBA)[1]
    plan = gw.plan("extract_json", [SAMBA, SAMBA2], 1000)
    assert plan.order == [SAMBA2, SAMBA]  # used only as a fallback
    for _ in range(10):  # 58 / 60 = 96.7 %
        gw.record(CallRecord(SAMBA, "ok", at=t[0]))
    assert gw.status(SAMBA)[0] == "skipped"
    assert gw.plan("extract_json", [SAMBA, SAMBA2], 1000).order == [SAMBA2]
    t[0] += 61  # the minute window resets
    assert gw.status(SAMBA)[0] == "healthy"
    # provider headers can say more than our own count (another client uses the same key)
    gw.observe_headers(SAMBA, {"x-ratelimit-limit-requests-day": "12000", "x-ratelimit-remaining-requests-day": "400",
                               "x-ratelimit-reset-requests-day": "7200"})
    st, why = gw.status(SAMBA)
    assert st == "skipped" and "daily limit" in why
    w = next(x for x in gw.windows(SAMBA) if x["window"] == "day")
    assert w["source"] == "headers" and w["used"] == 11600
    t[0] += 7201  # header window passed -> back to the ledger count
    assert gw.status(SAMBA)[0] == "healthy"


def test_deepinfra_daily_budget_and_bridge_cap():
    t = [1_700_000_000.0]
    gw = Gateway(settings(deepinfra_daily_budget_usd=1.0, bridge_complete_max_per_day=10), MemoryLedger(),
                 clock=lambda: t[0])
    gw.record(CallRecord(FLASH, "ok", cost_usd=0.85, at=t[0]))
    assert gw.status(FLASH)[0] == "demoted" and "daily budget" in gw.status(FLASH)[1]
    gw.record(CallRecord(FLASH, "ok", tokens_in=2_000_000, tokens_out=0, at=t[0]))  # +0.18 estimated from tokens
    assert gw.status(FLASH)[0] == "skipped"
    for _ in range(8):
        gw.record(CallRecord(CLAUDE, "ok", at=t[0]))
    assert gw.status(CLAUDE)[0] == "demoted"
    gw.record(CallRecord(CLAUDE, "skipped", sent=False, at=t[0]))  # a skip is not a request
    assert gw.status(CLAUDE)[0] == "demoted"


def test_reroute_message_for_the_hr_feed():
    t = [1_700_000_000.0]
    gw = Gateway(settings(sambanova_rpd=100), MemoryLedger(), clock=lambda: t[0])
    for _ in range(85):
        gw.record(CallRecord(SAMBA, "ok", at=t[0] - 3600))
    seen = []
    tok = set_listener(seen.append)
    try:
        r = router(gw, [(SAMBA, Ok("samba")), (FLASH, Ok("flash"))], pins={"reason_score": (SAMBA,)})
        assert r.complete_json("cloud", "s", "u", Narrative).summary == "flash"
        r.complete_json("cloud", "s", "u2", Narrative)  # said once per run, not for every call
    finally:
        reset_listener(tok)
    msgs = [e["message"] for e in seen if e["type"] == "llm_rerouted"]
    assert msgs == ["SambaNova DeepSeek-V3.1 near its daily limit → using DeepInfra DeepSeek-V4-Flash"]
    assert seen[-1] == {"type": "llm_answered", "provider": FLASH}


# ================================================================== breaker
def test_circuit_breaker_consecutive_backoff_and_half_open_probe():
    t = [0.0]
    b = CircuitBreaker(clock=lambda: t[0])
    for _ in range(2):
        b.failure()
    assert b.allow() and b.current() == "closed"
    b.failure()  # 3 consecutive -> open 2 min
    assert b.current() == "open" and not b.allow() and b.open_until == 120
    t[0] = 121
    assert b.current() == "half_open"
    assert b.allow() and not b.allow()  # one probe only
    b.failure()  # probe failed -> open again, twice as long
    assert b.open_until == 121 + 240
    t[0] = 400
    assert b.allow()
    b.success()
    assert b.current() == "closed" and b.opens == 0
    for _ in range(4):  # 2, 4, 8, then capped at 10 min
        b.failure(hard=True)
        t[0] = b.open_until
        b.allow()
    assert b.open_until - t[0] == 0 and b.opens == 4 and b.base_open_s * 2 ** 3 > b.max_open_s


def test_circuit_breaker_error_rate_window_and_hard_failure():
    t = [0.0]
    b = CircuitBreaker(clock=lambda: t[0])
    for ok in (True, False, True, False, True, False):  # 50 % over 6 calls, never 3 in a row
        b.success() if ok else b.failure()
    assert b.current() == "open"
    b2 = CircuitBreaker(clock=lambda: t[0])
    b2.failure(hard=True)  # 429 / 402: open at once
    assert b2.current() == "open"


def test_router_opens_breaker_and_skips_the_model():
    gw = Gateway(settings(), MemoryLedger())
    bad, good = Fail(RateLimited("429 daily limit")), Ok("good")
    r = router(gw, [(SAMBA, bad), (FLASH, good)], pins={"reason_score": (SAMBA,)})
    assert r.complete_json("cloud", "s", "u1", Narrative).summary == "good"
    assert gw.breaker(SAMBA).current() == "open"
    r.complete_json("cloud", "s", "u2", Narrative)
    assert bad.calls == 1 and good.calls == 2  # the open model is not called again
    assert gw.plan("extract_json", [SAMBA, FLASH], 100).status[SAMBA][0] == "open"


# ================================================================== deadlines / hedging
def test_deadline_cancels_a_hung_call_and_falls_through():
    gw = Gateway(settings(sambanova_timeout=0.2), MemoryLedger())
    hung, good = Hang(), Ok("next")
    seen = []
    tok = set_listener(seen.append)
    try:
        t0 = time.monotonic()
        out = router(gw, [(SAMBA, hung), (FLASH, good)], pins={"reason_score": (SAMBA,)}).complete_json(
            "cloud", "s", "u", Narrative)
    finally:
        reset_listener(tok)
    assert out.summary == "next" and time.monotonic() - t0 < 1.5
    assert hung.cancelled.wait(1)  # its connection was closed
    rows = gw.ledger.rows
    assert [(r.model_id, r.outcome) for r in rows] == [(SAMBA, "timeout"), (FLASH, "ok")]
    assert rows[0].fallback_to == FLASH
    assert seen[0]["type"] == "llm_fallback" and seen[0]["failed"] == SAMBA and seen[0]["next"] == FLASH


def test_hedged_request_first_valid_answer_wins_and_loser_is_cancelled():
    gw = Gateway(settings(), MemoryLedger())
    slow, fast = Hang(), Ok("hedge")
    seen = []
    tok = set_listener(seen.append)
    used, utok = track_providers()
    try:
        r = router(gw, [(SAMBA, slow), (FLASH, fast)], interactive=True, pins={"reason_score": (SAMBA,)})
        assert r.complete_json("cloud", "s", "u", Narrative).summary == "hedge"
    finally:
        untrack_providers(utok)
        reset_listener(tok)
    assert slow.cancelled.wait(1)
    assert used == [FLASH] and r.used == [(FLASH, "Narrative")]
    outcomes = {(x.model_id, x.outcome, x.hedged) for x in gw.ledger.rows}
    assert outcomes == {(FLASH, "ok", True), (SAMBA, "cancelled", False)}
    assert any(e["type"] == "llm_hedged" and e["message"] ==
               "SambaNova DeepSeek-V3.1 is slow → also asking DeepInfra DeepSeek-V4-Flash" for e in seen)


def test_no_hedge_for_batch_routers_and_primary_can_still_win():
    gw = Gateway(settings(), MemoryLedger())
    slowish, other = Hang(answer_after=0.2), Ok("other")
    r = router(gw, [(SAMBA, slowish), (FLASH, other)], interactive=False, pins={"reason_score": (SAMBA,)})
    assert r.complete_json("cloud", "s", "u", Narrative).summary == "slow"
    assert other.calls == 0


def test_all_fail_raises_with_every_error():
    gw = Gateway(settings(), MemoryLedger())
    with pytest.raises(LLMError, match="all LLM backends failed"):
        router(gw, [(SAMBA, Fail()), (FLASH, Fail())]).complete_json("cloud", "s", "u", Narrative)


# ================================================================== schema repair
def fake_openai(replies):
    calls = []

    def create(**kw):
        calls.append(kw)
        text = replies.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
                               usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=200))

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), calls


GOOD = '{"summary": "ok", "strengths": [], "concerns": []}'


def test_schema_repair_once_on_the_same_model_then_fall_back():
    client, calls = fake_openai(['{"summary": 1}', GOOD])
    llm = OpenAICompatLLM("u", "k", {"cloud": "m"}, max_retries=1, client=client)
    assert llm.complete_json("cloud", "s", "u", Narrative).summary == "ok"
    assert len(calls) == 2 and "Invalid JSON" in calls[1]["messages"][-1]["content"]

    client, calls = fake_openai(['{"summary": 1}', "not json"])
    bad = OpenAICompatLLM("u", "k", {"cloud": "m"}, max_retries=1, client=client)
    with pytest.raises(SchemaError):
        bad.complete_json("cloud", "s", "u", Narrative)

    client, _ = fake_openai(['{"summary": 1}', "nope"])
    good_client, _ = fake_openai([GOOD])
    gw = Gateway(settings(), MemoryLedger())
    r = router(gw, [(FLASH, OpenAICompatLLM("u", "k", {"cloud": "m"}, max_retries=1, client=client)),
                    (SAMBA, OpenAICompatLLM("u", "k", {"cloud": "m"}, max_retries=1, client=good_client))],
               pins={"reason_score": (FLASH,)})
    assert r.complete_json("cloud", "s", "u", Narrative).summary == "ok"
    first = gw.ledger.rows[0]
    assert first.model_id == FLASH and first.outcome == "schema_invalid" and first.schema_ok is False
    assert gw.ledger.rows[1].tokens_in == 1000 and gw.ledger.rows[1].cost_usd == 0  # SambaNova: free tier


# ================================================================== pacing / fair queue
def test_token_bucket_paces_bursts():
    t = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        t[0] += s

    b = TokenBucket(rate=1.0, capacity=2, clock=lambda: t[0], sleep=sleep)
    assert b.acquire() and b.acquire() and slept == []  # burst
    assert not b.acquire(max_wait=0.5)  # would need 1 s
    assert b.acquire(max_wait=5) and slept == [1.0]
    assert b.acquire(max_wait=5) and slept == [1.0, 1.0]  # spread, one per second
    gw = Gateway(settings(sambanova_rpm=60), MemoryLedger())
    assert gw.bucket(SAMBA).rate == pytest.approx(0.9) and gw.bucket(SAMBA).capacity == 10
    assert gw.bucket(FLASH) is None


def test_fair_limiter_serves_the_least_recently_served_user_first():
    lim = FairLimiter(1)
    assert lim.acquire("heavy", 0)
    order = []

    def wait(user):
        if lim.acquire(user, 5):
            order.append(user)
            time.sleep(0.02)
            lim.release()

    def queued(n):
        deadline = time.monotonic() + 2
        while lim.snapshot()["queued"] < n and time.monotonic() < deadline:
            time.sleep(0.005)

    ths = []
    for i, u in enumerate(["heavy", "heavy", "light"]):  # the heavy user queued twice before the light one
        th = threading.Thread(target=wait, args=(u,))
        th.start()
        ths.append(th)
        queued(i + 1)
    lim.release()
    for th in ths:
        th.join(5)
    assert order == ["light", "heavy", "heavy"]
    assert not lim.acquire("x", 0) or lim.release() is None  # free again
    lim2 = FairLimiter(1)
    lim2.acquire("a", 0)
    assert lim2.acquire("b", 0.05) is False and lim2.snapshot()["queued"] == 0  # timed out and left the queue


def test_user_context_reaches_the_ledger():
    gw = Gateway(settings(), MemoryLedger())
    with user_scope("0xABC"):
        router(gw, [(SAMBA, Ok())]).complete_json("cloud", "s", "u", Narrative)
    router(gw, [(SAMBA, Ok())]).complete_json("cloud", "s", "u2", Narrative)
    assert [r.user for r in gw.ledger.rows] == ["0xabc", "system"]


# ================================================================== cache
def test_result_cache_24h():
    t = [1_700_000_000.0]
    gw = Gateway(settings(ai_cache_ttl_hours=24), MemoryLedger(), clock=lambda: t[0])
    b = Ok("first")
    r = router(gw, [(SAMBA, b)])
    assert r.complete_json("cloud", "s", "same", Narrative).summary == "first"
    b.text = "second"
    used, utok = track_providers()
    try:
        assert r.complete_json("cloud", "s", "same", Narrative).summary == "first"  # cached, no call
    finally:
        untrack_providers(utok)
    assert b.calls == 1 and used == [SAMBA]
    assert r.complete_json("cloud", "s", "other", Narrative).summary == "second"
    t[0] += 24 * 3600 + 1
    assert r.complete_json("cloud", "s", "same", Narrative).summary == "second" and b.calls == 3


# ================================================================== wiring / search
def test_build_llm_wraps_the_env_chain_in_the_router():
    gwm.reset_gateways()
    s = settings(sambanova_api_key="k", deepinfra_api_key="d", sambanova_models=("DeepSeek-V3.1",),
                 deepinfra_models=("deepseek-ai/DeepSeek-V4-Flash",), claude_search_url="http://bridge:1",
                 claude_search_token="t", llm_provider_order=("sambanova", "claude_bridge", "deepinfra"))
    llm = build_llm(s)
    assert isinstance(llm, TierRouter) and isinstance(llm.routes["cloud"], RoutedLLM)
    assert [n for n, _ in llm.routes["cloud"].backends] == [SAMBA, CLAUDE, FLASH]
    hr = build_agent_llms(s)["people_analyst"].routes["cloud"]
    assert hr.pins == {"reason_score": (CLAUDE,)} and hr.agent == "people_analyst"
    assert primary_provider(llm) == SAMBA  # the router's current first choice
    # the adapters leave parking to the gateway
    assert llm.routes["cloud"].backends[0][1].park is False
    gwm.reset_gateways()


def test_search_chain_skips_a_provider_at_its_monthly_quota(tmp_path):
    from blockid_agents.tools.search import SearchChain

    class Prov:
        def __init__(self, name):
            self.name, self.calls, self.available, self.last_cached = name, 0, True, False

        def search(self, q, count=8):
            self.calls += 1
            return [{"title": "t", "url": "https://x.example/" + self.name, "description": "", "query": q}]

    t = [1_700_000_000.0]
    gw = Gateway(settings(brave_monthly_quota=100), MemoryLedger(), clock=lambda: t[0])
    brave, claude = Prov("brave"), Prov("claude")
    chain = SearchChain([("brave", brave), ("claude", claude)], gw)
    assert chain.search("q")[1] == "brave"
    for _ in range(95):
        gw.record(CallRecord("search:brave", "ok", profile="search", at=t[0]))
    seen = []
    tok = set_listener(seen.append)
    try:
        assert chain.search("q2")[1] == "claude"
    finally:
        reset_listener(tok)
    assert brave.calls == 1 and claude.calls == 1
    assert seen[0]["message"] == "Brave Search at its monthly limit → using Claude web search"
    brave.last_cached = True
    gw.ledger.rows = [r for r in gw.ledger.rows if r.model_id != "search:brave"]
    chain.search("q3")
    assert gw.ledger.rows[-1].sent is False  # a cache hit is not counted against the quota


def test_health_shape_and_pause_resume_in_memory():
    t = [1_700_000_000.0]
    s = settings(sambanova_api_key="k", sambanova_models=("DeepSeek-V3.1",), llm_provider_order=("sambanova",),
                 hr_llm_provider_order=("sambanova",), hr_sambanova_models=("DeepSeek-V3.1",))
    gw = Gateway(s, MemoryLedger(), clock=lambda: t[0])
    gw.record(CallRecord(SAMBA, "ok", latency_s=4, tokens_in=100, tokens_out=10, profile="extract_json", at=t[0]))
    gw.record(CallRecord(SAMBA, "timeout", error="no answer after 60 s", fallback_to=FLASH, profile="extract_json",
                         agent="people_analyst", at=t[0]))
    h = gw.health()
    m = next(x for x in h["models"] if x["id"] == SAMBA)
    assert m["status"] == "healthy" and m["calls_24h"] == 2 and m["error_rate"] == 0.5
    assert m["latency_p50_s"] == 4.0 and m["tokens_in_today"] == 100 and m["context_tokens"] == 131072
    assert {w["window"] for w in m["windows"]} == {"minute", "day"}
    assert h["recent_fallbacks"][0]["failed"] == SAMBA and h["recent_fallbacks"][0]["next"] == FLASH
    assert h["profiles"]["extract_json"] == [SAMBA] and h["providers"][0]["id"] == "sambanova"
    gw.pause(SAMBA, by="admin", reason="flaky", minutes=5)
    assert gw.model_health(SAMBA)["status"] == "paused"
    with pytest.raises(LLMError, match="no model available"):
        router(gw, [(SAMBA, Ok())]).complete_json("cloud", "s", "u", Narrative)
    t[0] += 301  # pause expired
    assert gw.model_health(SAMBA)["status"] == "healthy"
    gw.pause(SAMBA, by="admin")
    gw.resume(SAMBA, by="admin")
    assert gw.model_health(SAMBA)["status"] == "healthy"


def test_explicit_profile_keyword_and_bridge_counters():
    gw = Gateway(settings(), MemoryLedger())
    a, b = Ok("a"), Ok("b")
    r = RoutedLLM([(SAMBA, a), (FLASH, b)], gw, interactive=False, pins={"extract_json": (FLASH,)})
    tr = TierRouter({"cloud": r})
    assert tr.complete_json("cloud", "s", "u", Narrative, profile="extract_json").summary == "b"
    assert gw.ledger.rows[-1].profile == "extract_json"
    assert tr.complete_json("cloud", "s", "u", Narrative).summary == "a"  # Narrative -> reason_score, no pin
    assert profile_for("SuggestedPeople") == "extract_json"
    import httpx

    calls = []
    orig = httpx.get
    httpx.get = lambda url, **kw: calls.append(url) or httpx.Response(200, json={
        "today": 147, "max_per_day": 150, "complete_today": 10, "complete_max_per_day": 300})
    try:
        g2 = Gateway(settings(claude_search_url="http://bridge:8765", claude_search_token="t", ai_bridge_poll=True),
                     MemoryLedger())
        g2.poll_bridge(wait=True)
        g2.poll_bridge(wait=True)  # at most once a minute
    finally:
        httpx.get = orig
    assert calls == ["http://bridge:8765/healthz"]
    assert g2.status("search:claude")[0] == "skipped" and g2.status(CLAUDE)[0] == "healthy"


def test_kill_switch_and_safe_degradation():
    from blockid_agents.ai_gateway import PgLedger
    from blockid_agents.llm import FallbackLLM

    gwm.reset_gateways()
    s = settings(sambanova_api_key="k", sambanova_models=("DeepSeek-V3.1",), llm_provider_order=("sambanova",))
    off = build_llm(replace(s, ai_gateway=False))
    assert type(off.routes["cloud"]) is FallbackLLM and off.routes["cloud"].backends[0][1].park is True
    assert type(build_agent_llms(replace(s, ai_gateway=False))["people_analyst"].routes["cloud"]) is FallbackLLM
    assert get_settings().ai_routing == "static"  # default until the benchmark refreshed the priors

    class DeadPool:  # ledger table missing / database down: routing still works, nothing is recorded
        def connection(self):
            raise RuntimeError("relation studio.ai_usage does not exist")

    gw = Gateway(settings(), PgLedger(pool=DeadPool()))
    assert router(gw, [(SAMBA, Ok("still works"))]).complete_json("cloud", "s", "u", Narrative).summary == \
        "still works"

    class Broken:
        def complete(self, *a, **k):
            raise KeyError("gateway bug")

    r = RoutedLLM([(SAMBA, Ok("plain chain"))], Broken())
    assert r.complete_json("cloud", "s", "u", Narrative).summary == "plain chain"
    gwm.reset_gateways()


def test_fake_llm_still_works_through_the_router():
    fake = FakeLLM({QualitativeScores: lambda s, u: None})
    gw = Gateway(settings(), MemoryLedger())
    with pytest.raises(LLMError):  # FakeLLM has no Narrative handler -> error -> all failed
        router(gw, [("fake", fake)]).complete_json("cloud", "s", "u", Narrative)


# ================================================================== Postgres ledger + admin API
@needs_db
def test_pg_ledger_counts_stats_state_cache(studio_env):
    from blockid_agents.ai_gateway import PgLedger

    db = studio_env["db"]
    led = PgLedger(pool=db.pool)
    now = time.time()
    for i in range(5):
        led.record(CallRecord(SAMBA, "ok", schema_ok=True, latency_s=2 + i, tokens_in=100, tokens_out=20,
                              cost_usd=0.0, profile="extract_json", agent="default", user="0xabc", at=now - i))
    led.record(CallRecord(FLASH, "ok", tokens_in=1000, tokens_out=100, cost_usd=0.01, at=now))
    led.record(CallRecord(FLASH, "timeout", error="no answer", fallback_to=SAMBA, at=now))
    led.record(CallRecord(CLAUDE, "skipped", sent=False, error="circuit open", fallback_to=SAMBA, at=now))
    c = led.counts_all(now)
    assert c[SAMBA]["minute"] == 5 and c[SAMBA]["day"] == 5 and c[SAMBA]["tokens_in_day"] == 500
    assert c[CLAUDE]["day"] == 0 and led.provider_spend_day("deepinfra", now) == pytest.approx(0.01)
    st = led.stats_all(now - 3600)
    assert st[SAMBA].n == 5 and st[SAMBA].schema_ok == 5 and st[SAMBA].p50 == pytest.approx(4.0)
    assert st[FLASH].errors == 1 and st[FLASH].last_error["error"] == "no answer"
    fb = led.recent_fallbacks()
    assert {(x["failed"], x["outcome"]) for x in fb} == {(FLASH, "timeout"), (CLAUDE, "skipped")}
    led.set_state(SAMBA, paused=True, paused_by="admin", paused_until=now + 60)
    led.set_state(SAMBA, rl={"day": {"remaining": 50, "limit": 100, "reset_at": now + 60}})
    s = led.states_all()[SAMBA]
    assert s["paused"] is True and s["rl"]["day"]["remaining"] == 50 and s["paused_until"] == pytest.approx(now + 60)
    led.cache_put("k1", "extract_json", SAMBA, "Narrative", {"summary": "c"}, now)
    assert led.cache_get("k1", 3600, now)["value"] == {"summary": "c"}
    assert led.cache_get("k1", 10, now + 3600) is None
    # the gateway on top of it (shared by API + worker): a demoted model from another process' calls
    gw = Gateway(settings(sambanova_rpd=6), led)
    assert gw.status(SAMBA)[0] == "paused"
    led.set_state(SAMBA, paused=False)
    led._states = None
    assert gw.status(SAMBA)[0] == "demoted"  # 5 of 6 per day = 83 %


@needs_db
def test_admin_ai_health_api(studio_env):
    gwm.reset_gateways()
    c = studio_env["client"]()
    assert c.get("/v1/admin/ai/health").status_code == 401
    siwe_login(c, USER_KEY)
    assert c.get("/v1/admin/ai/health").status_code == 403
    c = studio_env["client"]()
    siwe_login(c, ADMIN_KEY)
    h = c.get("/v1/admin/ai/health")
    assert h.status_code == 200
    body = h.json()
    assert set(body) >= {"generated_at", "routing", "providers", "models", "profiles", "recent_fallbacks"}
    gw = gwm.get_gateway(studio_env["runner"].deps.settings, db=studio_env["db"])
    gw.record(CallRecord(FLASH, "ok", latency_s=3, tokens_in=1000, tokens_out=100))
    mid = "deepinfra%3Adeepseek-ai%2FDeepSeek-V4-Flash"
    r = c.post(f"/v1/admin/ai/models/{mid}/pause", json={"reason": "testing", "minutes": 30})
    assert r.status_code == 200, r.text
    m = r.json()["model"]
    assert m["id"] == FLASH and m["status"] == "paused" and m["paused_by"] and m["paused_until"]
    assert c.post("/v1/admin/ai/models/nope:x/pause").status_code == 404
    health = c.get("/v1/admin/ai/health").json()
    assert next(x for x in health["models"] if x["id"] == FLASH)["status"] == "paused"
    r = c.post(f"/v1/admin/ai/models/{mid}/resume")
    assert r.status_code == 200 and r.json()["model"]["status"] == "healthy"
    rows = studio_env["db"].all("SELECT action, target FROM studio.audit WHERE action LIKE 'ai_model_%%' ORDER BY id")
    assert [(x["action"], x["target"]) for x in rows] == [("ai_model_paused", FLASH), ("ai_model_resumed", FLASH)]
    gwm.reset_gateways()
