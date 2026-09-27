"""Brave Search client + local evidence store.

Flow: Brave (fresh web/news results) -> fetch pages -> store raw text with URL, timestamp and
SHA-256 in the local evidence DB -> the local model analyses ONLY stored evidence and must cite
the URLs it used. Search responses are cached to save API quota; nothing leaves the server
except the search query itself (never send PII in a query — `sanitize_query` enforces basics).
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from html.parser import HTMLParser
from pathlib import Path

import httpx

from ..schemas import EvidenceItem

BRAVE_WEB = "https://api.search.brave.com/res/v1/web/search"
BRAVE_NEWS = "https://api.search.brave.com/res/v1/news/search"

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"\+?\d[\d\s\-]{7,}\d")


def sanitize_query(q: str) -> str:
    """Strip obvious personal identifiers before a query leaves the server."""
    q = _EMAIL.sub("", q)
    q = _PHONE.sub("", q)
    return " ".join(q.split())[:400]


class EvidenceStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS search_cache(
                  key TEXT PRIMARY KEY, response TEXT NOT NULL, fetched_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS evidence(
                  sha256 TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT, snippet TEXT,
                  text TEXT, query TEXT, retrieved_at REAL NOT NULL, subject TEXT);
                -- v2: the same page may be evidence for several subjects (valuations)
                CREATE TABLE IF NOT EXISTS evidence_v2(
                  sha256 TEXT NOT NULL, url TEXT NOT NULL, title TEXT, snippet TEXT,
                  text TEXT, query TEXT, retrieved_at REAL NOT NULL, subject TEXT NOT NULL DEFAULT '',
                  PRIMARY KEY (sha256, subject));
                CREATE INDEX IF NOT EXISTS ev2_subject ON evidence_v2(subject);
                INSERT OR IGNORE INTO evidence_v2(sha256,url,title,snippet,text,query,retrieved_at,subject)
                  SELECT sha256,url,title,snippet,text,query,retrieved_at,
                  COALESCE(subject,'') FROM evidence;
                DELETE FROM evidence;
                """
            )
            cols = {r[1] for r in c.execute("PRAGMA table_info(evidence_v2)")}
            if "kind" not in cols:
                c.execute("ALTER TABLE evidence_v2 ADD COLUMN kind TEXT NOT NULL DEFAULT ''")

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def cache_get(self, key: str, max_age_s: float) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT response, fetched_at FROM search_cache WHERE key=?", (key,)).fetchone()
        if row and time.time() - row[1] <= max_age_s:
            return json.loads(row[0])
        return None

    def cache_put(self, key: str, response: dict) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO search_cache VALUES (?,?,?)", (key, json.dumps(response), time.time()))

    def add(self, item: EvidenceItem, text: str, subject: str) -> EvidenceItem:
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO evidence_v2(sha256,url,title,snippet,text,query,retrieved_at,subject,kind) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (item.content_sha256, item.url, item.title, item.snippet, text, item.query, item.retrieved_at, subject,
                 item.kind),
            )
        return item

    def delete_subject(self, subject: str, *, prefix: bool = False) -> int:
        """Remove stored evidence of one subject (or every subject starting with `subject` when prefix=True) —
        used when a person asks to be removed from a team report (studio/hr.py)."""
        with self._lock, self._conn() as c:
            if prefix:
                like = subject.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                return c.execute("DELETE FROM evidence_v2 WHERE subject LIKE ? ESCAPE '\\'", (like,)).rowcount
            return c.execute("DELETE FROM evidence_v2 WHERE subject=?", (subject,)).rowcount

    def count(self, subject: str) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(DISTINCT url) FROM evidence_v2 WHERE subject=?", (subject,)).fetchone()[0]

    def for_subject(self, subject: str, limit: int = 30) -> list[tuple[EvidenceItem, str]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT url,title,snippet,query,retrieved_at,sha256,text,kind FROM evidence_v2 "
                "WHERE subject=? ORDER BY retrieved_at DESC LIMIT ?",
                (subject, limit),
            ).fetchall()
        return [
            (EvidenceItem(url=r[0], title=r[1], snippet=r[2], query=r[3], retrieved_at=r[4], content_sha256=r[5],
                          kind=r[7] or ""), r[6])
            for r in rows
        ]


class BraveQuotaError(RuntimeError):
    """The subscription has no requests left this month (Brave still answers 200 with empty results)."""


