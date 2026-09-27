"""Valuation v5 engine (tools/valuation_methods.py, tools/valuation_v5.py): known answers, oracle checks, method rules,
blend / outlier / confidence, tokenisation proposal and exact recompute from stored inputs. Pure — no DB, no LLM."""
import copy
import json
from types import MappingProxyType

import numpy_financial as npf
import pytest

from blockid_agents.schemas import (
    Anchor,
    DimensionScore,
    MarketAnalysis,
    Metrics,
    StartupProfile,
    VerifiedValuationEvidence,
)
from blockid_agents.studio.report_hash import canonical_json
from blockid_agents.tools import market_data, svi
from blockid_agents.tools import valuation_methods as vm
from blockid_agents.tools import valuation_v5 as v5
from blockid_agents.tools.valuation_params import PARAMS, params

P = params("v5")
M = 1_000_000.0


def sme_rows(base=5 * M, growth=0.15, years=5):
    rows, rev = [], base
    for y in range(1, years + 1):
        nr = rev * (1 + growth)
        rows.append({"year": 2026 + y, "revenue": nr, "cogs": 0.0, "opex": nr * 0.8, "d_and_a": nr * 0.03,
                     "capex": nr * 0.035, "tax": None, "nwc": None, "change_nwc": None})
        rev = nr
    return rows


def dcf_inputs(**over):
    rb = vm.cost_of_capital(rf=0.0539, beta_u=0.9, erp=0.06, crp=0.0, size_premium=0.04, tax_rate=0.25)
    base = {"rows": sme_rows(), "base_revenue": 5 * M, "tax_rate": 0.25, "rate_build": rb, "rate_kind": "capm",
            "terminal": "gordon", "g": 0.025, "exit_multiple": 5.0, "net_debt_aud": 0.0, "mid_year": True,
            "evidence": ["projection_ok"]}
    base.update(over)
    return base


# ================================================================== DCF: plan §4.2 worked example
def test_worked_example_fcff_rate_and_ev():
    fc = vm.fcff_series(sme_rows(), tax_rate=0.25, base_revenue=5 * M)
    assert [round(x["fcff"] / M, 2) for x in fc] == [0.63, 0.72, 0.83, 0.96, 1.10]
    rb = dcf_inputs()["rate_build"]
    assert rb["rate"] == pytest.approx(0.1479, abs=1e-6)  # 5.39 % + 0.9 x 6 % + 4 %
    core = vm.dcf_core([x["fcff"] for x in fc], rb["rate"], terminal="gordon", g=0.025)
    assert core["pv_fcff"] == pytest.approx(2.95 * M, abs=5_000)
    assert core["tv"] == pytest.approx(9.18 * M, abs=5_000)
    assert core["pv_tv"] == pytest.approx(4.94 * M, abs=5_000)
    assert core["ev"] == pytest.approx(7.88 * M, abs=5_000)  # A$ within 5k of the plan's A$7.88M
    assert 0.62 < core["tv_share"] < 0.64
    ex = vm.dcf_core([x["fcff"] for x in fc], rb["rate"], terminal="exit", exit_multiple=5.0,
                     final_ebitda=fc[-1]["ebitda"])
    assert ex["tv"] == pytest.approx(10.06 * M, abs=5_000) and ex["pv_tv"] == pytest.approx(5.05 * M, abs=5_000)
    assert ex["ev"] == pytest.approx(7.99 * M, abs=5_000)


def test_dcf_matches_numpy_financial_oracle():
    fc = [x["fcff"] for x in vm.fcff_series(sme_rows(), tax_rate=0.25, base_revenue=5 * M)]
    r = 0.1479
    # end-of-year convention: npv of [0, cf1..cfN]
    core = vm.dcf_core(fc, r, terminal="exit", exit_multiple=1e-9, final_ebitda=0.0, mid_year=False)
    assert core["pv_fcff"] == pytest.approx(npf.npv(r, [0.0, *fc]), rel=1e-12)
    # mid-year convention = end-of-year x (1 + r)^0.5
    mid = vm.dcf_core(fc, r, terminal="exit", exit_multiple=1e-9, final_ebitda=0.0, mid_year=True)
    assert mid["pv_fcff"] == pytest.approx(npf.npv(r, [0.0, *fc]) * (1 + r) ** 0.5, rel=1e-12)


