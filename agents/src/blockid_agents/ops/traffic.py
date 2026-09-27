"""nginx access-log parser -> studio.ops_traffic_daily (docs/PLAN-OPS.md §3).

How the logs reach the API container: docker-compose mounts the host's /var/log/nginx read-only at
/host-logs/nginx in `agents-api` and adds the container user to group `adm` (gid 4, owner group of the live
logs, mode 0640). Host logrotate keeps 14 days (daily, compressed from .2 on). Every OPS_TRAFFIC_PARSE_SECONDS
(1 h) the monitor leader re-reads `<host>.access.log`, `.1` and `.2.gz` for each host and recomputes every day
they contain; a day's row is replaced only when the new parse saw at least as many requests (so a day that is
partly rotated away keeps its complete earlier numbers).

Privacy: raw IPs are never stored or logged. A visitor is HMAC(daily salt, ip + user agent) held in memory
during one parse; the salt is derived from OPS_IP_SALT_SECRET and the UTC date, so hashes cannot be joined across
days. Paths are normalised (query string dropped, id-like segments masked) and referrers reduced to their host.

Format: nginx "combined". An optional extra quoted field after the user agent is read as the Cloudflare country
(`log_format blockid_ops '$remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent
"$http_referer" "$http_user_agent" "$http_cf_ipcountry"';`). Days are UTC.
"""
from __future__ import annotations

import gzip
import hashlib
import hmac
import logging
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Iterator
from urllib.parse import urlparse

log = logging.getLogger(__name__)

LINE = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] "(?P<req>[^"]*)" (?P<status>\d{3}) (?P<bytes>\S+) '
    r'"(?P<ref>[^"]*)" "(?P<ua>[^"]*)"(?: "(?P<cc>[^"]*)")?')
BOT_UA = re.compile(
    r"bot|crawl|spider|slurp|scrap|curl|wget|python|httpx|aiohttp|go-http|java/|okhttp|axios|node-fetch|undici|"
    r"libwww|headless|lighthouse|pagespeed|monitor|uptime|pingdom|statuscake|zgrab|masscan|nmap|nuclei|censys|"
    r"facebookexternalhit|preview|embedly|feedfetcher|whatsapp|telegram|discord|slack|expanse|palo alto|"
    r"playwright|puppeteer|phantom|selenium", re.I)
PROBE_PATH = re.compile(r"\.(php|asp|aspx|jsp|cgi|env|git|ini|sql|bak|yml|yaml|conf)(\b|$)|^/(\.|wp-|wordpress|"
                        r"cgi-bin|phpmyadmin|vendor/|boaform|HNAP1|owa|ecp|console|actuator|solr|autodiscover|remote/|"
                        r"manager/|druid|geoserver|feed/|xmlrpc|telescope|debug|server-status|login\.action|confluence|\+CSCOE\+|webui|evox|dniapi|cf_scripts)", re.I)
ASSET = re.compile(r"^/(assets|_next|static|fonts|images|img|favicon)|\.(js|mjs|css|map|png|jpe?g|gif|svg|ico|webp|"
                   r"avif|woff2?|ttf|otf|json|txt|xml|webmanifest|mp4|webm|pdf|wasm)$", re.I)
NON_PAGE = re.compile(r"^/(api|rpc|healthz|explorer/api|socket|ws)(/|$)", re.I)
ID_SEG = re.compile(r"^(0x[0-9a-fA-F]{6,}|[0-9a-fA-F]{12,}|[A-Za-z0-9_-]{20,}|\d{3,})$")
TIME_FMT = "%d/%b/%Y:%H:%M:%S %z"


@dataclass
class Hit:
    ip: str
    at: datetime
    method: str
    path: str
    status: int
    referrer: str
    ua: str
    country: str | None


def parse_line(line: str) -> Hit | None:
    m = LINE.match(line)
    if not m:
        return None
    try:
        at = datetime.strptime(m["time"], TIME_FMT).astimezone(timezone.utc)
    except ValueError:
        return None
    parts = m["req"].split(" ")
    method, path = (parts[0], parts[1]) if len(parts) >= 2 else ("-", "-")
    cc = (m["cc"] or "").strip().upper()
    return Hit(ip=m["ip"], at=at, method=method, path=path, status=int(m["status"]), referrer=m["ref"],
               ua=m["ua"], country=cc if re.fullmatch(r"[A-Z]{2}", cc) and cc != "XX" else None)


