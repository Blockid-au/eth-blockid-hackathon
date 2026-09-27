"""People Analyst — founding-team and person review (docs/PLAN-HR.md; API in studio/hr.py).

Pipeline per person (policy "people_analyst": web_search / fetch_url / store_evidence only, no keys):
  1. provided URLs first (SSRF-safe fetch, tools/brave.fetch_page; LinkedIn is not readable -> listed, not fetched)
  2. at most HR_SEARCHES_PER_PERSON (3) searches per person and HR_SEARCHES_PER_TEAM (12) per team, round-robin in
     role priority order, on the People Analyst's own search chain (HR_SEARCH_PROVIDERS, default claude,brave);
     top pages fetched, further results kept as search snippets
  3. every page / snippet stored as evidence (URL, time, SHA-256 of the stored text) under `hr:<team>:<person>`;
     emails and phone numbers are redacted from founder text, pages and queries before anything is stored or sent
  4. ONE model call per person (HR LLM chain) -> PersonAnalysis: facts with verbatim quotes + source URL, a CV-style
     profile, suggested quality sub-scores and (with a target) fit sub-scores, each citing fact ids
  5. CODE verification: a fact is kept only if its quote is on the stored page / snippet, that page names the person,
     and the page names the company (or an organisation the person self-reported) or is a URL the founder provided.
     Everything else goes to "unconfirmed". Sensitive categories (health, religion, politics, family, address, phone,
     personal email, age, ethnicity, sexuality) are dropped by keyword filter whatever the model returned.
  6. ONE model call per team -> TeamAnalysis (worked-together evidence, strengths, gaps, risks, questions, red flags)
  7. CODE scoring (below). The model never produces a final score.

Live progress: every step also reports to a `Tracker` (studio/hr_store.HrProgress writes it to the report row for
GET /v1/hr/teams/{id} -> "progress"; see the contract in studio/hr.py): plain-English feed lines, counters, the
current step, per-person partial results as soon as a person is scored, and model / search fallbacks (llm.emit).

Nothing to analyse (docs/PLAN-AI-GATEWAY.md §2): when searches ran but nothing was found or readable and nobody
has self-reported information, the run stops BEFORE any model call with NoPublicInfo / SourcesUnreachable (their
`code` is the user-facing error code, studio/hr_store.ERROR_TEXT) instead of letting a model guess.

Scoring (all in code):
  person quality = sum(weight x sub-score) / 100, weights PERSON_WEIGHTS (25/25/15/15/10/10); a sub-score with no
    verified cited fact and no founder-provided support is capped at 50 (verifiability: founder text never counts)
  fit = sum(FIT_WEIGHTS x component) / 100; `gaps` is computed from the requirement matches
  contribution = 0.5 x quality + 0.5 x fit (quality alone when there is no fit)
  team = 0.6 x role-weighted mean of contributions (ROLE_MULTIPLIERS) + 0.4 x team component (TEAM_WEIGHTS over
    complementarity, key roles, worked together, advisors/board, key-person concentration) - verified red flags
    (5 points each, at most 15), clamped 0..100
"""
from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from datetime import UTC, datetime
from typing import Callable, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from ..deps import Deps
from ..llm import last_provider, primary_provider, provider_label, reset_listener, set_listener
from ..schemas import EvidenceItem
from ..tools.brave import fetch_page, sanitize_query

AGENT = "people_analyst"
VERSION = "hr-1"

PERSON_WEIGHTS = {"domain_fit": 25, "track_record": 25, "leadership": 15, "functional_depth": 15,
                  "verifiability": 10, "commitment": 10}
FIT_WEIGHTS = {"skills_match": 25, "domain_match": 20, "stage_scale_match": 15, "seniority_match": 15,
               "track_record_relevance": 15, "gaps": 10}
TEAM_WEIGHTS = {"complementarity": 0.30, "key_roles": 0.25, "worked_together": 0.15, "advisors_board": 0.10,
                "concentration": 0.20}
ROLE_MULTIPLIERS = {"ceo": 1.5, "founder": 1.5, "cofounder": 1.2, "executive": 1.0, "employee": 0.7, "advisor": 0.4}
PEOPLE_SHARE, TEAM_SHARE = 0.6, 0.4
CAP_WITHOUT_EVIDENCE = 50.0
RED_FLAG_POINTS, RED_FLAG_MAX = 5.0, 15.0
QUALITY_FIT_SPLIT = 0.5
FUNCTIONS = ("tech", "commercial", "domain", "finance")
KINDS = ("founder", "cofounder", "executive", "employee", "advisor")
FETCH_PER_QUERY = 2
SNIPPETS_PER_QUERY = 3
PAGE_EXCERPT = 3_500
MAX_PAGES_IN_PROMPT = 10
CV_CHARS = 8_000
UNREADABLE_HOSTS = ("linkedin.com", "facebook.com", "instagram.com", "x.com", "twitter.com")

# ------------------------------------------------------------------ privacy: redaction + sensitive categories
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<!\w)\+?\(?\d[\d\s().-]{7,}\d(?!\d)")
# Personal-context patterns (not bare topic words: a health-tech founder or "Wall Street" must not be dropped).
SENSITIVE = re.compile("|".join([
    # health
    r"\bdiagnosed with\b", r"\bsuffer(?:s|ed|ing)? from\b", r"\bbattl(?:e|ed|ing) (?:with )?(?:cancer|illness)",
    r"\b(?:his|her|their) (?:\w+ ){0,2}(?:illness|disease|cancer|diagnosis|medical condition|disability|pregnancy"
    r"|surgery|depression|anxiety|health)\b", r"\bmental health (?:issues?|struggles?|condition)\b",
    r"\bmedical leave\b", r"\bpregnan\w*", r"\bdisabilit(?:y|ies)\b",
    # religion
    r"\breligio(?:n|us)\b", r"\bdevout\b", r"\b(?:his|her|their) faith\b",
    r"\battends? (?:church|mosque|synagogue|temple)\b",
    r"\b(?:is|as) an? (?:christian|muslim|jew|jewish|hindu|buddhist|catholic|atheist)\b",
    # politics
    r"\bpolitical (?:party|views?|affiliation|beliefs?|leanings?)\b",
    r"\bmember of the (?:\w+ )?(?:labor|labour|liberal|green|greens|democratic|republican|national) party\b",
    r"\bvot(?:es|ed|ing) for\b", r"\bsupporter of the \w+ party\b",
    # family / relationships
    r"\bmarried\b", r"\bwife\b", r"\bhusband\b", r"\bspouse\b", r"\bdivorc\w*", r"\bwidow\w*", r"\bfiancée?\b",
    r"\b(?:his|her|their) (?:\w+ )?(?:children|kids|sons?|daughters?|mother|father|parents|family|partner|"
    r"girlfriend|boyfriend)\b", r"\b(?:father|mother) of (?:two|three|four|\d)\b",
    r"\bhas (?:\w+ )?(?:children|kids)\b",
    # home address / contact
    r"\bhome address\b", r"\bresides at\b", r"\bresidential address\b", r"\blives (?:at|on) \d",
    r"\b\d{1,5}\s+(?:\w+\s+){1,3}(?:street|st|road|rd|avenue|ave|drive|dr|lane|ln|court|ct|parade|pde)\b",
    r"\b(?:mobile|phone|cell|whatsapp)(?: number)?\s*[:#]", r"\bpersonal e-?mail\b", r"\[email\]", r"\[phone\]",
    # age / birth, ethnicity, sexuality
    r"\bdate of birth\b", r"\bborn (?:on|in) (?:\d|19\d\d|20\d\d|january|february|march|april|may|june|july"
    r"|august|september|october|november|december)", r"\baged \d+\b", r"\b\d{2} years old\b",
    r"\bethnicity\b", r"\bethnic (?:background|origin)\b", r"\bracial background\b", r"\bsexual orientation\b",
    r"\b(?:gay|lesbian|bisexual|transgender)\b",
]), re.IGNORECASE)


def _is_phone(s: str) -> bool:
    digits = re.sub(r"\D", "", s)
    return 9 <= len(digits) <= 15 and not re.fullmatch(r"(?:19|20)\d\d\s*[-–]\s*(?:19|20)\d\d", s.strip())


def redact(text: str | None) -> str:
    """Emails / phone numbers (9-15 digits) -> placeholders (before storing, prompting or searching)."""
    t = _EMAIL.sub("[email]", text or "")
    return _PHONE.sub(lambda m: "[phone]" if _is_phone(m.group(0)) else m.group(0), t)


def has_phone(text: str) -> bool:
    return any(_is_phone(m.group(0)) for m in _PHONE.finditer(text or ""))


def is_sensitive(*texts: str | None) -> bool:
    return any(SENSITIVE.search(t or "") or _EMAIL.search(t or "") or has_phone(t or "") for t in texts)


# ------------------------------------------------------------------ text helpers
def fold(s: str) -> str:
    """lower-case, accents removed (Vietnamese names), quote marks and whitespace normalised."""
    s = unicodedata.normalize("NFKD", (s or "").replace("đ", "d").replace("Đ", "D"))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.sub(r"[‘’“”]", "'", s).lower().split())


