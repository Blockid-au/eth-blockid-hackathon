"""Incident lifecycle, dedupe and the email policy (docs/PLAN-OPS.md §1).

Lifecycle: a failing result opens an incident keyed by fingerprint "<check id>[:<key>]" (at most one active =
open | acknowledged per fingerprint, enforced by a partial unique index). While it keeps failing the same row is
updated (last_seen_at, occurrences, detail; severity only goes up, an escalation to critical re-arms the email).
An ok result resolves it (resolved_by "auto"); an admin can acknowledge (stops reminders) or resolve it by hand.
If the fingerprint fails again within 30 min of being resolved, that incident is re-opened instead of a new one.

Email policy (Notifier.run, once per monitor round, leader only):
  critical opened / escalated  -> immediately (all new criticals of a round in one email)
  warn opened                  -> one digest at most every OPS_WARN_BATCH_MINUTES (15)
  info                         -> never emailed (Admin > Ops only)
  still open (not acknowledged) after OPS_REMINDER_HOURS (2) -> reminder, then every OPS_REMINDER_REPEAT_HOURS
  resolved (after its opening was emailed) -> one "resolved" email per round
  reports (weekly / daily)     -> see report.py; share the same budget
  at most OPS_MAX_EMAILS_PER_HOUR (10) attempts per rolling hour; after a failed send, 10 min back-off.
SMTP not configured: nothing is sent, rows keep emailed=false with email_reason "SMTP not configured"; once SMTP
works, the next round sends whatever is still relevant (active incidents; reports of the last 8 days).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg.types.json import Jsonb

from ..studio.db import jsonable
from . import mail
from .checks import RANK, Check, Result
from .config import OpsConfig

log = logging.getLogger(__name__)

ACTIVE = ("open", "acknowledged")
REOPEN_WINDOW = timedelta(minutes=30)
FAIL_BACKOFF = timedelta(minutes=10)


def fingerprint(check_id: str, key: str = "") -> str:
    return f"{check_id}:{key}" if key else check_id


def cap_severity(status: str, max_sev: str) -> str:
    return status if RANK[status] <= RANK[max_sev] else max_sev


class IncidentStore:
    def __init__(self, db, cfg: OpsConfig | None = None, registry: dict[str, Check] | None = None):
        from .checks import REGISTRY

        self.db, self.cfg = db, cfg or OpsConfig()
        self.registry = registry if registry is not None else REGISTRY

    # -------------------------------------------------------------- reads
    def get(self, iid: int) -> dict | None:
        row = self.db.one("SELECT * FROM studio.ops_incidents WHERE id=%s", (iid,))
        return self.view(row) if row else None

    def events(self, iid: int) -> list[dict]:
        return jsonable(self.db.all("SELECT id, at, kind, actor, detail FROM studio.ops_incident_events WHERE "
                                    "incident_id=%s ORDER BY id", (iid,)))

    def list(self, status: str = "active", limit: int = 100) -> list[dict]:
        where = {"active": "status <> 'resolved'", "all": "true", "open": "status='open'",
                 "acknowledged": "status='acknowledged'", "resolved": "status='resolved'"}.get(status, "true")
        rows = self.db.all(f"SELECT * FROM studio.ops_incidents WHERE {where} ORDER BY opened_at DESC, id DESC "
                           "LIMIT %s", (limit,))
        return [self.view(r) for r in rows]

    def active_for(self, fp: str) -> dict | None:
        return self.db.one("SELECT * FROM studio.ops_incidents WHERE fingerprint=%s AND status <> 'resolved'", (fp,))

    def view(self, row: dict) -> dict:
        c = self.registry.get(row["check_id"])
        out = jsonable(dict(row))
        out.pop("reminded_at", None)
        out.pop("resolve_emailed", None)
        out["fix_steps"] = list(c.fix_steps) if c else []
        out["runbook_url"] = self.cfg.runbook_link(row["runbook_id"]) if row["runbook_id"] else None
        return out

    def counts(self) -> dict:
        rows = self.db.all("SELECT severity, count(*) AS n FROM studio.ops_incidents WHERE status <> 'resolved' "
                           "GROUP BY severity")
        out = {"critical": 0, "warn": 0, "info": 0}
        out.update({r["severity"]: int(r["n"]) for r in rows})
        out["total"] = sum(out.values())
        return out

    def event(self, c, iid: int, kind: str, detail: str = "", actor: str = "monitor") -> None:
        c.execute("INSERT INTO studio.ops_incident_events (incident_id, kind, actor, detail) VALUES (%s,%s,%s,%s)",
                  (iid, kind, actor, detail[:2000]))

    # -------------------------------------------------------------- lifecycle from check results
    def apply(self, check: Check, results: list[Result], streaks: dict[str, int], now: datetime | None = None
              ) -> list[dict]:
        """Open / update / resolve incidents for one check's results. `streaks` (fingerprint -> consecutive
        failing rounds) is updated in place (the monitor persists it). Returns [{"fp", "action", "id"}]."""
        now = now or datetime.now(timezone.utc)
        actions: list[dict] = []
        broken = any(r.status == "unknown" and r.detail.startswith("check error") for r in results)
        seen: set[str] = set()
        for r in results:
            fp = fingerprint(check.id, r.key)
            seen.add(fp)
            if r.status == "unknown":
                continue
            if r.status == "ok":
                streaks.pop(fp, None)
                row = self.active_for(fp)
                if row:
                    self._resolve(row["id"], "auto", f"recovered: {r.detail}", now)
                    actions.append({"fp": fp, "action": "resolved", "id": row["id"]})
                continue
            streaks[fp] = streaks.get(fp, 0) + 1
            if streaks[fp] < check.confirm and not self.active_for(fp):
                actions.append({"fp": fp, "action": "pending"})
                continue
            actions.append(self._open_or_update(check, r, fp, now))
        if not broken:  # a key this check no longer reports is over
            for row in self.db.all("SELECT id, fingerprint FROM studio.ops_incidents WHERE check_id=%s AND "
                                   "status <> 'resolved'", (check.id,)):
                if row["fingerprint"] not in seen:
                    self._resolve(row["id"], "auto", "no longer reported by the check", now)
                    actions.append({"fp": row["fingerprint"], "action": "resolved", "id": row["id"]})
        return actions

    def _open_or_update(self, check: Check, r: Result, fp: str, now: datetime) -> dict:
        sev = cap_severity(r.status, check.severity)
        title = (r.title or (f"{check.title}: {r.key}" if r.key else check.title))[:300]
        impact = r.impact or check.impact
        data = Jsonb(jsonable(r.data))
        with self.db.tx() as c:
            c.execute("SELECT pg_advisory_xact_lock(hashtext('studio.ops_incidents'))")
            row = c.execute("SELECT * FROM studio.ops_incidents WHERE fingerprint=%s AND status <> 'resolved'",
                            (fp,)).fetchone()
            if row:
                escalate = RANK[sev] > RANK[row["severity"]]
                c.execute("UPDATE studio.ops_incidents SET last_seen_at=%s, occurrences=occurrences+1, detail=%s, "
                          "title=%s, data=%s, severity=%s, emailed = CASE WHEN %s THEN false ELSE emailed END "
                          "WHERE id=%s",
                          (now, r.detail[:2000], title, data, sev if escalate else row["severity"],
                           escalate and sev == "critical", row["id"]))
                if escalate:
                    self.event(c, row["id"], "escalated", f"{row['severity']} -> {sev}: {r.detail}")
                return {"fp": fp, "action": "escalated" if escalate else "seen", "id": row["id"]}
            prev = c.execute("SELECT * FROM studio.ops_incidents WHERE fingerprint=%s AND status='resolved' AND "
                             "resolved_at > %s ORDER BY resolved_at DESC LIMIT 1", (fp, now - REOPEN_WINDOW)
                             ).fetchone()
            if prev:
                c.execute("UPDATE studio.ops_incidents SET status='open', resolved_at=NULL, resolved_by=NULL, "
                          "acknowledged_at=NULL, acknowledged_by=NULL, last_seen_at=%s, occurrences=occurrences+1, "
                          "detail=%s, title=%s, data=%s, severity=%s WHERE id=%s",
                          (now, r.detail[:2000], title, data, sev, prev["id"]))
                self.event(c, prev["id"], "reopened", r.detail)
                return {"fp": fp, "action": "reopened", "id": prev["id"]}
            iid = c.execute(
                "INSERT INTO studio.ops_incidents (fingerprint, check_id, title, severity, detail, impact, runbook_id, "
                "data, opened_at, last_seen_at, email_reason) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (fp, check.id, title, sev, r.detail[:2000], impact, check.runbook_id, data, now, now,
                 None if sev == "info" else "pending")).fetchone()["id"]
            self.event(c, iid, "opened", f"{sev}: {r.detail}")
            return {"fp": fp, "action": "opened", "id": iid}

    def _resolve(self, iid: int, actor: str, detail: str, now: datetime) -> None:
        with self.db.tx() as c:
            n = c.execute("UPDATE studio.ops_incidents SET status='resolved', resolved_at=%s, resolved_by=%s WHERE "
                          "id=%s AND status <> 'resolved'", (now, actor, iid)).rowcount
            if n:
                self.event(c, iid, "resolved", detail, actor=actor)

    # -------------------------------------------------------------- admin actions
    def acknowledge(self, iid: int, actor: str, note: str = "") -> dict:
        with self.db.tx() as c:
            row = c.execute("SELECT status FROM studio.ops_incidents WHERE id=%s FOR UPDATE", (iid,)).fetchone()
            if row is None:
                raise KeyError(iid)
            if row["status"] == "resolved":
                raise ValueError("incident is already resolved")
            c.execute("UPDATE studio.ops_incidents SET status='acknowledged', acknowledged_at=now(), "
                      "acknowledged_by=%s WHERE id=%s", (actor, iid))
            self.event(c, iid, "acknowledged", note, actor=actor)
        return self.get(iid)

    def resolve(self, iid: int, actor: str, note: str = "") -> dict:
        row = self.db.one("SELECT status FROM studio.ops_incidents WHERE id=%s", (iid,))
        if row is None:
            raise KeyError(iid)
        if row["status"] == "resolved":
            raise ValueError("incident is already resolved")
        self._resolve(iid, actor, note or "resolved by admin", datetime.now(timezone.utc))
        return self.get(iid)


# ================================================================== notifier
class Notifier:
    """Sends ops emails with the rate limit / back-off / SMTP-missing rules above. `mailer` needs `configured`,
    `send(to, subject, text, html) -> bool` and `last_error` (studio.mailer.Mailer or a test fake)."""

    def __init__(self, db, mailer, cfg: OpsConfig | None = None, store: IncidentStore | None = None):
        self.db, self.mailer, self.cfg = db, mailer, cfg or OpsConfig()
        self.store = store or IncidentStore(db, self.cfg)
        self._now: datetime | None = None  # the round's clock (tests pass a fixed time)

    # -------------------------------------------------------------- sending primitive
    def budget(self, now: datetime) -> int:
        n = self.db.one("SELECT count(*) AS n FROM studio.ops_mail_log WHERE at > %s", (now - timedelta(hours=1),))
        return max(0, self.cfg.max_emails_per_hour - int(n["n"]))

    def backing_off(self, now: datetime) -> str | None:
        last = self.db.one("SELECT at, ok, error FROM studio.ops_mail_log ORDER BY id DESC LIMIT 1")
        if last and not last["ok"] and last["at"] > now - FAIL_BACKOFF:
            return f"send failed: {last['error'] or 'unknown error'} (retrying after back-off)"
        return None

    def send(self, kind: str, to: str, subject: str, text: str, html: str | None) -> tuple[bool, str | None]:
        """One attempt, logged in ops_mail_log. Returns (ok, reason-if-not)."""
        if not getattr(self.mailer, "configured", False):
            return False, "SMTP not configured"
        ok = bool(self.mailer.send(to, subject, text, html))
        err = None if ok else (getattr(self.mailer, "last_error", None) or "send failed")
        self.db.exec("INSERT INTO studio.ops_mail_log (at, kind, to_addr, subject, ok, error) VALUES "
                     "(%s,%s,%s,%s,%s,%s)", (self._now or datetime.now(timezone.utc), kind, to[:300], subject[:300],
                                             ok, err))
        return ok, None if ok else f"send failed: {err}"

    def _mark(self, ids: list[int], ok: bool, reason: str | None, kind: str, now: datetime) -> None:
        if not ids:
            return
        with self.db.tx() as c:
            if ok:
                c.execute("UPDATE studio.ops_incidents SET emailed=true, email_reason=NULL, last_emailed_at=%s "
                          "WHERE id = ANY(%s)", (now, ids))
            else:
                c.execute("UPDATE studio.ops_incidents SET email_reason=%s WHERE id = ANY(%s)", (reason, ids))
            for i in ids:
                self.store.event(c, i, "emailed" if ok else "email_failed", kind if ok else f"{kind}: {reason}")

    # -------------------------------------------------------------- one round
    def run(self, now: datetime | None = None, reports=None) -> dict:
        """Returns {"sent": [...kinds], "skipped": reason | None}. `reports` (report.Reports) sends unsent reports."""
        now = now or datetime.now(timezone.utc)
        self._now = now
        try:
            return self._run(now, reports)
        finally:
            self._now = None

    def _run(self, now: datetime, reports) -> dict:
        out: dict[str, Any] = {"sent": [], "skipped": None}
        if not getattr(self.mailer, "configured", False):
            self.db.exec("UPDATE studio.ops_incidents SET email_reason='SMTP not configured' WHERE emailed=false AND "
                         "status <> 'resolved' AND severity <> 'info'")
            if reports is not None:
                reports.mark_unsent("SMTP not configured")
            out["skipped"] = "SMTP not configured"
            return out
        # resolved before their opening was ever emailed: nothing to tell
        self.db.exec("UPDATE studio.ops_incidents SET resolve_emailed=true, email_reason='resolved before it was "
                     "emailed' WHERE status='resolved' AND emailed=false AND resolve_emailed=false AND severity <> 'info'")
        wait = self.backing_off(now)
        if wait:
            self.db.exec("UPDATE studio.ops_incidents SET email_reason=%s WHERE emailed=false AND status <> 'resolved' "
                         "AND severity <> 'info'", (wait,))
            out["skipped"] = wait
            return out
        budget = self.budget(now)
        to = self.cfg.alert_to

        def limited() -> bool:
            nonlocal budget
            if budget <= 0:
                self.db.exec("UPDATE studio.ops_incidents SET email_reason=%s WHERE emailed=false AND "
                             "status <> 'resolved' AND severity <> 'info'",
                             (f"rate limited ({self.cfg.max_emails_per_hour}/hour); will send later",))
                out["skipped"] = "rate limited"
                return True
            budget -= 1
            return False

        def active(where: str, params: tuple = ()) -> list[dict]:
            return self.db.all("SELECT * FROM studio.ops_incidents WHERE status <> 'resolved' AND " + where +
                               " ORDER BY opened_at", params)

        # 1. critical: immediately
        crit = active("severity='critical' AND emailed=false")
        if crit and not limited():
            subject, text, html = mail.incidents_email("critical", [self.store.view(r) for r in crit], self.cfg, now)
            ok, reason = self.send("critical", to, subject, text, html)
            self._mark([r["id"] for r in crit], ok, reason, "critical", now)
            if not ok:
                return out
            out["sent"].append("critical")
        # 2. resolved
        res = self.db.all("SELECT * FROM studio.ops_incidents WHERE status='resolved' AND emailed=true AND "
                          "resolve_emailed=false AND severity <> 'info' ORDER BY resolved_at")
        if res and not limited():
            subject, text, html = mail.resolved_email([self.store.view(r) for r in res], self.cfg, now)
            ok, reason = self.send("resolved", to, subject, text, html)
            if ok:
                with self.db.tx() as c:
                    c.execute("UPDATE studio.ops_incidents SET resolve_emailed=true WHERE id = ANY(%s)",
                              ([r["id"] for r in res],))
                    for r in res:
                        self.store.event(c, r["id"], "emailed", "resolved")
                out["sent"].append("resolved")
            else:
                return out
        # 3. warn digest
        warns = active("severity='warn' AND emailed=false")
        if warns:
            last = self.db.one("SELECT max(at) AS at FROM studio.ops_mail_log WHERE kind='warn' AND ok")["at"]
            due = last is None or now - last >= timedelta(minutes=self.cfg.warn_batch_minutes)
            if not due:
                self.db.exec("UPDATE studio.ops_incidents SET email_reason='batched: next warning digest within "
                             "15 min' WHERE id = ANY(%s)", ([r["id"] for r in warns],))
            elif not limited():
                subject, text, html = mail.incidents_email("warn", [self.store.view(r) for r in warns], self.cfg, now)
                ok, reason = self.send("warn", to, subject, text, html)
                self._mark([r["id"] for r in warns], ok, reason, "warn digest", now)
                if not ok:
                    return out
                out["sent"].append("warn")
        # 4. reports (weekly / daily) that are stored but not emailed
        if reports is not None and budget > 0:
            for rep in reports.unsent(now):
                if limited():
                    break
                ok = reports.deliver(rep, self)
                out["sent"].append(f"report:{rep['id']}" if ok else f"report_failed:{rep['id']}")
                if not ok:
                    return out
        # 5. reminders
        first = now - timedelta(hours=self.cfg.reminder_hours)
        again = now - timedelta(hours=self.cfg.reminder_repeat_hours)
        rem = active("status='open' AND severity <> 'info' AND emailed=true AND ((reminded_at IS NULL AND "
                     "opened_at <= %s) OR reminded_at <= %s)", (first, again))
        if rem and not limited():
            subject, text, html = mail.reminder_email([self.store.view(r) for r in rem], self.cfg, now)
            ok, reason = self.send("reminder", to, subject, text, html)
            if ok:
                with self.db.tx() as c:
                    c.execute("UPDATE studio.ops_incidents SET reminded_at=%s WHERE id = ANY(%s)",
                              (now, [r["id"] for r in rem]))
                    for r in rem:
                        self.store.event(c, r["id"], "reminder", "still open")
                out["sent"].append("reminder")
        return out

    def unsent_count(self) -> int:
        a = self.db.one("SELECT count(*) AS n FROM studio.ops_incidents WHERE emailed=false AND status <> 'resolved' "
                        "AND severity <> 'info'")["n"]
        b = self.db.one("SELECT count(*) AS n FROM studio.ops_reports WHERE emailed=false AND created_at > now() - "
                        "interval '8 days'")["n"]
        return int(a) + int(b)
