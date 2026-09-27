"""Evaluation v5 analysts (offline): claims are kept only with a verbatim quote on a stored page (or the uploaded
deck) that states the number; invented quotes / URLs are dropped for every analyst; levels by source; ABS lookup."""
import hashlib
import time
from datetime import date

import pytest

from blockid_agents.agents import analysts, deck_reader
from blockid_agents.audit import AuditLog
from blockid_agents.config import get_settings
from blockid_agents.deps import Deps
from blockid_agents.llm import FakeLLM
from blockid_agents.schemas import (
    DeckFacts,
    EvidenceItem,
    LogoClaim,
    MarketSizeClaims,
    MetricClaim,
    MoatClaims,
    PowerClaim,
    RetentionClaims,
    StartupProfile,
    TractionClaims,
)
from blockid_agents.tools import lookups
from blockid_agents.tools.brave import EvidenceStore

SITE = "https://agritrace.example/"
NEWS = "https://news.example/agritrace-arr"
MKT = "https://www.abs.gov.au/food-exports"
REV = "https://www.capterra.example/agritrace"
PAGES = {
    SITE: ("site", "AgriTrace — food traceability for Australian food exporters. Trusted by Coles and SunRice. "
                   "Our customers include 120 paying customers across Australia. Pricing: A$250 per month per site. "
                   "Integrates with 35 farm management systems. Patent AU2024100123 granted."),
    NEWS: ("web", "AgriTrace grew ARR to A$1.2 million in June 2026, up 150% year on year, the company said."),
    MKT: ("web", "Australia's food traceability software market was valued at A$410 million in 2025 and is growing "
                 "at a CAGR of 9.5% to 2030."),
    REV: ("web", "AgriTrace reviews: rated 4.7 out of 5 from 52 reviews on Capterra."),
}


def claim(metric, value, unit, url, quote, subject="company", period=""):
    return MetricClaim(metric=metric, value=value, unit=unit, source_url=url, quote=quote, subject=subject,
                       period=period)


def handlers():
    return {
        TractionClaims: lambda s, u: TractionClaims(claims=[
            claim("arr", 1_200_000, "AUD", NEWS, "AgriTrace grew ARR to A$1.2 million in June 2026", period="June 2026"),
            claim("revenue_growth_yoy", 150, "%", NEWS, "up 150% year on year"),
            claim("paying_customers", 120, "count", SITE, "120 paying customers across Australia"),
            claim("arr", 9_000_000, "AUD", NEWS, "AgriTrace reached A$9 million ARR"),  # invented quote
            claim("arr", 5_000_000, "AUD", "https://invented.example", "ARR of A$5 million"),  # invented URL
            claim("paying_customers", 500, "count", SITE, "120 paying customers across Australia"),  # wrong number
        ], logos=[LogoClaim(name="Coles", source_url=SITE, quote="Trusted by Coles and SunRice"),
                  LogoClaim(name="Aldi", source_url=SITE, quote="Trusted by Aldi")], revenue_model="subscription",
            revenue_model_quote="A$250 per month per site"),
        MarketSizeClaims: lambda s, u: MarketSizeClaims(
            claims=[claim("tam", 410_000_000, "AUD", MKT, "market was valued at A$410 million in 2025", "market",
                          "2025"),
                    claim("cagr", 9.5, "%", MKT, "growing at a CAGR of 9.5% to 2030", "market"),
                    claim("annual_price", 250, "AUD", SITE, "Pricing: A$250 per month per site"),
                    claim("tam", 99e9, "USD", MKT, "a US$99 billion opportunity", "market")],
            target_customer="Australian food exporters", anzsic_division="C", size_band="employing",
            customer_quote="food traceability for Australian food exporters", customer_source_url=SITE),
        MoatClaims: lambda s, u: MoatClaims(powers=[
            PowerClaim(power="switching_costs", evidence="35 integrations", number=35, source_url=SITE,
                       quote="Integrates with 35 farm management systems"),
            PowerClaim(power="ip_data", evidence="granted patent", registry_id="AU2024100123", source_url=SITE,
                       quote="Patent AU2024100123 granted"),
            PowerClaim(power="network_effects", evidence="invented", source_url=SITE, quote="the more farms join")]),
        RetentionClaims: lambda s, u: RetentionClaims(claims=[
            claim("review_rating", 4.7, "rating", REV, "rated 4.7 out of 5 from 52 reviews"),
            claim("review_count", 52, "count", REV, "rated 4.7 out of 5 from 52 reviews"),
            claim("nrr", 130, "%", REV, "net revenue retention of 130%")]),
        DeckFacts: lambda s, u: DeckFacts(claims=[
            claim("arr", 1_250_000, "AUD", "doc:7", "ARR A$1.25m (Aug 2026)", period="Aug 2026"),
            claim("nrr", 112, "%", "doc:7", "NRR 112%"), claim("lois", 9, "count", "doc:7", "nine LOIs signed")],
            round_type="Series A", round_quote="Raising a A$4m Series A"),
    }


