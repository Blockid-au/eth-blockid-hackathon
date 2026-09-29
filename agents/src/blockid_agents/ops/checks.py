"""Registry of ops checks (docs/PLAN-OPS.md §1, runbook docs/RUNBOOK-INCIDENTS.md).

A check = id, title, max severity, runbook id (anchor in RUNBOOK-INCIDENTS.md), impact, step-by-step fix, and a
`detect(env)` function returning one or more `Result`s. A result with status warn / critical / info opens (or
keeps open) the incident with fingerprint "<check id>[:<key>]"; ok resolves it; unknown means "cannot tell"
(not configured, data missing) and leaves any open incident untouched.

Adding monitoring for a new feature = add a function decorated with `@check(...)` here and a section with the same
runbook id in docs/RUNBOOK-INCIDENTS.md (tests/test_ops.py fails if the section is missing).

All probes are read-only: SELECT queries, GET /healthz-style endpoints, the issuer's GET /health (balances),
eth_blockNumber, a TLS handshake, shutil.disk_usage, reading nginx logs.
"""
from __future__ import annotations

import logging
import os
import shutil
import socket
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .config import OpsConfig

log = logging.getLogger(__name__)

STATUSES = ("ok", "info", "warn", "critical", "unknown")
RANK = {"ok": 0, "unknown": 0, "info": 1, "warn": 2, "critical": 3}
COMPOSE = "cd ~/blockid-eth-platform/deploy/vm-app && sudo docker compose --env-file /opt/blockid/app.env"


@dataclass
class Result:
    status: str
    detail: str
    key: str = ""
    title: str | None = None  # incident title (default: check title + key)
    data: dict = field(default_factory=dict)
    impact: str | None = None  # overrides the check's impact


@dataclass
class Check:
    id: str
    title: str
    severity: str  # the highest severity this check can raise
    runbook_id: str
    impact: str
    fix_steps: list[str]
    detect: Callable[["OpsEnv"], Any]
    confirm: int = 1  # consecutive failing rounds before an incident opens (flap guard for network probes)
    every_s: float = 0  # minimum seconds between runs (0 = every round)


REGISTRY: dict[str, Check] = {}


def check(id: str, title: str, severity: str, runbook_id: str, impact: str, fix: list[str], *, confirm: int = 1,
          every_s: float = 0):
    def deco(fn):
        REGISTRY[id] = Check(id, title, severity, runbook_id, impact, fix, fn, confirm, every_s)
        return fn
    return deco


# ------------------------------------------------------------------ probe environment
class OpsEnv:
    """What checks can read. Every external dependency is an attribute so tests swap in fakes."""

    def __init__(self, cfg: OpsConfig, settings=None, db=None, issuer=None, chain=None, *,
                 http_get: Callable[[str, float], tuple[int, Any]] | None = None,
                 tls_expiry: Callable[[str, str | None], datetime] | None = None,
                 disk_usage: Callable[[str], Any] | None = None, gateway: Callable[[], Any] | None = None,
                 mailer=None, now: Callable[[], datetime] | None = None):
        self.cfg, self.settings, self.db, self.issuer, self.chain = cfg, settings, db, issuer, chain
        self.http_get = http_get or _http_get
        self.tls_expiry = tls_expiry or _tls_expiry
        self.disk_usage = disk_usage or shutil.disk_usage
        self._gateway = gateway
        self.mailer = mailer
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.states: dict[str, dict] = {}  # per-check persistent data (ops_checks_state.data), set by the monitor
        self._memo: dict[str, Any] = {}

    def state(self, check_id: str) -> dict:
        return self.states.setdefault(check_id, {})

    def memo(self, key: str, fn: Callable[[], Any]) -> Any:
        """Once per round (issuer health / AI health are used by several checks)."""
        if key not in self._memo:
            try:
                self._memo[key] = ("ok", fn())
            except Exception as e:  # noqa: BLE001
                self._memo[key] = ("error", e)
        kind, v = self._memo[key]
        if kind == "error":
            raise v
        return v

    def new_round(self) -> None:
        self._memo.clear()

    def issuer_health(self) -> dict | None:
        if self.issuer is None:
            return None
        return self.memo("issuer", self.issuer.health)

    def ai_health(self) -> dict | None:
        if self._gateway is None:
            return None
        return self.memo("ai", lambda: self._gateway().health())


def _http_get(url: str, timeout: float = 5) -> tuple[int, Any]:
    import httpx

    r = httpx.get(url, timeout=timeout, follow_redirects=False, trust_env=False,
                  headers={"User-Agent": "blockid-ops-monitor/1 (bot)"})
    try:
        body = r.json()
    except ValueError:
        body = None
    return r.status_code, body


