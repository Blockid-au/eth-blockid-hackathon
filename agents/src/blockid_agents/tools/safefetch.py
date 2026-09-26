"""SSRF-safe HTTP GET for everything the agents read from the internet.

* Every hop (including each redirect, followed manually) must resolve ONLY to public unicast addresses:
  loopback, RFC1918, link-local (169.254.169.254 metadata), CGNAT, ULA, multicast, reserved and docker service
  names (single-label hosts such as `issuer`, `postgres`, `evmd`) are refused. Raw IP URLs are refused.
* DNS-rebinding safe: the connection goes to the IP that was validated (URL host replaced by the IP, original
  Host header kept, TLS SNI + certificate check against the original hostname), and the peer address reported
  by the socket is re-checked after connecting.
* Streamed body with a hard byte cap and a total per-page deadline (connect + redirects + body).
"""
from __future__ import annotations

import ipaddress
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

import httpx

UA = "BlockID-Research/1.0 (+https://eth.blockid.au)"
MAX_BYTES = 2_000_000
PAGE_DEADLINE_S = 20.0


class FetchError(RuntimeError):
    pass


def _ip_ok(addr: str) -> bool:
    ip = ipaddress.ip_address(addr.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not (ip.is_multicast or ip.is_reserved or ip.is_loopback or ip.is_link_local
                                 or ip.is_private or ip.is_unspecified)


def resolve_public(host: str) -> list[str]:
    """Validated addresses for `host`; raises FetchError unless it is a public DNS name with only public IPs."""
    host = (host or "").strip().rstrip(".").lower()
    try:
        ipaddress.ip_address(host.strip("[]"))
        raise FetchError(f"raw IP address {host!r} not allowed")
    except ValueError:
        pass
    if "." not in host or host.endswith((".local", ".internal", ".localhost", ".localdomain", ".lan", ".home.arpa")):
        raise FetchError(f"host {host!r} is not a public internet host")
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as e:
        raise FetchError(f"host {host!r} does not resolve") from e
    addrs = list(dict.fromkeys(i[4][0] for i in infos))
    if not addrs or not all(_ip_ok(a) for a in addrs):
        raise FetchError(f"host {host!r} is not a public internet host")
    return addrs


def public_host(host: str) -> bool:
    try:
        resolve_public(host)
        return True
    except FetchError:
        return False


@dataclass
class Fetched:
    url: str
    status_code: int
    headers: httpx.Headers
    content: bytes
    encoding: str | None

    @property
    def text(self) -> str:
        try:
            return self.content.decode(self.encoding or "utf-8", errors="ignore")
        except LookupError:  # bogus charset header
            return self.content.decode("utf-8", errors="ignore")


class SafeFetcher:
    """`host_ok` is a TEST hook: when given, hosts are checked with it and connections are not IP-pinned
    (MockTransport routes by hostname). Production leaves it None -> resolve_public + IP pinning."""

    def __init__(self, transport: httpx.BaseTransport | None = None, host_ok: Callable[[str], bool] | None = None,
                 *, timeout: float = 10, page_deadline: float = PAGE_DEADLINE_S, max_bytes: int = MAX_BYTES,
                 user_agent: str = UA):
        self.host_ok, self.timeout, self.page_deadline, self.max_bytes = host_ok, timeout, page_deadline, max_bytes
        self.client = httpx.Client(follow_redirects=False, transport=transport, trust_env=False,
                                   headers={"User-Agent": user_agent,
                                            "Accept": "text/html,application/xhtml+xml,*/*;q=0.5"})

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> SafeFetcher:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _request(self, url: str, timeout: float) -> httpx.Request:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
            raise FetchError(f"refusing to fetch {url!r}")
        t = httpx.Timeout(timeout)
        if self.host_ok is not None:  # test mode
            if not self.host_ok(p.hostname):
                raise FetchError(f"host {p.hostname!r} is not a public internet host")
            return self.client.build_request("GET", url, timeout=t)
        ip = resolve_public(p.hostname)[0]
        ip_host = f"[{ip}]" if ":" in ip else ip
        netloc = ip_host + (f":{p.port}" if p.port else "")
        pinned = urlunparse((p.scheme, netloc, p.path or "/", "", p.query, ""))
        ext = {"sni_hostname": p.hostname} if p.scheme == "https" else {}
        return self.client.build_request("GET", pinned, headers={"Host": p.netloc.rsplit("@", 1)[-1]},
                                         extensions=ext, timeout=t)

    def get(self, url: str, max_redirects: int = 5) -> tuple[str, Fetched]:
        deadline = time.monotonic() + self.page_deadline
        url = urldefrag(url)[0]
        for _ in range(max_redirects + 1):
            left = deadline - time.monotonic()
            if left <= 0:
                raise FetchError(f"deadline exceeded fetching {url}")
            req = self._request(url, min(self.timeout, left))
            try:
                r = self.client.send(req, stream=True)
            except httpx.HTTPError as e:
                raise FetchError(f"{url}: {type(e).__name__}: {e}") from e
            try:
                self._check_peer(r)
                if r.is_redirect and r.headers.get("location"):
                    url = urldefrag(urljoin(url, r.headers["location"]))[0]
                    continue
                body = b""
                for chunk in r.iter_bytes():
                    body += chunk
                    if len(body) >= self.max_bytes:
                        break
                    if time.monotonic() > deadline:
                        raise FetchError(f"deadline exceeded reading {url}")
                return url, Fetched(url, r.status_code, r.headers, body[: self.max_bytes], r.encoding)
            finally:
                r.close()
        raise FetchError("too many redirects")

    def _check_peer(self, r: httpx.Response) -> None:
        if self.host_ok is not None:
            return
        stream = r.extensions.get("network_stream")
        addr = stream.get_extra_info("server_addr") if stream is not None else None
        if addr and not _ip_ok(str(addr[0])):
            raise FetchError(f"connected to non-public address {addr[0]}")
