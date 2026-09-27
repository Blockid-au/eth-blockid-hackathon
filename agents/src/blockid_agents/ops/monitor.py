"""Ops monitor loop (docs/PLAN-OPS.md §1): runs in the API process, every OPS_INTERVAL_SECONDS (60).

Leader election: each API process tries `pg_try_advisory_lock(hashtext('blockid.ops.monitor'))` on a dedicated
connection and keeps it for its lifetime; only the holder runs a round. If that process dies (or its connection
drops) Postgres releases the lock and another process takes over on its next tick.

One round (leader only):
  1. run every registry check that is due (Check.every_s), open / update / resolve incidents, persist per-check
     state in studio.ops_checks_state (status, detail, data, fail streaks);
  2. re-aggregate nginx logs into ops_traffic_daily every OPS_TRAFFIC_PARSE_SECONDS (and before a report);
  3. build the weekly (and optional daily) report when its slot has passed;
  4. Notifier: emails per the policy in incidents.py;
  5. once a day: retention (ops_errors 30 d, mail log 30 d, incident events of incidents resolved > 180 d).
If Postgres is unreachable for 3 consecutive ticks, a direct email is attempted (max one per hour) since
nothing can be stored.

The worker writes a heartbeat row ("_hb:worker") every 30 s from a daemon thread (start_heartbeat).
"""
from __future__ import annotations

import logging
import os
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg.types.json import Jsonb

from ..studio.db import jsonable
from .checks import RANK, REGISTRY, Check, OpsEnv, run_check
from .config import OpsConfig
from .incidents import IncidentStore, Notifier
from .report import Reports
from .traffic import TrafficStore, logs_readable

log = logging.getLogger(__name__)
LOCK_KEY = "blockid.ops.monitor"


class Leader:
    """Session-level advisory lock on a dedicated connection."""

    def __init__(self, url: str, key: str = LOCK_KEY):
        self.url, self.key = url, key
        self.conn = None

    @property
    def is_leader(self) -> bool:
        return self.conn is not None

    def acquire(self) -> bool | None:
        """True = we hold the lock; False = another process holds it; None = database unreachable."""
        import psycopg

        if self.conn is not None:
            try:
                self.conn.execute("SELECT 1")
                return True
            except Exception:  # noqa: BLE001 - connection lost: the lock is gone with it
                self.release()
        try:
            conn = psycopg.connect(self.url, autocommit=True, connect_timeout=5)
        except Exception as e:  # noqa: BLE001
            log.warning("ops leader: database unreachable: %s", e)
            return None
        try:
            got = conn.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (self.key,)).fetchone()[0]
        except Exception:  # noqa: BLE001
            conn.close()
            return None
        if got:
            self.conn = conn
            log.info("ops monitor: this process is the leader")
            return True
        conn.close()
        return False

    def release(self) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:  # noqa: BLE001
                pass
            self.conn = None


def aggregate_status(results) -> str:
    known = [r.status for r in results if r.status != "unknown"]
    if not known:
        return "unknown"
    return max(known, key=lambda s: RANK[s])


