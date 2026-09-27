/* Mock of the admin operations API for ?mock=1 — same JSON as agents/src/blockid_agents/ops/__init__.py (docstring).
   In-memory: incidents can be acknowledged / resolved, "Send now" stores a new weekly report. SMTP is "not configured"
   (as in production until SMTP_* is set), so e-mails are stored and shown with that warning. */
import { ApiError } from "./api";
import type { OpsStats, RawOpsCheck, RawOpsError, RawOpsIncident, RawOpsReport, RawOpsSummary, RawOpsTraffic, RawOpsTrafficDay } from "./api";

const MIN = 6e4, HOUR = 36e5, DAY = 864e5;
const iso = (t: number) => new Date(t).toISOString();
const day = (t: number) => iso(t).slice(0, 10);
const RUNBOOK = "https://github.com/Blockid-au/eth-blockid/blob/main/docs/RUNBOOK-INCIDENTS.md";
const T0 = Date.now();

/** Deterministic noise so the charts look the same on every reload. */
let seed = 42;
const rnd = () => { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; };
const jig = (x: number, f = 0.18) => Math.max(0, Math.round(x * (1 + (rnd() - 0.5) * 2 * f)));

/* ---------- traffic (45 days so 7 / 30 / 90-day views and week-over-week work) ---------- */
const HOSTS = ["eth.blockid.au", "hr.blockid.au", "scan.blockid.au"]; // scan: log not mounted yet -> no rows
const PAGES: Record<string, [string, number][]> = {
  "eth.blockid.au": [["/", 0.34], ["/companies", 0.2], ["/valuation", 0.15], ["/c/VTR", 0.08], ["/investor", 0.06], ["/verify", 0.04]],
  "hr.blockid.au": [["/", 0.45], ["/team/new", 0.2], ["/r/demo", 0.08]],
};
const REFS: [string, number][] = [["google.com", 0.2], ["linkedin.com", 0.13], ["devfolio.co", 0.09], ["x.com", 0.035], ["github.com", 0.02]];
const CTRY: [string, number][] = [["AU", 0.55], ["VN", 0.25], ["US", 0.1], ["SG", 0.05], ["IN", 0.03], ["GB", 0.02]];
const DAILY: RawOpsTrafficDay[] = [];
for (let i = 89; i >= 0; i--) {
  const t = T0 - i * DAY, wd = new Date(t).getUTCDay(), weekend = wd === 0 || wd === 6 ? 0.62 : 1, growth = 1 + (89 - i) * 0.006;
  const hack = i <= 2 ? 1.9 : 1; // hackathon spike (26–27 Sep)
  for (const [host, base, ppv, boost] of [["eth.blockid.au", 118, 4.3, hack], ["hr.blockid.au", 46, 3.1, i <= 2 ? 1.4 : 1]] as const) {
    const uv = jig(base * weekend * growth * boost), pv = jig(uv * ppv), req = pv * 9;
    DAILY.push({
      day: day(t), host, unique_visitors: uv, page_views: pv, requests: req, bot_requests: jig(req * 0.4), api_requests: jig(req * 0.7), status_4xx: jig(pv * 0.02), status_5xx: jig(1.2, 1),
      top_pages: PAGES[host].map(([path, f]) => ({ path, views: jig(pv * f) })),
      top_referrers: REFS.map(([referrer, f]) => ({ referrer, count: jig(pv * f * (host === "hr.blockid.au" ? 0.6 : 1)) })),
      countries: CTRY.map(([country, f]) => ({ country, count: jig(pv * f) })),
    });
  }
}
const regDaily = Array.from({ length: 91 }, (_, k) => ({ day: day(T0 - (90 - k) * DAY), accounts: jig(k >= 88 ? 9 : 2 + k * 0.03, 0.6), wallets: jig(k >= 88 ? 12 : 3 + k * 0.05, 0.6) }));

