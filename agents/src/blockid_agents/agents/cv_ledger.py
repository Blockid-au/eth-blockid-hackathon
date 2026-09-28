"""CV claim ledger: every checkable CV claim compared, dimension by dimension, with the verified public facts
(docs/PLAN-HR-V3.md §1). All decisions here are CODE; the model only maps claims to fact ids and proposes a conflict
quote, which code re-checks on the stored page.

  claims_from_review(review, cv)        -> claims c1.. (roles, ventures, education, certifications, results, awards)
  claim_queries(name, claims, ...)      -> claim-led web searches ('"<name>" "<org>" <title>')
  build_ledger(...)                     -> per-claim status + dimensions + sources, counts, namesakes, lookups
  trust_index(ledger, stats)            -> CV Trust Index 0..100, band, coverage

Status rules (never "false" for not found):
  verified         identity + org + title / degree / metric on a tier-1/2 source, or on 2 independent tier-3 hosts
  partly_verified  the organisation is confirmed but not the title / degree / number, or only one tier-3 or snippet
  not_found        searched (or the organisation is on a stored page) but no verified fact supports it
  unverifiable     nothing public to check against (no organisation, or not searched within the budget)
  contradicted     an independent page that names the person and the same organisation states a different title,
                   period, degree or number, and code finds that quote on the stored page -> "needs human review"
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urlparse

from pydantic import BaseModel, Field

MAX_CLAIMS = 20
STATUS_WEIGHT = {"verified": 1.0, "partly_verified": 0.6, "unverifiable": 0.35, "not_found": 0.2,
                 "contradicted": 0.0}
STATUSES = tuple(STATUS_WEIGHT)
TRUST_HIGH, TRUST_MEDIUM = 70.0, 45.0
_YEAR = re.compile(r"\b(19[6-9]\d|20[0-4]\d)\b")
_WAYBACK = re.compile(r"^https://web\.archive\.org/web/(\d{4})\d*(?:id_)?/", re.I)
_NUM = re.compile(r"(\d+(?:[.,]\d+)?)\s*(k|m|mn|million|b|bn|billion|%|x)?", re.I)
_PRESENT = ("present", "current", "now", "nay", "hiện tại", "today", "")

# Tier-1 hosts: registries, universities, credential issuers. Tier-2: established press, structured public data.
T1_SUFFIXES = (".gov", ".gov.au", ".gov.vn", ".edu", ".edu.au", ".edu.vn", ".ac.uk", ".ac.nz", ".ac.jp")
T1_HOSTS = ("abr.business.gov.au", "asic.gov.au", "credly.com", "coursera.org", "learn.microsoft.com",
            "credentials.aws.com", "orcid.org", "scholar.google.com")
T2_HOSTS = ("api.github.com", "github.com", "openalex.org", "api.openalex.org", "web.archive.org", "reuters.com",
            "afr.com", "smh.com.au", "abc.net.au", "theaustralian.com.au", "techcrunch.com", "bloomberg.com",
            "forbes.com", "businessinsider.com", "startupdaily.net", "smartcompany.com.au", "itnews.com.au",
            "crunchbase.com", "vnexpress.net", "cafef.vn", "vneconomy.vn", "tuoitre.vn", "thanhnien.vn",
            "e27.co", "techinasia.com", "ft.com", "wsj.com", "nytimes.com", "theguardian.com", "bbc.com")

# Role families: a claimed title and a fact "match" when they share a family.
_FAMILIES = {
    "ceo": r"\bceo\b|chief executive|managing director|\bmd\b|general director|tổng giám đốc|giám đốc điều hành",
    "cto": r"\bcto\b|chief technology|chief technical|giám đốc công nghệ",
    "cfo": r"\bcfo\b|chief financial|giám đốc tài chính",
    "coo": r"\bcoo\b|chief operating",
    "cmo": r"\bcmo\b|chief marketing",
    "cpo": r"\bcpo\b|chief product",
    "founder": r"\bfound(?:er|ed|ing)\b|co-?founder|sáng lập",
    "engineering": r"engineer|engineering|developer|software|architect|tech lead|devops|\bcto\b|chief technology|"
                   r"kỹ sư|lập trình",
    "sales": r"\bsales\b|business development|account (?:executive|manager)|\bbd\b|kinh doanh",
    "marketing": r"marketing|\bgrowth\b|\bbrand\b",
    "product": r"product (?:manager|owner|lead|director)|head of product|\bcpo\b|chief product",
    "finance": r"financ|accountant|accounting|controller|treasur|investment|\bcfo\b",
    "operations": r"operations|\bops\b|\bcoo\b|supply chain|logistics",
    "data": r"data scien|data engineer|machine learning|\bml\b|\bai\b|analytics|data analyst",
    "research": r"research|scientist|professor|lecturer|postdoc|phd candidate",
    "design": r"design|\bux\b|\bui\b",
    "procurement": r"\bbuyer\b|procurement|purchasing|category manager",
    "legal": r"\blegal\b|counsel|lawyer|solicitor|attorney",
    "people": r"\bhr\b|human resources|people (?:lead|partner|ops)|talent|recruit",
    "advisor": r"advis[oe]r|board member|non-executive|\bned\b|chairman|chair of the board",
    "consulting": r"consult",
}
_FAM = {k: re.compile(v, re.I) for k, v in _FAMILIES.items()}
_DEGREES = {"phd": r"\bph\.?d\b|doctorate|doctor of|tiến sĩ", "master": r"\bmaster|\bmba\b|\bm\.?sc\b|\bmeng\b|thạc sĩ",
            "bachelor": r"\bbachelor|\bb\.?sc\b|\bb\.?a\b|\bbeng\b|\bbcom\b|undergraduate|cử nhân|kỹ sư",
            "diploma": r"diploma|associate degree|cao đẳng"}
_DEG = {k: re.compile(v, re.I) for k, v in _DEGREES.items()}


# ------------------------------------------------------------------ model suggestion schemas
class ClaimConflict(BaseModel):
    source_url: str = ""
    quote: str = Field(default="", max_length=400, description="verbatim excerpt of that page stating the conflict")
    field: str = Field(default="", description="title | dates | degree | metric")
    source_value: str = Field(default="", max_length=120, description="what the page says, e.g. 'Sales Manager'")


class ClaimCheck(BaseModel):
    claim_id: str = Field(description="c1, c2, ... from the CV CLAIMS list")
    fact_ids: list[str] = Field(default=[], description="your fact ids that support this claim")
    conflict: ClaimConflict | None = None
    note: str = Field(default="", max_length=240)


# ------------------------------------------------------------------ helpers
def _fold(s: str) -> str:
    from .people import fold

    return fold(s)


def families(text: str) -> set[str]:
    return {k for k, rx in _FAM.items() if rx.search(text or "")}


_LEVELS = ((r"\bintern\b|trainee|thực tập", 0), (r"\bc[a-z]o\b|chief|president|managing director|"
                                                          r"tổng giám đốc|giám đốc", 5),
           (r"\bvp\b|vice president|head of|\bhead\b|director|trưởng phòng", 4),
           (r"manager|\blead\b|team lead|principal|quản lý", 3), (r"\bsenior\b|\bsr\.?\b|chuyên viên cao cấp", 2),
           (r"junior|\bjr\.?\b|associate|assistant", 1))
_LEVEL = [(re.compile(p, re.I), n) for p, n in _LEVELS]


def title_level(title: str) -> int | None:
    """0 intern .. 5 C-level; None for founder / advisor / board titles or when nothing says (an IC title = 1)."""
    t = title or ""
    if _FAM["founder"].search(t) or _FAM["advisor"].search(t):
        return None
    hit = next((n for rx, n in _LEVEL if rx.search(t)), None)
    return hit if hit is not None else (1 if families(t) else None)


def titles_agree(a: str, b: str) -> bool | None:
    """True: same function and level within one step; False: another function, or the same function two or more
    levels apart (an inflated title); None: cannot tell."""
    fa, fb = families(a), families(b)
    if not fa or not fb:
        return None
    if not fa & fb:
        return False
    la, lb = title_level(a), title_level(b)
    if la is not None and lb is not None and abs(la - lb) >= 2:
        return False
    return True


def degree_level(text: str) -> str | None:
    return next((k for k, rx in _DEG.items() if rx.search(text or "")), None)


def _year_of(s: str) -> int | None:
    m = _YEAR.search(s or "")
    return int(m.group(1)) if m else None


def _span(claim: dict) -> tuple[int | None, int | None]:
    a = _year_of(claim.get("start") or "")
    end = (claim.get("end") or "").strip().lower()
    z = datetime.now(UTC).year if end in _PRESENT and a else _year_of(end)
    return a, z


def _number(s: str) -> float | None:
    """'40%' -> 40, 'A$2M' -> 2e6, '3x' -> 3, '1,200 users' -> 1200."""
    for m in _NUM.finditer(s or ""):
        try:
            v = float(m.group(1).replace(",", "")) if "," in m.group(1) and len(m.group(1).split(",")[-1]) == 3 \
                else float(m.group(1).replace(",", "."))
        except ValueError:
            continue
        unit = (m.group(2) or "").lower()
        v *= {"k": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}.get(unit, 1)
        if v and not (1960 <= v <= 2049 and not unit):  # a year is not the metric
            return v
    return None


def host_of(url: str) -> str:
    h = (urlparse(url or "").hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def source_tier(url: str, kind: str, *, business_host: str = "", org: str = "") -> int:
    """1 registry / university / issuer / the claimed organisation's own site; 2 press, structured data, the
    business's own site (not independent for its founders); 3 other pages; 4 search snippets."""
    if kind == "search_snippet":
        return 4
    h = host_of(url)
    if not h:
        return 3
    if h.endswith(T1_SUFFIXES) or any(h == x or h.endswith("." + x) for x in T1_HOSTS):
        return 1
    if business_host and (h == business_host or h.endswith("." + business_host)):
        return 2
    if org:
        from .people import org_key

        k = org_key(org).replace(" ", "")
        label = h.split(".")[0].replace("-", "")
        if len(k) >= 4 and (label == k or (len(label) >= 4 and (label in k or k in label))):
            return 1
    if any(h == x or h.endswith("." + x) for x in T2_HOSTS):
        return 2
    return 3