def quote_in(quote: str, text: str, min_len: int = 12) -> bool:
    q = fold(quote)
    return len(q) >= min_len and q in fold(text)


def name_tokens(full_name: str) -> list[str]:
    return [t for t in re.split(r"[^\w']+", fold(full_name)) if len(t) >= 2]


def names_person(text: str, full_name: str) -> bool:
    """The page names the person: the full name, or first and last name within 40 characters of each other."""
    t, toks = fold(text), name_tokens(full_name)
    if not toks:
        return False
    if " ".join(toks) in t:
        return True
    if len(toks) == 1:
        return bool(re.search(rf"\b{re.escape(toks[0])}\b", t))
    first, last = re.escape(toks[0]), re.escape(toks[-1])
    return bool(re.search(rf"\b{first}\b.{{0,40}}\b{last}\b|\b{last}\b.{{0,40}}\b{first}\b", t))


_SUFFIX = re.compile(r"\b(pty|ltd|limited|inc|llc|corp|corporation|co|jsc|plc|gmbh|group|holdings)\b\.?", re.I)


def org_key(name: str) -> str:
    return " ".join(fold(_SUFFIX.sub(" ", name or "")).replace(",", " ").split())


def names_org(text: str, org: str) -> bool:
    k = org_key(org)
    return len(k) >= 3 and bool(re.search(rf"(?<!\w){re.escape(k)}(?!\w)", fold(text)))


def host(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def excerpts(text: str, full_name: str, head: int = 500, window: int = 450, limit: int = PAGE_EXCERPT) -> str:
    """The start of a page plus the passages around the person's last name."""
    toks = name_tokens(full_name)
    if not toks:
        return text[:limit]
    spans: list[list[int]] = [[0, min(head, len(text))]]
    for m in re.finditer(re.escape(toks[-1]), text, re.IGNORECASE):
        a, b = max(0, m.start() - window), min(len(text), m.end() + window)
        if a <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], b)
        else:
            spans.append([a, b])
    return " … ".join(text[a:b] for a, b in spans)[:limit]


def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return lo
    return lo if x != x else max(lo, min(hi, x))


def grade(score: float | None) -> str | None:
    if score is None:
        return None
    return "A" if score >= 80 else "B" if score >= 65 else "C" if score >= 50 else "D" if score >= 35 else "E"


# ------------------------------------------------------------------ LLM schemas (suggestions only)
class FactClaim(BaseModel):
    id: str = Field(description="f1, f2, ... unique within this person")
    text: str = Field(max_length=400)
    quote: str = Field(default="", max_length=600, description="verbatim excerpt of the cited page")
    source_url: str = ""
    category: Literal["role", "venture", "exit", "education", "achievement", "publication", "skill", "other"] = "other"


class Cited(BaseModel):
    fact_ids: list[str] = []
    cv_quote: str = Field(default="", max_length=400, description="exact excerpt of the founder-provided bio/CV")


class TextItem(Cited):
    text: str = Field(max_length=300)


class ExperienceItem(Cited):
    org: str = Field(max_length=200)
    title: str = Field(default="", max_length=200)
    start: str = ""
    end: str = ""
    achievements: list[str] = []


class EducationItem(Cited):
    institution: str = Field(max_length=200)
    degree: str = ""
    field: str = ""
    start: str = ""
    end: str = ""


class SkillGroup(Cited):
    group: str = Field(max_length=80)
    items: list[str] = []


class VentureItem(Cited):
    name: str = Field(max_length=200)
    role: str = ""
    outcome: Literal["exit", "acquired", "ipo", "active", "closed", "unknown"] = "unknown"
    year: str = ""


class PublicationItem(Cited):
    title: str = Field(max_length=300)
    kind: Literal["publication", "patent", "talk"] = "publication"
    venue: str = ""
    year: str = ""


class AwardItem(Cited):
    title: str = Field(max_length=300)
    year: str = ""


class CVDraft(BaseModel):
    headline: TextItem | None = None
    location: TextItem | None = None
    summary: str = Field(default="", max_length=1500)
    experience: list[ExperienceItem] = []
    education: list[EducationItem] = []
    skills: list[SkillGroup] = []
    ventures: list[VentureItem] = []
    publications: list[PublicationItem] = []
    awards: list[AwardItem] = []


class SubScore(BaseModel):
    score: float = Field(ge=0, le=100)
    rationale: str = Field(default="", max_length=600)
    fact_ids: list[str] = []
    self_reported: bool = False


class PersonScores(BaseModel):
    domain_fit: SubScore
    track_record: SubScore
    leadership: SubScore
    functional_depth: SubScore
    verifiability: SubScore
    commitment: SubScore


class RequirementMatch(BaseModel):
    requirement: str = Field(max_length=300)
    must_have: bool = True
    status: Literal["matched", "partial", "missing"] = "missing"
    fact_ids: list[str] = []
    self_reported: bool = False
    note: str = Field(default="", max_length=300)


class FitSuggestion(BaseModel):
    skills_match: SubScore
    domain_match: SubScore
    stage_scale_match: SubScore
    seniority_match: SubScore
    track_record_relevance: SubScore
    requirements: list[RequirementMatch] = []
    risks: list[str] = []
    interview_questions: list[str] = []


class PersonAnalysis(BaseModel):
    facts: list[FactClaim] = []
    profile: CVDraft = CVDraft()
    scores: PersonScores
    fit: FitSuggestion | None = None
    strengths: list[str] = []
    gaps: list[str] = []
    questions: list[str] = []
    functions: list[Literal["tech", "commercial", "domain", "finance"]] = []


class Component(BaseModel):
    score: float = Field(ge=0, le=100)
    rationale: str = Field(default="", max_length=600)
    fact_ids: list[str] = []


class RedFlagClaim(BaseModel):
    text: str = Field(max_length=400)
    fact_ids: list[str] = []