export function opsTraffic(days: number): RawOpsTraffic {
  const n = Math.max(1, Math.min(90, days || 14));
  const since = day(T0 - (n - 1) * DAY);
  const rows = DAILY.filter((d) => d.day >= since);
  const sum = (k: keyof RawOpsTrafficDay) => rows.reduce((a, d) => a + Number(d[k] ?? 0), 0);
  return {
    days: n, source: "nginx", last_parsed_at: iso(T0 - 14 * MIN), hosts: HOSTS, daily: rows,
    totals: { page_views: sum("page_views"), unique_visitors: sum("unique_visitors"), requests: sum("requests"), bot_requests: sum("bot_requests"), status_5xx: sum("status_5xx") },
  };
}

export function opsStats(days: number): OpsStats {
  const p = Math.max(1, Math.min(365, days || 30));
  const reg = regDaily.slice(-Math.min(p, 91));
  const last = (n: number, k: "accounts" | "wallets") => regDaily.slice(-n).reduce((a, d) => a + d[k], 0);
  const per = (x7: number) => Math.round(x7 * p / 7 * 0.8);
  return {
    generated_at: iso(Date.now()), days: p,
    accounts: { total: 212, new_7d: last(7, "accounts"), new_period: last(p, "accounts") },
    wallets: { linked_total: 486, signed_in_7d: 131, signed_in_period: 298 },
    sign_ins: { "7d": { google: 61, wallet: 38, guest: 27, demo: 19, password: 6 }, period: { google: 164, wallet: 97, guest: 71, demo: 48, password: 21 } },
    active_users: { d1: 34, d7: 131, d30: 298 },
    registrations_daily: reg,
    valuations: { started_7d: 38, finished_7d: 33, failed_7d: 2, started_period: 38 + per(22), finished_period: 33 + per(20), failed_period: 2 + per(1), running: 3 },
    hr: { teams_7d: 17, done_7d: 15, failed_7d: 1, teams_period: 17 + per(9) },
    companies: { total: 21, created_7d: 3, by_status: { anchored: 17, partially_anchored: 1, pending: 3 } },
    offerings: { total: 4, open: 1, created_7d: 1 },
    dividends: { total: 6, created_7d: 0, paid_7d: 0 },
    admin_actions_7d: 57,
  };
}

