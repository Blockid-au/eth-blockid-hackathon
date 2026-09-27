"""Ops configuration (env; documented in docs/RUNBOOK-STUDIO.md "Operations").

OPS_ENABLED               1 (default) runs the monitor loop in the API; 0 disables checks, mail and reports
OPS_INTERVAL_SECONDS      60   seconds between monitor rounds
OPS_ALERT_TO              admin@blockid.au   incident emails (comma-separated list allowed)
OPS_REPORT_TO             = OPS_ALERT_TO     weekly / daily report emails
OPS_DAILY_DIGEST          0    1 = also send a daily digest at 08:00 Australia/Sydney
OPS_REPORT_TZ             Australia/Sydney
OPS_WEEKLY_AT             "MON 08:00"        weekday + local time of the weekly report
OPS_MAX_EMAILS_PER_HOUR   10
OPS_WARN_BATCH_MINUTES    15   warn incidents are batched into one email at most this often
OPS_REMINDER_HOURS        2    reminder for an incident still open (not acknowledged) after this long
OPS_REMINDER_REPEAT_HOURS 24   further reminders
OPS_NGINX_LOG_DIR         /host-logs/nginx   (compose mounts the host's /var/log/nginx read-only there)
OPS_TRAFFIC_HOSTS         eth.blockid.au,hr.blockid.au,scan.blockid.au
OPS_TRAFFIC_PARSE_SECONDS 3600 how often access logs are re-aggregated into ops_traffic_daily
OPS_TLS_HOSTS             eth.blockid.au,hr.blockid.au,scan.blockid.au
OPS_TLS_ORIGIN            ""   host/IP of the origin nginx (compose: host.docker.internal); "" = edge only
OPS_TLS_WARN_DAYS         14   (critical below OPS_TLS_CRIT_DAYS, default 3)
OPS_DISK_PATHS            /data,/host-logs/nginx,/   mount points checked with shutil.disk_usage
OPS_DISK_WARN_PCT / OPS_DISK_CRIT_PCT   80 / 90
OPS_5XX_WARN_PCT / OPS_5XX_CRIT_PCT     2 / 10   API 5xx share over the last 15 min (min OPS_5XX_MIN_COUNT=5)
OPS_HSK_WARN / OPS_HSK_CRIT             0.02 / 0.005   issuer HSK balance
OPS_ETH_WARN / OPS_ETH_CRIT             0.05 / 0.01    issuer Hoodi ETH balance
OPS_BLKD_WARN / OPS_BLKD_CRIT           10 / 1         issuer BLKD balance (it drips gas to new wallets)
OPS_DB_SIZE_WARN_GB       20
OPS_WORKER_STALE_SECONDS  300  worker heartbeat older than this -> critical
OPS_QUEUE_WARN_MINUTES / OPS_QUEUE_CRIT_MINUTES   15 / 60   oldest queued valuation / HR run
OPS_ERRORS_WARN           20   new error-log occurrences in 15 min -> warn
OPS_ERROR_RETENTION_DAYS  30
OPS_DEPLOY_LOG            /data/deploys.log  lines written by scripts/record-deploy.sh (weekly "deploys" section)
OPS_GIT_DIR               ""   optional read-only mount of the repo; `git log` of the week is added when readable
OPS_ADMIN_URL             {PUBLIC_BASE_URL}/admin/ops
OPS_RUNBOOK_URL           https://github.com/Blockid-au/eth-blockid/blob/main/docs/RUNBOOK-INCIDENTS.md
OPS_IP_SALT_SECRET        secret mixed into the daily visitor-hash salt (default: SESSION_SECRET)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _s(k: str, d: str = "") -> str:
    return os.environ.get(k, d).strip()


def _f(k: str, d: float) -> float:
    try:
        return float(_s(k, str(d)) or d)
    except ValueError:
        return d


def _i(k: str, d: int) -> int:
    return int(_f(k, d))


def _b(k: str, d: str) -> bool:
    return _s(k, d).lower() in ("1", "true", "yes", "on")


def _csv(k: str, d: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in _s(k, d).split(",") if x.strip())


@dataclass
class OpsConfig:
    enabled: bool = field(default_factory=lambda: _b("OPS_ENABLED", "1"))
    interval_s: float = field(default_factory=lambda: max(5.0, _f("OPS_INTERVAL_SECONDS", 60)))
    alert_to: str = field(default_factory=lambda: _s("OPS_ALERT_TO", "admin@blockid.au") or "admin@blockid.au")
    report_to: str = field(default_factory=lambda: _s("OPS_REPORT_TO") or _s("OPS_ALERT_TO", "admin@blockid.au")
                           or "admin@blockid.au")
    daily_digest: bool = field(default_factory=lambda: _b("OPS_DAILY_DIGEST", "0"))
    report_tz: str = field(default_factory=lambda: _s("OPS_REPORT_TZ", "Australia/Sydney") or "Australia/Sydney")
    weekly_at: str = field(default_factory=lambda: _s("OPS_WEEKLY_AT", "MON 08:00") or "MON 08:00")
    max_emails_per_hour: int = field(default_factory=lambda: _i("OPS_MAX_EMAILS_PER_HOUR", 10))
    warn_batch_minutes: float = field(default_factory=lambda: _f("OPS_WARN_BATCH_MINUTES", 15))
    reminder_hours: float = field(default_factory=lambda: _f("OPS_REMINDER_HOURS", 2))
    reminder_repeat_hours: float = field(default_factory=lambda: _f("OPS_REMINDER_REPEAT_HOURS", 24))
    nginx_log_dir: str = field(default_factory=lambda: _s("OPS_NGINX_LOG_DIR", "/host-logs/nginx"))
    traffic_hosts: tuple[str, ...] = field(default_factory=lambda: _csv(
        "OPS_TRAFFIC_HOSTS", "eth.blockid.au,hr.blockid.au,scan.blockid.au"))
    traffic_parse_s: float = field(default_factory=lambda: _f("OPS_TRAFFIC_PARSE_SECONDS", 3600))
    tls_hosts: tuple[str, ...] = field(default_factory=lambda: _csv(
        "OPS_TLS_HOSTS", "eth.blockid.au,hr.blockid.au,scan.blockid.au"))
    tls_origin: str = field(default_factory=lambda: _s("OPS_TLS_ORIGIN"))
    tls_warn_days: float = field(default_factory=lambda: _f("OPS_TLS_WARN_DAYS", 14))
    tls_crit_days: float = field(default_factory=lambda: _f("OPS_TLS_CRIT_DAYS", 3))
    disk_paths: tuple[str, ...] = field(default_factory=lambda: _csv("OPS_DISK_PATHS", "/data,/host-logs/nginx,/"))
    disk_warn_pct: float = field(default_factory=lambda: _f("OPS_DISK_WARN_PCT", 80))
    disk_crit_pct: float = field(default_factory=lambda: _f("OPS_DISK_CRIT_PCT", 90))
    err5xx_warn_pct: float = field(default_factory=lambda: _f("OPS_5XX_WARN_PCT", 2))
    err5xx_crit_pct: float = field(default_factory=lambda: _f("OPS_5XX_CRIT_PCT", 10))
    err5xx_min_count: int = field(default_factory=lambda: _i("OPS_5XX_MIN_COUNT", 5))
    hsk_warn: float = field(default_factory=lambda: _f("OPS_HSK_WARN", 0.02))
    hsk_crit: float = field(default_factory=lambda: _f("OPS_HSK_CRIT", 0.005))
    eth_warn: float = field(default_factory=lambda: _f("OPS_ETH_WARN", 0.05))
    eth_crit: float = field(default_factory=lambda: _f("OPS_ETH_CRIT", 0.01))
    blkd_warn: float = field(default_factory=lambda: _f("OPS_BLKD_WARN", 10))
    blkd_crit: float = field(default_factory=lambda: _f("OPS_BLKD_CRIT", 1))
    db_size_warn_gb: float = field(default_factory=lambda: _f("OPS_DB_SIZE_WARN_GB", 20))
    worker_stale_s: float = field(default_factory=lambda: _f("OPS_WORKER_STALE_SECONDS", 300))
    queue_warn_min: float = field(default_factory=lambda: _f("OPS_QUEUE_WARN_MINUTES", 15))
    queue_crit_min: float = field(default_factory=lambda: _f("OPS_QUEUE_CRIT_MINUTES", 60))
    errors_warn: int = field(default_factory=lambda: _i("OPS_ERRORS_WARN", 20))
    error_retention_days: int = field(default_factory=lambda: _i("OPS_ERROR_RETENTION_DAYS", 30))
    deploy_log: str = field(default_factory=lambda: _s("OPS_DEPLOY_LOG", "/data/deploys.log"))
    git_dir: str = field(default_factory=lambda: _s("OPS_GIT_DIR"))
    admin_url: str = field(default_factory=lambda: _s("OPS_ADMIN_URL") or (
        _s("PUBLIC_BASE_URL", "https://eth.blockid.au").rstrip("/") + "/admin/ops"))
    runbook_url: str = field(default_factory=lambda: _s(
        "OPS_RUNBOOK_URL", "https://github.com/Blockid-au/eth-blockid/blob/main/docs/RUNBOOK-INCIDENTS.md"))
    ip_salt_secret: str = field(default_factory=lambda: _s("OPS_IP_SALT_SECRET") or _s("SESSION_SECRET")
                                or "blockid-ops")

    def runbook_link(self, runbook_id: str) -> str:
        return f"{self.runbook_url}#{runbook_id}"

    @staticmethod
    def recipients(value: str) -> list[str]:
        return [x.strip() for x in value.split(",") if x.strip()]