class Monitor:
    def __init__(self, db, env: OpsEnv, *, cfg: OpsConfig | None = None, mailer=None, leader: Leader | None = None,
                 registry: dict[str, Check] | None = None):
        self.db, self.env = db, env
        self.cfg = cfg or env.cfg
        self.registry = registry if registry is not None else REGISTRY
        self.store = IncidentStore(db, self.cfg, self.registry)
        self.mailer = mailer if mailer is not None else env.mailer
        self.notifier = Notifier(db, self.mailer, self.cfg, self.store)
        self.reports = Reports(db, self.cfg, self.mailer, ai_health=env.ai_health if env._gateway else None)
        self.traffic = TrafficStore(db)
        self.leader = leader
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._db_down = 0
        self._db_down_mailed = 0.0
        self.last_round: dict | None = None

    # -------------------------------------------------------------- state rows
    def _states(self) -> dict[str, dict]:
        return {r["check_id"]: r for r in self.db.all("SELECT * FROM studio.ops_checks_state")}

    def _save_state(self, check_id: str, status: str, detail: str, data: dict, now: datetime) -> None:
        self.db.exec(
            "INSERT INTO studio.ops_checks_state (check_id, status, detail, data, last_run_at, last_ok_at, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,now()) ON CONFLICT (check_id) DO UPDATE SET status=EXCLUDED.status, "
            "detail=EXCLUDED.detail, data=EXCLUDED.data, last_run_at=EXCLUDED.last_run_at, "
            "last_ok_at=coalesce(EXCLUDED.last_ok_at, studio.ops_checks_state.last_ok_at), updated_at=now()",
            (check_id, status, detail[:2000], Jsonb(jsonable(data)), now, now if status == "ok" else None))

    # -------------------------------------------------------------- one round
    def run_checks(self, now: datetime) -> dict:
        states = self._states()
        self.env.new_round()
        out: dict[str, Any] = {}
        for c in self.registry.values():
            st = states.get(c.id)
            if c.every_s and st and st["last_run_at"] and (now - st["last_run_at"]).total_seconds() < c.every_s - 1:
                continue
            data = dict((st or {}).get("data") or {})
            streaks = data.pop("_streak", {}) or {}
            self.env.states[c.id] = data
            results = run_check(c, self.env)
            actions = self.store.apply(c, results, streaks, now)
            status = aggregate_status(results)
            bad = [r.detail for r in results if r.status not in ("ok", "unknown")]
            detail = "; ".join(bad) if bad else "; ".join(r.detail for r in results)[:600]
            self._save_state(c.id, status, detail, {**self.env.states.get(c.id, {}), "_streak": streaks}, now)
            out[c.id] = {"status": status, "actions": [a for a in actions if a["action"] != "seen"]}
        return out

    def parse_traffic(self, now: datetime, force: bool = False) -> dict | None:
        st = self.db.one("SELECT last_run_at FROM studio.ops_checks_state WHERE check_id='_traffic'")
        if not force and st and st["last_run_at"] and (now - st["last_run_at"]).total_seconds() < self.cfg.traffic_parse_s:
            return None
        readable, reason = logs_readable(self.cfg.nginx_log_dir, self.cfg.traffic_hosts)
        res: dict = {"readable": readable, "reason": reason}
        if readable:
            res["result"] = self.traffic.parse_all(self.cfg.nginx_log_dir, self.cfg.traffic_hosts,
                                                   self.cfg.ip_salt_secret)
        self._save_state("_traffic", "ok" if readable else "unknown", reason, res, now)
        return res

    def retention(self, now: datetime) -> None:
        st = self.db.one("SELECT last_run_at FROM studio.ops_checks_state WHERE check_id='_retention'")
        if st and st["last_run_at"] and now - st["last_run_at"] < timedelta(days=1):
            return
        from .errors import ErrorStore

        n = ErrorStore(self.db).purge(self.cfg.error_retention_days)
        self.db.exec("DELETE FROM studio.ops_mail_log WHERE at < now() - interval '30 days'")
        self.db.exec("DELETE FROM studio.ops_incident_events e USING studio.ops_incidents i WHERE e.incident_id=i.id "
                     "AND i.status='resolved' AND i.resolved_at < now() - interval '180 days' AND e.kind='seen'")
        self._save_state("_retention", "ok", f"purged {n} old error rows", {}, now)

    def round(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        self.db.ensure_schema()
        out: dict[str, Any] = {"at": now.isoformat()}
        out["checks"] = self.run_checks(now)
        try:
            missing = self.reports.missing_slots(now)
            out["traffic"] = self.parse_traffic(now, force=bool(missing))  # fresh numbers before a report
        except Exception:  # noqa: BLE001
            log.exception("traffic parse failed")
        try:
            out["reports"] = self.reports.due(now)
        except Exception:  # noqa: BLE001
            log.exception("report build failed")
        out["mail"] = self.notifier.run(now, self.reports)
        try:
            self.retention(now)
        except Exception:  # noqa: BLE001
            log.exception("ops retention failed")
        self._save_state("_monitor", "ok", f"round done, pid {os.getpid()} on {socket.gethostname()}",
                         {"mail": out["mail"]}, now)
        self.last_round = out
        return out

    # -------------------------------------------------------------- loop
    def tick(self) -> None:
        got = self.leader.acquire() if self.leader else True
        if got is None:
            self._db_down += 1
            if self._db_down >= 3:
                self._alert_db_down()
            return
        self._db_down = 0
        if not got:
            return
        try:
            self.round()
        except Exception:  # noqa: BLE001
            log.exception("ops monitor round failed")

    def _alert_db_down(self) -> None:
        if not (self.mailer and self.mailer.configured) or time.time() - self._db_down_mailed < 3600:
            return
        self._db_down_mailed = time.time()
        steps = "\n".join(f"  {i}. {s}" for i, s in enumerate(REGISTRY["db.postgres"].fix_steps, 1))
        self.mailer.send(self.cfg.alert_to, "[BlockID CRITICAL] Postgres unreachable",
                         f"The ops monitor cannot reach Postgres for {self._db_down} minutes; nothing can be stored, "
                         f"so this email is sent directly.\nImpact: {REGISTRY['db.postgres'].impact}\nFix:\n{steps}\n"
                         f"Runbook: {self.cfg.runbook_link('postgres')}\n")

    def start(self) -> None:
        if self._thread is not None:
            return

        def loop() -> None:
            if self._stop.wait(min(15.0, self.cfg.interval_s)):  # let the API finish starting
                return
            while not self._stop.is_set():
                self.tick()
                self._stop.wait(self.cfg.interval_s)

        self._thread = threading.Thread(target=loop, name="ops-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self.leader:
            self.leader.release()


def build_monitor(ctx, cfg: OpsConfig | None = None) -> Monitor | None:
    """Monitor for the API process (StudioContext); None when there is no Postgres."""
    cfg = cfg or OpsConfig()
    db = ctx.db
    if db is None or not getattr(db, "url", "").startswith("postgres"):
        return None
    from ..studio.mailer import Mailer

    s = ctx.settings

    def gateway():
        from ..ai_gateway import get_gateway

        return get_gateway(s, db=db)

    mailer = Mailer()
    env = OpsEnv(cfg, s, db, ctx.issuer, ctx.chain, gateway=gateway, mailer=mailer)
    return Monitor(db, env, cfg=cfg, mailer=mailer, leader=Leader(db.url))


# ------------------------------------------------------------------ worker heartbeat
def beat(db, component: str = "worker", extra: dict | None = None) -> None:
    db.exec("INSERT INTO studio.ops_checks_state (check_id, status, detail, data, last_run_at, last_ok_at) "
            "VALUES (%s,'ok','alive',%s,now(),now()) ON CONFLICT (check_id) DO UPDATE SET last_run_at=now(), "
            "last_ok_at=now(), data=EXCLUDED.data, updated_at=now()",
            (f"_hb:{component}", Jsonb({"pid": os.getpid(), "host": socket.gethostname(), **(extra or {})})))


def start_heartbeat(db, component: str = "worker", interval_s: float = 30) -> threading.Thread:
    def loop() -> None:
        while True:
            try:
                beat(db, component)
            except Exception as e:  # noqa: BLE001 - DB down: try again next time
                log.warning("heartbeat failed: %s", e)
            time.sleep(interval_s)

    t = threading.Thread(target=loop, name=f"ops-heartbeat-{component}", daemon=True)
    t.start()
    return t
