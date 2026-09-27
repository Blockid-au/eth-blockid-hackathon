"""Site intake — read a startup's PUBLIC website and extract a StartupProfile (cloud tier).

Crawler rules: same site only (host or its www. twin), at most SITE_MAX_PAGES pages (default 6: the homepage
plus the highest-priority about / product / pricing / customers / team / press pages), robots.txt
respected for our user agent, HTML only, query strings dropped, redirects followed manually so
every hop is re-checked. SSRF guard: every hostname must resolve to public IP addresses only
(no loopback / private / link-local / internal service names such as `issuer` or `postgres`).
Emails and phone numbers are stripped before any text is stored or shown to a model.
"""
from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx
from pydantic import BaseModel, Field

from ..deps import Deps
from ..schemas import SELF_REPORTED_TO_METRIC, EvidenceItem, SelfReportedMetrics, StartupProfile
from ..tools.brave import _EMAIL, _PHONE, html_to_text
from ..tools.safefetch import UA, FetchError, SafeFetcher, public_host  # noqa: F401 (re-exported)

AGENT = "site_intake"
CRAWL_DEADLINE_S = 120.0
PAGE_CHARS = 6_000
SKIP_EXT = re.compile(
    r"\.(pdf|jpe?g|png|gif|svg|webp|ico|css|js|json|xml|zip|gz|mp4|mp3|mov|avi|woff2?|ttf|eot|docx?|xlsx?|pptx?)$", re.I
)
# Most useful first for a valuation: what the company is, what it sells, for how much, to whom, who runs it.
PRIORITY_GROUPS = (
    ("about", "company", "mission", "story", "who-we-are"),
    ("product", "platform", "solution", "feature", "how-it-works", "service"),
    ("pricing", "plans"),
    ("customer", "case-stud", "client", "success"),
    ("team", "leadership", "founder", "people"),
    ("press", "news", "media", "investor"),
)
PRIORITY = tuple(k for g in PRIORITY_GROUPS for k in g) + ("career", "partner")
LOW_PRIORITY = ("login", "signin", "sign-in", "signup", "register", "cart", "checkout", "privacy", "terms", "cookie",
                "legal", "account", "tag/", "category/", "author/", "wp-", "/feed")

SYSTEM = """You are the BlockID intake analyst. Extract a factual StartupProfile from the company's PUBLIC
website pages.
Rules:
- Use ONLY facts stated on the pages. Unknown numbers stay 0; never estimate revenue, growth, margin, burn or runway.
- company_name: the trading or legal name shown on the site. country: ISO 3166 alpha-2 of the headquarters if stated
  (the domain's country-code TLD is a hint, not proof).
- sector: a short neutral category (e.g. "online graphic design software"). stage: best judgement from the site
  (idea / pre-seed / seed / series-a / growth); large, established companies are "growth".
- description: 2-3 neutral sentences on what the company sells and to whom — no marketing superlatives.
- founders: only people the site presents as founders or executives, with their role; experience only if stated.
- metrics: only explicit figures (e.g. "2,000 paying customers", "raised A$5M"). Monetary values in AUD.
- competitors: only companies named on the site as alternatives or competitors (usually none).
- search_keywords: 3-6 neutral market terms (category, product type, region). No people's names.
- missing_items: what an investor would still need that a website cannot show (audited financial statements,
  cap table, constitution, IP assignment deeds, KYC of directors, ...)."""


class SiteError(RuntimeError):
    pass


# ------------------------------------------------------------------ URL + SSRF guard
def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname or "." not in p.hostname:
        raise SiteError(f"not a website URL: {url!r}")
    if p.username or p.password:
        raise SiteError("URLs with credentials are not allowed")
    return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path or "/", "", "", ""))


def site_key(host: str) -> str:
    host = (host or "").lower()
    return host[4:] if host.startswith("www.") else host


def strip_contacts(text: str) -> str:
    return _PHONE.sub("[phone]", _EMAIL.sub("[email]", text))


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []
        self.title = ""
        self.description = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag == "title":
            self._in_title = True
        elif tag == "meta" and (a.get("name") or a.get("property") or "").lower() in ("description", "og:description"):
            self.description = self.description or (a.get("content") or "")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


