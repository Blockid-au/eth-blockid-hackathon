"""Competitor discovery (public web only), on a fixed research budget.

1. ONE web search (tools/search.py, essential query (1)): "<name> competitors alternatives <country>". The
   startup's own domain is dropped; the top SEARCH_FETCH_PER_QUERY result pages are fetched and stored as evidence
   (the snippet is stored instead when a page cannot be fetched).
2. The model names up to 9 competitors. Code keeps only names that literally appear in the evidence and are not
   the startup itself (anti-hallucination).
3. Homepages (at most COMPETITOR_HOMEPAGES_MAX fetches per valuation, no searches): the homepages of search-found
   competitors are fetched and stored; when fewer than 3 competitors were found (or search is unavailable) the
   model suggests more, each kept only if its fetched homepage is that brand and on-topic.
4. Funding: the model may report an amount ONLY with the source URL and a verbatim quote from a page fetched in
   this step (search result pages or homepages). Code checks both; otherwise raised_aud stays null.
   Currency -> AUD uses the fixed indicative rates in config.FX_TO_AUD so the result is reproducible.
"""
from __future__ import annotations

import hashlib
import re
import time
from urllib.parse import urlparse

from ..config import FX_TO_AUD, fx_to_aud  # noqa: F401 (FX_TO_AUD re-exported)
from ..deps import Deps
from ..schemas import Competitor, CompetitorList, EvidenceItem, FundingClaims, RelevanceVerdicts, StartupProfile
from ..tools.brave import fetch_page
from ..tools.search import COUNTRY_NAMES, budgeted_search, essential_queries, store_result  # noqa: F401

AGENT = "competitor_discovery"
MAX_COMPETITORS = 9

SYSTEM_LIST = """You identify direct competitors of a startup from web search evidence.
Rules:
- Return at most 9 companies that sell a similar product to a similar customer. Prefer companies explicitly
  described as competitors or alternatives in the evidence.
- Use ONLY company names that appear in the evidence. Never include the startup itself, its parent or its products.
- url: the competitor's own website if it appears in the evidence, else "".
- note: one neutral line on what they do / how they compare."""

SYSTEM_FUNDING = """For each competitor, report the TOTAL funding raised to date ONLY if one of the pages listed under
that competitor explicitly states it. Rules:
- source_url must be copied exactly from that competitor's list; quote must be a short verbatim excerpt
  (<= 200 characters, copied character for character) from that page that states the amount.
- amount as a plain number in the stated currency (e.g. "$25 million" -> 25000000, currency "USD" unless the page
  says otherwise; "A$" -> AUD). Valuations, revenue or market sizes are NOT funding.
- If no page states it, omit the competitor. Returning an empty list is fine."""

_SUFFIX = re.compile(r"\b(pty|ltd|limited|inc|llc|corp|corporation|jsc|co|group|holdings)\b\.?", re.I)


def short_name(name: str) -> str:
    return " ".join(_SUFFIX.sub("", name).replace(",", " ").split()) or name