class TeamAnalysis(BaseModel):
    worked_together: Component
    strengths: list[str] = []
    gaps: list[str] = []
    risks: list[str] = []
    questions: list[str] = []
    red_flags: list[RedFlagClaim] = []


SYSTEM_PERSON = """You are the BlockID People Analyst. From the numbered evidence pages and the founder-provided
information, build the professional profile of ONE person and suggest scores. Rules:
- Public professional information only. NEVER output health, religion, political views, family or relationships,
  home address, phone numbers, email addresses, age / date of birth, ethnicity or sexual orientation — skip it.
- facts: professional facts about THIS person stated in the evidence pages (roles, companies founded, exits, funding
  raised, scale managed, education, publications, patents, talks, awards, skills). Each: id "f1", "f2", ...; a short
  neutral text; source_url copied exactly from the evidence list; quote copied character for character from that
  page (<= 300 chars) stating the fact. If a page may be about a different person with the same name, skip it.
- Never turn the founder-provided bio / CV into facts: it is self-reported. Profile items taken from it set cv_quote
  to an exact excerpt (<= 200 chars) of the bio / CV.
- profile: CV-style items, each citing fact_ids and/or cv_quote. location: city and country only.
- scores 0-100 with a rationale citing fact_ids (self_reported=true when it rests on founder-provided information):
  domain_fit (domain expertise, founder–market fit for the business), track_record (prior ventures, exits, scale
  managed), leadership (leadership and fit for the stated role), functional_depth (depth in their function: tech,
  commercial or finance), verifiability (how much is confirmed by independent sources), commitment (full-time,
  equity, tenure). Be conservative: missing evidence lowers a score.
- fit (only when a TARGET is given): skills_match, domain_match, stage_scale_match, seniority_match,
  track_record_relevance with rationale and fact_ids; requirements = the target's key requirements (a role: its
  listed requirements; a business: 4-8 derived from its sector, stage and product), each matched / partial /
  missing with fact_ids or self_reported and a short note; risks; interview_questions (3-6).
- strengths, gaps, questions (what an investor should ask this person), functions (tech, commercial, domain,
  finance) the person really covers."""

SYSTEM_TEAM = """You are the BlockID People Analyst reviewing a founding team. Using ONLY the people summaries and
their numbered verified facts, return:
- worked_together: 0-100, have these people worked together before (same prior company / venture at the same time)?
  Cite the fact ids; no cited fact -> at most 50.
- strengths, gaps (missing roles or skills), risks, questions investors should ask the team (3-6).
- red_flags: ONLY professional concerns stated by a verified fact (e.g. a failed venture with investor losses, a
  regulator action, litigation, a disqualified director), each citing fact ids. Never speculate. Empty is fine.
Never mention health, religion, politics, family, address, contact details, age, ethnicity or sexuality."""


# ------------------------------------------------------------------ research
Progress = Callable[[str, str | None, str], None]


class Tracker:
    """Live-progress sink (studio/hr_store.HrProgress). This base class ignores everything (tests, CLI).
    Step kinds with timings (ETA): fetch, search, person_model, team_model."""

    def plan(self, people: list[dict], *, fetches: int, searches: int, team: bool) -> None: ...
    def phase(self, phase: str) -> None: ...
    def begin(self, kind: str, person: str | None, step: str, detail: str = "") -> None: ...
    def end(self, kind: str) -> None: ...
    def note(self, msg: str, *, level: str = "info", person: str | None = None, source: str | None = None) -> None: ...
    def count(self, **inc: int) -> None: ...
    def person(self, pid: int, status: str, *, facts: list | None = None, score: float | None = None,
               fit: float | None = None) -> None: ...
    def llm_event(self, event: dict, person: str | None = None) -> None: ...


NULL_TRACKER = Tracker()


class ReviewError(RuntimeError):
    """A run that cannot produce a meaningful report; `code` is the user-facing error code (studio/hr_store
    ERROR_TEXT: the plain sentence shown to the requester; str(self) is the internal detail)."""
    code = "internal"


class NoPublicInfo(ReviewError):
    """Searches ran but found nothing about anyone, no link was readable and nobody has a bio / CV / headline."""
    code = "no_public_info"


class SourcesUnreachable(ReviewError):
    """Every search failed and no provided link could be read: nothing to analyse."""
    code = "sources_unreachable"


def check_evidence(people: list[dict], stored: dict, searches: list[dict], pages_fetched: int) -> None:
    """Raise NoPublicInfo / SourcesUnreachable before any model call when there is nothing to analyse (a model
    would only guess). Never raised when no search was attempted (search not configured: links / bios only)."""
    if not searches or any(stored.values()) or pages_fetched or any(has_founder_info(p) for p in people):
        return
    def unreachable(err: str | None) -> bool:  # "brave: no results; claude: no results" is an answer, not an outage
        return bool(err) and not all(part.strip().endswith("no results") for part in err.split(";"))

    if all(unreachable(x.get("error")) for x in searches):
        raise SourcesUnreachable(f"all {len(searches)} searches failed: {searches[-1].get('error')}")
    raise NoPublicInfo(f"{len(searches)} searches, {sum(int(x.get('results') or 0) for x in searches)} results, "
                       "no readable page and no self-reported information")


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def fit_word(score: float | None) -> str:
    if score is None:
        return ""
    return "Strong fit" if score >= 70 else "Partial fit" if score >= 50 else "Weak fit"


def _subject(team_id: str, pid) -> str:
    return f"hr:{team_id}:{pid}"


def person_queries(p: dict, company: str) -> list[str]:
    name = " ".join((p.get("full_name") or "").split())
    role = (p.get("role") or "").strip()
    headline = (p.get("headline") or "").strip()
    kind = p.get("kind") or "employee"
    qs = [f'"{name}" {company}' if company else f'"{name}" {headline or role}',
          f'"{name}" {headline}' if headline and company else f'"{name}" {role}',
          f'"{name}" {"advisor" if kind == "advisor" else "founder" if kind in ("founder", "cofounder") else role}']
    out: list[str] = []
    for q in qs:
        q = sanitize_query(redact(q))[:200].strip()
        if q and q != f'"{name}"' and q not in out:
            out.append(q)
    return out[:3]


def priority(p: dict) -> tuple[int, int]:
    return (0 if is_ceo(p) else {"founder": 1, "cofounder": 2, "executive": 3, "employee": 4, "advisor": 5}.get(
        p.get("kind") or "employee", 4), int(p.get("position") or 0))


_CEO = re.compile(r"\b(ceo|chief executive|managing director|md)\b", re.I)
_TECH = re.compile(r"\b(cto|chief technology|technical|engineering|engineer|developer|head of product|cpo|"
                   r"tech lead|architect|data scien\w*)\b", re.I)
_COMMERCIAL = re.compile(r"\b(coo|chief operating|cmo|cro|sales|commercial|growth|marketing|revenue|business "
                         r"development|partnerships|operations)\b", re.I)
_FINANCE = re.compile(r"\b(cfo|chief financial|finance|financial|accounting|treasurer)\b", re.I)


def is_ceo(p: dict) -> bool:
    return bool(_CEO.search(p.get("role") or ""))


def multiplier(p: dict) -> float:
    kind = p.get("kind") or "employee"
    if kind != "advisor" and is_ceo(p):
        return ROLE_MULTIPLIERS["ceo"]
    return ROLE_MULTIPLIERS.get(kind, ROLE_MULTIPLIERS["employee"])


