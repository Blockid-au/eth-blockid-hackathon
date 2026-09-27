"""Valuation v3 (triangulation): anchor / comps / sector verification, listing detection, blending maths, weights,
confidence, bounds, and the public recompute. All offline."""
from datetime import date

import pytest

from blockid_agents.agents import market_evidence as me
from blockid_agents.config import (
    ANCHOR_KIND_WEIGHT,
    PRIVATE_COMPANY_DISCOUNT,
    RANGE_MIN_HALF_WIDTH,
    REVENUE_METHOD_WEIGHT,
)
from blockid_agents.schemas import (
    Anchor,
    AnchorClaim,
    CompClaim,
    CompMultiple,
    EvidenceItem,
    ListingClaim,
    SectorMultiple,
    SectorMultipleClaim,
    StartupProfile,
    ValuationEvidence,
)
from blockid_agents.tools import triangulate as tg

TODAY = date(2026, 9, 27)
URL = "https://news.example.com/airwallex-series-h"
PAGE = ("25 June 2026 — Airwallex has raised $320 million in Series H funding, bringing the company's valuation to "
        "$11 billion, up from its $8 billion valuation in December 2025. Airwallex reached $1.3 billion in "
        "annualized revenue. Rival Wise trades at 6.5x revenue, while Adyen is valued at US$50 billion on "
        "revenue of US$2.5 billion. Public fintech companies trade at a median of 7.6x revenue.")
CAP_URL = "https://stocks.example.com/asx/art"
CAP_PAGE = "Airtasker Limited (ASX: ART) has a market cap of A$97.9 million. Revenue 57.83M."


def ev(url, text, snippet=""):
    return (EvidenceItem(url=url, title=url, snippet=snippet, retrieved_at=1790000000.0, query="q", kind="web"), text)


def profile(name="Airwallex", sector="global payments platform"):
    return StartupProfile(company_name=name, sector=sector, description="d", stage="growth")


def anchor(**kw):
    base = {"kind": "priced_round", "amount": 11e9, "currency": "USD", "date_text": "25 June 2026", "source_url": URL,
            "quote": "bringing the company's valuation to $11 billion"}
    return AnchorClaim(**{**base, **kw})


# ================================================================== dates / recency
@pytest.mark.parametrize("text,out", [("25 June 2026", "2026-06"), ("June 25, 2026", "2026-06"),
                                      ("December 2025", "2025-12"), ("2026-06-25", "2026-06"), ("Q1 2026", "2026-02"),
                                      ("in 2021", "2021"), ("no date", "")])
def test_parse_as_of(text, out):
    assert tg.parse_as_of(text) == out


def test_age_and_recency_bands():
    assert tg.age_months("2026-06", TODAY) == 3
    assert tg.age_months("2024-09", TODAY) == 24
    assert tg.age_months("2021", TODAY) == 62  # a bare year counts from July
    assert tg.age_months("2027-05", TODAY) is None  # future date is not a valid anchor date
    assert tg.recency_factor(3) == 1.0 and tg.recency_factor(24) == 0.8 and tg.recency_factor(30) == 0.45
    assert tg.recency_factor(62) == 0.15 and tg.recency_factor(None) < tg.recency_factor(24)


# ================================================================== anchor verification
def test_anchor_verified_with_dated_fx():
    out = me.verify(ValuationEvidence(anchors=[anchor()]), [ev(URL, PAGE)], profile(), TODAY)
    a = out.anchors[0]
    assert a.amount_aud == 16_500_000_000 and a.fx_rate_to_aud == 1.5 and a.fx_as_of
    assert a.as_of == "2026-06" and a.age_months == 3 and not out.dropped


@pytest.mark.parametrize("kw,reason", [
    ({"quote": "valued at $12 billion by insiders"}, "quote not found"),
    ({"amount": 12e9}, "does not state the amount"),
    ({"source_url": "https://invented.example"}, "not in evidence"),
    ({"currency": "XYZ"}, "not in FX table"),
    ({"amount": 320e6, "quote": "Airwallex has raised $320 million in Series H funding"}, "does not describe a valuation"),
    ({"kind": "market_cap"}, "no listing verified"),
])
def test_anchor_rejections(kw, reason):
    out = me.verify(ValuationEvidence(anchors=[anchor(**kw)]), [ev(URL, PAGE)], profile(), TODAY)
    assert not out.anchors and reason in out.dropped[0]


def test_anchor_page_must_name_company_and_date_must_be_on_page():
    out = me.verify(ValuationEvidence(anchors=[anchor()]), [ev(URL, PAGE)], profile("Canva"), TODAY)
    assert not out.anchors and "does not name the company" in out.dropped[0]
    # a date that is not on the page is ignored; the quote has no year either -> unknown date
    out = me.verify(ValuationEvidence(anchors=[anchor(date_text="March 2019")]), [ev(URL, PAGE)], profile(), TODAY)
    assert out.anchors[0].as_of == "" and out.anchors[0].age_months is None


