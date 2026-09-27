"""Structured logs and error capture (docs/PLAN-OPS.md §2).

* `JsonFormatter`: one JSON object per line {"ts","level","logger","msg","source","request_id",...,"exc"}; enabled for
  api / worker / issuer by `configure_logging(source)` (LOG_FORMAT=json, the default in containers; LOG_FORMAT=text
  keeps the classic format). Docker keeps them (json-file driver, rotated 20 MB x 10, see docker-compose.yml).
* `ErrorStore` + `DbErrorHandler`: every ERROR+ record goes to studio.ops_errors with its traceback, deduplicated by a
  fingerprint (source + logger + exception type + stack frames, or the message with numbers / hex masked) and counted.
  A background thread batches writes (never blocks the caller, drops records when its queue is full) and deletes
  rows not seen for OPS_ERROR_RETENTION_DAYS (30).
* `install_access_log(app)`: X-Request-ID on every response (incoming value kept when it looks sane), one
  "blockid.access" line per request: method, route template, status, latency_ms, user (HMAC of the session actor,
  never the address itself).
"""
from __future__ import annotations

import contextvars
import hashlib
import hmac
import json
import logging
import os
import queue
import re
import threading
import time
import traceback as tb
import uuid
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

REQUEST_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("ops_request_id", default=None)
ROUTE: contextvars.ContextVar[str | None] = contextvars.ContextVar("ops_route", default=None)
_USER_SLOT: contextvars.ContextVar[dict | None] = contextvars.ContextVar("ops_user_slot", default=None)
_RID_OK = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_SOURCE = {"name": os.environ.get("OPS_SOURCE", "api")}

# loggers whose errors must not be stored (they would recurse: the store itself / the DB driver it uses)
_SKIP_LOGGERS = ("blockid_agents.ops.errors", "psycopg", "psycopg_pool")


def user_hash(actor: str | None) -> str | None:
    if not actor:
        return None
    secret = (os.environ.get("OPS_IP_SALT_SECRET") or os.environ.get("SESSION_SECRET") or "blockid-ops").encode()
    return hmac.new(secret, actor.strip().lower().encode(), hashlib.sha256).hexdigest()[:12]


def note_user(actor: str | None) -> None:
    """Called when a request's session is resolved; the access log line carries the hash (best effort)."""
    slot = _USER_SLOT.get()
    if slot is not None and actor:
        slot["user"] = user_hash(actor)


# ------------------------------------------------------------------ JSON logs
class JsonFormatter(logging.Formatter):
    _STD = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname, "logger": record.name, "msg": record.getMessage(),
            "source": _SOURCE["name"],
        }
        rid = getattr(record, "request_id", None) or REQUEST_ID.get()
        if rid:
            out["request_id"] = rid
        for k, v in record.__dict__.items():
            if k not in self._STD and not k.startswith("_") and k != "request_id":
                out[k] = v
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str, ensure_ascii=False)


def configure_logging(source: str, level: str | None = None) -> None:
    """Root logging for a process (api | worker | issuer): JSON lines unless LOG_FORMAT=text."""
    _SOURCE["name"] = source
    root = logging.getLogger()
    root.setLevel(level or os.environ.get("LOG_LEVEL", "INFO"))
    handler = logging.StreamHandler()
    if os.environ.get("LOG_FORMAT", "json").lower() == "text":
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    else:
        handler.setFormatter(JsonFormatter())
    for h in list(root.handlers):
        if isinstance(h, logging.StreamHandler) and not isinstance(h, DbErrorHandler):
            root.removeHandler(h)
    root.addHandler(handler)


# ------------------------------------------------------------------ error store
_NUM = re.compile(r"0x[0-9a-fA-F]+|\b[0-9a-f]{12,}\b|\d+")


def fingerprint(source: str, logger: str, message: str, exc_type: str | None, frames: list[str]) -> str:
    basis = [source, logger, exc_type or ""]
    basis += frames[-6:] if frames else [_NUM.sub("#", message)[:200]]
    return hashlib.sha1("|".join(basis).encode()).hexdigest()[:20]


def record_to_row(record: logging.LogRecord, source: str) -> dict:
    message = record.getMessage()[:2000]
    exc_type, frames, text = None, [], None
    if record.exc_info and record.exc_info[0] is not None:
        et, ev, etb = record.exc_info
        exc_type = et.__name__
        frames = [f"{os.path.basename(f.filename)}:{f.name}" for f in tb.extract_tb(etb)]
        text = "".join(tb.format_exception(et, ev, etb))[-8000:]
        if ev is not None and str(ev) and str(ev) not in message:
            message = f"{message}: {exc_type}: {ev}"[:2000]
    elif record.exc_text:
        text = record.exc_text[-8000:]
    return {"fingerprint": fingerprint(source, record.name, message, exc_type, frames), "source": source,
            "logger": record.name[:200], "level": record.levelname, "message": message, "traceback": text,
            "at": datetime.fromtimestamp(record.created, timezone.utc),
            "request_id": getattr(record, "request_id", None) or REQUEST_ID.get(), "route": ROUTE.get(), "count": 1}