class Research:
    """Evidence gathering for one report (budgeted search + SSRF-safe fetch + evidence store)."""

    def __init__(self, deps: Deps, team_id: str, progress: Progress, tracker: Tracker | None = None):
        self.deps, self.team_id, self.progress = deps, team_id, progress
        self.tracker = tracker or NULL_TRACKER
        self.planned_searches = 0
        self.fetch = deps.fetcher or fetch_page
        self.search = deps.search_for(AGENT)
        self.searches: list[dict] = []
        self.pages_fetched = 0
        self._fetched: dict[str, str] = {}

    def _get(self, url: str) -> str:
        if url in self._fetched:
            return self._fetched[url]
        self.deps.tool(AGENT, "fetch_url", url=url)
        try:
            text = self.fetch(url) or ""
            self.pages_fetched += 1
        except Exception as e:  # noqa: BLE001 - one page never fails the report
            self.deps.audit.record(AGENT, "fetch_error", url=url, error=str(e)[:300])
            text = ""
        self._fetched[url] = redact(text)
        return self._fetched[url]

    def store(self, subject: str, url: str, title: str, snippet: str, text: str, query: str, kind: str) -> bool:
        text, snippet = redact(text), redact(snippet)
        if not text.strip():
            return False
        item = EvidenceItem(url=url, title=(title or url)[:300], snippet=snippet[:500], retrieved_at=time.time(),
                            content_sha256=hashlib.sha256(text.encode()).hexdigest(), query=query, kind=kind)
        self.deps.tool(AGENT, "store_evidence", url=url, sha256=item.content_sha256)
        self.deps.evidence.add(item, text, subject)
        return True

    def provided(self, p: dict) -> list[str]:
        """Fetch the URLs the founder provided; returns the notes for unreadable ones."""
        notes = []
        for url in (p.get("urls") or [])[:6]:
            if not re.match(r"^https?://", url or ""):
                continue
            name = p.get("full_name")
            if any(host(url) == h or host(url).endswith("." + h) for h in UNREADABLE_HOSTS):
                notes.append(f"{url}: not readable by the agent (sign-in wall); the typed bio is used as self-reported")
                self.tracker.note(f"Skipped {host(url)} — this site cannot be read without signing in; the typed "
                                  "bio is used instead", level="warn", person=name, source=url)
                continue
            self.progress("fetch", name, f"reading {host(url)}")
            self.tracker.begin("fetch", name, "Reading a link", host(url))
            cached = url in self._fetched
            text = self._get(url)
            self.tracker.end("fetch")
            if not self.store(_subject(self.team_id, p["id"]), url, url, "", text, "provided", "provided"):
                notes.append(f"{url}: could not be read")
                self.tracker.note(f"Could not read {host(url)}", level="warn", person=name, source=url)
            else:
                if not cached:
                    self.tracker.count(pages_read=1)
                self.tracker.note(f"Read {host(url)} — {len(text):,} characters saved as evidence", level="found",
                                  person=name, source=url)
        return notes

    def run_searches(self, people: list[dict], company: str, per_person: int, per_team: int) -> None:
        if self.search is None:
            self.deps.audit.record(AGENT, "search_skipped", reason="no search provider configured")
            return
        plan = {p["id"]: person_queries(p, company)[:per_person] for p in people}
        self.planned_searches = min(per_team, sum(len(q) for q in plan.values()))
        order = sorted(people, key=priority)
        for rnd in range(max(per_person, 0)):
            for p in order:
                qs = plan[p["id"]]
                if rnd >= len(qs):
                    continue
                if len(self.searches) >= per_team:
                    self.deps.audit.record(AGENT, "search_budget_exhausted", used=len(self.searches))
                    return
                self._one(p, qs[rnd])

    def _one(self, p: dict, query: str) -> None:
        from ..tools.search import MAX_COUNT, SearchUnavailable

        self.deps.tool(AGENT, "web_search", query=query, kind="person", purpose="public professional profile")
        from ..tools.search import LABELS

        rec: dict = {"person_id": p["id"], "query": query, "provider": None, "results": 0}
        self.searches.append(rec)
        n, total, name = len(self.searches), max(self.planned_searches, len(self.searches)), p.get("full_name")
        self.progress("search", name, f"search {n}: {query}")
        self.tracker.begin("search", name, f"Search {n} of {total}", query)
        self.tracker.count(searches=1)
        try:
            results, provider = self.search.search(query, count=MAX_COUNT)
        except SearchUnavailable as e:
            rec["error"] = str(e)[:300]
            self.deps.audit.record(AGENT, "search_unavailable", query=query, error=str(e)[:300])
            self.tracker.end("search")
            self.tracker.note(f"Search {n}/{total} · {query} — no results from any search service", level="warn",
                              person=name)
            return
        rec.update(provider=provider, results=len(results))
        self.deps.audit.record(AGENT, "search_served", query=query, provider=provider, results=len(results))
        subject = _subject(self.team_id, p["id"])
        read = 0
        for i, r in enumerate(results[:FETCH_PER_QUERY + SNIPPETS_PER_QUERY]):
            url = r.get("url") or ""
            if not url.startswith("https://"):
                continue
            cached = url in self._fetched
            text = self._get(url) if i < FETCH_PER_QUERY else ""
            if text.strip() and not cached:
                read += 1
            kind = "web" if text.strip() else "search_snippet"
            self.store(subject, url, r.get("title") or url, r.get("description", ""),
                       text if text.strip() else r.get("description", ""), query, kind)
        self.tracker.end("search")
        if read:
            self.tracker.count(pages_read=read)
        self.tracker.note(f"Search {n}/{total} · {query} — {_plural(len(results), 'result')}"
                          + (f", read {_plural(read, 'page')}" if read else "")
                          + f" ({LABELS.get(provider, provider)})", level="found" if results else "info", person=name)

    def target_page(self, website: str) -> str:
        """Homepage text of a business given only by its website (SSRF-safe; stored as evidence)."""
        if not website:
            return ""
        text = self._get(website)
        self.store(_subject(self.team_id, "target"), website, website, "", text, "target", "provided")
        return text[:1_500]


# ------------------------------------------------------------------ verification
def verify_facts(p: dict, claims: list[FactClaim], evidence: list, anchors: list[str],
                 provided: set[str]) -> tuple[list[dict], list[dict], int, dict[str, str]]:
    """-> (verified facts, unconfirmed, dropped as sensitive, local id -> global id)."""
    texts: dict[str, list[str]] = {}
    titles: dict[str, str] = {}
    for ev, text in evidence:
        texts.setdefault(ev.url, []).extend([text or "", ev.snippet or ""])
        titles.setdefault(ev.url, ev.title)
    name = p.get("full_name") or ""
    verified, unconfirmed, dropped, ids = [], [], 0, {}
    for c in claims[:40]:
        if is_sensitive(c.text, c.quote):
            dropped += 1
            continue
        page = texts.get(c.source_url)
        why = ""
        if not page:
            why = "source not among the stored pages"
        elif not any(quote_in(c.quote, t) for t in page):
            why = "quote not found on the page"
        elif not any(names_person(t, name) for t in page):
            why = "page does not name the person"
        elif c.source_url not in provided and not any(names_org(t, a) for t in page for a in anchors):
            why = "page does not name the company or a self-reported organisation"
        if why:
            unconfirmed.append({"text": c.text, "quote": c.quote or None, "url": c.source_url or None, "reason": why})
            continue
        gid = f"p{p['id']}f{len(verified) + 1}"
        ids[c.id] = gid
        verified.append({"id": gid, "text": c.text, "quote": c.quote, "url": c.source_url, "category": c.category})
    return verified, unconfirmed, dropped, ids


