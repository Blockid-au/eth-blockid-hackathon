"""Valuation Agent (agents/valuation_agent.py): the model only extracts / cites — industry key must be in the dataset,
unknown evidence URLs are dropped, precedent deals need a verbatim quote with the multiple and a date on the page;
nothing the model says becomes a number unchecked. Flag off: the v3 path is untouched. Offline (fake LLM)."""
import json
from datetime import date

import pytest

from blockid_agents.agents import valuation as valuation_mod
from blockid_agents.agents import valuation_agent as va
from blockid_agents.audit import AuditLog
from blockid_agents.config import get_settings
from blockid_agents.deps import Deps
from blockid_agents.llm import FakeLLM
from blockid_agents.policy import PolicyViolation, guard
from blockid_agents.schemas import (
    DealClaim,
    DealClaims,
    DimensionScore,
    EvidenceItem,
    FactorScore,
    IndustryPick,
    MarketAnalysis,
    Metrics,
    RfsRating,
    StartupFactors,
    StartupProfile,
    SVIResult,
)
from blockid_agents.tools import svi
from blockid_agents.tools.brave import EvidenceStore

PAGE = ("Sydney, 12 March 2026 — Listed group Beta Holdings acquired Gamma Bookkeeping for A$18 million, "
        "or 6.0 times EBITDA, the company said. Gamma had revenue of A$9 million.")


def profile(stage="seed", rev=0.0):
    return StartupProfile(company_name="Acme Ledger Pty Ltd", sector="accounting software", stage=stage,
                          description="bookkeeping software for small firms", metrics=Metrics(revenue_ttm_aud=rev))


def make_deps(tmp_path, handlers):
    store = EvidenceStore(tmp_path / "ev.sqlite")
    ev = EvidenceItem(url="https://news.example/gamma", title="Gamma sold", snippet="", retrieved_at=1.0,
                      query="comps", kind="web")
    store.add(ev, PAGE, "vx")
    llm = FakeLLM(handlers)
    s = get_settings()
    return Deps(llm=llm, audit=AuditLog(tmp_path / "audit.jsonl"), evidence=store, settings=s)


def test_policy_valuation_methods_has_one_search_kind_and_no_chain_tools():
    guard("valuation_methods", tier="cloud", tool="value_methods")
    for tool in ("web_search", "fetch_url", "store_evidence"):  # the one `precedents` search (tools/search.py)
        guard("valuation_methods", tool=tool)
    for tool in ("sign_tx", "send_tx", "shell", "read_private_key"):
        with pytest.raises(PolicyViolation):
            guard("valuation_methods", tool=tool)


def test_industry_pick_must_be_a_dataset_key(tmp_path):
    d = make_deps(tmp_path, {IndustryPick: lambda s, u: IndustryPick(industry="Crypto casinos", rationale="x")})
    key, basis, _ = va.pick_industry(profile(), d)
    assert basis == "keyword" and key == "software"  # invented key -> keyword fallback
    d = make_deps(tmp_path, {IndustryPick: lambda s, u: IndustryPick(industry="business_services", rationale="ok")})
    assert va.pick_industry(profile(), d)[:2] == ("business_services", "ai_suggested")
    d = make_deps(tmp_path, {})  # model down -> fallback, never an exception
    assert va.pick_industry(profile(), d)[1] == "keyword"


def test_startup_factor_sources_outside_evidence_are_dropped(tmp_path):
    def factors(_s, _u):
        return StartupFactors(berkus={"prototype": FactorScore(score=70, sources=["https://news.example/gamma",
                                                                                  "https://invented.example/x"])},
                              rfs={"competition": RfsRating(rating=-1, sources=["https://invented.example/y"])})

    d = make_deps(tmp_path, {StartupFactors: factors})
    ev = va._evidence(d, "vx")
    out, dropped = va.suggest_factors(profile(), None, ev, "seed", d)
    assert out["berkus"]["prototype"]["sources"] == ["https://news.example/gamma"]
    assert out["rfs"]["competition"]["sources"] == [] and len(dropped) == 2


def _deal(**kw):
    base = {"target": "Gamma Bookkeeping", "acquirer": "Beta Holdings", "multiple": 6.0, "basis": "ebitda",
            "currency": "AUD", "date_text": "12 March 2026", "source_url": "https://news.example/gamma",
            "quote": "acquired Gamma Bookkeeping for A$18 million, or 6.0 times EBITDA"}
    base.update(kw)
    return DealClaim(**base)


def test_deal_verification_rules(tmp_path):
    d = make_deps(tmp_path, {})
    ev = va._evidence(d, "vx")
    ok, dropped = va.verify_deals(DealClaims(deals=[_deal()]), ev, profile(), date(2026, 9, 27))
    assert len(ok) == 1 and ok[0]["multiple"] == 6.0 and ok[0]["as_of"] == "2026-03" and ok[0]["age_months"] == 6
    cases = {
        "quote not found": _deal(quote="acquired Gamma for 9.5 times EBITDA"),
        "not in evidence": _deal(source_url="https://invented.example/deal"),
        "does not state": _deal(multiple=8.0),  # 8.0x is not in the quote
        "company itself": _deal(target="Acme Ledger"),
        "outside bounds": _deal(multiple=None, ev=18e6, ebitda=0.2e6,
                                quote="Gamma Bookkeeping for A$18 million, or 6.0 times EBITDA"),
        "currency": _deal(currency="XYZ"),
        "revenue": _deal(basis="revenue"),  # quote talks about EBITDA
    }
    for why, claim in cases.items():
        ok, dropped = va.verify_deals(DealClaims(deals=[claim]), ev, profile(), date(2026, 9, 27))
        assert ok == [] and len(dropped) == 1, why
    # price + metric both stated on the page -> multiple computed by code
    ok, _ = va.verify_deals(DealClaims(deals=[_deal(multiple=None, ev=18e6, ebitda=3e6,
                                                    quote="acquired Gamma Bookkeeping for A$18 million, or 6.0 "
                                                          "times EBITDA")]), ev, profile(), date(2026, 9, 27))
    assert ok == []  # EBITDA 3M is not stated in the quote: refused (no guessing)


