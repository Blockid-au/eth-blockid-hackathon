"""People Analyst (agents/people.py) offline: verification, privacy filters, redaction, score maths, caps, role
weights, per-agent LLM / search routing, SVI v4 weights + old-report verification, valuation blend."""
import json
from dataclasses import replace

import pytest

from conftest import v5_on

from blockid_agents.agents import people as pa
from blockid_agents.audit import AuditLog
from blockid_agents.config import get_settings
from blockid_agents.deps import Deps
from blockid_agents.fakes import FAKE_PEOPLE_PAGES, FakePeopleSearch, fake_llm, fake_people_fetch, fake_people_llm
from blockid_agents.llm import FakeLLM
from blockid_agents.policy import PolicyViolation, guard
from blockid_agents.schemas import MarketAnalysis, QualitativeScores, StartupProfile
from blockid_agents.studio import verify
from blockid_agents.tools import svi
from blockid_agents.tools.brave import EvidenceStore
from blockid_agents.tools.search import SearchChain

JANE = {"id": 1, "full_name": "Jane Nguyen", "role": "CEO", "kind": "founder",
        "headline": "Agri supply-chain founder", "full_time": True, "equity_pct": 60, "start_year": 2021,
        "urls": ["https://agritrace.example/team", "https://www.linkedin.com/in/jane"],
        "bio": "Based in Melbourne. MBA, University of Melbourne. enterprise sales. Call +61 481 993 178",
        "cv": None, "position": 0}
TOM = {"id": 2, "full_name": "Tom Lee", "role": "CTO", "kind": "cofounder", "urls": [], "position": 1}
TEAM = {"id": "t_test", "mode": "team", "name": "AgriTrace Pty Ltd", "website": "https://agritrace.example"}


def deps_for(tmp_path, llm=None, search=None, **settings) -> Deps:
    s = replace(get_settings(), data_dir=str(tmp_path), hr_tier="cloud", **settings)
    return Deps(llm=fake_llm(), audit=AuditLog(tmp_path / "audit.jsonl"), evidence=EvidenceStore(tmp_path / "e.sqlite"),
                settings=s, agent_llm={"people_analyst": llm or fake_people_llm()},
                agent_search={"people_analyst": SearchChain([("claude", search or FakePeopleSearch())])},
                fetcher=fake_people_fetch)


# ================================================================== privacy
def test_redaction_of_contact_details():
    t = pa.redact("mail jane@agritrace.au, call +61 481 993 178 or (02) 9876 5432; CTO 2016 - 2019; 12 000 000")
    assert "jane@" not in t and "481" not in t and "9876" not in t
    assert t.count("[email]") == 1 and t.count("[phone]") == 2
    assert "2016 - 2019" in t and "12 000 000" in t  # year ranges and amounts are not phone numbers
    qs = pa.person_queries({**JANE, "headline": "founder jane@x.com +61 481 993 178"}, "AgriTrace")
    assert qs and all("@" not in q and "481" not in q for q in qs) and len(qs) <= 3


@pytest.mark.parametrize("text", [
    "Nguyen is married with two children", "She was diagnosed with cancer in 2020", "a devout Catholic",
    "member of the Liberal Party", "lives at 12 Smith Street", "home address: 4 Rose Ave",
    "date of birth 1 May 1980", "aged 45", "his wife runs a bakery", "sexual orientation", "email jane@x.com",
    "mobile: 0481 993 178",
])
def test_sensitive_categories_detected(text):
    assert pa.is_sensitive(text)


@pytest.mark.parametrize("text", [
    "Founder of a health-tech startup", "worked on Wall Street for 10 years", "the parent company acquired it",
    "led the family office investment team", "CTO from 2016 to 2019", "raised A$12 million in 2021",
    "Temple University MBA",
])
def test_professional_text_not_flagged(text):
    assert not pa.is_sensitive(text)


def test_policy_people_analyst_is_read_only():
    guard("people_analyst", tool="web_search")
    guard("people_analyst", tool="fetch_url")
    guard("people_analyst", tier="cloud")
    for tool in ("sign_tx", "send_tx", "read_private_key", "build_unsigned_tx", "svi_score"):
        with pytest.raises(PolicyViolation):
            guard("people_analyst", tool=tool)