def test_dcf_method_refuses_g_at_or_above_rate_and_negative_terminal():
    m = vm.build("dcf", dcf_inputs(g=0.2), P, "profitable_sme")
    assert m.raw_weight == 0 and m.value_aud == 0 and any(c.code == "g_ge_rate" and c.severity == "error"
                                                          for c in m.checks)
    rows = sme_rows()
    rows[-1]["capex"] = rows[-1]["revenue"]  # final-year FCFF negative
    m = vm.build("dcf", dcf_inputs(rows=rows, exit_multiple=None), P, "profitable_sme")
    assert m.raw_weight == 0 and any(c.code == "negative_terminal_fcff" for c in m.checks)
    # with an exit multiple the terminal value falls back to it (and says so)
    m = vm.build("dcf", dcf_inputs(rows=rows, exit_multiple=5.0), P, "profitable_sme")
    assert m.raw_weight > 0 and m.inputs["result"]["terminal_used"] == "exit"
    assert any("exit multiple used" in n for n in m.notes)


def test_dcf_tv_share_warning_lowers_weight_and_rate_band():
    base = vm.build("dcf", dcf_inputs(), P, "profitable_sme")
    assert base.raw_weight == pytest.approx(1.0 * 0.7)  # SME base 1.0 x projection_ok 0.7
    hi = vm.build("dcf", dcf_inputs(g=0.03, rate_build={**dcf_inputs()["rate_build"], "rate": 0.05}), P,
                  "profitable_sme")
    assert any(c.code == "tv_share" for c in hi.checks)
    assert hi.raw_weight == pytest.approx(0.7 * 0.8)
    assert not any(c.code == "rate_band" for c in hi.checks)  # 5 % is inside the band
    low = vm.build("dcf", dcf_inputs(rate_build={**dcf_inputs()["rate_build"], "rate": 0.25}), P, "profitable_sme")
    assert any(c.code == "rate_band" and c.severity == "warning" for c in low.checks)


def test_sensitivity_grid_centre_is_base_and_range_cells():
    m = vm.build("dcf", dcf_inputs(), P, "profitable_sme")
    g = m.inputs["result"]["sensitivity"]
    assert g["rates"][2] == pytest.approx(0.1479) and g["gs"][2] == pytest.approx(0.025)
    assert g["values"][2][2] == pytest.approx(m.value_aud, abs=0.01)
    assert m.low_aud == pytest.approx(g["values"][4][0], abs=0.01)  # rate +2 pp, g -1 pp
    assert m.high_aud == pytest.approx(g["values"][0][4], abs=0.01)  # rate -2 pp, g +1 pp
    assert m.low_aud < m.value_aud < m.high_aud


def test_dcf_equity_bridge_and_no_dlom():
    a = vm.build("dcf", dcf_inputs(), P, "profitable_sme")
    b = vm.build("dcf", dcf_inputs(net_debt_aud=1 * M), P, "profitable_sme")
    assert a.value_aud - b.value_aud == pytest.approx(1 * M, abs=0.01)
    assert "dlom" not in a.inputs  # the size premium is in the rate: no marketability discount on top