LOCATION_RE = re.compile(r"^[^\W\d_][^\d,]{0,40}(,\s*[^\W\d_][^\d,]{0,40}){0,2}$")


def founder_text(p: dict) -> str:
    return "\n".join(redact(x) for x in (p.get("headline"), p.get("bio"), (p.get("cv") or "")[:20_000]) if x)


def build_profile(p: dict, draft: CVDraft, ids: dict[str, str], facts: list[dict],
                  unconfirmed: list[dict]) -> tuple[dict, int]:
    """Keep CV items that cite a verified fact or quote the founder's bio / CV verbatim. -> (profile, dropped)."""
    ftext = founder_text(p)
    url_of = {f["id"]: f["url"] for f in facts}
    dropped = 0

    def source(item: Cited, label: str) -> dict | None:
        gids = [ids[i] for i in item.fact_ids if i in ids]
        if gids:
            return {"type": "verified", "fact_ids": gids, "urls": list(dict.fromkeys(url_of[g] for g in gids))}
        if item.cv_quote and quote_in(item.cv_quote, ftext, min_len=4):
            return {"type": "self_reported", "fact_ids": [], "urls": []}
        unconfirmed.append({"text": label, "quote": item.cv_quote or None, "url": None,
                            "reason": "not in a stored source or the provided bio / CV"})
        return None

    def keep(items, label, build, texts):
        nonlocal dropped
        out = []
        for it in items[:25]:
            if is_sensitive(*texts(it)):
                dropped += 1
                continue
            src = source(it, label(it))
            if src:
                out.append({**build(it), "source": src})
        return out

    prof: dict = {"headline": None, "location": None}
    for key in ("headline", "location"):
        it: TextItem | None = getattr(draft, key)
        if it is None or not it.text.strip():
            continue
        if is_sensitive(it.text) or (key == "location" and not LOCATION_RE.match(it.text.strip())):
            dropped += 1
            continue
        src = source(it, f"{key}: {it.text}")
        if src:
            prof[key] = {"text": it.text.strip(), "source": src}
    summary = draft.summary if not is_sensitive(draft.summary) else ""
    dropped += bool(draft.summary and not summary)
    prof["summary"] = summary
    prof["experience"] = keep(
        draft.experience, lambda i: f"{i.title} at {i.org}".strip(),
        lambda i: {"org": i.org, "title": i.title, "start": i.start, "end": i.end,
                   "achievements": [x for x in i.achievements[:8] if not is_sensitive(x)]},
        lambda i: (i.org, i.title))
    prof["education"] = keep(
        draft.education, lambda i: f"{i.degree} {i.institution}".strip(),
        lambda i: {"institution": i.institution, "degree": i.degree, "field": i.field, "start": i.start,
                   "end": i.end}, lambda i: (i.institution, i.degree, i.field))
    prof["skills"] = keep(draft.skills, lambda i: f"skills: {i.group}",
                          lambda i: {"group": i.group, "items": [x for x in i.items[:20] if not is_sensitive(x)]},
                          lambda i: (i.group,))
    prof["ventures"] = keep(draft.ventures, lambda i: f"venture: {i.name}",
                            lambda i: {"name": i.name, "role": i.role, "outcome": i.outcome, "year": i.year},
                            lambda i: (i.name, i.role))
    prof["publications"] = keep(draft.publications, lambda i: f"{i.kind}: {i.title}",
                                lambda i: {"title": i.title, "kind": i.kind, "venue": i.venue, "year": i.year},
                                lambda i: (i.title, i.venue))
    prof["awards"] = keep(draft.awards, lambda i: f"award: {i.title}",
                          lambda i: {"title": i.title, "year": i.year}, lambda i: (i.title,))
    prof["links"] = [{"url": u, "label": host(u)} for u in (p.get("urls") or [])[:6]]
    prof["completeness_pct"] = completeness(prof)
    return prof, dropped


COMPLETENESS = {"experience": 25, "education": 15, "skills": 15, "headline": 10, "summary": 10, "achievements": 10,
                "links": 10, "location": 5}


def completeness(prof: dict) -> int:
    have = {"experience": bool(prof.get("experience")), "education": bool(prof.get("education")),
            "skills": bool(prof.get("skills")), "headline": bool(prof.get("headline")),
            "summary": bool(prof.get("summary")), "links": bool(prof.get("links")),
            "location": bool(prof.get("location")),
            "achievements": bool(prof.get("ventures") or prof.get("publications") or prof.get("awards"))}
    return int(sum(w for k, w in COMPLETENESS.items() if have[k]))


# ------------------------------------------------------------------ scoring (code)
def has_founder_info(p: dict) -> bool:
    return bool((p.get("bio") or "").strip() or (p.get("cv") or "").strip() or (p.get("headline") or "").strip()
                or p.get("full_time") is not None or p.get("equity_pct") is not None or p.get("start_year"))


def sub_score(s: SubScore, ids: dict[str, str], founder_info: bool, weight: float, *,
              allow_self: bool = True) -> dict:
    gids = [ids[i] for i in s.fact_ids if i in ids]
    self_ok = allow_self and s.self_reported and founder_info
    suggested = round(clamp(s.score), 1)
    capped = not gids and not self_ok and suggested > CAP_WITHOUT_EVIDENCE
    score = min(suggested, CAP_WITHOUT_EVIDENCE) if not (gids or self_ok) else suggested
    return {"score": score, "suggested": suggested, "capped": capped, "weight": weight,
            "rationale": s.rationale if not is_sensitive(s.rationale) else "", "fact_ids": gids,
            "self_reported": bool(self_ok and not gids)}


def weighted(parts: dict[str, dict], weights: dict[str, float]) -> float:
    return round(sum(weights[k] * parts[k]["score"] for k in weights) / sum(weights.values()), 1)


def person_quality(scores: PersonScores, ids: dict[str, str], founder_info: bool) -> tuple[float, dict]:
    subs = {k: sub_score(getattr(scores, k), ids, founder_info, w, allow_self=(k != "verifiability"))
            for k, w in PERSON_WEIGHTS.items()}
    return weighted(subs, PERSON_WEIGHTS), subs


REQ_VALUE = {"matched": 1.0, "partial": 0.5, "unverified": 0.25, "missing": 0.0}


def fit_score(fit: FitSuggestion, ids: dict[str, str], founder_info: bool, target_type: str) -> dict:
    comps = {k: sub_score(getattr(fit, k), ids, founder_info, FIT_WEIGHTS[k])
             for k in FIT_WEIGHTS if k != "gaps"}
    reqs = []
    for r in fit.requirements[:30]:
        if is_sensitive(r.requirement, r.note):
            continue
        gids = [ids[i] for i in r.fact_ids if i in ids]
        self_ok = r.self_reported and founder_info
        status = r.status
        if status in ("matched", "partial") and not (gids or self_ok):
            status = "unverified"
        reqs.append({"requirement": r.requirement, "must_have": r.must_have, "status": status, "fact_ids": gids,
                     "self_reported": bool(self_ok and not gids), "note": r.note})
    must = [r for r in reqs if r["must_have"]] or reqs
    if must:
        g = round(100 * sum(REQ_VALUE[r["status"]] for r in must) / len(must), 1)
        why = (f"{sum(r['status'] == 'matched' for r in must)} of {len(must)} key requirements matched with "
               f"evidence; {sum(r['status'] == 'missing' for r in must)} missing")
    else:
        g, why = CAP_WITHOUT_EVIDENCE, "no requirements listed"
    comps["gaps"] = {"score": g, "suggested": g, "capped": False, "weight": FIT_WEIGHTS["gaps"], "rationale": why,
                     "fact_ids": [], "self_reported": False, "computed": True}
    comps = {k: comps[k] for k in FIT_WEIGHTS}
    return {"target_type": target_type,
            "label": "founder–business fit" if target_type == "business" else "role fit",
            "score": weighted(comps, FIT_WEIGHTS), "components": comps, "requirements": reqs,
            "matched": [r["requirement"] for r in reqs if r["status"] in ("matched", "partial")],
            "missing": [r["requirement"] for r in reqs if r["status"] == "missing"],
            "risks": [x for x in fit.risks[:8] if not is_sensitive(x)],
            "interview_questions": [x for x in fit.interview_questions[:8] if not is_sensitive(x)]}


