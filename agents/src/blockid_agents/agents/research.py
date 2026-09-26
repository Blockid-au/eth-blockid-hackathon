"""Agent 2 — Research: fresh internet data via web search (tools/search.py), analysed by the model.

Pipeline: the essential queries not yet run for this valuation (market size/growth, the company's own reported
financials — and the competitor query when no competitor step ran), within the SEARCH_MAX_QUERIES budget -> fetch
the top SEARCH_FETCH_PER_QUERY pages each -> store evidence (URL, time, SHA-256; the search snippet when a page
cannot be fetched) -> the model reads stored evidence and returns a MarketAnalysis in which every claim cites
stored URLs. Findings citing URLs we have no content for are dropped (anti-hallucination).

Company financials (revenue / ARR / funding / last valuation) are kept only when the cited page or its search
snippet contains the model's quote verbatim AND the quote states that number; figures are converted to AUD with
the fixed config.FX_TO_AUD table (rate + date recorded). Only revenue/ARR can feed the valuation (GMV never does).
"""
from __future__ import annotations

import re
import time

from ..config import FX_TO_AUD_AS_OF, fx_to_aud
from ..deps import Deps
from ..schemas import CompanyFinancials, Finding, MarketAnalysis, StartupProfile
from ..tools.brave import fetch_page
from ..tools.search import budgeted_search, essential_queries, store_result

AGENT = "research"

SYSTEM = """You are the BlockID market research analyst. Using ONLY the numbered evidence provided, produce a
MarketAnalysis for the startup's market.
Rules:
- Every finding, competitor note and risk MUST cite source_urls copied exactly from the evidence list.
- Revenue multiples: only report multiples that appear in the evidence (EV/Revenue or valuation-to-revenue for
  this startup or comparable private or listed companies in the same sector — market or company articles). If
  none appear, leave them null. Never compute one yourself.
- Leave company_financials null (a separate step extracts it).
- Prefer the most recent evidence. Set confidence=low when sources are few, old or promotional."""


SYSTEM_FINANCIALS = """From the numbered evidence, extract the startup's OWN reported financial figures.
Rules:
- revenue_ttm is the most important field: the latest annual revenue, annualized revenue or ARR of THIS company
  (never the market size, a competitor, a target or a forecast). "surpassed $1 billion in annualized revenue" ->
  revenue_ttm 1000000000, revenue_type "ARR"; "annual revenue of A$12m" -> 12000000, "revenue", currency "AUD".
  Payment / transaction volume, TPV or GMV is NOT revenue: revenue_type "GMV".
- funding_raised_total: total raised to date; last_valuation: the latest stated company valuation.
- All figures must come from ONE evidence page (source_url copied exactly). Prefer what the company itself
  reported (press release, newsroom, company blog) over analyst estimates, and the most recent figure.
- quote: copied character for character from that page and containing the revenue number (<= 300 chars).
  funding_quote / valuation_quote: separate verbatim excerpts from the same page when not inside `quote`.
- Plain numbers in the stated currency (ISO code; "$" alone means USD unless the page is Australian-dollar).
- If a figure is not explicitly stated, leave it null. Returning all nulls is fine."""
FIN_TERMS = re.compile(r"revenue|\bARR\b|annuali[sz]ed|turnover|valuation|valued|raised|funding|series [a-h]\b"
                       r"|doanh thu", re.I)


def fin_excerpts(text: str, head: int = 600, window: int = 260, limit: int = 3_000) -> str:
    """The start of a page plus the passages around financial terms (long pages are otherwise cut off)."""
    spans: list[list[int]] = [[0, min(head, len(text))]]
    for m in FIN_TERMS.finditer(text):
        a, b = max(0, m.start() - window), min(len(text), m.end() + window)
        if a <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], b)
        else:
            spans.append([a, b])
    out = " … ".join(text[a:b] for a, b in spans)
    return out[:limit]


QUERY_ORDER = ("market", "company", "competitors")
FRESHNESS = {"market": "py"}  # Brave only: market data from the past year; company reports may be older


def build_queries(p: StartupProfile, year: int) -> list[tuple[str, str]]:
    """(kind, query) for the essential queries this agent may run, in priority order."""
    qs = essential_queries(p, year)
    return [(k, qs[k]) for k in QUERY_ORDER]


