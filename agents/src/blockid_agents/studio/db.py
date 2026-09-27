"""Postgres access for the Issuance Studio (schema `studio`, see schema.sql).

One small pool per process. All helpers return plain dicts (psycopg dict_row), JSON columns come
back as Python objects. The valuation-progress helpers are used by the worker while a graph runs.
"""
from __future__ import annotations

import json
import logging
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

log = logging.getLogger(__name__)

SCHEMA_SQL = Path(__file__).with_name("schema.sql")

STEP_KEYS = ("read_site", "profile", "competitors", "market", "svi", "narrative")
ONCHAIN_STATUSES = ("issued", "pending_anchor", "anchoring", "anchored", "partially_anchored")


def now() -> datetime:
    return datetime.now(timezone.utc)


def initial_steps() -> list[dict]:
    from ..tools.valuation_params import v5_enabled

    keys = list(STEP_KEYS)
    if v5_enabled():  # evaluation v5 analysts (graph node `analysts`, before svi) + valuation v5 methods
        keys.insert(keys.index("svi"), "analysts")
        keys.insert(keys.index("narrative"), "valuation_methods")
    return [{"key": k, "status": "pending", "detail": "", "at": None} for k in keys]


def jsonable(v: Any) -> Any:
    """Decimal/datetime -> JSON-friendly values (FastAPI handles most, but result blobs need it)."""
    return json.loads(json.dumps(v, default=_default))


def _default(o: Any):
    from decimal import Decimal

    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    raise TypeError(f"not JSON serialisable: {type(o).__name__}")


class LimitError(Exception):
    pass