def is_bot(h: Hit) -> bool:
    return (not h.ua or h.ua == "-" or bool(BOT_UA.search(h.ua)) or bool(PROBE_PATH.search(h.path))
            or h.method not in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"))


def normalise_path(path: str) -> str:
    p = path.split("?", 1)[0].split("#", 1)[0] or "/"
    segs = ["{id}" if ID_SEG.match(s) else s for s in p.split("/")]
    out = "/".join(segs)[:120]
    return out or "/"


def is_page_view(h: Hit) -> bool:
    p = h.path.split("?", 1)[0]
    return (h.method == "GET" and 200 <= h.status < 400 and not NON_PAGE.match(p) and not ASSET.search(p))


def referrer_host(ref: str, own: Iterable[str]) -> str | None:
    if not ref or ref == "-":
        return None
    host = (urlparse(ref).hostname or "").lower()
    if not host or host in own:
        return None
    return host[4:] if host.startswith("www.") else host


def day_salt(secret: str, day: date) -> bytes:
    return hmac.new(secret.encode(), f"ops-visitor:{day.isoformat()}".encode(), hashlib.sha256).digest()


def visitor_hash(salt: bytes, ip: str, ua: str) -> str:
    return hmac.new(salt, f"{ip}|{ua}".encode(), hashlib.sha256).hexdigest()[:16]


@dataclass
class DayAgg:
    page_views: int = 0
    requests: int = 0
    bot_requests: int = 0
    api_requests: int = 0
    status_4xx: int = 0
    status_5xx: int = 0
    visitors: set = field(default_factory=set)
    pages: Counter = field(default_factory=Counter)
    referrers: Counter = field(default_factory=Counter)
    countries: Counter = field(default_factory=Counter)

    def row(self) -> dict:
        return {"page_views": self.page_views, "unique_visitors": len(self.visitors), "requests": self.requests,
                "bot_requests": self.bot_requests, "api_requests": self.api_requests,
                "status_4xx": self.status_4xx, "status_5xx": self.status_5xx,
                "top_pages": [{"path": p, "views": n} for p, n in self.pages.most_common(20)],
                "top_referrers": [{"referrer": r, "count": n} for r, n in self.referrers.most_common(20)],
                "countries": [{"country": c, "count": n} for c, n in self.countries.most_common(30)]}


def aggregate(lines: Iterable[str], secret: str, own_hosts: Iterable[str] = ()) -> dict[date, dict]:
    """{utc_day: row dict} for one host's lines. Hashes live only inside this call."""
    own = {h.lower() for h in own_hosts}
    days: dict[date, DayAgg] = {}
    salts: dict[date, bytes] = {}
    for line in lines:
        h = parse_line(line)
        if h is None:
            continue
        d = h.at.date()
        a = days.setdefault(d, DayAgg())
        a.requests += 1
        if 400 <= h.status < 500:
            a.status_4xx += 1
        elif h.status >= 500:
            a.status_5xx += 1
        if h.path.startswith("/api/"):
            a.api_requests += 1
        if is_bot(h):
            a.bot_requests += 1
            continue
        salt = salts.get(d) or salts.setdefault(d, day_salt(secret, d))
        a.visitors.add(visitor_hash(salt, h.ip, h.ua))
        if h.country:
            a.countries[h.country] += 1
        if is_page_view(h):
            a.page_views += 1
            a.pages[normalise_path(h.path)] += 1
            r = referrer_host(h.referrer, own)
            if r:
                a.referrers[r] += 1
    return {d: a.row() for d, a in days.items()}


# ------------------------------------------------------------------ files
def _open(path: str):
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, encoding="utf-8", errors="replace")


def host_files(log_dir: str, host: str) -> list[str]:
    base = os.path.join(log_dir, f"{host}.access.log")
    return [p for p in (base + ".2.gz", base + ".1", base) if os.path.exists(p)]


def read_lines(paths: list[str]) -> Iterator[str]:
    for p in paths:
        try:
            with _open(p) as f:
                yield from f
        except OSError as e:
            log.warning("cannot read %s: %s", p, e)


