"""Web search provider chain + per-valuation research budget.

Providers are tried in the order given by SEARCH_PROVIDERS (default "brave,claude"):

* ``brave``  — Brave Search API (tools/brave.py); skipped when the key is missing or Brave is cached-unavailable.
* ``claude`` — the host bridge ``deploy/search-bridge/claude_search_bridge.py`` (Claude Code CLI headless with only
  WebSearch). POST {CLAUDE_SEARCH_URL}/search, header X-Bridge-Token, body {"query", "count"<=8}
  -> {"results": [{"title", "url", "snippet"}], "cost_usd", "model"}.

Results are normal web results (title, url, description, query) and are stored as evidence exactly like Brave's.
A provider that refuses service (429 / 5xx / timeout / network / bad token) is skipped for UNAVAILABLE_S.

Budget: every valuation runs at most SEARCH_MAX_QUERIES queries in total (default 8, hard cap 8), each planned by
purpose (QUERY_PLAN, in priority order, so a smaller budget keeps the most useful ones):

  1 competitors   "<name> competitors alternatives <country>"              (competitor step)
  2 market        "<sector> market size growth <country> <year>"           (market step)
  3 company       "<name> revenue ARR funding valuation <year>"            (market step)
  4 valuation     "<name> valuation funding round post-money"              (market step, v3 anchors)
  5 market_cap    "<name> <exchange>:<ticker> market cap"                  (only when a listing was detected)
  6 comps         "<sector> companies EV/revenue multiple <year>"          (only when the company has revenue)
  7 comps_named   "<competitor 1> <competitor 2> valuation revenue"        (only with revenue + named competitors)

Each attempt is recorded in the graph state (``searches``: kind, purpose, query, provider, results) so the budget
holds across steps and checkpoint resumes, and in the audit log. Repeated queries hit the 72 h search cache.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time

import httpx

from ..schemas import EvidenceItem, StartupProfile
from .brave import BraveSearch, EvidenceStore, sanitize_query

log = logging.getLogger(__name__)

UNAVAILABLE_S = 600
MAX_COUNT = 8
LABELS = {"brave": "Brave Search", "claude": "Claude web search"}
COUNTRY_NAMES = {"AU": "Australia", "AUS": "Australia", "VN": "Vietnam", "SG": "Singapore", "NZ": "New Zealand",
                 "US": "United States", "GB": "United Kingdom", "UK": "United Kingdom", "IN": "India",
                 "ID": "Indonesia", "JP": "Japan"}


class SearchUnavailable(RuntimeError):
    """No provider could answer (all missing, refusing service or cached-unavailable)."""


class BridgeUnavailable(SearchUnavailable):
    pass


class ClaudeBridgeSearch:
    name = "claude"

    def __init__(self, url: str, token: str, store: EvidenceStore | None = None, *, timeout: float = 150,
                 cache_ttl_hours: int = 72, transport: httpx.BaseTransport | None = None):
        if not url or not token:
            raise ValueError("CLAUDE_SEARCH_URL and CLAUDE_SEARCH_TOKEN are required")
        self.url = url.rstrip("/") + "/search"
        self.store = store
        self.ttl = cache_ttl_hours * 3600
        self.unavailable_until = 0.0
        self.unavailable_reason = ""
        self.last_cost_usd: float | None = None
        self.http = httpx.Client(timeout=timeout, transport=transport, trust_env=False,
                                 headers={"X-Bridge-Token": token, "Accept": "application/json"})

    @property
    def available(self) -> bool:
        return time.monotonic() >= self.unavailable_until

    def _mark_unavailable(self, reason: str):
        self.unavailable_until = time.monotonic() + UNAVAILABLE_S
        self.unavailable_reason = reason
        raise BridgeUnavailable(f"Claude search bridge {reason}")

    def search(self, query: str, *, count: int = MAX_COUNT, **_ignored) -> list[dict]:
        q = sanitize_query(query)[:200]
        count = max(1, min(int(count), MAX_COUNT))
        key = "claude:" + hashlib.sha256(json.dumps([q, count]).encode()).hexdigest()
        data = self.store.cache_get(key, self.ttl) if self.store else None
        if data is None:
            if not self.available:
                raise BridgeUnavailable(f"Claude search bridge unavailable (cached): {self.unavailable_reason}")
            try:
                r = self.http.post(self.url, json={"query": q, "count": count})
            except httpx.TimeoutException:
                self._mark_unavailable("timed out")
            except httpx.HTTPError as e:
                self._mark_unavailable(f"network error: {type(e).__name__}")
            if r.status_code in (401, 403, 429) or r.status_code >= 500:
                self._mark_unavailable(f"HTTP {r.status_code}")
            if r.status_code != 200:
                raise SearchUnavailable(f"Claude search bridge HTTP {r.status_code}")
            try:
                data = r.json()
            except ValueError:
                data = None
            if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                self._mark_unavailable("returned malformed JSON")
            self.last_cost_usd = data.get("cost_usd")
            log.info("claude search: %d results, model %s, $%s", len(data["results"]), data.get("model"),
                     data.get("cost_usd"))
            if data["results"] and self.store:
                self.store.cache_put(key, data)
        out, seen = [], set()
        for x in data.get("results") or []:
            url = str((x or {}).get("url", "")).strip()
            if not url.startswith("https://") or url in seen:
                continue
            seen.add(url)
            out.append({"title": str(x.get("title", ""))[:300], "url": url,
                        "description": str(x.get("snippet", ""))[:500], "query": q})
        return out[:count]


class SearchChain:
    """Try each provider in order; returns (results, provider name). Empty results fall through to the next."""

    def __init__(self, providers: list[tuple[str, object]]):
        self.providers = providers

    @property
    def names(self) -> list[str]:
        return [n for n, _ in self.providers]

    def search(self, query: str, *, count: int = MAX_COUNT, freshness: str | None = None) -> tuple[list[dict], str]:
        errors = []
        for name, p in self.providers:
            if not getattr(p, "available", True):
                errors.append(f"{name}: unavailable ({getattr(p, 'unavailable_reason', '')})")
                continue
            try:
                if isinstance(p, BraveSearch):
                    results = p.search(query, count=count, freshness=freshness)
                else:
                    results = p.search(query, count=count)
            except Exception as e:  # quota / refusal / network -> next provider
                log.warning("search provider %s failed: %s", name, e)
                errors.append(f"{name}: {e}")
                continue
            if results:
                return results, name
            errors.append(f"{name}: no results")
        raise SearchUnavailable("; ".join(errors) or "no search provider configured")


def build_search(settings, store: EvidenceStore) -> SearchChain | None:
    providers: list[tuple[str, object]] = []
    for name in settings.search_providers:
        if name == "brave" and settings.brave_api_key:
            providers.append(("brave", BraveSearch(settings.brave_api_key, store, max_rps=settings.brave_max_rps,
                                                   cache_ttl_hours=settings.brave_cache_ttl_hours)))
        elif name == "claude" and settings.claude_search_url and settings.claude_search_token:
            providers.append(("claude", ClaudeBridgeSearch(settings.claude_search_url, settings.claude_search_token,
                                                           store, timeout=settings.claude_search_timeout,
                                                           cache_ttl_hours=settings.brave_cache_ttl_hours)))
    return SearchChain(providers) if providers else None


# ------------------------------------------------------------------ the three essential queries + budget
def country_name(code: str) -> str:
    return COUNTRY_NAMES.get((code or "").upper(), code or "")


def essential_queries(p: StartupProfile, year: int, company: str | None = None) -> dict[str, str]:
    """kind -> query. Built only from public profile fields (no people's names); sanitized (emails/phones)."""
    from ..agents.competitors import short_name

    name = company or short_name(p.company_name)
    country = country_name(p.country)
    sector = p.sector or " ".join(p.search_keywords[:2])
    qs = {
        "competitors": f"{name} competitors alternatives {country}",
        "market": f"{sector} market size growth {country} {year}",
        "company": f"{name} revenue ARR funding valuation {year}",
    }
    return {k: sanitize_query(v)[:200] for k, v in qs.items()}


# purpose of every planned query (shown in the report's search log)
PURPOSE = {
    "competitors": "find competitors",
    "market": "market size and growth",
    "company": "company revenue / ARR",
    "valuation": "company valuation, latest funding round or share sale",
    "market_cap": "market capitalisation (listed company)",
    "comps": "revenue multiples of comparable companies / sector",
    "comps_named": "valuations and revenue of named competitors",
}
QUERY_PLAN = ("competitors", "market", "company", "valuation", "market_cap", "comps", "comps_named")


def valuation_queries(p: StartupProfile, year: int, *, listing: tuple[str, str] | None = None,
                      competitors: list[str] | None = None, company: str | None = None) -> dict[str, str]:
    """v3 queries (kind -> query), built from public profile fields only. market_cap needs a detected listing
    (exchange, ticker); comps_named needs competitor names."""
    from ..agents.competitors import short_name

    name = company or short_name(p.company_name)
    sector = p.sector or " ".join(p.search_keywords[:2])
    qs = {
        "valuation": f"{name} valuation funding round post-money valued at",
        "comps": f"{sector} companies EV/revenue multiple {year}",
    }
    if listing:
        qs["market_cap"] = f"{name} {listing[0]}:{listing[1]} market cap"
    names = [c for c in (competitors or []) if c][:3]
    if names:
        qs["comps_named"] = f"{' '.join(names)} valuation revenue"
    return {k: sanitize_query(v)[:200] for k, v in qs.items()}


def budgeted_search(deps, agent: str, searches: list[dict], kind: str, query: str, *,
                    freshness: str | None = None) -> list[dict] | None:
    """Run one essential query if the budget allows. Appends the attempt to `searches` (graph state).
    Returns None when skipped (already run / budget spent / no provider), [] when every provider failed."""
    if any(s.get("kind") == kind for s in searches):
        return None
    if len(searches) >= deps.settings.search_max_queries:
        deps.audit.record(agent, "search_budget_exhausted", kind=kind, used=len(searches))
        return None
    if deps.search is None:
        deps.audit.record(agent, "search_skipped", reason="no search provider configured")
        return None
    deps.tool(agent, "web_search", query=query, kind=kind, purpose=PURPOSE.get(kind, kind))
    rec = {"kind": kind, "purpose": PURPOSE.get(kind, kind), "query": query, "provider": None, "results": 0}
    searches.append(rec)
    try:
        results, provider = deps.search.search(query, count=MAX_COUNT, freshness=freshness)
    except SearchUnavailable as e:
        rec["error"] = str(e)[:300]
        deps.audit.record(agent, "search_unavailable", query=query, error=str(e)[:500])
        return []
    rec.update(provider=provider, results=len(results))
    deps.audit.record(agent, "search_served", query=query, provider=provider, results=len(results))
    return results


def summary(searches: list[dict] | None, max_queries: int) -> str:
    """e.g. '3/3 searches · Claude web search'."""
    searches = searches or []
    served = list(dict.fromkeys(LABELS.get(s["provider"], s["provider"]) for s in searches if s.get("provider")))
    return f"{len(searches)}/{max_queries} searches · " + (" + ".join(served) if served else "search unavailable")


def store_result(deps, agent: str, r: dict, query: str, subject: str, fetch) -> str:
    """Fetch one result page and store it as evidence. When the fetch fails the search snippet is stored instead
    (kind "search_snippet"), so a finding may still cite that URL — the snippet is the content we actually have.
    fetch=None stores the snippet without fetching the page."""
    kind, text = "web", ""
    if fetch is not None:
        deps.tool(agent, "fetch_url", url=r["url"])
        try:
            text = fetch(r["url"])
        except Exception as e:  # noqa: BLE001
            deps.audit.record(agent, "fetch_error", url=r["url"], error=str(e)[:300])
            text = ""
    if not (text or "").strip():
        text, kind = r.get("description", ""), "search_snippet"
        if not text.strip():
            return ""
    item = EvidenceItem(url=r["url"], title=r.get("title") or r["url"], snippet=r.get("description", ""),
                        retrieved_at=time.time(), content_sha256=hashlib.sha256(text.encode()).hexdigest(),
                        query=query, kind=kind)
    deps.tool(agent, "store_evidence", url=item.url, sha256=item.content_sha256)
    deps.evidence.add(item, text, subject)
    return text
