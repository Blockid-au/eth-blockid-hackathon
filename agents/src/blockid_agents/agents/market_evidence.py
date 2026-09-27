"""Valuation v3 evidence: the company's own market anchors, its listing, comparable-company and sector multiples.

Runs inside the market step (after agents/research), on the shared search budget (tools/search.py QUERY_PLAN):
  valuation   always           "<name> valuation funding round post-money valued at"
  market_cap  if listed        "<name> <EXCHANGE>:<TICKER> market cap" — listing detected by code in stored pages
  comps       if revenue known "<sector> companies EV/revenue multiple <year>"
  comps_named if revenue known and competitors were named
Then ONE model call reads the stored evidence (passages around valuation / multiple terms) and returns
`ValuationEvidence` claims. Code keeps a claim only if:
  * its source URL is stored evidence for this valuation and its quote appears verbatim in that page (or its
    search snippet), and the quote states the number (tools: research.amount_in_quote);
  * anchors: the quote uses valuation words (valued / valuation / market cap / post-money / ...), the page names the
    company, the currency is in the dated FX table, the amount is plausible; the date comes from `date_text` only if
    it appears on the page (else a year in the quote; a market cap page without a date is dated by its fetch time);
  * comps / sector multiples: the quote states the multiple with a multiple word (x / times / multiple) and a revenue
    word, or (comps) states both the valuation and the revenue (the multiple is then computed by code).
Nothing here produces a valuation — tools/triangulate.py does, from these verified inputs.
"""
from __future__ import annotations

import re
import time
from datetime import date

from ..config import ANCHOR_AUD_BOUNDS, FX_TO_AUD_AS_OF, MULTIPLE_BOUNDS, fx_to_aud
from ..deps import Deps
from ..schemas import (
    Anchor,
    CompanyFinancials,
    CompMultiple,
    Listing,
    SectorMultiple,
    StartupProfile,
    ValuationEvidence,
    VerifiedValuationEvidence,
)
from ..tools.brave import fetch_page
from ..tools.search import budgeted_search, store_result, valuation_queries
from ..tools.triangulate import age_months, parse_as_of

AGENT = "research"

SYSTEM = """From the numbered evidence, extract market-price evidence for valuing the startup named below.
Rules:
- anchors: THIS company's own valuation only — a funding round's post-money valuation (priced_round), a secondary /
  employee share sale or tender (secondary_sale), a fund marking its stake (investor_mark), a press-reported valuation
  (reported_valuation) or, if the company is listed, its market capitalisation (market_cap). `amount` is the
  COMPANY VALUE, never the amount raised. Newest first; include older ones too (at most 5).
- date_text: the date of that valuation copied exactly as written on the page ("June 2026", "25 June 2026", "2024").
- comps: comparable companies (similar product / customers) whose revenue multiple is stated, or whose valuation AND
  revenue are both stated on the same page. Never the startup itself.
- sector_multiples: sector-wide EV/revenue (or price/sales) medians or averages stated in the evidence.
- listing: only if the evidence shows THIS company trades on an exchange (e.g. "Airtasker (ASX: ART)").
- Every quote is copied character for character from the page cited in source_url (<= 300 chars) and contains the
  number. Plain numbers in the stated currency ("US$11 billion" -> 11000000000, currency USD; "A$" -> AUD).
- Leave out anything not explicitly stated. Empty lists are fine."""

VAL_TERMS = re.compile(r"valu(?:ation|ed|e)|worth|market cap|capitali[sz]ation|post-money|pre-money|secondary|tender"
                       r"|share (?:sale|price)|marked|EV\s*/|multiple|times (?:revenue|sales|ARR)|\d\s*x\b"
                       r"|\b(?:ASX|NYSE|NASDAQ|Nasdaq)\b|listed|IPO|series [a-h]\b|raised|revenue|\bARR\b", re.IGNORECASE)
ANCHOR_WORDS = re.compile(r"valu|worth|market cap|capitali[sz]|post-money|pre-money|priced at|tender|secondary|\bmark(?:ed|ing|s)? (?:it|down|up)"
                          r"|share (?:sale|price)|marked", re.IGNORECASE)
