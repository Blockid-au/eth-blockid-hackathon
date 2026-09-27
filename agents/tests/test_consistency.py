"""tools/consistency.py: cross-source rules, arithmetic, plausibility caps, concentration, ARR hygiene."""
from blockid_agents.schemas import MetricValue
from blockid_agents.tools import consistency as cons


def mv(v, source, level=0, quote=""):
    return MetricValue(value=v, source=source, level=level, quote=quote)


def test_typed_matching_document_is_promoted_to_l2():
    out, flags = cons.resolve({"arr_aud": [mv(1_000_000, "self_reported"), mv(1_030_000, "deck")]}, "seed")
    assert out["arr_aud"].level == 2 and out["arr_aud"].source == "self_reported" and not flags


def test_thirty_percent_gap_flags_and_uses_lower():
    out, flags = cons.resolve({"arr_aud": [mv(1_300_000, "self_reported"), mv(1_000_000, "deck")]}, "seed")
    assert out["arr_aud"].value == 1_000_000
    assert flags[0].code == "cross_source_gap" and flags[0].action == "lower_used"
    out, _ = cons.resolve({"arr_aud": [mv(1_300_000, "cited"), mv(1_000_000, "self_reported")]}, "seed")
    assert out["arr_aud"].value == 1_300_000  # the higher one is L3 (independent source)
    out, _ = cons.resolve({"burn_multiple": [mv(1.0, "self_reported"), mv(3.0, "csv")]}, "seed")
    assert out["burn_multiple"].value == 3.0  # lower-is-better: the conservative value is the higher one


def test_arithmetic_and_bounds():
    out, flags = cons.resolve({"arr_aud": [mv(2_000_000, "self_reported")], "mrr_aud": [mv(100_000, "self_reported")],
                               "nrr_pct": [mv(85, "self_reported")], "grr_pct": [mv(104, "self_reported")],
                               "runway_months": [mv(36, "self_reported")], "cash_aud": [mv(1e6, "self_reported")],
                               "burn_monthly_aud": [mv(1e5, "self_reported")]}, "seed")
    codes = {f.code for f in flags}
    assert {"arr_vs_mrr", "nrr_below_grr", "grr_over_100", "runway_vs_cash"} <= codes
    assert out["grr_pct"].value == 100 and out["runway_months"].value == 10


def test_plausibility_cap_public_contradiction_concentration_run_rate():
    out, flags = cons.resolve({"yoy_growth_pct": [mv(5000, "self_reported")],
                               "active_users_monthly": [mv(2_000_000, "self_reported")],
                               "top_customer_share_pct": [mv(60, "self_reported")],
                               "arr_aud": [mv(5e6, "site", quote="annualised run rate of $5m")]}, "series-a",
                              lookups={"tranco": {}, "app_store": {"rating_count": 3}})
    codes = {f.code for f in flags}
    assert {"implausible", "public_contradiction", "concentration_high", "arr_run_rate"} <= codes
    assert out["yoy_growth_pct"].value == 250  # series-a P90
    assert "arr_aud" not in out and out["revenue_run_rate_aud"].value == 5e6
    assert cons.stability(40, 60, typed_only=True).code == "rescore_jump"
    assert cons.stability(40, 60, typed_only=False) is None