def _cv_quote(cv: str, *needles: str) -> str:
    """The first CV line naming one of the needles (an exact excerpt, so the UI can show what the CV says)."""
    from .people import names_org

    for n in needles:
        if not n or len(n.strip()) < 3:
            continue
        for line in (cv or "").splitlines():
            if names_org(line, n) or (n.strip().lower() in line.lower()):
                return line.strip()[:200]
    return ""


# ------------------------------------------------------------------ claims
def claims_from_review(review: dict, cv: str) -> list[dict]:
    """Normalised claims from the CV review (code only; the review parts are model-read but self-reported)."""
    from .people import org_key

    tl, ins = review.get("timeline") or {}, review.get("insights") or {}
    now = datetime.now(UTC).year
    out: list[dict] = []
    seen: set[tuple] = set()

    def add(kind: str, text: str, importance: int, **kw) -> None:
        key = (kind, org_key(kw.get("org") or ""), (kw.get("title") or "").lower()[:40], (kw.get("metric") or ""))
        if key in seen or not text.strip():
            return
        seen.add(key)
        out.append({"id": "", "kind": kind, "text": text.strip()[:300], "org": kw.get("org") or "",
                    "title": kw.get("title") or "", "start": kw.get("start") or "", "end": kw.get("end") or "",
                    "metric": kw.get("metric") or "", "cv_quote": kw.get("cv_quote") or "",
                    "importance": importance})

    for i, r in enumerate((tl.get("roles") or [])[:12]):
        org, title = (r.get("org") or "").strip(), (r.get("title") or "").strip()
        if not org:
            continue
        end = (r.get("end") or "").strip()
        current = end.lower() in _PRESENT
        a, z = _year_of(r.get("start") or ""), (now if current else _year_of(end))
        imp = 3 if i == 0 and current else 2 if (current or (z or 0) >= now - 5) else 1
        dates = f" ({r.get('start') or '?'}–{end or 'present'})" if r.get("start") or end else ""
        kind = "venture" if r.get("kind") == "founder" else "role"
        add(kind, f"{title + ' at ' if title else ''}{org}{dates}", imp, org=org, title=title,
            start=r.get("start") or "", end=end, cv_quote=_cv_quote(cv, org))
        if a and z and z < a:
            out[-1]["date_issue"] = True
    for i, e in enumerate((tl.get("education") or [])[:4]):
        inst = (e.get("institution") or "").strip()
        if not inst:
            continue
        deg = " ".join(x for x in (e.get("degree") or "", e.get("field") or "") if x).strip()
        add("education", f"{deg + ', ' if deg else ''}{inst}", 2 if i == 0 else 1, org=inst,
            title=e.get("degree") or "", start=e.get("start") or "", end=e.get("end") or "",
            cv_quote=_cv_quote(cv, inst))
    for c in (tl.get("certifications") or [])[:3]:
        add("certification", c, 1, title=c, cv_quote=_cv_quote(cv, c))
    for a in (ins.get("achievements") or [])[:6]:
        if not a.get("metric"):
            continue
        add("achievement", a.get("text") or "", 1, org=a.get("org") or "", metric=a.get("metric") or "",
            cv_quote=_cv_quote(cv, a.get("metric") or "", a.get("org") or ""))
    covered = {org_key(c["org"]) for c in out if c["org"]}
    for c in (ins.get("claims") or [])[:8]:
        k = c.get("kind") or "other"
        if k in ("role", "education") and org_key(c.get("org") or "") in covered:
            continue  # already a structured role / degree claim
        add({"venture": "venture", "achievement": "achievement"}.get(k, "award" if k == "other" else k),
            c.get("text") or "", 1, org=c.get("org") or "", cv_quote=_cv_quote(cv, c.get("org") or ""))
    out.sort(key=lambda c: -c["importance"])  # stable: newest first inside the same importance
    out = out[:MAX_CLAIMS]
    for i, c in enumerate(out, 1):
        c["id"] = f"c{i}"
    return out