def _tls_expiry(host: str, connect_to: str | None = None, timeout: float = 5) -> datetime:
    """notAfter of the certificate served for `host` (SNI), connecting to `connect_to` (origin) or `host` (edge).
    Verifies the chain and hostname; an invalid / expired certificate raises ssl.SSLError."""
    ctx = ssl.create_default_context()
    with socket.create_connection((connect_to or host, 443), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as s:
            cert = s.getpeercert()
    return datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["notAfter"]), timezone.utc)


def _age_min(then: datetime | None, now: datetime) -> float | None:
    return None if then is None else (now - then).total_seconds() / 60


def _level(value: float, warn: float, crit: float, *, below: bool = False) -> str:
    """Threshold helper: value >= crit -> critical, >= warn -> warn (below=True inverts)."""
    if below:
        return "critical" if value < crit else "warn" if value < warn else "ok"
    return "critical" if value >= crit else "warn" if value >= warn else "ok"


# ================================================================== checks
@check("site.up", "Public site reachable", "critical", "site-down",
       "Visitors cannot load the page or the API; every flow on that host is down.",
       ["Open the URL in a browser; note the HTTP status (502/504 = nginx is up but the backend is not).",
        f"API: `{COMPOSE} ps agents-api` then `{COMPOSE} logs --tail=200 agents-api`.",
        f"Restart the API: `{COMPOSE} up -d --no-build agents-api`.",
        "nginx: `sudo nginx -t && sudo systemctl reload nginx`; `sudo tail -50 /var/log/nginx/<host>.error.log`.",
        "Blockscout (scan): `cd ~/blockid-eth-platform/deploy/blockscout && sudo docker compose "
        "--env-file /opt/blockid/blockscout.env ps` and restart `frontend` / `backend`."],
       confirm=2)
def _site_up(env: OpsEnv):
    out = []
    base = (env.settings.public_base_url if env.settings else "https://eth.blockid.au").rstrip("/")
    urls = [x.strip() for x in os.environ.get(
        "OPS_PROBE_URLS", f"{base}/api/healthz,{base}/,https://hr.blockid.au/,https://scan.blockid.au/").split(",")
        if x.strip()]
    for url in urls:
        key = url.split("://", 1)[-1].rstrip("/")
        try:
            t0 = time.monotonic()
            status, _ = env.http_get(url, 8)
            ms = round((time.monotonic() - t0) * 1000)
            ok = 200 <= status < 400
            out.append(Result("ok" if ok else "critical", f"{url} -> HTTP {status} in {ms} ms", key=key,
                              title=f"{key} is down (HTTP {status})", data={"status": status, "ms": ms}))
        except Exception as e:  # noqa: BLE001
            out.append(Result("critical", f"{url} unreachable: {str(e)[:200]}", key=key, title=f"{key} unreachable"))
    return out


@check("api.5xx_rate", "API 5xx rate (nginx)", "critical", "api-5xx",
       "Some API calls fail with a server error: users see failed actions or blank panels.",
       ["Top failing routes: `sudo awk '$9>=500' /var/log/nginx/eth.blockid.au.access.log | tail -50`.",
        "502/504 = backend down or slow: `sudo tail -50 /var/log/nginx/eth.blockid.au.error.log`.",
        "500 = application error: open Admin > Ops > Logs (errors with traceback) or "
        f"`{COMPOSE} logs --tail=300 agents-api | grep -i error`.",
        f"If the API container restarted in a loop: `{COMPOSE} ps` and fix the startup error, then "
        f"`{COMPOSE} up -d --no-build agents-api`."])
def _api_5xx(env: OpsEnv):
    from .traffic import recent_status

    host = (env.settings.public_base_url if env.settings else "https://eth.blockid.au").split("://")[-1].rstrip("/")
    path = os.path.join(env.cfg.nginx_log_dir, f"{host}.access.log")
    if not os.access(path, os.R_OK):
        return Result("unknown", f"{path} not readable (logs not mounted)")
    st = recent_status(path, env.now() - timedelta(minutes=15))
    total, bad = st["total"], st["5xx"]
    pct = 100.0 * bad / total if total else 0.0
    status = "ok"
    if bad >= env.cfg.err5xx_min_count:
        status = _level(pct, env.cfg.err5xx_warn_pct, env.cfg.err5xx_crit_pct)
    return Result(status, f"{pct:.1f} % 5xx in the last 15 min ({bad} / {total}); codes {st['codes'] or '-'}",
                  title=f"API errors: {pct:.0f} % of requests failing", data={**st, "pct": round(pct, 2)})


