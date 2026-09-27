"""Company-financials search (query 3): verified-quote extraction, FX conversion, revenue precedence, budget.
All offline (fake LLM, fake search provider, fake fetcher)."""
import re

import pytest
from test_research_budget import run_graph
from test_studio import studio_deps  # shared offline fixture

from blockid_agents.agents import research, valuation
from blockid_agents.config import FX_TO_AUD, FX_TO_AUD_AS_OF
from blockid_agents.fakes import fake_llm
from blockid_agents.schemas import CompanyFinancials, MarketAnalysis, QualitativeScores, StartupProfile
from blockid_agents.tools import svi
from blockid_agents.tools.search import SearchChain, essential_queries

REV_URL = "https://news.example.com/agritrace-arr"
REV_PAGE = "AgriTrace reported ARR of US$1.6 million in 2025 and has raised US$4 million to date, the company said."


class FinSearch:
    """Answers every query; the company-financials query also returns an article stating AgriTrace's ARR."""

    def __init__(self):
        self.queries = []

    def search(self, query, count=8, **_):
        self.queries.append(query)
        n = len(self.queries)
        out = [{"title": f"TE-FOOD and OpenSC #{n}", "url": f"https://news.example.com/r{n}-{i}",
                "description": "TE-FOOD and OpenSC compete in food traceability", "query": query} for i in range(3)]
        if "revenue ARR funding valuation" in query:
            out.insert(0, {"title": "AgriTrace ARR", "url": REV_URL, "description": REV_PAGE[:60], "query": query})
            out.append({"title": "snippet only", "url": "https://news.example.com/snip",
                        "description": "AgriTrace was valued at US$20 million in its seed round", "query": query})
        return out


def fetcher(url):
    return REV_PAGE if url == REV_URL else f"Page {url}. TE-FOOD and OpenSC are traceability platforms."


def claim(**kw) -> CompanyFinancials:
    base = dict(revenue_ttm=1_600_000, currency="USD", revenue_year=2025, revenue_type="ARR",
                funding_raised_total=4_000_000, source_url=REV_URL, quote="AgriTrace reported ARR of US$1.6 million")
    return CompanyFinancials(**{**base, **kw})


def deps_with(tmp_path, cf_fn, revenue=0):
    """Fake deps: profile revenue `revenue` (website); the financials extraction call answers cf_fn(user)."""
    deps = studio_deps(tmp_path)
    deps.search, deps.fetcher = SearchChain([("claude", FinSearch())]), fetcher
    base = fake_llm().handlers
    prof = base[StartupProfile]

    def profile(s, u):
        p = prof(s, u)
        p.metrics.revenue_ttm_aud = revenue
        return p

    def market(s, u):
        m = base[MarketAnalysis](s, u)
        m.revenue_multiple_low = m.revenue_multiple_median = m.revenue_multiple_high = None  # no cited multiple
        m.company_financials = claim(revenue_ttm=9e9, quote="invented")  # market call's own value is ignored
        return m
    deps.llm.handlers[StartupProfile] = profile
    deps.llm.handlers[MarketAnalysis] = market
    deps.llm.handlers[CompanyFinancials] = lambda s, u: cf_fn(u) or CompanyFinancials()
    return deps


def research_state(deps, revenue=0):
    p = deps.llm.handlers[StartupProfile]("", "")
    p.metrics.revenue_ttm_aud = revenue
    return {"job_id": "cf", "profile": p.model_dump()}


def test_company_query_replaces_generic_valuation_query():
    p = fake_llm().handlers[StartupProfile]("", "")
    qs = essential_queries(p, 2026)
    assert qs["company"] == "AgriTrace revenue ARR funding valuation 2026"
    assert [k for k, _ in research.build_queries(p, 2026)] == ["market", "company", "competitors"]


def test_financials_kept_only_with_verifiable_quote(tmp_path):
    deps = deps_with(tmp_path, lambda u: claim())
    cf = research.run(research_state(deps), deps)["market"]["company_financials"]
    assert cf["revenue_ttm"] == 1_600_000 and cf["revenue_ttm_aud"] == 2_400_000  # USD 1.50
    assert cf["fx_rate_to_aud"] == 1.50 and cf["fx_as_of"] == FX_TO_AUD_AS_OF
    assert cf["usable_for_valuation"] and cf["quote"] == "AgriTrace reported ARR of US$1.6 million"
    assert cf["funding_raised_total_aud"] is None  # "US$4 million" is not in the revenue quote

    deps = deps_with(tmp_path / "b", lambda u: claim(funding_quote="has raised US$4 million to date"))
    cf = research.run(research_state(deps), deps)["market"]["company_financials"]
    assert cf["funding_raised_total_aud"] == 6_000_000

    bad = [claim(quote="AgriTrace reported ARR of US$9 million"),  # quote not on the page
           claim(revenue_ttm=16_000_000),  # quote on the page but states a different number
           claim(source_url="https://invented.example/x"),  # URL never fetched
           claim(currency="XYZ")]  # no FX rate: dropped, not guessed
    for i, c in enumerate(bad):
        deps = deps_with(tmp_path / f"x{i}", lambda u, c=c: c.model_copy(update={"funding_raised_total": None}))
        assert research.run(research_state(deps), deps)["market"]["company_financials"] is None, c


