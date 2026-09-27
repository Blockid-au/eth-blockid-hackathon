"""Detailed review of an uploaded / pasted CV (self-reported), run while the web research is still going.

Three parts land one after another on the live screen (Tracker.cv):
  read       - instant, code only: words, sections found, years covered, links, private details removed
  timeline   - model reads the roles / education; code computes tenure, total years, gaps and overlaps
  insights   - model: skills with level, measurable results, leadership, strengths, concerns, claims to check
The two model calls run in parallel. After the facts are verified, `finish` marks each CV claim confirmed when a
verified public fact names its organisation. Everything here is self-reported and never verifies itself.
"""
from __future__ import annotations

import contextvars
import logging
import re
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

CV_REVIEW_CHARS = 30_000
GAP_MONTHS = 6  # a break between roles at least this long is shown as a gap

_SECTIONS = {
    "summary": r"summary|profile|about me|objective|tóm tắt|giới thiệu|mục tiêu",
    "experience": r"(?:work |professional |employment )?experience|employment|career history|work history|kinh nghiệm",
    "education": r"education|academic|qualifications|học vấn|đào tạo",
    "skills": r"(?:technical |core |key )?skills|competencies|technologies|tech stack|kỹ năng",
    "projects": r"projects|portfolio|dự án",
    "certifications": r"certifications?|licen[cs]es|chứng chỉ",
    "publications": r"publications|papers|patents|research|công bố|nghiên cứu",
    "awards": r"awards|honou?rs|achievements|giải thưởng|thành tích",
    "languages": r"languages|ngôn ngữ|ngoại ngữ",
}
_HEAD = {k: re.compile(rf"^\s*(?:[#*•\-\d.]+\s*)?(?:{v})\s*:?\s*$", re.I | re.M) for k, v in _SECTIONS.items()}
_YEAR = re.compile(r"\b(19[6-9]\d|20[0-4]\d)\b")
_URL = re.compile(r"(?:https?://|www\.)[^\s<>()\"']+|\b(?:linkedin\.com/in|github\.com)/[\w\-./]+", re.I)


# ------------------------------------------------------------------ model schemas (suggestions only)
class CVRole(BaseModel):
    org: str = Field(max_length=200)
    title: str = Field(default="", max_length=200)
    start: str = Field(default="", description="YYYY or YYYY-MM")
    end: str = Field(default="", description="YYYY, YYYY-MM, 'present' or empty")
    location: str = Field(default="", max_length=120, description="city / country only")
    kind: Literal["employee", "founder", "advisor", "board", "freelance", "intern", "other"] = "employee"
    team_size: int | None = Field(default=None, ge=0, le=1_000_000, description="people managed, if stated")
    highlights: list[str] = Field(default=[], description="<= 4 short results or duties, from the CV")


class CVEducation(BaseModel):
    institution: str = Field(max_length=200)
    degree: str = ""
    field: str = ""
    start: str = ""
    end: str = ""


class CVStructure(BaseModel):
    headline: str = Field(default="", max_length=200)
    location: str = Field(default="", max_length=120)
    roles: list[CVRole] = []
    education: list[CVEducation] = []
    certifications: list[str] = []
    languages: list[str] = []


class CVSkill(BaseModel):
    name: str = Field(max_length=80)
    level: Literal["expert", "strong", "working"] = "working"
    years: float | None = Field(default=None, ge=0, le=60)
    evidence: str = Field(default="", max_length=240, description="short exact excerpt of the CV")


class CVAchievement(BaseModel):
    text: str = Field(max_length=300)
    metric: str = Field(default="", max_length=80, description="the number, e.g. '40% lower cost', '2M users'")
    org: str = Field(default="", max_length=200)


class CVClaim(BaseModel):
    text: str = Field(max_length=300)
    org: str = Field(default="", max_length=200)
    kind: Literal["role", "education", "achievement", "venture", "other"] = "other"