@check("app.errors", "Application errors (error log)", "warn", "app-errors",
       "Background jobs or requests are raising errors; some actions may silently fail.",
       ["Admin > Ops > Logs: sort by count, open the traceback of the newest fingerprint.",
        f"Container logs around the time: `{COMPOSE} logs --since=30m agents-api agents-worker issuer | "
        "grep '\"level\": \"ERROR\"'`.",
        "Fix the cause (config, upstream outage, bug); restart the affected container if it is wedged."])
def _app_errors(env: OpsEnv):
    if env.db is None:
        return Result("unknown", "no database")
    row = env.db.one("SELECT coalesce(sum(count),0)::bigint AS n FROM studio.ops_errors")
    total = int(row["n"])
    st = env.state("app.errors")
    prev = st.get("total")
    delta = 0 if prev is None else max(0, total - int(prev))
    now = time.time()
    ring = [x for x in st.get("ring", []) if x[0] > now - 900] + [[now, delta]]
    st.update(total=total, ring=ring)
    n = sum(x[1] for x in ring)
    top = env.db.all("SELECT source, logger, message, count FROM studio.ops_errors WHERE last_seen > now() - "
                     "interval '15 minutes' ORDER BY last_seen DESC LIMIT 3")
    status = "warn" if n >= env.cfg.errors_warn else "ok"
    return Result(status, f"{n} error log records in the last 15 min"
                  + (f"; latest: {top[0]['source']} {top[0]['logger']}: {top[0]['message'][:160]}" if top else ""),
                  title=f"{n} application errors in 15 min", data={"count_15m": n})


@check("worker.heartbeat", "AI worker alive", "critical", "worker-down",
       "Valuations and HR reviews are not processed; users wait on 'queued' forever.",
       [f"`{COMPOSE} ps agents-worker` (is it running / restarting?).",
        f"`{COMPOSE} logs --tail=200 agents-worker` for the crash or hang.",
        f"Restart: `{COMPOSE} restart agents-worker` (or `up -d --no-build agents-worker`).",
        "If it hangs on an LLM call, check Admin > AI health for a provider outage."])
def _worker_heartbeat(env: OpsEnv):
    if env.db is None:
        return Result("unknown", "no database")
    row = env.db.one("SELECT last_run_at, data FROM studio.ops_checks_state WHERE check_id='_hb:worker'")
    if not row or not row["last_run_at"]:
        return Result("unknown", "no worker heartbeat recorded yet (worker not upgraded to the ops build?)")
    age = (env.now() - row["last_run_at"]).total_seconds()
    status = "critical" if age > env.cfg.worker_stale_s else "ok"
    return Result(status, f"last heartbeat {int(age)} s ago", title=f"AI worker silent for {int(age // 60)} min",
                  data={"age_s": int(age), **(row["data"] or {})})


@check("jobs.backlog", "Job queue backlog", "critical", "queue-backlog",
       "New valuations / HR reviews wait longer than usual before they start.",
       ["Admin > Valuations / HR: how many are queued, since when.",
        f"Worker alive? `{COMPOSE} logs --tail=100 agents-worker`.",
        "Limits: VALUATIONS_MAX_ACTIVE / HR_MAX_ACTIVE in /opt/blockid/app.env; a stuck running job blocks the "
        "queue (see jobs.failures).",
        f"Restart the worker: `{COMPOSE} restart agents-worker`."])
def _backlog(env: OpsEnv):
    if env.db is None:
        return Result("unknown", "no database")
    now = env.now()
    out = []
    for key, table, label in (("valuations", "studio.valuations", "valuation"), ("hr", "studio.hr_teams", "HR run")):
        r = env.db.one(f"SELECT count(*) AS n, min(updated_at) AS oldest FROM {table} WHERE status='queued'")
        age = _age_min(r["oldest"], now) or 0
        status = _level(age, env.cfg.queue_warn_min, env.cfg.queue_crit_min) if r["n"] else "ok"
        out.append(Result(status, f"{r['n']} queued {label}s, oldest {age:.0f} min", key=key,
                          title=f"{r['n']} {label}s queued, oldest {age:.0f} min", data={"queued": r["n"],
                                                                                          "oldest_min": round(age)}))
    return out


@check("jobs.failures", "Valuation / HR failures and stalls", "warn", "job-failures",
       "Users see failed or never-finishing valuations / team reviews.",
       ["Admin > Valuations (or HR): open the failed rows, read `error`.",
        "Common causes: all LLM providers skipped (Admin > AI health), site unreachable, Brave quota.",
        f"Worker log: `{COMPOSE} logs --since=2h agents-worker | grep -i -E 'error|failed'`.",
        "Stalled running rows: restart the worker; the HR watchdog re-queues HR runs automatically."])