def test_snippet_only_source_and_gmv_is_not_revenue(tmp_path):
    # results past the fetch budget keep their snippet: a figure stated there is accepted
    deps = deps_with(tmp_path, lambda u: CompanyFinancials(
        last_valuation=20_000_000, currency="USD", source_url="https://news.example.com/snip",
        quote="AgriTrace was valued at US$20 million"))
    cf = research.run(research_state(deps), deps)["market"]["company_financials"]
    assert cf["last_valuation_aud"] == 30_000_000 and not cf["usable_for_valuation"] and cf["revenue_ttm"] is None

    page = "AgriTrace processed US$1.6 million in payments in 2025."
    deps = deps_with(tmp_path / "g", lambda u: claim(quote="AgriTrace processed US$1.6 million in payments",
                                                     revenue_type="revenue"))
    deps.fetcher = lambda url: page if url == REV_URL else fetcher(url)
    cf = research.run(research_state(deps), deps)["market"]["company_financials"]
    assert cf["revenue_type"] == "GMV" and not cf["usable_for_valuation"]  # volume wording overrides the label


def test_financial_excerpts_reach_past_the_page_head():
    page = "Intro. " * 2_000 + "We recently surpassed $1 billion in annualized revenue this year." + " Outro." * 500
    ex = research.fin_excerpts(page)
    assert "surpassed $1 billion in annualized revenue" in ex and len(ex) <= 3_000


@pytest.mark.parametrize("quote,amount,ok", [
    ("revenue of US$900 million", 900e6, True), ("A$1.2bn in ARR", 1.2e9, True), ("revenue 12,500,000", 12.5e6, True),
    ("doanh thu 1.200 tỷ đồng", 1.2e12, True), ("$5m ARR", 5e6, True), ("revenue of US$900 million", 9e9, False),
    ("900 more customers", 900e6, False)])
def test_amount_in_quote(quote, amount, ok):
    assert research.amount_in_quote(amount, quote) is ok


def test_fx_table_is_fixed_and_documented():
    assert {k: FX_TO_AUD[k] for k in ("USD", "EUR", "GBP", "SGD", "VND")} == {
        "USD": 1.50, "EUR": 1.65, "GBP": 1.95, "SGD": 1.15, "VND": 0.00006}
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", FX_TO_AUD_AS_OF)


def _verified(**kw) -> MarketAnalysis:
    cf = claim(**kw).model_copy(update={"revenue_ttm_aud": 2_400_000, "fx_rate_to_aud": 1.5,
                                        "fx_as_of": FX_TO_AUD_AS_OF, "usable_for_valuation": True})
    return MarketAnalysis(market_summary="x", company_financials=cf)


def test_revenue_precedence_self_reported_then_website_then_cited():
    p = fake_llm().handlers[StartupProfile]("", "")
    m = _verified()
    # website-stated revenue wins over a cited source
    q = p.model_copy(deep=True)
    assert valuation.apply_cited_revenue(q, m, []) == (None, [])
    assert q.metrics.revenue_ttm_aud == 480_000 and q.metrics_sources["revenue_ttm_aud"] == "website"
    # self-reported wins over both
    q = p.model_copy(deep=True)
    assert valuation.apply_cited_revenue(q, m, ["revenue_ttm_aud"])[0] is None
    assert q.metrics_sources["revenue_ttm_aud"] == "self_reported"
    # no revenue anywhere else -> the cited figure, labelled and warned
    q = p.model_copy(deep=True)
    q.metrics.revenue_ttm_aud = 0
    cited, warns = valuation.apply_cited_revenue(q, m, [])
    assert cited == {"source_url": REV_URL, "quote": "AgriTrace reported ARR of US$1.6 million"}
    assert q.metrics.revenue_ttm_aud == 2_400_000 and q.metrics_sources["revenue_ttm_aud"] == "cited_source"
    assert "third-party source" in warns[0] and REV_URL in warns[0]
    # GMV is never used
    q = p.model_copy(deep=True)
    q.metrics.revenue_ttm_aud = 0
    gmv = _verified(revenue_type="GMV")
    gmv.company_financials.usable_for_valuation = False
    cited, warns = valuation.apply_cited_revenue(q, gmv, [])
    assert cited is None and q.metrics.revenue_ttm_aud == 0 and "GMV" in warns[0]


