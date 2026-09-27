"""Issuance Studio tests: ticker, cap table, SIWE, crawler, site_valuation graph (offline),
and API flows against a throwaway Postgres (TEST_DATABASE_URL; skipped when unset)."""
import json
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from blockid_agents.agents import competitors, site_intake
from blockid_agents.audit import AuditLog
from blockid_agents.config import get_settings
from blockid_agents.deps import Deps
from blockid_agents.fakes import (
    FAKE_SITE,
    fake_competitor_brave_transport,
    fake_competitor_fetch,
    fake_llm,
    fake_site_transport,
)
from blockid_agents.graph import build_site_valuation
from blockid_agents.studio import auth
from blockid_agents.studio.db import MemoryProgress
from blockid_agents.tools import captable, ticker
from blockid_agents.tools.brave import BraveSearch, EvidenceStore
from blockid_agents.tools.search import SearchChain

TEST_DB = os.environ.get("TEST_DATABASE_URL", "")
ADMIN_KEY = "0x" + "a1" * 32
USER_KEY = "0x" + "b2" * 32
ADMIN = Account.from_key(ADMIN_KEY).address
USER = Account.from_key(USER_KEY).address


# ================================================================== ticker
def test_ticker_rules_and_stopwords():
    c = ticker.suggest("AgriTrace Pty Ltd")
    assert len(c) == 3 and all(x["available"] for x in c)
    assert c[0] == {"ticker": "AGR", "available": True, "rule": "consonants"}  # first3 is also AGR -> deduped
    assert len({x["ticker"] for x in c}) == 3 and c[1]["rule"] == "letters"
    three = ticker.suggest("Blue Ocean Robotics Holdings")
    assert three[0] == {"ticker": "BOR", "available": True, "rule": "initials"}
    assert three[1]["ticker"] == "BOC" and three[1]["rule"] == "first+two"
    assert ticker.words("The Canva Group Australia Pty Ltd") == ["CANVA"]


def test_ticker_uniqueness_blocklist_and_always_three():
    taken = {"CNV", "CAN"}
    c = ticker.suggest("Canva", taken)
    assert len(c) == 3 and c[0]["available"] and c[0]["ticker"] not in taken
    assert all(len(x["ticker"]) == 3 and x["ticker"].isalpha() for x in c)
    # 'Ass Solutions' first3 -> ASS is blocked
    assert all(x["ticker"] not in ticker.BLOCKLIST for x in ticker.suggest("Assure Solutions"))
    assert not ticker.valid("ASS") and not ticker.valid("AUD") and not ticker.valid("AB1") and ticker.valid("XYZ")
    # Vietnamese diacritics are transliterated
    assert ticker.words("Công ty Đông Á JSC") == ["DONG", "A"]
    assert ticker.words("Go1") == ["GO", "ONE"] and ticker.suggest("Go1")[0]["ticker"] == "GON"
    # everything taken by the rules -> fallbacks are still available
    rules = [x["ticker"] for x in ticker.suggest("Blue Ocean Robotics")]
    again = ticker.suggest("Blue Ocean Robotics", rules)
    assert len(again) == 3 and all(x["available"] for x in again)


# ================================================================== cap table
def test_captable_largest_remainder_sums_exactly():
    hs = [{"name": "A", "wallet": ADMIN, "pct": 33.33}, {"name": "B", "wallet": USER, "pct": 33.33},
          {"name": "C", "wallet": "0x" + "1" * 40, "pct": 33.34}]
    out = captable.allocate(hs, 1_000_001)
    assert sum(h["shares"] for h in out) == 1_000_001
    assert [h["shares"] for h in out] == [333_300, 333_300, 333_401]
    small = captable.allocate([{"name": "A", "wallet": ADMIN, "pct": 50}, {"name": "B", "wallet": USER, "pct": 50}], 3)
    assert [h["shares"] for h in small] == [2, 1]  # tie -> input order


def test_captable_validation():
    with pytest.raises(captable.CapTableError, match="sum"):
        captable.allocate([{"name": "A", "wallet": ADMIN, "pct": 99.99}], 100)
    captable.allocate([{"name": "A", "wallet": ADMIN, "pct": 99.996}], 100)  # within 0.005
    bad = ADMIN[:2] + ADMIN[2:].swapcase()
    with pytest.raises(captable.CapTableError, match="checksum"):
        captable.allocate([{"name": "A", "wallet": bad, "pct": 100}], 100)
    assert captable.checksum(ADMIN.lower()) == ADMIN  # all-lowercase is normalised
    with pytest.raises(captable.CapTableError, match="duplicate"):
        captable.allocate([{"name": "A", "wallet": ADMIN, "pct": 50},
                           {"name": "B", "wallet": ADMIN.lower(), "pct": 50}], 10)
    with pytest.raises(captable.CapTableError, match="0 shares"):
        captable.allocate([{"name": "A", "wallet": ADMIN, "pct": 99.5}, {"name": "B", "wallet": USER, "pct": 0.5}], 10)


# ================================================================== SIWE
def siwe_message(address: str, nonce: str, domain: str = "eth.blockid.au", chain_id: int = 262626,
                 issued: datetime | None = None, expires: datetime | None = None) -> str:
    issued = issued or datetime.now(timezone.utc)
    lines = [f"{domain} wants you to sign in with your Ethereum account:", address, "",
             "Sign in to BlockID Issuance Studio.", "", f"URI: https://{domain}", "Version: 1",
             f"Chain ID: {chain_id}", f"Nonce: {nonce}", f"Issued At: {issued.isoformat().replace('+00:00', 'Z')}"]
    if expires:
        lines.append(f"Expiration Time: {expires.isoformat().replace('+00:00', 'Z')}")
    return "\n".join(lines)


def sign(msg: str, key: str) -> str:
    return "0x" + Account.sign_message(encode_defunct(text=msg), private_key=key).signature.hex().removeprefix("0x")


ALLOWED = auth.allowed_domains("https://eth.blockid.au")