# ================================================================== the pipeline (fakes)
def test_team_analysis_verifies_facts_and_filters(tmp_path):
    search = FakePeopleSearch()
    deps = deps_for(tmp_path, search=search)
    steps = []
    res = pa.analyse(TEAM, [JANE, TOM], deps, progress=lambda *a: steps.append(a))
    jane, tom = res["people"]
    # verified: quote on the stored page + page names the person + (company or provided URL)
    assert [f["id"] for f in jane["facts"]] == ["p1f1"] and jane["facts"][0]["url"] == "https://agritrace.example/team"
    reasons = {u["text"]: u["reason"] for u in jane["unconfirmed"]}
    assert reasons["Raised A$50m"] == "quote not found on the page"
    assert reasons["Won a baking award"].startswith("page does not name the company")  # a namesake
    assert reasons["Spoke at a conference"] == "source not among the stored pages"
    assert not any("married" in json.dumps(c) for c in (jane, tom))  # sensitive fact dropped entirely
    assert res["counters"]["facts_dropped_sensitive"] >= 1
    # the team page Jane provided is also evidence for Tom (it names him)
    assert [f["id"] for f in tom["facts"]] == ["p2f1", "p2f2"]
    src = {s["id"]: s for s in res["sources"]}
    assert all(f["source_id"] in src and len(src[f["source_id"]]["sha256"]) == 64 for f in jane["facts"] + tom["facts"])
    # CV profile: every item cited or self-reported (verbatim in the bio); unsupported items -> unconfirmed
    prof = jane["profile"]
    assert prof["experience"][0]["source"]["type"] == "verified" and len(prof["experience"]) == 1  # Sequoia dropped
    assert prof["education"][0]["source"]["type"] == "self_reported"
    assert prof["location"]["text"] == "Melbourne, Australia"
    assert [g["group"] for g in prof["skills"]] == ["Commercial"]
    assert 0 < prof["completeness_pct"] <= 100
    # stored evidence is redacted (no email / phone), LinkedIn was not fetched
    stored = deps.evidence.for_subject("hr:t_test:1", limit=50)
    assert stored and all("@agritrace" not in t and "481 993" not in t for _, t in stored)
    assert any("linkedin" in n for n in jane["notes"])
    # search: <= 3 per person, the People Analyst's own provider chain, models logged per person
    assert res["counters"]["searches"] == len(search.queries) <= 6
    assert set(res["method"]["models"]) == {"person:1", "person:2", "team"}
    assert res["method"]["search_providers"] == ["claude"]
    assert res["counters"]["llm_calls"] == 3  # one per person + one team call
    assert [s[0] for s in steps][-1] == "done"
    # red flags: only those citing a verified fact
    assert [f["text"] for f in res["team"]["red_flags"]] == ["FarmLink was sold (verified fact)"]
    assert res["team"]["red_flag_penalty"] == 5.0


def test_search_budget_per_team(tmp_path):
    search = FakePeopleSearch()
    deps = deps_for(tmp_path, search=search)
    crew = [{"id": i, "full_name": f"Person Number{chr(64 + i)}", "role": "Engineer", "kind": "employee",
             "position": i} for i in range(1, 7)]
    rs = pa.Research(deps, "t_budget", lambda *a: None)
    rs.run_searches(crew, "AgriTrace", 3, 12)
    assert len(rs.searches) == 12 == len(search.queries)
    per = {}
    for s in rs.searches:
        per[s["person_id"]] = per.get(s["person_id"], 0) + 1
    assert set(per.values()) == {2}  # round-robin: everyone gets 2 before anyone gets a 3rd


def test_person_report_role_fit(tmp_path):
    deps = deps_for(tmp_path)
    target = {"type": "role", "company": "Acme", "title": "Head of Supply Chain", "description": "Lead ops",
              "requirements": ["agri-food supply chain expertise", "enterprise sales", "regulatory affairs"]}
    res = pa.analyse({"id": "t_p", "mode": "person", "name": "Jane Nguyen"}, [JANE], deps, target=target)
    assert res["team"] is None and res["mode"] == "person"
    card = res["people"][0]
    fit = card["fit"]
    assert fit["label"] == "role fit" and fit["target_type"] == "role"
    st = {r["requirement"]: r["status"] for r in fit["requirements"]}
    # matched with a verified fact / matched without any evidence -> unverified / missing
    assert st == {"agri-food supply chain expertise": "matched", "enterprise sales": "unverified",
                  "regulatory affairs": "missing"}
    assert fit["components"]["gaps"]["score"] == round(100 * (1 + 0.25 + 0) / 3, 1)
    assert fit["components"]["stage_scale_match"]["score"] == 50 and fit["components"]["stage_scale_match"]["capped"]
    assert card["contribution"] == round(0.5 * card["score"] + 0.5 * fit["score"], 1)
    assert res["counters"]["search_budget"] == 3


