"""Authentication for the Issuance Studio.

* SIWE (EIP-4361): GET nonce -> wallet signs the message -> POST message+signature. The nonce is
  single-use and valid for 10 minutes; the signature is recovered with eth_account (EIP-191).
* Password login for the seeded admin (bcrypt), 5 failures / 15 min per client IP -> 429.
* Sessions: random id in the `bid_session` cookie; only an HMAC of it is stored in studio.sessions,
  so a database read does not yield usable cookies.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import bcrypt
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import to_checksum_address

COOKIE = "__Host-bid_session"  # __Host-: Secure, Path=/, no Domain (cannot be set by a subdomain)
NONCE_TTL_S = 600
SIWE_CHAINS = {262626, 560048}


class AuthError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


# ------------------------------------------------------------------ SIWE
_HEADER = re.compile(r"^(?P<domain>[^\s]+) wants you to sign in with your Ethereum account:$")
_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")
_FIELDS = {
    "URI": "uri", "Version": "version", "Chain ID": "chain_id", "Nonce": "nonce", "Issued At": "issued_at",
    "Expiration Time": "expiration_time", "Not Before": "not_before", "Request ID": "request_id",
}


@dataclass
class SiweMessage:
    domain: str
    address: str
    statement: str
    uri: str
    version: str
    chain_id: int
    nonce: str
    issued_at: str
    expiration_time: str | None = None
    not_before: str | None = None
    request_id: str | None = None


def parse_siwe(message: str) -> SiweMessage:
    lines = message.replace("\r\n", "\n").split("\n")
    if len(lines) < 7:
        raise AuthError(400, "malformed SIWE message")
    m = _HEADER.match(lines[0].strip())
    if not m:
        raise AuthError(400, "malformed SIWE header")
    address = lines[1].strip()
    if not _ADDR.match(address):
        raise AuthError(400, "malformed SIWE address")
    fields: dict[str, str] = {}
    statement_lines: list[str] = []
    for line in lines[2:]:
        if line.startswith("Resources:") or line.startswith("- "):
            continue
        key, sep, val = line.partition(": ")
        if sep and key in _FIELDS:
            fields[_FIELDS[key]] = val.strip()
        elif line.strip():
            statement_lines.append(line.strip())
    for req in ("uri", "version", "chain_id", "nonce", "issued_at"):
        if req not in fields:
            raise AuthError(400, f"SIWE message missing {req}")
    try:
        chain_id = int(fields.pop("chain_id"))
    except ValueError:
        raise AuthError(400, "bad SIWE chain id") from None
    return SiweMessage(domain=m["domain"], address=address, statement=" ".join(statement_lines),
                       chain_id=chain_id, **fields)


def _ts(s: str) -> datetime:
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise AuthError(400, f"bad SIWE timestamp {s!r}") from None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def allowed_domains(public_base_url: str) -> set[str]:
    host = urlparse(public_base_url).netloc or "eth.blockid.au"
    return {host, "eth.blockid.au"}


def domain_ok(domain: str, allowed: set[str], dev: bool = False) -> bool:
    if domain in allowed:
        return True
    host, _, port = domain.partition(":")
    return dev and host in ("localhost", "127.0.0.1") and (not port or port.isdigit())  # STUDIO_DEV=1 only


def verify_siwe(message: str, signature: str, allowed: set[str], at: datetime | None = None,
                dev: bool = False) -> SiweMessage:
    """Checks everything except nonce freshness (the caller consumes the nonce in the DB)."""
    msg = parse_siwe(message)
    at = at or datetime.now(timezone.utc)
    if not domain_ok(msg.domain, allowed, dev):
        raise AuthError(401, f"SIWE domain {msg.domain!r} not allowed")
    uri_host = urlparse(msg.uri).netloc
    if uri_host != msg.domain:
        raise AuthError(401, "SIWE URI does not match domain")
    if msg.version != "1":
        raise AuthError(401, "unsupported SIWE version")
    if msg.chain_id not in SIWE_CHAINS:
        raise AuthError(401, f"SIWE chain id {msg.chain_id} not accepted")
    if msg.expiration_time and _ts(msg.expiration_time) <= at:
        raise AuthError(401, "SIWE message expired")
    if msg.not_before and _ts(msg.not_before) > at:
        raise AuthError(401, "SIWE message not yet valid")
    if _ts(msg.issued_at) > at + timedelta(minutes=5):
        raise AuthError(401, "SIWE issued-at is in the future")
    try:
        recovered = Account.recover_message(encode_defunct(text=message), signature=signature)
    except Exception:
        raise AuthError(401, "invalid signature") from None
    if recovered.lower() != msg.address.lower():
        raise AuthError(401, "signature does not match address")
    msg.address = to_checksum_address(recovered)
    return msg


def new_nonce() -> str:
    return secrets.token_hex(12)  # 24 alphanumeric chars (EIP-4361 requires >= 8)


# ------------------------------------------------------------------ passwords
def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(12)).decode()


_DUMMY_HASH = bcrypt.hashpw(b"blockid-dummy-password", bcrypt.gensalt(12)).decode()


def check_password(pw: str, hashed: str | None) -> bool:
    """Constant-work check: an unknown user still costs one bcrypt verification (no username oracle)."""
    if not hashed:
        bcrypt.checkpw(pw.encode(), _DUMMY_HASH.encode())
        return False
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


class LoginThrottle:
    """At most `limit` failed logins per client IP within `window_s`."""

    def __init__(self, limit: int = 5, window_s: int = 900):
        self.limit, self.window = limit, window_s
        self._fails: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, ip: str, t: float) -> deque:
        q = self._fails[ip]
        while q and q[0] <= t - self.window:
            q.popleft()
        return q

    def blocked(self, ip: str) -> bool:
        with self._lock:
            return len(self._prune(ip, time.time())) >= self.limit

    def fail(self, ip: str) -> None:
        with self._lock:
            self._prune(ip, time.time()).append(time.time())

    def reset(self, ip: str) -> None:
        with self._lock:
            self._fails.pop(ip, None)


def password_locked() -> bool:
    """ADMIN_PASSWORD_LOCKED (default "1" on the public demo): password changes are refused and the seeded admin's
    must_change flag is ignored, so nobody holding the shared demo password can lock the others out."""
    return os.environ.get("ADMIN_PASSWORD_LOCKED", "1").strip().lower() not in ("0", "false", "no", "off", "")


# ------------------------------------------------------------------ sessions
@dataclass
class Session:
    role: str  # user | admin
    address: str | None = None
    username: str | None = None
    must_change: bool = False

    @property
    def actor(self) -> str:
        return self.address or self.username or "?"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def session_key(secret: str, sid: str) -> str:
    return hmac.new((secret or "blockid-dev-secret").encode(), sid.encode(), hashlib.sha256).hexdigest()


class Sessions:
    def __init__(self, db, secret: str, hours: int = 12):
        self.db, self.secret, self.hours = db, secret, hours

    def create(self, role: str, *, address: str | None = None, username: str | None = None) -> str:
        sid = secrets.token_urlsafe(32)
        self.db.exec(
            "INSERT INTO studio.sessions(id,address,username,role,expires_at) VALUES (%s,%s,%s,%s,now() + %s)",
            (session_key(self.secret, sid), address, username, role, timedelta(hours=self.hours)),
        )
        if secrets.randbelow(20) == 0:
            self.db.exec("DELETE FROM studio.sessions WHERE expires_at < now()")
        return sid

    def get(self, sid: str | None) -> Session | None:
        if not sid:
            return None
        row = self.db.one(
            "SELECT s.address, s.username, s.role, a.must_change FROM studio.sessions s "
            "LEFT JOIN studio.admin_users a ON a.username = s.username "
            "WHERE s.id=%s AND s.expires_at > now()",
            (session_key(self.secret, sid),),
        )
        if not row:
            return None
        return Session(role=row["role"], address=row["address"], username=row["username"],
                       must_change=bool(row["must_change"]) and not password_locked() if row["username"] else False)

    def delete(self, sid: str | None) -> None:
        if sid:
            self.db.exec("DELETE FROM studio.sessions WHERE id=%s", (session_key(self.secret, sid),))

    # nonces
    def issue_nonce(self) -> str:
        n = new_nonce()
        self.db.exec("DELETE FROM studio.nonces WHERE created_at < now() - interval '10 minutes'")
        self.db.exec("INSERT INTO studio.nonces(nonce) VALUES (%s)", (n,))
        return n

    def consume_nonce(self, nonce: str) -> bool:
        """Single use: the row is deleted whether or not it was still fresh."""
        row = self.db.one(
            "DELETE FROM studio.nonces WHERE nonce=%s RETURNING created_at > now() - interval '10 minutes' AS fresh",
            (nonce,),
        )
        return bool(row and row["fresh"])
