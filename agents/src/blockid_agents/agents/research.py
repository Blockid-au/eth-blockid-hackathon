"""Agent 2 — Research: fresh internet data via web search (tools/search.py), analysed by the model.

Pipeline: the essential queries not yet run for this valuation (market size, valuation benchmark — and the
competitor query when no competitor step ran), within the SEARCH_MAX_QUERIES budget -> fetch the top
SEARCH_FETCH_PER_QUERY pages each -> store evidence (URL, time, SHA-256; the search snippet when a page cannot be
fetched) -> the model reads stored evidence and returns a MarketAnalysis in which every claim cites stored URLs.
Findings citing URLs we have no content for are dropped (anti-hallucination).
"""
from __future__ import annotations

import time

from ..deps import Deps
from ..schemas import Finding, MarketAnalysis, StartupProfile
from ..tools.brave import fetch_page
from ..tools.search import budgeted_search, essential_queries, store_result

AGENT = "research"

SYSTEM = """You are the BlockID market research analyst. Using ONLY the numbered evidence provided, produce a
MarketAnalysis for the startup's market.
Rules:
- Every finding, competitor note and risk MUST cite source_urls copied exactly from the evidence list.
- Revenue multiples: only report numbers that appear in the evidence (EV/Revenue for comparable private or listed
  companies in the same sector). If none appear, leave them null.
- Prefer the most recent evidence. Set confidence=low when sources are few, old or promotional."""


QUERY_ORDER = ("market", "valuation", "competitors")


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
        f"{text[:4_000]}"
        for i, (ev, text) in enumerate(evidence, 1)
    )
    user = (
        f"Startup: {profile.company_name} — sector: {profile.sector}; stage: {profile.stage}; "
        f"country: {profile.country}\nCompetitors: {', '.join(profile.competitors) or 'unknown'}\n\n"
        f"<data>\n{listing}\n</data>"
    )
    market = deps.ask(AGENT, deps.settings.svi_tier, SYSTEM, user, MarketAnalysis)
    market = _keep_cited(market, {ev.url for ev, _ in evidence})
    return {"market": market.model_dump(), "evidence_count": len(evidence), "market_fallback": fallback,
            "searches": searches}


def _search_and_fetch(profile: StartupProfile, subject: str, deps: Deps, searches: list[dict],
                      year: int | None) -> int:
    """Returns the number of pages stored from search results in this step (0 = none run / unavailable / empty)."""
    fetch = deps.fetcher or fetch_page
    seen: set[str] = set()
    stored = 0
    for kind, query in build_queries(profile, year or time.gmtime().tm_year):
        results = budgeted_search(deps, AGENT, searches, kind, query, freshness="py" if kind != "competitors" else None)
        for r in (results or [])[: deps.settings.search_fetch_per_query]:
            if r["url"] in seen:
                continue
            seen.add(r["url"])
            if store_result(deps, AGENT, r, query, subject, fetch):
                stored += 1
    return stored


def _keep_cited(m: MarketAnalysis, known: set[str]) -> MarketAnalysis:
    def ok(f: Finding) -> bool:
        return all(u in known for u in f.source_urls)

    m.key_findings = [f for f in m.key_findings if ok(f)]
    m.competitor_notes = [f for f in m.competitor_notes if ok(f)]
    m.risks = [f for f in m.risks if ok(f)]
    if not m.key_findings:
        m.confidence = "low"
    return m
