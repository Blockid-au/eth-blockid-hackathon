"""Valuation / evaluation v5 readiness (docs/V5-READINESS.md): /verify recomputes the v5 index and band, dated
Damodaran industry table (dataset 2026-09-27), params v5.1 calibration (VC target return + retention, venture-rate DCF
exit terminal, calibrated stage benchmark, listed-peer revenue blend), cited revenue in v5 traction, metrics CSV as
text, gateway routing of the valuation agent's schemas and the `precedents` search kind. Offline, no DB."""
import copy
import json
import math

import pytest

from blockid_agents.schemas import (
    CompanyFinancials,
    DimensionScore,
    MarketAnalysis,
    Metrics,
    StartupProfile,
    SVIResult,
    VerifiedValuationEvidence,
)
from blockid_agents.studio import verify
from blockid_agents.studio.report_hash import canonical_json
from blockid_agents.tools import evaluation as ev
from blockid_agents.tools import market_data, svi
from blockid_agents.tools import stage as st
from blockid_agents.tools import valuation_methods as vm
from blockid_agents.tools.valuation_params import MARKET_DATASET, PARAMS, PARAMS_VERSION, params
from blockid_agents.tools.valuation_v5 import industry_multiple, recompute_v5, triangulate_v5

TYPED = {"revenue_ttm_aud": 600_000, "revenue_prev_ttm_aud": 300_000, "customers": 40, "gross_margin_pct": 70,
         "cash_aud": 1_000_000, "burn_monthly_aud": 80_000, "nrr_pct": 105, "grr_pct": 88,
         "qualified_pipeline_aud": 900_000, "target_customer_count": 20_000, "annual_price_aud": 6_000}


# ================================================================== /verify: v5 index + band
def v5_report() -> dict:
    sd = st.classify_stage(st.evidence_from_result({}, TYPED))
    a = ev.evaluate(None, stage_decision=sd, self_reported=TYPED, competitors=[{"name": "x", "raised_aud": 5e6}] * 4,
                    qualitative={"founder_quality": {"score": 82, "basis": "team_report", "rationale": "team"},
                                 "product_strength": {"score": 60, "basis": "ai_suggested"}})
    base = SVIResult(index=0, band="", dimensions={}, weights={}, valuation_low_aud=1, valuation_mid_aud=1,
                     valuation_high_aud=1, method="m", needs_human_review=[])
    res = svi.apply_v5(base, a)
    return {"url": "https://x.example", "profile": {"metrics": {}}, "svi": json.loads(res.model_dump_json())}


def test_verify_recomputes_v5_index_band_and_dimensions():
    rep = v5_report()
    s = rep["svi"]
    rc = verify.recompute(json.loads(canonical_json(rep)))
    assert rc["formula_version"] == "v5" and rc["weights_version"] == s["weights_profile"] == "v5:seed"
    assert rc["weights"] == st.weights("seed") and len(rc["contributions"]) == 9
    assert rc["index"] == s["index"] and rc["band"] == s["band"] == svi.band(s["index"])
    for k in ("index", "band", "weights", "dimensions"):
        assert rc["matches_report"][k], k
    assert all(rc["dimension_matches"].values())
    # trust_verification is rebuilt from the sub-metric levels, not echoed
    assert svi.recompute_v5(s)["dimensions"]["trust_verification"] == s["dimensions"]["trust_verification"]["score"]


@pytest.mark.parametrize("tamper", ["index", "band", "weights", "sub_metric", "trust"])
def test_verify_v5_detects_tampering(tamper):
    rep = v5_report()
    s = rep["svi"]
    if tamper == "index":
        s["index"] = round(s["index"] + 3, 2)
    elif tamper == "band":
        s["band"] = svi.band(95)
    elif tamper == "weights":  # stored weights moved to traction: no longer the published stage column
        w = s["weights"]
        w["traction"], w["founder_quality"] = w["traction"] + 0.1, w["founder_quality"] - 0.1
        s["analysis"]["stage_profile"]["weights"] = dict(w)
        s["index"] = svi.index_v5(s["dimensions"], w)
        s["band"] = svi.band(s["index"])
    elif tamper == "sub_metric":
        s["analysis"]["dimensions"]["traction"]["sub_metrics"][0]["value"]["value"] = 50e6
    else:
        s["dimensions"]["trust_verification"]["score"] = 99.0
        s["index"] = svi.index_v5(s["dimensions"], s["weights"])
        s["band"] = svi.band(s["index"])
    rc = verify.recompute(json.loads(canonical_json(rep)))
    assert not all(rc["matches_report"].values()), tamper
    if tamper == "weights":
        assert not rc["matches_report"]["weights"]