# ================================================================== multiples
def test_ebitda_comps_quartiles_and_dlom_only_on_listed():
    m = vm.build("ebitda_multiple", {"ebitda_aud": 1 * M, "band": [3.5, 5.0, 7.0], "dlom": 0.25,
                                     "net_debt_aud": 0, "evidence": ["management_actuals", "industry_table"]},
                 P, "profitable_sme")
    assert m.value_aud == pytest.approx(3.75 * M)  # plan worked example: 1.0 x 5.0 x (1 - 25 %)
    q = vm.build("ebitda_multiple", {"ebitda_aud": 1 * M, "multiples": [4, 5, 6, 8], "dlom": 0.0,
                                     "evidence": ["management_actuals", "comps_3plus"]}, P, "profitable_sme")
    assert q.value_aud == pytest.approx(5.5 * M) and q.low_aud == pytest.approx(4.75 * M)
    assert q.high_aud == pytest.approx(6.5 * M)
    one = vm.build("ebitda_multiple", {"ebitda_aud": 1 * M, "multiples": [5], "dlom": 0.0}, P, "profitable_sme")
    assert (one.low_aud, one.high_aud) == (pytest.approx(3.5 * M), pytest.approx(7 * M))
    assert vm.build("ebitda_multiple", {"ebitda_aud": -1, "band": [1, 2, 3]}, P, "profitable_sme").raw_weight == 0


def test_precedents_no_dlom_recency_weighted_median_and_band():
    band = vm.build("precedents", {"metric_aud": 1 * M, "basis": "ebitda", "band": [3.5, 4.5, 6.0],
                                   "evidence": ["management_actuals", "sector_cited"]}, P, "profitable_sme")
    assert band.value_aud == pytest.approx(4.5 * M)  # plan worked example (no DLOM)
    assert band.raw_weight == pytest.approx(0.8 * 0.9 * 0.7)
    deals = [{"multiple": 4.0, "age_months": 6}, {"multiple": 5.0, "age_months": 60}, {"multiple": 9.0,
                                                                                       "age_months": 70}]
    m = vm.build("precedents", {"metric_aud": 1 * M, "basis": "ebitda", "deals": deals,
                                "evidence": ["management_actuals", "deals_3plus"]}, P, "profitable_sme")
    # weights 1.0 / 0.4 / 0.4: cumulative 1.0 of 1.8 passes half at the first (4.0x)
    assert m.value_aud == pytest.approx(4.0 * M)
    assert vm.weighted_median([(1, 1), (2, 1)]) == 1.5 and vm.weighted_median([(1, 1), (2, 3)]) == 2


def test_percentile_matches_numpy_linear():
    import numpy as np

    xs = [3.1, 7.4, 2.2, 9.0, 5.5]
    for q in (0.25, 0.5, 0.75):
        assert vm.percentile(xs, q) == pytest.approx(float(np.percentile(xs, q * 100)))


# ================================================================== VC / First Chicago / startup methods
def test_vc_method_multiple_and_irr_forms_and_retention():
    m = vm.build("vc_method", {"exit_metric_aud": 10 * M, "exit_multiple": 5.0, "years_to_exit": 5,
                               "target_multiples": [20, 25, 30], "investment_aud": 0.5 * M,
                               "evidence": ["projection_ok"]}, P, "seed")
    assert m.value_aud == pytest.approx(50 * M / 25 - 0.5 * M)
    assert m.low_aud == pytest.approx(50 * M / 30 - 0.5 * M) and m.high_aud == pytest.approx(50 * M / 20 - 0.5 * M)
    assert m.raw_weight == pytest.approx(0.8 * 0.7)
    irr = vm.build("vc_method", {"exit_metric_aud": 10 * M, "exit_multiple": 5.0, "years_to_exit": 5,
                                 "target_irr": 0.5}, P, "seed")
    assert irr.value_aud == pytest.approx(50 * M / 1.5 ** 5)
    half = vm.build("vc_method", {"exit_metric_aud": 10 * M, "exit_multiple": 5.0, "years_to_exit": 5,
                                  "target_multiples": [20, 25, 30], "retention": 0.5}, P, "seed")
    assert half.value_aud == pytest.approx(50 * M * 0.5 / 25)
    none = vm.build("vc_method", {"exit_metric_aud": 1 * M, "exit_multiple": 1.0, "years_to_exit": 5,
                                  "target_multiples": [20, 25, 30], "investment_aud": 5 * M}, P, "seed")
    assert none.raw_weight == 0


