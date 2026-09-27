"""tools/stage.py: evidence-based stage rules (15 table cases), stage profiles, benchmark scoring, AU bases."""
import json

import pytest

from blockid_agents.tools import stage as st

T = "2026-09-27"


@pytest.mark.parametrize("ev,stage,basis,conflict", [
    ({"listed": True, "listing_ref": "ASX: ART", "revenue_aud": 1e5}, "growth", "listing", False),
    ({"rounds": [{"round_type": "pre-seed", "as_of": "2026-03"}]}, "pre-seed", "round", False),
    ({"rounds": [{"round_type": "Angel round", "as_of": "2026-03"}]}, "pre-seed", "round", False),
    ({"rounds": [{"round_type": "Seed", "as_of": "2025-11"}], "revenue_aud": 400e3}, "seed", "round", False),
    ({"rounds": [{"round_type": "Series A", "as_of": "2026-01"}], "revenue_aud": 3e6}, "series-a", "round", False),
    ({"rounds": [{"round_type": "Series C", "as_of": "2025-06"}]}, "growth", "round", False),
    ({"rounds": [{"round_type": "Series A", "as_of": "2026-01"}], "revenue_aud": 100e3}, "pre-seed", "revenue", True),
    ({"rounds": [{"round_type": "Series A", "as_of": "2021-01"}], "revenue_aud": 500e3}, "seed", "revenue", False),
    ({"revenue_aud": 0, "product_live": False}, "idea", "revenue", False),
    ({"revenue_aud": 0}, "pre-seed", "revenue", False),
    ({"revenue_aud": 149_999}, "pre-seed", "revenue", False),
    ({"revenue_aud": 1.5e6}, "series-a", "revenue", False),
    ({"revenue_aud": 20e6}, "growth", "revenue", False),
    ({"raised_to_date_aud": 3e6}, "seed", "raised", False),
    ({"hint": "series-a"}, "series-a", "hint", False),
    ({}, "seed", "default", False),
])
def test_classify_stage_table(ev, stage, basis, conflict):
    d = st.classify_stage({**ev, "today": T})
    assert (d.stage, d.basis, d.conflict) == (stage, basis, conflict), d.reasons
    assert d.reasons and d.table_version == st.STAGE_TABLE_VERSION


def test_evidence_from_result_uses_anchor_quote_and_typed_round():
    res = {"profile": {"stage": "seed", "metrics": {"revenue_ttm_aud": 0}},
           "valuation_evidence": {"as_of": T, "anchors": [
               {"kind": "priced_round", "quote": "closed a A$12m Series A led by X", "as_of": "2026-02",
                "source_url": "https://news.example/a"}]}}
    d = st.classify_stage(st.evidence_from_result(res, {}))
    assert d.stage == "series-a" and d.basis == "round" and "https://news.example/a" in d.sources
    d2 = st.classify_stage(st.evidence_from_result({"profile": {"stage": "seed"}},
                                                   {"last_round_type": "Seed", "last_round_date": "2026-05",
                                                    "arr_aud": 600_000}))
    assert d2.stage == "seed" and d2.signals == {"hint": "seed", "round": "seed", "revenue": "seed"}
    d3 = st.override_stage(d2, "series-a", "admin", "board-approved term sheet")
    assert d3.stage == "series-a" and d3.basis == "human" and "admin" in d3.reasons[0]


def test_profiles_weights_and_priority_order():
    for s in st.STAGES:
        w = st.weights(s)
        assert abs(sum(w.values()) - 1) < 1e-9 and list(w) == list(st.DIMENSIONS)
        assert w["founder_quality"] == 0.30
        assert w["traction"] >= w["market"] >= w["moat"] >= w["retention"]
    assert st.weights("pre-seed")["product_strength"] == 0.10 and st.weights("growth")["retention"] == 0.12
    assert st.profile("nonsense").stage == "seed"
    json.dumps(st.profile_snapshot("growth", "enterprise", 200_000))


def test_score_vs_benchmark_points_and_direction():
    b = st.benchmark("seed", "arr_aud")
    assert st.score_vs_benchmark(b[1], b, log=True) == 50
    assert st.score_vs_benchmark(b[2], b, log=True) == 75
    assert st.score_vs_benchmark(b[3], b, log=True) == 90
    assert st.score_vs_benchmark(b[0], b, log=True) == 25
    bm = st.benchmark("seed", "burn_multiple")  # lower is better
    assert st.score_vs_benchmark(3.0, bm) == 50 and st.score_vs_benchmark(1.5, bm) == 90
    assert st.score_vs_benchmark(10, bm) == 0 and st.score_vs_benchmark(0.5, bm) == 100
    assert st.score_vs_benchmark(None, b) is None and st.benchmark("pre-seed", "nrr_pct") is None
    assert st.shrink(90, 1) == 74 and st.shrink(10, 1) == 26 and st.shrink(90, 4) == 90
    assert st.SELF_REPORTED_FACTOR == st.LEVEL_SHRINK[1] == 0.6


def test_acv_and_sector_adjustments():
    assert st.benchmark("series-a", "nrr_pct", acv_aud=10_000)[1] == 98
    assert st.benchmark("series-a", "nrr_pct", acv_aud=200_000)[1] == 107
    assert max(st.benchmark("growth", "grr_pct", "enterprise")) <= 100
    assert st.benchmark("seed", "nrr_pct", "services") is None
    assert st.benchmark("seed", "yoy_growth_pct", "hardware")[1] == pytest.approx(45)
    assert st.sector_key("B2B SaaS for dentists") == "saas" and st.sector_key("x", "marketplace") == "marketplace"
    assert st.sector_key("payments platform") == "fintech"


def test_au_round_bases_follow_owner_decision():
    seed = st.au_round_medians("seed")
    assert seed["pre_money_aud"][1] == 16e6 * 1.5 * 0.5 and seed["au_round_adj"] == 0.5
    assert st.au_round_medians("series-a")["round_size_aud"][1] == 11e6
    assert [st.recommended_share_price(s) for s in st.STAGES] == [0.10, 0.10, 0.25, 1.00, 1.00]
    assert st.profile("seed").stage_method_weight_with_others == 0.2