/* ---------- incidents ---------- */
type Inc = RawOpsIncident & { events: NonNullable<RawOpsIncident["events"]> };
let evId = 1;
const ev = (at: number, kind: string, detail: string | null = null, actor = "monitor") => ({ id: evId++, at: iso(at), kind, actor, detail });
const NC = "SMTP not configured";
const incidents: Inc[] = [
  {
    id: 104, check_id: "wallet.hsk_balance", fingerprint: "wallet.hsk_balance:issuer", title: "Issuer HSK balance low (0.011 HSK)", severity: "critical", status: "open",
    opened_at: iso(T0 - 52 * MIN), last_seen_at: iso(T0 - 40e3), occurrences: 53,
    detail: "Issuer 0x2567…5ddf has 0.011 HSK on HashKey Chain testnet; warn below 0.02 HSK. About 9 more anchoring transactions are possible.",
    impact: "Company issuance and HashKey anchoring will fail once gas runs out; valuations still finish but cannot be anchored.",
    runbook_id: "wallet-balances", runbook_url: RUNBOOK + "#wallet-balances",
    fix_steps: [
      "Open **Admin → Issuer wallets** and copy the issuer address `0x2567Bb502ac840cF93957C60A410160a8cCb5ddf`.",
      "Request test HSK at the faucet: https://faucet.hsk.xyz (0.5 HSK per request).",
      "Check the balance: `cast balance 0x2567Bb502ac840cF93957C60A410160a8cCb5ddf --rpc-url $HSK_RPC_URL`.",
      "The incident resolves by itself at the next check (every 60 s) once the balance is above 0.02 HSK.",
    ],
    emailed: false, email_reason: NC, last_emailed_at: null, data: { balance_hsk: 0.011, warn_below: 0.02, tx_left: 9 },
    events: [ev(T0 - 52 * MIN, "opened", "0.019 HSK < 0.02 HSK"), ev(T0 - 20 * MIN, "escalated", "warn -> critical: 0.011 HSK")],
  },
  {
    id: 103, check_id: "worker.queue_backlog", fingerprint: "worker.queue_backlog", title: "Valuation queue backlog (14 waiting)", severity: "warn", status: "acknowledged",
    opened_at: iso(T0 - 3 * HOUR - 12 * MIN), last_seen_at: iso(T0 - 2 * MIN), occurrences: 184, acknowledged_at: iso(T0 - 2 * HOUR), acknowledged_by: "admin@blockid.au",
    detail: "14 valuation jobs are waiting; the oldest has waited 26 minutes (warn above 10 jobs or 15 minutes).",
    impact: "New valuations start late; users see “queued” for longer.",
    runbook_id: "worker-backlog", runbook_url: RUNBOOK + "#worker-backlog",
    fix_steps: [
      "Check the worker heartbeat check on **Admin → Operations → Overview**.",
      "Look at the worker logs: `sudo docker compose -f deploy/docker-compose.yml logs --tail 200 agents-worker`.",
      "If it is stuck, restart it: `sudo docker compose -f deploy/docker-compose.yml restart agents-worker`.",
      "If the AI gateway is throttled, open **Admin → AI health** and pause the failing model.",
    ],
    emailed: false, email_reason: NC, data: { waiting: 14, oldest_min: 26 },
    events: [ev(T0 - 3 * HOUR - 12 * MIN, "opened", "11 jobs waiting, oldest 16 min"), ev(T0 - 2 * HOUR, "acknowledged", "Hackathon traffic, watching", "admin@blockid.au")],
  },
  {
    id: 102, check_id: "email.delivery", fingerprint: "email.delivery", title: "E-mail delivery not configured", severity: "warn", status: "open",
    opened_at: iso(T0 - 2 * DAY), last_seen_at: iso(T0 - 30e3), occurrences: 2880,
    detail: "SMTP_HOST / SMTP_USER / SMTP_PASSWORD are not set, so incident e-mails and weekly reports are only stored.",
    impact: "Nobody is e-mailed about incidents; check this page instead.",
    runbook_id: "email-delivery", runbook_url: RUNBOOK + "#email-delivery",
    fix_steps: [
      "Create an app password for info@blockid.au in Google Workspace (Security → App passwords).",
      "Set `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USER=info@blockid.au`, `SMTP_PASSWORD=…` in `deploy/.env`.",
      "Restart the API: `sudo docker compose -f deploy/docker-compose.yml up -d agents-api`.",
      "Press **Send test email** on the Weekly reports tab.",
    ],
    emailed: false, email_reason: NC, data: {}, events: [ev(T0 - 2 * DAY, "opened", "SMTP settings missing")],
  },
  {
    id: 101, check_id: "tls.expiry", fingerprint: "tls.expiry:scan.blockid.au", title: "TLS certificate for scan.blockid.au expires in 12 days", severity: "warn", status: "resolved",
    opened_at: iso(T0 - 4 * DAY), last_seen_at: iso(T0 - 3 * DAY - 5 * HOUR), occurrences: 1140, resolved_at: iso(T0 - 3 * DAY - 5 * HOUR), resolved_by: "auto",
    detail: "The certificate was renewed by certbot.", impact: "Browsers would have warned visitors of the explorer.",
    runbook_id: "tls-expiry", runbook_url: RUNBOOK + "#tls-expiry", fix_steps: ["Renew: `sudo certbot renew`.", "Reload nginx: `sudo systemctl reload nginx`."],
    emailed: false, email_reason: NC, data: { days_left: 12 },
    events: [ev(T0 - 4 * DAY, "opened", "expires in 12 days"), ev(T0 - 3 * DAY - 5 * HOUR, "resolved", "check passing again", "auto")],
  },
  {
    id: 100, check_id: "api.5xx_rate", fingerprint: "api.5xx_rate", title: "API 5xx rate 4.1 %", severity: "critical", status: "resolved",
    opened_at: iso(T0 - 6 * DAY - 2 * HOUR), last_seen_at: iso(T0 - 6 * DAY - HOUR), occurrences: 38, resolved_at: iso(T0 - 6 * DAY - HOUR + 20 * MIN), resolved_by: "admin@blockid.au",
    detail: "Postgres connection pool exhausted during a deploy.", impact: "Some page loads failed for about an hour.",
    runbook_id: "api-5xx", runbook_url: RUNBOOK + "#api-5xx",
    fix_steps: ["`sudo docker compose -f deploy/docker-compose.yml logs --tail 300 agents-api | grep ERROR`", "Restart the API if the pool is stuck."],
    emailed: true, email_reason: null, last_emailed_at: iso(T0 - 6 * DAY - 2 * HOUR + 3e3), data: { rate_pct: 4.1 },
    events: [ev(T0 - 6 * DAY - 2 * HOUR, "opened", "4.1 % 5xx in 15 min"), ev(T0 - 6 * DAY - 2 * HOUR + 3e3, "emailed", "to admin@blockid.au"), ev(T0 - 6 * DAY - HOUR + 20 * MIN, "resolved", "Restarted agents-api", "admin@blockid.au")],
  },
];
const findInc = (id: string) => { const x = incidents.find((i) => String(i.id) === id); if (!x) throw new ApiError(404, "unknown incident"); return x; };
const view = ({ events: _e, ...x }: Inc): RawOpsIncident => structuredClone(x); // eslint-disable-line @typescript-eslint/no-unused-vars

