"""Free public lookups for evaluation v5 (no paid keys; docs/PLAN-EVALUATION-V5.md §2 table, §2.3).

* Tranco rank (tranco-list.eu API) — only ever a CONTRADICTION flag, never a positive score input.
* Wayback CDX first snapshot (web.archive.org) — site age ("first seen").
* iTunes Search API (itunes.apple.com/search) — App Store rating and rating count of the company's app (matched
  by seller URL / name); feeds retention R4 and moat "brand" (level 3, public).
* ABS Counts of Australian Businesses June 2025 (local table agents/data/abs_business_counts_2025.csv) — the
  bottom-up SAM count for AU B2B targets; no network.
* ABN Lookup (abr.business.gov.au JSON web service) — only when ABN_LOOKUP_GUID is set (free registration).

Every network lookup is cached 7 days in the evidence store's cache table (key "lookup:<kind>:<arg>"), fails soft
(returns {} on any error, records nothing) and has a 6 s timeout, so it can never block or fail a valuation.
Set LOOKUPS_OFFLINE=1 to disable network lookups (tests set a transport instead).
"""
from __future__ import annotations

import csv
import json
import os
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx

CACHE_TTL_S = 7 * 24 * 3600
TIMEOUT_S = 6.0
ABS_TABLE = Path(__file__).resolve().parent.parent / "agents" / "data" / "abs_business_counts_2025.csv"
ABS_SOURCE_URL = ("https://www.abs.gov.au/statistics/economy/business-indicators/"
                  "counts-australian-businesses-including-entries-and-exits/jul2021-jun2025")
BANDS = {  # size band -> columns summed
    "all": ("non_employing", "emp_1_4", "emp_5_19", "emp_20_199", "emp_200_plus"),
    "employing": ("emp_1_4", "emp_5_19", "emp_20_199", "emp_200_plus"),
    "non_employing": ("non_employing",),
    "1-19": ("emp_1_4", "emp_5_19"),
    "20-199": ("emp_20_199",),
    "200+": ("emp_200_plus",),
}


def domain_of(url: str) -> str:
    host = (urlparse(url if "//" in url else f"https://{url}").hostname or "").lower()
    return host.removeprefix("www.")