MULTIPLE_WORDS = re.compile(r"\d\s*(?:x|×)(?![a-z])|\btimes\b|multiple", re.IGNORECASE)
REVENUE_WORDS = re.compile(r"revenue|sales|\bARR\b|turnover", re.IGNORECASE)
EXCHANGES = r"ASX|NYSE|NASDAQ|Nasdaq|LSE|SGX|TSX|HOSE|HNX|NZX"
LISTING_RE = re.compile(rf"\b({EXCHANGES})\s*[:：]\s*([A-Z]{{1,5}})\b")
MAX_PAGES = 30
PAGE_CHARS = 2_500
SNIPPETS_EXTRA = 4


def val_excerpts(text: str, head: int = 400, window: int = 220, limit: int = PAGE_CHARS) -> str:
    spans: list[list[int]] = [[0, min(head, len(text))]]
    for m in VAL_TERMS.finditer(text):
        a, b = max(0, m.start() - window), min(len(text), m.end() + window)
        if a <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], b)
        else:
            spans.append([a, b])
    return " … ".join(text[a:b] for a, b in spans)[:limit]


# ------------------------------------------------------------------ listing detection (code, not the model)
def detect_listing(profile: StartupProfile, pages: list[tuple[str, str]]) -> Listing | None:
    """'<Company> (ASX: ART)' style mention within 120 characters after the company's name on a stored page."""
    from .competitors import _norm, short_name

    name = _norm(short_name(profile.company_name))
    if not name:
        return None
    for url, text in pages:
        for m in LISTING_RE.finditer(text or ""):
            before = _norm(text[max(0, m.start() - 120):m.start()])
            if name in before:
                a = max(0, m.start() - 120)
                quote = " ".join(text[a:m.end() + 1].split())
                return Listing(exchange=m.group(1).upper(), ticker=m.group(2), source_url=url, quote=quote[-200:])
    return None


# ------------------------------------------------------------------ search (bounded)
def _runner(deps: Deps, subject: str, searches: list[dict]):
    fetch = deps.fetcher or fetch_page
    fetch_n = deps.settings.search_fetch_per_query
    known = {ev.url for ev, _ in deps.evidence.for_subject(subject, limit=500)}

    def run(kind: str, query: str, extra: int = 0) -> int:
        stored = 0
        for i, r in enumerate((budgeted_search(deps, AGENT, searches, kind, query) or [])[: fetch_n + extra]):
            if r["url"] in known:
                continue  # reuse evidence already stored for this valuation
            known.add(r["url"])
            stored += bool(store_result(deps, AGENT, r, query, subject, fetch if i < fetch_n else None))
        return stored
    return run


def search_anchors(profile: StartupProfile, subject: str, deps: Deps, searches: list[dict], year: int,
                   run) -> tuple[Listing | None, int]:
    """valuation query, then market_cap only when a listing is detected. Returns (listing, pages stored)."""
    stored = run("valuation", valuation_queries(profile, year)["valuation"], SNIPPETS_EXTRA)
    pages = [(ev.url, f"{ev.snippet} {text}") for sub in (subject, f"{subject}:site")
             for ev, text in deps.evidence.for_subject(sub, limit=200)]
    listing = detect_listing(profile, pages)
    if listing:
        stored += run("market_cap", valuation_queries(profile, year, listing=(listing.exchange, listing.ticker))
                      ["market_cap"])
    else:
        deps.audit.record(AGENT, "search_planned_skip", kind="market_cap", reason="no listing detected")
    return listing, stored


def search_comps(profile: StartupProfile, deps: Deps, year: int, has_revenue: bool, run) -> None:
    if not has_revenue:
        deps.audit.record(AGENT, "search_planned_skip", kind="comps", reason="no company revenue: multiples unused")
        return
    qs = valuation_queries(profile, year, competitors=profile.competitors)
    run("comps", qs["comps"])
    if "comps_named" in qs:
        run("comps_named", qs["comps_named"])


def _has_revenue(profile: StartupProfile, cf: CompanyFinancials | None) -> bool:
    return profile.metrics.revenue_ttm_aud > 0 or bool(cf and cf.usable_for_valuation)