def make_deps(tmp_path, llm=None):
    store = EvidenceStore(tmp_path / "ev.sqlite")
    for url, (kind, text) in PAGES.items():
        subject = "v1:site" if kind == "site" else "v1"
        store.add(EvidenceItem(url=url, title=url, retrieved_at=time.time(), kind=kind,
                               query="site" if kind == "site" else "q",
                               content_sha256=hashlib.sha256(text.encode()).hexdigest()), text, subject)
    return Deps(llm=llm or FakeLLM(handlers()), audit=AuditLog(tmp_path / "a.jsonl"), evidence=store,
                settings=get_settings())


PROFILE = StartupProfile(company_name="AgriTrace Pty Ltd", sector="food traceability SaaS", stage="seed",
                         description="d", country="AU").model_dump()


class NoLookups(lookups.Lookups):
    def __init__(self):
        super().__init__(None, offline=True)


def run(tmp_path, **state):
    deps = make_deps(tmp_path)
    st = {"job_id": "v1", "url": SITE, "site_url": SITE, "profile": PROFILE, "competitors": [
        {"name": "TE-FOOD", "raised_aud": 15_000_000}], "market": {}, "searches": [], **state}
    return deps, analysts.run(st, deps, today=date(2026, 9, 27), lookups_client=NoLookups())


def test_analysts_keep_only_verified_claims(tmp_path):
    deps, out = run(tmp_path)
    a = out["analysis"]
    kept = {(c["metric"], c["value"]) for c in a["claims"]}
    assert ("arr", 1_200_000) in kept and ("revenue_growth_yoy", 150) in kept and ("paying_customers", 120) in kept
    assert ("arr", 9_000_000) not in kept and ("arr", 5_000_000) not in kept and ("paying_customers", 500) not in kept
    assert ("tam", 410_000_000) in kept and ("cagr", 9.5) in kept and ("tam", 99e9) not in kept
    assert ("review_rating", 4.7) in kept and ("nrr", 130) not in kept
    urls = {c["source_url"] for c in a["claims"]}
    assert urls <= set(PAGES)  # zero invented URLs
    reasons = " | ".join(a["dropped"])
    for why in ("quote not found", "source URL not in the stored evidence", "does not state the number"):
        assert why in reasons
    logos = [c for c in a["claims"] if c["metric"] == "customer_logo"]
    assert len(logos) == 1 and "Coles" in logos[0]["quote"]  # 'Aldi' quote is not on the page
    by = {c["metric"]: c for c in a["claims"]}
    assert by["arr"]["level"] == 3 and by["paying_customers"]["level"] == 1  # third-party vs own site
    assert by["arr"]["value_aud"] == 1_200_000 and by["arr"]["as_of"] == "2026-06"