def test_v5_score_without_analysis_never_verifies_as_v5():
    rep = v5_report()
    rep["svi"].pop("analysis")
    rc = verify.recompute(rep)
    assert rc["matches_report"]["dimensions"] is False


# ================================================================== dated market data + params versions
def test_market_dataset_2026_09_27_is_damodaran_january_2026():
    snap = market_data.snapshot("2026-09-27")
    d = snap.data
    assert MARKET_DATASET == "2026-09-27" and d["industries_status"] == "verified"
    assert d["industries_data_date"] == "2026-01-05"
    for name in ("betaGlobal", "psGlobal", "vebitdaGlobal", "marginGlobal", "betaRest", "psRest"):
        src = d["industries_sources"][name]
        assert src["url"].startswith("https://pages.stern.nyu.edu/~adamodar/pc/datasets/") and len(src["sha256"]) == 64
    sw = snap.industry("software")  # transcribed from the January 2026 global files
    assert (sw["damodaran_industry"], sw["beta_u"], sw["ev_sales"], sw["ev_ebitda"], sw["n_firms"]) == \
        ("Software (System & Application)", 1.33, 9.91, 24.64, 1532)
    assert snap.industry("general")["damodaran_industry"] == "Total Market (without financials)"
    assert snap.industry("fintech")["reference_financial"]["damodaran_industry"].startswith("Financial Svcs")
    for k in snap.industry_keys():
        row = snap.industry(k)
        assert row["aunzca"]["n_firms"] > 0 and row["ebitda_margin_p90"] >= row["ebitda_margin"] + 0.1 - 1e-9
    # the placeholder dataset stays as it was (reports that used it keep their id)
    old = market_data.snapshot("2026-09-26")
    assert old.data["industries_status"] == "placeholder_pending_refresh" and old.industry("software")["ev_sales"] == 6.0


def test_params_v5_frozen_and_v5_1_adds_calibration_only():
    v5, v51 = PARAMS["v5"], PARAMS["v5.1"]
    assert PARAMS_VERSION == "v5.1"
    assert not {"vc_target_irr_band", "vc_retention", "startup_terminal", "revenue_listed_blend",
                "stage_benchmark_source"} & set(v5)
    assert {k for k in v5 if v5[k] != v51[k]} == set()  # every v5 rule is unchanged in v5.1
    # retention to exit after Series A, B, C at Carta's 2025 software medians (18 %, 14 %, 10 %)
    assert v51["vc_retention"]["seed"] == pytest.approx((1 - 0.18) * (1 - 0.14) * (1 - 0.10), abs=0.005)
    assert verify.formula()["params_by_version"]["v5.1"]["startup_terminal"] == "exit"


def test_ebitda_multiple_uses_verified_table_without_placeholder_penalty():
    p = params()
    snap = market_data.snapshot(MARKET_DATASET)
    row = snap.industry("business_services")
    m = vm.build("ebitda_multiple", {"ebitda_aud": 1e6, "band": [row["ev_ebitda"] * 0.7, row["ev_ebitda"],
                                                                 row["ev_ebitda"] * 1.4], "dlom": 0.25,
                                     "evidence": ["management_actuals", "industry_table"]}, p, "profitable_sme")
    assert m.raw_weight == pytest.approx(1.0 * 0.9 * 0.6) and not m.notes