def claim_queries(name: str, claims: list[dict], company: str, done: list[str], n: int) -> list[tuple[str, str]]:
    """Up to n searches aimed at the most important claims with an organisation not already searched."""
    from ..tools.brave import sanitize_query
    from .people import org_key, redact

    name = " ".join((name or "").split())
    comp = org_key(company)
    taken = {q.lower() for q in done}
    orgs: set[str] = set()
    out: list[tuple[str, str]] = []
    for c in sorted(claims, key=lambda c: -c["importance"]):
        k = org_key(c["org"])
        if not k or k in orgs or (comp and k == comp) or len(out) >= n:
            continue
        title = " ".join(c["title"].split()[:4])
        q = {"education": f'"{name}" "{c["org"]}"', "venture": f'"{name}" "{c["org"]}" founder',
             "achievement": f'"{name}" "{c["org"]}"'}.get(c["kind"], f'"{name}" "{c["org"]}" {title}')
        q = sanitize_query(redact(q))[:200].strip()
        if q and q.lower() not in taken:
            out.append((c["id"], q))
            taken.add(q.lower())
            orgs.add(k)
    return out


# ------------------------------------------------------------------ ledger
def _fact_text(f: dict) -> str:
    return f"{f.get('text', '')} {f.get('quote', '')}"