class Lookups:
    def __init__(self, store=None, *, transport: httpx.BaseTransport | None = None, offline: bool | None = None,
                 abn_guid: str | None = None):
        self.store = store
        self.offline = (os.environ.get("LOOKUPS_OFFLINE", "0") == "1") if offline is None else offline
        self.abn_guid = abn_guid if abn_guid is not None else os.environ.get("ABN_LOOKUP_GUID", "")
        self.http = httpx.Client(timeout=TIMEOUT_S, transport=transport, trust_env=False, follow_redirects=True,
                                 headers={"User-Agent": "BlockID-Startup-Passport/1.0 (+https://eth.blockid.au)"})

    # ---------------------------------------------------------------- cache
    def _cached(self, key: str, fn) -> dict:
        if self.store is not None:
            try:
                hit = self.store.cache_get("lookup:" + key, CACHE_TTL_S)
            except Exception:  # noqa: BLE001
                hit = None
            if hit is not None:
                return {**hit, "cached": True}
        if self.offline:
            return {}
        try:
            val = fn() or {}
        except Exception:  # noqa: BLE001 - lookups never fail a valuation
            return {}
        if val and self.store is not None:
            try:
                self.store.cache_put("lookup:" + key, val)
            except Exception:  # noqa: BLE001
                pass
        return val

    # ---------------------------------------------------------------- lookups
    def tranco(self, url: str) -> dict:
        d = domain_of(url)
        if not d:
            return {}

        def go():
            r = self.http.get(f"https://tranco-list.eu/api/ranks/domain/{quote(d)}")
            if r.status_code != 200:
                return {}
            ranks = (r.json() or {}).get("ranks") or []
            best = min((x.get("rank") for x in ranks if x.get("rank")), default=None)
            return {"domain": d, "rank": best, "source_url": f"https://tranco-list.eu/query#{d}",
                    "in_top_1m": best is not None}
        return self._cached(f"tranco:{d}", go)

    def wayback_first_seen(self, url: str) -> dict:
        d = domain_of(url)
        if not d:
            return {}

        def go():
            r = self.http.get("https://web.archive.org/cdx/search/cdx",
                              params={"url": d, "output": "json", "limit": "1", "fl": "timestamp"})
            if r.status_code != 200:
                return {}
            rows = r.json() or []
            if len(rows) < 2 or not rows[1]:
                return {"domain": d, "first_seen": None}
            ts = str(rows[1][0])
            return {"domain": d, "first_seen": f"{ts[:4]}-{ts[4:6]}",
                    "source_url": f"https://web.archive.org/web/{ts}/{d}"}
        return self._cached(f"wayback:{d}", go)

    def app_store(self, company: str, site_url: str, country: str = "au") -> dict:
        """The company's iOS app (seller URL on the company's domain, else an exact seller-name match)."""
        name = (company or "").strip()
        dom = domain_of(site_url)
        if not name:
            return {}

        def go():
            r = self.http.get("https://itunes.apple.com/search", params={
                "term": name[:80], "entity": "software", "country": (country or "au").lower()[:2], "limit": "8"})
            if r.status_code != 200:
                return {}
            best = None
            for x in (r.json() or {}).get("results") or []:
                seller_dom = domain_of(x.get("sellerUrl") or "")
                seller = (x.get("sellerName") or x.get("artistName") or "").lower()
                if (dom and seller_dom and (seller_dom == dom or seller_dom.endswith("." + dom))) or \
                        _norm(name) and _norm(name) in _norm(seller):
                    if best is None or (x.get("userRatingCount") or 0) > (best.get("userRatingCount") or 0):
                        best = x
            if not best:
                return {"matched": False}
            return {"matched": True, "app": best.get("trackName"), "rating": best.get("averageUserRating"),
                    "rating_count": best.get("userRatingCount"), "source_url": best.get("trackViewUrl"),
                    "seller": best.get("sellerName")}
        return self._cached(f"itunes:{country}:{_norm(name)}:{dom}", go)

    def abn(self, company: str) -> dict:
        if not self.abn_guid or not company:
            return {}

        def go():
            r = self.http.get("https://abr.business.gov.au/json/MatchingNames.aspx",
                              params={"name": company[:100], "maxResults": "3", "guid": self.abn_guid})
            m = re.search(r"\((\{.*\})\)", r.text, re.DOTALL)
            data = json.loads(m.group(1)) if m else {}
            names = data.get("Names") or []
            if not names:
                return {"matched": False}
            n = names[0]
            return {"matched": True, "abn": n.get("Abn"), "name": n.get("Name"), "state": n.get("State"),
                    "status": n.get("AbnStatus"), "score": n.get("Score"),
                    "source_url": f"https://abr.business.gov.au/ABN/View?abn={n.get('Abn')}"}
        return self._cached(f"abn:{_norm(company)}", go)


def _norm(s: str) -> str:
    s = re.sub(r"\b(pty|ltd|limited|inc|llc|group|holdings|co)\b\.?", " ", (s or "").lower())
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


# ------------------------------------------------------------------ ABS counts (local table)
@lru_cache(maxsize=1)
def _abs_rows() -> tuple[dict, ...]:
    with ABS_TABLE.open(newline="", encoding="utf-8") as f:
        lines = [ln for ln in f if not ln.startswith("#")]
    return tuple(csv.DictReader(lines))


def abs_divisions() -> dict[str, str]:
    return {r["code"]: r["label"] for r in _abs_rows() if r["level"] == "division"}


def abs_count(code: str, band: str = "employing") -> dict | None:
    """Number of Australian businesses (June 2025) in an ANZSIC division (letter) or class (4 digits), size band
    all | employing | non_employing | 1-19 | 20-199 | 200+. None when the code/band is unknown."""
    cols = BANDS.get(band or "employing")
    code = (code or "").strip().upper()
    if not cols or not code:
        return None
    level = "division" if re.fullmatch(r"[A-S]", code) else "class" if re.fullmatch(r"\d{4}", code) else None
    if level is None:
        return None
    for r in _abs_rows():
        if r["level"] == level and r["code"] == code:
            n = sum(int(r[c]) for c in cols)
            return {"count": n, "code": code, "label": r["label"], "band": band or "employing", "level": level,
                    "source_url": ABS_SOURCE_URL, "as_of": "2025-06",
                    "note": f"ABS 8165.0 June 2025: {r['label']} ({level} {code}), {band or 'employing'} businesses"}
    return None