class CVInsights(BaseModel):
    summary: str = Field(default="", max_length=700)
    seniority: Literal["entry", "mid", "senior", "lead", "executive"] = "mid"
    skills: list[CVSkill] = []
    achievements: list[CVAchievement] = []
    leadership: list[str] = []
    strengths: list[str] = []
    concerns: list[str] = []
    claims: list[CVClaim] = []
    questions: list[str] = []


SYSTEM_STRUCTURE = """You read ONE person's CV (self-reported) and return its structure. Rules:
- roles: every job, venture, board or advisory role, newest first; org and title as written; start / end as YYYY or
  YYYY-MM ('present' when current, empty when unknown); kind; team_size only when the CV states people managed;
  highlights: up to 4 short results or duties from that role, in the CV's words (no invention).
- education, certifications, languages (spoken languages) as written. headline: the person's current title in a
  few words. location: city and country only.
- NEVER output health, religion, politics, family, home address, phone, email, age / date of birth, ethnicity or
  sexual orientation. Keep the CV's language for names; write everything else in English."""

SYSTEM_INSIGHTS = """You are a senior recruiter reviewing ONE person's CV (self-reported). Be specific and fair.
- summary: 2-3 plain sentences on who this person is professionally.
- seniority: entry / mid / senior / lead / executive, from scope and titles.
- skills: up to 16, the most important first; level expert / strong / working judged from years and depth shown;
  years when the CV makes it clear; evidence: a short exact excerpt of the CV.
- achievements: up to 8 results with a number (revenue, users, cost, speed, team size, funding); metric = the
  number in a few words; org where it happened. Only what the CV states.
- leadership: up to 5 signals (teams led, budgets, hiring, mentoring). strengths: up to 6.
- concerns: up to 6 things a reviewer should check — vague claims with no result, unexplained breaks, very short
  stints, title jumps, dates that do not add up, buzzwords without evidence. Neutral wording, no speculation.
- claims: up to 8 checkable claims (roles at named organisations, degrees, funding, awards) with org.
- questions: up to 6 interview questions that test the CV's key claims.
- If a TARGET is given, weigh relevance to it. NEVER output health, religion, politics, family, address, contact
  details, age, ethnicity or sexuality."""


# ------------------------------------------------------------------ code-only parts
def read_stats(cv: str) -> dict:
    """Instant facts about the text itself (shown before any model answers)."""
    text = cv or ""
    words = len(re.findall(r"\w+", text))
    sections = [k for k, rx in _HEAD.items() if rx.search(text)]
    years = sorted({int(y) for y in _YEAR.findall(text) if int(y) <= datetime.now(UTC).year})
    links = []
    for m in _URL.findall(text):
        u = m.rstrip(".,;")
        if u not in links:
            links.append(u)
    return {"words": words, "chars": len(text), "sections": sections,
            "years": [years[0], years[-1]] if years else None, "links": links[:10],
            "redacted": text.count("[email]") + text.count("[phone]")}


def _month(s: str, *, end: bool = False) -> int | None:
    """'2019', '2019-03', '03/2019', 'Mar 2019', 'present' -> months since year 0 (None when unknown)."""
    s = (s or "").strip().lower()
    if not s:
        return None
    if s in ("present", "current", "now", "nay", "hiện tại", "hien tai", "today"):
        d = datetime.now(UTC)
        return d.year * 12 + d.month - 1
    y = _YEAR.search(s)
    if not y:
        return None
    mo = re.search(r"(?:^|[-/.\s])(0?[1-9]|1[0-2])(?:$|[-/.\s])", s.replace(y.group(0), " "))
    names = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    nm = next((i + 1 for i, n in enumerate(names) if n in s), None)
    m = int(mo.group(1)) if mo else nm or (12 if end else 1)
    return int(y.group(0)) * 12 + m - 1


def _precise(s: str) -> bool:
    s = (s or "").strip().lower()
    return s in ("present", "current", "now", "nay", "hiện tại", "today") or bool(
        re.search(r"\b(?:19|20)\d\d[-/.]\d{1,2}\b|\b\d{1,2}[-/.](?:19|20)\d\d\b|[a-z]{3,}\.? ?(?:19|20)\d\d", s))