def test_first_chicago_probabilities_and_scenarios():
    inp = {**dcf_inputs(), "rate_kind": "startup", "rate_build": {"rate": 0.4},
           "scenarios": [["worst", 0.25, 0.5], ["base", 0.5, 1.0], ["best", 0.25, 1.25]]}
    m = vm.build("first_chicago", inp, P, "series_a")
    sc = {s["scenario"]: s["value_aud"] for s in m.inputs["result"]["scenarios"]}
    assert sc["worst"] < sc["base"] < sc["best"]
    assert m.value_aud == pytest.approx(0.25 * sc["worst"] + 0.5 * sc["base"] + 0.25 * sc["best"])
    base_dcf = vm.build("dcf", {**dcf_inputs(), "rate_kind": "startup", "rate_build": {"rate": 0.4}}, P, "growth")
    assert sc["base"] == pytest.approx(base_dcf.value_aud, abs=0.01)
    bad = vm.build("first_chicago", {**inp, "scenarios": [["a", 0.5, 1.0], ["b", 0.4, 1.0]]}, P, "series_a")
    assert bad.raw_weight == 0 and bad.checks[0].code == "probabilities"
    assert vm.scale_rows([{"revenue": 100.0, "cogs": 10.0, "opex": 20.0, "d_and_a": 1.0, "capex": 2.0}], 50.0,
                         0.5)[0]["revenue"] == pytest.approx(75.0)  # growth 100 % x 0.5


def test_scorecard_payne_mapping_neutral_is_base():
    lines = {k: {"score": 50} for k in P["scorecard_weights"]}
    m = vm.build("scorecard", {"stage": "seed", "base_pre_money_aud": 12 * M, "lines": lines}, P, "seed")
    assert m.value_aud == pytest.approx(12 * M) and m.inputs["factor"] == pytest.approx(1.0)
    lines["team"]["score"] = 100  # +0.5 x 0.30
    m = vm.build("scorecard", {"stage": "seed", "base_pre_money_aud": 12 * M, "lines": lines,
                               "evidence": ["ai_suggested"]}, P, "seed")
    assert m.value_aud == pytest.approx(12 * M * 1.15) and m.raw_weight == pytest.approx(0.6 * 0.5)
    assert (m.low_aud, m.high_aud) == (pytest.approx(m.value_aud * 0.75), pytest.approx(m.value_aud * 1.25))


def test_berkus_cap_and_rfs_floor():
    full = vm.build("berkus", {"scores": {k: 100 for k in vm.BERKUS_KEYS}, "cap_per_factor_aud": 750_000}, P, "idea")
    assert full.value_aud == pytest.approx(5 * 750_000)
    over = vm.build("berkus", {"scores": {k: 250 for k in vm.BERKUS_KEYS}, "cap_per_factor_aud": 750_000}, P, "idea")
    assert over.value_aud == full.value_aud  # capped at 100 per milestone
    assert vm.build("berkus", {"scores": {}, "cap_per_factor_aud": 750_000}, P, "idea").raw_weight == 0
    worst = vm.build("rfs", {"base_pre_money_aud": 2 * M, "ratings": {k: -2 for k in vm.RFS_KEYS}}, P, "pre_seed")
    assert worst.value_aud == pytest.approx(0.2 * 2 * M)  # floor 0.2 x base
    best = vm.build("rfs", {"base_pre_money_aud": 2 * M, "ratings": {"management": 2, "technology": 1}}, P, "pre_seed")
    assert best.value_aud == pytest.approx(2 * M + 3 * 0.125 * 2 * M) and best.inputs["net_steps"] == 3