def contribution(quality: float, fit: dict | None) -> float:
    if not fit:
        return round(quality, 1)
    return round(QUALITY_FIT_SPLIT * quality + (1 - QUALITY_FIT_SPLIT) * fit["score"], 1)


def functions_of(card: dict) -> set[str]:
    out = set(card.get("functions") or [])
    role = card.get("role") or ""
    if _TECH.search(role):
        out.add("tech")
    if _COMMERCIAL.search(role) or is_ceo(card):
        out.add("commercial")
    if _FINANCE.search(role):
        out.add("finance")
    return out & set(FUNCTIONS)


def team_components(cards: list[dict], people: dict[int, dict], worked: dict | None) -> dict[str, dict]:
    """Team-level components 0..100 (code; worked_together from the model with the evidence cap)."""
    core = [c for c in cards if c["kind"] != "advisor"]
    leaders = [c for c in core if c["kind"] != "employee"]
    advisors = [c for c in cards if c["kind"] == "advisor"]
    cov = {f: any(f in functions_of(c) for c in core) for f in FUNCTIONS}
    comp = {"complementarity": {"score": 25.0 * sum(cov.values()), "computed": True, "fact_ids": [],
                                "rationale": "covered: " + (", ".join(f for f, v in cov.items() if v) or "none")}}
    ceo = any(is_ceo(c) or c["kind"] == "founder" for c in core)
    tech = any(_TECH.search(c["role"] or "") or "tech" in functions_of(c) for c in core)
    # commercial / finance lead: a non-CEO with that role or function, or a CEO the model found commercial
    comm = any((not is_ceo(c) and (_COMMERCIAL.search(c["role"] or "") or _FINANCE.search(c["role"] or "")
                                   or functions_of(c) & {"commercial", "finance"}))
               or (is_ceo(c) and set(c.get("functions") or []) & {"commercial", "finance"}) for c in core)
    comp["key_roles"] = {"score": 40.0 * ceo + 30.0 * tech + 30.0 * bool(comm), "computed": True, "fact_ids": [],
                         "rationale": f"CEO / lead founder {'yes' if ceo else 'no'}, technical lead "
                                      f"{'yes' if tech else 'no'}, commercial / finance lead {'yes' if comm else 'no'}"}
    if len(core) < 2:
        comp["worked_together"] = {"score": CAP_WITHOUT_EVIDENCE, "computed": True, "fact_ids": [],
                                   "rationale": "single-person team"}
    else:
        w = worked or {"score": 0.0, "rationale": "not assessed", "fact_ids": []}
        s = clamp(w["score"])
        if not w.get("fact_ids"):
            s = min(s, CAP_WITHOUT_EVIDENCE)
        comp["worked_together"] = {"score": round(s, 1), "computed": False, "fact_ids": w.get("fact_ids") or [],
                                   "rationale": w.get("rationale", "")}
    a = len(advisors)
    adv = {0: 30.0, 1: 60.0}.get(a, 80.0) + (20.0 if any(c["score"] >= 70 for c in advisors) else 0.0)
    comp["advisors_board"] = {"score": min(adv, 100.0), "computed": True, "fact_ids": [],
                              "rationale": f"{a} advisor(s)"}
    n = len(leaders)
    conc = {0: 0.0, 1: 30.0, 2: 70.0}.get(n, 90.0)
    notes = [f"{n} founder / executive(s)"]
    if any((people.get(c["person_id"]) or {}).get("equity_pct") and
           float(people[c["person_id"]]["equity_pct"]) >= 75 for c in leaders):
        conc -= 20
        notes.append("one person holds >= 75% equity")
    if any(is_ceo(c) and (people.get(c["person_id"]) or {}).get("full_time") is False for c in leaders):
        conc -= 10
        notes.append("CEO is not full-time")
    comp["concentration"] = {"score": clamp(conc), "computed": True, "fact_ids": [], "rationale": "; ".join(notes)}
    return {k: comp[k] for k in TEAM_WEIGHTS}


def team_score(cards: list[dict], people: dict[int, dict], worked: dict | None,
               red_flags: list[dict]) -> dict:
    if not cards:
        return {"score": 0.0, "grade": "E", "people_component": 0.0, "team_component": 0.0, "red_flag_penalty": 0.0,
                "components": {}, "component_detail": {}, "coverage": {f: False for f in FUNCTIONS}}
    total_m = sum(c["multiplier"] for c in cards)
    people_c = round(sum(c["multiplier"] * c["contribution"] for c in cards) / total_m, 1)
    comps = team_components(cards, people, worked)
    team_c = round(sum(TEAM_WEIGHTS[k] * comps[k]["score"] for k in TEAM_WEIGHTS), 1)
    penalty = min(RED_FLAG_POINTS * len(red_flags), RED_FLAG_MAX)
    score = round(clamp(PEOPLE_SHARE * people_c + TEAM_SHARE * team_c - penalty), 1)
    core = [c for c in cards if c["kind"] != "advisor"]
    return {"score": score, "grade": grade(score), "people_component": people_c, "team_component": team_c,
            "red_flag_penalty": penalty, "components": {k: v["score"] for k, v in comps.items()},
            "component_detail": comps,
            "coverage": {f: any(f in functions_of(c) for c in core) for f in FUNCTIONS}}


def recompute_team(result: dict, people: dict[int, dict]) -> dict:
    """Team block from the stored cards + team inputs (after a person was removed). Deterministic."""
    cards = result.get("people") or []
    known = {f["id"] for c in cards for f in c.get("facts") or []}
    inputs = result.get("team_inputs") or {}
    worked = inputs.get("worked_together")
    if worked:
        worked = {**worked, "fact_ids": [i for i in worked.get("fact_ids") or [] if i in known]}
    flags = [f for f in inputs.get("red_flags") or [] if any(i in known for i in f.get("fact_ids") or [])]
    block = team_score(cards, people, worked, flags)
    old = result.get("team") or {}
    return {**old, **block, "red_flags": flags}


# ------------------------------------------------------------------ the job
def _listing(evidence: list, name: str) -> str:
    return "\n\n".join(
        f"[{i}] {ev.title}{' (search snippet only)' if ev.kind == 'search_snippet' else ''}\nURL: {ev.url}\n"
        + (f"Search snippet: {ev.snippet}\n" if ev.snippet and ev.kind == "web" else "")
        + excerpts(text or "", name)
        for i, (ev, text) in enumerate(evidence[:MAX_PAGES_IN_PROMPT], 1))