def test_quote_may_come_from_search_snippet():
    snip = "Airwallex valued at US$8 billion in December 2025 Series G"
    c = anchor(amount=8e9, quote="Airwallex valued at US$8 billion", date_text="December 2025")
    out = me.verify(ValuationEvidence(anchors=[c]), [ev(URL, "", snippet=snip)], profile(), TODAY)
    assert out.anchors[0].amount_aud == 12e9 and out.anchors[0].age_months == 9


# ================================================================== listing + market cap
def test_listing_detected_by_code_and_market_cap_dated_by_fetch():
    p = profile("Airtasker Limited", "local services marketplace")
    listing = me.detect_listing(p, [(CAP_URL, CAP_PAGE)])
    assert (listing.exchange, listing.ticker) == ("ASX", "ART") and "Airtasker" in listing.quote
    assert me.detect_listing(p, [(CAP_URL, "Some other company (ASX: XYZ) reported")]) is None
    cap = AnchorClaim(kind="market_cap", amount=97.9e6, currency="AUD", source_url=CAP_URL,
                      quote="has a market cap of A$97.9 million")
    out = me.verify(ValuationEvidence(anchors=[cap]), [ev(CAP_URL, CAP_PAGE)], p, date(2026, 9, 1), listing=listing)
    a = out.anchors[0]
    assert a.kind == "market_cap" and a.amount_aud == 97_900_000 and a.as_of  # dated by the page fetch time
    assert out.listing.ticker == "ART"


def test_listing_claim_needs_verbatim_quote():
    p = profile("Airtasker Limited")
    bad = ValuationEvidence(listing=ListingClaim(exchange="NYSE", ticker="TSK", source_url=CAP_URL,
                                                 quote="Airtasker (NYSE: TSK)"))
    out = me.verify(bad, [ev(CAP_URL, CAP_PAGE)], p, TODAY)
    assert out.listing is None and "listing" in out.dropped[0]
    good = ValuationEvidence(listing=ListingClaim(exchange="ASX", ticker="ART", source_url=CAP_URL,
                                                  quote="Airtasker Limited (ASX: ART)"))
    assert me.verify(good, [ev(CAP_URL, CAP_PAGE)], p, TODAY).listing.ticker == "ART"


# ================================================================== comps + sector multiples
def test_comps_stated_computed_self_and_bounds():
    claims = ValuationEvidence(comps=[
        CompClaim(name="Wise", public=True, multiple=6.5, source_url=URL, quote="Rival Wise trades at 6.5x revenue"),
        CompClaim(name="Adyen", public=True, valuation=50e9, revenue=2.5e9, source_url=URL,
                  quote="Adyen is valued at US$50 billion", revenue_quote="on revenue of US$2.5 billion"),
        CompClaim(name="Airwallex", multiple=8.5, source_url=URL, quote="Airwallex reached $1.3 billion"),
        CompClaim(name="Wise", multiple=65, source_url=URL, quote="Rival Wise trades at 6.5x revenue"),
        CompClaim(name="Stripe", multiple=20, source_url=URL, quote="Stripe trades at 20x revenue"),
    ])
    out = me.verify(claims, [ev(URL, PAGE)], profile(), TODAY)
    got = {c.name: (c.multiple, c.basis) for c in out.comps}
    assert got == {"Wise": (6.5, "stated"), "Adyen": (20.0, "valuation/revenue")}
    reasons = " | ".join(out.dropped)
    assert "the company itself" in reasons and "Wise (https://news.example.com/airwallex-series-h): quote does not " \
        "state a multiple" in reasons  # 65x is not what the quote says
    assert "quote not found" in reasons  # Stripe: not on the page


def test_sector_multiple_needs_multiple_and_revenue_words():
    claims = ValuationEvidence(sector_multiples=[
        SectorMultipleClaim(multiple=7.6, source_url=URL, quote="Public fintech companies trade at a median of 7.6x revenue"),
        SectorMultipleClaim(multiple=11, source_url=URL, quote="bringing the company's valuation to $11 billion"),
    ])
    out = me.verify(claims, [ev(URL, PAGE)], profile(), TODAY)
    assert [s.multiple for s in out.sector_multiples] == [7.6]
    assert "does not state a revenue multiple" in out.dropped[0]