const CHECKS: [string, string, "critical" | "warn" | "info", string][] = [
  ["api.5xx_rate", "API 5xx rate", "critical", "0.2 % 5xx in the last 15 min (3 / 1,500)"], ["api.up", "API responding", "critical", "200 in 41 ms"],
  ["worker.heartbeat", "Worker heartbeat", "critical", "last beat 12 s ago"], ["worker.queue_backlog", "Job queue backlog", "warn", ""],
  ["jobs.failures", "Valuation / HR job failures", "warn", "2 failed of 55 in 24 h"], ["wallet.hsk_balance", "Issuer HSK balance", "critical", ""],
  ["wallet.eth_balance", "Issuer Hoodi ETH balance", "warn", "0.41 ETH"], ["chain.sync", "Chain sync + Hoodi mirror", "warn", "0 failed syncs"],
  ["chain.blocks", "BlockID Chain producing blocks", "critical", "block #18,204, 3 s ago"], ["ai.bridge", "Claude bridge + daily cap", "warn", "251 / 300 today"],
  ["ai.gateway", "AI gateway models", "warn", "1 circuit open (DeepInfra Qwen3)"], ["search.brave_quota", "Brave Search quota", "warn", "86 % of the month"],
  ["db.postgres", "Postgres reachable + size", "critical", "1.4 GB"], ["host.disk", "Disk space", "warn", "61 % used"],
  ["tls.expiry", "TLS certificates", "warn", "eth 71 d · hr 71 d · scan 78 d"], ["automation.errors", "Dividend / offering automation", "warn", "no errors"],
  ["email.delivery", "E-mail delivery", "warn", ""],
];
function checks(): RawOpsCheck[] {
  return CHECKS.map(([id, title, severity, detail]) => {
    const inc = incidents.find((i) => i.check_id === id && i.status !== "resolved");
    const warnOnly = id === "ai.gateway" || id === "search.brave_quota";
    return {
      id, title, severity, status: inc ? inc.severity : warnOnly ? "warn" : id === "chain.sync" ? "unknown" : "ok",
      detail: inc ? inc.detail ?? inc.title : id === "chain.sync" ? "not configured (HOODI_RPC_URL unset)" : detail,
      last_run_at: iso(Math.floor(Date.now() / MIN) * MIN), last_ok_at: inc ? inc.opened_at : iso(Math.floor(Date.now() / MIN) * MIN),
      incident_id: inc?.id ?? null, runbook_id: id.split(".")[0], runbook_url: RUNBOOK + "#" + id.replace(/[._]/g, "-"),
    };
  });
}

