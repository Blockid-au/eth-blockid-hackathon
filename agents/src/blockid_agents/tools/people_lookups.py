"""Free structured lookups for the People Analyst's CV cross-check (docs/PLAN-HR-V3.md §1.2). No keys.

* GitHub REST (api.github.com/users/<login> + /orgs) — only for a GitHub URL the person or their CV gives.
* OpenAlex authors (api.openalex.org) — kept only when an affiliation matches an organisation the CV names
  (namesakes are common for researchers).
* Wayback Machine — the earliest archived copy of a page that names the person (e.g. the company's team page), so a
  role can be dated ("listed as CTO in June 2021").

Each lookup returns evidence pages [{url, title, text, kind}] plus a record for the report's `lookups` list. Results
are cached 7 days in the evidence store's cache table (same pattern as tools/lookups.py); any error returns nothing,
6 s timeout, so a lookup never blocks or fails a report. `HR_LOOKUPS` (default "wayback,github,openalex") picks
which run; tests inject a transport or disable them.
"""
from __future__ import annotations

import re
from urllib.parse import quote

import httpx

from .lookups import CACHE_TTL_S, TIMEOUT_S

_GH = re.compile(r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))(?:/|$|\?)", re.I)
_GH_RESERVED = {"orgs", "about", "features", "pricing", "topics", "collections", "sponsors", "enterprise", "login"}


def github_logins(urls: list[str]) -> list[str]:
    out = []
    for u in urls or []:
        m = _GH.search(u or "")
        if m and m.group(1).lower() not in _GH_RESERVED and m.group(1).lower() not in out:
            out.append(m.group(1).lower())
    return out[:2]