def _result(stage="seed", rev=480_000.0):
    dims = {k: DimensionScore(score=60, basis="ai_suggested") for k in svi.WEIGHTS}
    return SVIResult(index=60, band="C", dimensions=dims, weights=dict(svi.WEIGHTS), valuation_low_aud=1,
                     valuation_mid_aud=1, valuation_high_aud=1, method="x", needs_human_review=[])


def test_node_never_takes_numbers_from_the_model(tmp_path, monkeypatch):
    monkeypatch.setenv("VALUATION_V5", "1")

    def factors(_s, _u):
        return StartupFactors(berkus={k: FactorScore(score=100) for k in ("sound_idea", "prototype")})

    d = make_deps(tmp_path, {IndustryPick: lambda s, u: IndustryPick(industry="software"),
                             StartupFactors: factors,
                             DealClaims: lambda s, u: DealClaims(deals=[_deal(multiple=99.0)])})
    p = profile("seed", 100_000)  # seed below A$250k revenue: Berkus runs
    state = {"job_id": "vx", "profile": p.model_dump(), "market": MarketAnalysis(market_summary="m").model_dump(),
             "svi": _result().model_dump()}
    out = va.run(state, d)
    tri = out["svi"]["triangulation"]
    assert tri["version"] == "v5" and out["valuation_inputs"]["industry"] == "software"
    berkus = next(m for m in tri["methods"] if m["method"] == "berkus")
    assert berkus["inputs"]["scores"]["sound_idea"] == 100  # a rating, used by the fixed Berkus formula
    assert berkus["inputs"]["cap_per_factor_aud"] == 750_000  # the cap is a parameter, not the model's
    assert "ai_suggested" in berkus["inputs"]["evidence"]
    assert out["valuation_inputs"]["factors_basis"] == "ai_suggested"
    calls = [name for _, name in d.llm.calls]
    assert len(calls) <= 3 and "DealClaims" not in calls  # deals only for series-a / growth
    # the headline range comes from the deterministic blend
    assert out["svi"]["valuation_mid_aud"] == round(tri["value_aud"], -3)
    # the approval gate confirms the ratings: weight 0.5 -> 1.0
    res = SVIResult.model_validate(out["svi"])
    st = {**state, "svi": out["svi"], "valuation_inputs": out["valuation_inputs"]}
    tri2 = va.triangulation_v5(res, p, None, st, reviewer="admin")
    assert st["valuation_inputs"]["factors_basis"] == "human"
    assert "ai_suggested" not in next(m for m in tri2.methods if m.method == "berkus").inputs["evidence"]


def test_flag_off_hook_is_exactly_v3(monkeypatch):
    monkeypatch.setenv("VALUATION_V5", "0")
    p = profile("seed", 480_000)
    res = _result()
    a = valuation_mod.triangulate_result(res, p, None, {})
    b = valuation_mod.triangulation_for(p, None, {}, res.index)
    assert a.version == "v3" and json.dumps(a.model_dump(), sort_keys=True) == json.dumps(b.model_dump(),
                                                                                          sort_keys=True)
    monkeypatch.setenv("VALUATION_V5", "1")
    assert valuation_mod.triangulate_result(res, p, None, {}).version == "v5"


def test_team_score_blend_keeps_v5_dimensions_and_value(tmp_path, monkeypatch):
    """valuation.apply_team_score on a stored v5 result (evaluation v5 + valuation v5): founder_quality = the team
    score, the nine v5 dimensions / weights profile survive, and the v5 value is recomputed from the new scores."""
    import sys

    from langgraph.checkpoint.memory import InMemorySaver

    from blockid_agents.fakes import FAKE_SITE
    from blockid_agents.graph import build_site_valuation
    from blockid_agents.studio.db import MemoryProgress

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from test_studio import studio_deps

    monkeypatch.setenv("VALUATION_V5", "1")
    prog = MemoryProgress()
    build_site_valuation(studio_deps(tmp_path), InMemorySaver(), prog).invoke(
        {"job_id": "vt", "url": FAKE_SITE}, {"configurable": {"thread_id": "vt"}})
    stored = prog.results["vt"]
    s0 = stored["svi"]
    assert s0["weights_profile"].startswith("v5:") and s0["triangulation"]["version"] == "v5"
    patch = valuation_mod.apply_team_score(stored, 88.0, "team report", ["https://hr.example/r/1"])
    s1 = patch["svi"]
    assert s1["weights_profile"] == s0["weights_profile"] and s1["analysis"]
    assert set(s1["dimensions"]) == set(s0["dimensions"])  # nine v5 dimensions kept
    assert s1["dimensions"]["founder_quality"]["score"] == 88.0
    assert s1["dimensions"]["founder_quality"]["basis"] == "team_report"
    assert s1["triangulation"]["version"] == "v5"
    assert s1["valuation_mid_aud"] == round(s1["triangulation"]["value_aud"], -3)
    assert s1["index"] != s0["index"]
    sc = next(m for m in s1["triangulation"]["methods"] if m["method"] == "scorecard")
    assert sc["inputs"]["lines"]["team"]["score"] == 88.0  # the scorecard uses the team score