def _label(m: int) -> str:
    return f"{m // 12}-{m % 12 + 1:02d}"


def timeline(roles: list[dict]) -> dict:
    """Tenure per role, total years (overlaps counted once), gaps >= GAP_MONTHS and concurrent main roles."""
    spans = []
    for i, r in enumerate(roles):
        a, z = _month(r.get("start", "")), _month(r.get("end", ""), end=True)
        if a is None:
            continue
        if z is None:
            z = a  # unknown end: at least the start month
        if z < a:
            a, z = z, a
        spans.append((a, z, i))
        r["months"] = z - a + 1
    spans.sort()
    total, merged = 0, []
    for a, z, _ in spans:
        if merged and a <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], z)
        else:
            merged.append([a, z])
    total = sum(z - a + 1 for a, z in merged)
    gaps = [{"from": _label(merged[k][1] + 1), "to": _label(merged[k + 1][0] - 1),
             "months": merged[k + 1][0] - merged[k][1] - 1}
            for k in range(len(merged) - 1) if merged[k + 1][0] - merged[k][1] - 1 >= GAP_MONTHS]
    main = [(a, z, i) for a, z, i in spans if roles[i].get("kind") in ("employee", "founder", "freelance")]
    exact = [(a, z, i) for a, z, i in main if _precise(roles[i].get("start", "")) and _precise(roles[i].get("end", ""))]
    overlaps = 0  # only month-precise dates: a year-only end ("2013") reads as December and flags a normal move
    for k in range(1, len(exact)):
        if any(exact[k][0] < exact[j][1] - 2 for j in range(k)):  # > 3 months of two main jobs at once
            overlaps += 1
    tenures = [roles[i]["months"] for _, _, i in main if roles[i].get("months")]
    now = _month("present") or 0
    return {"years": round(total / 12, 1), "roles": len(roles), "avg_tenure_months": round(sum(tenures) /
            len(tenures)) if tenures else None, "longest_months": max(tenures) if tenures else None,
            "gaps": gaps[:6], "overlaps": overlaps,
            "first": _label(spans[0][0]) if spans else None,
            "current": next((roles[i].get("org") for a, z, i in reversed(spans) if z >= now - 1), None),
            "short_stints": sum(1 for x in tenures if x < 12)}