def merge_rows(rows: list[dict]) -> list[dict]:
    """Collapse rows with the same fingerprint (count summed, latest message / time kept)."""
    out: dict[str, dict] = {}
    for r in rows:
        cur = out.get(r["fingerprint"])
        if cur is None:
            out[r["fingerprint"]] = dict(r)
        else:
            cur["count"] += r["count"]
            if r["at"] >= cur["at"]:
                cur.update({k: r[k] for k in ("message", "at", "request_id", "route")})
                cur["traceback"] = r["traceback"] or cur["traceback"]
    return list(out.values())


class ErrorStore:
    """Writes error rows to studio.ops_errors. `db` is a studio.db.Studio (or anything with exec/tx)."""

    UPSERT = ("INSERT INTO studio.ops_errors (fingerprint,source,logger,level,message,traceback,count,first_seen,"
              "last_seen,request_id,route) VALUES (%(fingerprint)s,%(source)s,%(logger)s,%(level)s,%(message)s,"
              "%(traceback)s,%(count)s,%(at)s,%(at)s,%(request_id)s,%(route)s) ON CONFLICT (fingerprint) DO UPDATE SET "
              "count = studio.ops_errors.count + EXCLUDED.count, last_seen = GREATEST(studio.ops_errors.last_seen, "
              "EXCLUDED.last_seen), message = EXCLUDED.message, level = EXCLUDED.level, "
              "traceback = COALESCE(EXCLUDED.traceback, studio.ops_errors.traceback), "
              "request_id = COALESCE(EXCLUDED.request_id, studio.ops_errors.request_id), "
              "route = COALESCE(EXCLUDED.route, studio.ops_errors.route)")

    def __init__(self, db):
        self.db = db

    def write(self, rows: list[dict]) -> None:
        if not rows:
            return
        with self.db.tx() as c:
            for r in merge_rows(rows):
                c.execute(self.UPSERT, r)

    def purge(self, days: int = 30) -> int:
        return self.db.exec("DELETE FROM studio.ops_errors WHERE last_seen < now() - make_interval(days => %s)",
                            (int(days),))


class DbErrorHandler(logging.Handler):
    """ERROR+ -> queue -> background writer thread -> ErrorStore. Never raises, never blocks."""

    def __init__(self, store: ErrorStore, source: str, flush_s: float = 2.0, maxsize: int = 1000):
        super().__init__(level=logging.ERROR)
        self.store, self.source, self.flush_s = store, source, flush_s
        self.q: queue.Queue = queue.Queue(maxsize=maxsize)
        self.dropped = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="ops-errors", daemon=True)
        self._thread.start()

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(_SKIP_LOGGERS):
            return
        try:
            self.q.put_nowait(record_to_row(record, self.source))
        except queue.Full:
            self.dropped += 1
        except Exception:  # noqa: BLE001 - a logging handler must never raise
            self.dropped += 1

    def drain(self) -> list[dict]:
        rows = []
        while True:
            try:
                rows.append(self.q.get_nowait())
            except queue.Empty:
                return rows

    def flush_now(self) -> None:
        rows = self.drain()
        if rows:
            try:
                self.store.write(rows)
            except Exception as e:  # noqa: BLE001 - DB down: keep the stderr log, drop the rows
                logging.getLogger("blockid_agents.ops.errors").warning("ops_errors write failed: %s", e)

    def _run(self) -> None:
        while not self._stop.wait(self.flush_s):
            self.flush_now()

    def close(self) -> None:
        self._stop.set()
        self.flush_now()
        super().close()


_INSTALLED: dict[str, DbErrorHandler] = {}


def install_error_capture(db, source: str) -> DbErrorHandler | None:
    """Attach the DB error handler to the root logger once per process. Returns it (None when db is None)."""
    if db is None:
        return None
    if source in _INSTALLED:
        return _INSTALLED[source]
    h = DbErrorHandler(ErrorStore(db), source)
    logging.getLogger().addHandler(h)
    _INSTALLED[source] = h
    return h


def install_error_capture_url(database_url: str, source: str) -> DbErrorHandler | None:
    """For the worker / issuer: small dedicated pool on DATABASE_URL (Postgres only)."""
    if not database_url.startswith("postgres"):
        return None
    try:
        from ..studio.db import Studio

        db = Studio(database_url, min_size=0, max_size=1)
        db.ensure_schema()
        return install_error_capture(db, source)
    except Exception as e:  # noqa: BLE001
        log.warning("error capture disabled: %s", e)
        return None


# ------------------------------------------------------------------ access log middleware
access_log = logging.getLogger("blockid.access")


def install_access_log(app) -> None:
    from starlette.requests import Request

    @app.middleware("http")
    async def request_log(request: Request, call_next):
        rid = request.headers.get("x-request-id") or ""
        if not _RID_OK.match(rid):
            rid = uuid.uuid4().hex[:16]
        t_rid, t_route = REQUEST_ID.set(rid), ROUTE.set(f"{request.method} {request.url.path}"[:200])
        slot: dict = {}
        t_user = _USER_SLOT.set(slot)
        t0 = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            route = request.scope.get("route")
            path_t = getattr(route, "path", None) or "<unmatched>"
            if request.url.path != "/healthz":
                access_log.info("%s %s %s", request.method, path_t, status, extra={
                    "request_id": rid, "method": request.method, "route": path_t, "status": status,
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 1), "user": slot.get("user")})
            REQUEST_ID.reset(t_rid)
            ROUTE.reset(t_route)
            _USER_SLOT.reset(t_user)