def _job_failures(env: OpsEnv):
    if env.db is None:
        return Result("unknown", "no database")
    v = env.db.one("SELECT count(*) FILTER (WHERE status='failed' AND updated_at > now() - interval '1 hour') AS "
                   "failed, count(*) FILTER (WHERE status='running' AND updated_at < now() - interval '30 minutes') "
                   "AS stalled FROM studio.valuations")
    h = env.db.one("SELECT count(*) FILTER (WHERE status='failed' AND updated_at > now() - interval '1 hour') AS "
                   "failed, count(*) FILTER (WHERE status='running' AND coalesce(heartbeat_at, updated_at) < now() - "
                   "interval '20 minutes') AS stalled FROM studio.hr_teams")
    out = []
    for key, n, what in (("valuations_failed", v["failed"], "valuations failed in the last hour"),
                         ("valuations_stalled", v["stalled"], "valuations running without progress for 30+ min"),
                         ("hr_failed", h["failed"], "HR runs failed in the last hour"),
                         ("hr_stalled", h["stalled"], "HR runs without heartbeat for 20+ min")):
        limit = 3 if key.endswith("failed") else 1
        out.append(Result("warn" if n >= limit else "ok", f"{n} {what}", key=key, title=f"{n} {what}",
                          data={"count": n}))
    return out


@check("issuer.health", "Issuer service", "critical", "issuer-down",
       "Approvals (issue, anchor, mint, dividends, transfers, gas drips) fail with 502; nothing reaches the chains.",
       [f"`{COMPOSE} ps issuer` and `{COMPOSE} logs --tail=200 issuer`.",
        "Keystore / password errors at startup: check /opt/blockid/keys (uid 10001, read-only) and issuer.env.",
        f"Restart: `{COMPOSE} up -d --no-build issuer`.",
        "Then Admin > Wallets shows balances again; re-run failed approvals (Re-sync)."],
       confirm=2)
def _issuer(env: OpsEnv):
    if env.issuer is None:
        return Result("unknown", "issuer not configured in this process")
    h = env.issuer_health() or {}
    if not h.get("ok"):
        return Result("critical", f"issuer /health failed: {str(h.get('error'))[:200]}",
                      title="Issuer service unreachable")
    q = int(h.get("queue") or 0)
    if q > 20:
        return Result("warn", f"issuer queue has {q} pending jobs", title=f"Issuer backlog: {q} jobs",
                      data={"queue": q})
    return Result("ok", f"issuer ok, {q} jobs pending", data={"queue": q})


WALLET_CHAINS = (("local", "local_balance", "BLKD", "BlockID Chain"), ("hoodi", "hoodi_balance", "ETH", "Hoodi"),
                 ("hsk", "hsk_balance", "HSK", "HashKey testnet"))


@check("wallet.balances", "Issuer gas balances", "critical", "wallet-balances",
       "When a balance runs out, anchoring / mirroring to that chain fails (companies end partially_anchored) and "
       "BLKD gas drips to new wallets stop.",
       ["Admin > Wallets shows the issuer address and balances (issuer 0x2567…5ddf).",
        "Hoodi ETH: request at https://hoodi-faucet.pk910.de (PoW faucet) to the issuer address.",
        "HSK (HashKey Chain testnet): use the HashKey testnet faucet (https://faucet.hsk.xyz) for the issuer address.",
        "BLKD: `sudo docker exec -it blockid-app-evmd-1 evmd tx bank send validator <bech32> <amount>ablkd "
        "--keyring-backend file --home /root/.evmd --chain-id blockid_262626-1 --gas-prices 10000000000ablkd -y` "
        "(bech32 via `evmd debug addr <0x…>`; see RUNBOOK-STUDIO.md Funding).",
        "Afterwards Re-sync partially_anchored companies from Admin."],
       every_s=300)
def _balances(env: OpsEnv):
    if env.issuer is None:
        return Result("unknown", "issuer not configured")
    h = env.issuer_health() or {}
    if not h.get("ok"):
        return Result("unknown", "issuer health unavailable")
    iss = h.get("issuer") or {}
    c = env.cfg
    thresholds = {"local": (c.blkd_warn, c.blkd_crit), "hoodi": (c.eth_warn, c.eth_crit),
                  "hsk": (c.hsk_warn, c.hsk_crit)}
    st = env.state("wallet.balances")
    today = env.now().date().isoformat()
    out = []
    for chain, field_, unit, label in WALLET_CHAINS:
        raw = iss.get(field_)
        if raw is None:
            out.append(Result("unknown", f"{label}: balance not available", key=chain))
            continue
        bal = int(raw) / 1e18
        hist = st.setdefault(chain, {})
        hist[today] = bal
        for d in sorted(hist)[:-15]:
            del hist[d]
        days_left = days_of_gas(hist)
        warn, crit = thresholds[chain]
        status = _level(bal, warn, crit, below=True)
        left = f"; ~{days_left:.0f} days left at the current burn" if days_left is not None else ""
        out.append(Result(status, f"{label} issuer balance {bal:.4f} {unit} (warn < {warn}){left}", key=chain,
                          title=f"Issuer {unit} low on {label}: {bal:.4f} {unit}",
                          data={"balance": bal, "unit": unit, "address": iss.get("address"), "days_left": days_left}))
    return out


