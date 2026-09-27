"""Weekly report (and optional daily digest) to OPS_REPORT_TO (docs/PLAN-OPS.md §4).

Schedule: every Monday 08:00 Australia/Sydney (OPS_WEEKLY_AT, OPS_REPORT_TZ) covering the 7 days before; with
OPS_DAILY_DIGEST=1 also every day at 08:00 covering the previous 24 h. The monitor leader builds the report once per
slot (unique (kind, slot) in studio.ops_reports), stores HTML + text + raw numbers, then the Notifier emails it
(or keeps it with email_reason when SMTP is missing; it is sent once SMTP works, if not older than 8 days).

Contents: traffic and users week-over-week, new registrations, product activity, incidents (count, MTTR, still
open), AI usage / spend and model health, issuer balances and days of gas left, top errors, deploys this week,
recommended actions.

Deploys: lines of OPS_DEPLOY_LOG (default /data/deploys.log = host /mnt/app-data/agents/deploys.log), written by
`scripts/record-deploy.sh` at deploy time ("<ISO time>\t<git sha>\t<subject>\t<who>"); plus `git log` of the week
when OPS_GIT_DIR points at a readable checkout (optional read-only mount).
"""
from __future__ import annotations

import html as h
import logging
import os
import subprocess
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from ..studio.db import jsonable
from . import stats
from .checks import days_of_gas
from .config import OpsConfig
from .traffic import TrafficStore

log = logging.getLogger(__name__)
DAYS = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}


# ------------------------------------------------------------------ schedule
def weekly_slot(now: datetime, cfg: OpsConfig) -> datetime:
    """The most recent weekly send time <= now (aware UTC)."""
    tz = ZoneInfo(cfg.report_tz)
    wd, _, hm = cfg.weekly_at.strip().upper().partition(" ")
    hh, mm = (int(x) for x in (hm or "08:00").split(":"))
    local = now.astimezone(tz)
    d = local.date() - timedelta(days=(local.weekday() - DAYS.get(wd[:3], 0)) % 7)
    slot = datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz)
    if slot > local:
        slot -= timedelta(days=7)
        slot = datetime(slot.year, slot.month, slot.day, hh, mm, tzinfo=tz)  # DST-safe wall time
    return slot.astimezone(timezone.utc)


def daily_slot(now: datetime, cfg: OpsConfig) -> datetime:
    tz = ZoneInfo(cfg.report_tz)
    _, _, hm = cfg.weekly_at.strip().partition(" ")
    hh, mm = (int(x) for x in (hm or "08:00").split(":"))
    local = now.astimezone(tz)
    slot = datetime(local.year, local.month, local.day, hh, mm, tzinfo=tz)
    if slot > local:
        prev = local.date() - timedelta(days=1)
        slot = datetime(prev.year, prev.month, prev.day, hh, mm, tzinfo=tz)
    return slot.astimezone(timezone.utc)


# ------------------------------------------------------------------ data
def _pct_change(cur: float, prev: float) -> str:
    if not prev:
        return "new" if cur else "–"
    d = 100.0 * (cur - prev) / prev
    return f"{d:+.0f} %"


