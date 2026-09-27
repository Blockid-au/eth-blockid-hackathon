"""Evaluation v5 analysts — shared helpers and the `analysts` graph step (docs/PLAN-EVALUATION-V5.md §2).

Step (between `market` and `svi`, only when VALUATION_V5=1):
  1. evidence pool = every page already stored for this valuation (site, research, competitors) — reused, not refetched
  2. conditional searches, run SEQUENTIALLY on the shared budget (tools/search.QUERY_PLAN order: traction, reviews,
     market_bottom_up, ip — after the valuation-critical kinds, so a smaller budget drops these first); on a paid
     provider at most ANALYST_PAID_SEARCH_MAX (default 2) of them
  3. free lookups (Tranco, Wayback, iTunes, ABN when a GUID is set; ABS table is local) — cached 7 days
  4. four extractions IN PARALLEL (traction, market_size, moat, retention): each gets a keyword-windowed digest
     (<= 14k chars) and returns typed claims with verbatim quotes (one `extract_json` call each)
  5. code verifies every claim (quote on the cited stored page / document, number stated in the quote, page names
     the company for company claims, currency in the FX table, period <= 36 months) and assigns the level:
     company's own site / deck = L1, third-party page = L3; drops go to `dropped` with the reason
  6. the stage is decided (tools/stage.classify_stage) and tools/evaluation.evaluate builds the partial Analysis
The LLM never returns a score. Any analyst failure leaves its dimension at "Not enough data" (never fails the run).
"""
from __future__ import annotations

import contextvars
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from urllib.parse import urlparse

from ..config import fx_to_aud
from ..deps import Deps
from ..schemas import Analysis, MarketSizing, MetricClaim, MetricValue, StartupProfile, VerifiedClaim
from ..tools import evaluation
from ..tools import lookups as lookups_mod
from ..tools import stage as stage_tools
from ..tools.brave import fetch_page
from ..tools.search import budgeted_search, sanitize_query, store_result

MAX_DIGEST_CHARS = 14_000
MAX_CLAIM_AGE_MONTHS = 36
PAID_SEARCH_PROVIDERS = ("brave",)
MARKET_SOURCE_TIERS = (  # (tier, domain suffixes) — first match wins; unknown = 4
    (1, (".gov.au", ".gov", ".gov.uk", ".gov.sg", ".gov.vn", "abs.gov.au", "oecd.org", "worldbank.org", "imf.org",
         "rba.gov.au", "austrade.gov.au")),
    (2, (".org.au", "asx.com.au", "sec.gov", "annualreports.com", ".edu.au", ".edu", "aicd.com.au",
         "ibisworld.com", "deloitte.com", "pwc.com", "kpmg.com", "mckinsey.com", "bcg.com")),
    (3, ("grandviewresearch.com", "mordorintelligence.com", "statista.com", "marketsandmarkets.com",
         "fortunebusinessinsights.com", "imarcgroup.com", "precedenceresearch.com", "globenewswire.com",
         "prnewswire.com", "businesswire.com", "researchandmarkets.com", "alliedmarketresearch.com")),
)


def analyst_paid_search_max() -> int:
    try:
        return max(0, int(os.environ.get("ANALYST_PAID_SEARCH_MAX", "2")))
    except ValueError:
        return 2


def host(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    return h.removeprefix("www.")


def source_tier(url: str) -> int:
    h = host(url)
    for tier, suffixes in MARKET_SOURCE_TIERS:
        if any(h == s.lstrip(".") or h.endswith(s if s.startswith(".") else "." + s) or h == s for s in suffixes):
            return tier
    return 4


# ------------------------------------------------------------------ evidence pool + digest
def evidence_pool(deps: Deps, vid: str) -> list[tuple]:
    """(EvidenceItem, text) for every page stored for this valuation (site first), de-duplicated by URL."""
    from . import competitors, site_intake

    out, seen = [], set()
    for subject in (site_intake.site_subject(vid), vid, competitors.comp_subject(vid)):
        for ev, text in deps.evidence.for_subject(subject, limit=500):
            if ev.url not in seen:
                seen.add(ev.url)
                out.append((ev, text or ""))
    return out


def windows(text: str, pattern: re.Pattern, head: int = 300, window: int = 220, limit: int = 1_800) -> str:
    spans: list[list[int]] = [[0, min(head, len(text))]]
    for m in pattern.finditer(text):
        a, b = max(0, m.start() - window), min(len(text), m.end() + window)
        if a <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], b)
        else:
            spans.append([a, b])
    return " … ".join(text[a:b] for a, b in spans)[:limit]