# ================================================================== blending maths
def A(kind="priced_round", aud=16.5e9, age=3.0, url=URL):
    return Anchor(kind=kind, amount=aud, currency="AUD", amount_aud=aud, fx_rate_to_aud=1, fx_as_of="x",
                  as_of="2026-06", age_months=age, source_url=url, quote="q")


def tri(anchors=(), rev=0.0, rsrc="website", comps=(), sectors=(), mm=None, listed=False, stage="growth",
        factor=1.0):
    return tg.triangulate(anchors=list(anchors), listed=listed, revenue_aud=rev, revenue_source=rsrc, revenue_ref="",
                          comps=list(comps), sectors=list(sectors), market_multiples=mm,
                          default=("default", (2.0, 3.5, 6.0)), stage=stage,
                          stage_benchmark=(30e6, 80e6, 200e6), svi_factor=factor, as_of="2026-09-27")


def comp(name, m, public=True):
    return CompMultiple(name=name, multiple=m, public=public, source_url=f"https://c.example/{name}", quote="q")


def test_blend_is_weighted_arithmetic_mean_and_weights_sum_to_one():
    t = tri([A()], rev=1.95e9, comps=[comp("a", 5), comp("b", 7), comp("c", 9)])
    used = [m for m in t.methods if m.weight > 0]
    assert abs(sum(m.weight for m in used) - 1) < 1e-3
    an, rv = (next(m for m in t.methods if m.method == k) for k in ("market_anchor", "revenue_multiple"))
    assert an.raw_weight == ANCHOR_KIND_WEIGHT["priced_round"] * 1.0
    assert rv.raw_weight == pytest.approx(REVENUE_METHOD_WEIGHT * 1.0 * 0.9)
    assert rv.value_aud == pytest.approx(1.95e9 * 7 * (1 - PRIVATE_COMPANY_DISCOUNT))  # median, public comps
    assert t.value_aud == pytest.approx(sum(m.weight * m.value_aud for m in used), rel=1e-3)
    stage = next(m for m in t.methods if m.method == "stage_scorecard")
    assert stage.weight == 0 and "not used" in stage.notes[-1]  # 80M is > 5x away from ~13B
    assert t.low_aud <= t.value_aud * (1 - RANGE_MIN_HALF_WIDTH[t.confidence]) + 1
    assert t.high_aud >= t.value_aud * (1 + RANGE_MIN_HALF_WIDTH[t.confidence]) - 1


def test_old_anchor_weighs_less_and_lowers_confidence():
    sec = [SectorMultiple(multiple=14, source_url="s", quote="q")]  # 1e9 x 14 x 0.75 = 10.5B, within 2x of 16.5B
    fresh, old = tri([A(age=3)], rev=1e9, sectors=sec), tri([A(age=48)], rev=1e9, sectors=sec)
    w = lambda t: next(m.weight for m in t.methods if m.method == "market_anchor")
    assert w(fresh) > w(old)
    assert fresh.confidence == "high" and old.confidence == "medium"
    assert any("48 months old" in n for m in old.methods for n in m.notes)


def test_anchors_within_3_months_are_combined_older_ones_shown_only():
    t = tri([A(aud=16.5e9, age=3), A(kind="secondary_sale", aud=12e9, age=5), A(aud=8e9, age=9), A(aud=3e9, age=40)])
    an = t.methods[0]
    assert an.value_aud == pytest.approx((16.5e9 + 12e9) / 2) and len(an.inputs["anchors"]) == 2
    assert any("older valuation" in n for n in an.notes)


def test_listed_market_cap_dominates_and_no_private_discount():
    cap = A(kind="market_cap", aud=97.9e6, age=0)
    t = tri([cap, A(aud=300e6, age=30)], rev=57.8e6, comps=[comp("a", 2), comp("b", 3), comp("c", 4)], listed=True)
    an = next(m for m in t.methods if m.method == "market_anchor")
    rv = next(m for m in t.methods if m.method == "revenue_multiple")
    assert an.value_aud == 97.9e6 and an.weight > 0.8 and rv.inputs["discount"] == 0
    assert t.confidence == "high" and abs(t.value_aud / 97.9e6 - 1) < 0.15


def test_stale_market_cap_is_just_a_reported_value():
    assert tg.effective_kind("market_cap", 2) == "market_cap"
    assert tg.effective_kind("market_cap", 12) == "reported_valuation"
    assert tg.effective_kind("market_cap", None) == "reported_valuation"


def test_stage_only_and_low_confidence():
    t = tri(stage="seed", factor=1.2)
    assert [m.method for m in t.methods if m.weight > 0] == ["stage_scorecard"]
    assert t.value_aud == pytest.approx(80e6 * 1.2) and t.confidence == "low"
    assert any("no verified valuation" in r for r in t.confidence_reasons)


