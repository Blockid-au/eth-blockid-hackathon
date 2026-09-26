import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from blockid_agents.agents import dividend, research, valuation
from blockid_agents.audit import AuditLog
from blockid_agents.config import get_settings
from blockid_agents.deps import Deps
from blockid_agents.fakes import (DEMO_CAP_TABLE, DEMO_DATAROOM, DEMO_DEPLOYMENT, DEMO_INPUTS, DEMO_KYC,
                                  fake_brave_transport, fake_fetch, fake_forge_runner, fake_llm)
from blockid_agents.jobs import JobQueue
from blockid_agents.policy import PolicyViolation, guard
from blockid_agents.schemas import TokenParams
from blockid_agents.tools import chain, svi
from blockid_agents.tools.brave import BraveSearch, EvidenceStore, html_to_text, sanitize_query
from blockid_agents.tools.merkle import build_distribution, verify
from blockid_agents.worker import Worker, make_checkpointer

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def deps(tmp_path):
    s = replace(get_settings(), data_dir=str(tmp_path), contracts_dir=str(tmp_path / "contracts"), database_url="")
    store = EvidenceStore(tmp_path / "ev.sqlite")
    return Deps(
        llm=fake_llm(), audit=AuditLog(tmp_path / "audit.jsonl"), evidence=store, settings=s,
        brave=BraveSearch("k", store, max_rps=0, transport=fake_brave_transport()),
        forge_runner=fake_forge_runner, fetcher=fake_fetch,
    )


# ---------------------------------------------------------------- policy
def test_pii_agent_cannot_use_cloud():
    with pytest.raises(PolicyViolation):
        guard("intake", tier="cloud")


def test_forbidden_tools_for_everyone():
    for agent in ("intake", "research", "valuation", "contract_builder", "registry", "dividend"):
        for tool in ("sign_tx", "send_tx", "deploy_contract", "read_private_key"):
            with pytest.raises(PolicyViolation):
                guard(agent, tool=tool)


def test_research_cannot_touch_chain():
    with pytest.raises(PolicyViolation):
        guard("research", tool="build_unsigned_tx")