def digest(pool: list[tuple], pattern: re.Pattern, *, docs: dict[str, str] | None = None,
           max_chars: int = MAX_DIGEST_CHARS, only_matching: bool = True) -> str:
    """Numbered evidence list of keyword windows, within the prompt budget. Pages without a match are skipped."""
    parts: list[str] = []
    used = 0
    for doc_id, text in (docs or {}).items():
        if pattern.search(text):
            block = f"[doc] Uploaded document\nURL: doc:{doc_id}\n{windows(text, pattern, limit=4_000)}"
            parts.append(block)
            used += len(block)
    for i, (ev, text) in enumerate(pool, 1):
        body = text or ev.snippet or ""
        if only_matching and not pattern.search(body):
            continue
        block = (f"[{i}] {ev.title}{' (company website)' if ev.kind == 'site' or ev.query == 'site' else ''}\n"
                 f"URL: {ev.url}\n{windows(body, pattern)}")
        if used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts)


# ------------------------------------------------------------------ claim verification
def _fold(s: str) -> str:
    return " ".join(re.sub(r"[‘’“”]", "'", s or "").replace(" ", " ").lower().split())


def quote_found(quote: str, texts: list[str], min_len: int = 6) -> bool:
    q = _fold(quote)
    return len(q) >= min_len and any(q in _fold(t) for t in texts)


def number_in_quote(value: float | None, quote: str, tol: float = 0.015) -> bool:
    from .research import amount_in_quote, quote_numbers

    if value is None:
        return False
    if value > 0 and amount_in_quote(value, quote, tol):
        return True
    return any(abs(v - value) <= max(tol * abs(value), 1e-9) for v in quote_numbers(quote))


def _as_of(period: str, quote: str) -> str:
    from ..tools.triangulate import parse_as_of

    return parse_as_of(period) or parse_as_of(quote)


def _age_months(as_of: str, today: date) -> float | None:
    m = re.match(r"^(\d{4})(?:-(\d{2}))?$", as_of or "")
    if not m:
        return None
    return (today.year - int(m.group(1))) * 12 + (today.month - int(m.group(2) or 7))


class Verifier:
    """Verifies MetricClaims against the stored evidence pool and uploaded documents."""

    def __init__(self, pool: list[tuple], profile: StartupProfile, site_url: str, docs: dict[str, str] | None = None,
                 today: date | None = None):
        self.texts: dict[str, list[str]] = {}
        self.site: set[str] = set()
        self.company_host = host(site_url)
        for ev, text in pool:
            self.texts.setdefault(ev.url, []).extend([text or "", ev.snippet or ""])
            if ev.kind == "site" or ev.query == "site" or (self.company_host and host(ev.url) == self.company_host):
                self.site.add(ev.url)
        for doc_id, text in (docs or {}).items():
            self.texts[f"doc:{doc_id}"] = [text]
        from .competitors import short_name

        self.name = _fold(short_name(profile.company_name))
        self.today = today or datetime.now(UTC).date()

    def own(self, url: str) -> bool:
        return url in self.site or url.startswith("doc:")

    def level_for(self, url: str) -> int:
        return 1 if self.own(url) else 3

    def names_company(self, url: str) -> bool:
        return self.own(url) or (bool(self.name) and any(self.name in _fold(t) for t in self.texts.get(url, [])))

    def found(self, quote: str, url: str) -> bool:
        return url in self.texts and quote_found(quote, self.texts[url])

    def claim(self, c: MetricClaim, analyst: str, allowed: set[str]) -> tuple[VerifiedClaim | None, str]:
        label = f"{analyst}: {c.metric} {c.value if c.value is not None else ''} {c.unit}".strip()
        if c.metric not in allowed:
            return None, f"{label}: metric not allowed for this analyst"
        if c.source_url not in self.texts:
            return None, f"{label}: source URL not in the stored evidence"
        if not self.found(c.quote, c.source_url):
            return None, f"{label}: quote not found on the page"
        if not number_in_quote(c.value, c.quote):
            return None, f"{label}: quote does not state the number"
        if c.subject == "company" and not self.names_company(c.source_url):
            return None, f"{label}: page does not name the company"
        metric_key = evaluation.CLAIM_METRICS.get(c.metric, "")
        unit = (c.unit or "").upper().replace("A$", "AUD").replace("US$", "USD").strip()
        value_aud = None
        if metric_key.endswith("_aud"):
            rate = fx_to_aud(unit or "AUD")
            if rate is None:
                return None, f"{label}: currency {c.unit!r} not in the FX table"
            value_aud = round(float(c.value) * rate, 2)
        as_of = _as_of(c.period, c.quote)
        age = _age_months(as_of, self.today)
        if age is not None and age > MAX_CLAIM_AGE_MONTHS:
            return None, f"{label}: older than {MAX_CLAIM_AGE_MONTHS} months ({as_of})"
        return VerifiedClaim(metric=c.metric, value=c.value, unit=c.unit, period=c.period, as_of=as_of,
                             value_aud=value_aud, source_url=c.source_url, quote=c.quote[:300], subject=c.subject,
                             level=self.level_for(c.source_url), analyst=analyst), ""

    def claims(self, claims: list[MetricClaim], analyst: str, allowed: set[str],
               limit: int = 20) -> tuple[list[VerifiedClaim], list[str]]:
        ok, dropped, seen = [], [], set()
        for c in claims[:limit]:
            v, why = self.claim(c, analyst, allowed)
            if v is None:
                dropped.append(why)
                continue
            key = (v.metric, v.value, v.source_url)
            if key not in seen:
                seen.add(key)
                ok.append(v)
        return ok, dropped