def test_siwe_verify_ok_and_localhost():
    m = siwe_message(USER, "abc12345")
    out = auth.verify_siwe(m, sign(m, USER_KEY), ALLOWED)
    assert out.address == USER and out.nonce == "abc12345" and out.chain_id == 262626
    m2 = siwe_message(USER, "abc12345", domain="localhost:5173", chain_id=560048)
    with pytest.raises(auth.AuthError, match="domain"):  # localhost only with STUDIO_DEV=1
        auth.verify_siwe(m2, sign(m2, USER_KEY), ALLOWED)
    assert auth.verify_siwe(m2, sign(m2, USER_KEY), ALLOWED, dev=True).chain_id == 560048


@pytest.mark.parametrize("kw,err", [
    ({"domain": "evil.example"}, "domain"),
    ({"chain_id": 1}, "chain id"),
    ({"expires": datetime.now(timezone.utc) - timedelta(minutes=1)}, "expired"),
])
def test_siwe_rejects_bad_fields(kw, err):
    m = siwe_message(USER, "abc12345", **kw)
    with pytest.raises(auth.AuthError, match=err):
        auth.verify_siwe(m, sign(m, USER_KEY), ALLOWED)


def test_siwe_rejects_wrong_signer_and_garbage():
    m = siwe_message(USER, "abc12345")
    with pytest.raises(auth.AuthError, match="does not match"):
        auth.verify_siwe(m, sign(m, ADMIN_KEY), ALLOWED)
    with pytest.raises(auth.AuthError):
        auth.verify_siwe(m, "0x1234", ALLOWED)
    with pytest.raises(auth.AuthError):
        auth.verify_siwe("hello", "0x", ALLOWED)


def test_password_hash_and_throttle():
    h = auth.hash_password("correct horse")
    assert auth.check_password("correct horse", h) and not auth.check_password("nope", h)
    t = auth.LoginThrottle(limit=5, window_s=900)
    for _ in range(4):
        t.fail("1.2.3.4")
    assert not t.blocked("1.2.3.4")
    t.fail("1.2.3.4")
    assert t.blocked("1.2.3.4") and not t.blocked("5.6.7.8")


# ================================================================== crawler + graph (offline)
def test_crawler_same_site_robots_and_ssrf():
    seen: list[str] = []
    res = site_intake.crawl(FAKE_SITE, transport=fake_site_transport(seen), host_ok=lambda h: h == "agritrace.example")
    urls = {p.url for p in res.pages}
    assert urls == {FAKE_SITE + "/", FAKE_SITE + "/about", FAKE_SITE + "/contact"}
    assert res.robots_blocked == 1  # /private/secret
    assert not any("elsewhere" in u or "logo.png" in u or "issuer" in u for u in seen)
    assert any("issuer" in e for e in res.errors)  # redirect to the internal host was refused
    text = " ".join(p.text for p in res.pages)
    assert "jane@agritrace.au" not in text and "481 993 178" not in text and "[email]" in text


def test_public_host_rejects_internal_addresses():
    assert not site_intake.public_host("127.0.0.1")
    assert not site_intake.public_host("localhost")
    assert not site_intake.public_host("issuer")  # docker service names do not resolve publicly
    with pytest.raises(site_intake.SiteError):
        site_intake.normalize_url("ftp://x.example")
    assert site_intake.normalize_url("canva.com") == "https://canva.com/"


def studio_deps(tmp_path) -> Deps:
    s = replace(get_settings(), data_dir=str(tmp_path), database_url="", svi_tier="cloud")
    store = EvidenceStore(tmp_path / "ev.sqlite")
    return Deps(llm=fake_llm(), audit=AuditLog(tmp_path / "audit.jsonl"), evidence=store, settings=s,
                brave=BraveSearch("k", store, max_rps=0, transport=fake_competitor_brave_transport()),
                fetcher=fake_competitor_fetch, site_transport=fake_site_transport(),
                host_check=lambda h: h.endswith(".example"))


def test_competitor_discovery_filters_and_funding_needs_quote(tmp_path):
    deps = studio_deps(tmp_path)
    profile = fake_llm().handlers[__import__("blockid_agents.schemas", fromlist=["x"]).StartupProfile]("", "")
    out = competitors.discover({"job_id": "v1", "url": FAKE_SITE, "profile": profile.model_dump()}, deps)
    comps = {c["name"]: c for c in out["competitors"]}
    assert set(comps) == {"TE-FOOD", "OpenSC"}  # self + hallucinated names dropped
    assert comps["TE-FOOD"]["raised_aud"] == 15_000_000  # US$10M, quote verified in fetched page
    assert comps["OpenSC"]["raised_aud"] is None  # invented claim (unfetched URL) dropped
    assert comps["TE-FOOD"]["sources"] >= 1
    assert out["profile"]["competitors"] == ["TE-FOOD", "OpenSC"]


def test_site_valuation_graph_progress_and_gate(tmp_path):
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    deps = studio_deps(tmp_path)
    prog = MemoryProgress()
    g = build_site_valuation(deps, InMemorySaver(), prog)
    cfg = {"configurable": {"thread_id": "v9"}}
    out = g.invoke({"job_id": "v9", "url": FAKE_SITE}, cfg)
    assert out["__interrupt__"][0].value["gate"] == "valuation"
    steps = prog.steps["v9"]
    assert list(steps) == ["read_site", "profile", "competitors", "market", "svi", "narrative"]
    assert all(v["status"] == "done" for v in steps.values())
    r = prog.results["v9"]
    assert r["counters"]["pages"] == 3 and r["counters"]["competitors"] == 2 and r["counters"]["sources"] > 0
    assert r["svi"]["narrative"] and r["svi"]["valuation_mid_aud"] > 0
    assert all("@" not in e["snippet"] for e in r["evidence"])
    llm_tiers = {t for t, _ in deps.llm.calls}
    assert llm_tiers == {"cloud"}

    final = g.invoke(Command(resume={"approved": True, "reviewer": "admin", "overrides": {"founder_quality": 90}}), cfg)
    assert final["status"] == "approved"
    assert final["svi"]["dimensions"]["founder_quality"]["score"] == 90
    assert final["svi"]["dimensions"]["founder_quality"]["basis"] == "human"