def domain(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[‘’“”]", "'", s).lower().split())


def quote_in(quote: str, text: str, min_len: int = 6) -> bool:
    """The claimed verbatim quote really appears in the page text (whitespace / quote marks / case normalised)."""
    q = _norm(quote or "")
    return len(q) >= min_len and q in _norm(text or "")


def comp_subject(vid: str) -> str:
    return f"{vid}:comp"


SYSTEM_SUGGEST = """Web search is unavailable or found too few competitors. From your own knowledge, name up to 8 real
companies that compete directly with the startup described (similar product, similar customers; prefer the same country or region).
Rules:
- url MUST be the competitor's official homepage (e.g. https://www.example.com/), not a news, review or social page.
- Only well-established, currently operating companies you are confident exist. Never the startup itself.
- note: one neutral line on what they do. Every suggestion will be verified by fetching its homepage."""

SYSTEM_RELEVANCE = """For each fetched homepage, decide whether that business is a plausible competitor of the
startup: it offers a similar product or service to similar customers (adjacent or partial overlap counts; a
completely different industry, a parked domain, an error or login page does not). Judge ONLY from the page text."""

FALLBACK_WARNING = "Search unavailable: competitors suggested by the model and verified by fetching their websites"
FILL_WARNING = ("Few competitors named in search results: the rest were suggested by the model and verified by "
                "fetching their websites")
MIN_COMPETITORS = 3
_GENERIC = {"software", "platform", "online", "service", "services", "company", "solution", "solutions", "startup",
            "startups", "australia", "australian", "digital", "based", "business", "businesses", "market", "global",
            "technology", "tools", "users", "customers", "products", "product", "management", "system", "systems"}


def relevance_terms(p: StartupProfile) -> set[str]:
    words = re.findall(r"[a-z]{5,}", " ".join([p.sector, *p.search_keywords]).lower())
    return {w for w in words if w not in _GENERIC}


def _names_brand(name: str, url: str, text: str) -> bool:
    """The page must belong to that brand (its name in the text or the domain)."""
    brand = next((w for w in re.findall(r"[a-z0-9]{3,}", name.lower())), "")
    return bool(brand) and (brand in _norm(text) or brand in domain(url).replace("-", ""))


def _relevant(name: str, url: str, text: str, terms: set[str]) -> bool:
    """Cheap keyword check (used as a fast accept before asking the model)."""
    return _names_brand(name, url, text) and bool(terms) and any(w in _norm(text) for w in terms)


def _funding(deps: Deps, comps: list[Competitor], per: dict[str, dict[str, str]]) -> None:
    """Set raised_aud only where a fetched page states it (URL fetched for that competitor + verbatim quote)."""
    if not any(per.values()):
        return
    blocks = [f"### Competitor: {cname}\n" + "\n\n".join(f"URL: {u}\n{t[:3_000]}" for u, t in pages.items())
              for cname, pages in per.items() if pages]
    claims = deps.ask(AGENT, deps.settings.svi_tier, SYSTEM_FUNDING,
                      "<data>\n" + "\n\n".join(blocks) + "\n</data>", FundingClaims)
    best: dict[str, float] = {}
    for cl in claims.items:
        text = (per.get(cl.name) or {}).get(cl.source_url)
        rate = fx_to_aud(cl.currency)
        if text is None or rate is None or cl.amount <= 0 or not quote_in(cl.quote, text):
            deps.audit.record(AGENT, "funding_claim_dropped", competitor=cl.name, url=cl.source_url)
            continue
        best[cl.name] = max(best.get(cl.name, 0), round(cl.amount * rate, -3))
    for c in comps:
        if c.name in best:
            c.raised_aud = best[c.name]


def _own_names(profile: StartupProfile) -> set[str]:
    return {x for x in (_norm(short_name(profile.company_name)), _norm(profile.company_name)) if x}


def _is_self(key: str, own_names: set[str]) -> bool:
    return not key or any(key in o or o in key for o in own_names)


def _fetch_homepages(deps: Deps, cands: list, timeout: float = 8) -> list:
    """Fetch one page per candidate (robots.txt, SSRF guard, contacts stripped), in parallel.
    Returns [(candidate, Page | None, reason)]."""
    from concurrent.futures import ThreadPoolExecutor

    from .site_intake import crawl

    def one(c):
        deps.tool(AGENT, "fetch_url", url=c.url, reason="competitor_homepage")
        try:
            res = crawl(c.url, max_pages=1, transport=deps.site_transport, host_ok=deps.host_check, timeout=timeout,
                        page_deadline=15, crawl_deadline=20)
        except Exception as e:  # noqa: BLE001 - unreachable candidate is simply dropped
            deps.audit.record(AGENT, "fetch_error", url=c.url, error=str(e)[:200])
            return c, None, str(e)[:200]
        if res.pages:
            return c, res.pages[0], ""
        why = "blocked by robots.txt" if res.robots_blocked else "; ".join(res.errors[:2])
        return c, None, why or "no readable page"

    if not cands:
        return []
    with ThreadPoolExecutor(max_workers=min(8, len(cands))) as pool:
        return list(pool.map(one, cands))


def _store_homepage(deps: Deps, vid: str, name: str, page) -> None:
    item = EvidenceItem(url=page.url, title=page.title or name, snippet=page.text[:300], retrieved_at=time.time(),
                        content_sha256=hashlib.sha256(page.text.encode()).hexdigest(),
                        query=f"competitor homepage: {name}", kind="web")
    deps.tool(AGENT, "store_evidence", url=item.url, sha256=item.content_sha256)
    deps.evidence.add(item, page.text, vid)  # kind "web": counts as a source and feeds market analysis


def suggest_and_verify(state: dict, deps: Deps, *, timeout: float = 8, exclude: list[Competitor] | tuple = (),
                       limit: int | None = None) -> tuple[list[Competitor], dict[str, dict[str, str]]]:
    """Model-suggested competitors, each verified by fetching its homepage (at most `limit` fetches) and kept only
    if the page is reachable, is that brand and is on-topic. Used when search is unavailable or found < 3.
    Returns (competitors, {name: {url: page text}}) — funding is extracted by the caller."""
    vid = state["job_id"]
    profile = StartupProfile.model_validate(state["profile"])
    own = domain(state.get("site_url") or state.get("url") or "")
    limit = deps.settings.competitor_homepages_max if limit is None else limit
    if limit <= 0:
        return [], {}
    user = (f"<data>\nStartup: {profile.company_name} ({own})\nSector: {profile.sector}\nCountry: {profile.country}\n"
            f"Stage: {profile.stage}\nDescription: {profile.description}\n"
            f"Keywords: {', '.join(profile.search_keywords)}"
            + (f"\nAlready found (do not repeat): {', '.join(c.name for c in exclude)}" if exclude else "")
            + "\n</data>")
    found = deps.ask(AGENT, deps.settings.svi_tier, SYSTEM_SUGGEST, user, CompetitorList)
    own_names = _own_names(profile)
    taken = [(_norm(x.name), domain(x.url) if x.url else "") for x in exclude]
    cands: list = []
    for c in found.competitors:
        n = " ".join(c.name.split())[:120]
        if _is_self(_norm(n), own_names) or not c.url.startswith(("http://", "https://")) or domain(c.url) == own:
            continue
        if any(_norm(n) == k or domain(c.url) == d for k, d in taken):
            continue
        taken.append((_norm(n), domain(c.url)))
        cands.append(c.model_copy(update={"name": n}))
        if len(cands) >= limit:
            break

    terms = relevance_terms(profile)
    fetched = []
    for c, page, why in _fetch_homepages(deps, cands, timeout):
        if page is None:
            deps.audit.record(AGENT, "suggestion_dropped", competitor=c.name, url=c.url, reason=f"unreachable: {why}")
        elif not _names_brand(c.name, page.url, f"{page.title} {page.text}"):
            deps.audit.record(AGENT, "suggestion_dropped", competitor=c.name, url=c.url, reason="not that brand")
        else:
            fetched.append((c, page))
    unsure = [(c, p) for c, p in fetched if not _relevant(c.name, p.url, f"{p.title} {p.text}", terms)]
    rejected: set[str] = set()
    if unsure:
        body = "\n\n".join(f"### {c.name}\nURL: {p.url}\n{p.title}\n{p.text[:1_500]}" for c, p in unsure)
        verdicts = deps.ask(AGENT, deps.settings.svi_tier, SYSTEM_RELEVANCE,
                            f"Startup: {profile.company_name} — {profile.sector}; {profile.description}\n\n"
                            f"<data>\n{body}\n</data>", RelevanceVerdicts)
        ok = {_norm(v.name) for v in verdicts.items if v.relevant}
        rejected = {c.name for c, _ in unsure if _norm(c.name) not in ok}
    comps: list[Competitor] = []
    per: dict[str, dict[str, str]] = {}
    for c, page in fetched:
        if c.name in rejected:
            deps.audit.record(AGENT, "suggestion_dropped", competitor=c.name, url=c.url, reason="not relevant")
            continue
        _store_homepage(deps, vid, c.name, page)
        comps.append(Competitor(name=c.name, url=page.url, note=c.note[:300], sources=1,
                                basis="model_suggested_verified"))
        per[c.name] = {page.url: page.text}
    deps.audit.record(AGENT, "competitors_suggested", suggested=len(cands), verified=len(comps))
    return comps, per


def discover(state: dict, deps: Deps, *, year: int | None = None) -> dict:
    vid = state["job_id"]
    profile = StartupProfile.model_validate(state["profile"])
    own = domain(state.get("site_url") or state.get("url") or "")
    searches = [dict(x) for x in state.get("searches") or []]
    fetch = deps.fetcher or fetch_page
    fetch_n = deps.settings.search_fetch_per_query
    warnings: list[str] = []

    # ---- 1. one search, top pages fetched
    q = essential_queries(profile, year or time.gmtime().tm_year)["competitors"]
    results = [r for r in (budgeted_search(deps, AGENT, searches, "competitors", q) or []) if domain(r["url"]) != own]
    listing: list[str] = []
    corpus: list[tuple[str, str]] = []  # (url, text) of everything read in this step (names must appear here)
    pages: dict[str, str] = {}  # fetched (or snippet-stored) page text by URL: funding quotes must come from these
    for i, r in enumerate(results):
        text = store_result(deps, AGENT, r, q, vid, fetch) if i < fetch_n else ""
        if text:
            pages[r["url"]] = text
        corpus.append((r["url"], f"{r.get('title', '')} {r.get('description', '')} {text}"))
        listing.append(f"[{len(listing) + 1}] {r.get('title', '')}\nURL: {r['url']}\n"
                       f"{r.get('description', '')}\n{text[:2_500]}")

    # ---- 2. names from the evidence only
    comps: list[Competitor] = []
    if listing:
        user = (f"Startup: {profile.company_name} ({own}) — {profile.sector}; {profile.description}\n\n"
                f"<data>\n" + "\n\n".join(listing) + "\n</data>")
        found = deps.ask(AGENT, deps.settings.svi_tier, SYSTEM_LIST, user, CompetitorList)
        blob = _norm(" ".join(t for _, t in corpus))
        own_names = _own_names(profile)
        for c in found.competitors:
            n = " ".join(c.name.split())[:120]
            key = _norm(n)
            if _is_self(key, own_names) or key not in blob or any(_norm(x.name) == key for x in comps):
                continue
            url = c.url if c.url.startswith(("http://", "https://")) and domain(c.url) != own else ""
            comps.append(Competitor(name=n, url=url, note=c.note[:300]))
            if len(comps) >= MAX_COMPETITORS:
                break

    # ---- 3. homepages (bounded), then model-suggested fill-in when < 3 found
    per: dict[str, dict[str, str]] = {c.name: {u: t for u, t in pages.items() if _norm(c.name) in _norm(t)}
                                      for c in comps}
    budget = deps.settings.competitor_homepages_max
    with_url = [c for c in comps if c.url][:budget]
    for c, page, _why in _fetch_homepages(deps, with_url):
        if page is not None and _names_brand(c.name, page.url, f"{page.title} {page.text}"):
            _store_homepage(deps, vid, c.name, page)
            c.url = page.url
            per[c.name][page.url] = page.text
            corpus.append((page.url, page.text))
    budget -= len(with_url)
    if len(comps) < MIN_COMPETITORS:
        reason = "search found too few competitors" if listing else "search unavailable or returned no results"
        deps.audit.record(AGENT, "search_fallback", reason=reason, found=len(comps))
        extra, extra_per = suggest_and_verify(state, deps, exclude=comps, limit=budget)
        extra = extra[: MAX_COMPETITORS - len(comps)]
        comps += extra
        per.update({c.name: extra_per[c.name] for c in extra})
        corpus += [(u, t) for c in extra for u, t in extra_per[c.name].items()]
        if not listing:
            warnings.append(FALLBACK_WARNING)
        elif extra:
            warnings.append(FILL_WARNING)

    # ---- 4. funding, only when a page fetched in this step states it
    _funding(deps, comps, per)
    for c in comps:
        key = _norm(c.name)
        c.sources = max(c.sources or 0, len({u for u, t in corpus if key in _norm(t)}))
    deps.audit.record(AGENT, "competitors_found", n=len(comps),
                      with_funding=sum(c.raised_aud is not None for c in comps))
    profile.competitors = [c.name for c in comps] or profile.competitors
    return {"competitors": [c.model_dump() for c in comps], "profile": profile.model_dump(), "warnings": warnings,
            "searches": searches}