def _target_block(target: dict | None) -> str:
    if not target:
        return "TARGET: none (no fit assessment; set fit to null)"
    if target.get("type") == "role":
        reqs = "\n".join(f"- {r}" for r in (target.get("requirements") or [])[:30])
        return (f"TARGET (role): {target.get('title', '')} at {target.get('company', '')}\n"
                f"Description: {(target.get('description') or '')[:5000]}\nRequirements:\n{reqs}")
    return (f"TARGET (business — founder–business fit): {target.get('company') or ''}\n"
            f"Website: {target.get('website') or ''}\nSector: {target.get('sector') or 'unknown'}; stage: "
            f"{target.get('stage') or 'unknown'}; country: {target.get('country') or ''}\n"
            f"Product / business: {(target.get('description') or '')[:1500]}\n"
            f"Market: {(target.get('market') or '')[:800]}")


def _person_prompt(p: dict, target: dict | None, evidence: list, notes: list[str]) -> str:
    cv = redact((p.get("cv") or "")[:CV_CHARS])
    return (
        f"PERSON: {p['full_name']} — role: {p.get('role') or 'unknown'} ({p.get('kind')})\n{_target_block(target)}\n\n"
        f"<data>\nFOUNDER-PROVIDED (self-reported, not verified):\nheadline: {redact(p.get('headline') or '')}\n"
        f"bio: {redact(p.get('bio') or '')}\nfull_time: {p.get('full_time')}; equity_pct: {p.get('equity_pct')}; "
        f"start_year: {p.get('start_year')}\nCV:\n{cv}\n"
        + (f"notes: {'; '.join(notes)}\n" if notes else "")
        + f"\nEVIDENCE PAGES:\n{_listing(evidence, p['full_name']) or '(none)'}\n</data>")


def _anchors(team: dict, target: dict | None, p: dict, draft: CVDraft) -> list[str]:
    """Organisations a page may name to count as about this person: the business, plus organisations the person
    self-reported (appear verbatim in the founder-provided text)."""
    out = [x for x in (team.get("name"), (target or {}).get("company") if (target or {}).get("type") == "business"
                       else None) if x]
    web = team.get("website") or (target or {}).get("website")
    if web:
        out.append(host(web).split(".")[0])
    ftext = founder_text(p)
    for it in [*draft.experience, *draft.ventures]:
        org = getattr(it, "org", None) or getattr(it, "name", "")
        if org and len(org_key(org)) >= 3 and names_org(ftext, org):
            out.append(org)
    return list(dict.fromkeys(out))


def _readable(url: str) -> bool:
    return bool(re.match(r"^https?://", url or "")) and not any(
        host(url) == h or host(url).endswith("." + h) for h in UNREADABLE_HOSTS)


def analyse(team: dict, people: list[dict], deps: Deps, *, target: dict | None = None,
            progress: Progress | None = None, tracker: Tracker | None = None) -> dict:
    """Run the People Analyst for one report. `team`: {id, mode, name, website}; `people`: hr_people rows (id,
    full_name, role, kind, headline, full_time, start_year, equity_pct, urls, bio, cv, position);
    `target`: resolved target context (see studio/hr.py) or None; `tracker`: live progress (see Tracker).
    Returns the Report dict (see studio/hr.py)."""
    tr = tracker or NULL_TRACKER
    current: dict = {"person": None}
    token = set_listener(lambda ev: tr.llm_event(ev, current["person"]))
    try:
        return _analyse(team, people, deps, target, progress or (lambda step, person, msg: None), tr, current)
    finally:
        reset_listener(token)