def logs_readable(log_dir: str, hosts: Iterable[str]) -> tuple[bool, str]:
    if not os.path.isdir(log_dir):
        return False, f"{log_dir} is not mounted"
    for h in hosts:
        p = os.path.join(log_dir, f"{h}.access.log")
        if os.path.exists(p):
            if not os.access(p, os.R_OK):
                return False, f"{p} is not readable (container user needs group adm)"
            return True, "ok"
    return False, f"no <host>.access.log in {log_dir}"


def tail_lines(path: str, max_bytes: int = 1_000_000) -> list[str]:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - max_bytes))
            data = f.read()
    except OSError:
        return []
    lines = data.decode("utf-8", "replace").splitlines()
    return lines[1:] if size > max_bytes else lines


def recent_status(path: str, since: datetime, prefix: str = "/api/") -> dict:
    """Requests under `prefix` since `since` in the tail of one access log: {"total", "5xx", "codes"}."""
    total, bad, codes = 0, 0, Counter()
    for line in tail_lines(path):
        h = parse_line(line)
        if h is None or h.at < since or not h.path.startswith(prefix):
            continue
        total += 1
        if h.status >= 500:
            bad += 1
            codes[str(h.status)] += 1
    return {"total": total, "5xx": bad, "codes": dict(codes)}


# ------------------------------------------------------------------ store
class TrafficStore:
    def __init__(self, db):
        self.db = db

    def upsert(self, host: str, day: date, row: dict) -> bool:
        from psycopg.types.json import Jsonb

        n = self.db.exec(
            "INSERT INTO studio.ops_traffic_daily (day,host,page_views,unique_visitors,requests,bot_requests,"
            "api_requests,status_4xx,status_5xx,top_pages,top_referrers,countries,updated_at) VALUES "
            "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now()) ON CONFLICT (day,host) DO UPDATE SET "
            "page_views=EXCLUDED.page_views, unique_visitors=EXCLUDED.unique_visitors, requests=EXCLUDED.requests, "
            "bot_requests=EXCLUDED.bot_requests, api_requests=EXCLUDED.api_requests, status_4xx=EXCLUDED.status_4xx, "
            "status_5xx=EXCLUDED.status_5xx, top_pages=EXCLUDED.top_pages, top_referrers=EXCLUDED.top_referrers, "
            "countries=EXCLUDED.countries, updated_at=now() "
            "WHERE EXCLUDED.requests >= studio.ops_traffic_daily.requests",
            (day, host, row["page_views"], row["unique_visitors"], row["requests"], row["bot_requests"],
             row["api_requests"], row["status_4xx"], row["status_5xx"], Jsonb(row["top_pages"]),
             Jsonb(row["top_referrers"]), Jsonb(row["countries"])))
        return n > 0

    def parse_all(self, log_dir: str, hosts: Iterable[str], secret: str) -> dict:
        hosts = list(hosts)
        out: dict = {"hosts": {}, "at": datetime.now(timezone.utc).isoformat()}
        for host in hosts:
            files = host_files(log_dir, host)
            if not files:
                out["hosts"][host] = {"files": 0, "days": 0}
                continue
            days = aggregate(read_lines(files), secret, own_hosts=hosts)
            written = sum(self.upsert(host, d, row) for d, row in days.items())
            out["hosts"][host] = {"files": len(files), "days": len(days), "written": written}
        return out

    def daily(self, days: int) -> list[dict]:
        since = (datetime.now(timezone.utc) - timedelta(days=days - 1)).date()
        return self.db.all("SELECT * FROM studio.ops_traffic_daily WHERE day >= %s ORDER BY day, host", (since,))

    def totals(self, start: date, end: date) -> dict:
        """Sums over [start, end) (days), all hosts and per host."""
        rows = self.db.all(
            "SELECT host, sum(page_views)::int AS page_views, sum(unique_visitors)::int AS unique_visitors, "
            "sum(requests)::int AS requests, sum(bot_requests)::int AS bot_requests, "
            "sum(status_5xx)::int AS status_5xx FROM studio.ops_traffic_daily WHERE day >= %s AND day < %s "
            "GROUP BY host ORDER BY host", (start, end))
        keys = ("page_views", "unique_visitors", "requests", "bot_requests", "status_5xx")
        total = {k: sum(int(r[k] or 0) for r in rows) for k in keys}
        return {"total": total, "hosts": {r["host"]: {k: int(r[k] or 0) for k in keys} for r in rows}}