def _years_in(f: dict) -> set[int]:
    ys = {int(y) for y in _YEAR.findall(_fact_text(f))}
    m = _WAYBACK.match(f.get("url") or "")
    if m:
        ys.add(int(m.group(1)))
    return ys


def _check_conflict(c: dict, cf: ClaimConflict | None, pages: dict[str, list[str]], kinds: dict[str, str],
                    person: str) -> dict | None:
    """A model-proposed conflict counts only when every check passes (zero false 'contradicted' is the goal)."""
    from .people import names_org, names_person, quote_in

    if cf is None or not cf.quote or not cf.source_value or cf.field not in ("title", "dates", "degree", "metric"):
        return None
    page = pages.get(cf.source_url)
    if not page or kinds.get(cf.source_url) == "search_snippet":
        return None
    if not any(quote_in(cf.quote, t) for t in page) or not any(names_person(t, person) for t in page):
        return None
    if _fold(cf.source_value) not in _fold(cf.quote):
        return None  # the conflicting value must be stated in the quote itself
    if c["org"] and not names_org(cf.quote, c["org"]):
        return None  # same organisation, different value — otherwise it may be another job
    if cf.field == "title":
        if titles_agree(c["title"], cf.source_value) is not False:
            return None
    elif cf.field == "dates":
        lo, hi = _span(c)
        y = _year_of(cf.source_value)
        if lo is None or y is None or (lo - 1) <= y <= ((hi or lo) + 1):
            return None
    elif cf.field == "degree":
        a, b = degree_level(c["title"] or c["text"]), degree_level(cf.source_value)
        if not a or not b or a == b:
            return None
    else:
        a, b = _number(c["metric"] or c["text"]), _number(cf.source_value)
        if not a or not b or abs(a - b) / max(a, b) <= 0.25:
            return None
    return {"url": cf.source_url, "quote": cf.quote[:400], "field": cf.field, "source_value": cf.source_value[:120]}