def read_deploys(cfg: OpsConfig, start: datetime, end: datetime) -> list[dict]:
    out: list[dict] = []
    try:
        with open(cfg.deploy_log, encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 2:
                    continue
                try:
                    at = datetime.fromisoformat(parts[0].replace("Z", "+00:00"))
                except ValueError:
                    continue
                if at.tzinfo is None:
                    at = at.replace(tzinfo=timezone.utc)
                if start <= at < end:
                    out.append({"at": at.isoformat(), "sha": parts[1][:12], "subject": (parts[2] if len(parts) > 2
                                                                                       else "")[:200],
                                "by": parts[3][:60] if len(parts) > 3 else "", "source": "deploy-log"})
    except OSError:
        pass
    if cfg.git_dir and os.path.isdir(cfg.git_dir):
        try:
            r = subprocess.run(["git", "-c", "safe.directory=*", "-C", cfg.git_dir, "log", "--no-merges",
                                f"--since={start.isoformat()}", f"--until={end.isoformat()}",
                                "--pretty=format:%cI%x09%h%x09%s", "-n", "100"],
                               capture_output=True, text=True, timeout=10)
            for line in r.stdout.splitlines():
                at, sha, subject = (line.split("\t", 2) + ["", ""])[:3]
                out.append({"at": at, "sha": sha, "subject": subject[:200], "by": "", "source": "git"})
        except Exception as e:  # noqa: BLE001
            log.info("git log unavailable: %s", e)
    return out


def incidents_summary(db, start: datetime, end: datetime) -> dict:
    opened = db.all("SELECT severity, count(*) AS n FROM studio.ops_incidents WHERE opened_at >= %s AND opened_at < %s "
                    "GROUP BY severity", (start, end))
    res = db.one("SELECT count(*) AS n, avg(extract(epoch FROM resolved_at - opened_at)) AS mttr FROM "
                 "studio.ops_incidents WHERE resolved_at >= %s AND resolved_at < %s AND severity <> 'info'",
                 (start, end))
    still = db.all("SELECT id, title, severity, status, opened_at FROM studio.ops_incidents WHERE status <> 'resolved' "
                   "ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warn' THEN 1 ELSE 2 END, opened_at LIMIT 20")
    by = {r["severity"]: int(r["n"]) for r in opened}
    return jsonable({"opened": sum(by.values()), "by_severity": by, "resolved": int(res["n"]),
                     "mttr_minutes": None if res["mttr"] is None else round(float(res["mttr"]) / 60, 1),
                     "still_open": still})


def ai_summary(db, start: datetime, end: datetime) -> dict:
    rows = db.all("SELECT provider, count(*) FILTER (WHERE sent) AS calls, count(*) FILTER (WHERE sent AND outcome "
                  "<> 'ok') AS errors, coalesce(sum(cost_usd),0) AS cost, coalesce(sum(tokens_in),0) AS tin, "
                  "coalesce(sum(tokens_out),0) AS tout FROM studio.ai_usage WHERE at >= %s AND at < %s "
                  "GROUP BY provider ORDER BY 2 DESC", (start, end))
    prov = [{"provider": r["provider"], "calls": int(r["calls"]), "errors": int(r["errors"]),
             "cost_usd": round(float(r["cost"]), 2), "tokens_in": int(r["tin"]), "tokens_out": int(r["tout"])}
            for r in rows]
    return {"providers": prov, "calls": sum(p["calls"] for p in prov), "errors": sum(p["errors"] for p in prov),
            "cost_usd": round(sum(p["cost_usd"] for p in prov), 2)}


def checks_snapshot(db) -> dict:
    rows = db.all("SELECT check_id, status, detail, data, last_run_at FROM studio.ops_checks_state WHERE check_id NOT "
                  "LIKE '\\_%%'")
    return {r["check_id"]: jsonable(r) for r in rows}


def balances(db) -> list[dict]:
    from .checks import WALLET_CHAINS

    row = db.one("SELECT data FROM studio.ops_checks_state WHERE check_id='wallet.balances'")
    data = (row or {}).get("data") or {}
    out = []
    for chain, _, unit, label in WALLET_CHAINS:
        hist = data.get(chain) or {}
        if not hist:
            continue
        last = hist[sorted(hist)[-1]]
        out.append({"chain": label, "unit": unit, "balance": round(float(last), 6), "days_left": days_of_gas(hist)})
    return out


def top_errors(db, start: datetime, end: datetime, n: int = 10) -> list[dict]:
    return jsonable(db.all("SELECT source, logger, message, count, first_seen, last_seen FROM studio.ops_errors WHERE "
                           "last_seen >= %s AND last_seen < %s ORDER BY count DESC, last_seen DESC LIMIT %s",
                           (start, end, n)))


def recommendations(d: dict, cfg: OpsConfig, smtp: bool) -> list[str]:
    out = []
    for i in d["incidents"]["still_open"]:
        if i["severity"] in ("critical", "warn"):
            out.append(f"Resolve open {i['severity']} incident #{i['id']}: {i['title']}")
    for b in d["balances"]:
        if b["days_left"] is not None and b["days_left"] < 14:
            out.append(f"Top up the issuer on {b['chain']}: {b['balance']} {b['unit']} left, about "
                       f"{b['days_left']:.0f} days at this week's burn")
    for e in d["top_errors"][:3]:
        if e["count"] >= 10:
            out.append(f"Investigate recurring error ({e['count']}x) in {e['logger']}: {e['message'][:120]}")
    if not smtp:
        out.append("Configure SMTP (SMTP_HOST/SMTP_USER/SMTP_PASSWORD in /opt/blockid/app.env) so alerts and this "
                   "report are emailed")
    if d["traffic"]["source"] != "nginx":
        out.append("Mount nginx logs into agents-api (/var/log/nginx -> /host-logs/nginx) to get traffic numbers")
    ai = d["ai"]
    if ai["calls"] and ai["errors"] / ai["calls"] > 0.1:
        out.append(f"AI error rate {100 * ai['errors'] / ai['calls']:.0f} % this week: review Admin > AI health")
    for cid, c in d["checks"].items():
        if cid == "tls.expiry" and c["status"] != "ok":
            out.append(f"TLS: {c['detail']}")
        if cid == "disk.space" and c["status"] != "ok":
            out.append(f"Disk: {c['detail']}")
    return out or ["Nothing urgent. Keep an eye on the numbers above."]


# ------------------------------------------------------------------ build / render
class Reports:
    def __init__(self, db, cfg: OpsConfig | None = None, mailer=None, ai_health=None):
        self.db, self.cfg, self.mailer, self.ai_health = db, cfg or OpsConfig(), mailer, ai_health

    def data(self, kind: str, end: datetime) -> dict:
        span = timedelta(days=7 if kind == "weekly" else 1)
        start, pstart = end - span, end - 2 * span
        ts = TrafficStore(self.db)
        # traffic: the complete UTC days before the send time (7 for weekly, 1 for daily) vs the same span before
        t_end = end.date()
        cur_t = ts.totals(t_end - span, t_end)
        prev_t = ts.totals(t_end - 2 * span, t_end - span)
        last_parse = self.db.one("SELECT data FROM studio.ops_checks_state WHERE check_id='_traffic'")
        cur_w, prev_w = stats.window(self.db, start, end), stats.window(self.db, pstart, start)
        health = None
        if self.ai_health is not None:
            try:
                hh = self.ai_health()
                health = [{"id": m["id"], "status": m["status"], "usage_pct": m.get("usage_pct"),
                           "error_rate": m.get("error_rate")} for m in hh.get("models", [])]
            except Exception as e:  # noqa: BLE001
                log.info("ai health for report unavailable: %s", e)
        d = {"kind": kind, "period_start": start.isoformat(), "period_end": end.isoformat(),
             "traffic": {"current": cur_t, "previous": prev_t,
                         "source": "nginx" if (last_parse and (last_parse["data"] or {}).get("readable")) or
                         cur_t["total"]["requests"] else "unavailable"},
             "users": {"current": cur_w, "previous": prev_w},
             "totals": {"accounts": stats._n(self.db, "SELECT count(*) AS n FROM studio.accounts"),
                        "companies": stats._n(self.db, "SELECT count(*) AS n FROM studio.companies")},
             "incidents": incidents_summary(self.db, start, end), "ai": ai_summary(self.db, start, end),
             "ai_models": health, "balances": balances(self.db), "top_errors": top_errors(self.db, start, end),
             "deploys": read_deploys(self.cfg, start, end), "checks": checks_snapshot(self.db)}
        d["recommendations"] = recommendations(d, self.cfg, bool(self.mailer and self.mailer.configured))
        return jsonable(d)

    def render(self, d: dict) -> tuple[str, str, str]:
        tz = ZoneInfo(self.cfg.report_tz)
        s, e = (datetime.fromisoformat(d[k]).astimezone(tz) for k in ("period_start", "period_end"))
        label = "weekly report" if d["kind"] == "weekly" else "daily digest"
        subject = f"BlockID {label} {s.strftime('%d %b')} – {e.strftime('%d %b %Y')}"
        tc, tp = d["traffic"]["current"]["total"], d["traffic"]["previous"]["total"]
        uc, up = d["users"]["current"], d["users"]["previous"]
        sections: list[tuple[str, list[tuple[str, str, str, str]] | list[str]]] = []

        def row(name, cur, prev):
            return (name, str(cur), str(prev), _pct_change(float(cur or 0), float(prev or 0)))

        traffic = [row("Page views", tc["page_views"], tp["page_views"]),
                   row("Unique visitors (sum of daily)", tc["unique_visitors"], tp["unique_visitors"]),
                   row("Requests", tc["requests"], tp["requests"]), row("Bot requests", tc["bot_requests"],
                                                                        tp["bot_requests"]),
                   row("5xx responses", tc["status_5xx"], tp["status_5xx"])]
        for host, v in sorted(d["traffic"]["current"]["hosts"].items()):
            pv = d["traffic"]["previous"]["hosts"].get(host, {})
            traffic.append(row(f"{host} page views", v["page_views"], pv.get("page_views", 0)))
        sections.append(("Traffic" + ("" if d["traffic"]["source"] == "nginx" else " (nginx logs not available)"),
                         traffic))
        sections.append(("Users", [
            row("New Google accounts", uc["new_accounts"], up["new_accounts"]),
            row("New wallets (first sign-in)", uc["new_wallets"], up["new_wallets"]),
            row("Active users (signed in)", uc["active_users"], up["active_users"]),
            *[row(f"Sign-ins: {m}", uc["sign_ins"].get(m, 0), up["sign_ins"].get(m, 0)) for m in stats.METHODS]]))
        sections.append(("Product activity", [
            row("Valuations started", uc["valuations_started"], up["valuations_started"]),
            row("Valuations finished", uc["valuations_finished"], up["valuations_finished"]),
            row("Valuations failed", uc["valuations_failed"], up["valuations_failed"]),
            row("HR reports", uc["hr_reports"], up["hr_reports"]), row("HR done", uc["hr_done"], up["hr_done"]),
            row("Companies created", uc["companies_created"], up["companies_created"]),
            row("Offerings created", uc["offerings_created"], up["offerings_created"]),
            row("Dividends declared", uc["dividends_created"], up["dividends_created"])]))
        inc = d["incidents"]
        lines = [f"Opened: {inc['opened']} ({', '.join(f'{k} {v}' for k, v in inc['by_severity'].items()) or 'none'})",
                 f"Resolved: {inc['resolved']}; mean time to resolve: "
                 f"{'–' if inc['mttr_minutes'] is None else str(inc['mttr_minutes']) + ' min'}"]
        lines += [f"Still open: #{i['id']} [{i['severity']}] {i['title']} (since {i['opened_at'][:16]} UTC)"
                  for i in inc["still_open"]] or ["Still open: none"]
        sections.append(("Incidents", lines))
        ai = d["ai"]
        ai_lines = [f"{ai['calls']} calls, {ai['errors']} errors, ~${ai['cost_usd']:.2f} estimated spend"]
        ai_lines += [f"{p['provider']}: {p['calls']} calls, {p['errors']} errors, ${p['cost_usd']:.2f}"
                     for p in ai["providers"]]
        if d["ai_models"]:
            bad = [m for m in d["ai_models"] if m["status"] not in ("healthy",)]
            ai_lines.append("Model health now: " + (", ".join(f"{m['id']} {m['status']}" for m in bad)
                                                    if bad else "all healthy"))
        sections.append(("AI usage", ai_lines))
        sections.append(("Issuer balances", [
            f"{b['chain']}: {b['balance']} {b['unit']}" + (f", ~{b['days_left']:.0f} days of gas left"
                                                            if b["days_left"] is not None else "")
            for b in d["balances"]] or ["No balance data yet"]))
        sections.append(("Top errors", [f"{e['count']}x {e['source']} {e['logger']}: {e['message'][:160]}"
                                        for e in d["top_errors"]] or ["No errors logged"]))
        sections.append(("Deploys this week", [f"{x['at'][:16]} {x['sha']} {x['subject']}" + (f" ({x['by']})"
                                                                                           if x["by"] else "")
                                               for x in d["deploys"]] or ["None recorded (scripts/record-deploy.sh)"]))
        sections.append(("Recommended actions", d["recommendations"]))

        text = [f"{subject}\nPeriod: {s.strftime('%a %d %b %H:%M')} – {e.strftime('%a %d %b %H:%M')} "
                f"({self.cfg.report_tz})\n"]
        html_parts = [f'<!doctype html><html><body style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;'
                      f'font-size:14px;line-height:1.5;color:#10262B;max-width:760px">'
                      f'<h2 style="margin:0">{h.escape(subject)}</h2><p style="color:#667085">'
                      f'{h.escape(s.strftime("%a %d %b %H:%M"))} – {h.escape(e.strftime("%a %d %b %H:%M"))} '
                      f'({h.escape(self.cfg.report_tz)})</p>']
        for title, body in sections:
            text.append(f"\n== {title} ==")
            html_parts.append(f'<h3 style="margin:18px 0 6px">{h.escape(title)}</h3>')
            if body and isinstance(body[0], tuple):
                text.append(f"{'':34} {'this':>8} {'previous':>9} {'change':>8}")
                html_parts.append('<table style="border-collapse:collapse;width:100%"><tr style="text-align:left;'
                                  'color:#667085"><th>Metric</th><th>This period</th><th>Previous</th><th>Change</th>'
                                  '</tr>')
                for name, cur, prev, ch in body:
                    text.append(f"{name[:34]:34} {cur:>8} {prev:>9} {ch:>8}")
                    html_parts.append(f'<tr style="border-top:1px solid #EAECF0"><td>{h.escape(name)}</td>'
                                      f'<td>{h.escape(cur)}</td><td>{h.escape(prev)}</td><td>{h.escape(ch)}</td></tr>')
                html_parts.append("</table>")
            else:
                text += [f"- {x}" for x in body]
                html_parts.append("<ul>" + "".join(f"<li>{h.escape(str(x))}</li>" for x in body) + "</ul>")
        text.append(f"\nAdmin: {self.cfg.admin_url}")
        html_parts.append(f'<p style="color:#667085;font-size:12px">BlockID ops · <a href="{h.escape(self.cfg.admin_url)}'
                          f'">{h.escape(self.cfg.admin_url)}</a></p></body></html>')
        return subject, "\n".join(text) + "\n", "".join(html_parts)

    def build(self, kind: str = "weekly", end: datetime | None = None) -> dict:
        end = end or datetime.now(timezone.utc)
        d = self.data(kind, end)
        subject, text, html_ = self.render(d)
        return {"kind": kind, "period_start": d["period_start"], "period_end": d["period_end"], "subject": subject,
                "text": text, "html": html_, "data": d}

    # -------------------------------------------------------------- storage
    def store(self, rep: dict, *, trigger: str, slot: str | None, to: str | None = None) -> int | None:
        row = self.db.one(
            "INSERT INTO studio.ops_reports (kind, period_start, period_end, subject, to_addr, html, text, data, "
            "trigger, slot, email_reason) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending') "
            "ON CONFLICT (kind, slot) WHERE slot IS NOT NULL DO NOTHING RETURNING id",
            (rep["kind"], rep["period_start"], rep["period_end"], rep["subject"], to or self.cfg.report_to,
             rep["html"], rep["text"], Jsonb(rep["data"]), trigger, slot))
        return row["id"] if row else None

    def missing_slots(self, now: datetime) -> list[tuple[str, datetime, str]]:
        """(kind, slot time, slot key) of scheduled reports whose time has passed (< 1 day ago) and not stored."""
        plan = [("weekly", weekly_slot(now, self.cfg))]
        if self.cfg.daily_digest:
            plan.append(("daily", daily_slot(now, self.cfg)))
        out = []
        for kind, slot in plan:
            if now - slot > timedelta(days=1):
                continue
            key = slot.astimezone(ZoneInfo(self.cfg.report_tz)).date().isoformat()
            if not self.db.one("SELECT 1 AS x FROM studio.ops_reports WHERE kind=%s AND slot=%s", (kind, key)):
                out.append((kind, slot, key))
        return out

    def due(self, now: datetime | None = None) -> list[int]:
        """Build + store the scheduled reports whose slot has passed (within the last day). Returns new ids."""
        now = now or datetime.now(timezone.utc)
        new = []
        for kind, slot, key in self.missing_slots(now):
            rid = self.store(self.build(kind, slot), trigger="schedule", slot=key)
            if rid:
                new.append(rid)
        return new

    def unsent(self, now: datetime) -> list[dict]:
        rows = self.db.all("SELECT * FROM studio.ops_reports WHERE emailed=false AND created_at > %s AND "
                           "coalesce(email_reason,'') NOT LIKE 'superseded%%' ORDER BY created_at DESC",
                           (now - timedelta(days=8),))
        latest: dict[str, dict] = {}
        for r in rows:
            if r["kind"] in latest:
                self.db.exec("UPDATE studio.ops_reports SET email_reason='superseded by a newer report' WHERE id=%s",
                             (r["id"],))
            else:
                latest[r["kind"]] = r
        return list(latest.values())

    def deliver(self, rep: dict, notifier) -> bool:
        ok, reason = notifier.send(f"report_{rep['kind']}", rep["to_addr"], rep["subject"], rep["text"], rep["html"])
        self.db.exec("UPDATE studio.ops_reports SET emailed=%s, sent_at=CASE WHEN %s THEN now() ELSE sent_at END, "
                     "email_reason=%s WHERE id=%s", (ok, ok, None if ok else reason, rep["id"]))
        return ok

    def mark_unsent(self, reason: str) -> None:
        self.db.exec("UPDATE studio.ops_reports SET email_reason=%s WHERE emailed=false AND "
                     "coalesce(email_reason,'') NOT LIKE 'superseded%%'", (reason,))

    # -------------------------------------------------------------- views
    @staticmethod
    def summary(r: dict) -> dict:
        return jsonable({k: r[k] for k in ("id", "kind", "period_start", "period_end", "created_at", "subject",
                                           "emailed", "email_reason", "sent_at", "trigger")} | {"to": r["to_addr"]})

    def list(self, limit: int = 20) -> list[dict]:
        return [self.summary(r) for r in self.db.all(
            "SELECT id, kind, period_start, period_end, created_at, subject, to_addr, emailed, email_reason, sent_at, "
            "trigger FROM studio.ops_reports ORDER BY created_at DESC, id DESC LIMIT %s", (limit,))]

    def get(self, rid: int) -> dict | None:
        r = self.db.one("SELECT * FROM studio.ops_reports WHERE id=%s", (rid,))
        return None if r is None else {**self.summary(r), "html": r["html"], "text": r["text"],
                                       "data": jsonable(r["data"])}