def days_of_gas(hist: dict[str, float]) -> float | None:
    """Days until empty from daily samples {iso_day: balance} (average daily decrease, top-ups ignored)."""
    days = sorted(hist)[-8:]
    if len(days) < 2:
        return None
    drops = [max(0.0, hist[a] - hist[b]) for a, b in zip(days, days[1:])]
    burn = sum(drops) / len(drops)
    return None if burn <= 0 else hist[days[-1]] / burn


@check("chain.sync", "Chain sync (issue / anchor / mirror)", "warn", "chain-sync",
       "Some companies are not fully on every chain: Hoodi / HashKey views and proofs are missing or stale.",
       ["Admin > Companies: filter failed / partially_anchored; the row shows the chain error.",
        f"`{COMPOSE} logs --since=2h issuer | grep -i -E 'revert|error|insufficient'`.",
        "Usually gas: top up the issuer (see wallet.balances), then press Re-sync (approve-anchor) on the company.",
        "BlockID revert -> status failed: retry = approve-issue again."])
def _chain_sync(env: OpsEnv):
    if env.db is None:
        return Result("unknown", "no database")
    bad = env.db.all("SELECT ticker, status, coalesce(error,'') AS error FROM studio.companies WHERE status IN "
                     "('failed','partially_anchored') ORDER BY updated_at DESC LIMIT 20")
    stuck = env.db.all("SELECT ticker, status FROM studio.companies WHERE status IN ('issuing','anchoring') AND "
                       "updated_at < now() - interval '30 minutes' ORDER BY updated_at LIMIT 20")
    out = [Result("warn" if bad else "ok", (f"{len(bad)} companies failed / partially anchored: "
                                            + ", ".join(f"{r['ticker']} ({r['status']})" for r in bad[:8]))
                  if bad else "no failed companies", key="failed",
                  title=f"{len(bad)} companies failed or partially anchored",
                  data={"tickers": [r["ticker"] for r in bad]}),
           Result("warn" if stuck else "ok", (f"{len(stuck)} companies stuck in issuing/anchoring for 30+ min: "
                                              + ", ".join(r["ticker"] for r in stuck[:8])) if stuck else
                  "nothing stuck", key="stuck", title=f"{len(stuck)} companies stuck while syncing",
                  data={"tickers": [r["ticker"] for r in stuck]})]
    return out


@check("chain.blocks", "BlockID Chain producing blocks", "critical", "chain-halted",
       "No new blocks: every BlockID Chain transaction (issue, mint, transfers, dividends) hangs.",
       [f"`{COMPOSE} ps evmd` and `{COMPOSE} logs --tail=200 evmd`.",
        "`cast block-number --rpc-url http://127.0.0.1:8545` twice, 10 s apart.",
        "Disk full stops CometBFT: check disk.space. Restart: "
        f"`{COMPOSE} restart evmd` (single validator; data in /mnt/app-data/evmd)."],
       confirm=2)
def _blocks(env: OpsEnv):
    if env.chain is None:
        return Result("unknown", "no chain reader configured")
    try:
        n = int(env.chain.block_number())
    except Exception as e:  # noqa: BLE001
        return Result("critical", f"RPC error: {str(e)[:200]}", title="BlockID Chain RPC unreachable")
    st = env.state("chain.blocks")
    now = env.now().timestamp()
    if st.get("block") != n:
        st.update(block=n, since=now)
    stalled = now - float(st.get("since", now))
    status = "critical" if stalled >= 180 else "ok"
    return Result(status, f"block {n}, unchanged for {int(stalled)} s", data={"block": n, "stalled_s": int(stalled)},
                  title=f"BlockID Chain stopped at block {n} ({int(stalled // 60)} min)")