def test_analysts_score_dimensions_and_market_sizing(tmp_path):
    _, out = run(tmp_path)
    a = out["analysis"]
    d = a["dimensions"]
    assert d["traction"]["status"] == "scored" and d["traction"]["coverage"] >= 0.85
    ms = a["market_sizing"]
    abs_c = lookups.abs_count("C", "employing")["count"]
    assert ms["target_customers_source"] == "abs:C:employing" and ms["target_customers"] == abs_c
    assert ms["annual_price_aud"] == 3000  # A$250 per month x 12 (code annualises)
    assert ms["sam_aud"] == round(abs_c * 3000, -3) and ms["tam_aud"] == 410_000_000
    assert ms["source_tier"] == 1
    powers = {p["key"]: p for p in a["powers"]}
    assert powers["switching_costs"]["level"] == 2 and powers["ip_data"]["level"] == 1  # own site, not a registry
    assert powers["network_effects"]["level"] == 0  # quote not on the page
    assert powers["competition"]["points"] > 0
    assert d["retention"]["status"] == "scored"
    assert a["stage"]["stage"] == "seed" and a["stage"]["basis"] == "revenue"
    assert analysts.detail(a).startswith("traction ")


def test_analyst_failure_never_fails_the_step(tmp_path):
    deps = make_deps(tmp_path, llm=FakeLLM({}))
    st = {"job_id": "v1", "url": SITE, "site_url": SITE, "profile": PROFILE, "searches": []}
    out = analysts.run(st, deps, today=date(2026, 9, 27), lookups_client=NoLookups())
    d = out["analysis"]["dimensions"]
    assert d["traction"]["status"] == "not_enough_data" and d["traction"]["score"] == 40
    assert all(v["error"] for k, v in out["analysis"]["analysts"].items() if k in ("traction", "moat"))


def test_search_plan_is_conditional_and_budgeted(tmp_path):
    from blockid_agents.tools.search import ANALYST_QUERY_PLAN, QUERY_PLAN

    assert ANALYST_QUERY_PLAN == ("traction", "reviews", "market_bottom_up", "ip") and not set(QUERY_PLAN) & set(
        ANALYST_QUERY_PLAN)
    prof = StartupProfile.model_validate(PROFILE)
    deps = make_deps(tmp_path)
    pool = analysts.evidence_pool(deps, "v1")
    kinds = [k for k, _, _ in analysts.plan_searches(prof, pool, {}, 2026)]
    assert kinds == ["traction", "ip"]  # < 3 customer markers; patents mentioned; AU -> ABS table, no customers typed
    kinds = [k for k, _, _ in analysts.plan_searches(prof, pool, {"customers": 5}, 2026)]
    assert "reviews" in kinds

    class Chain:
        def __init__(self):
            self.n = 0

        def search(self, q, count=8, freshness=None):
            self.n += 1
            return [{"url": f"https://r{self.n}.example/", "title": "t", "description": "d"}], "brave"
    deps.search = Chain()
    from dataclasses import replace

    deps.settings = replace(deps.settings, search_max_queries=12)
    searches = [{"kind": k, "provider": "claude"} for k in range(11)]
    analysts.run_searches(prof, {"job_id": "v1"}, deps, pool, {"customers": 5}, searches, 2026)
    assert len(searches) == 12  # budget cap (SEARCH_MAX_QUERIES=12 in production; default here)


def test_deck_reader_verifies_against_the_deck_text(tmp_path):
    deps = make_deps(tmp_path)
    text = "Slide 3\nARR A$1.25m (Aug 2026)\nSlide 5\nNRR 112%\nRaising a A$4m Series A"
    out = deck_reader.read_deck("7", text, PROFILE, deps, SITE)
    kept = {(c["metric"], c["value"]) for c in out["claims"]}
    assert kept == {("arr", 1_250_000), ("nrr", 112)}  # 'nine LOIs signed' is not in the deck
    assert all(c["level"] == 1 and c["source_url"] == "doc:7" for c in out["claims"])
    assert out["round_type"] == "Series A"


@pytest.mark.parametrize("code,band,ok", [("C", "employing", True), ("0111", "all", True), ("Z", "all", False),
                                          ("C", "bogus", False)])
def test_abs_table(code, band, ok):
    r = lookups.abs_count(code, band)
    assert (r is not None) == ok
    if ok:
        assert r["count"] > 0 and r["source_url"].startswith("https://www.abs.gov.au/")
    assert sum(1 for _ in lookups.abs_divisions()) == 20  # A-S + unknown