# ================================================================== class, params, market data
@pytest.mark.parametrize("kw,expected", [
    ({"stage": "growth", "listed": True, "ebitda_last_actual": None, "revenue_aud": 5e7, "growth_pct": 50,
      "raised_aud": None}, "listed"),
    ({"stage": "series-a", "listed": False, "ebitda_last_actual": 1e6, "revenue_aud": 5e6, "growth_pct": 12,
      "raised_aud": 0}, "profitable_sme"),
    ({"stage": "series-a", "listed": False, "ebitda_last_actual": 1e6, "revenue_aud": 5e6, "growth_pct": 45,
      "raised_aud": 0}, "series_a"),  # growing fast: not an SME
    ({"stage": "series-a", "listed": False, "ebitda_last_actual": 1e6, "revenue_aud": 5e6, "growth_pct": 10,
      "raised_aud": 9e6}, "series_a"),  # VC-funded beyond 1x revenue
    ({"stage": "seed", "listed": False, "ebitda_last_actual": -2e5, "revenue_aud": 4e5, "growth_pct": 80,
      "raised_aud": 1e6}, "seed"),
    ({"stage": "pre-seed", "listed": False, "ebitda_last_actual": None, "revenue_aud": 0, "growth_pct": None,
      "raised_aud": None}, "pre_seed"),
    ({"stage": "idea", "listed": False, "ebitda_last_actual": None, "revenue_aud": 0, "growth_pct": None,
      "raised_aud": None}, "idea"),
])
def test_classify_valuation_class(kw, expected):
    assert vm.classify_valuation_class(**kw)[0] == expected


def test_params_frozen_and_market_dataset():
    assert isinstance(PARAMS["v5"], MappingProxyType)
    with pytest.raises(TypeError):
        PARAMS["v5"]["dlom"] = 0.5  # type: ignore[index]
    with pytest.raises(ValueError):
        params("v9")
    snap = market_data.snapshot("2026-09-26")
    assert snap.country("AU")["erp"] == 0.06 and snap.country("VN")["erp"] == 0.0813  # owner decision 6
    assert len(snap.sha256) == 64 and snap.industry("nope")["label"].startswith("Total market")
    assert snap.industry_for_text("B2B SaaS software for farms") == "software"
    assert snap.size_premium(3e6) == 0.06 and snap.size_premium(3e7) == 0.03
    assert snap.precedent_band("software", 5e5)[0] == "small" and snap.precedent_band("software", 6e6)[0] == "tech"
    with pytest.raises(ValueError):
        market_data.snapshot("../etc/passwd")


def test_tokenisation_proposal_default_price_by_stage():
    t = v5.tokenisation_proposal(4_321_000, 3e6, 6e6, "pre-seed", shares_fd=None, planned_raise=0, p=P)
    assert t["default_price_for_stage_aud"] == 0.10 and t["total_shares"] == 43_200_000
    assert t["recommended_price_per_share_aud"] == pytest.approx(0.1, abs=5e-4) and t["basis"] == "new_company"
    assert v5.tokenisation_proposal(4e6, 3e6, 6e6, "seed", shares_fd=None, planned_raise=0, p=P)[
        "default_price_for_stage_aud"] == 0.25
    for st in ("series-a", "growth"):
        assert v5.tokenisation_proposal(4e7, 3e7, 6e7, st, shares_fd=None, planned_raise=0, p=P)[
            "default_price_for_stage_aud"] == 1.0
    ex = v5.tokenisation_proposal(10e6, 8e6, 12e6, "seed", shares_fd=20_000_000, planned_raise=1e6, p=P)
    assert ex["basis"] == "existing_shares" and ex["recommended_price_per_share_aud"] == 0.5
    assert ex["new_shares"] == 2_000_000 and ex["dilution_pct"] == pytest.approx(9.09, abs=0.01)
    assert ex["offer_price_low_aud"] == 0.4 and ex["post_money_aud"] == 11e6
    tiny = v5.tokenisation_proposal(500, 400, 600, "idea", shares_fd=None, planned_raise=0, p=P)
    assert tiny["total_shares"] == 10_000  # lower bound