# ---------------------------------------------------------------- audit
def test_audit_chain_detects_tampering(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    for i in range(3):
        log.record("x", "act", i=i)
    assert log.verify()
    lines = (tmp_path / "a.jsonl").read_text().splitlines()
    entry = json.loads(lines[1])
    entry["data"]["i"] = 99
    lines[1] = json.dumps(entry)
    (tmp_path / "a.jsonl").write_text("\n".join(lines) + "\n")
    assert not log.verify()


# ---------------------------------------------------------------- merkle / dividend maths
def test_merkle_matches_solidity_fixture():
    fx = json.loads((ROOT / "contracts/test/fixtures/dividend_round.json").read_text())
    d = build_distribution({h["account"]: h["amount"] for h in fx["holders"]})
    assert d.root == fx["root"]
    for h in fx["holders"]:
        assert verify(d.root, h["account"], h["amount"], h["proof"])


def test_merkle_many_holders_all_verify():
    alloc = {f"0x{i:040x}": i * 7 + 1 for i in range(1, 38)}
    d = build_distribution(alloc)
    assert all(verify(d.root, a, c["amount"], c["proof"]) for a, c in d.claims.items())
    assert not verify(d.root, "0x" + "1" * 40, 8, d.claims["0x" + "0" * 39 + "1"]["proof"])


def test_pro_rata_rounds_down_and_keeps_remainder():
    alloc, rest = dividend.allocate({"0x" + "a" * 40: 1, "0x" + "b" * 40: 2}, 100)
    assert alloc == {"0x" + "a" * 40: 33, "0x" + "b" * 40: 66}
    assert rest == 1


# ---------------------------------------------------------------- SVI
def test_svi_is_deterministic_and_weighted(deps):
    from blockid_agents.fakes import fake_llm as f
    from blockid_agents.schemas import MarketAnalysis, QualitativeScores, StartupProfile

    llm = f()
    p = llm.handlers[StartupProfile]("", "")
    q = llm.handlers[QualitativeScores]("", "")
    m = MarketAnalysis(market_summary="x", revenue_multiple_median=6, confidence="medium")
    a, b = svi.score(p, q, m), svi.score(p, q, m)
    assert a.report_sha256 == b.report_sha256
    expected = sum(svi.WEIGHTS[k] * a.dimensions[k].score for k in svi.WEIGHTS)
    assert a.index == pytest.approx(expected, abs=0.01)
    assert a.valuation_low_aud < a.valuation_mid_aud < a.valuation_high_aud


def test_valuation_prompt_is_redacted_and_scores_marked_ai(deps, tmp_path):
    state = {"profile": fake_llm().handlers[__import__("blockid_agents.schemas", fromlist=["StartupProfile"]).StartupProfile]("", "").model_dump(), "market": None}
    out = valuation.run(state, deps)  # the fake LLM asserts no founder name reaches the prompt
    assert all(d["basis"] in ("ai_suggested", "computed") for d in out["svi"]["dimensions"].values())


# ---------------------------------------------------------------- Brave research
def test_sanitize_query_strips_pii():
    assert "@" not in sanitize_query("contact jane@agritrace.au +61 481 993 178 traceability")


def test_html_to_text_drops_scripts():
    assert html_to_text("<p>Hello</p><script>steal()</script><p>World</p>") == "Hello World"


def test_brave_search_uses_cache(tmp_path):
    calls = []

    def handler(req):
        calls.append(req.url)
        return httpx.Response(200, json={"web": {"results": [{"title": "t", "url": "https://a.b/c", "description": "d"}]}})

    b = BraveSearch("k", EvidenceStore(tmp_path / "e.sqlite"), max_rps=0, transport=httpx.MockTransport(handler))
    assert b.search("x")[0]["url"] == "https://a.b/c"
    b.search("x")
    assert len(calls) == 1


def test_research_drops_uncited_claims(deps):
    from blockid_agents.fakes import fake_llm as f
    from blockid_agents.schemas import StartupProfile

    state = {"job_id": "t1", "profile": f().handlers[StartupProfile]("", "").model_dump()}
    out = research.run(state, deps)
    claims = [x["claim"] for x in out["market"]["key_findings"]]
    assert out["evidence_count"] > 0
    assert not any("Invented" in c for c in claims)


# ---------------------------------------------------------------- chain encoding
def test_selector_known_value():
    assert chain.selector("transfer(address,uint256)").hex() == "a9059cbb"


@pytest.mark.skipif(shutil.which("cast") is None, reason="foundry cast not installed")
def test_encoding_matches_cast():
    args = ["0x1000000000000000000000000000000000000001", "600000", "0x" + "ab" * 32]
    ours = chain.encode_call("issue(address,uint256,bytes32)", *args)
    theirs = subprocess.run(["cast", "calldata", "issue(address,uint256,bytes32)", *args], capture_output=True, text=True).stdout.strip()
    assert ours == theirs


def test_token_params_validation():
    with pytest.raises(Exception):
        TokenParams(name="x", symbol="bad symbol", companyName="x", companyNumber="1", shareClass="ORD",
                    issuerSafe="0x1", transferAgent="0x2", kycAgent="0x3", lockupUntil=0, maxShareholders=1,
                    legalDocHash="0x00")


# ---------------------------------------------------------------- end-to-end workflow with human gates
def test_onboarding_and_dividend_end_to_end(deps, tmp_path):
    w = Worker(deps, JobQueue(tmp_path / "jobs.sqlite"), make_checkpointer(deps))
    q = w.queue
    wid = q.enqueue("onboarding", "onboarding", {"dataroom": DEMO_DATAROOM, "issuance_inputs": DEMO_INPUTS})
    w.drain()
    job = q.latest_for_thread(wid)
    assert job["status"] == "waiting_human" and job["gate"]["gate"] == "valuation"
    assert "dataroom" not in job["result"]  # never persisted in job results

    # a decision without a reviewer is refused before it reaches the graph; workflow stays paused
    bad = q.enqueue("resume", "onboarding", {"decision": {"approved": True}}, thread_id=wid)
    w.drain()
    assert q.get(bad)["status"] == "rejected_input"
    assert q.latest_for_thread(wid)["status"] == "waiting_human"

    q.enqueue("resume", "onboarding", {"decision": {"approved": True, "reviewer": "r1"}}, thread_id=wid)
    w.drain()
    job = q.latest_for_thread(wid)
    assert job["gate"]["gate"] == "contract"
    params = json.loads((Path(deps.settings.contracts_dir) / "deployments/params" / f"{wid}.json").read_text())
    assert params["maxShareholders"] == 50  # proprietary company default

    q.enqueue("resume", "onboarding", {"decision": {"approved": True, "reviewer": "r2", "deployment": DEMO_DEPLOYMENT,
                                                    "cap_table": DEMO_CAP_TABLE, "kyc": DEMO_KYC}}, thread_id=wid)
    w.drain()
    job = q.latest_for_thread(wid)
    assert job["status"] == "done"
    txs = job["result"]["safe_batch"]["transactions"]
    assert len(txs) == 3 + 3 + 1
    assert all(set(t) == {"to", "value", "data", "description"} for t in txs)
    assert deps.audit.verify()

    did = q.enqueue("dividend", "dividend", {"dividend": {
        "record_block": 1, "total_amount": 1000, "pay_token": "0x" + "4" * 40, "distributor": DEMO_DEPLOYMENT["distributor"],
        "balances": {e["wallet"]: e["shares"] for e in DEMO_CAP_TABLE}}})
    w.drain()
    q.enqueue("resume", "dividend", {"decision": {"approved": False, "reviewer": "board"}}, thread_id=did)
    w.drain()
    job = q.latest_for_thread(did)
    assert job["status"] == "done" and job["result"]["status"] == "rejected_at_dividend"
    assert "safe_batch" not in job["result"]


def test_blocked_contract_cannot_be_approved(deps, tmp_path):
    def failing_runner(cmd, cwd, env):
        return subprocess.CompletedProcess(cmd, 1, "FAIL", "")

    deps.forge_runner = failing_runner
    w = Worker(deps, JobQueue(tmp_path / "jobs.sqlite"), make_checkpointer(deps))
    q = w.queue
    wid = q.enqueue("onboarding", "onboarding", {"dataroom": DEMO_DATAROOM, "issuance_inputs": DEMO_INPUTS})
    w.drain()
    q.enqueue("resume", "onboarding", {"decision": {"approved": True, "reviewer": "r"}}, thread_id=wid)
    w.drain()
    q.enqueue("resume", "onboarding", {"decision": {"approved": True, "reviewer": "r", "deployment": DEMO_DEPLOYMENT,
                                                    "cap_table": DEMO_CAP_TABLE}}, thread_id=wid)
    w.drain()
    res = q.latest_for_thread(wid)["result"]
    assert res["status"] == "rejected_contract_checks_failed"
    assert "safe_batch" not in res


# ---------------------------------------------------------------- API
def test_api_requires_key_and_hides_dataroom(tmp_path):
    from fastapi.testclient import TestClient

    from blockid_agents.api import create_app

    s = replace(get_settings(), api_key="secret", data_dir=str(tmp_path))
    c = TestClient(create_app(s, JobQueue(tmp_path / "jobs.sqlite")))
    assert c.post("/v1/onboarding", json={"dataroom": {}, "issuance_inputs": {}}).status_code == 401
    r = c.post("/v1/onboarding", headers={"X-API-Key": "secret"}, json={"dataroom": {"a": "PII"}, "issuance_inputs": {}})
    wid = r.json()["workflow_id"]
    body = c.get(f"/v1/workflows/{wid}", headers={"X-API-Key": "secret"}).json()
    assert "payload" not in body
    assert c.post(f"/v1/workflows/{wid}/decision", headers={"X-API-Key": "secret"},
                  json={"decision": {"approved": True, "reviewer": "x"}}).status_code == 409


# ------------------------------------------------------------------ hosted LLM chain (Claude CLI -> DeepInfra)
from blockid_agents.llm import ClaudeCliLLM, FakeLLM, FallbackLLM, LLMError, TierRouter, build_llm  # noqa: E402
from blockid_agents.schemas import Narrative  # noqa: E402
from blockid_agents.tools.brave import BraveQuotaError  # noqa: E402


def _cli_runner(payload: dict, code: int = 0, seen: list | None = None):
    def run(cmd, **kw):
        if seen is not None:
            seen.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, code, stdout=json.dumps(payload), stderr="")
    return run