@dataclass
class Page:
    url: str
    title: str
    text: str


@dataclass
class CrawlResult:
    start_url: str
    final_url: str = ""
    pages: list[Page] = field(default_factory=list)
    robots_blocked: int = 0
    errors: list[str] = field(default_factory=list)


def _score(url: str) -> float:
    """Lower is fetched first: 0-5 priority groups, 6 other known pages, 7 top-level, 8 deeper, 9 low value."""
    path = urlparse(url).path.lower()
    if any(k in path for k in LOW_PRIORITY):
        return 9
    for i, group in enumerate(PRIORITY_GROUPS):
        if any(k in path for k in group):
            return i if path.count("/") <= 2 else i + 0.5
    if any(k in path for k in PRIORITY):
        return 6
    return 7 if path.count("/") <= 2 else 8


def crawl(start_url: str, *, max_pages: int = 6, transport: httpx.BaseTransport | None = None,
          host_ok: Callable[[str], bool] | None = None, timeout: float = 10, page_deadline: float = 20,
          crawl_deadline: float = CRAWL_DEADLINE_S) -> CrawlResult:
    """host_ok=None (production) -> public-DNS check + IP pinning in SafeFetcher; tests pass a predicate."""
    start = normalize_url(start_url)
    res = CrawlResult(start_url=start)
    f = SafeFetcher(transport, host_ok, timeout=timeout, page_deadline=page_deadline)
    stop_at = time.monotonic() + crawl_deadline
    robots: dict[str, RobotFileParser | None] = {}

    def allowed(url: str) -> bool:
        p = urlparse(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin not in robots:
            rp: RobotFileParser | None = RobotFileParser()
            try:
                _, r = f.get(origin + "/robots.txt")
                if r.status_code in (401, 403):
                    rp.disallow_all = True
                elif r.status_code == 200 and "html" not in r.headers.get("content-type", ""):
                    rp.parse(r.text.splitlines())
                else:
                    rp = None  # no robots.txt -> everything allowed
            except Exception:
                rp = None
            robots[origin] = rp
        rp = robots[origin]
        return rp is None or rp.can_fetch("BlockID-Research", url)

    base = site_key(urlparse(start).hostname or "")
    frontier: list[tuple[int, int, str]] = [(-1, 0, start)]
    queued = {start}
    order = 0
    try:
        while frontier and len(res.pages) < max_pages:
            if time.monotonic() > stop_at:
                res.errors.append(f"crawl deadline ({crawl_deadline:.0f}s) reached")
                break
            frontier.sort()
            _, _, url = frontier.pop(0)
            if not allowed(url):
                res.robots_blocked += 1
                continue
            try:
                final, r = f.get(url)
            except Exception as e:
                res.errors.append(f"{url}: {e}")
                continue
            if url == start and r.status_code == 200 and site_key(urlparse(final).hostname or "") != base:
                # The address the founder gave redirects to another domain (rebrand / regional site):
                # follow the new domain and record it, instead of failing the whole valuation.
                res.errors.append(f"{start}: redirects to {final}; following the new domain")
                base = site_key(urlparse(final).hostname or "")
            if site_key(urlparse(final).hostname or "") != base or r.status_code != 200:
                res.errors.append(f"{url}: HTTP {r.status_code}" if r.status_code != 200 else f"{url}: left the site")
                continue
            if "html" not in r.headers.get("content-type", "text/html"):
                continue
            if not res.final_url:
                res.final_url = final
            html = r.text
            lp = _LinkParser()
            try:
                lp.feed(html)
            except Exception:
                pass
            text = strip_contacts(html_to_text(html, limit=PAGE_CHARS * 2))[:PAGE_CHARS]
            if lp.description and lp.description not in text:
                text = strip_contacts(lp.description) + " " + text
            if text.strip() and final not in {p.url for p in res.pages}:
                res.pages.append(Page(url=final, title=" ".join(lp.title.split())[:200], text=text))
            for href in lp.links:
                link = urldefrag(urljoin(final, href.strip()))[0]
                p = urlparse(link)
                if p.scheme not in ("http", "https") or site_key(p.hostname or "") != base or SKIP_EXT.search(p.path):
                    continue
                link = urlunparse((p.scheme, p.netloc.lower(), p.path.rstrip("/") or "/", "", "", ""))
                if link in queued or _score(link) >= 9:  # login / legal / cart pages are never worth a slot
                    continue
                queued.add(link)
                order += 1
                frontier.append((_score(link), order, link))
    finally:
        f.close()
    if not res.final_url:
        res.final_url = start
    return res


# ------------------------------------------------------------------ founder-provided figures
def apply_self_reported(p: StartupProfile, self_reported: dict | None) -> list[str]:
    """Founder-provided figures override what the website stated. Returns the metric fields overridden."""
    if not self_reported:
        return []
    sr = SelfReportedMetrics.model_validate(self_reported)  # re-checked: state may come from a stored row
    used = []
    for k, v in sr.model_dump(exclude_none=True).items():
        if k in SELF_REPORTED_TO_METRIC:
            setattr(p.metrics, SELF_REPORTED_TO_METRIC[k], v)
            used.append(SELF_REPORTED_TO_METRIC[k])
    return used


# ------------------------------------------------------------------ graph nodes
def site_subject(vid: str) -> str:
    return f"{vid}:site"


def read_site(state: dict, deps: Deps) -> dict:
    vid = state["job_id"]
    deps.tool(AGENT, "fetch_url", url=state["url"], max_pages=deps.settings.site_max_pages)
    res = crawl(state["url"], max_pages=deps.settings.site_max_pages,
                transport=deps.site_transport, host_ok=deps.host_check)
    if not res.pages:
        detail = "; ".join(res.errors[:3]) or ("blocked by robots.txt" if res.robots_blocked else "no readable pages")
        raise SiteError(f"could not read {res.start_url}: {detail}")
    now = time.time()
    for p in res.pages:
        item = EvidenceItem(url=p.url, title=p.title or p.url, snippet=p.text[:300], retrieved_at=now,
                            content_sha256=hashlib.sha256(p.text.encode()).hexdigest(), query="site")
        deps.evidence.add(item, p.text, site_subject(vid))
    deps.audit.record(AGENT, "site_read", url=res.final_url, pages=len(res.pages), robots_blocked=res.robots_blocked)
    return {"site_url": res.final_url, "site_pages": len(res.pages)}


def profile(state: dict, deps: Deps) -> dict:
    vid = state["job_id"]
    pages = sorted(deps.evidence.for_subject(site_subject(vid), limit=deps.settings.site_max_pages),
                   key=lambda x: (_score(x[0].url) if x[0].url != state.get("site_url") else -1, x[0].url))
    body = "\n\n".join(f"### {ev.title}\nURL: {ev.url}\n{text[:PAGE_CHARS]}" for ev, text in pages)
    host = urlparse(state.get("site_url") or state["url"]).hostname or ""
    user = f"Website: {host}\n\n<data>\n{body}\n</data>"
    p = deps.ask(AGENT, "cloud", SYSTEM, user, StartupProfile)
    p.documents_reviewed = [ev.url for ev, _ in pages]
    used = apply_self_reported(p, state.get("self_reported"))
    # provenance, set by code: founder-typed figures, else what the site stated (0 = unknown, no entry)
    p.metrics_sources = {k: "self_reported" if k in used else "website"
                         for k, v in p.metrics.model_dump().items() if k in used or v}
    deps.tool(AGENT, "store_profile", company=p.company_name, pages=len(pages), self_reported=used)
    return {"profile": p.model_dump(), "status": "profiled"}


# ------------------------------------------------------------------ people on team / about pages (hr suggestions)
# Deterministic, no model: "Jane Doe — CEO", "Jane Doe, Co-founder & CTO", "Jane Doe is the CEO", "CEO: Jane Doe".
# Used by GET /v1/hr/suggest-people (studio/hr.py) on pages site intake already stored, or one fetched /team page.
TEAM_WORDS = ("team", "leadership", "founder", "people", "management", "board", "who-we-are")
ABOUT_WORDS = ("about", "company", "story", "mission")
_ROLE = re.compile(
    r"\b(?:co-?\s?founder(?:\s*(?:&|and|/)\s*(?:ceo|cto|coo|cfo|cpo|chief\s+\w+\s+officer))?"
    r"|founder(?:\s*(?:&|and|/)\s*(?:ceo|cto|coo|cfo|managing\s+director))?"
    r"|chief\s+\w+(?:\s+\w+)?\s+officer|ceo|cto|cfo|coo|cmo|cpo|cro|cio"
    r"|head\s+of\s+[a-z]+(?:\s+[a-z]+)?|managing\s+director|non-executive\s+director|general\s+manager"
    r"|(?:vp|vice\s+president)(?:\s+of)?\s+[a-z]+|president|chair(?:man|woman|person)?"
    r"|(?:board\s+)?advis[eo]r|director(?:\s+of\s+[a-z]+)?|product\s+manager"
    r"|(?:lead|senior|principal)\s+(?:software\s+)?(?:engineer|designer|developer|scientist))\b", re.I)
_NAME_STOP = {"our", "the", "team", "meet", "about", "us", "leadership", "founders", "founder", "board", "advisors",
              "advisory", "contact", "home", "careers", "company", "management", "and", "with", "from", "by", "of",
              "as", "is", "we", "at", "for", "in", "on", "a", "an", "led", "former", "previously", "chief", "head",
              "ceo", "cto", "cfo", "coo", "cmo", "director", "manager", "vp", "president", "co-founder", "cofounder",
              "executive", "officer", "senior", "lead", "principal", "engineer", "partner", "partners", "people"}
_SEP_BEFORE = re.compile(r"(?:\s*(?:,|\||:|–|—|-|\(|/)\s*|\s+is\s+(?:the\s+|our\s+|a\s+|an\s+)?|\s+as\s+(?:the\s+|our\s+)?"
                         r"|\s+)$", re.I)


def _name_token(tok: str) -> bool:
    t = tok.strip(".,;:()'\"")
    return (2 <= len(t) <= 24 and t[0].isupper() and not t.isupper() and t.lower() not in _NAME_STOP
            and all(c.isalpha() or c in "'’-." for c in t))


def _name_before(text: str) -> str | None:
    m = _SEP_BEFORE.search(text)
    head = text[:m.start()] if m else text
    toks = head.split()[-4:]
    out: list[str] = []
    for tok in reversed(toks):
        if not _name_token(tok) or tok.endswith((".", ",", ":", ";")) and out:
            break
        out.insert(0, tok.strip(".,;:()'\""))
    return " ".join(out) if 2 <= len(out) <= 4 else None


def _name_after(text: str) -> str | None:
    m = re.match(r"\s*(?::|–|—|\s-\s)\s*", text)
    if not m:
        return None
    out: list[str] = []
    for tok in text[m.end():].split()[:4]:
        clean = tok.strip(".,;:()'\"")
        if not _name_token(clean):
            break
        out.append(clean)
        if tok.endswith((",", ".", ";", ")")):
            break
    return " ".join(out) if 2 <= len(out) <= 4 else None


def person_kind(role: str) -> str:
    r = (role or "").lower()
    if re.search(r"advis|board|non-executive|chair", r):
        return "advisor"
    if re.search(r"co-?\s?founder", r):
        return "founder" if re.search(r"\bceo\b|chief executive|managing director", r) else "cofounder"
    if "founder" in r:
        return "founder"
    if re.search(r"\bc[a-z]o\b|chief|head of|director|president|\bvp\b|general manager", r):
        return "executive"
    return "employee"


def people_from_text(text: str, exclude: tuple[str, ...] = ()) -> list[dict]:
    """[{full_name, role}] named with a role in a page's text (order of appearance, deduped, <= 20)."""
    text = " ".join(strip_contacts(text or "").split())
    bad = {w.lower() for x in exclude for w in re.split(r"\W+", x or "") if len(w) >= 3}
    out: dict[str, dict] = {}
    for m in _ROLE.finditer(text):
        role = " ".join(m.group(0).split())
        more = re.match(r"\s*(?:&|and|/|,)\s*(co-?\s?founder|founder)\b", text[m.end():m.end() + 30], re.I)
        if more and "founder" not in role.lower():
            role = f"{role} & {more.group(1)}"
        name = _name_before(text[max(0, m.start() - 80):m.start()]) or _name_after(text[m.end():m.end() + 80])
        if not name or {w.lower() for w in name.split()} & bad:
            continue
        key = name.lower()
        if key in out:
            if len(role) > len(out[key]["role"]) and role.lower() not in out[key]["role"].lower():
                out[key]["role"] = f"{out[key]['role']} & {role}"[:80]
            continue
        out[key] = {"full_name": name, "role": role[:80]}
        if len(out) >= 20:
            break
    for p in out.values():
        r = p["role"]
        p["role"] = r if not r.islower() else (r.upper() if len(r) <= 3 else r[0].upper() + r[1:])
    return list(out.values())


def page_rank(url: str) -> int:
    path = urlparse(url).path.lower()
    return 0 if any(w in path for w in TEAM_WORDS) else 1 if any(w in path for w in ABOUT_WORDS) else 2


# ------------------------------------------------------------------ model fallback for hr suggestions
# docs/PLAN-AI-GATEWAY.md §2: when the deterministic parser above finds nobody, GET /v1/hr/suggest-people may make
# ONE cheap `extract_json`-profile model call over the team / about text it ALREADY has (stored by site intake or
# the one /team fetch) — never a new search or fetch. Budgeted by the caller (per-user rate limit + a daily cap).
# Every name the model returns must appear in the page it cites (code check), so nothing is invented.
SUGGEST_CHARS = 12_000  # total page text sent to the model
SUGGEST_SYSTEM = """You list the people named on a company's own team / about pages. Return ONLY people the text
names with a job title or role at THIS company (founders, executives, team members, advisors, board). For each:
full_name exactly as written, role (short, as written, "" if none) and page (the URL of the page naming them).
Never guess, never add people who are not in the text, never include contact details. Empty list if nobody."""


class SuggestedPerson(BaseModel):
    full_name: str = Field(max_length=120)
    role: str = Field(default="", max_length=120)
    page: str = Field(default="", max_length=500)


class SuggestedPeople(BaseModel):
    people: list[SuggestedPerson] = Field(default_factory=list, max_length=30)


def complete_profile(llm, profile: str, tier: str, system: str, user: str, schema):
    """complete_json with a gateway task profile when the client supports one (llm.py `profile=` keyword), else the
    plain call."""
    import inspect

    try:
        params = inspect.signature(llm.complete_json).parameters
        takes = "profile" in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    except (TypeError, ValueError):
        takes = False
    if takes:
        return llm.complete_json(tier, system, user, schema, profile=profile)
    return llm.complete_json(tier, system, user, schema)


def suggest_people_with_model(llm, pages: list[tuple[str, str]], exclude: tuple[str, ...] = (), *,
                              tier: str = "cloud") -> list[dict]:
    """[{full_name, role, source_url}] from ONE model call over already-stored page text [(url, text)] (team /
    about pages first). Names not literally on the cited page (or any given page) are dropped."""
    from .people import fold, names_person

    pages = [(u, " ".join(strip_contacts(t or "").split())) for u, t in sorted(pages, key=lambda x: page_rank(x[0]))
             if (t or "").strip()]
    if not pages:
        return []
    budget, blocks, used = SUGGEST_CHARS, [], []
    for u, t in pages:
        if budget <= 200:
            break
        blocks.append(f'<page url="{u}">\n{t[:budget]}\n</page>')
        used.append((u, t))
        budget -= min(len(t), budget)
    out = complete_profile(llm, "extract_json", tier, SUGGEST_SYSTEM, "\n\n".join(blocks), SuggestedPeople)
    bad = {w.lower() for x in exclude for w in re.split(r"\W+", x or "") if len(w) >= 3}
    found: dict[str, dict] = {}
    for p in out.people:
        name = " ".join((p.full_name or "").split())
        if (len(name.split()) < 2 or any(ch.isdigit() for ch in name) or "@" in name
                or {w.lower() for w in name.split()} & bad or fold(name) in found):
            continue
        cited = next(((u, t) for u, t in used if u == p.page), None)
        where = next((u for u, t in ([cited] if cited else []) + used if names_person(t, name)), None)
        if where is None:
            continue
        found[fold(name)] = {"full_name": name[:120], "role": " ".join((p.role or "").split())[:80],
                             "source_url": where}
    return list(found.values())[:12]