# ------------------------------------------------------------------ run
class CVReview:
    """Starts the two model calls in the background; `result()` waits for them (bounded) and returns the review."""

    def __init__(self, deps, agent: str, tier: str, person: dict, target_block: str, tracker, *,
                 sensitive, redact, pool: ThreadPoolExecutor):
        self.p, self.tr, self.sensitive = person, tracker, sensitive
        self.pid, self.name = person["id"], person["full_name"]
        cv = redact((person.get("cv") or "")[:CV_REVIEW_CHARS])
        self.review: dict = {"read": read_stats(cv), "timeline": None, "insights": None, "claims": [],
                             "models": {}}
        tracker.cv(self.pid, "read", self.review["read"])
        st = self.review["read"]
        yrs = st["years"]
        tracker.note(f"CV read: {st['words']:,} words" + (f" · {len(st['sections'])} sections" if st["sections"]
                     else "") + (f" · covers {yrs[0]}–{yrs[1]}" if yrs else ""), level="found", person=self.name)
        user = f"PERSON: {self.name} — {person.get('role') or ''}\n{target_block}\n<cv>\n{cv}\n</cv>"
        self.f_struct: Future = pool.submit(contextvars.copy_context().run, self._call, deps, agent, tier,
                                            SYSTEM_STRUCTURE, user, CVStructure, "timeline")
        self.f_ins: Future = pool.submit(contextvars.copy_context().run, self._call, deps, agent, tier,
                                         SYSTEM_INSIGHTS, user, CVInsights, "insights")

    def _call(self, deps, agent, tier, system, user, schema, part):
        from ..llm import last_provider

        try:
            out = deps.ask(agent, tier, system, user, schema)
        except Exception as e:  # noqa: BLE001 - a CV review failure never fails the report
            log.warning("cv review %s failed for %s: %s", part, self.name, e)
            self.tr.note(f"CV {part} could not be prepared ({type(e).__name__}); the report continues",
                         level="warn", person=self.name)
            return None
        self.review["models"][part] = last_provider() or "unknown"
        data = self._timeline(out) if part == "timeline" else self._insights(out)
        self.review[part] = data
        self.tr.cv(self.pid, part, data)
        if part == "timeline":
            t = data["stats"]
            self.tr.note(f"Career timeline ready: {t['roles']} role(s), about {t['years']:g} years"
                         + (f", breaks of {GAP_MONTHS}+ months: {len(t['gaps'])}" if t["gaps"] else ", no long breaks"),
                         level="found", person=self.name)
        else:
            self.tr.note(f"CV insights ready: {len(data['skills'])} skills, {len(data['achievements'])} measurable "
                         f"result(s), {len(data['claims'])} claim(s) to check", level="found", person=self.name)
        return data

    def _clean(self, xs: list[str], n: int) -> list[str]:
        return [x.strip()[:300] for x in xs if x and x.strip() and not self.sensitive(x)][:n]

    def _timeline(self, s: CVStructure) -> dict:
        roles = [r.model_dump() for r in s.roles[:25] if not self.sensitive(r.org, r.title)]
        for r in roles:
            r["highlights"] = self._clean(r["highlights"], 4)
        return {"headline": "" if self.sensitive(s.headline) else s.headline,
                "location": "" if self.sensitive(s.location) else s.location, "roles": roles,
                "education": [e.model_dump() for e in s.education[:8] if not self.sensitive(e.institution)],
                "certifications": self._clean(s.certifications, 10), "languages": self._clean(s.languages, 8),
                "stats": timeline(roles)}

    def _insights(self, s: CVInsights) -> dict:
        return {"summary": "" if self.sensitive(s.summary) else s.summary, "seniority": s.seniority,
                "skills": [k.model_dump() for k in s.skills[:16] if not self.sensitive(k.name, k.evidence)],
                "achievements": [a.model_dump() for a in s.achievements[:8] if not self.sensitive(a.text)],
                "leadership": self._clean(s.leadership, 5), "strengths": self._clean(s.strengths, 6),
                "concerns": self._clean(s.concerns, 6), "questions": self._clean(s.questions, 6),
                "claims": [c.model_dump() for c in s.claims[:8] if not self.sensitive(c.text)]}

    def result(self, timeout: float = 200.0) -> dict:
        for f in (self.f_struct, self.f_ins):
            try:
                f.result(timeout=timeout)
            except Exception:  # noqa: BLE001 - timeout: keep what arrived
                log.warning("cv review for %s did not finish in time", self.name)
        return self.review

    def prompt_block(self) -> str:
        """Compact structured CV for the person model (self-reported)."""
        tl = self.review.get("timeline")
        if not tl:
            return ""
        lines = [f"- {r['title']} @ {r['org']} ({r['start'] or '?'}–{r['end'] or '?'})" for r in tl["roles"][:12]]
        st = tl["stats"]
        return ("CV TIMELINE (self-reported, structured):\n" + "\n".join(lines)
                + f"\n~{st['years']:g} years; gaps: {', '.join(g['from'] + '..' + g['to'] for g in st['gaps']) or 'none'}\n")

    def finish(self, facts: list[dict], names_org) -> dict:
        """Mark each CV claim confirmed when a verified public fact names its organisation."""
        claims = []
        for c in (self.review.get("insights") or {}).get("claims", []):
            org = (c.get("org") or "").strip()
            hit = [f["id"] for f in facts if org and names_org(f"{f.get('text', '')} {f.get('quote', '')}", org)]
            claims.append({**c, "status": "confirmed" if hit else "unconfirmed", "fact_ids": hit[:4]})
        self.review["claims"] = claims
        if claims:
            n = sum(1 for c in claims if c["status"] == "confirmed")
            self.tr.cv(self.pid, "claims", claims)
            self.tr.note(f"{n} of {len(claims)} CV claim(s) confirmed by public sources", person=self.name,
                         level="found" if n else "info")
        return self.review