def build_ledger(claims: list[dict], facts: list[dict], checks: list[ClaimCheck], ids: dict[str, str],
                 evidence: list, *, person: str, business_host: str = "", searched: set[str] | None = None,
                 anchors: list[str] | None = None, provided: set[str] | None = None,
                 lookups: list[dict] | None = None) -> dict:
    """`facts`: verified facts (global ids); `ids`: model fact id -> global id; `evidence`: [(EvidenceItem, text)]."""
    from .people import names_org, names_person

    searched = searched or set()
    pages: dict[str, list[str]] = {}
    kinds: dict[str, str] = {}
    for ev, text in evidence:
        pages.setdefault(ev.url, []).extend([text or "", ev.snippet or ""])
        kinds.setdefault(ev.url, ev.kind)
    by_id = {f["id"]: f for f in facts}
    chk = {c.claim_id: c for c in checks}
    stored_text = " ".join(t for ts in pages.values() for t in ts)
    out = []
    for c in claims:
        ck = chk.get(c["id"])
        mapped = [by_id[ids[i]] for i in (ck.fact_ids if ck else []) if i in ids and ids[i] in by_id]
        org_hits = [f for f in facts if c["org"] and names_org(_fact_text(f), c["org"])]
        if c["kind"] == "certification" and not c["org"]:
            org_hits = [f for f in facts if c["title"] and _fold(c["title"]) in _fold(_fact_text(f))]
        cands = list({f["id"]: f for f in [*org_hits, *mapped]}.values())
        dims: dict[str, bool | None] = {"identity": None, "org": None, "title": None, "dates": None,
                                        "degree": None, "metric": None}
        conflict = _check_conflict(c, ck.conflict if ck else None, pages, kinds, person)
        if cands:
            dims["identity"] = True
            dims["org"] = True if org_hits else None
        ctx = org_hits or cands
        if c["kind"] in ("role", "venture") and c["title"] and ctx:
            fam = families(c["title"]) | ({"founder"} if c["kind"] == "venture" else set())
            lvl = title_level(c["title"])
            for f in ctx:
                ft = _fact_text(f)
                fl = title_level(ft)
                if fam & families(ft) and (lvl is None or fl is None or abs(lvl - fl) <= 1 or "founder" in fam
                                           & families(ft)):
                    dims["title"] = True
                    break
        lo, hi = _span(c)
        if lo and ctx and any(lo - 1 <= y <= (hi or lo) + 1 for f in ctx for y in _years_in(f)):
            dims["dates"] = True
        if c["kind"] == "education" and ctx:
            lvl = degree_level(c["title"] or c["text"])
            if lvl and any(degree_level(_fact_text(f)) == lvl for f in ctx):
                dims["degree"] = True
        if c["metric"] and ctx:
            want = _number(c["metric"])
            if want and any((v := _number(_fact_text(f))) and abs(v - want) / max(v, want) <= 0.1 for f in ctx):
                dims["metric"] = True
        if conflict:
            dims[conflict["field"]] = False
        tiers = sorted({(source_tier(f["url"], kinds.get(f["url"], "web"), business_host=business_host,
                                     org=c["org"]), host_of(f["url"])) for f in cands})
        best = tiers[0][0] if tiers else None
        t3_hosts = {h for t, h in tiers if t == 3}
        need = {"role": "title", "venture": "title", "education": "degree", "achievement": "metric"}.get(c["kind"])
        need_ok = need is None or dims[need] is True or (need == "title" and not c["title"]) or \
            (need == "degree" and not degree_level(c["title"] or c["text"])) or (need == "metric" and not c["metric"])
        if conflict:
            status, note = "contradicted", "A public source states something different — needs human review"
        elif cands and dims["org"] and need_ok and best is not None and (best <= 2 or len(t3_hosts) >= 2):
            status, note = "verified", ""
        elif cands:
            status = "partly_verified"
            note = ("The organisation is confirmed; the " + need + " is not stated by the source") if (
                dims["org"] and not need_ok) else ("Only one independent page or a search snippet"
                                                  if dims["org"] else "A source supports it without naming the "
                                                                      "organisation")
        elif not c["org"]:
            status, note = "unverifiable", "No organisation to check against"
        elif c["id"] in searched or names_org(stored_text, c["org"]):
            status, note = "not_found", "Searched; no public source confirms it (not the same as false)"
        else:
            status, note = "unverifiable", "Not searched — the search budget went to more important claims"
        out.append({**{k: c[k] for k in ("id", "kind", "text", "org", "title", "start", "end", "metric",
                                         "cv_quote", "importance")},
                    "status": status, "dims": dims, "fact_ids": [f["id"] for f in cands][:6], "best_tier": best,
                    "sources": [{"url": f["url"], "tier": source_tier(f["url"], kinds.get(f["url"], "web"),
                                                                     business_host=business_host, org=c["org"])}
                                for f in cands][:6],
                    "conflict": conflict, "note": ((ck.note if ck else "") or note)[:240],
                    "date_issue": bool(c.get("date_issue"))})
    namesakes = []
    if anchors is not None:
        for url, texts in pages.items():
            if url in (provided or set()) or not any(names_person(t, person) for t in texts):
                continue
            if not any(names_org(t, a) for t in texts for a in anchors):
                namesakes.append({"url": url, "reason": "Names the person but none of their organisations — "
                                                        "possibly someone else with the same name; not used"})
    counts = {s: sum(1 for c in out if c["status"] == s) for s in STATUSES}
    return {"claims": out, "counts": counts, "namesakes": namesakes[:6], "lookups": (lookups or [])[:12]}