class Studio:
    def __init__(self, url: str, *, min_size: int = 1, max_size: int = 8):
        self.url = url
        self.pool = ConnectionPool(
            url, min_size=min_size, max_size=max_size, open=True,
            kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": None},
        )
        self._schema_ok = False

    def close(self) -> None:
        self.pool.close()

    # ------------------------------------------------------------------ basics
    def apply_schema(self) -> None:
        with self.pool.connection() as c:
            c.execute(SCHEMA_SQL.read_text())
        self._schema_ok = True

    def ensure_schema(self) -> None:
        if not self._schema_ok:
            self.apply_schema()

    @contextmanager
    def tx(self) -> Iterator[Any]:
        """A connection inside one transaction (commits on success)."""
        with self.pool.connection() as c:
            with c.transaction():
                yield c

    def all(self, sql: str, params: Any = None) -> list[dict]:
        with self.pool.connection() as c:
            return list(c.execute(sql, params).fetchall())

    def one(self, sql: str, params: Any = None) -> dict | None:
        with self.pool.connection() as c:
            return c.execute(sql, params).fetchone()

    def exec(self, sql: str, params: Any = None) -> int:
        with self.pool.connection() as c:
            return c.execute(sql, params).rowcount

    # ------------------------------------------------------------------ audit
    def audit(self, actor: str, action: str, target: str | None = None, **detail) -> None:
        self.exec(
            "INSERT INTO studio.audit(actor,action,target,detail) VALUES (%s,%s,%s,%s)",
            (actor, action, target, Jsonb(jsonable(detail))),
        )

    # ------------------------------------------------------------------ admin users
    def seed_admin(self, username: str, password_hash: str) -> None:
        if username and password_hash:
            self.exec(
                "INSERT INTO studio.admin_users(username,password_hash,must_change) VALUES (%s,%s,true) "
                "ON CONFLICT (username) DO NOTHING",
                (username, password_hash),
            )

    # ------------------------------------------------------------------ valuations
    def create_valuation(self, url: str, requested_by: str) -> str:
        vid = uuid.uuid4().hex[:16]
        self.exec(
            "INSERT INTO studio.valuations(id,url,requested_by,status,steps,result) VALUES (%s,%s,%s,'queued',%s,%s)",
            (vid, url, requested_by, Jsonb(initial_steps()),
             Jsonb({"counters": {"pages": 0, "competitors": 0, "sources": 0}})),
        )
        return vid

    def create_valuation_limited(self, url: str, requested_by: str, *, per_wallet: int | None,
                                 global_per_day: int | None, max_active: int | None,
                                 self_reported: dict | None = None) -> str:
        """Check the limits and insert in ONE transaction under an advisory lock, so concurrent requests
        cannot all pass the count. Raises LimitError(message)."""
        vid = uuid.uuid4().hex[:16]
        with self.tx() as c:
            c.execute("SELECT pg_advisory_xact_lock(hashtext('studio.valuations.create'))")
            n = c.execute(
                "SELECT count(*) FILTER (WHERE status IN ('queued','running')) AS active,"
                " count(*) FILTER (WHERE created_at > now() - interval '1 day') AS today,"
                " count(*) FILTER (WHERE created_at > now() - interval '1 day'"
                "                  AND lower(requested_by) = lower(%s)) AS mine "
                "FROM studio.valuations", (requested_by,)).fetchone()
            if max_active and n["active"] >= max_active:
                raise LimitError("busy, try later")
            if global_per_day and n["today"] >= global_per_day:
                raise LimitError("the platform's daily valuation limit is reached; try again tomorrow")
            if per_wallet is not None and n["mine"] >= per_wallet:
                raise LimitError(f"limit of {per_wallet} valuations per day reached")
            c.execute(
                "INSERT INTO studio.valuations(id,url,requested_by,status,steps,result,self_reported) "
                "VALUES (%s,%s,%s,'queued',%s,%s,%s)",
                (vid, url, requested_by, Jsonb(initial_steps()),
                 Jsonb({"counters": {"pages": 0, "competitors": 0, "sources": 0}}),
                 Jsonb(self_reported) if self_reported else None))
        return vid

    def get_valuation(self, vid: str) -> dict | None:
        return self.one("SELECT * FROM studio.valuations WHERE id=%s", (vid,))

    def claim_valuation(self) -> dict | None:
        return self.one(
            "UPDATE studio.valuations SET status='running', updated_at=now() WHERE id = ("
            " SELECT id FROM studio.valuations WHERE status='queued' ORDER BY created_at"
            " FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *"
        )

    def set_valuation_status(self, vid: str, status: str, error: str | None = None) -> None:
        self.exec(
            "UPDATE studio.valuations SET status=%s, error=%s, updated_at=now() WHERE id=%s", (status, error, vid)
        )

    def merge_result(self, vid: str, patch: dict) -> None:
        """Shallow-merge `patch` into result (counters are merged key by key)."""
        with self.tx() as c:
            row = c.execute("SELECT result FROM studio.valuations WHERE id=%s FOR UPDATE", (vid,)).fetchone()
            if row is None:
                return
            res = row["result"] or {}
            patch = jsonable(patch)
            if "counters" in patch:
                patch["counters"] = {**res.get("counters", {}), **patch["counters"]}
            res.update(patch)
            c.execute("UPDATE studio.valuations SET result=%s, updated_at=now() WHERE id=%s", (Jsonb(res), vid))

    def set_step(self, vid: str, key: str, status: str, detail: str = "") -> None:
        with self.tx() as c:
            row = c.execute("SELECT steps FROM studio.valuations WHERE id=%s FOR UPDATE", (vid,)).fetchone()
            if row is None:
                return
            steps = row["steps"] or initial_steps()
            for s in steps:
                if s["key"] == key:
                    s.update(status=status, detail=detail[:500], at=now().isoformat())
            c.execute("UPDATE studio.valuations SET steps=%s, updated_at=now() WHERE id=%s", (Jsonb(steps), vid))

    def valuations_today(self, requested_by: str) -> int:
        row = self.one(
            "SELECT count(*) AS n FROM studio.valuations WHERE lower(requested_by)=lower(%s) "
            "AND created_at > now() - interval '1 day'",
            (requested_by,),
        )
        return int(row["n"])


class StudioProgress:
    """Progress sink used by the site_valuation graph (writes to studio.valuations)."""

    def __init__(self, db: Studio):
        self.db = db

    def step(self, vid: str, key: str, status: str, detail: str = "") -> None:
        try:
            self.db.set_step(vid, key, status, detail)
        except Exception:  # progress must never kill the run
            log.exception("progress update failed")

    def result(self, vid: str, **patch) -> None:
        try:
            self.db.merge_result(vid, patch)
        except Exception:
            log.exception("result update failed")

    def status(self, vid: str, status: str, error: str | None = None) -> None:
        self.db.set_valuation_status(vid, status, error)


class MemoryProgress:
    """In-memory progress sink (tests, CLI)."""

    def __init__(self):
        self.steps: dict[str, dict[str, dict]] = {}
        self.results: dict[str, dict] = {}
        self.statuses: dict[str, str] = {}

    def step(self, vid: str, key: str, status: str, detail: str = "") -> None:
        self.steps.setdefault(vid, {})[key] = {"status": status, "detail": detail}

    def result(self, vid: str, **patch) -> None:
        r = self.results.setdefault(vid, {"counters": {}})
        patch = jsonable(patch)
        if "counters" in patch:
            patch["counters"] = {**r.get("counters", {}), **patch["counters"]}
        r.update(patch)

    def status(self, vid: str, status: str, error: str | None = None) -> None:
        self.statuses[vid] = status