def test_claude_cli_returns_structured_output_with_no_tools():
    seen: list = []
    llm = ClaudeCliLLM({"cloud": "sonnet"}, cli_path="/bin/claude", runner=_cli_runner(
        {"is_error": False, "structured_output": {"summary": "ok", "strengths": [], "concerns": []}}, seen=seen))
    out = llm.complete_json("cloud", "sys", "user text", Narrative)
    cmd, kw = seen[0]
    assert out.summary == "ok"
    assert cmd[cmd.index("--tools") + 1] == "" and "--json-schema" in cmd and "--strict-mcp-config" in cmd
    assert kw["input"] == "user text"  # untrusted data goes via stdin, never argv


def test_claude_cli_error_raises():
    llm = ClaudeCliLLM({"cloud": "sonnet"}, cli_path="/bin/claude",
                       runner=_cli_runner({"is_error": True, "result": "rate limited"}, code=1))
    with pytest.raises(LLMError, match="rate limited"):
        llm.complete_json("cloud", "s", "u", Narrative)


def test_fallback_uses_next_backend_when_claude_fails():
    bad = ClaudeCliLLM({"cloud": "sonnet"}, cli_path="/bin/claude",
                       runner=_cli_runner({"is_error": True, "result": "Not logged in"}, code=1))
    good = FakeLLM({Narrative: lambda s, u: Narrative(summary="from deepinfra", strengths=[], concerns=[])})
    chain = FallbackLLM([("claude-cli", bad), ("deepinfra:qwen", good)])
    assert chain.complete_json("cloud", "s", "u", Narrative).summary == "from deepinfra"
    assert chain.used == [("deepinfra:qwen", "Narrative")]