@check("bridge.health", "Claude bridge (search + complete)", "warn", "claude-bridge",
       "Claude web search / completion fall back to other providers; research quality drops, cap reached = no "
       "Claude until tomorrow.",
       ["`curl -s http://172.18.0.1:8765/healthz` on the host (daily counters).",
        "`sudo systemctl status claude-search-bridge` and `sudo journalctl -u claude-search-bridge -n 100`.",
        "Restart: `sudo systemctl restart claude-search-bridge`.",
        "Caps: /opt/blockid/search-bridge.env (BRIDGE_MAX_PER_DAY, BRIDGE_COMPLETE_MAX_PER_DAY); counters reset at "
        "midnight host time."],
       confirm=2)
def _bridge(env: OpsEnv):
    url = env.settings.claude_search_url if env.settings else ""
    if not url:
        return Result("unknown", "CLAUDE_SEARCH_URL not set")
    try:
        status, body = env.http_get(url.rstrip("/") + "/healthz", 4)
    except Exception as e:  # noqa: BLE001
        return [Result("warn", f"bridge unreachable: {str(e)[:200]}", key="up", title="Claude bridge unreachable")]
    if status != 200 or not isinstance(body, dict):
        return [Result("warn", f"bridge /healthz -> HTTP {status}", key="up", title="Claude bridge unhealthy")]
    out = [Result("ok", "bridge up", key="up")]
    for key, n, cap, label in (("search_cap", body.get("today"), body.get("max_per_day"), "web searches"),
                               ("complete_cap", body.get("complete_today"), body.get("complete_max_per_day"),
                                "completions")):
        if not cap:
            continue
        pct = 100.0 * int(n or 0) / int(cap)
        status_ = "warn" if pct >= 100 else "info" if pct >= 80 else "ok"
        out.append(Result(status_, f"{n}/{cap} {label} today ({pct:.0f} %)", key=key,
                          title=f"Claude bridge {label}: {pct:.0f} % of the daily cap", data={"pct": round(pct, 1)}))
    return out


@check("ai.models", "AI gateway models", "critical", "ai-gateway",
       "LLM calls fall back to other models (slower / lower quality); with every model down, valuations and HR "
       "reviews fail.",
       ["Admin > AI health: which models are open / skipped / paused and why (last_error).",
        "Circuit open = repeated failures: check the provider status page; it half-opens by itself.",
        "Skipped = quota: wait for the window reset, or add capacity (SAMBANOVA_MODELS / DEEPINFRA_MODELS in "
        "/opt/blockid/app.env, then `up -d --no-build --force-recreate agents-worker agents-api`).",
        "DeepInfra budget: DEEPINFRA_DAILY_BUDGET_USD (default 3) — raise it only deliberately."],
       every_s=120)
def _ai(env: OpsEnv):
    h = env.ai_health()
    if h is None:
        return Result("unknown", "AI gateway not available in this process")
    out = []
    llm = [m for m in h.get("models", []) if m.get("kind") == "llm"]
    for m in llm:
        s, pct = m.get("status"), float(m.get("usage_pct") or 0)
        if s == "open":
            st, why = "warn", "circuit open after failures"
        elif s == "skipped":
            st, why = "warn", m.get("status_reason") or f"quota {pct:.0f} %"
        elif pct >= 80:
            st, why = "info", f"quota {pct:.0f} %"
        else:
            st, why = "ok", s or "healthy"
        err = (m.get("last_error") or {}).get("error")
        out.append(Result(st, f"{m['id']}: {why}" + (f"; last error: {err[:120]}" if err and st != "ok" else ""),
                          key=m["id"], title=f"AI model {m.get('label') or m['id']}: {why}",
                          data={"status": s, "usage_pct": pct}))
    usable = [m for m in llm if m.get("status") in ("healthy", "demoted")]
    if llm:
        out.append(Result("critical" if not usable else "ok", f"{len(usable)}/{len(llm)} LLM models usable",
                          key="all", title="No AI model is usable"))
    for p in h.get("providers", []):
        if p.get("budget_today_usd"):
            spent, budget = float(p.get("spend_today_usd") or 0), float(p["budget_today_usd"])
            pct = 100 * spent / budget
            st = "warn" if pct >= 100 else "info" if pct >= 80 else "ok"
            out.append(Result(st, f"{p['label']} spend today ${spent:.2f} of ${budget:.2f} ({pct:.0f} %)",
                              key=f"budget:{p['id']}", title=f"{p['label']} daily budget {pct:.0f} % used",
                              data={"spent": spent, "budget": budget}))
    return out or Result("unknown", "no AI model configured")


@check("search.brave", "Brave search quota", "warn", "brave-quota",
       "Web research falls back to the Claude bridge or runs without search ('Search unavailable' warning).",
       ["Admin > AI health > search:brave windows (month).",
        "Brave dashboard (api.search.brave.com) for the real usage; BRAVE_MONTHLY_QUOTA in app.env (default 2000).",
        "Upgrade the plan or accept degraded search until the month resets."],
       every_s=300)