# ------------------------------------------------------------------ extraction + verification
def gather(profile: StartupProfile, subject: str, deps: Deps, searches: list[dict], *, year: int, today: date,
           cf: CompanyFinancials | None,
           refresh_cf=None) -> tuple[VerifiedValuationEvidence, CompanyFinancials | None]:
    """Search (bounded) -> one model call -> strict verification. Never fails the valuation.
    refresh_cf(): re-runs the company-financials extraction when the anchor searches stored new pages and no usable
    revenue was found yet (e.g. a listed company's market-cap page states its revenue). Returns (evidence, cf)."""
    run = _runner(deps, subject, searches)
    listing, stored = search_anchors(profile, subject, deps, searches, year, run)
    if stored and refresh_cf is not None and not _has_revenue(profile, cf):
        cf = refresh_cf() or cf
    search_comps(profile, deps, year, _has_revenue(profile, cf), run)
    evidence = [(ev, t) for sub in (subject, f"{subject}:site")
                for ev, t in deps.evidence.for_subject(sub, limit=200)]
    claims = ValuationEvidence()
    usable = [(ev, t) for ev, t in evidence if VAL_TERMS.search(f"{ev.snippet} {t}")][:MAX_PAGES]
    if usable:
        listing_txt = "\n\n".join(
            f"[{i}] {ev.title}\nURL: {ev.url}\nRetrieved: {time.strftime('%Y-%m-%d', time.gmtime(ev.retrieved_at))}\n"
            + (f"Search snippet: {ev.snippet}\n" if ev.snippet and ev.kind == "web" and ev.query != "site" else "")
            + val_excerpts(t)
            for i, (ev, t) in enumerate(usable, 1))
        try:
            claims = deps.ask(AGENT, deps.settings.svi_tier, SYSTEM,
                              f"Startup: {profile.company_name} — {profile.sector}; country: {profile.country}\n"
                              f"Competitors: {', '.join(profile.competitors) or 'unknown'}\n\n"
                              f"<data>\n{listing_txt}\n</data>", ValuationEvidence)
        except Exception as e:  # noqa: BLE001 - optional enrichment
            deps.audit.record(AGENT, "valuation_evidence_error", error=str(e)[:300])
    out = verify(claims, evidence, profile, today, cf=cf, listing=listing)
    deps.audit.record(AGENT, "valuation_evidence_verified", anchors=len(out.anchors), comps=len(out.comps),
                      sector_multiples=len(out.sector_multiples), listed=bool(out.listing), dropped=len(out.dropped))
    return out, cf


def _texts_by_url(evidence) -> dict[str, list[str]]:
    by: dict[str, list[str]] = {}
    for ev, text in evidence:
        by.setdefault(ev.url, []).extend([text or "", ev.snippet or ""])
    return by


def _retrieved(evidence) -> dict[str, float]:
    return {ev.url: ev.retrieved_at for ev, _ in evidence}