# ================================================================== engine calibration (v5.1)
def _seed_case(**over):
    from blockid_agents.tools import projections as pj

    snap = market_data.snapshot(MARKET_DATASET)
    cases = json.loads((__import__("pathlib").Path(__file__).resolve().parents[2] / "scripts" / "fixtures" /
                        "valuation-v5-cases.json").read_text())["cases"]
    name = over.pop("name", "seed-good")
    c = next(x for x in cases if x["name"] == name)
    inp = pj.ProjectionInput.model_validate(c["projection"])
    cls = "series_a" if c["stage_hint"] == "series-a" else "seed"
    checks, used = pj.validate(inp, cls=cls, industry_row=snap.industry(snap.industry_for_text(c["sector"])),
                               revenue_ref_aud=c["revenue_ttm_aud"], p=params())
    proj = {"parsed": pj.parsed_record(inp, used), "checks": [x.model_dump() for x in checks], "sha256": "f"}
    prof = StartupProfile(company_name=c["name"], sector=c["sector"], description=c["sector"], stage=c["stage_hint"],
                          metrics=Metrics(revenue_ttm_aud=c["revenue_ttm_aud"], revenue_growth_yoy_pct=c["growth_pct"]))
    dims = {k: DimensionScore(score=60, basis="human") for k in svi.WEIGHTS}
    kw = {"profile": prof, "market": MarketAnalysis(market_summary="f"),
          "ve": VerifiedValuationEvidence(as_of="2026-09-27"), "dims": dims, "svi_index": 60.0, "self_reported": None,
          "v5_inputs": {}, "projection": proj, "stage_ranges": svi.STAGE_PRE_REVENUE_RANGE, "as_of": "2026-09-27"}
    kw.update(over)
    return triangulate_v5(**kw)


@pytest.mark.parametrize("name", ["seed-good", "series_a-good"])
def test_typical_cases_keep_dcf_vc_and_scorecard(name):
    tri = _seed_case(name=name)
    used = {m.method for m in tri.methods if m.weight > 0}
    assert {"first_chicago", "vc_method", "scorecard"} <= used, [(m.method, m.notes) for m in tri.methods]
    vc = next(m for m in tri.methods if m.method == "vc_method")
    assert vc.inputs["target_irr"] == params()["startup_discount_rates"][tri.valuation_class]
    assert vc.inputs["retention"] == params()["vc_retention"][tri.valuation_class] < 1
    fc = next(m for m in tri.methods if m.method == "first_chicago")
    ind = market_data.snapshot(MARKET_DATASET).industry(tri.stage["industry"])
    assert fc.inputs["terminal"] == "exit" and fc.inputs["exit_multiple"] == pytest.approx(ind["ev_ebitda"] * 0.75)
    stored = json.loads(canonical_json(tri.model_dump()))
    r = recompute_v5(copy.deepcopy(stored))
    assert (r["low"], r["mid"], r["high"]) == (round(tri.low_aud, -3), round(tri.value_aud, -3), round(tri.high_aud, -3))


def test_v5_params_report_still_recomputes_with_v5_rules():
    tri = _seed_case(params_version="v5", dataset="2026-09-26")
    assert tri.params_version == "v5" and tri.market_dataset == "2026-09-26"
    vc = next(m for m in tri.methods if m.method == "vc_method")
    assert "target_irr" not in vc.inputs and vc.inputs["retention"] == 1.0  # the v5 rule, as shipped
    stored = json.loads(canonical_json(tri.model_dump()))
    assert recompute_v5(stored)["mid"] == round(tri.value_aud, -3)


def test_stage_benchmark_au_table_and_funding_implied():
    prof = StartupProfile(company_name="X", sector="software", description="saas", stage="growth")
    base = {"profile": prof, "market": None, "ve": VerifiedValuationEvidence(as_of="2026-09-27"), "dims": {},
            "svi_index": 50.0, "self_reported": None, "v5_inputs": {}, "projection": None,
            "stage_ranges": svi.STAGE_PRE_REVENUE_RANGE, "as_of": "2026-09-27",
            "stage_decision": st.StageDecision(stage="growth", basis="hint").model_dump()}
    t = triangulate_v5(**base)
    sm = next(m for m in t.methods if m.method == "stage_scorecard")
    assert sm.inputs["benchmark"] == list(st.au_round_medians("growth")["pre_money_aud"])
    assert "AU growth pre-money" in sm.inputs["benchmark_basis"] and sm.weight == 1
    cf = CompanyFinancials(funding_raised_total=400e6, funding_raised_total_aud=600e6, source_url="https://n.example/a",
                           quote="raised around US$400 million")
    t2 = triangulate_v5(**{**base, "market": MarketAnalysis(market_summary="m", company_financials=cf)})
    sm2 = next(m for m in t2.methods if m.method == "stage_scorecard")
    assert sm2.inputs["benchmark"] == [2.1e9, 2.7e9, 3.6e9] and sm2.inputs["raised_source"] == "cited source"
    assert sm2.label.startswith("funding-implied value") and "https://n.example/a" in sm2.sources
    t3 = triangulate_v5(**{**base, "self_reported": {"raised_to_date_aud": 2e6}})
    sm3 = next(m for m in t3.methods if m.method == "stage_scorecard")
    assert sm3.inputs["benchmark"] == [7e6, 9e6, 12e6] and sm3.inputs["raised_source"] == "self-reported"
    for tri in (t, t2, t3):
        stored = json.loads(canonical_json(tri.model_dump()))
        assert recompute_v5(stored)["mid"] == round(tri.value_aud, -3)