/* ---------- errors ---------- */
const STACK = (fn: string, msg: string) => `Traceback (most recent call last):
  File "/app/src/blockid_agents/api.py", line 412, in ${fn}
    result = await handler(request)
  File "/app/src/blockid_agents/studio/valuation.py", line 233, in run_step
    data = await gateway.complete(profile="extract_json", prompt=p)
  File "/app/src/blockid_agents/ai_gateway.py", line 518, in complete
    raise GatewayError(last_error)
blockid_agents.ai_gateway.GatewayError: ${msg}`;
const ERRORS: RawOpsError[] = [
  { id: 7, fingerprint: "a91f3c02e1", source: "worker", logger: "blockid_agents.studio.valuation", level: "ERROR", count: 41, first_seen: iso(T0 - 5 * DAY), last_seen: iso(T0 - 9 * MIN), route: null, message: "GatewayError: all models failed for profile extract_json (last: HTTP 503 model overloaded)", traceback: STACK("run_valuation", "all models failed for profile extract_json"), request_id: "7d1c9a0b" },
  { id: 6, fingerprint: "5be2710d44", source: "api", logger: "blockid_agents.tools.search", level: "ERROR", count: 17, first_seen: iso(T0 - 2 * DAY), last_seen: iso(T0 - 48 * MIN), route: "POST /v1/hr/teams/{tid}/run", message: "Brave Search 429 Too Many Requests", traceback: 'Traceback (most recent call last):\n  File "/app/src/blockid_agents/tools/search.py", line 88, in brave\n    r.raise_for_status()\nhttpx.HTTPStatusError: Client error \'429 Too Many Requests\'', request_id: "22ab01ff" },
  { id: 5, fingerprint: "0c44e9b701", source: "issuer", logger: "blockid_agents.issuer.chain", level: "ERROR", count: 6, first_seen: iso(T0 - 26 * HOUR), last_seen: iso(T0 - 3 * HOUR), route: "POST /v1/admin/companies/{cid}/sync", message: "issuer /sync -> HTTP 500: execution reverted: nonce too low", traceback: 'Traceback (most recent call last):\n  File "/app/src/blockid_agents/issuer/chain.py", line 301, in send\n    tx = w3.eth.send_raw_transaction(raw)\nweb3.exceptions.ContractLogicError: execution reverted: nonce too low', request_id: "9e0f33aa" },
  { id: 4, fingerprint: "f2d8a61190", source: "api", logger: "blockid_agents.studio.auth", level: "ERROR", count: 2, first_seen: iso(T0 - 7 * HOUR), last_seen: iso(T0 - 6 * HOUR), route: "POST /v1/auth/google", message: "Google sign-in failed: Token used too early, check that your computer's clock is set correctly", traceback: null, request_id: null },
];