def verify(claims: ValuationEvidence, evidence, profile: StartupProfile, today: date, *,
           cf: CompanyFinancials | None = None, listing: Listing | None = None) -> VerifiedValuationEvidence:
    from .competitors import _norm, quote_in, short_name
    from .research import amount_in_quote

    texts = _texts_by_url(evidence)
    fetched = _retrieved(evidence)
    name = _norm(short_name(profile.company_name))
    out = VerifiedValuationEvidence(as_of=today.isoformat())

    def found(quote: str, url: str) -> bool:
        return any(quote_in(quote, t) for t in texts.get(url, []))

    def names_company(url: str) -> bool:
        return bool(name) and any(name in _norm(t) for t in texts.get(url, []))

    # listing: code-detected first, else the model's claim when its quote is on the page and names the company
    if listing is None and claims.listing is not None:
        lc = claims.listing
        ok = (lc.source_url in texts and found(lc.quote, lc.source_url) and lc.ticker.upper() in lc.quote.upper()
              and lc.exchange.upper() in lc.quote.upper() and name in _norm(lc.quote))
        if ok:
            listing = Listing(exchange=lc.exchange.upper(), ticker=lc.ticker.upper(), source_url=lc.source_url,
                              quote=lc.quote)
        else:
            out.dropped.append(f"listing {lc.exchange}:{lc.ticker}: quote not verified")
    out.listing = listing

    # anchors
    for c in claims.anchors[:8]:
        why = ""
        rate = fx_to_aud(c.currency)
        if c.source_url not in texts:
            why = "source URL not in evidence"
        elif rate is None:
            why = f"currency {c.currency!r} not in FX table"
        elif not found(c.quote, c.source_url):
            why = "quote not found on the page"
        elif not amount_in_quote(c.amount, c.quote):
            why = "quote does not state the amount"
        elif not ANCHOR_WORDS.search(c.quote):
            why = "quote does not describe a valuation"
        elif not names_company(c.source_url):
            why = "page does not name the company"
        elif c.kind == "market_cap" and listing is None:
            why = "market cap claimed but no listing verified"
        amount_aud = round(c.amount * (rate or 0), -3)
        if not why and not (ANCHOR_AUD_BOUNDS[0] <= amount_aud <= ANCHOR_AUD_BOUNDS[1]):
            why = "implausible amount"
        if why:
            out.dropped.append(f"anchor {c.kind} {c.amount:g} {c.currency} ({c.source_url}): {why}")
            continue
        as_of = ""
        if len(c.date_text.strip()) >= 4 and any(quote_in(c.date_text, t, min_len=4) for t in texts[c.source_url]):
            as_of = parse_as_of(c.date_text)  # the stated date must be on the same page
        if not as_of:
            as_of = parse_as_of(c.quote)
        if not as_of and c.kind == "market_cap" and c.source_url in fetched:
            as_of = time.strftime("%Y-%m", time.gmtime(fetched[c.source_url]))
        out.anchors.append(Anchor(kind=c.kind, amount=c.amount, currency=c.currency.upper().strip(),
                                  amount_aud=amount_aud, fx_rate_to_aud=rate, fx_as_of=FX_TO_AUD_AS_OF, as_of=as_of,
                                  age_months=age_months(as_of, today), date_text=c.date_text,
                                  source_url=c.source_url, quote=c.quote))

    # the research step's verified last valuation (same verbatim rule), when no anchor already states it
    if cf is not None and cf.last_valuation_aud and not any(
            abs(a.amount_aud - cf.last_valuation_aud) <= 0.02 * a.amount_aud for a in out.anchors):
        q = cf.valuation_quote or cf.quote
        as_of = parse_as_of(q)
        out.anchors.append(Anchor(kind="reported_valuation", amount=cf.last_valuation or 0, currency=cf.currency,
                                  amount_aud=cf.last_valuation_aud, fx_rate_to_aud=cf.fx_rate_to_aud or 0,
                                  fx_as_of=cf.fx_as_of or FX_TO_AUD_AS_OF, as_of=as_of,
                                  age_months=age_months(as_of, today), source_url=cf.source_url, quote=q))

    # comparable companies
    lo_b, hi_b = MULTIPLE_BOUNDS
    for c in claims.comps[:10]:
        why, m, basis = "", None, "stated"
        if _norm(short_name(c.name)) and name and (_norm(short_name(c.name)) in name or name in _norm(c.name)):
            why = "the company itself"
        elif c.source_url not in texts:
            why = "source URL not in evidence"
        elif not found(c.quote, c.source_url):
            why = "quote not found on the page"
        elif not any(_norm(c.name) in _norm(t) for t in texts[c.source_url]):
            why = "page does not name the comparable"
        elif c.multiple and amount_in_quote(c.multiple, c.quote, tol=0.001) and MULTIPLE_WORDS.search(c.quote):
            m = c.multiple
        elif c.valuation and c.revenue:
            rq = c.revenue_quote or c.quote
            if (amount_in_quote(c.valuation, c.quote) and amount_in_quote(c.revenue, rq) and found(rq, c.source_url)
                    and REVENUE_WORDS.search(rq)):
                m, basis = c.valuation / c.revenue, "valuation/revenue"
            else:
                why = "valuation and revenue not both stated"
        else:
            why = "quote does not state a multiple"
        if not why and not (lo_b <= (m or 0) <= hi_b):
            why = f"multiple {m:g}x outside bounds"
        if why:
            out.dropped.append(f"comparable {c.name} ({c.source_url}): {why}")
            continue
        if any(_norm(x.name) == _norm(c.name) for x in out.comps):
            continue
        out.comps.append(CompMultiple(name=c.name, multiple=round(m, 3), public=c.public, basis=basis,
                                      source_url=c.source_url, quote=c.quote))

    # sector multiples
    for s in claims.sector_multiples[:6]:
        why = ""
        if s.source_url not in texts:
            why = "source URL not in evidence"
        elif not found(s.quote, s.source_url):
            why = "quote not found on the page"
        elif not (amount_in_quote(s.multiple, s.quote, tol=0.001) and MULTIPLE_WORDS.search(s.quote)
                  and REVENUE_WORDS.search(s.quote)):
            why = "quote does not state a revenue multiple"
        elif not (lo_b <= s.multiple <= hi_b):
            why = "outside bounds"
        if why:
            out.dropped.append(f"sector multiple {s.multiple:g}x ({s.source_url}): {why}")
            continue
        out.sector_multiples.append(SectorMultiple(multiple=s.multiple, sector=s.sector[:120], public=s.public,
                                                   source_url=s.source_url, quote=s.quote))
    return out