def test_revenue_multiple_listed_blend_by_size():
    p = params()
    snap = market_data.snapshot(MARKET_DATASET)
    row = snap.industry("software")
    cited = {"source": "sector_cited", "low": 3.0, "median": 4.6, "high": 7.0, "discount": 0.25, "n": 1,
             "detail": "SaaS median", "sources": ["https://s.example"]}
    small, rec = industry_multiple(dict(cited), 5e6, row, p, snap, dlom=0.25, listed=False)
    assert small["median"] == 4.6 and rec is None  # <= A$10M: private-market multiple only
    mid, rec = industry_multiple(dict(cited), 100e6, row, p, snap, dlom=0.25, listed=False)
    assert rec["share"] == pytest.approx(0.25)
    eff = math.exp(0.75 * math.log(4.6 * 0.75) + 0.25 * math.log(9.91 * 0.75))
    assert mid["median"] == pytest.approx(eff / 0.75, abs=1e-3) and mid["source"] == "sector_cited"
    _, rec = industry_multiple(dict(cited), 50e9, row, p, snap, dlom=0.25, listed=False)
    assert rec["share"] == 0.5
    comps = {**cited, "source": "comps_3plus", "n": 4}
    assert industry_multiple(dict(comps), 1e9, row, p, snap, dlom=0.25, listed=False)[1] is None
    m = vm.build("revenue_multiple", {"revenue_aud": 100e6, "revenue_source": "cited_source",
                                      "multiple_source": "sector_cited", "low_multiple": mid["low"],
                                      "median_multiple": mid["median"], "high_multiple": mid["high"],
                                      "discount": 0.25, "n": 1, "listed_blend": rec}, p, "growth")
    assert m.inputs["listed_blend"] == rec and any("listed peers" in n for n in m.notes)


# ================================================================== evaluation: cited revenue reaches traction
def test_research_verified_revenue_and_funding_become_claims():
    from blockid_agents.agents.analysts import Verifier, research_claims
    from blockid_agents.tools.brave import EvidenceItem

    cf = {"revenue_ttm": 1.6e6, "currency": "USD", "revenue_year": 2025, "revenue_type": "ARR",
          "revenue_ttm_aud": 2.4e6, "usable_for_valuation": True, "source_url": "https://news.example/a",
          "quote": "X reported ARR of US$1.6 million", "funding_raised_total": 5e6, "funding_raised_total_aud": 7.5e6,
          "funding_quote": "X has raised US$5 million"}
    item = EvidenceItem(url="https://news.example/a", title="t", snippet="", retrieved_at=0, content_sha256="0",
                        query="q", kind="web")
    v = Verifier([(item, "X reported ARR of US$1.6 million.")], StartupProfile(company_name="X", sector="s",
                                                                               description="d"), "https://x.example")
    claims = research_claims({"market": {"company_financials": cf}}, v)
    assert [(c.metric, c.value_aud, c.level, c.analyst) for c in claims] == [
        ("arr", 2.4e6, 3, "research"), ("raised_to_date", 7.5e6, 3, "research")]
    gmv = research_claims({"market": {"company_financials": {**cf, "revenue_type": "GMV",
                                                             "usable_for_valuation": False}}}, v)
    assert [c.metric for c in gmv] == ["raised_to_date"]
    sd = st.classify_stage(st.evidence_from_result({}, {}))
    a = ev.evaluate({"stage": sd.model_dump(), "claims": [c.model_dump() for c in claims]}, stage_decision=sd)
    assert a.metrics["arr_aud"].level == 3 and a.dimensions["traction"].sub_metrics[0].status == "scored"
    assert any(c.analyst == "research" for c in a.dimensions["traction"].evidence)


