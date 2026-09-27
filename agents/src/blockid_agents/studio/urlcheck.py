"""Website link check that runs before a valuation is created (POST /v1/studio/check-url).

Catches the common mistakes early, while the person is still on the input: a typo'd or look-alike domain
(`xn--` / Unicode hosts), a host that does not exist, an IP address or local name, or a homepage that is gone.
Nothing here stores anything; the homepage is read once with the SSRF-safe fetcher (short timeout).

Result: {ok, url, title, reason, message, suggestion}. `reason` is a stable code the web app translates:
empty · spaces · bad_url · no_tld · ip · not_public · lookalike · dns · unreachable · http_error.
"""
from __future__ import annotations

import ipaddress
import re
import threading
import time
import unicodedata
from collections import defaultdict, deque
from collections.abc import Callable
from html import unescape
from urllib.parse import urlparse, urlunparse

from ..agents.site_intake import SiteError, normalize_url
from ..tools.safefetch import FetchError, SafeFetcher, resolve_public

CHECK_TIMEOUT_S = 6.0
CHECK_DEADLINE_S = 9.0

_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_TLD = re.compile(r"^(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})$")
_LOCAL_SUFFIX = (".local", ".internal", ".localhost", ".localdomain", ".lan", ".home.arpa", ".test", ".invalid",
                 ".example")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)

# Latin look-alikes (Cyrillic / Greek) that NFKD does not fold to ASCII.
_CONFUSABLE = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s",
    "һ": "h", "ԁ": "d", "ԛ": "q", "ԝ": "w", "ɡ": "g", "ⅼ": "l", "ӏ": "l", "ı": "i",
    "α": "a", "ο": "o", "ν": "v", "ρ": "p", "τ": "t", "κ": "k", "ι": "i", "υ": "u",
})

MESSAGES = {
    "empty": "Enter the business's website address.",
    "spaces": "A website address cannot contain spaces.",
    "bad_url": "This is not a website address. Try something like example.com.au.",
    "no_tld": "The address needs a domain ending, like .com or .com.au.",
    "ip": "Use the business's domain name, not an IP address.",
    "not_public": "This address is not a public website.",
    "lookalike": "This address uses look-alike letters.",
    "dns": "We couldn't find this website. Check the spelling.",
    "unreachable": "We couldn't open this website. Check the address or try again later.",
    "http_error": "The website answered with an error page.",
}


class CheckFailed(Exception):
    def __init__(self, reason: str, suggestion: str | None = None, detail: str = ""):
        super().__init__(reason)
        self.reason, self.suggestion, self.detail = reason, suggestion, detail


def ascii_guess(unicode_host: str) -> str:
    """Best ASCII reading of a Unicode host: fold accents (NFKD) and Cyrillic/Greek look-alikes, drop the rest."""
    s = unicodedata.normalize("NFKD", unicode_host.lower().translate(_CONFUSABLE))
    return "".join(ch for ch in s if ch.isascii() and (ch.isalnum() or ch in ".-"))


def _unicode_host(host: str) -> str:
    out = []
    for label in host.split("."):
        if label.startswith("xn--"):
            try:
                out.append(label.encode("ascii").decode("idna"))
            except (UnicodeError, ValueError):
                out.append(label)
        else:
            out.append(label)
    return ".".join(out)


def _with_host(url: str, host: str) -> str:
    p = urlparse(url)
    netloc = host + (f":{p.port}" if p.port else "")
    return urlunparse((p.scheme, netloc, p.path or "/", "", "", ""))


def normalise(raw: str) -> str:
    """Syntax-only checks (no network). Returns the normalised URL or raises CheckFailed."""
    raw = (raw or "").strip()
    if not raw:
        raise CheckFailed("empty")
    if re.search(r"\s", raw):
        raise CheckFailed("spaces")
    try:
        url = normalize_url(raw)
    except SiteError:
        # normalize_url refuses hosts without a dot; tell "localhost" apart from plain garbage
        host = (urlparse(raw if "://" in raw else "https://" + raw).hostname or "").lower()
        if host == "localhost":
            raise CheckFailed("not_public") from None
        try:
            ipaddress.ip_address(host.strip("[]"))
            raise CheckFailed("ip") from None
        except ValueError:
            pass
        if host and re.fullmatch(r"[a-z0-9-]+", host):
            raise CheckFailed("no_tld") from None
        raise CheckFailed("bad_url") from None
    p = urlparse(url)
    host = (p.hostname or "").rstrip(".")
    try:
        ipaddress.ip_address(host.strip("[]"))
        raise CheckFailed("ip")
    except ValueError:
        pass
    if host == "localhost" or host.endswith(_LOCAL_SUFFIX):
        raise CheckFailed("not_public")
    if not host.isascii():  # typed with Unicode letters: same treatment as its xn-- form
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            raise CheckFailed("bad_url") from None
    labels = host.split(".")
    if any(label.startswith("xn--") for label in labels):
        guess = ascii_guess(_unicode_host(host))
        ok_guess = guess and "." in guess and all(_LABEL.match(x) for x in guess.split(".")) and guess != host
        raise CheckFailed("lookalike", _with_host(url, guess) if ok_guess else None, _unicode_host(host))
    if len(labels) < 2 or not all(_LABEL.match(x) for x in labels):
        raise CheckFailed("bad_url")
    if not _TLD.match(labels[-1]):
        raise CheckFailed("no_tld")
    return _with_host(url, host)


def page_title(html: str) -> str:
    m = _TITLE.search(html or "")
    return re.sub(r"\s+", " ", unescape(m.group(1))).strip()[:160] if m else ""


def check_url(raw: str, *, resolve: Callable[[str], list[str]] = resolve_public,
              fetcher: Callable[[], SafeFetcher] | None = None) -> dict:
    """Full check: syntax, DNS, homepage. Never raises; returns the result dict."""
    try:
        url = normalise(raw)
        host = urlparse(url).hostname or ""
        try:
            resolve(host)
        except FetchError as e:
            raise CheckFailed("not_public" if "not a public" in str(e) else "dns", detail=str(e)) from None
        make = fetcher or (lambda: SafeFetcher(timeout=CHECK_TIMEOUT_S, page_deadline=CHECK_DEADLINE_S,
                                               max_bytes=300_000))
        try:
            with make() as f:
                final, page = f.get(url)
        except FetchError as e:
            raise CheckFailed("unreachable", detail=str(e)[:200]) from None
        # bot walls (401/403/429/503) still prove the site exists; the valuation reports what it could read
        if page.status_code >= 400 and page.status_code not in (401, 403, 429, 503):
            raise CheckFailed("http_error", detail=f"HTTP {page.status_code}")
        final_url = final
        try:
            final_url = normalize_url(final)
        except SiteError:
            pass
        return {"ok": True, "url": final_url, "title": page_title(page.text), "reason": None, "message": None,
                "suggestion": None}
    except CheckFailed as e:
        msg = MESSAGES.get(e.reason, e.reason)
        if e.suggestion:
            msg += f" Did you mean {urlparse(e.suggestion).hostname}?"
        return {"ok": False, "url": None, "title": None, "reason": e.reason, "message": msg,
                "suggestion": e.suggestion, "detail": e.detail or None}


class RateLimiter:
    """At most `limit` calls per key (client IP) within `window_s` (in-memory, per process)."""

    def __init__(self, limit: int = 20, window_s: int = 60):
        self.limit, self.window = limit, window_s
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            if len(self._hits) > 10_000:  # bound memory: drop idle keys
                for k in [k for k, v in self._hits.items() if not v]:
                    del self._hits[k]
            return True