def ask(deps: Deps, agent: str, system: str, user: str, schema):
    """One extract_json call; None on any error (recorded)."""
    try:
        return deps.ask(agent, deps.settings.svi_tier, system, user, schema)
    except Exception as e:  # noqa: BLE001 - an analyst never fails the valuation
        deps.audit.record(agent, "analyst_error", error=f"{type(e).__name__}: {e}"[:300])
        return None


# ------------------------------------------------------------------ searches (sequential, budgeted)
ANALYST_KINDS = ("traction", "reviews", "market_bottom_up", "ip")
_CUSTOMER_RE = re.compile(r"case stud|customers include|trusted by|our customers|clients include|used by", re.IGNORECASE)
_IP_RE = re.compile(r"\bpatent|trade ?mark|\bIP\b|intellectual property", re.IGNORECASE)


def plan_searches(profile: StartupProfile, pool: list[tuple], typed: dict, year: int) -> list[tuple[str, str, str]]:
    """(kind, query, agent) for the conditional analyst searches."""
    from .competitors import short_name

    name = short_name(profile.company_name)
    site_text = " ".join(t for ev, t in pool if ev.kind == "site" or ev.query == "site")
    has_customers = bool(profile.metrics.paying_customers or profile.metrics.revenue_ttm_aud
                         or typed.get("customers") or typed.get("revenue_ttm_aud") or typed.get("arr_aud"))
    out = []
    if len(_CUSTOMER_RE.findall(site_text)) < 3:
        out.append(("traction", f'"{name}" customers OR "case study" OR partnership OR contract {year}',
                    "traction_analyst"))
    if has_customers:
        out.append(("reviews", f'"{name}" reviews G2 OR Capterra OR Trustpilot OR "App Store"', "retention_analyst"))
    if (profile.country or "AU").upper() not in ("AU", "AUS") and not typed.get("target_customer_count"):
        target = typed.get("target_customer") or profile.sector
        from ..tools.search import country_name

        out.append(("market_bottom_up", f"number of {target} {country_name(profile.country)} statistics",
                    "market_sizer"))
    if _IP_RE.search(site_text) or typed.get("patents") or typed.get("trademarks"):
        out.append(("ip", f'"{name}" patent OR trademark site:ipaustralia.gov.au OR patents.google.com',
                    "moat_analyst"))
    return [(k, sanitize_query(q)[:200], a) for k, q, a in out]


def run_searches(profile: StartupProfile, state: dict, deps: Deps, pool: list[tuple], typed: dict,
                 searches: list[dict], year: int) -> int:
    fetch = deps.fetcher or fetch_page
    paid_used = sum(1 for s in searches if s.get("kind") in ANALYST_KINDS and s.get("provider") in
                    PAID_SEARCH_PROVIDERS)
    stored = 0
    for kind, query, agent in plan_searches(profile, pool, typed, year):
        if paid_used >= analyst_paid_search_max():  # paid provider already answered the allowed number
            deps.audit.record(agent, "search_skipped", kind=kind, reason="ANALYST_PAID_SEARCH_MAX reached")
            continue
        results = budgeted_search(deps, agent, searches, kind, query)
        if searches and searches[-1].get("kind") == kind and searches[-1].get("provider") in PAID_SEARCH_PROVIDERS:
            paid_used += 1
        for i, r in enumerate((results or [])[: deps.settings.search_fetch_per_query + 2]):
            if store_result(deps, agent, r, query, state["job_id"],
                            fetch if i < deps.settings.search_fetch_per_query else None):
                stored += 1
    return stored