# ================================================================== blend: outliers, confidence
def _m(method, value, raw, **inputs):
    return vm.ValuationMethod(method=method, label=method, value_aud=value, low_aud=value * 0.8, high_aud=value * 1.2,
                              raw_weight=raw, inputs=inputs)


def test_outlier_rule_excludes_the_divergent_method_with_a_note():
    ms = [_m("revenue_multiple", 10 * M, 0.5, multiple_source="comps_3plus", n=3),
          _m("ebitda_multiple", 11 * M, 0.5), _m("dcf", 60 * M, 0.7)]
    t = v5.blend_v5(ms, "profitable_sme", P)
    dcf = next(m for m in t.methods if m.method == "dcf")
    assert dcf.weight == 0 and any("away from the other methods" in n for n in dcf.notes)
    assert t.value_aud == pytest.approx(10.5 * M)
    assert any("left out" in r for r in t.confidence_reasons)


def test_fresh_anchor_never_excluded_two_methods_drop_the_weaker():
    anchor = _m("market_anchor", 100 * M, 1.6, anchors=[{"kind": "priced_round", "age_months": 6}])
    rev = _m("revenue_multiple", 10 * M, 0.4, multiple_source="default", n=0)
    t = v5.blend_v5([anchor, rev], "growth", P)
    assert [m.weight for m in t.methods] == [1.0, 0.0] and t.value_aud == 100 * M
    old = _m("market_anchor", 100 * M, 0.3, anchors=[{"kind": "priced_round", "age_months": 50}])
    t = v5.blend_v5([old, _m("revenue_multiple", 10 * M, 0.4, multiple_source="default", n=0)], "growth", P)
    assert t.methods[0].weight == 0 and t.methods[1].weight == 1.0  # stale anchor is the weaker one


def test_stage_benchmark_alone_and_far_away():
    st = vm.build("stage_scorecard", {"stage": "seed", "benchmark": [2e6, 5e6, 1e7], "svi_factor": 1.0}, P, "seed")
    assert v5.blend_v5([st], "seed", P).methods[0].weight == 1.0
    st = vm.build("stage_scorecard", {"stage": "seed", "benchmark": [2e6, 5e6, 1e7], "svi_factor": 1.0}, P, "seed")
    rev = _m("revenue_multiple", 200 * M, 0.4, multiple_source="comps_3plus", n=3)
    t = v5.blend_v5([rev, st], "seed", P)
    assert t.methods[1].weight == 0 and "not used" in t.methods[1].notes[-1]


def test_confidence_levels():
    listed = _m("market_anchor", 100 * M, 5.0, anchors=[{"kind": "market_cap", "age_months": 0}])
    assert v5.blend_v5([listed], "listed", P).confidence == "high"
    startup = [vm.build("scorecard", {"stage": "seed", "base_pre_money_aud": 12 * M,
                                      "lines": {k: {"score": 50} for k in P["scorecard_weights"]}}, P, "seed")]
    assert v5.blend_v5(startup, "seed", P).confidence == "low"
    rev = _m("revenue_multiple", 10 * M, 0.4, multiple_source="sector_cited", n=1)
    assert v5.blend_v5([rev], "seed", P).confidence == "medium"
    e = _m("ebitda_multiple", 10 * M, 0.9, evidence=["management_actuals", "comps_3plus"])
    pr = _m("precedents", 12 * M, 0.9, evidence=["management_actuals", "deals_3plus"])
    t = v5.blend_v5([e, pr], "profitable_sme", P)
    assert t.confidence == "high" and all(isinstance(r, str) and r for r in t.confidence_reasons)


# ================================================================== end to end: triangulate_v5 + exact recompute
def _dims(score=60, basis="human"):
    return {k: DimensionScore(score=score, basis=basis) for k in svi.WEIGHTS}