def _brave(env: OpsEnv):
    h = env.ai_health()
    if h is None:
        return Result("unknown", "AI gateway not available")
    ms = [m for m in h.get("models", []) if m.get("kind") == "search" and "brave" in m["id"]]
    if not ms:
        return Result("unknown", "Brave not configured")
    pct = max(float(m.get("usage_pct") or 0) for m in ms)
    st = "warn" if pct >= 80 else "ok"
    return Result(st, f"Brave quota {pct:.0f} % used", title=f"Brave search quota {pct:.0f} % used",
                  data={"pct": pct})


@check("db.postgres", "Postgres", "critical", "postgres",
       "Nothing works without the database: sign-in, pages, jobs, the monitor itself.",
       [f"`{COMPOSE} ps postgres` and `{COMPOSE} logs --tail=100 postgres`.",
        "Disk full is the usual cause (see disk.space); `df -h /mnt/app-data`.",
        f"Restart: `{COMPOSE} restart postgres`, then `{COMPOSE} restart agents-api agents-worker issuer`.",
        "Size: `sudo docker exec blockid-app-postgres-1 psql -U blockid -c \"SELECT relname, "
        "pg_size_pretty(pg_total_relation_size(relid)) FROM pg_statio_user_tables ORDER BY 2 DESC LIMIT 10\"`."])
def _postgres(env: OpsEnv):
    if env.db is None:
        return Result("unknown", "no database configured")
    try:
        r = env.db.one("SELECT pg_database_size(current_database()) AS b")
    except Exception as e:  # noqa: BLE001
        return Result("critical", f"query failed: {str(e)[:200]}", title="Postgres unreachable")
    gb = int(r["b"]) / 1e9
    st = "warn" if gb >= env.cfg.db_size_warn_gb else "ok"
    return Result(st, f"database size {gb:.2f} GB", title=f"Database size {gb:.1f} GB", data={"gb": round(gb, 3)})


@check("disk.space", "Disk space", "critical", "disk-space",
       "A full disk stops Postgres, the chain node and logging; the whole site goes down.",
       ["`df -h / /mnt/app-data` and `sudo du -xh --max-depth=2 /mnt/app-data | sort -h | tail`.",
        "Docker: `sudo docker system df`; `sudo docker image prune -f` and `sudo docker builder prune -f` "
        "(never `volume prune`).",
        "Logs: `sudo journalctl --vacuum-time=7d`; nginx logs rotate daily (14 days).",
        "Still short: grow the disk in GCP and `sudo resize2fs`."],
       every_s=300)
def _disk(env: OpsEnv):
    out, seen = [], set()
    for path in env.cfg.disk_paths:
        if not os.path.exists(path):
            continue
        try:
            dev = os.stat(path).st_dev
            if dev in seen:
                continue
            seen.add(dev)
            u = env.disk_usage(path)
        except OSError:
            continue
        pct = 100.0 * u.used / u.total if u.total else 0
        st = _level(pct, env.cfg.disk_warn_pct, env.cfg.disk_crit_pct)
        out.append(Result(st, f"{path}: {pct:.0f} % used, {u.free / 1e9:.1f} GB free", key=path,
                          title=f"Disk {pct:.0f} % full ({path})", data={"pct": round(pct, 1),
                                                                        "free_gb": round(u.free / 1e9, 1)}))
    return out or Result("unknown", "no configured path exists")


@check("tls.expiry", "TLS certificates", "critical", "tls-expiry",
       "When the certificate expires, browsers (edge) or Cloudflare (origin, Full strict) refuse the connection.",
       ["Origin (certbot on the host): `sudo certbot certificates`; renew with `sudo certbot renew` then "
        "`sudo systemctl reload nginx`. Check the timer: `systemctl list-timers | grep certbot`.",
        "Edge (Cloudflare): certificates renew automatically; check SSL/TLS > Edge Certificates in Cloudflare.",
        "Verify: `echo | openssl s_client -connect 127.0.0.1:443 -servername <host> 2>/dev/null | "
        "openssl x509 -noout -enddate`."],
       every_s=3600, confirm=2)
