"""Ops email templates: (subject, text, html). Every incident block says what happened, since when, the impact,
the step-by-step fix from the runbook, and links (Admin > Ops, runbook section, logs command)."""
from __future__ import annotations

import html as h
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import OpsConfig

LOGS_CMD = ("cd ~/blockid-eth-platform/deploy/vm-app && sudo docker compose --env-file /opt/blockid/app.env "
            "logs --since=1h agents-api agents-worker issuer")
SEV_COLOR = {"critical": "#B42318", "warn": "#B54708", "info": "#175CD3"}
STYLE = "font-family:system-ui,-apple-system,Segoe UI,sans-serif;font-size:14px;line-height:1.5;color:#10262B"


def when(iso: str | datetime | None, cfg: OpsConfig) -> str:
    if not iso:
        return "-"
    d = datetime.fromisoformat(iso) if isinstance(iso, str) else iso
    local = d.astimezone(ZoneInfo(cfg.report_tz))
    return f"{d.strftime('%Y-%m-%d %H:%M')} UTC ({local.strftime('%a %d %b %H:%M')} Sydney)"


def ago(iso: str | None, now: datetime) -> str:
    if not iso:
        return ""
    mins = int((now - datetime.fromisoformat(iso)).total_seconds() // 60)
    return f"{mins} min" if mins < 120 else f"{mins // 60} h {mins % 60} min"


def _links(inc: dict, cfg: OpsConfig) -> list[tuple[str, str]]:
    return [("Admin > Ops", f"{cfg.admin_url}?incident={inc['id']}"),
            ("Runbook", inc.get("runbook_url") or cfg.runbook_url)]


def incident_text(inc: dict, cfg: OpsConfig, now: datetime) -> str:
    steps = "\n".join(f"  {i}. {s}" for i, s in enumerate(inc.get("fix_steps") or [], 1)) or "  (see runbook)"
    return (f"[{inc['severity'].upper()}] {inc['title']}\n"
            f"What: {inc['detail']}\n"
            f"Since: {when(inc['opened_at'], cfg)} ({ago(inc['opened_at'], now)} ago; seen {inc['occurrences']}x)\n"
            f"Impact: {inc['impact']}\n"
            f"Fix:\n{steps}\n"
            + "".join(f"{k}: {v}\n" for k, v in _links(inc, cfg))
            + f"Logs: {LOGS_CMD}\n")


def incident_html(inc: dict, cfg: OpsConfig, now: datetime) -> str:
    color = SEV_COLOR.get(inc["severity"], "#10262B")
    steps = "".join(f"<li>{h.escape(s)}</li>" for s in inc.get("fix_steps") or [])
    links = " · ".join(f'<a href="{h.escape(u)}">{h.escape(k)}</a>' for k, u in _links(inc, cfg))
    return (f'<div style="border-left:4px solid {color};padding:8px 12px;margin:12px 0">'
            f'<div style="font-weight:600"><span style="color:{color}">{inc["severity"].upper()}</span> '
            f'{h.escape(inc["title"])}</div>'
            f'<div><b>What:</b> {h.escape(inc["detail"])}</div>'
            f'<div><b>Since:</b> {h.escape(when(inc["opened_at"], cfg))} ({ago(inc["opened_at"], now)} ago, '
            f'seen {inc["occurrences"]}x)</div>'
            f'<div><b>Impact:</b> {h.escape(inc["impact"])}</div>'
            f'<div><b>Fix:</b><ol style="margin:4px 0 4px 18px;padding:0">{steps}</ol></div>'
            f'<div>{links} · Logs: <code>{h.escape(LOGS_CMD)}</code></div></div>')


def _wrap(title: str, intro: str, body: str, cfg: OpsConfig) -> str:
    return (f'<!doctype html><html><body style="{STYLE}"><h2 style="margin:0 0 8px">{h.escape(title)}</h2>'
            f'<p>{h.escape(intro)}</p>{body}<p style="color:#667085;font-size:12px">BlockID ops monitor · '
            f'<a href="{h.escape(cfg.admin_url)}">{h.escape(cfg.admin_url)}</a> · acknowledge an incident in Admin '
            f'to stop reminders.</p></body></html>')


def incidents_email(kind: str, incs: list[dict], cfg: OpsConfig, now: datetime) -> tuple[str, str, str]:
    n = len(incs)
    label = "CRITICAL" if kind == "critical" else "Warning"
    subject = (f"[BlockID {label}] {incs[0]['title']}" if n == 1 else f"[BlockID {label}] {n} incidents: "
               + "; ".join(i["title"] for i in incs[:3]))[:200]
    intro = (f"{n} {'critical incident needs' if kind == 'critical' and n == 1 else 'incidents need'} attention."
             if kind == "critical" else f"{n} warning(s) opened since the last digest.")
    text = intro + "\n\n" + "\n".join(incident_text(i, cfg, now) for i in incs) + f"\nAdmin: {cfg.admin_url}\n"
    html = _wrap(subject, intro, "".join(incident_html(i, cfg, now) for i in incs), cfg)
    return subject, text, html


def reminder_email(incs: list[dict], cfg: OpsConfig, now: datetime) -> tuple[str, str, str]:
    n = len(incs)
    subject = (f"[BlockID reminder] still open: {incs[0]['title']}" if n == 1
               else f"[BlockID reminder] {n} incidents still open")[:200]
    intro = "Still open and not acknowledged. Acknowledge in Admin > Ops to stop reminders."
    text = intro + "\n\n" + "\n".join(incident_text(i, cfg, now) for i in incs)
    return subject, text, _wrap(subject, intro, "".join(incident_html(i, cfg, now) for i in incs), cfg)


def resolved_email(incs: list[dict], cfg: OpsConfig, now: datetime) -> tuple[str, str, str]:
    n = len(incs)
    subject = (f"[BlockID resolved] {incs[0]['title']}" if n == 1 else f"[BlockID resolved] {n} incidents")[:200]
    lines, blocks = [], []
    for i in incs:
        dur = ""
        if i.get("resolved_at"):
            mins = int((datetime.fromisoformat(i["resolved_at"]) - datetime.fromisoformat(i["opened_at"]))
                       .total_seconds() // 60)
            dur = f"{mins} min" if mins < 120 else f"{mins // 60} h {mins % 60} min"
        by = "automatically (check recovered)" if i.get("resolved_by") == "auto" else f"by {i.get('resolved_by')}"
        lines.append(f"- [{i['severity']}] {i['title']}: resolved {by} after {dur} "
                     f"(opened {when(i['opened_at'], cfg)})")
        blocks.append(f"<li><b>{h.escape(i['title'])}</b> ({i['severity']}): resolved {h.escape(by)} after {dur}; "
                      f"opened {h.escape(when(i['opened_at'], cfg))} · <a href=\"{h.escape(cfg.admin_url)}?incident="
                      f"{i['id']}\">details</a></li>")
    intro = f"{n} incident(s) resolved."
    return subject, intro + "\n\n" + "\n".join(lines) + f"\n\nAdmin: {cfg.admin_url}\n", _wrap(
        subject, intro, f"<ul>{''.join(blocks)}</ul>", cfg)


def test_email(cfg: OpsConfig) -> tuple[str, str, str]:
    subject = "BlockID ops test email"
    text = ("This is a test from the BlockID ops monitor. Incident alerts and the weekly report will arrive here.\n"
            f"Admin: {cfg.admin_url}\n")
    return subject, text, _wrap(subject, "Incident alerts and the weekly report will arrive at this address.", "", cfg)