def _projection(years):
    return {"parsed": {"currency": "AUD", "fx_rate_to_aud": 1.0, "cash": 200_000, "debt": 0, "planned_raise": 0,
                       "shares_fd": None, "audited": False, "years": years, "years_used": years},
            "checks": [], "sha256": "ab" * 32, "attested_by": "0xabc", "attested_at": "2026-09-27T00:00:00+00:00"}


def _sme_years():
    ys = [{"year": 2025, "actual": True, "revenue": 4.35 * M, "cogs": 1.3 * M, "opex": 2.2 * M, "d_and_a": 0.13 * M,
           "capex": 0.15 * M, "tax": None, "nwc": None, "change_nwc": None},
          {"year": 2026, "actual": True, "revenue": 5 * M, "cogs": 1.5 * M, "opex": 2.5 * M, "d_and_a": 0.15 * M,
           "capex": 0.175 * M, "tax": None, "nwc": None, "change_nwc": None}]
    rev = 5 * M
    for y in range(2027, 2032):
        rev *= 1.1
        ys.append({"year": y, "actual": False, "revenue": rev, "cogs": rev * 0.3, "opex": rev * 0.5,
                   "d_and_a": rev * 0.03, "capex": rev * 0.035, "tax": None, "nwc": None, "change_nwc": None})
    return ys


def _run(profile, dims, projection=None, anchors=(), vi=None, listing=None):
    ve = VerifiedValuationEvidence(anchors=list(anchors), listing=listing, as_of="2026-09-27")
    tri = v5.triangulate_v5(profile=profile, market=MarketAnalysis(market_summary="m"), ve=ve, dims=dims,
                            svi_index=60.0, self_reported=None, v5_inputs=vi, projection=projection,
                            stage_ranges=svi.STAGE_PRE_REVENUE_RANGE, as_of="2026-09-27")
    return tri


def _roundtrip(tri):
    stored = json.loads(canonical_json(tri.model_dump()))
    r = v5.recompute_v5(copy.deepcopy(stored))
    assert (r["low"], r["mid"], r["high"]) == (round(tri.low_aud, -3), round(tri.value_aud, -3),
                                               round(tri.high_aud, -3))
    assert r["confidence"] == tri.confidence
    return stored


def test_profitable_sme_three_pillars_and_recompute():
    p = StartupProfile(company_name="Acme Pty Ltd", sector="accounting services", description="bookkeeping firm",
                       stage="seed", metrics=Metrics(revenue_ttm_aud=5 * M, revenue_growth_yoy_pct=15))
    tri = _run(p, _dims(), projection=_projection(_sme_years()))
    assert tri.version == "v5" and tri.valuation_class == "profitable_sme"
    used = {m.method for m in tri.methods if m.weight > 0}
    assert {"dcf", "ebitda_multiple", "precedents"} <= used  # the classic three pillars
    assert tri.projections["label"].startswith("Based on management projections")
    assert tri.without_projections and tri.without_projections["value_aud"] > 0
    assert {b["method"] for b in tri.football_field} == {m.method for m in tri.methods}
    assert tri.tokenisation["default_price_for_stage_aud"] in (0.1, 0.25, 1.0)
    stored = _roundtrip(tri)
    tampered = copy.deepcopy(stored)
    dcf = next(m for m in tampered["methods"] if m["method"] == "dcf")
    dcf["inputs"]["g"] = 0.0
    assert v5.recompute_v5(tampered)["mid"] != round(tri.value_aud, -3)  # stored inputs drive the recompute