def run(state: dict, deps: Deps, *, year: int | None = None) -> dict:
    """Search -> fetch -> analyse. When web search is unavailable (no key, quota, HTTP errors) or returns
    nothing, the analysis still runs on evidence already stored for this subject (e.g. competitor homepages)
    plus the company's own site pages (`<subject>:site`) — the cite-only-fetched-URLs rule is unchanged."""
    profile = StartupProfile.model_validate(state["profile"])
    subject = state["job_id"]
    searches = [dict(x) for x in state.get("searches") or []]
    _search_and_fetch(profile, subject, deps, searches, year)
    # search-result pages stored by this step or the competitor step (homepages alone mean "fallback")
    searched = sum(1 for ev, _ in deps.evidence.for_subject(subject, limit=500)
                   if ev.query != "site" and not ev.query.startswith("competitor homepage:"))

    evidence = deps.evidence.for_subject(subject, limit=30)
    fallback = searched == 0
    if fallback:
        known = {ev.url for ev, _ in evidence}
        evidence += [x for x in deps.evidence.for_subject(f"{subject}:site", limit=10) if x[0].url not in known]
    if not evidence:
        return {"market": None, "evidence_count": 0, "searches": searches}
    if fallback:
        deps.audit.record(AGENT, "fallback_analysis", sources=len(evidence))

    listing = "\n\n".join(
        f"[{i}] {ev.title}{' (search snippet only)' if ev.kind == 'search_snippet' else ''}\nURL: {ev.url}\nRetrieved: {time.strftime('%Y-%m-%d', time.gmtime(ev.retrieved_at))}\n"
        + (f"Search snippet: {ev.snippet}\n" if ev.snippet and ev.kind == "web" and ev.query != "site"
           and not ev.query.startswith("competitor homepage:") else "")
        + f"{text[:4_000]}"
        for i, (ev, text) in enumerate(evidence, 1)
    )
    user = (
        f"Startup: {profile.company_name} — sector: {profile.sector}; stage: {profile.stage}; "
        f"country: {profile.country}\nCompetitors: {', '.join(profile.competitors) or 'unknown'}\n\n"
        f"<data>\n{listing}\n</data>"
    )
    market = deps.ask(AGENT, deps.settings.svi_tier, SYSTEM, user, MarketAnalysis)
    market = _keep_cited(market, {ev.url for ev, _ in evidence})
    market.company_financials = company_financials(profile, subject, deps, year or time.gmtime().tm_year)
    return {"market": market.model_dump(), "evidence_count": len(evidence), "market_fallback": fallback,
            "searches": searches}


def _search_and_fetch(profile: StartupProfile, subject: str, deps: Deps, searches: list[dict],
                      year: int | None) -> int:
    """Returns the number of pages stored from search results in this step (0 = none run / unavailable / empty)."""
    fetch = deps.fetcher or fetch_page
    seen: set[str] = set()
    stored = 0
    for kind, query in build_queries(profile, year or time.gmtime().tm_year):
        results = budgeted_search(deps, AGENT, searches, kind, query, freshness=FRESHNESS.get(kind))
        fetch_n = deps.settings.search_fetch_per_query
        for i, r in enumerate((results or [])[: fetch_n + (SNIPPETS_EXTRA if kind == "company" else 0)]):
            if r["url"] in seen:
                continue
            seen.add(r["url"])
            # company query: results past the fetch budget keep their search snippet (no extra fetch), since
            # revenue / funding figures are often right in the snippet
            if store_result(deps, AGENT, r, query, subject, fetch if i < fetch_n else None):
                stored += 1
    return stored


SNIPPETS_EXTRA = 4



def _keep_cited(m: MarketAnalysis, known: set[str]) -> MarketAnalysis:
    def ok(f: Finding) -> bool:
        return all(u in known for u in f.source_urls)

    m.key_findings = [f for f in m.key_findings if ok(f)]
    m.competitor_notes = [f for f in m.competitor_notes if ok(f)]
    m.risks = [f for f in m.risks if ok(f)]
    if not m.key_findings:
        m.confidence = "low"
    return m


# ------------------------------------------------------------------ company financials (verified quotes only)
_SCALE = {"thousand": 1e3, "k": 1e3, "nghìn": 1e3, "million": 1e6, "mn": 1e6, "m": 1e6, "triệu": 1e6,
          "billion": 1e9, "bn": 1e9, "b": 1e9, "tỷ": 1e9, "trillion": 1e12, "tn": 1e12}
_NUM = re.compile(r"(\d{1,3}(?:[,.]\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?)"
                  r"(?:\s*(trillion|billion|million|thousand|nghìn|triệu|tỷ|bn|mn|tn|k|m|b)(?![a-zà-ỹ]))?", re.I)
_VOLUME = re.compile(r"\b(volume|gmv|processed|transactions?|payments? flow|tpv|gross merchandise)\b", re.I)
_REVENUE = re.compile(r"\b(revenue|arr|sales|turnover|doanh thu)\b", re.I)
MAX_REVENUE_AGE_YEARS = 3


def quote_numbers(quote: str) -> list[float]:
    """Every amount a quote states, with scale words applied ("US$1.2bn" -> 1.2e9). Ambiguous separators give
    several candidates ("1.200 tỷ" -> 1.2e9 and 1.2e12)."""
    out: list[float] = []
    for num, unit in _NUM.findall(quote or ""):
        scale = _SCALE.get(unit.lower(), 1.0) if unit else 1.0
        cands = {num.replace(",", "")}
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", num):
            cands.add(num.replace(".", ""))  # 1.200.000 (dot thousands)
        if re.fullmatch(r"\d+,\d{1,2}", num):
            cands.add(num.replace(",", "."))  # 1,5 (comma decimal)
        for c in cands:
            try:
                out.append(float(c) * scale)
            except ValueError:
                pass
    return out


