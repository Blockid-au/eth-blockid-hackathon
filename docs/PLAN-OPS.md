# Plan — incidents, logs, usage statistics and weekly report to admin@blockid.au (27 Sep 2026)

## 1. Incident detection + email with fix steps
- `ops` monitor loop (in the API process, leader-elected via a Postgres advisory lock so only one instance runs;
  every 60 s) runs a **registry of checks** (each check = id, severity, how to detect, runbook id). New features add
  a check to the registry — that is how monitoring keeps up with development.
- Initial checks: API up + 5xx rate (nginx log), worker heartbeat + queue backlog, valuation/HR job failures and
  stalls, issuer health + wallet balances (BLKD, Hoodi ETH, HSK: warn < 0.02 HSK / < 0.05 ETH), chain sync failures
  and mirror mismatches, BlockID Chain producing blocks, Claude bridge health + daily cap, AI gateway (model skipped /
  circuit open / quota ≥ 80 %, DeepInfra budget), Brave quota, Postgres reachable + size, disk space (warn 80 %, crit
  90 %), TLS certificates expiring < 14 days (eth, hr, scan), dividend/offering automation errors, email delivery
  failures.
- Incidents table with fingerprint dedupe, severity (info/warn/critical), open → acknowledged → resolved; email on
  open (critical immediately, warn batched every 15 min), reminder if still open after 2 h, email on resolve; max 10
  emails/hour; each email has what happened, since when, impact, **step-by-step fix from the runbook**, links to the
  admin page and logs.
- `docs/RUNBOOK-INCIDENTS.md`: one section per check with diagnosis commands and fixes (e.g. top up HSK at the faucet,
  `sudo docker compose … restart agents-worker`, re-run chain sync from admin, renew certs `certbot renew`).

## 2. Logs
- Structured JSON logs (request id, route, status, latency, user id hash) for API/worker/issuer; errors also stored
  in `ops_errors` (30 days) with stack trace for admins; Docker json-file rotation (max-size 20m × 10 files);
  nginx access/error logs for eth/hr/scan kept by logrotate (14 days) and parsed.

## 3. Usage statistics
- Traffic: nightly + hourly parse of nginx access logs → `ops_traffic_daily` (host, page views, unique visitors via
  a daily-salted IP hash — no raw IPs stored, bots filtered, top pages, referrers, countries if Cloudflare header).
- Users: accounts (Google), wallets that signed in (MetaMask / guest / Google / demo), new registrations per day,
  active users (7/30 d), valuations started/finished, HR reports, companies issued, offerings, dividends.
- Admin page `/admin/ops`: Incidents · Traffic & users · Logs (errors) · Weekly reports (preview + history + send now).

## 4. Weekly report
- Every Monday 08:00 Australia/Sydney to admin@blockid.au (env `OPS_REPORT_TO`): traffic and users week-over-week,
  new registrations, product activity, incidents (count, MTTR, still open), AI usage/spend and model health, wallet
  balances and days of gas left, top errors, deploys this week (git log), recommended actions. HTML + text; stored so
  it can be viewed in admin. Optional daily digest (`OPS_DAILY_DIGEST=1`).

## 5. Delivery requires SMTP
Email uses `studio/mailer.py` (admin@blockid.au via Google Workspace). Until `SMTP_*` is set, incidents and reports
are stored and shown in admin with "not emailed — SMTP not configured"; they are sent when SMTP works.