/* ---------- weekly reports ---------- */
const mondayOf = (t: number) => { const d = new Date(t); const wd = (d.getUTCDay() + 6) % 7; d.setUTCDate(d.getUTCDate() - wd); d.setUTCHours(0, 0, 0, 0); return +d; };
function reportHtml(ws: number): string {
  const we = ws + 6 * DAY, f = (t: number) => new Date(t).toLocaleDateString("en-AU", { day: "numeric", month: "short" });
  const row = (k: string, v: string, c: string) => `<tr><td style="padding:6px 0;color:#55676A">${k}</td><td style="padding:6px 0;text-align:right;font-weight:600">${v}</td><td style="padding:6px 0 6px 12px;text-align:right;color:${c.startsWith("+") ? "#12805C" : "#C8372D"}">${c}</td></tr>`;
  return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>BlockID weekly report</title></head>
<body style="margin:0;background:#F3F6F5;font-family:Arial,Helvetica,sans-serif;color:#0D1B1E">
<div style="max-width:640px;margin:0 auto;padding:24px 16px">
<p style="margin:0;color:#00876A;font-weight:700;letter-spacing:.06em;font-size:12px">BLOCKID · WEEKLY REPORT</p>
<h1 style="font-size:22px;margin:6px 0 4px">Week of ${f(ws)} – ${f(we)}</h1>
<p style="margin:0 0 18px;color:#55676A;font-size:14px">Traffic up, 1 critical incident still open, SMTP not configured.</p>
<div style="background:#fff;border:1px solid #D9E3E0;border-radius:12px;padding:16px;margin-bottom:14px">
<h2 style="font-size:15px;margin:0 0 8px">Traffic and users</h2>
<table style="width:100%;border-collapse:collapse;font-size:14px">${row("Unique visitors", "1,284", "+31 %")}${row("Page views", "5,102", "+27 %")}${row("New registrations", "46", "+64 %")}${row("Active users (7 d)", "131", "+18 %")}</table></div>
<div style="background:#fff;border:1px solid #D9E3E0;border-radius:12px;padding:16px;margin-bottom:14px">
<h2 style="font-size:15px;margin:0 0 8px">Product activity</h2>
<table style="width:100%;border-collapse:collapse;font-size:14px">${row("Valuations finished", "33", "+65 %")}${row("HR reports", "17", "+89 %")}${row("Companies issued", "3", "+50 %")}${row("Dividends", "0", "−100 %")}</table></div>
<div style="background:#fff;border:1px solid #D9E3E0;border-radius:12px;padding:16px;margin-bottom:14px">
<h2 style="font-size:15px;margin:0 0 8px">Incidents</h2>
<p style="font-size:14px;margin:0">5 opened · 2 resolved · median time to resolve 1 h 20 min · <b style="color:#C8372D">3 still open</b></p></div>
<div style="background:#fff;border:1px solid #D9E3E0;border-radius:12px;padding:16px;margin-bottom:14px">
<h2 style="font-size:15px;margin:0 0 8px">Recommended actions</h2>
<ol style="font-size:14px;margin:0;padding-left:20px;line-height:1.6"><li>Top up the issuer wallet with HSK (≈ 9 transactions left).</li><li>Set SMTP_* so incidents are e-mailed.</li><li>Raise the Brave Search quota — 86 % used this month.</li></ol></div>
<p style="font-size:12px;color:#5E706D">Sent by the BlockID ops monitor · <a href="https://eth.blockid.au/admin/ops" style="color:#00876A">Open admin</a></p>
</div></body></html>`;
}
const reports: RawOpsReport[] = [0, 1, 2, 3].map((k) => {
  const ws = mondayOf(T0) - (k + 1) * 7 * DAY, sent = k >= 2;
  return {
    id: 20 - k, kind: "weekly", period_start: iso(ws), period_end: iso(ws + 7 * DAY), created_at: iso(ws + 7 * DAY - 2 * HOUR), trigger: "schedule",
    subject: `BlockID weekly report ${new Date(ws).toLocaleDateString("en-AU", { day: "numeric", month: "short" })} – ${new Date(ws + 6 * DAY).toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" })}`,
    to: "admin@blockid.au", emailed: sent, email_reason: sent ? null : NC, sent_at: sent ? iso(ws + 7 * DAY - 2 * HOUR + 4e3) : null,
  };
});
let smtpOk = false; // flip in the console: sessionStorage["blockid-mock-smtp"]="1"
try { smtpOk = sessionStorage.getItem("blockid-mock-smtp") === "1"; } catch { /* */ }

/* ---------- summary ---------- */
export function opsSummary(): RawOpsSummary {
  const active = incidents.filter((i) => i.status !== "resolved");
  const by = (s: string) => active.filter((i) => i.severity === s).length;
  const today = DAILY.filter((d) => d.day === day(T0));
  const last = reports[0];
  return {
    generated_at: iso(Date.now()), enabled: true, leader: true, last_run_at: iso(Math.floor(Date.now() / MIN) * MIN),
    smtp_configured: smtpOk, alert_to: "admin@blockid.au", report_to: "admin@blockid.au", unsent_emails: smtpOk ? 0 : 4,
    open_incidents: { critical: by("critical"), warn: by("warn"), info: by("info"), total: active.length }, checks: checks(),
    errors_24h: ERRORS.filter((e) => Date.parse(e.last_seen) > T0 - DAY).reduce((a, e) => a + e.count, 0),
    traffic_today: { page_views: today.reduce((a, d) => a + d.page_views, 0), unique_visitors: today.reduce((a, d) => a + d.unique_visitors, 0), requests: today.reduce((a, d) => a + (d.requests ?? 0), 0), status_5xx: 1 },
    last_report: last ? { id: last.id, kind: last.kind, created_at: last.created_at, emailed: !!last.emailed, email_reason: last.email_reason } : null,
  };
}