def run_lookups(profile: StartupProfile, site_url: str, deps: Deps, lk: lookups_mod.Lookups | None = None) -> dict:
    lk = lk or lookups_mod.Lookups(deps.evidence)
    out: dict = {}
    for key, fn in (("tranco", lambda: lk.tranco(site_url)), ("wayback", lambda: lk.wayback_first_seen(site_url)),
                    ("app_store", lambda: lk.app_store(profile.company_name, site_url,
                                                       "au" if (profile.country or "AU").upper() in ("AU", "AUS")
                                                       else (profile.country or "us")[:2])),
                    ("abn", lambda: lk.abn(profile.company_name))):
        try:
            v = fn()
        except Exception:  # noqa: BLE001
            v = {}
        if v:
            out[key] = v
    return out


def lookup_metrics(lookups: dict) -> dict[str, MetricValue]:
    """Public lookup values that feed scoring (level 3, source "lookup")."""
    out: dict[str, MetricValue] = {}
    app = lookups.get("app_store") or {}
    if app.get("matched") and app.get("rating") is not None and app.get("rating_count"):
        out["review_rating"] = MetricValue(value=float(app["rating"]), unit="rating", level=3, source="lookup",
                                           source_url=app.get("source_url") or "",
                                           note=f"App Store, {app['rating_count']:,} ratings")
        out["review_count"] = MetricValue(value=float(app["rating_count"]), unit="count", level=3, source="lookup",
                                          source_url=app.get("source_url") or "")
    return out


def stage_evidence(result: dict, typed: dict, claims: list[VerifiedClaim], today: str) -> stage_tools.StageEvidence:
    """Stage evidence from the stored result + typed figures, completed with the analysts' verified revenue / ARR
    (the strongest level first) when neither the founder nor the website gave one."""
    ev = stage_tools.evidence_from_result({**result, "self_reported": typed}, typed, today)
    if ev.revenue_aud is None:
        rev = [c for c in claims if c.metric in ("arr", "revenue") and c.subject == "company" and c.value_aud]
        if rev:
            best = max(rev, key=lambda c: (c.level, c.as_of, c.value_aud or 0))
            ev.revenue_aud = best.value_aud
            ev.revenue_source = f"{best.metric} cited at {best.source_url}"
    return ev


# ------------------------------------------------------------------ the graph step
def run(state: dict, deps: Deps, *, today: date | None = None, lookups_client=None) -> dict:
    from . import market_size, moat, retention, traction

    t0 = time.monotonic()
    today = today or datetime.now(UTC).date()
    profile = StartupProfile.model_validate(state["profile"])
    typed = state.get("self_reported") or {}
    site_url = state.get("site_url") or state.get("url") or ""
    searches = [dict(x) for x in state.get("searches") or []]
    pool = evidence_pool(deps, state["job_id"])
    run_searches(profile, state, deps, pool, typed, searches, today.year)
    pool = evidence_pool(deps, state["job_id"])  # + pages the analyst searches stored
    lk = run_lookups(profile, site_url, deps, lookups_client)
    verifier = Verifier(pool, profile, site_url, today=today)
    ctx = {"profile": profile, "pool": pool, "verifier": verifier, "typed": typed, "competitors":
           state.get("competitors") or [], "market": state.get("market") or {}, "lookups": lk, "deps": deps}
    jobs = {"traction": traction.run, "market_size": market_size.run, "moat": moat.run, "retention": retention.run}
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="analyst") as ex:
        futs = {k: ex.submit(contextvars.copy_context().run, fn, ctx) for k, fn in jobs.items()}
        for k, f in futs.items():
            try:
                results[k] = f.result()
            except Exception as e:  # noqa: BLE001
                deps.audit.record("valuation", "analyst_failed", analyst=k, error=str(e)[:300])
                results[k] = {"claims": [], "dropped": [f"{k}: failed ({type(e).__name__})"], "error": str(e)[:200]}
    claims: list[VerifiedClaim] = []
    dropped: list[str] = []
    for k in jobs:
        claims += results[k].get("claims") or []
        dropped += results[k].get("dropped") or []
    metrics = lookup_metrics(lk)
    metrics.update(results["market_size"].get("metrics") or {})
    seed = Analysis(stage=stage_tools.classify_stage(stage_evidence(state, typed, claims, today.isoformat())),
        claims=claims, dropped=dropped, powers=results["moat"].get("powers") or [],
        market_sizing=results["market_size"].get("market_sizing") or MarketSizing(), lookups=lk, metrics=metrics,
        revenue_model=results["traction"].get("revenue_model") or "",
        analysts={k: {"claims": len(results[k].get("claims") or []), "dropped": len(results[k].get("dropped") or []),
                      "error": results[k].get("error", "")} for k in jobs})
    seed.analysts["searches"] = [s["kind"] for s in searches if s.get("kind") in ANALYST_KINDS]
    seed.analysts["seconds"] = round(time.monotonic() - t0, 1)
    analysis = evaluation.evaluate(seed, stage_decision=seed.stage, self_reported=typed,
                                   competitors=state.get("competitors") or [], sector=profile.sector)
    deps.audit.record("valuation", "analysts_done", claims=len(claims), dropped=len(dropped),
                      stage=analysis.stage.stage, seconds=seed.analysts["seconds"])
    return {"analysis": analysis.model_dump(), "searches": searches}