def quota_brave(deps, calls: list | None = None) -> BraveSearch:
    def handler(r):
        if calls is not None:
            calls.append(r.url.params.get("q"))
        return httpx.Response(200, json={"type": "search", "query": {}}, headers={"x-ratelimit-remaining": "1, 0"})
    return BraveSearch("k", deps.evidence, max_rps=0, transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("brave", ["quota", "none"])
def test_search_unavailable_falls_back_to_verified_model_suggestions(tmp_path, brave):
    from langgraph.checkpoint.memory import InMemorySaver

    deps = studio_deps(tmp_path)
    calls: list = []
    deps.brave = quota_brave(deps, calls) if brave == "quota" else None
    deps.search = SearchChain([("brave", deps.brave)]) if deps.brave else None
    prog = MemoryProgress()
    out = build_site_valuation(deps, InMemorySaver(), prog).invoke({"job_id": "vq", "url": FAKE_SITE},
                                                                   {"configurable": {"thread_id": "vq"}})
    assert out["__interrupt__"]
    r = prog.results["vq"]
    # OpenSC (homepage 404), ShoeCo (off-topic) and the startup itself are dropped
    assert [(c["name"], c["basis"]) for c in r["competitors"]] == [("TE-FOOD", "model_suggested_verified")]
    assert r["competitors"][0]["raised_aud"] == 15_000_000  # stated on the fetched homepage (quote verified)
    assert r["competitors"][0]["url"] == "https://te-food.example/"
    assert competitors.FALLBACK_WARNING in r["warnings"]
    assert any("market analysis cites only" in w for w in r["warnings"])
    assert r["counters"]["sources"] == 1 and r["counters"]["competitors"] == 1
    web = [e["url"] for e in r["evidence"] if e["kind"] == "web"]
    assert web == ["https://te-food.example/"]
    # market analysis ran on fetched pages only (own site + competitor homepage), every finding cites them
    cited = {u for f in r["market"]["key_findings"] for u in f["source_urls"]}
    assert r["market"] and cited and cited <= {e["url"] for e in r["evidence"]}
    assert competitors.FALLBACK_WARNING in prog.steps["vq"]["competitors"]["detail"]
    assert ("cloud", "RelevanceVerdicts") in deps.llm.calls  # ShoeCo failed the keyword check -> model judged it
    if brave == "quota":
        assert len(calls) == 1  # first refusal is cached: no further Brave calls in this run


def test_brave_refusals_fail_fast_and_are_cached(tmp_path):
    from blockid_agents.tools.brave import BraveUnavailable

    calls: list = []

    def handler(r):
        calls.append(1)
        return httpx.Response(429, json={"error": "rate"})
    b = BraveSearch("k", EvidenceStore(tmp_path / "e.sqlite"), max_rps=0, transport=httpx.MockTransport(handler))
    for q in ("a", "b", "c"):
        with pytest.raises(BraveUnavailable):
            b.search(q)
    assert len(calls) == 1 and not b.available
    b.unavailable_until = 0  # after the 10-minute window it is tried again
    with pytest.raises(BraveUnavailable, match="402"):
        b.http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(402)))
        b.search("d")


def test_site_valuation_step_failure_is_reported(tmp_path):
    from langgraph.checkpoint.memory import InMemorySaver

    deps = studio_deps(tmp_path)
    deps.host_check = lambda h: False  # nothing is public -> read_site fails
    prog = MemoryProgress()
    with pytest.raises(site_intake.SiteError):
        build_site_valuation(deps, InMemorySaver(), prog).invoke({"job_id": "vf", "url": FAKE_SITE},
                                                                  {"configurable": {"thread_id": "vf"}})
    assert prog.steps["vf"]["read_site"]["status"] == "failed"


# ================================================================== API flows (Postgres)
needs_db = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")


class FakeChain:
    def __init__(self):
        self.balances_by_token: dict[str, dict[str, int]] = {}
        self.caps: dict[str, int] = {}
        self.fail = False
        # what transfer_facts returns (test_transfer_rules.py changes it); all clear by default
        self.facts = {"balance_from": 10**9, "balance_to": 0, "from_verified": True, "to_verified": True,
                      "frozen_from": False, "frozen_to": False, "lockup_until": 0, "holders": 1, "max_holders": 0,
                      "now": 1_700_000_000}

    def transfer_facts(self, token, registry, frm, to):
        if self.fail:
            raise ConnectionError("rpc down")
        return dict(self.facts)

    def block_number(self) -> int:
        if self.fail:
            raise ConnectionError("rpc down")
        return 4242

    def balances(self, token, wallets):
        if self.fail:
            raise ConnectionError("rpc down")
        b = self.balances_by_token.get(token, {})
        return {w: b.get(w.lower(), 0) for w in wallets}

    def shareholders(self, token):
        """(maxShareholders, shareholderCount): cap from `caps` (default 0 = no limit), count = non-zero balances."""
        if self.fail:
            raise ConnectionError("rpc down")
        count = sum(1 for v in self.balances_by_token.get(token, {}).values() if v > 0)
        return self.caps.get(token, 0), count


@pytest.fixture
def studio_env(tmp_path):
    from fastapi.testclient import TestClient

    from blockid_agents.api import create_app
    from blockid_agents.jobs import JobQueue
    from blockid_agents.studio.db import Studio
    from blockid_agents.studio.runner import ValuationRunner
    from blockid_agents.studio.services import IssuerClient
    from blockid_agents.worker import make_checkpointer

    db = Studio(TEST_DB)
    db.exec("DROP SCHEMA IF EXISTS studio CASCADE")
    deps = studio_deps(tmp_path)
    s = replace(deps.settings, admin_wallets=(ADMIN.lower(),), admin_username="admin",
                admin_password_hash=auth.hash_password("admin"), session_secret="test-secret", valuations_per_day=2,
                open_issue=False,
                api_key="k")
    deps.settings = s
    calls: list[tuple[str, dict]] = []

    def issuer_handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["X-Internal-Token"] == "itok"
        if req.method == "GET":
            return httpx.Response(200, json={"ok": True, "issuer": {"address": "0x2567", "local_balance": "1",
                                                                     "hoodi_balance": "2"}})
        calls.append((req.url.path, json.loads(req.content)))
        return httpx.Response(202, json={"accepted": True})

    chain = FakeChain()
    runner = ValuationRunner(deps, make_checkpointer(deps), db)
    app = create_app(s, JobQueue(tmp_path / "jobs.sqlite"), studio=db, chain=chain,
                     issuer=IssuerClient("http://issuer", "itok", transport=httpx.MockTransport(issuer_handler)),
                     runner_factory=lambda: runner)

    def client() -> TestClient:
        return TestClient(app, base_url="https://testserver", headers={"Origin": "https://eth.blockid.au"})

    yield {"db": db, "client": client, "runner": runner, "calls": calls, "chain": chain}
    db.close()


