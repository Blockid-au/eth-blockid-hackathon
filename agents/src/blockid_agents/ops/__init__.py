"""Operations: incident detection + email, error capture, traffic / usage statistics, weekly report
(docs/PLAN-OPS.md, runbook docs/RUNBOOK-INCIDENTS.md).

Modules
  checks.py     registry of health checks (id, severity, detect(), runbook id). New features add a check here.
  monitor.py    background loop in the API (every OPS_INTERVAL_SECONDS, default 60), leader-elected with a Postgres
                advisory lock so exactly one API process runs checks, sends mail, parses logs and builds reports.
  incidents.py  incident lifecycle (open -> acknowledged -> resolved), fingerprint dedupe, email policy.
  errors.py     logging handler: ERROR+ records -> studio.ops_errors (fingerprint dedupe, 30-day retention);
                JSON log formatter + request-id / access-log middleware.
  traffic.py    nginx access-log parser -> studio.ops_traffic_daily (daily-salted IP hash, bots filtered).
  stats.py      users / product activity from the existing studio tables.
  report.py     weekly (and optional daily) report: HTML + text, stored in studio.ops_reports.
  mail.py       email templates (incident, digest, resolve, reminder).
  api.py        admin router below.

Admin HTTP API (platform admin session only: no session -> 401, non-admin -> 403, admin with password change
pending -> 403). All timestamps are ISO-8601 UTC strings or null. Base path /v1/admin/ops (behind nginx: /api/v1/...).

Incident object (used by several endpoints):
  {"id": 12,
   "check_id": "wallet.hsk_balance",             // registry id (see GET /summary checks[].id)
   "fingerprint": "wallet.hsk_balance:issuer",   // dedupe key (one active incident per fingerprint)
   "title": "Issuer HSK balance low (0.012 HSK)",
   "severity": "warn",                           // info | warn | critical (highest seen while open)
   "status": "open",                             // open | acknowledged | resolved
   "detail": "Issuer 0x2567... has 0.012 HSK; warn below 0.02",
   "impact": "HashKey anchoring will fail when the balance runs out ...",
   "fix_steps": ["Open https://faucet.hsk.xyz ...", "..."],   // step-by-step from the runbook
   "runbook_id": "wallet-balances",
   "runbook_url": "https://github.com/Blockid-au/eth-blockid/blob/main/docs/RUNBOOK-INCIDENTS.md#wallet-balances",
   "opened_at": "...", "last_seen_at": "...", "occurrences": 42,   // checks that reported it while active
   "acknowledged_at": null, "acknowledged_by": null,
   "resolved_at": null, "resolved_by": null,      // "auto" when the check recovered, else the admin actor
   "emailed": false,                               // opening email delivered?
   "email_reason": "SMTP not configured",          // why not (null when emailed, or "pending" while batched)
   "last_emailed_at": null,
   "data": {}}                                     // check-specific numbers (balance, pct, ...)

GET  /v1/admin/ops/summary  ->  200
  {"generated_at": "...", "enabled": true,
   "leader": true,                                // this API process holds the monitor lock
   "last_run_at": "...",                          // last completed monitor round (any process; null = never)
   "smtp_configured": false, "alert_to": "admin@blockid.au", "report_to": "admin@blockid.au",
   "unsent_emails": 3,                            // incidents/reports stored but not emailed yet
   "open_incidents": {"critical": 0, "warn": 2, "info": 0, "total": 2},
   "checks": [{"id": "api.5xx_rate", "title": "API 5xx rate", "severity": "critical",   // max severity it can raise
               "status": "ok",                    // ok | warn | critical | info | unknown (skipped / not configured)
               "detail": "0.2 % 5xx in the last 15 min (3 / 1500)",
               "last_run_at": "...", "last_ok_at": "...", "incident_id": null,
               "runbook_id": "api-5xx", "runbook_url": "..."}],
   "errors_24h": 5,                               // sum of ops_errors counts seen in the last 24 h
   "traffic_today": {"page_views": 120, "unique_visitors": 30, "requests": 2400, "status_5xx": 0},
   "last_report": {"id": 3, "kind": "weekly", "created_at": "...", "emailed": false, "email_reason": "..."} | null,
   "kpis": {                                      // headline numbers; null if they could not be computed
     // every entry is {"current": number, "previous": number}
     "visitors_7d":            {"current": 210, "previous": 180},  // sum of daily unique visitors, last 7 UTC days
                                                                   // incl. today vs the 7 days before (all hosts)
     "page_views_7d":          {"current": 900, "previous": 850},  // same windows
     "registered_users_total": {"current": 40, "previous": 35},    // Google accounts + wallets that signed in without
                                                                   // a linked Google account; previous = as of 7 d ago
     "new_registrations_7d":   {"current": 5, "previous": 3},      // new Google accounts + first-time wallets,
                                                                   // last 7 x 24 h vs the 7 days before
     "active_users_7d":        {"current": 12, "previous": 9},     // distinct users who signed in, same windows
     "valuations_7d":          {"current": 4, "previous": 6},      // valuations started
     "hr_reports_7d":          {"current": 2, "previous": 1},      // HR team / person reports created
     "ai_spend_today_usd":     {"current": 0.42, "previous": 1.10}}}  // estimated AI spend, today UTC vs yesterday

GET  /v1/admin/ops/incidents?status=active|open|acknowledged|resolved|all&limit=100
     (default status=active = open + acknowledged; limit 1..500)
  ->  200 {"incidents": [Incident, ...]}          // newest first
GET  /v1/admin/ops/incidents/{id}
  ->  200 Incident + {"events": [{"id": 1, "at": "...",
                                  "kind": "opened|seen|escalated|acknowledged|resolved|reopened|emailed|email_failed|reminder",
                                  "actor": "monitor" | "<admin actor>", "detail": "..."}]}      // oldest first
      404 {"detail": "unknown incident"}
POST /v1/admin/ops/incidents/{id}/ack      body (optional): {"note": "looking at it"}
POST /v1/admin/ops/incidents/{id}/resolve  body (optional): {"note": "topped up"}
  ->  200 {"ok": true, "incident": Incident}; 404 unknown; 409 {"detail": "incident is already resolved"}
      (a manually resolved incident re-opens if its check still fails on the next round)

GET  /v1/admin/ops/errors?days=7&source=api|worker|issuer&limit=100   (days 1..30, limit 1..500)
  ->  200 {"errors": [{"id": 7, "fingerprint": "ab12...", "source": "api", "logger": "blockid_agents.studio.routes",
                       "level": "ERROR", "message": "issuer /issue -> HTTP 500 ...",
                       "traceback": "Traceback (most recent call last): ...",   // null when none
                       "count": 4, "first_seen": "...", "last_seen": "...",
                       "request_id": "c0ffee..." | null, "route": "POST /v1/admin/companies/{cid}/approve-issue" | null}],
           "total": 12}                                    // distinct fingerprints in the window

GET  /v1/admin/ops/traffic?days=14      (days 1..90)
  ->  200 {"days": 14, "source": "nginx" | "unavailable",   // "unavailable": logs not mounted / readable
           "last_parsed_at": "...",
           "hosts": ["eth.blockid.au", "hr.blockid.au", "scan.blockid.au"],
           "daily": [{"day": "2026-09-27", "host": "eth.blockid.au",
                      "page_views": 120,          // HTML page loads (non-asset, non-/api GET 2xx/3xx), bots excluded
                      "unique_visitors": 30,      // distinct salted IP+UA hashes that day (salt rotates daily)
                      "requests": 2400, "bot_requests": 300,
                      "api_requests": 1800, "status_4xx": 12, "status_5xx": 0,
                      "top_pages": [{"path": "/i", "views": 40}],             // up to 20
                      "top_referrers": [{"referrer": "google.com", "count": 5}], // hosts only, up to 20, own hosts excluded
                      "countries": [{"country": "AU", "count": 20}]}],         // only when a CF-IPCountry field is logged
           "totals": {"page_views": 0, "unique_visitors": 0, "requests": 0, "bot_requests": 0, "status_5xx": 0}}
                                                   // unique_visitors total = sum of daily uniques (salt rotates daily)

GET  /v1/admin/ops/stats?days=30        (days 1..365)
  ->  200 {"generated_at": "...", "days": 30,
           "accounts": {"total": 10, "new_7d": 2, "new_period": 5},                 // Google accounts
           "wallets": {"linked_total": 12, "signed_in_7d": 8, "signed_in_period": 20},  // distinct addresses with sessions
           "sign_ins": {"7d": {"wallet": 3, "guest": 4, "google": 2, "demo": 9, "password": 1},
                        "period": {...same keys...}},                             // sessions created, by auth_method
           "active_users": {"d1": 3, "d7": 8, "d30": 20},                          // distinct actors with a session
           "registrations_daily": [{"day": "2026-09-27", "accounts": 1, "wallets": 3}],  // period, oldest first
           "valuations": {"started_7d": 4, "finished_7d": 3, "failed_7d": 1, "started_period": 9,
                          "finished_period": 7, "failed_period": 2, "running": 0},
           "hr": {"teams_7d": 2, "done_7d": 1, "failed_7d": 0, "teams_period": 3},
           "companies": {"total": 14, "created_7d": 1, "by_status": {"anchored": 12, "partially_anchored": 1}},
           "offerings": {"total": 3, "open": 1, "created_7d": 0},
           "dividends": {"total": 5, "created_7d": 1, "paid_7d": 1},
           "admin_actions_7d": 23}

GET  /v1/admin/ops/reports?limit=20
  ->  200 {"reports": [{"id": 3, "kind": "weekly" | "daily", "period_start": "...", "period_end": "...",
                        "created_at": "...", "subject": "BlockID weekly report 21-27 Sep 2026",
                        "to": "admin@blockid.au", "emailed": false, "email_reason": "SMTP not configured",
                        "sent_at": null, "trigger": "schedule" | "manual"}]}
GET  /v1/admin/ops/reports/{id}
  ->  200 report summary + {"html": "<!doctype html>...", "text": "...", "data": {...raw numbers...}}; 404 unknown
POST /v1/admin/ops/reports/send-now     body (optional): {"kind": "weekly" | "daily", "to": "someone@x"}
  ->  200 {"ok": true, "report": <report summary>, "emailed": false, "reason": "SMTP not configured"}
      (always builds and stores a fresh report for the period ending now, then tries to email it)
GET  /v1/admin/ops/reports/preview?kind=weekly  ->  200 {"html": ..., "text": ..., "subject": ..., "data": ...}
      (renders without storing or sending)
POST /v1/admin/ops/test-email           body (optional): {"to": "someone@x"}  (default OPS_ALERT_TO)
  ->  200 {"ok": true, "to": "admin@blockid.au", "reason": null}
      200 {"ok": false, "to": "...", "reason": "SMTP not configured" | "send failed: <error>"}

Every admin POST writes a studio.audit row (ops_incident_ack / ops_incident_resolved / ops_report_sent /
ops_test_email).
"""