def test_hosted_backend_keeps_local_tier_on_gateway():
    s = replace(get_settings(), llm_backend="hosted", deepinfra_api_key="k", claude_cli_enabled=False)
    llm = build_llm(s)
    assert isinstance(llm, TierRouter)
    assert type(llm.routes["local"]).__name__ == "GatewayLLM"  # PII never reaches a hosted provider
    assert [n for n, _ in llm.routes["cloud"].backends] == [f"deepinfra:{m}" for m in s.deepinfra_models]


def test_brave_quota_exhausted_raises_and_is_not_cached(tmp_path):
    t = httpx.MockTransport(lambda r: httpx.Response(
        200, json={"type": "search", "query": {}}, headers={"x-ratelimit-remaining": "1, 0"}))
    b = BraveSearch("k", EvidenceStore(tmp_path / "e.sqlite"), max_rps=0, transport=t)
    with pytest.raises(BraveQuotaError):
        b.search("agtech")
    with pytest.raises(BraveQuotaError):  # still an error (Brave marked unavailable), never a cached empty page
        b.search("agtech")


def test_brave_news_falls_back_to_web_when_not_in_plan(tmp_path):
    paths: list[str] = []

    def handler(r: httpx.Request) -> httpx.Response:
        paths.append(r.url.path)
        if "news" in r.url.path:
            return httpx.Response(400, json={"error": {"code": "OPTION_NOT_IN_PLAN"}})
        return httpx.Response(200, json={"web": {"results": [{"url": "https://a.example", "title": "A"}]}})

    b = BraveSearch("k", EvidenceStore(tmp_path / "e.sqlite"), max_rps=0, transport=httpx.MockTransport(handler))
    assert [x["url"] for x in b.search("agtech", news=True)] == ["https://a.example"]
    b.search("other", news=True)
    assert paths == ["/res/v1/news/search", "/res/v1/web/search", "/res/v1/web/search"]