# ================================================================== contracts (UI <-> backend)
def test_metrics_csv_rows_accept_text_or_rows():
    from blockid_agents.studio.evaluation import MAX_TEXT_CHARS, DocumentBody

    h = "a" * 64
    txt = DocumentBody.model_validate({"kind": "metrics_csv", "filename": "m.csv", "sha256": h,
                                       "rows": "month,revenue_aud\n2026-01,100\n"})
    assert isinstance(txt.rows, str)
    rows = DocumentBody.model_validate({"kind": "metrics_csv", "filename": "m.csv", "sha256": h,
                                        "rows": [["month", "revenue_aud"], ["2026-01", "100"]]})
    assert rows.rows[1] == ["2026-01", "100"]
    with pytest.raises(ValueError):
        DocumentBody.model_validate({"kind": "metrics_csv", "filename": "m.csv", "sha256": h,
                                     "rows": "x" * (MAX_TEXT_CHARS + 1)})
    with pytest.raises(ValueError):
        DocumentBody.model_validate({"kind": "metrics_csv", "filename": "m.csv", "sha256": h,
                                     "rows": [["2026-01", "1"]] * 200})


def test_gateway_routes_valuation_agent_schemas():
    from blockid_agents.ai_gateway import SCHEMA_PROFILES, profile_for

    assert profile_for("IndustryPick") == profile_for("DealClaims") == "extract_json"
    assert profile_for("StartupFactors") == "reason_score"
    import blockid_agents.schemas as sch

    for name in ("TractionClaims", "MarketSizeClaims", "MoatClaims", "RetentionClaims", "DeckFacts", "IndustryPick",
                 "DealClaims", "StartupFactors"):
        assert hasattr(sch, name) and name in SCHEMA_PROFILES  # every v5 LLM schema is routed explicitly


def test_precedents_search_kind_on_the_shared_budget(tmp_path):
    from datetime import date

    from test_studio import studio_deps

    from blockid_agents.agents.valuation_agent import search_precedents
    from blockid_agents.tools.search import (
        ANALYST_QUERY_PLAN,
        PURPOSE,
        QUERY_PLAN,
        VALUATION_QUERY_PLAN,
        SearchChain,
        precedents_query,
    )

    assert len(QUERY_PLAN) + len(ANALYST_QUERY_PLAN) + len(VALUATION_QUERY_PLAN) == 12  # production budget
    prof = StartupProfile(company_name="Jane Pty Ltd", sector="accounting services", description="d", country="AU")
    q = precedents_query(prof, 2026)
    assert q == "accounting services business acquisition EBITDA multiple Australia 2026" and "precedents" in PURPOSE

    class Counting:
        def __init__(self):
            self.queries = []

        def search(self, query, count=8, **_):
            self.queries.append(query)
            return [{"url": f"https://deal{i}.example/", "title": "deal", "description": "sold for 5x EBITDA"}
                    for i in range(3)]

    deps = studio_deps(tmp_path)
    prov = Counting()
    deps.search = SearchChain([("claude", prov)])
    deps.fetcher = lambda url: f"{url}: acquired for 5.5 times EBITDA in March 2026"
    searches = [{"kind": k} for k in QUERY_PLAN[:5]]
    assert search_precedents(prof, "vp", searches, date(2026, 9, 27), deps) == 3
    assert searches[-1]["kind"] == "precedents" and prov.queries == [q]
    assert search_precedents(prof, "vp", searches, date(2026, 9, 27), deps) == 0  # once per valuation
    full = [{"kind": f"k{i}"} for i in range(deps.settings.search_max_queries)]
    assert search_precedents(prof, "vq", full, date(2026, 9, 27), deps) == 0 and len(prov.queries) == 1