def detail(analysis: dict | None) -> str:
    """Progress line: 'traction 62 · market 55 · moat 48 · retention n/a · stage seed'."""
    if not analysis:
        return "analysts skipped"
    dims = analysis.get("dimensions") or {}
    parts = []
    for k in ("traction", "market", "moat", "retention"):
        d = dims.get(k) or {}
        parts.append(f"{k} " + (f"{d.get('score', 0):.0f}" if d.get("status") == "scored" else "n/a"))
    return " · ".join(parts) + f" · stage {(analysis.get('stage') or {}).get('stage', '?')}"


# ------------------------------------------------------------------ v5 scoring of a (stored or in-flight) result
def rescore_v5(result: dict, *, svi_dict: dict | None = None, qualitative: dict | None = None,
               self_reported: dict | None = None, documents: list[dict] | None = None, kpis: dict | None = None,
               stage_override: dict | None = None, today: str = "", verifications: dict | None = None,
               allow_empty_seed: bool = False) -> dict:
    """Deterministic v5 re-score (no web, no LLM): evaluation.evaluate over the stored analysis seed + current typed
    figures + documents (+ approved KPI series), then svi.apply_v5 and the triangulation refresh with the new index.
    `result` = a graph state or a stored valuation result (profile, market, competitors, valuation_evidence,
    svi.analysis or analysis). Returns the new svi dict."""
    from ..schemas import MarketAnalysis, StageDecision, SVIResult
    from ..tools import svi as svi_tools

    s = svi_dict if svi_dict is not None else (result.get("svi") or {})
    seed = result.get("analysis") or s.get("analysis")
    sr = self_reported if self_reported is not None else (result.get("self_reported") or {})
    q = qualitative if qualitative is not None else (result.get("qualitative") or {})
    if not seed:
        if not allow_empty_seed:
            raise ValueError("no v5 analysis stored for this valuation")
        seed = Analysis(stage=stage_tools.classify_stage(stage_tools.evidence_from_result(result, sr, today)))
    seed_a = Analysis.model_validate(seed)
    if verifications is None:
        verifications = (result.get("metric_verifications") or {})
    if stage_override:
        sd = StageDecision.model_validate(stage_override)
    elif seed_a.stage.basis == "human":
        sd = seed_a.stage
    else:
        doc_claims = [c for d in documents or [] for c in ((d.get("parsed") or {}).get("claims") or [])]
        from ..schemas import VerifiedClaim as _VC

        ev = stage_evidence(result, sr, list(seed_a.claims) + [_VC.model_validate(c) for c in doc_claims], today)
        for d in documents or []:
            rt = (d.get("parsed") or {}).get("round_type")
            if rt:
                ev.rounds.append(stage_tools.RoundSignal(rt, "", f"doc:{d.get('doc_id')}"))
        if kpis and kpis.get("revenue_ttm_aud"):
            ev.revenue_aud = max(c.value for c in kpis["revenue_ttm_aud"] if c.value is not None)
            ev.revenue_source = "approved KPI updates"
        sd = stage_tools.classify_stage(ev)
    profile = StartupProfile.model_validate(result["profile"])
    analysis = evaluation.evaluate(seed_a, stage_decision=sd, self_reported=sr, documents=documents,
                                   competitors=result.get("competitors") or [], qualitative=q, kpis=kpis,
                                   sector=profile.sector, verifications=verifications)
    res = svi_tools.apply_v5(SVIResult.model_validate(s), analysis)
    try:  # keep the headline blend consistent with the new index (the valuation engine may replace this)
        from . import valuation as valuation_agent

        market = MarketAnalysis.model_validate(result["market"]) if result.get("market") else None
        tri = valuation_agent.triangulate_result(res, profile, market, result)  # v3, or the v5 engine
        svi_tools.apply_triangulation(res, tri)
    except Exception:  # noqa: BLE001 - no market / engine changed: keep the stored triangulation
        pass
    return res.model_dump()