class PeopleLookups:
    def __init__(self, store=None, *, kinds: tuple[str, ...] = ("wayback", "github", "openalex"),
                 transport: httpx.BaseTransport | None = None, offline: bool = False):
        self.store, self.kinds, self.offline = store, set(kinds), offline
        self.http = httpx.Client(timeout=TIMEOUT_S, transport=transport, trust_env=False, follow_redirects=True,
                                 headers={"User-Agent": "BlockID-HR/1.0 (+https://hr.blockid.au)",
                                          "Accept": "application/json"})

    def _cached(self, key: str, fn):
        if self.store is not None:
            try:
                hit = self.store.cache_get("lookup:hr:" + key, CACHE_TTL_S)
            except Exception:  # noqa: BLE001
                hit = None
            if hit is not None:
                return hit
        if self.offline:
            return {}
        try:
            val = fn() or {}
        except Exception:  # noqa: BLE001 - lookups never fail a report
            return {}
        if self.store is not None:
            try:
                self.store.cache_put("lookup:hr:" + key, val)
            except Exception:  # noqa: BLE001
                pass
        return val

    # ---------------------------------------------------------------- GitHub
    def github(self, login: str) -> dict:
        if "github" not in self.kinds or not login:
            return {}

        def go():
            r = self.http.get(f"https://api.github.com/users/{quote(login)}")
            if r.status_code != 200:
                return {"found": False}
            u = r.json() or {}
            orgs = []
            o = self.http.get(f"https://api.github.com/users/{quote(login)}/orgs")
            if o.status_code == 200:
                orgs = [x.get("login") for x in (o.json() or []) if x.get("login")][:12]
            return {"found": True, "login": u.get("login") or login, "name": u.get("name") or "",
                    "company": u.get("company") or "", "blog": u.get("blog") or "",
                    "location": u.get("location") or "",
                    "bio": u.get("bio") or "", "created_at": (u.get("created_at") or "")[:10],
                    "public_repos": u.get("public_repos"), "followers": u.get("followers"), "orgs": orgs}
        d = self._cached(f"github:{login.lower()}", go)
        if not d.get("found"):
            return {"record": {"kind": "github", "query": login, "url": f"https://github.com/{login}",
                               "found": False, "detail": "no public GitHub profile"}} if d else {}
        text = (f"GitHub profile github.com/{d['login']} (GitHub API). Name: {d['name'] or 'not set'}. "
                f"Company: {d['company'] or 'not set'}. Bio: {d['bio'] or 'not set'}. "
                f"Location: {d['location'] or 'not set'}. "
                f"Website: {d['blog'] or 'not set'}. Account created: {d['created_at']}. Public repositories: "
                f"{d['public_repos']}. Followers: {d['followers']}. "
                f"Organisations: {', '.join(d['orgs']) or 'none public'}.")
        url = f"https://api.github.com/users/{d['login']}"
        return {"page": {"url": url, "title": f"GitHub — {d['name'] or d['login']}", "text": text, "kind": "provided"},
                "record": {"kind": "github", "query": login, "url": f"https://github.com/{d['login']}", "found": True,
                           "detail": f"account since {d['created_at'][:4]}, {d['public_repos']} public repos"
                                     + (f", company {d['company']}" if d["company"] else "")}}

    # ---------------------------------------------------------------- OpenAlex
    def openalex(self, name: str, orgs: list[str]) -> dict:
        from ..agents.people import names_org, names_person

        if "openalex" not in self.kinds or not name or not orgs:
            return {}

        def go():
            r = self.http.get("https://api.openalex.org/authors", params={"search": name[:100], "per-page": "5"})
            if r.status_code != 200:
                return {"found": False}
            out = []
            for a in (r.json() or {}).get("results") or []:
                affs = []
                for x in a.get("affiliations") or []:
                    inst = (x.get("institution") or {}).get("display_name") or ""
                    ys = sorted(x.get("years") or [])
                    if inst:
                        affs.append({"institution": inst, "from": ys[0] if ys else None,
                                     "to": ys[-1] if ys else None})
                out.append({"id": (a.get("id") or "").rsplit("/", 1)[-1], "name": a.get("display_name") or "",
                            "works": a.get("works_count"), "cited_by": a.get("cited_by_count"),
                            "affiliations": affs[:10]})
            return {"found": True, "authors": out}
        d = self._cached(f"openalex:{name.lower()}", go)
        for a in d.get("authors") or []:
            if not names_person(a["name"], name):
                continue
            hits = [x for x in a["affiliations"] if any(names_org(x["institution"], o) or names_org(o, x["institution"])
                                                       for o in orgs)]
            if not hits:
                continue
            affs = "; ".join(f"{x['institution']} ({x['from']}–{x['to']})" if x["from"] else x["institution"]
                             for x in a["affiliations"])
            text = (f"OpenAlex author record for {a['name']} (openalex.org/{a['id']}). Affiliations: {affs}. "
                    f"Works: {a['works']}. Cited by: {a['cited_by']}.")
            url = f"https://openalex.org/{a['id']}"
            return {"page": {"url": url, "title": f"OpenAlex — {a['name']}", "text": text, "kind": "web"},
                    "record": {"kind": "openalex", "query": name, "url": url, "found": True,
                               "detail": f"{a['works']} works; affiliation match: {hits[0]['institution']}"}}
        return {"record": {"kind": "openalex", "query": name, "url": "https://openalex.org", "found": False,
                           "detail": "no author record matching the CV's organisations"}} if d else {}

    # ---------------------------------------------------------------- Wayback
    def wayback(self, page_url: str, fetch) -> dict:
        """Earliest archived copy of `page_url` (fetched with the SSRF-safe fetcher)."""
        if "wayback" not in self.kinds or not page_url.startswith("https://"):
            return {}

        def go():
            r = self.http.get("https://web.archive.org/cdx/search/cdx",
                              params={"url": page_url, "output": "json", "limit": "1", "fl": "timestamp",
                                      "filter": "statuscode:200"})
            if r.status_code != 200:
                return {"found": False}
            rows = r.json() or []
            return {"found": len(rows) >= 2 and bool(rows[1]), "ts": str(rows[1][0]) if len(rows) >= 2 and rows[1]
                    else None}
        d = self._cached(f"wayback:{page_url}", go)
        if not d.get("found") or not d.get("ts"):
            return {"record": {"kind": "wayback", "query": page_url, "url": page_url, "found": False,
                               "detail": "no archived copy"}} if d else {}
        ts = d["ts"]
        arch = f"https://web.archive.org/web/{ts}id_/{page_url}"
        try:
            body = fetch(arch) or ""
        except Exception:  # noqa: BLE001
            body = ""
        date = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
        rec = {"kind": "wayback", "query": page_url, "url": f"https://web.archive.org/web/{ts}/{page_url}",
               "found": bool(body.strip()), "detail": f"earliest copy {date}"}
        if not body.strip():
            return {"record": rec}
        text = f"Archived copy of {page_url} captured on {date} (Wayback Machine).\n{body}"
        return {"page": {"url": rec["url"], "title": f"Archived {page_url} ({date[:7]})", "text": text, "kind": "web"},
                "record": rec}