def test_pre_seed_startup_methods_ai_suggested_weight_and_confirmation():
    p = StartupProfile(company_name="Tiny", sector="consumer app", description="an app", stage="pre-seed",
                       metrics=Metrics())
    factors = {"berkus": {k: {"score": 40, "sources": []} for k in vm.BERKUS_KEYS},
               "rfs": {k: {"rating": 0, "sources": []} for k in vm.RFS_KEYS}}
    ai = _run(p, _dims(55, "ai_suggested"), vi={"startup_factors": factors, "factors_basis": "ai_suggested"})
    assert ai.valuation_class in ("pre_seed", "idea")
    by = {m.method: m for m in ai.methods}
    assert {"scorecard", "berkus", "rfs"} <= set(by)
    assert by["berkus"].raw_weight == pytest.approx(0.8 * 0.5)  # ai_suggested x 0.5
    hu = _run(p, _dims(55, "human"), vi={"startup_factors": factors, "factors_basis": "human"})
    assert {m.method: m for m in hu.methods}["berkus"].raw_weight == pytest.approx(0.8)
    assert ai.confidence == "low" and hu.confidence == "low"
    _roundtrip(ai)
    _roundtrip(hu)


def test_listed_and_anchor_led_growth_recompute():
    p = StartupProfile(company_name="Listed Co", sector="online marketplace", description="marketplace",
                       stage="growth", metrics=Metrics(revenue_ttm_aud=50 * M))
    cap = Anchor(kind="market_cap", amount=98e6, currency="AUD", amount_aud=98e6, fx_rate_to_aud=1.0,
                 fx_as_of="2026-09-26", as_of="2026-09", age_months=0, source_url="https://x", quote="q")
    from blockid_agents.schemas import Listing

    tri = _run(p, _dims(), anchors=[cap], listing=Listing(exchange="ASX", ticker="LST", source_url="https://x",
                                                          quote="Listed Co (ASX: LST)"))
    assert tri.valuation_class == "listed" and tri.confidence == "high"
    assert next(m for m in tri.methods if m.method == "market_anchor").weight >= 0.9
    _roundtrip(tri)


def test_admin_assumptions_flow_into_inputs():
    p = StartupProfile(company_name="Acme Pty Ltd", sector="accounting services", description="firm",
                       stage="seed", metrics=Metrics(revenue_ttm_aud=5 * M, revenue_growth_yoy_pct=15))
    base = _run(p, _dims(), projection=_projection(_sme_years()))
    adj = _run(p, _dims(), projection=_projection(_sme_years()),
               vi={"assumptions": {"dcf.g": 0.01, "weights.dcf": 1.4, "dlom": 0.3}})
    d0 = next(m for m in base.methods if m.method == "dcf")
    d1 = next(m for m in adj.methods if m.method == "dcf")
    assert d1.inputs["g"] == 0.01 and d1.value_aud < d0.value_aud
    assert d1.raw_weight == pytest.approx(1.4) and d1.inputs["weight_override"] == 1.4
    capped = _run(p, _dims(), projection=_projection(_sme_years()), vi={"assumptions": {"weights.dcf": 9}})
    assert next(m for m in capped.methods if m.method == "dcf").raw_weight == pytest.approx(2.0)  # <= 2x rule
    assert next(m for m in adj.methods if m.method == "ebitda_multiple").inputs["dlom"] == 0.3
    _roundtrip(adj)
    cur = v5.current_assumptions(json.loads(canonical_json(adj.model_dump())))
    assert cur["dcf.g"] == 0.01 and cur["weights.dcf"] == 1.4


def test_v3_triangulation_dump_unchanged_by_v5_schema():
    """A v3 Triangulation / ValuationMethod dump has exactly the pre-v5 keys (report hashes unchanged)."""
    from blockid_agents.tools.triangulate import blend, stage_method

    t = blend([stage_method("seed", (1, 2, 3), 1.0)])
    d = t.model_dump()
    assert set(d) == {"version", "value_aud", "low_aud", "high_aud", "confidence", "confidence_reasons", "methods",
                      "listed", "listing", "as_of", "fx_as_of"}
    assert set(d["methods"][0]) == {"method", "label", "value_aud", "low_aud", "high_aud", "raw_weight", "weight",
                                    "inputs", "sources", "notes"}