class BraveUnavailable(BraveQuotaError):
    """Brave refused service (quota / 429 / 402 / 401 / network) — cached for UNAVAILABLE_S so we don't hammer it."""


UNAVAILABLE_S = 600


def _monthly_remaining(r: httpx.Response) -> int | None:
    # e.g. "x-ratelimit-remaining: 1, 0" -> per-second, per-month
    parts = [x.strip() for x in r.headers.get("x-ratelimit-remaining", "").split(",")]
    return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None


class BraveSearch:
    def __init__(
        self,
        api_key: str,
        store: EvidenceStore,
        *,
        max_rps: float = 1.0,
        cache_ttl_hours: int = 72,
        transport: httpx.BaseTransport | None = None,
    ):
        if not api_key:
            raise ValueError("BRAVE_API_KEY is not set")
        self.store = store
        self.min_interval = 1.0 / max_rps if max_rps > 0 else 0
        self.ttl = cache_ttl_hours * 3600
        self._last = 0.0
        self.news_supported = True  # flips off if the plan rejects the News endpoint
        self.unavailable_until = 0.0  # monotonic deadline; set when Brave refuses service
        self.unavailable_reason = ""
        self.http = httpx.Client(
            timeout=10,
            transport=transport,
            headers={"Accept": "application/json", "X-Subscription-Token": api_key},
        )

    def _throttle(self) -> None:
        wait = self._last + self.min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def _mark_unavailable(self, reason: str):
        self.unavailable_until = time.monotonic() + UNAVAILABLE_S
        self.unavailable_reason = reason
        raise BraveUnavailable(f"Brave {reason}")

    @property
    def available(self) -> bool:
        return time.monotonic() >= self.unavailable_until

    def search(
        self, query: str, *, news: bool = False, count: int = 10, freshness: str | None = "py", country: str = "ALL"
    ) -> list[dict]:
        """freshness: pd (day) | pw (week) | pm (month) | py (year) | None (any time)."""
        q = sanitize_query(query)
        news = news and self.news_supported
        params = {"q": q, "count": count, "country": country}
        if freshness:
            params["freshness"] = freshness
        key = hashlib.sha256(json.dumps([news, params], sort_keys=True).encode()).hexdigest()
        cached = self.store.cache_get(key, self.ttl)
        if cached is None:
            if time.monotonic() < self.unavailable_until:
                raise BraveUnavailable(f"Brave unavailable (cached): {self.unavailable_reason}")
            self._throttle()
            try:
                r = self.http.get(BRAVE_NEWS if news else BRAVE_WEB, params=params)
            except httpx.HTTPError as e:
                self._mark_unavailable(f"network error: {e}")
            if news and r.status_code == 400 and "OPTION_NOT_IN_PLAN" in r.text:
                self.news_supported = False
                return self.search(query, news=False, count=count, freshness=freshness, country=country)
            if r.status_code in (401, 402, 403, 429) or r.status_code >= 500:
                self._mark_unavailable(f"HTTP {r.status_code}")
            r.raise_for_status()
            cached = r.json()
            if "web" not in cached and "results" not in cached and _monthly_remaining(r) == 0:
                self._mark_unavailable(
                    f"monthly quota exhausted (resets in {r.headers.get('x-ratelimit-reset', '?')} s)"
                )
            self.store.cache_put(key, cached)
        results = cached.get("results") if news else (cached.get("web") or {}).get("results")
        return [
            {"title": x.get("title", ""), "url": x.get("url", ""), "description": x.get("description", ""), "query": q}
            for x in (results or [])
            if x.get("url", "").startswith("https://")
        ]


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def html_to_text(html: str, limit: int = 20_000) -> str:
    p = _TextExtractor()
    p.feed(html)
    return " ".join(p.parts)[:limit]


def fetch_page(url: str, *, transport: httpx.BaseTransport | None = None, max_bytes: int = 2_000_000,
               host_ok=None, deadline: float = 20) -> str:
    """Fetch one public page as text. SSRF-safe (see tools/safefetch.py): every redirect hop re-checked,
    connection pinned to the validated public IP, 2 MB cap, total deadline."""
    from .safefetch import FetchError, SafeFetcher

    with SafeFetcher(transport, host_ok, page_deadline=deadline, max_bytes=max_bytes) as f:
        _, r = f.get(url)
    if r.status_code >= 400:
        raise FetchError(f"{url}: HTTP {r.status_code}")
    if "html" not in r.headers.get("content-type", "text/html"):
        return r.text[:20_000]
    return html_to_text(r.text)