# ================================================================== score maths
def S(score, ids=(), sr=False):
    return pa.SubScore(score=score, fact_ids=list(ids), self_reported=sr)


def test_person_quality_weights_and_cap():
    ids = {"f1": "p1f1"}
    scores = pa.PersonScores(domain_fit=S(80, ["f1"]), track_record=S(90), leadership=S(70, sr=True),
                             functional_depth=S(60, ["f9"]), verifiability=S(85, sr=True), commitment=S(90, sr=True))
    q, subs = pa.person_quality(scores, ids, founder_info=True)
    assert subs["domain_fit"]["score"] == 80 and subs["domain_fit"]["fact_ids"] == ["p1f1"]
    assert subs["track_record"]["score"] == 50 and subs["track_record"]["capped"]  # no evidence -> cap 50
    assert subs["functional_depth"]["score"] == 50  # cites an unverified fact -> no evidence
    assert subs["leadership"]["score"] == 70 and subs["leadership"]["self_reported"]
    assert subs["verifiability"]["score"] == 50  # self-reported never proves verifiability
    assert q == round((25 * 80 + 25 * 50 + 15 * 70 + 15 * 50 + 10 * 50 + 10 * 90) / 100, 1) == 64.5
    q2, subs2 = pa.person_quality(scores, ids, founder_info=False)  # nothing founder-provided -> self flag ignored
    assert subs2["leadership"]["score"] == 50 and subs2["commitment"]["score"] == 50 and q2 < q
    low = pa.person_quality(pa.PersonScores(**{k: S(30) for k in pa.PERSON_WEIGHTS}), {}, True)[0]
    assert low == 30  # the cap never raises a score


def test_role_multipliers():
    m = pa.multiplier
    assert m({"kind": "cofounder", "role": "CEO"}) == 1.5
    assert m({"kind": "founder", "role": "CTO"}) == 1.5
    assert m({"kind": "cofounder", "role": "CTO"}) == 1.2
    assert m({"kind": "executive", "role": "Head of Sales"}) == 1.0
    assert m({"kind": "employee", "role": "Engineer"}) == 0.7
    assert m({"kind": "advisor", "role": "CEO of another company"}) == 0.4


def card(pid, kind, role, contribution, functions=(), score=None):
    return {"person_id": pid, "kind": kind, "role": role, "multiplier": pa.multiplier({"kind": kind, "role": role}),
            "contribution": contribution, "score": contribution if score is None else score,
            "functions": list(functions)}


def test_team_score_formula():
    cards = [card(1, "founder", "CEO", 80, ["commercial"]), card(2, "cofounder", "CTO", 60, ["tech"]),
             card(3, "advisor", "Advisor", 90, ["finance"])]
    people = {1: {"equity_pct": 80, "full_time": True}, 2: {}, 3: {}}
    worked = {"score": 90, "rationale": "", "fact_ids": []}  # no cited fact -> capped at 50
    t = pa.team_score(cards, people, worked, [{"text": "x", "fact_ids": ["p1f1"]}])
    people_c = round((1.5 * 80 + 1.2 * 60 + 0.4 * 90) / (1.5 + 1.2 + 0.4), 1)
    comps = {"complementarity": 50.0,  # tech + commercial among core people (the advisor's finance does not count)
             "key_roles": 100.0, "worked_together": 50.0, "advisors_board": 80.0,  # 1 advisor 60 + 20 (score>=70)
             "concentration": 50.0}  # 2 leaders 70 - 20 (one holds >= 75%)
    assert t["components"] == comps and t["people_component"] == people_c
    team_c = round(sum(pa.TEAM_WEIGHTS[k] * v for k, v in comps.items()), 1)
    assert t["team_component"] == team_c
    assert t["score"] == round(0.6 * people_c + 0.4 * team_c - 5, 1) and t["grade"] == pa.grade(t["score"])
    assert t["coverage"] == {"tech": True, "commercial": True, "domain": False, "finance": False}
    flags = [{"text": str(i), "fact_ids": ["x"]} for i in range(5)]
    assert pa.team_score(cards, people, worked, flags)["red_flag_penalty"] == 15.0  # max 15