def trust_index(ledger: dict, stats: dict | None = None) -> dict | None:
    claims = ledger.get("claims") or []
    if not claims:
        return None
    tot = sum(c["importance"] for c in claims)
    score = round(100 * sum(c["importance"] * STATUS_WEIGHT[c["status"]] for c in claims) / tot, 1)
    key = [c for c in claims if c["importance"] >= 2]
    cov = round(100 * sum(1 for c in key if c["status"] in ("verified", "partly_verified")) / len(key)) if key \
        else None
    bad = sum(1 for c in key if c["status"] == "contradicted")
    band = "low" if (score < TRUST_MEDIUM or bad) else "high" if score >= TRUST_HIGH else "medium"
    n = ledger.get("counts") or {}
    return {"score": score, "band": band, "coverage_pct": cov, "contradicted_key": bad,
            "consistency": {"overlaps": (stats or {}).get("overlaps", 0),
                            "date_issues": sum(1 for c in claims if c.get("date_issue"))},
            "summary": f"{n.get('verified', 0)} verified, {n.get('partly_verified', 0)} partly, "
                       f"{n.get('not_found', 0)} not found, {n.get('unverifiable', 0)} unverifiable, "
                       f"{n.get('contradicted', 0)} in conflict of {len(claims)} CV claims"}
