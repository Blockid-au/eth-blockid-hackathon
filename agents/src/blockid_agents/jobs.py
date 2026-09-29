"""Asynchronous (batch) execution — the cost engine of the platform.

Nothing in BlockID needs an instant AI answer, so every AI task is a queued job:
  API enqueues -> worker claims -> GPU VM is started only if it is stopped -> graph runs until it
  finishes or hits a human gate -> the AI VM stops itself after N idle minutes
  (deploy/vm-ai/idle-shutdown.sh). You pay for the GPU only while jobs are running and can use
  Spot pricing, because a pre-empted job is simply retried from its last checkpoint.

The queue uses SQLite for a single-node deployment; for multiple workers switch to Postgres with
`SELECT ... FOR UPDATE SKIP LOCKED` (same interface).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,              -- onboarding | dividend | resume
  thread_id TEXT NOT NULL,         -- LangGraph thread (one per company workflow)
  graph TEXT NOT NULL,             -- onboarding | dividend
  payload TEXT NOT NULL,
  status TEXT NOT NULL,            -- queued | running | waiting_human | done | failed | rejected_input
  gate TEXT,                       -- JSON of the pending human gate
  result TEXT,
  error TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, created_at);
"""


class JobQueue:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        return c

    def enqueue(self, kind: str, graph: str, payload: dict, thread_id: str | None = None) -> str:
        jid = uuid.uuid4().hex[:12]
        now = time.time()
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO jobs(id,kind,thread_id,graph,payload,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (jid, kind, thread_id or jid, graph, json.dumps(payload), "queued", now, now),
            )
        return jid

    def claim_next(self) -> dict | None:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not row:
                return None
            cur = c.execute(
                "UPDATE jobs SET status='running', attempts=attempts+1, updated_at=? WHERE id=? AND status='queued'",
                (time.time(), row["id"]),
            )
            if cur.rowcount == 0:  # another worker container claimed it first (the lock is per process)
                return None
            return dict(row) | {"payload": json.loads(row["payload"])}

    def pending(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM jobs WHERE status='queued'").fetchone()[0]

    def set(self, jid: str, status: str, *, gate: dict | None = None, result: dict | None = None, error: str = ""):
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE jobs SET status=?, gate=?, result=?, error=?, updated_at=? WHERE id=?",
                (
                    status,
                    json.dumps(gate, default=str) if gate else None,
                    json.dumps(result, default=str) if result else None,
                    error,
                    time.time(),
                    jid,
                ),
            )

    def requeue(self, jid: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE jobs SET status='queued', updated_at=? WHERE id=?", (time.time(), jid))

    def get(self, jid: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        if not row:
            return None
        d = dict(row)
        for k in ("payload", "gate", "result"):
            d[k] = json.loads(d[k]) if d[k] else None
        return d

    def latest_for_thread(self, thread_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT id FROM jobs WHERE thread_id=? AND status!='rejected_input' ORDER BY created_at DESC, rowid DESC LIMIT 1", (thread_id,)
            ).fetchone()
        return self.get(row["id"]) if row else None


class GpuController:
    """No-op controller (GPU always on, or local development)."""

    def ensure_running(self) -> None:  # pragma: no cover - trivial
        return None


class GceGpuController(GpuController):
    """Starts the AI VM on demand via the Compute Engine REST API and waits for the LLM gateway.

    The app VM's service account needs only `compute.instances.get` + `compute.instances.start`
    on that single instance (see infra/terraform/iam.tf). Stopping is done by the AI VM itself.
    """

    def __init__(self, project: str, zone: str, name: str, health_url: str, timeout_s: int = 900):
        self.url = f"https://compute.googleapis.com/compute/v1/projects/{project}/zones/{zone}/instances/{name}"
        self.health_url = health_url
        self.timeout_s = timeout_s

    def ensure_running(self) -> None:
        import google.auth  # lazy: only on GCP
        import httpx
        from google.auth.transport.requests import AuthorizedSession

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/compute"])
        s = AuthorizedSession(creds)
        status = s.get(self.url).json().get("status")
        if status != "RUNNING":
            log.info("AI VM is %s — starting it", status)
            s.post(self.url + "/start").raise_for_status()
        deadline = time.time() + self.timeout_s
        while time.time() < deadline:
            try:
                if httpx.get(self.health_url, timeout=5).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(15)
        raise TimeoutError("AI VM did not become healthy in time")