def test_recompute_team_after_removal():
    res = {"people": [card(1, "founder", "CEO", 70), card(2, "cofounder", "CTO", 60, ["tech"])],
           "team": {"score": 1, "strengths": ["kept"]},
           "team_inputs": {"worked_together": {"score": 90, "rationale": "", "fact_ids": ["p2f1"]},
                           "red_flags": [{"text": "r", "fact_ids": ["p2f1"]}]}}
    res["people"][1]["facts"] = [{"id": "p2f1"}]
    res["people"] = res["people"][:1]  # person 2 removed
    t = pa.recompute_team(res, {1: {}})
    assert t["red_flags"] == [] and t["strengths"] == ["kept"] and t["components"]["worked_together"] == 50.0


# ================================================================== per-agent routing
def test_per_agent_llm_chain_and_default_unchanged():
    from blockid_agents.llm import FallbackLLM, build_agent_llms, cloud_chain

    s = replace(get_settings(), llm_backend="hosted", sambanova_api_key="sk", deepinfra_api_key="dk",
                claude_search_url="http://127.0.0.1:1", claude_search_token="t", claude_cli_enabled=True,
                llm_provider_order=("sambanova", "claude_bridge", "deepinfra"),
                sambanova_models=("gpt-oss-120b",), deepinfra_models=("deepseek-ai/DeepSeek-V4-Flash",),
                hr_llm_provider_order=("claude_bridge", "sambanova", "deepinfra"),
                hr_sambanova_models=("DeepSeek-V3.1", "DeepSeek-V3.2"),
                hr_deepinfra_models=("deepseek-ai/DeepSeek-V4-Flash", "Qwen/Qwen3-235B-A22B-Instruct-2507"))
    assert [n for n, _ in cloud_chain(s)] == ["claude-cli", "sambanova:gpt-oss-120b", "claude-bridge",
                                              "deepinfra:deepseek-ai/DeepSeek-V4-Flash"]  # valuation chain as before
    hr = build_agent_llms(s)["people_analyst"]
    chain = hr.routes["cloud"]
    assert isinstance(chain, FallbackLLM)
    assert [n for n, _ in chain.backends] == [
        "claude-bridge", "sambanova:DeepSeek-V3.1", "sambanova:DeepSeek-V3.2",
        "deepinfra:deepseek-ai/DeepSeek-V4-Flash", "deepinfra:Qwen/Qwen3-235B-A22B-Instruct-2507"]
    assert build_agent_llms(replace(s, llm_backend="gateway")) == {}


def test_deps_routes_people_analyst_to_its_own_llm_and_search(tmp_path):
    main, hr = FakeLLM({pa.Component: lambda s, u: pa.Component(score=1)}), \
        FakeLLM({pa.Component: lambda s, u: pa.Component(score=2)})
    main.name, hr.name = "main", "hr"
    shared, own = SearchChain([("brave", FakePeopleSearch())]), SearchChain([("claude", FakePeopleSearch())])
    d = Deps(llm=main, audit=AuditLog(tmp_path / "a.jsonl"), evidence=EvidenceStore(tmp_path / "e.sqlite"),
             settings=get_settings(), search=shared, agent_llm={"people_analyst": hr},
             agent_search={"people_analyst": own})
    assert d.ask("people_analyst", "cloud", "s", "u", pa.Component).score == 2
    assert d.ask("research", "cloud", "s", "u", pa.Component).score == 1
    assert d.search_for("people_analyst") is own and d.search_for("research") is shared
    lines = [json.loads(x) for x in (tmp_path / "a.jsonl").read_text().splitlines()]
    assert [x["data"].get("provider") for x in lines if x.get("action") == "llm_call"] == ["hr", "main"]


