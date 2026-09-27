"""SVI v5 (tools/evaluation.py + tools/svi.apply_v5/recompute_v5) and the v5 graph path (offline fakes)."""
import json

import pytest

from blockid_agents.schemas import SVIResult
from blockid_agents.tools import evaluation as ev
from blockid_agents.tools import stage as st
from blockid_agents.tools import svi

TYPED = {"revenue_ttm_aud": 600_000, "revenue_prev_ttm_aud": 300_000, "customers": 40, "gross_margin_pct": 70,
         "cash_aud": 1_000_000, "burn_monthly_aud": 80_000, "nrr_pct": 105, "grr_pct": 88,
         "qualified_pipeline_aud": 900_000, "target_customer_count": 20_000, "annual_price_aud": 6_000}


def blank() -> SVIResult:
    return SVIResult(index=0, band="", dimensions={}, weights={}, valuation_low_aud=1, valuation_mid_aud=1,
                     valuation_high_aud=1, method="m", needs_human_review=[])


def evaluate(**kw):
    sd = st.classify_stage(st.evidence_from_result({}, kw.get("self_reported") or {}))
    return ev.evaluate(None, stage_decision=sd, competitors=[{"name": "x", "raised_aud": 5e6}] * 4, **kw)


def test_deterministic_and_recomputable():
    q = {"founder_quality": {"score": 82, "basis": "team_report", "rationale": "team"},
         "product_strength": {"score": 60, "basis": "ai_suggested"}}
    a1, a2 = evaluate(self_reported=TYPED, qualitative=q), evaluate(self_reported=TYPED, qualitative=q)
    assert a1.model_dump_json() == a2.model_dump_json()
    r = svi.apply_v5(blank(), a1)
    assert r.weights_profile == "v5:seed" and list(r.dimensions) == list(st.DIMENSIONS)
    assert r.index == round(sum(r.weights[k] * r.dimensions[k].score for k in r.weights), 2)
    assert r.dimensions["founder_quality"].score == 82 and r.dimensions["founder_quality"].basis == "team_report"
    rc = svi.recompute_v5(json.loads(r.model_dump_json()))
    assert rc["matches"]["index"] and all(rc["matches"]["dimensions"].values())
    tampered = json.loads(r.model_dump_json())
    tampered["analysis"]["dimensions"]["traction"]["sub_metrics"][0]["value"]["value"] = 50e6
    assert not svi.recompute_v5(tampered)["matches"]["dimensions"]["traction"]


def test_self_reported_keeps_sixty_percent_and_documents_raise_level():
    a = evaluate(self_reported=TYPED)
    t1 = a.dimensions["traction"].sub_metrics[0]
    assert t1.value.level == 1 and t1.score == pytest.approx(50 + (t1.score_raw - 50) * 0.6, abs=0.01)
    doc = {"doc_id": 3, "kind": "metrics_csv", "parsed": {"months": ["2026-08"], "flags": [],
                                                           "metrics": {"revenue_ttm_aud": 610_000}}}
    b = evaluate(self_reported=TYPED, documents=[doc])
    t1b = b.dimensions["traction"].sub_metrics[0]
    assert t1b.value.level == 2 and t1b.score > t1.score  # typed matches the CSV within 5 % -> L2
    assert b.trust_share > a.trust_share


def test_website_only_company_is_not_enough_data():
    a = evaluate()
    for k in ("traction", "market", "efficiency"):
        assert a.dimensions[k].status == "not_enough_data" and a.dimensions[k].score == 40
    assert a.dimensions["retention"].status == "not_applicable" and a.dimensions["retention"].score == 40
    assert a.dimensions["founder_quality"].improve and a.top_improvements


def test_founder_llm_suggestion_capped_without_team_report():
    a = evaluate(qualitative={"founder_quality": {"score": 90, "basis": "ai_suggested"}})
    assert a.dimensions["founder_quality"].score == 50


def test_market_bottom_up_and_warning():
    a = evaluate(self_reported={**TYPED, "revenue_ttm_aud": 50_000_000, "target_customer_count": 100,
                                "annual_price_aud": 1000})
    assert a.market_sizing.sam_aud == 100_000
    assert any("mis-sized" in w for w in a.market_sizing.warnings)


def test_flag_off_result_has_no_v5_keys():
    d = blank().model_dump()
    assert "analysis" not in d and "weights_profile" not in d
    assert "analysis" not in json.loads(blank().model_dump_json())


def _graph(tmp_path, v5):
    from langgraph.checkpoint.memory import InMemorySaver
    from test_studio import studio_deps

    from blockid_agents.fakes import FAKE_SITE
    from blockid_agents.graph import build_site_valuation
    from blockid_agents.studio.db import MemoryProgress

    deps = studio_deps(tmp_path)
    prog = MemoryProgress()
    g = build_site_valuation(deps, InMemorySaver(), prog, v5=v5)
    cfg = {"configurable": {"thread_id": "g5"}}
    out = g.invoke({"job_id": "g5", "url": FAKE_SITE,
                    "self_reported": {"revenue_ttm_aud": 480_000, "customers": 23}}, cfg)
    return g, cfg, prog, out


def test_graph_v5_adds_analysts_and_nine_dimensions(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOKUPS_OFFLINE", "1")
    from langgraph.types import Command

    g, cfg, prog, out = _graph(tmp_path, True)
    assert out["__interrupt__"][0].value["gate"] == "valuation"
    steps = list(prog.steps["g5"])
    assert steps.index("market") < steps.index("analysts") < steps.index("svi")
    s = prog.results["g5"]["svi"]
    assert s["weights_profile"].startswith("v5:") and set(s["dimensions"]) == set(st.DIMENSIONS)
    assert s["analysis"]["stage"]["stage"] in st.STAGES
    assert svi.recompute_v5(s)["matches"]["index"]
    final = g.invoke(Command(resume={"approved": True, "reviewer": "admin",
                                     "overrides": {"product_strength": 77}}), cfg)
    fs = final["svi"]
    assert fs["weights_profile"].startswith("v5:") and fs["dimensions"]["product_strength"]["score"] == 77
    assert fs["dimensions"]["product_strength"]["basis"] == "human"


def test_graph_flag_off_is_v4(tmp_path):
    _, _, prog, _ = _graph(tmp_path, False)
    assert "analysts" not in prog.steps["g5"]
    s = prog.results["g5"]["svi"]
    assert "analysis" not in s and "weights_profile" not in s and "revenue_performance" in s["dimensions"]