def test_default_multiple_is_low_confidence_and_stage_gets_lowest_weight():
    t = tri(rev=20e6)  # 20M x 3.5 = 70M ; stage 80M close -> used with the lowest weight
    rv = next(m for m in t.methods if m.method == "revenue_multiple")
    st = next(m for m in t.methods if m.method == "stage_scorecard")
    assert rv.inputs["multiple_source"] == "default" and "multiple is a default, not cited" in rv.notes
    assert 0 < st.raw_weight < rv.raw_weight and t.confidence == "low"


def test_multiple_bounds_and_source_order():
    ch = tg.choose_multiple([comp("x", 80)], [SectorMultiple(multiple=4.6, source_url="s", quote="q", public=True)],
                            (3, 6, 10), ("default", (2, 3.5, 6)), listed=False)
    assert ch["source"] == "sector_cited" and ch["median"] == 4.6 and ch["discount"] == PRIVATE_COMPANY_DISCOUNT
    ch = tg.choose_multiple([], [], (None, 6, None), ("default", (2, 3.5, 6)), listed=False)
    assert ch["source"] == "market_analysis" and (ch["low"], ch["high"]) == pytest.approx((3.6, 9.0))
    ch = tg.choose_multiple([comp("p", 8, public=False)], [], None, ("default", (2, 3.5, 6)), listed=False)
    assert ch["source"] == "comps_1_2" and ch["discount"] == 0  # private comps: no discount


def test_methods_disagreeing_lowers_confidence():
    t = tri([A(aud=16.5e9, age=3)], rev=1e8, comps=[comp("a", 5), comp("b", 6), comp("c", 7)])
    assert t.confidence == "medium" and any("disagree" in r for r in t.confidence_reasons)


# ================================================================== reproducibility (public verifier)
def test_recompute_rebuilds_blend_from_inputs_and_detects_tampering():
    t = tri([A(), A(kind="secondary_sale", aud=12e9, age=5)], rev=1.95e9,
            comps=[comp("a", 5), comp("b", 7), comp("c", 9)])
    d = t.model_dump()
    r = tg.recompute(d)
    assert (r["low"], r["mid"], r["high"]) == (round(t.low_aud, -3), round(t.value_aud, -3), round(t.high_aud, -3))
    d["methods"][0]["inputs"]["anchors"][0]["amount_aud"] *= 2
    assert tg.recompute(d)["mid"] != r["mid"]


def test_svi_result_v3_matches_public_verifier_and_old_hash_is_stable():
    from blockid_agents.fakes import fake_llm
    from blockid_agents.schemas import MarketAnalysis, QualitativeScores
    from blockid_agents.studio import verify
    from blockid_agents.tools import svi

    p = fake_llm().handlers[StartupProfile]("", "")
    q = fake_llm().handlers[QualitativeScores]("", "")
    m = MarketAnalysis(market_summary="m", revenue_multiple_median=6)
    res = svi.score(p, q, m)
    old_hash = res.report_sha256
    assert old_hash == svi.report_hash(res)  # pre-v3 payload unchanged (no triangulation key)
    svi.apply_triangulation(res, tri([A(aud=20e6, age=6)], rev=480_000, stage="seed", factor=0.5 + res.index / 100))
    assert res.report_sha256 != old_hash and res.valuation_mid_aud == round(res.triangulation.value_aud, -3)
    rep = {"profile": p.model_dump(), "market": m.model_dump(), "svi": res.model_dump()}
    r = verify.recompute(rep)
    assert r["formula_version"] == "v3" and all(r["matches_report"].values()), r


# ================================================================== offline backtest (recorded fixtures)
def test_offline_backtest_meets_target(tmp_path):
    """scripts/valuation-backtest.py replays recorded research through the real graph: median |error| <= 30%."""
    import importlib.util
    import json
    import statistics
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("backtest", root / "scripts" / "valuation-backtest.py")
    bt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bt)
    fixtures = json.loads(bt.FIXTURES.read_text())["companies"]
    errors = {}
    for ref in bt.REFERENCE:
        fx = fixtures[ref["company"]]
        work = tmp_path / ref["company"].replace(" ", "_")
        work.mkdir()
        res = bt.run_one(bt.offline_deps(ref["company"], fx, work), "bt", fx["url"])
        assert len(res["searches"]) <= 8
        errors[ref["company"]] = res["svi"]["triangulation"]["value_aud"] / bt.ref_aud(ref) - 1
        assert res["svi"]["valuation_mid_aud"] == round(res["svi"]["triangulation"]["value_aud"], -3)
    assert statistics.median(abs(e) for e in errors.values()) <= 0.30, errors
    assert abs(errors["Airtasker"]) < 0.1  # listed: market cap found via the detected ASX:ART listing