# ================================================================== SVI v4 weights + verification
def test_weights_v4_and_old_reports_still_verify():
    assert svi.WEIGHTS["founder_quality"] == 0.30 and svi.WEIGHTS["market_attractiveness"] == 0.15
    assert svi.WEIGHTS["revenue_performance"] == 0.15 and svi.FORMULA_VERSION == "v4"
    dims = {"founder_quality": 70, "product_strength": 60, "market_attractiveness": 75, "revenue_performance": 55.5,
            "growth_capability": 48.2, "investment_readiness": 40, "trust_verification": 90}
    for ver, w in svi.WEIGHT_SETS.items():
        index = round(sum(w[k] * v for k, v in dims.items()), 2)
        f = 0.5 + index / 100
        rep = {"profile": {"stage": "seed", "metrics": {"revenue_ttm_aud": 0}}, "market": {},
               "svi": {"index": index, "band": svi.band(index), "weights": dict(w),
                       "dimensions": {k: {"score": v} for k, v in dims.items()},
                       "valuation_low_aud": round(2e6 * f, -3), "valuation_mid_aud": round(5e6 * f, -3),
                       "valuation_high_aud": round(10e6 * f, -3)}}
        r = verify.recompute(rep)
        assert r["weights_version"] == ver and all(r["matches_report"].values()), (ver, r)
        # a report without recorded weights is matched by its index
        rep2 = json.loads(json.dumps(rep))
        rep2["svi"].pop("weights")
        assert verify.recompute(rep2)["weights_version"] == ver
    assert verify.formula()["weights_by_version"]["v3"]["founder_quality"] == 0.20


def stored_valuation() -> dict:
    """A stored valuation result like the worker writes (fake profile + scores, v3 triangulation, v4 weights)."""
    from blockid_agents.agents.valuation import triangulation_for

    p = fake_llm().handlers[StartupProfile]("", "")
    q = fake_llm().handlers[QualitativeScores]("", "")
    for k in QualitativeScores.model_fields:
        getattr(q, k).basis = "ai_suggested"
    m = MarketAnalysis(market_summary="m", revenue_multiple_median=6)
    res = svi.score(p, q, m)
    state = {"valuation_evidence": None}
    svi.apply_triangulation(res, triangulation_for(p, m, state, res.index))
    res.narrative = "n"
    return {"profile": p.model_dump(), "market": m.model_dump(), "qualitative": q.model_dump(),
            "svi": res.model_dump(), "valuation_evidence": None}


def test_team_score_blends_into_valuation_deterministically():
    from blockid_agents.agents.valuation import apply_team_score

    stored = stored_valuation()
    patch = apply_team_score(stored, 91.0, "team report t_x", ["https://hr.blockid.au/r/t_x"])
    fq = patch["svi"]["dimensions"]["founder_quality"]
    assert fq["score"] == 91.0 and fq["basis"] == "team_report" and fq["sources"] == ["https://hr.blockid.au/r/t_x"]
    others = {k: v["score"] for k, v in patch["svi"]["dimensions"].items() if k != "founder_quality"}
    assert others == {k: v["score"] for k, v in stored["svi"]["dimensions"].items() if k != "founder_quality"}
    expect = round(sum(svi.WEIGHTS[k] * patch["svi"]["dimensions"][k]["score"] for k in svi.WEIGHTS), 2)
    assert patch["svi"]["index"] == expect and patch["svi"]["narrative"] == "n"
    assert patch == apply_team_score(stored, 91.0, "team report t_x", ["https://hr.blockid.au/r/t_x"])  # same in, same out
    rep = {"profile": stored["profile"], "market": stored["market"], "svi": patch["svi"]}
    r = verify.recompute(rep)
    assert r["formula_version"] == ("v5" if v5_on() else "v4") and all(r["matches_report"].values()), r
    # admin override of founder_quality at the gate wins
    over = json.loads(json.dumps(stored))
    over["qualitative"]["founder_quality"].update(basis="human", rationale="x [set by admin]")
    assert apply_team_score(over, 91.0, "r", []) is None


def test_gate_keeps_team_score_unless_overridden(tmp_path):
    from blockid_agents.agents.valuation import apply_overrides, apply_team_score

    stored = stored_valuation()
    state = {**stored, **apply_team_score(stored, 88.0, "team", [])}
    deps = deps_for(tmp_path)
    out = apply_overrides(state, {}, "admin", deps)
    fq = out["svi"]["dimensions"]["founder_quality"]
    assert fq["basis"] == "team_report" and fq["score"] == 88.0 and "[confirmed by admin]" in fq["rationale"]
    assert out["svi"]["dimensions"]["product_strength"]["basis"] == "human"
    out2 = apply_overrides(state, {"founder_quality": 40}, "admin", deps)
    assert out2["svi"]["dimensions"]["founder_quality"] == {**out2["svi"]["dimensions"]["founder_quality"],
                                                            "basis": "human", "score": 40.0}


def test_fake_pages_fixture_is_consistent():
    assert "Jane Nguyen" in FAKE_PEOPLE_PAGES["https://agritrace.example/team"]