/* ---------- router (same shape as mock.ts) ---------- */
type H = (m: RegExpMatchArray, body: any) => unknown; // eslint-disable-line @typescript-eslint/no-explicit-any
export function opsRoutes(needAdmin: () => void, actor: () => string): [string, RegExp, H][] {
  const g = (f: H): H => (m, b) => { needAdmin(); return f(m, b); };
  return [
    ["GET", /^\/v1\/admin\/ops\/summary$/, g(() => opsSummary())],
    ["GET", /^\/v1\/admin\/ops\/incidents$/, g((_m, q) => {
      const st = q?.status ?? "active";
      return { incidents: incidents.filter((i) => st === "all" || (st === "active" ? i.status !== "resolved" : i.status === st)).sort((a, b) => Date.parse(b.opened_at) - Date.parse(a.opened_at)).map(view) };
    })],
    ["GET", /^\/v1\/admin\/ops\/incidents\/(\d+)$/, g((m) => { const x = findInc(m[1]); return { ...view(x), events: structuredClone(x.events) }; })],
    ["POST", /^\/v1\/admin\/ops\/incidents\/(\d+)\/(ack|resolve)$/, g((m, b) => {
      const x = findInc(m[1]), now = Date.now(), note = String(b?.note ?? "") || null;
      if (x.status === "resolved") throw new ApiError(409, "incident is already resolved");
      if (m[2] === "ack") { x.status = "acknowledged"; x.acknowledged_at = iso(now); x.acknowledged_by = actor(); x.events.push(ev(now, "acknowledged", note, actor())); }
      else { x.status = "resolved"; x.resolved_at = iso(now); x.resolved_by = actor(); x.events.push(ev(now, "resolved", note, actor())); if (smtpOk) x.events.push(ev(now + 1e3, "emailed", "resolved notice to admin@blockid.au")); }
      return { ok: true, incident: view(x) };
    })],
    ["GET", /^\/v1\/admin\/ops\/errors$/, g((_m, q) => {
      const d = Number(q?.days ?? 7), rows = ERRORS.filter((e) => Date.parse(e.last_seen) >= T0 - d * DAY);
      return { errors: rows, total: rows.length };
    })],
    ["GET", /^\/v1\/admin\/ops\/traffic$/, g((_m, q) => opsTraffic(Number(q?.days ?? 14)))],
    ["GET", /^\/v1\/admin\/ops\/stats$/, g((_m, q) => opsStats(Number(q?.days ?? 30)))],
    ["GET", /^\/v1\/admin\/ops\/reports$/, g(() => ({ reports: reports.map((r) => ({ ...r })) }))],
    ["GET", /^\/v1\/admin\/ops\/reports\/(\d+)$/, g((m) => {
      const r = reports.find((x) => String(x.id) === m[1]);
      if (!r) throw new ApiError(404, "unknown report");
      return { ...r, html: reportHtml(Date.parse(r.period_start)), text: "BlockID weekly report (text version)", data: {} };
    })],
    ["POST", /^\/v1\/admin\/ops\/reports\/send-now$/, g(() => {
      const now = Date.now(), ws = now - 7 * DAY;
      const r: RawOpsReport = { id: Math.max(...reports.map((x) => x.id)) + 1, kind: "weekly", period_start: iso(ws), period_end: iso(now), created_at: iso(now), trigger: "manual",
        subject: "BlockID weekly report (manual)", to: "admin@blockid.au", emailed: smtpOk, email_reason: smtpOk ? null : NC, sent_at: smtpOk ? iso(now) : null };
      reports.unshift(r);
      return { ok: true, report: { ...r }, emailed: smtpOk, reason: smtpOk ? null : NC };
    })],
    ["POST", /^\/v1\/admin\/ops\/test-email$/, g((_m, b) => ({ ok: smtpOk, to: b?.to || "admin@blockid.au", reason: smtpOk ? null : NC }))],
  ];
}