def amount_in_quote(amount: float | None, quote: str, tol: float = 0.015) -> bool:
    """The quote states this amount (within rounding: 'US$900 million' == 900_000_000)."""
    return bool(amount and amount > 0) and any(abs(v - amount) <= tol * amount for v in quote_numbers(quote))


def company_financials(profile: StartupProfile, subject: str, deps: Deps, year: int) -> CompanyFinancials | None:
    """One focused LLM call over the search-result evidence (financial passages of each page + its snippet), then
    strict verification. Never fails the valuation: no evidence / model error -> None."""
    evidence = [(ev, t) for ev, t in deps.evidence.for_subject(subject, limit=60)
                if ev.query != "site" and not ev.query.startswith("competitor homepage:")]
    if not evidence:
        return None
    listing = "\n\n".join(
        f"[{i}] {ev.title}\nURL: {ev.url}\n"
        + (f"Search snippet: {ev.snippet}\n" if ev.snippet and ev.kind == "web" else "")
        + fin_excerpts(t)
        for i, (ev, t) in enumerate(evidence, 1))
    try:
        cf = deps.ask(AGENT, deps.settings.svi_tier, SYSTEM_FINANCIALS,
                      f"Startup: {profile.company_name} — {profile.sector}; country: {profile.country}\n\n"
                      f"<data>\n{listing}\n</data>", CompanyFinancials)
    except Exception as e:  # noqa: BLE001 - optional enrichment
        deps.audit.record(AGENT, "company_financials_error", error=str(e)[:300])
        return None
    if not any((cf.revenue_ttm, cf.funding_raised_total, cf.last_valuation)):
        return None
    return verify_financials(cf, evidence, profile, deps, year)


def verify_financials(cf: CompanyFinancials | None, evidence: list, profile: StartupProfile, deps: Deps,
                      year: int) -> CompanyFinancials | None:
    """Keep only figures whose quote appears verbatim in the cited page (or its search snippet) and states the
    number; convert to AUD at the fixed config rate. Returns None when nothing survives."""
    from .competitors import _norm, quote_in, short_name

    if cf is None:
        return None
    texts: list[str] = []
    for ev, text in evidence:
        if ev.url == cf.source_url:
            texts += [text or "", ev.snippet or ""]
    rate = fx_to_aud(cf.currency)
    name = _norm(short_name(profile.company_name))
    about_company = bool(name) and any(name in _norm(t) for t in texts)

    def reason() -> str:
        if not texts:
            return "source URL not in evidence"
        if rate is None:
            return f"currency {cf.currency!r} not in FX table"
        return "" if about_company else "page does not name the company"

    why = reason()
    if why:
        deps.audit.record(AGENT, "company_financials_dropped", url=cf.source_url, reason=why)
        return None

    def stated(amount: float | None, *quotes: str) -> str:
        for q in quotes:
            if q and amount_in_quote(amount, q) and any(quote_in(q, t) for t in texts):
                return q
        return ""

    out = CompanyFinancials(currency=cf.currency.upper().strip(), source_url=cf.source_url, fx_rate_to_aud=rate,
                            fx_as_of=FX_TO_AUD_AS_OF)
    q_rev = stated(cf.revenue_ttm, cf.quote)
    if q_rev and (cf.revenue_ttm or 0) * rate <= 1e12:
        rtype = cf.revenue_type
        if _VOLUME.search(q_rev) and not _REVENUE.search(q_rev):
            rtype = "GMV"  # "processed US$100B" is volume, whatever the model called it
        out.revenue_ttm, out.revenue_year, out.revenue_type, out.quote = cf.revenue_ttm, cf.revenue_year, rtype, q_rev
        out.revenue_ttm_aud = round(cf.revenue_ttm * rate, -3)
        fresh = cf.revenue_year is None or cf.revenue_year >= year - MAX_REVENUE_AGE_YEARS
        out.usable_for_valuation = rtype in ("revenue", "ARR") and fresh and out.revenue_ttm_aud > 0
    q_fund = stated(cf.funding_raised_total, cf.quote, cf.funding_quote)
    if q_fund:
        out.funding_raised_total = cf.funding_raised_total
        out.funding_raised_total_aud = round(cf.funding_raised_total * rate, -3)
        out.funding_quote = "" if q_fund == out.quote else q_fund
    q_val = stated(cf.last_valuation, cf.quote, cf.valuation_quote)
    if q_val:
        out.last_valuation = cf.last_valuation
        out.last_valuation_aud = round(cf.last_valuation * rate, -3)
        out.valuation_quote = "" if q_val == out.quote else q_val
    if not (q_rev or q_fund or q_val):
        deps.audit.record(AGENT, "company_financials_dropped", url=cf.source_url, reason="quote not verified")
        return None
    if not out.quote:  # no verified revenue: the first verified quote becomes the main one
        out.quote = out.funding_quote or out.valuation_quote
        out.funding_quote = "" if out.funding_quote == out.quote else out.funding_quote
        out.valuation_quote = "" if out.valuation_quote == out.quote else out.valuation_quote
    deps.audit.record(AGENT, "company_financials_verified", url=cf.source_url, revenue=bool(q_rev),
                      usable=out.usable_for_valuation, funding=bool(q_fund), valuation=bool(q_val))
    return out