def _tls(env: OpsEnv):
    out = []
    targets = [(h, None) for h in env.cfg.tls_hosts]
    if env.cfg.tls_origin:
        targets += [(h, env.cfg.tls_origin) for h in env.cfg.tls_hosts]
    for host, via in targets:
        key = host + ("@origin" if via else "")
        where = "origin" if via else "edge"
        try:
            exp = env.tls_expiry(host, via)
        except Exception as e:  # noqa: BLE001
            out.append(Result("critical" if "expired" in str(e).lower() else "warn",
                              f"{host} ({where}): TLS check failed: {str(e)[:200]}", key=key,
                              title=f"TLS problem on {host} ({where})"))
            continue
        days = (exp - env.now()).total_seconds() / 86400
        st = _level(days, env.cfg.tls_warn_days, env.cfg.tls_crit_days, below=True)
        out.append(Result(st, f"{host} ({where}) certificate expires {exp.date()} ({days:.0f} days)", key=key,
                          title=f"TLS certificate for {host} ({where}) expires in {days:.0f} days",
                          data={"expires": exp.isoformat(), "days": round(days, 1)}))
    return out


AUTOMATION_LOGGERS = ("blockid_agents.studio.dividend_policy", "blockid_agents.studio.offerings")


@check("automation.errors", "Dividend / offering automation", "warn", "automation",
       "Automatic dividends or offering closes/settlements did not run; investors do not see payouts on time.",
       ["Admin > Ops > Logs filtered by dividend_policy / offerings: read the traceback.",
        "Admin > Offerings: rows in `failed` show the error; retry settlement from there.",
        f"`{COMPOSE} logs --since=1h agents-api | grep -E 'dividend|offering'`.",
        "Issuer down or out of gas is the usual cause (see issuer.health, wallet.balances)."])
def _automation(env: OpsEnv):
    if env.db is None:
        return Result("unknown", "no database")
    errs = env.db.all("SELECT logger, message, count FROM studio.ops_errors WHERE logger = ANY(%s) AND last_seen > "
                      "now() - interval '30 minutes' ORDER BY last_seen DESC", (list(AUTOMATION_LOGGERS),))
    failed = env.db.one("SELECT count(*) AS n FROM studio.offerings WHERE status='failed'")["n"]
    div = env.db.one("SELECT count(*) AS n FROM studio.dividends WHERE status='failed' OR (status='paying' AND "
                     "created_at < now() - interval '2 hours')")["n"]
    return [
        Result("warn" if errs else "ok", (f"{len(errs)} automation errors in 30 min; latest: "
                                          f"{errs[0]['message'][:160]}") if errs else "no automation errors",
               key="errors", title="Dividend / offering automation errors"),
        Result("warn" if failed else "ok", f"{failed} offerings in status failed", key="offerings",
               title=f"{failed} offerings failed"),
        Result("warn" if div else "ok", f"{div} dividends failed or paying for 2+ h", key="dividends",
               title=f"{div} dividends failed / stuck"),
    ]


@check("email.delivery", "Email delivery", "warn", "email-delivery",
       "Incident emails, reports and welcome emails are not delivered (they stay stored in Admin > Ops).",
       ["Admin > Ops > send test email; the error text says why (auth, TLS, relay not allowed).",
        "App Password: SMTP_HOST=smtp.gmail.com SMTP_PORT=587 SMTP_USER=admin@blockid.au SMTP_PASSWORD=<app password>.",
        "Workspace relay: SMTP_HOST=smtp-relay.gmail.com with the VM public IP allow-listed (ephemeral; re-allow after a stop/start).",
        f"Edit /opt/blockid/app.env then `{COMPOSE} up -d --no-build --force-recreate agents-api`."])
def _email(env: OpsEnv):
    if env.mailer is None or not env.mailer.configured:
        return Result("unknown", "SMTP not configured: emails are stored, not sent")
    from ..studio import mailer as mailer_mod

    recent = [x for x in mailer_mod.RECENT if x[0] > time.time() - 7200][-3:]
    if env.db is not None:
        rows = env.db.all("SELECT ok, error FROM studio.ops_mail_log WHERE at > now() - interval '2 hours' "
                          "ORDER BY id DESC LIMIT 3")
        if len(rows) >= len(recent):
            recent = [(0, r["ok"], r["error"]) for r in rows]
    if len(recent) >= 2 and not any(ok for _, ok, _ in recent):
        return Result("warn", f"last {len(recent)} sends failed: {recent[-1][2] or recent[0][2]}",
                      title="Email sending fails")
    return Result("ok", "recent sends ok" if recent else "no recent sends")


def run_check(c: Check, env: OpsEnv) -> list[Result]:
    try:
        r = c.detect(env)
    except Exception as e:  # noqa: BLE001 - a broken probe must not stop the round
        log.warning("check %s raised: %s", c.id, e)
        return [Result("unknown", f"check error: {type(e).__name__}: {str(e)[:200]}")]
    rs = r if isinstance(r, list) else [r]
    for x in rs:
        if x.status not in STATUSES:
            x.status = "unknown"
    return rs