def test_graph_uses_cited_revenue_within_three_searches(tmp_path):
    def cf_from_prompt(u):
        return claim() if REV_URL in u else None
    deps = deps_with(tmp_path, cf_from_prompt, revenue=0)
    out, prog = run_graph(deps, "vcf")
    assert out["__interrupt__"]
    r = prog.results["vcf"]
    kinds = [s["kind"] for s in r["searches"]]
    assert kinds[:3] == ["competitors", "market", "company"]  # same priority order as before v3
    assert kinds[3:] == ["valuation", "comps", "comps_named"]  # v3 plan: no listing -> no market-cap search
    assert len(deps.search.providers[0][1].queries) == len(kinds) <= deps.settings.search_max_queries <= 8
    assert r["profile"]["metrics"]["revenue_ttm_aud"] == 2_400_000
    assert r["profile"]["metrics_sources"]["revenue_ttm_aud"] == "cited_source"
    rev = r["svi"]["dimensions"]["revenue_performance"]
    assert rev["basis"] == "cited_source" and REV_URL in rev["rationale"] and rev["sources"] == [REV_URL]
    assert r["company_financials"]["revenue_ttm_aud"] == 2_400_000
    assert any("third-party source" in w for w in r["warnings"])
    assert "company ARR A$2,400,000 (cited)" in prog.steps["vcf"]["market"]["detail"]
    assert "revenue: cited_source" in prog.steps["vcf"]["svi"]["detail"]

    # self-reported revenue still wins over the cited figure in the full graph
    from langgraph.checkpoint.memory import InMemorySaver

    from blockid_agents.graph import build_site_valuation
    from blockid_agents.studio.db import MemoryProgress
    deps = deps_with(tmp_path / "sr", cf_from_prompt, revenue=0)
    prog = MemoryProgress()
    build_site_valuation(deps, InMemorySaver(), prog).invoke(
        {"job_id": "vsr", "url": "https://agritrace.example", "self_reported": {"revenue_ttm_aud": 500_000}},
        {"configurable": {"thread_id": "vsr"}})
    r = prog.results["vsr"]
    assert r["profile"]["metrics"]["revenue_ttm_aud"] == 500_000
    assert r["profile"]["metrics_sources"]["revenue_ttm_aud"] == "self_reported"
    assert r["svi"]["dimensions"]["revenue_performance"]["basis"] == "self_reported"


# ================================================================== valuation range rules
def _q():
    return fake_llm().handlers[QualitativeScores]("", "")


def _p(revenue, sector="agri-food supply chain traceability"):
    p = fake_llm().handlers[StartupProfile]("", "")
    p.metrics.revenue_ttm_aud, p.sector = revenue, sector
    return p


def _market(multiple=None, valuation_aud=None):
    m = _verified()
    m.company_financials.last_valuation_aud = valuation_aud
    m.revenue_multiple_median = multiple
    return m


def test_range_uses_implied_multiple_from_cited_last_round():
    r = svi.score(_p(2_400_000), _q(), _market(multiple=6, valuation_aud=26_400_000))  # 26.4M / 2.4M = 11x
    f = 0.5 + r.index / 100
    assert "implied multiple from cited last round: 11.0x" in r.method and REV_URL in r.method
    assert r.valuation_mid_aud == round(2_400_000 * 11 * f, -3)
    assert r.valuation_low_aud == round(2_400_000 * 11 * 0.7 * f, -3)
    assert r.valuation_high_aud == round(2_400_000 * 11 * 1.4 * f, -3)


@pytest.mark.parametrize("valuation_aud", [2_400_000 * 45, 2_400_000 * 0.4])
def test_implied_multiple_outside_bounds_is_ignored(valuation_aud):
    r = svi.score(_p(2_400_000), _q(), _market(multiple=6, valuation_aud=valuation_aud))
    assert "implied" not in r.method and "cited market data" in r.method  # falls to the cited market multiple


def test_default_multiple_table_when_revenue_but_nothing_cited():
    r = svi.score(_p(1_000_000), _q(), None)
    f = 0.5 + r.index / 100
    assert "default multiple (2.0x / 3.5x / 6.0x, default; uncalibrated default" in r.method
    assert r.valuation_mid_aud == round(1_000_000 * 3.5 * f, -3)
    assert "multiple is a default, not cited" in r.needs_human_review
    r = svi.score(_p(1_000_000, "global payments and financial platform"), _q(), _market())
    assert "(3.0x / 6.0x / 10.0x, saas_fintech;" in r.method
    assert r.valuation_mid_aud == round(1_000_000 * 6 * (0.5 + r.index / 100), -3)


def test_stage_range_only_without_revenue():
    r = svi.score(_p(0), _q(), _market(multiple=6, valuation_aud=26_400_000))
    lo, mid, hi = svi.STAGE_PRE_REVENUE_RANGE["seed"]
    assert r.method.startswith("stage benchmark range (seed")
    assert r.valuation_mid_aud == round(mid * (0.5 + r.index / 100), -3)