def _analyse(team: dict, people: list[dict], deps: Deps, target: dict | None, prog: Progress, tr: Tracker,
             current: dict) -> dict:
    s = deps.settings
    tid, mode = team["id"], team.get("mode") or "team"
    if mode == "team" and target is None:
        target = {"type": "business", "company": team.get("name"), "website": team.get("website")}
    rs = Research(deps, tid, prog, tr)
    company = ((target or {}).get("company") if (target or {}).get("type") == "business" else "") or (
        team.get("name") or "" if mode == "team" else "")
    company = " ".join(_SUFFIX.sub(" ", company).replace(",", " ").split())
    per_person = s.hr_searches_per_person
    per_team = s.hr_searches_per_team if mode == "team" else s.hr_searches_per_person
    planned = 0 if rs.search is None else min(per_team, sum(len(person_queries(p, company)[:per_person])
                                                            for p in people))
    fetches = len({u for p in people for u in (p.get("urls") or [])[:6] if _readable(u)})
    tr.plan(people, fetches=fetches, searches=planned, team=mode == "team")
    tr.phase("reading")
    tr.note(f"Starting the review of {_plural(len(people), 'person', 'people')}"
            + (f" — {_plural(fetches, 'link')} to read" if fetches else "")
            + (f", up to {_plural(planned, 'web search', 'web searches')}" if planned else ""))
    notes_by: dict[int, list[str]] = {}
    for p in people:
        current["person"] = p["full_name"]
        notes_by[p["id"]] = rs.provided(p)
    tr.phase("searching")
    rs.run_searches(people, company, per_person, per_team)
    if rs.search is None:
        tr.note("No web search service is configured; only the links provided are used", level="warn")

    counters = {"searches": len(rs.searches), "search_budget": s.hr_searches_per_team if mode == "team"
                else s.hr_searches_per_person, "pages_fetched": rs.pages_fetched, "facts_verified": 0,
                "facts_unconfirmed": 0, "facts_dropped_sensitive": 0, "llm_calls": 0}
    models: dict[str, str] = {}
    cards, sources, seen_src = [], [], {}
    # pages any team member's research stored; a page stored for someone else (e.g. the company's team page a
    # co-founder provided) is also evidence for every person it names
    stored = {p["id"]: deps.evidence.for_subject(_subject(tid, p["id"]), limit=60) for p in people}
    check_evidence(people, stored, rs.searches, rs.pages_fetched)
    provided = {ev.url for evs in stored.values() for ev, _ in evs if ev.kind == "provided"}
    for p in sorted(people, key=lambda x: int(x.get("position") or 0)):
        evidence = list(stored[p["id"]])
        own = {ev.url for ev, _ in evidence}
        for pid, evs in stored.items():
            for ev, text in evs:
                if pid != p["id"] and ev.url not in own and names_person(f"{ev.snippet} {text}", p["full_name"]):
                    evidence.append((ev, text))
                    own.add(ev.url)
        evidence.sort(key=lambda e: (e[0].kind != "provided", e[0].kind == "search_snippet"))
        prog("extract", p["full_name"], f"analysing {len(evidence)} source(s)")
        current["person"] = p["full_name"]
        tr.phase("extracting")
        tr.person(p["id"], "working")
        n_pages = min(len(evidence), MAX_PAGES_IN_PROMPT)
        first = provider_label(primary_provider(deps.agent_llm.get(AGENT, deps.llm), s.hr_tier))
        tr.begin("person_model", p["full_name"], "Reading the sources", _plural(n_pages, "page"))
        tr.note(f"{first} is reading {_plural(n_pages, 'page')} about {p['full_name']}", person=p["full_name"])
        t0 = time.monotonic()
        a = deps.ask(AGENT, s.hr_tier, SYSTEM_PERSON, _person_prompt(p, target, evidence, notes_by[p["id"]]),
                     PersonAnalysis)
        tr.end("person_model")
        counters["llm_calls"] += 1
        models[f"person:{p['id']}"] = last_provider() or "unknown"
        tr.note(f"{provider_label(models['person:' + str(p['id'])])} answered in "
                f"{time.monotonic() - t0:.0f} s", person=p["full_name"])
        deps.audit.record(AGENT, "person_analysed", team=tid, person=p["id"], model=models[f"person:{p['id']}"])
        anchors = _anchors(team, target, p, a.profile)
        facts, unconfirmed, dropped, ids = verify_facts(p, a.facts, evidence, anchors, provided)
        profile, dropped_cv = build_profile(p, a.profile, ids, facts, unconfirmed)
        for f in facts:
            key = f["url"]
            if key not in seen_src:
                ev = next(ev for ev, _ in evidence if ev.url == key)
                seen_src[key] = f"s{len(sources) + 1}"
                sources.append({"id": seen_src[key], "url": ev.url, "title": ev.title, "sha256": ev.content_sha256,
                                "kind": {"search_snippet": "snippet", "web": "page"}.get(ev.kind, ev.kind),
                                "fetched_at": datetime.fromtimestamp(ev.retrieved_at, UTC).isoformat(),
                                "person_id": p["id"]})
            f["source_id"] = seen_src[key]
        info = has_founder_info(p)
        quality, subs = person_quality(a.scores, ids, info)
        fit = fit_score(a.fit, ids, info, target["type"]) if (a.fit and target) else None
        card = {"person_id": p["id"], "full_name": p["full_name"], "role": p.get("role") or "",
                "kind": p.get("kind") or "employee", "multiplier": multiplier(p), "score": quality,
                "subscores": subs, "fit": fit, "contribution": contribution(quality, fit), "profile": profile,
                "facts": facts,
                "self_reported": {"headline": redact(p.get("headline") or "") or None,
                                  "bio": redact(p.get("bio") or "") or None, "full_time": p.get("full_time"),
                                  "equity_pct": p.get("equity_pct"), "start_year": p.get("start_year"),
                                  "has_cv": bool((p.get("cv") or "").strip())},
                "unconfirmed": unconfirmed[:40],
                "strengths": [x for x in a.strengths[:8] if not is_sensitive(x)],
                "gaps": [x for x in a.gaps[:8] if not is_sensitive(x)],
                "questions": [x for x in a.questions[:8] if not is_sensitive(x)],
                "functions": sorted(set(a.functions) & set(FUNCTIONS)), "model": models[f"person:{p['id']}"],
                "notes": notes_by[p["id"]]}
        cards.append(card)
        counters["facts_verified"] += len(facts)
        counters["facts_unconfirmed"] += len(unconfirmed)
        counters["facts_dropped_sensitive"] += dropped + dropped_cv
        tr.count(facts_verified=len(facts), facts_unconfirmed=len(unconfirmed))
        tr.note(f"Checked the facts about {p['full_name']}: {_plural(len(facts), 'verified fact')}, "
                f"{len(unconfirmed)} unconfirmed" + (f", {dropped + dropped_cv} private item(s) removed"
                                                     if dropped + dropped_cv else ""),
                level="found" if facts else "info", person=p["full_name"])
        tr.phase("scoring")
        prog("score", p["full_name"], f"quality {quality}" + (f", fit {fit['score']}" if fit else "")
             + f" · {len(facts)} verified fact(s)")
        tr.note(f"Scored {p['full_name']}: " + (f"{fit_word(fit['score'])} {fit['score']:.0f} · " if fit else "")
                + f"quality {quality:.0f}", level="found", person=p["full_name"])
        tr.person(p["id"], "done", facts=facts, score=quality, fit=fit["score"] if fit else None)
        tr.count(people_done=1)

    team_block, team_inputs = None, None
    if mode == "team":
        known = {f["id"] for c in cards for f in c["facts"]}
        ta = None
        if len(cards) >= 1:
            prog("team", None, "team-level review")
            current["person"] = None
            tr.phase("scoring")
            tr.begin("team_model", None, "Team review", "How the people work together")
            tr.note(f"{provider_label(primary_provider(deps.agent_llm.get(AGENT, deps.llm), s.hr_tier))} is "
                    f"reviewing the team as a whole")
            summary = "\n\n".join(
                f"PERSON {c['full_name']} — {c['role']} ({c['kind']}); functions: {', '.join(c['functions'])}; "
                f"quality {c['score']}\n" + "\n".join(f"  [{f['id']}] {f['text']}" for f in c["facts"][:20])
                for c in cards)
            ta = deps.ask(AGENT, s.hr_tier, SYSTEM_TEAM,
                          f"Business: {team.get('name')} ({team.get('website') or ''})\n\n<data>\n{summary}\n</data>",
                          TeamAnalysis)
            tr.end("team_model")
            counters["llm_calls"] += 1
            models["team"] = last_provider() or "unknown"
            deps.audit.record(AGENT, "team_analysed", team=tid, model=models["team"])
        worked = None
        flags: list[dict] = []
        if ta is not None:
            worked = {"score": ta.worked_together.score, "rationale": ta.worked_together.rationale,
                      "fact_ids": [i for i in ta.worked_together.fact_ids if i in known]}
            for f in ta.red_flags[:10]:
                fids = [i for i in f.fact_ids if i in known]
                if fids and not is_sensitive(f.text):
                    flags.append({"text": f.text, "fact_ids": fids})
        team_inputs = {"worked_together": worked, "red_flags": flags}
        people_by = {p["id"]: p for p in people}
        team_block = {**team_score(cards, people_by, worked, flags), "red_flags": flags,
                      "strengths": [x for x in (ta.strengths if ta else [])[:8] if not is_sensitive(x)],
                      "gaps": [x for x in (ta.gaps if ta else [])[:8] if not is_sensitive(x)],
                      "risks": [x for x in (ta.risks if ta else [])[:8] if not is_sensitive(x)],
                      "questions": [x for x in (ta.questions if ta else [])[:8] if not is_sensitive(x)]}

    if team_block:
        tr.note(f"Scored the team: {team_block['score']:.0f} (grade {team_block['grade']})", level="found")
    prog("done", None, (f"team score {team_block['score']} ({team_block['grade']})" if team_block else
                        f"{len(cards)} person report(s)"))
    return {
        "version": VERSION, "mode": mode, "team": team_block, "team_inputs": team_inputs, "people": cards,
        "target": target,
        "method": {"person_weights": PERSON_WEIGHTS, "fit_weights": FIT_WEIGHTS, "team_weights": TEAM_WEIGHTS,
                   "role_multipliers": ROLE_MULTIPLIERS,
                   "team_formula": f"{PEOPLE_SHARE} x role-weighted mean of contributions + {TEAM_SHARE} x team "
                                   f"component - {RED_FLAG_POINTS:g} per verified red flag (max {RED_FLAG_MAX:g})",
                   "contribution": f"{QUALITY_FIT_SPLIT} x quality + {1 - QUALITY_FIT_SPLIT} x fit "
                                   "(quality alone when there is no fit)",
                   "cap_without_evidence": CAP_WITHOUT_EVIDENCE,
                   "notes": ["The model only suggests sub-scores with cited facts; code computes every score.",
                             "A fact is verified only when its quote is on a stored page that names the person and "
                             "the company (or a self-reported organisation), or on a URL the founder provided.",
                             "Self-reported information (bio, CV, commitment) is labelled and never verifies itself.",
                             "Public professional information only; sensitive categories are filtered out.",
                             "Advisory only - not an employment, credit or investment decision."],
                   "models": models, "search_providers": list(deps.search_for(AGENT).names)
                   if deps.search_for(AGENT) is not None else []},
        "sources": sources, "counters": counters, "searches": rs.searches,
        "created_at": datetime.now(UTC).isoformat(),
    }