def siwe_login(c, key: str, domain: str = "eth.blockid.au"):
    n = c.get("/v1/auth/nonce").json()["nonce"]
    m = siwe_message(Account.from_key(key).address, n, domain=domain)
    return c.post("/v1/auth/siwe", json={"message": m, "signature": sign(m, key)}), m


@needs_db
def test_auth_endpoints(studio_env):
    c = studio_env["client"]()
    assert c.get("/v1/auth/me").status_code == 401
    r, m = siwe_login(c, USER_KEY)
    assert r.status_code == 200 and r.json() == {"address": USER, "role": "user"}
    cookie = r.headers["set-cookie"].lower()
    assert cookie.startswith("__host-bid_session=") and "httponly" in cookie and "secure" in cookie
    assert "samesite=lax" in cookie and "path=/" in cookie and "domain" not in cookie
    assert c.get("/v1/auth/me").json()["address"] == USER
    assert c.get("/v1/admin/audit").status_code == 403
    # nonce is single-use
    replay = c.post("/v1/auth/siwe", json={"message": m, "signature": sign(m, USER_KEY)})
    assert replay.status_code == 401
    assert c.post("/v1/auth/logout").json() == {"ok": True}
    assert c.get("/v1/auth/me").status_code == 401

    a = studio_env["client"]()
    r, _ = siwe_login(a, ADMIN_KEY, domain="localhost:5173")
    assert r.status_code == 401  # STUDIO_DEV is off
    r, _ = siwe_login(a, ADMIN_KEY)
    assert r.json()["role"] == "admin"
    # CSRF: a session-carrying POST from another origin, or with no Origin at all, is refused
    assert a.post("/v1/admin/issuer-wallets", json={"address": USER, "label": "x"},
                  headers={"Origin": "https://evil.example"}).status_code == 403
    a.headers.pop("Origin")
    assert a.post("/v1/admin/issuer-wallets", json={"address": USER, "label": "x"}).status_code == 403
    assert a.post("/v1/admin/issuer-wallets", json={"address": USER, "label": "x"},
                  headers={"Referer": "https://eth.blockid.au/admin"}).status_code == 201
    a.headers["Origin"] = "https://eth.blockid.au"
    assert a.get("/v1/admin/audit").status_code == 200

    # password admin: must change first, then full access
    p = studio_env["client"]()
    assert p.post("/v1/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401
    r = p.post("/v1/auth/login", json={"username": "admin", "password": "admin"})
    assert r.json() == {"role": "admin", "must_change": True}
    assert p.get("/v1/admin/audit").status_code == 403
    assert p.post("/v1/auth/change-password", json={"current": "admin", "new": "short"}).status_code == 422
    r = p.post("/v1/auth/change-password", json={"current": "admin", "new": "a-long-new-password"})
    assert r.json() == {"ok": True}
    assert p.get("/v1/auth/me").json()["must_change"] is False
    assert p.get("/v1/admin/audit").status_code == 200
    assert p.post("/v1/auth/login", json={"username": "admin", "password": "a-long-new-password"}).status_code == 200


@needs_db
def test_login_lockout(studio_env):
    c = studio_env["client"]()
    h = {"X-Real-IP": "9.9.9.9"}
    for _ in range(5):
        assert c.post("/v1/auth/login", json={"username": "admin", "password": "x"}, headers=h).status_code == 401
    assert c.post("/v1/auth/login", json={"username": "admin", "password": "admin"}, headers=h).status_code == 429
    assert c.post("/v1/auth/login", json={"username": "admin", "password": "admin"},
                  headers={"X-Real-IP": "8.8.8.8"}).status_code == 200


@needs_db
def test_full_studio_flow(studio_env):
    db, runner, calls, chain = studio_env["db"], studio_env["runner"], studio_env["calls"], studio_env["chain"]
    u, a = studio_env["client"](), studio_env["client"]()
    siwe_login(u, USER_KEY)
    siwe_login(a, ADMIN_KEY)

    # ---- valuation
    assert u.post("/v1/studio/valuations", json={"url": "http://127.0.0.1/"}).status_code == 422
    vid = u.post("/v1/studio/valuations", json={"url": "agritrace.example"}).json()["id"]
    v = u.get(f"/v1/studio/valuations/{vid}").json()
    assert v["status"] == "queued" and [s["key"] for s in v["steps"]] == ["read_site", "profile", "competitors",
                                                                          "market", "svi", "narrative"]
    assert runner.drain() == 1
    v = u.get(f"/v1/studio/valuations/{vid}").json()
    assert v["status"] == "waiting_approval", v["error"]
    assert all(s["status"] == "done" and s["at"] for s in v["steps"])
    assert v["counters"]["pages"] == 3 and v["counters"]["competitors"] == 2
    assert {c["name"] for c in v["competitors"]} == {"TE-FOOD", "OpenSC"}
    assert set(v["svi"]) >= {"index", "band", "dimensions", "weights", "valuation_low_aud", "valuation_mid_aud",
                             "valuation_high_aud", "method", "narrative"}
    ev = u.get(f"/v1/studio/valuations/{vid}/evidence").json()
    assert ev and set(ev[0]) >= {"url", "title", "snippet", "retrieved_at"}
    # rate limit (2/day in this fixture)
    u.post("/v1/studio/valuations", json={"url": "agritrace.example"})
    assert u.post("/v1/studio/valuations", json={"url": "agritrace.example"}).status_code == 429
    # other users cannot read it
    o = studio_env["client"]()
    siwe_login(o, "0x" + "c3" * 32)
    assert o.get(f"/v1/studio/valuations/{vid}").status_code == 403

    # ---- decision (admin only)
    assert u.post(f"/v1/studio/valuations/{vid}/decision", json={"approved": True}).status_code == 403
    assert a.post(f"/v1/studio/valuations/{vid}/decision",
                  json={"approved": True, "overrides": {"revenue_performance": 50}}).status_code == 422
    v = a.post(f"/v1/studio/valuations/{vid}/decision",
               json={"approved": True, "overrides": {"founder_quality": 88}}).json()
    assert v["status"] == "approved" and v["svi"]["dimensions"]["founder_quality"]["score"] == 88
    assert a.get("/v1/admin/approvals").json()["valuations"] == []
    mid = v["svi"]["valuation_mid_aud"]

    # ---- ticker + company
    cands = u.get("/v1/studio/tickers/suggest", params={"name": "AgriTrace Pty Ltd"}).json()["candidates"]
    assert len(cands) == 3 and cands[0]["available"]
    tk = cands[0]["ticker"]
    holders = [{"name": "Founder A", "wallet": USER, "pct": 60}, {"name": "Founder B", "wallet": ADMIN, "pct": 40}]
    bad = u.post("/v1/studio/companies", json={"valuation_id": vid, "name": "AgriTrace", "ticker": tk,
                                               "holders": [{**holders[0], "pct": 50}, holders[1]]})
    assert bad.status_code == 422 and "100" in bad.json()["detail"]
    r = u.post("/v1/studio/companies", json={"valuation_id": vid, "name": "AgriTrace", "ticker": tk.lower(),
                                             "holders": holders})
    assert r.status_code == 201, r.text
    co = r.json()
    assert co["status"] == "draft" and co["total_shares"] == round(mid) and co["ticker"] == tk
    assert sum(h["shares"] for h in co["holders"]) == co["total_shares"]
    assert u.post("/v1/studio/companies", json={"valuation_id": vid, "name": "X", "ticker": "XYZ",
                                                "holders": holders}).status_code == 409
    cid = co["id"]
    assert u.post(f"/v1/studio/companies/{cid}/submit").status_code == 403  # not an issuer wallet yet
    assert a.post("/v1/admin/issuer-wallets", json={"address": USER, "label": "founder"}).status_code == 201
    assert u.post(f"/v1/studio/companies/{cid}/submit").json()["status"] == "pending_issue"
    assert [c["id"] for c in a.get("/v1/admin/approvals").json()["companies"]] == [cid]

    # ---- issuance (issuer simulated)
    assert u.post(f"/v1/admin/companies/{cid}/approve-issue").status_code == 403
    r = a.post(f"/v1/admin/companies/{cid}/approve-issue")
    assert r.status_code == 202 and r.json()["status"] == "issuing"
    assert calls[-1] == ("/issue", {"company_id": cid})
    token = "0x" + "7" * 40
    db.exec("UPDATE studio.companies SET status='issued', local_token=%s, local_registry=%s, local_distributor=%s, "
            "local_block=10 WHERE id=%s", (token, "0x" + "8" * 40, "0x" + "9" * 40, cid))
    db.exec("INSERT INTO studio.marks(company_id,at,valuation_aud,mark_aud,source) VALUES (%s, now() - interval "
            "'40 days', %s, 1, 'issuance')", (cid, mid))
    db.exec("INSERT INTO studio.events(company_id,kind,chain,tx_hash,data) VALUES (%s,'issued','blockid','0xabc',%s)",
            (cid, json.dumps({"wallet": USER, "name": "Founder A", "shares": 5})))
    shares = {h["wallet"].lower(): h["shares"] for h in co["holders"]}
    chain.balances_by_token[token] = shares

    lst = u.get("/v1/companies").json()
    assert [x["ticker"] for x in lst] == [tk] and lst[0]["mark_aud"] == 1 and len(lst[0]["spark_30d"]) == 30
    d = u.get(f"/v1/companies/{tk}").json()
    assert d["cap_table_source"] == "chain" and d["cap_table"][0]["wallet"] == USER
    assert d["local"]["token"] == token and d["local"]["chain_id"] == 262626 and d["events"][0]["kind"] == "issued"
    chain.fail = True
    assert u.get(f"/v1/companies/{tk}").json()["cap_table_source"] == "db"
    chain.fail = False

    # ---- anchor + revalue
    d = u.get(f"/v1/companies/{tk}").json()
    assert d["sync"]["blockid"] == "done" and d["sync"]["hoodi"] == "pending" and d["sync"]["hsk"] == "pending"
    assert d["hsk"]["chain_id"] == 133 and d["hsk"]["token"] is None and "valuation_report_hash" in d
    assert [e["kind"] for e in d["events"]][-2:] == ["issue_approved", "submitted"]
    # issuer reports Hoodi done, HSK failed -> partially anchored; admin re-sync runs only HSK
    db.exec("UPDATE studio.companies SET status='partially_anchored', hoodi_token=%s, hoodi_anchor_tx='0xdd', "
            "sync=%s WHERE id=%s", ("0x" + "5" * 40, json.dumps({"blockid": "done", "hoodi": "done", "hsk": "failed",
                                                                 "errors": {"hsk": "low balance"}}), cid))
    assert cid in [c["id"] for c in a.get("/v1/admin/approvals").json()["companies"]]
    assert a.get("/v1/admin/companies").json()[0]["sync"]["errors"] == {"hsk": "low balance"}
    assert a.post(f"/v1/admin/companies/{cid}/approve-anchor").json()["status"] == "anchoring"
    assert calls[-1] == ("/anchor", {"company_id": cid})
    assert u.get(f"/v1/companies/{tk}").json()["events"][0]["data"]["chains"] == ["hsk"]
    db.exec("UPDATE studio.companies SET status='anchored', hsk_token=%s, hsk_anchor_tx='0xee', "
            "sync=%s WHERE id=%s", ("0x" + "4" * 40, json.dumps({"blockid": "done", "hoodi": "done", "hsk": "done"}), cid))
    assert a.post(f"/v1/admin/companies/{cid}/approve-anchor").status_code == 409  # nothing left to sync
    db.exec("UPDATE studio.companies SET status='anchored', hoodi_token=%s, hoodi_anchor_tx='0xdef' WHERE id=%s",
            ("0x" + "6" * 40, cid))
    r = a.post(f"/v1/admin/companies/{cid}/revalue", json={"valuation_aud": mid * 1.5, "note": "Q3 review"}).json()
    assert r["mark_aud"] == pytest.approx(1.5, rel=1e-3) and r["issuer"] == "queued"
    assert calls[-1] == ("/revalue", {"company_id": cid})
    item = u.get("/v1/companies").json()[0]
    assert item["change_30d"] == pytest.approx(50, abs=0.1) and item["anchored"] is True

    # ---- mint + dividend
    other = Account.from_key("0x" + "d4" * 32).address
    m = u.post(f"/v1/companies/{tk}/mints", json={"to_wallet": other, "holder_name": "Angel", "shares": 1000,
                                                  "reason": "seed"})
    assert m.status_code == 201 and m.json()["status"] == "pending"
    r = o.post(f"/v1/companies/{tk}/mints", json={"to_wallet": other, "holder_name": "x", "shares": 1})
    assert r.status_code == 403
    assert a.post(f"/v1/admin/mints/{m.json()['id']}/approve").status_code == 202
    assert calls[-1] == ("/mint", {"mint_id": m.json()["id"]})
    assert a.post(f"/v1/admin/mints/{m.json()['id']}/approve").status_code == 409
    dv = u.post(f"/v1/companies/{tk}/dividends", json={"total_maud": 1000})
    assert dv.status_code == 201, dv.text
    dv = dv.json()
    assert dv["total_units"] <= 1_000_000_000 and dv["merkle_root"].startswith("0x") and dv["holders"] == 2
    assert a.get("/v1/admin/approvals").json()["dividends"][0]["id"] == dv["id"]
    assert a.post(f"/v1/admin/dividends/{dv['id']}/approve").status_code == 202
    assert calls[-1] == ("/dividend", {"dividend_id": dv["id"]})
    db.exec("UPDATE studio.dividends SET status='paid' WHERE id=%s", (dv["id"],))

    # ---- stats, wallets, audit
    st = u.get("/v1/platform/stats").json()
    k = st["kpis"]
    assert k["companies"] == 1 and k["tokens"] == 3 and k["anchored"] == 1 and k["anchored_total"] == 1
    assert k["tx_value_aud"] == pytest.approx(co["total_shares"] + dv["total_units"] / 1e6, rel=1e-6)
    assert len(st["series"]["days"]) == 365 and st["series"]["companies"][-1] == 1
    assert st["series"]["value_aud"][-1] == pytest.approx(mid * 1.5) and st["series"]["value_aud"][0] == 0
    assert st["block"] == 4242 and st["movers"][0]["ticker"] == tk and sum(st["grades"].values()) == 1
    assert {x["kind"] for x in st["activity"]} >= {"issued", "revalued", "mint_requested"}
    w = a.get("/v1/admin/wallets").json()
    assert w["admins"] == [ADMIN] and w["issuer"]["address"] == "0x2567"
    actions = {x["action"] for x in a.get("/v1/admin/audit").json()}
    assert {"valuation_approved", "issuer_wallet_granted", "approve_issue", "approve_anchor", "company_revalued",
            "mint_approved", "dividend_approved", "company_submitted"} <= actions
    assert a.post(f"/v1/admin/issuer-wallets/{USER}/revoke").json()["status"] == "revoked"
    # the creator is also seeded as the company's 'owner' admin (company_admins.py); once that is revoked too,
    # the creator without an active issuer wallet can no longer request mints / dividends
    assert db.one("SELECT role FROM studio.company_admins WHERE company_id=%s AND address=%s", (cid, USER))["role"] \
        == "owner"
    db.exec("UPDATE studio.company_admins SET status='revoked' WHERE company_id=%s", (cid,))
    assert u.post(f"/v1/companies/{tk}/mints", json={"to_wallet": other, "holder_name": "A", "shares": 1}
                  ).status_code == 403
    assert u.post(f"/v1/companies/{tk}/dividends", json={"total_maud": 5}).status_code == 403
    # NaN / Infinity are rejected
    nan = a.post(f"/v1/admin/companies/{cid}/revalue", content='{"valuation_aud": NaN}',
                 headers={"content-type": "application/json"})
    assert nan.status_code == 422
    # stats activity only shows on-chain companies
    did = db.one("INSERT INTO studio.companies(ticker,name,valuation_aud,total_shares,status) "
                 "VALUES ('DRF','Draft',1,1,'draft') RETURNING id")["id"]
    db.exec("INSERT INTO studio.events(company_id,kind) VALUES (%s,'rejected')", (did,))
    assert "DRF" not in {x["ticker"] for x in u.get("/v1/platform/stats").json()["activity"]}


@needs_db
def test_issuer_down_reverts_status(studio_env):
    from blockid_agents.studio.services import IssuerClient

    db = studio_env["db"]
    a = studio_env["client"]()
    siwe_login(a, ADMIN_KEY)
    db.exec("INSERT INTO studio.valuations(id,url,status) VALUES ('vx','https://x.example','approved')")
    cid = db.one("INSERT INTO studio.companies(ticker,name,valuation_aud,total_shares,status,valuation_id) "
                 "VALUES ('XXA','X',100,100,'pending_issue','vx') RETURNING id")["id"]
    a.app.state.studio.issuer = IssuerClient("http://issuer", "t", transport=httpx.MockTransport(
        lambda r: httpx.Response(503, text="down")))
    assert a.post(f"/v1/admin/companies/{cid}/approve-issue").status_code == 502
    row = db.one("SELECT status, error FROM studio.companies WHERE id=%s", (cid,))
    assert row["status"] == "pending_issue" and "503" in row["error"]


@needs_db
def test_valuation_limits_are_global_and_atomic(studio_env):
    db = studio_env["db"]
    u, a = studio_env["client"](), studio_env["client"]()
    siwe_login(u, USER_KEY)
    siwe_login(a, ADMIN_KEY)
    for _ in range(5):  # admins skip the per-wallet/daily caps but not the queue-depth cap
        assert a.post("/v1/studio/valuations", json={"url": "agritrace.example"}).status_code == 202
    r = a.post("/v1/studio/valuations", json={"url": "agritrace.example"})
    assert r.status_code == 429 and "busy" in r.json()["detail"]
    db.exec("UPDATE studio.valuations SET status='approved'")
    db.exec("INSERT INTO studio.valuations(id,url,requested_by,status) "
            "SELECT 'g' || i, 'https://x.example', 'someone', 'approved' FROM generate_series(1, 55) i")
    r = u.post("/v1/studio/valuations", json={"url": "agritrace.example"})
    assert r.status_code == 429 and "daily" in r.json()["detail"]


# ================================================================== self-reported founder metrics
SELF_REPORTED = {"revenue_ttm_aud": 30_000_000, "revenue_growth_yoy_pct": 45, "runway_months": 30,
                 "customers": 1200, "employees": 250}


def _run_site(tmp_path, vid, self_reported=None):
    from langgraph.checkpoint.memory import InMemorySaver

    deps = studio_deps(tmp_path / vid)
    prog = MemoryProgress()
    g = build_site_valuation(deps, InMemorySaver(), prog)
    cfg = {"configurable": {"thread_id": vid}}
    g.invoke({"job_id": vid, "url": FAKE_SITE, "self_reported": self_reported}, cfg)
    return g, cfg, prog.results[vid]


def test_self_reported_metrics_change_svi_and_are_labelled(tmp_path):
    from langgraph.types import Command

    from blockid_agents.graph import SELF_REPORTED_WARNING

    _, _, base = _run_site(tmp_path, "vb")
    g, cfg, r = _run_site(tmp_path, "vs", SELF_REPORTED)
    bd, d = base["svi"]["dimensions"], r["svi"]["dimensions"]
    assert bd["revenue_performance"]["basis"] == "computed" and bd["growth_capability"]["basis"] == "computed"
    assert base["self_reported"] is None and SELF_REPORTED_WARNING not in base["warnings"]

    assert r["self_reported"] == SELF_REPORTED
    assert r["warnings"][0] == SELF_REPORTED_WARNING
    assert r["profile"]["metrics"]["revenue_ttm_aud"] == 30_000_000
    assert r["profile"]["metrics"]["paying_customers"] == 1200
    assert r["profile"]["metrics"]["gross_margin_pct"] == 72  # not supplied -> website value kept
    for k in ("revenue_performance", "growth_capability"):
        assert d[k]["basis"] == "self_reported" and "self-reported" in d[k]["rationale"]
    assert "revenue_ttm_aud" in d["revenue_performance"]["rationale"]
    assert d["revenue_performance"]["score"] > bd["revenue_performance"]["score"]
    assert d["growth_capability"]["score"] != bd["growth_capability"]["score"]
    assert d["founder_quality"]["basis"] == "ai_suggested"
    assert r["svi"]["index"] != base["svi"]["index"]
    assert r["svi"]["valuation_mid_aud"] > base["svi"]["valuation_mid_aud"]  # revenue x cited multiple
    assert r["svi"]["method"].startswith("self-reported revenue multiple")

    final = g.invoke(Command(resume={"approved": True, "reviewer": "admin"}), cfg)
    assert final["svi"]["dimensions"]["revenue_performance"]["basis"] == "self_reported"
    assert final["svi"]["dimensions"]["founder_quality"]["basis"] == "human"


def test_self_reported_margin_only_marks_revenue_dimension():
    from blockid_agents.schemas import StartupProfile, self_reported_metric_fields
    from blockid_agents.tools import svi

    p = StartupProfile(company_name="X", sector="s", description="d", stage="seed")
    used = self_reported_metric_fields({"gross_margin_pct": 80, "employees": 12, "customers": None})
    assert used == ["gross_margin_pct"]
    assert svi.revenue_performance(p, used).basis == "self_reported"
    assert svi.growth_capability(p, used).basis == "computed"
    assert svi.revenue_performance(p).basis == "computed"


@pytest.mark.parametrize("bad", [
    {"revenue_ttm_aud": float("nan")}, {"revenue_ttm_aud": float("inf")}, {"revenue_ttm_aud": -1},
    {"revenue_ttm_aud": 1e13}, {"gross_margin_pct": 101}, {"revenue_growth_yoy_pct": -101},
    {"runway_months": 601}, {"customers": -3}, {"customers": 1.5}, {"employees": "many"}, {"ebitda": 5},
])
def test_self_reported_metrics_validation(bad):
    from pydantic import ValidationError

    from blockid_agents.schemas import SelfReportedMetrics

    with pytest.raises(ValidationError):
        SelfReportedMetrics.model_validate(bad)


@needs_db
def test_self_reported_valuation_api(studio_env):
    db, runner = studio_env["db"], studio_env["runner"]
    db.apply_schema()  # the ALTER ... ADD COLUMN IF NOT EXISTS is idempotent
    u = studio_env["client"]()
    siwe_login(u, USER_KEY)
    for bad in ('{"url": "agritrace.example", "metrics": {"revenue_ttm_aud": NaN}}',
                '{"url": "agritrace.example", "metrics": {"gross_margin_pct": 250}}',
                '{"url": "agritrace.example", "metrics": {"secret": 1}}'):
        r = u.post("/v1/studio/valuations", content=bad, headers={"Content-Type": "application/json"})
        assert r.status_code == 422, bad
    plain = u.post("/v1/studio/valuations", json={"url": "agritrace.example", "metrics": {}}).json()["id"]
    assert db.get_valuation(plain)["self_reported"] is None
    vid = u.post("/v1/studio/valuations", json={"url": "agritrace.example",
                                                 "metrics": {**SELF_REPORTED, "gross_margin_pct": None}}).json()["id"]
    v = u.get(f"/v1/studio/valuations/{vid}").json()
    assert v["self_reported"] == SELF_REPORTED
    assert runner.drain() == 2
    v = u.get(f"/v1/studio/valuations/{vid}").json()
    assert v["status"] == "waiting_approval", v["error"]
    assert v["self_reported"] == SELF_REPORTED
    assert v["warnings"][0] == "Includes self-reported figures (not independently verified)"
    assert v["svi"]["dimensions"]["revenue_performance"]["basis"] == "self_reported"
    assert v["svi"]["dimensions"]["growth_capability"]["basis"] == "self_reported"
    p = u.get(f"/v1/studio/valuations/{plain}").json()
    assert p["self_reported"] is None and p["svi"]["dimensions"]["revenue_performance"]["basis"] == "computed"
    assert p["svi"]["index"] != v["svi"]["index"]


# ================================================================== CSRF + RPC proxy (no DB needed)
def _bare_app(tmp_path, rpc_handler=None):
    from fastapi.testclient import TestClient

    from blockid_agents.api import create_app
    from blockid_agents.jobs import JobQueue

    s = replace(get_settings(), data_dir=str(tmp_path), database_url="", api_key="k", issuer_internal_token="",
                local_rpc_url="http://rpc.test")
    app = create_app(s, JobQueue(tmp_path / "jobs.sqlite"))
    if rpc_handler:
        app.state.studio.rpc_transport = httpx.MockTransport(rpc_handler)
    return app, TestClient(app, base_url="https://testserver")


def test_csrf_middleware_and_docs_hidden(tmp_path):
    app, c = _bare_app(tmp_path)
    assert c.post("/v1/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.post("/v1/auth/logout", headers={"Origin": "null"}).status_code == 403
    assert c.post("/v1/auth/logout", headers={"Referer": "https://evil.example/x"}).status_code == 403
    assert c.post("/v1/auth/logout", headers={"Origin": "http://localhost:5173"}).status_code == 403  # dev only
    assert c.post("/v1/auth/logout", headers={"Origin": "https://eth.blockid.au"}).status_code == 503  # reached route
    c.cookies.set("__Host-bid_session", "x")
    assert c.post("/v1/auth/logout").status_code == 403  # session cookie but no Origin/Referer
    assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404


def test_rpc_proxy_policy(tmp_path):
    import json as _json

    seen: list = []

    def upstream(req: httpx.Request) -> httpx.Response:
        body = _json.loads(req.content)
        seen.append(body)
        items = body if isinstance(body, list) else [body]
        out = [{"jsonrpc": "2.0", "id": x.get("id"), "result": "0x1"} for x in items]
        return httpx.Response(200, json=out if isinstance(body, list) else out[0])

    _, c = _bare_app(tmp_path, upstream)
    ok = c.post("/v1/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []})
    assert ok.json() == {"jsonrpc": "2.0", "id": 1, "result": "0x1"}
    for m in ("eth_sendTransaction", "eth_sign", "eth_signTypedData_v4", "eth_accounts", "debug_traceTransaction",
              "txpool_content", "personal_unlockAccount", "admin_peers", "miner_start", "evm_mine"):
        r = c.post("/v1/rpc", json={"jsonrpc": "2.0", "id": 2, "method": m, "params": []})
        assert r.json()["error"]["code"] == -32601, m
    n = len(seen)
    batch = c.post("/v1/rpc", json=[{"jsonrpc": "2.0", "id": 1, "method": "eth_chainId"},
                                    {"jsonrpc": "2.0", "id": 2, "method": "debug_traceBlock"},
                                    {"jsonrpc": "2.0", "id": 3, "method": "eth_sendRawTransaction", "params": ["0x"]}])
    assert sorted(x["id"] for x in batch.json()) == [1, 2, 3]
    assert [x["method"] for x in seen[n]] == ["eth_chainId", "eth_sendRawTransaction"]  # denied one never forwarded
    assert c.post("/v1/rpc", json=[{"jsonrpc": "2.0", "id": i, "method": "eth_chainId"} for i in range(21)]
                  ).status_code == 400
    assert c.post("/v1/rpc", content=b"x" * (256 * 1024 + 1)).status_code == 413
    assert c.post("/v1/rpc", content=b"{not json").status_code == 400
    # no Origin needed (wallets / scripts), cross-origin allowed: it carries no session
    assert c.post("/v1/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "net_version"},
                  headers={"Origin": "chrome-extension://abc"}).status_code == 200

    _, down = _bare_app(tmp_path, lambda r: (_ for _ in ()).throw(httpx.ConnectError("down")))
    assert down.post("/v1/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "eth_chainId"}).status_code == 502


# ================================================================== SSRF-safe fetching
@pytest.fixture
def fake_dns(monkeypatch):
    import socket

    table = {"public.example": "93.184.216.34", "rebind.example": "10.0.0.5", "meta.example": "169.254.169.254",
             "v6.example": "::ffff:127.0.0.1"}

    def gai(host, *a, **k):
        if host not in table:
            raise socket.gaierror("nx")
        ip = table[host]
        fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(fam, socket.SOCK_STREAM, 6, "", (ip, 0))]
    monkeypatch.setattr(socket, "getaddrinfo", gai)
    return table


def test_safefetch_pins_ip_and_rechecks_every_redirect(fake_dns):
    from blockid_agents.tools.brave import fetch_page
    from blockid_agents.tools.safefetch import FetchError, SafeFetcher

    seen: list = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.url.host, req.headers["host"], req.extensions.get("sni_hostname")))
        if req.url.path == "/to-internal":
            return httpx.Response(302, headers={"location": "http://issuer:8090/health"})
        for p, target in (("/to-rebind", "https://rebind.example/"), ("/to-meta", "https://meta.example/"),
                          ("/to-v6", "https://v6.example/"), ("/to-ip", "http://169.254.169.254/")):
            if req.url.path == p:
                return httpx.Response(302, headers={"location": target})
        if req.url.path == "/big":
            return httpx.Response(200, content=b"a" * 3_000_000, headers={"content-type": "text/plain"})
        return httpx.Response(200, text="<p>hello</p>", headers={"content-type": "text/html"})

    t = httpx.MockTransport(handler)
    assert fetch_page("https://public.example/", transport=t) == "hello"
    assert seen[-1] == ("93.184.216.34", "public.example", "public.example")  # pinned IP, Host + SNI kept
    for path in ("/to-internal", "/to-rebind", "/to-meta", "/to-v6", "/to-ip"):
        with pytest.raises(FetchError):
            fetch_page("https://public.example" + path, transport=t)
    assert all(h == "93.184.216.34" for h, _, _ in seen)  # never connected anywhere else
    with SafeFetcher(t) as f:
        assert len(f.get("https://public.example/big")[1].content) == 2_000_000
    with pytest.raises(FetchError, match="deadline"), SafeFetcher(t, page_deadline=0) as f:
        f.get("https://public.example/")
    with pytest.raises(FetchError, match="HTTP 404"):
        fetch_page("https://public.example/x", transport=httpx.MockTransport(lambda r: httpx.Response(404)))
