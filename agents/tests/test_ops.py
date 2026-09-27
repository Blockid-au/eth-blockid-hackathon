"""Ops: check registry, incident lifecycle + email policy, error capture, nginx traffic parser, usage stats, weekly
report, leader lock, admin API (docs/PLAN-OPS.md). Offline tests use fakes; the Postgres parts run against
TEST_DATABASE_URL (skipped when unset)."""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from blockid_agents.ops import checks as ck
from blockid_agents.ops import mail, traffic
from blockid_agents.ops.checks import REGISTRY, Check, OpsEnv, Result, run_check
from blockid_agents.ops.config import OpsConfig
from blockid_agents.ops.errors import JsonFormatter, fingerprint, merge_rows, record_to_row
from blockid_agents.ops.report import daily_slot, weekly_slot

from test_studio import ADMIN_KEY, USER_KEY, needs_db, siwe_login, studio_env  # noqa: F401 (fixture)

TEST_DB = os.environ.get("TEST_DATABASE_URL", "")
ROOT = Path(__file__).resolve().parents[2]
SAMPLE = Path(__file__).with_name("fixtures") / "nginx-access-sample.log"
NOW = datetime(2026, 9, 27, 12, 50, tzinfo=timezone.utc)


def cfg(**kw) -> OpsConfig:
    c = OpsConfig()
    c.alert_to = c.report_to = "ops@example.test"
    c.ip_salt_secret = "salt-secret"
    for k, v in kw.items():
        setattr(c, k, v)
    return c


class FakeIssuer:
    def __init__(self, health):
        self.h = health

    def health(self):
        return self.h


def env(**kw) -> OpsEnv:
    settings = SimpleNamespace(public_base_url="https://eth.blockid.au", claude_search_url="http://bridge:8765")
    e = OpsEnv(kw.pop("cfg", cfg()), kw.pop("settings", settings), kw.pop("db", None), kw.pop("issuer", None),
               kw.pop("chain", None), now=lambda: NOW, **kw)
    return e


# ================================================================== registry
def test_registry_is_complete_and_every_runbook_section_exists():
    doc = (ROOT / "docs" / "RUNBOOK-INCIDENTS.md").read_text()
    assert len(REGISTRY) >= 15
    for c in REGISTRY.values():
        assert re.fullmatch(r"[a-z0-9]+\.[a-z0-9_]+", c.id)
        assert c.severity in ("info", "warn", "critical")
        assert c.impact and c.fix_steps and all(isinstance(s, str) and s for s in c.fix_steps)
        assert f'<a id="{c.runbook_id}"></a>' in doc, f"RUNBOOK-INCIDENTS.md lacks section {c.runbook_id}"
        assert f"\n## {c.runbook_id}\n" in doc, f"heading slug must equal the runbook id {c.runbook_id}"
        assert f"`{c.id}`" in doc, f"RUNBOOK-INCIDENTS.md does not mention check {c.id}"
    for must in ("site.up", "api.5xx_rate", "worker.heartbeat", "jobs.backlog", "issuer.health", "wallet.balances",
                 "chain.sync", "chain.blocks", "bridge.health", "ai.models", "search.brave", "db.postgres",
                 "disk.space", "tls.expiry", "automation.errors", "email.delivery"):
        assert must in REGISTRY


def test_balance_check_thresholds_and_days_left():
    wei = 10**18
    e = env(issuer=FakeIssuer({"ok": True, "issuer": {"address": "0x2567", "local_balance": str(50 * wei),
                                                      "hoodi_balance": str(wei // 25), "hsk_balance": str(wei // 250)}}))
    e.state("wallet.balances")["hsk"] = {"2026-09-25": 0.012, "2026-09-26": 0.008}
    rs = {r.key: r for r in run_check(REGISTRY["wallet.balances"], e)}
    assert rs["local"].status == "ok"
    assert rs["hoodi"].status == "warn" and "0.0400 ETH" in rs["hoodi"].detail
    assert rs["hsk"].status == "critical"  # 0.004 < 0.005
    assert rs["hsk"].data["days_left"] == pytest.approx(0.004 / 0.004)
    assert ck.days_of_gas({"a": 1.0}) is None and ck.days_of_gas({"2026-01-01": 1, "2026-01-02": 2}) is None


def test_issuer_down_disk_tls_site_bridge_ai_checks():
    e = env(issuer=FakeIssuer({"ok": False, "error": "connection refused"}))
    assert run_check(REGISTRY["issuer.health"], e)[0].status == "critical"
    assert run_check(REGISTRY["wallet.balances"], e)[0].status == "unknown"

    usage = SimpleNamespace(total=100, used=91, free=9 * 10**9)
    e = env(cfg=cfg(disk_paths=("/",)), disk_usage=lambda p: usage)
    assert run_check(REGISTRY["disk.space"], e)[0].status == "critical"
    usage.used = 85
    assert run_check(REGISTRY["disk.space"], e)[0].status == "warn"

    exp = {"eth.blockid.au": NOW + timedelta(days=60), "hr.blockid.au": NOW + timedelta(days=10)}

    def tls(host, via):
        if via:
            raise OSError("certificate verify failed: certificate has expired")
        return exp.get(host, NOW + timedelta(days=2))

    rs = {r.key: r.status for r in run_check(REGISTRY["tls.expiry"], env(tls_expiry=tls, cfg=cfg(tls_origin="h")))}
    assert rs["eth.blockid.au"] == "ok" and rs["hr.blockid.au"] == "warn" and rs["scan.blockid.au"] == "critical"
    assert rs["eth.blockid.au@origin"] == "critical"

    def http(url, timeout):
        if "hr." in url:
            raise OSError("timeout")
        if "healthz" in url and "bridge" in url:
            return 200, {"ok": True, "today": 150, "max_per_day": 150, "complete_today": 10,
                         "complete_max_per_day": 300}
        return (502, None) if "scan." in url else (200, {"ok": True})

    e = env(http_get=http)
    rs = {r.key: r.status for r in run_check(REGISTRY["site.up"], e)}
    assert rs == {"eth.blockid.au/api/healthz": "ok", "eth.blockid.au": "ok", "hr.blockid.au": "critical",
                  "scan.blockid.au": "critical"}
    rs = {r.key: r.status for r in run_check(REGISTRY["bridge.health"], e)}
    assert rs == {"up": "ok", "search_cap": "warn", "complete_cap": "ok"}

    health = {"models": [
        {"id": "sambanova:A", "kind": "llm", "status": "open", "usage_pct": 10, "last_error": {"error": "500"}},
        {"id": "deepinfra:B", "kind": "llm", "status": "demoted", "usage_pct": 85},
        {"id": "search:brave", "kind": "search", "status": "healthy", "usage_pct": 90}],
        "providers": [{"id": "deepinfra", "label": "DeepInfra", "spend_today_usd": 3.2, "budget_today_usd": 3}]}
    e = env(gateway=lambda: SimpleNamespace(health=lambda: health))
    rs = {r.key: r.status for r in run_check(REGISTRY["ai.models"], e)}
    assert rs == {"sambanova:A": "warn", "deepinfra:B": "info", "all": "ok", "budget:deepinfra": "warn"}
    assert run_check(REGISTRY["search.brave"], e)[0].status == "warn"
    health["models"][1]["status"] = "skipped"
    e.new_round()
    assert {r.key: r.status for r in run_check(REGISTRY["ai.models"], e)}["all"] == "critical"


def test_broken_check_is_unknown_not_an_exception():
    c = Check("x.boom", "Boom", "warn", "x", "i", ["s"], lambda e: 1 / 0)
    r = run_check(c, env())
    assert r[0].status == "unknown" and "ZeroDivisionError" in r[0].detail


def test_chain_blocks_detects_a_halt():
    chain = SimpleNamespace(block_number=lambda: 100)
    t = [NOW]
    e = env(chain=chain)
    e.now = lambda: t[0]
    assert run_check(REGISTRY["chain.blocks"], e)[0].status == "ok"
    t[0] = NOW + timedelta(minutes=4)
    assert run_check(REGISTRY["chain.blocks"], e)[0].status == "critical"


# ================================================================== nginx parser
def test_nginx_parser_bots_pages_and_hashing():
    lines = SAMPLE.read_text().splitlines()
    h = traffic.parse_line(lines[0])
    assert h.status == 200 and h.path == "/" and h.at == datetime(2026, 9, 27, 12, 45, 38, tzinfo=timezone.utc)
    assert traffic.parse_line("this is not a log line") is None
    assert traffic.parse_line(lines[4]).country == "AU"
    bots = [traffic.is_bot(traffic.parse_line(x)) for x in lines[:11]]
    assert bots == [False] * 6 + [True] * 5  # googlebot, wp-login probe, HeadlessChrome, curl, TLS garbage
    assert traffic.normalise_path("/r/Zq3xT9vK2mW8pL4nR7sY1b?x=1") == "/r/{id}"
    assert traffic.normalise_path("/tx/0x25300d49ec50a46c569ca876ea92ef3590b6aa9c") == "/tx/{id}"
    days = traffic.aggregate(lines, "salt-secret", own_hosts=["eth.blockid.au"])
    d = days[datetime(2026, 9, 27).date()]
    assert d["requests"] == 11 and d["bot_requests"] == 5 and d["status_5xx"] == 1 and d["status_4xx"] == 3
    assert d["api_requests"] == 3
    assert d["page_views"] == 3 and d["unique_visitors"] == 2
    assert {p["path"] for p in d["top_pages"]} == {"/", "/i/offerings/2", "/r/{id}"}
    assert d["top_referrers"] == [{"referrer": "google.com", "count": 1}, {"referrer": "t.co", "count": 1}] or \
        {r["referrer"] for r in d["top_referrers"]} == {"google.com", "t.co"}
    assert d["countries"] == [{"country": "AU", "count": 2}]
    assert days[datetime(2026, 9, 28).date()]["unique_visitors"] == 1
    blob = json.dumps({str(k): v for k, v in days.items()})
    assert "203.0.113" not in blob and "198.51.100" not in blob and "Mozilla" not in blob
    # the visitor hash depends on the day (salt rotates) and the secret, never equals the IP
    s1 = traffic.day_salt("k", datetime(2026, 9, 27).date())
    s2 = traffic.day_salt("k", datetime(2026, 9, 28).date())
    assert traffic.visitor_hash(s1, "203.0.113.10", "ua") != traffic.visitor_hash(s2, "203.0.113.10", "ua")
    assert traffic.visitor_hash(s1, "1.2.3.4", "ua") == traffic.visitor_hash(s1, "1.2.3.4", "ua")


def test_recent_5xx_rate_from_log_tail(tmp_path):
    (tmp_path / "eth.blockid.au.access.log").write_text(SAMPLE.read_text())
    st = traffic.recent_status(str(tmp_path / "eth.blockid.au.access.log"), NOW - timedelta(minutes=15))
    assert st == {"total": 3, "5xx": 1, "codes": {"502": 1}}
    e = env(cfg=cfg(nginx_log_dir=str(tmp_path), err5xx_min_count=1))
    r = run_check(REGISTRY["api.5xx_rate"], e)[0]
    assert r.status == "critical" and "33.3 %" in r.detail
    assert run_check(REGISTRY["api.5xx_rate"], env(cfg=cfg(nginx_log_dir=str(tmp_path / "nope"))))[0].status == \
        "unknown"
    assert traffic.logs_readable(str(tmp_path), ["eth.blockid.au"]) == (True, "ok")
    assert traffic.logs_readable(str(tmp_path / "x"), ["eth.blockid.au"])[0] is False


# ================================================================== logs
def test_error_fingerprint_json_formatter_and_merge():
    assert fingerprint("api", "l", "user 123 failed at 0xabc", None, []) == \
        fingerprint("api", "l", "user 456 failed at 0xdef", None, [])
    try:
        raise ValueError("boom 42")
    except ValueError:
        rec = logging.getLogger("t").makeRecord("t", logging.ERROR, "f", 1, "job %s crashed", (7,),
                                                exc_info=__import__("sys").exc_info())
    row = record_to_row(rec, "worker")
    assert row["source"] == "worker" and "ValueError: boom 42" in row["message"] and "Traceback" in row["traceback"]
    merged = merge_rows([row, dict(row, at=row["at"] + timedelta(seconds=1), message="later")])
    assert len(merged) == 1 and merged[0]["count"] == 2 and merged[0]["message"] == "later"
    rec.request_id = "req-12345678"
    out = json.loads(JsonFormatter().format(rec))
    assert out["level"] == "ERROR" and out["msg"] == "job 7 crashed" and out["request_id"] == "req-12345678"
    assert "exc" in out


# ================================================================== schedule + templates
def test_weekly_and_daily_slots_in_sydney():
    c = cfg()
    # Mon 28 Sep 2026 08:00 AEST = Sun 27 Sep 22:00 UTC
    assert weekly_slot(datetime(2026, 9, 27, 22, 0, tzinfo=timezone.utc), c) == \
        datetime(2026, 9, 27, 22, 0, tzinfo=timezone.utc)
    assert weekly_slot(datetime(2026, 9, 27, 21, 59, tzinfo=timezone.utc), c) == \
        datetime(2026, 9, 20, 22, 0, tzinfo=timezone.utc)
    # after DST starts (4 Oct 2026) 08:00 AEDT = 21:00 UTC
    assert weekly_slot(datetime(2026, 10, 5, 23, 0, tzinfo=timezone.utc), c) == \
        datetime(2026, 10, 4, 21, 0, tzinfo=timezone.utc)
    assert daily_slot(datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc), c) == \
        datetime(2026, 9, 26, 22, 0, tzinfo=timezone.utc)


def test_incident_email_has_what_since_impact_fix_and_links():
    c = cfg()
    inc = {"id": 5, "severity": "critical", "title": "Issuer HSK low", "detail": "0.004 HSK",
           "opened_at": (NOW - timedelta(minutes=30)).isoformat(), "occurrences": 3, "impact": "anchoring fails",
           "fix_steps": ["Top up at the faucet", "Re-sync"], "runbook_url": c.runbook_link("wallet-balances")}
    subject, text, html = mail.incidents_email("critical", [inc], c, NOW)
    assert subject.startswith("[BlockID CRITICAL] Issuer HSK low")
    for s in ("What: 0.004 HSK", "Since: 2026-09-27 12:20 UTC", "30 min ago", "Impact: anchoring fails",
              "1. Top up at the faucet", "2. Re-sync", "?incident=5", "#wallet-balances", "docker compose"):
        assert s in text
    assert "<ol" in html and "Top up at the faucet" in html


# ================================================================== Postgres
class FakeMailer:
    def __init__(self, configured=True, fail=False):
        self.configured, self.fail = configured, fail
        self.sent: list[tuple[str, str]] = []
        self.last_error = None

    def send(self, to, subject, text, html=None):
        if self.fail:
            self.last_error = "SMTPAuthenticationError: bad password"
            return False
        self.sent.append((to, subject))
        return True


@pytest.fixture
def opsdb():
    from blockid_agents.studio.db import Studio

    db = Studio(TEST_DB)
    db.exec("DROP SCHEMA IF EXISTS studio CASCADE")
    db.apply_schema()
    yield db
    db.close()


def _chk(id_="t.check", sev="critical", confirm=1):
    return Check(id_, "Test check", sev, "site-down", "things break", ["step one", "step two"], lambda e: [],
                 confirm=confirm)


@needs_db
def test_incident_lifecycle_dedupe_escalate_resolve_reopen(opsdb):
    from blockid_agents.ops.incidents import IncidentStore

    c = _chk()
    st = IncidentStore(opsdb, cfg(), {c.id: c})
    streaks: dict = {}
    a = st.apply(c, [Result("warn", "slow", key="k1")], streaks, NOW)
    assert a[0]["action"] == "opened"
    iid = a[0]["id"]
    assert st.apply(c, [Result("warn", "slower", key="k1")], streaks, NOW)[0] == {"fp": "t.check:k1",
                                                                                   "action": "seen", "id": iid}
    inc = st.get(iid)
    assert inc["occurrences"] == 2 and inc["detail"] == "slower" and inc["fix_steps"] == ["step one", "step two"]
    opsdb.exec("UPDATE studio.ops_incidents SET emailed=true WHERE id=%s", (iid,))
    assert st.apply(c, [Result("critical", "down", key="k1")], streaks, NOW)[0]["action"] == "escalated"
    inc = st.get(iid)
    assert inc["severity"] == "critical" and inc["emailed"] is False  # escalation re-arms the email
    # severity is capped at the check's max
    w = _chk("t.warnonly", "warn")
    st.registry[w.id] = w
    wid = st.apply(w, [Result("critical", "x")], {}, NOW)[0]["id"]
    assert st.get(wid)["severity"] == "warn"
    # ok resolves; failing again within 30 min re-opens the same incident
    assert st.apply(c, [Result("ok", "fine", key="k1")], streaks, NOW)[0]["action"] == "resolved"
    assert st.get(iid)["status"] == "resolved" and st.get(iid)["resolved_by"] == "auto"
    assert st.apply(c, [Result("warn", "again", key="k1")], streaks, NOW + timedelta(minutes=5))[0] == \
        {"fp": "t.check:k1", "action": "reopened", "id": iid}
    # a key no longer reported is resolved
    acts = st.apply(c, [Result("ok", "other", key="k2")], streaks, NOW)
    assert {"fp": "t.check:k1", "action": "resolved", "id": iid} in acts
    # confirm=2: first failing round is only pending
    c2 = _chk("t.flappy", confirm=2)
    st.registry[c2.id] = c2
    s2: dict = {}
    assert st.apply(c2, [Result("critical", "x")], s2, NOW)[0]["action"] == "pending"
    assert st.apply(c2, [Result("critical", "x")], s2, NOW)[0]["action"] == "opened"
    # admin ack / resolve
    fid = st.active_for("t.flappy")["id"]
    assert st.acknowledge(fid, "admin", "on it")["status"] == "acknowledged"
    assert st.resolve(fid, "admin")["resolved_by"] == "admin"
    with pytest.raises(ValueError):
        st.resolve(fid, "admin")
    kinds = [e["kind"] for e in st.events(iid)]
    assert kinds[:3] == ["opened", "escalated", "resolved"] and "reopened" in kinds
    # at most one active incident per fingerprint (partial unique index)
    from psycopg.errors import UniqueViolation

    st.apply(c, [Result("warn", "x", key="u")], {}, NOW)
    with pytest.raises(UniqueViolation):
        opsdb.exec("INSERT INTO studio.ops_incidents (fingerprint, check_id, title, severity) VALUES "
                   "('t.check:u','t.check','dup','warn')")


@needs_db
def test_email_policy_batching_rate_limit_reminder_resolve(opsdb):
    from blockid_agents.ops.incidents import IncidentStore, Notifier

    crit, warn = _chk("t.crit", "critical"), _chk("t.warn", "warn")
    reg = {crit.id: crit, warn.id: warn}
    c = cfg(max_emails_per_hour=3)
    st = IncidentStore(opsdb, c, reg)
    m = FakeMailer()
    n = Notifier(opsdb, m, c, st)
    st.apply(crit, [Result("critical", "api down")], {}, NOW)
    st.apply(warn, [Result("warn", "slow", key="a")], {}, NOW)
    out = n.run(NOW)
    assert out["sent"] == ["critical", "warn"] and len(m.sent) == 2
    assert "[BlockID CRITICAL]" in m.sent[0][1] and m.sent[0][0] == "ops@example.test"
    # a second warn within 15 min waits for the next digest
    st.apply(warn, [Result("warn", "slow", key="a"), Result("warn", "slower", key="b")], {}, NOW)
    assert n.run(NOW + timedelta(minutes=5))["sent"] == []
    assert st.active_for("t.warn:b")["email_reason"].startswith("batched")
    assert n.run(NOW + timedelta(minutes=16))["sent"] == ["warn"]
    # rate limit: 3 per hour already used -> the resolve email waits
    st.apply(warn, [Result("ok", "fine", key="a"), Result("warn", "x", key="b")], {}, NOW + timedelta(minutes=17))
    out = n.run(NOW + timedelta(minutes=18))
    assert out["sent"] == [] and out["skipped"] == "rate limited"
    # an hour later the resolve goes out
    out = n.run(NOW + timedelta(minutes=80))
    assert "resolved" in out["sent"] and any("[BlockID resolved]" in s for _, s in m.sent)
    # reminder after 2 h for incidents still open and not acknowledged (the ack'd one is skipped)
    st.acknowledge(st.active_for("t.warn:b")["id"], "admin")
    out = n.run(NOW + timedelta(hours=2, minutes=30))
    assert "reminder" in out["sent"] and "still open" in m.sent[-1][1]
    assert n.run(NOW + timedelta(hours=3))["sent"] == []  # next reminder only after 24 h
    rows = opsdb.all("SELECT kind, ok FROM studio.ops_mail_log ORDER BY id")
    assert [r["kind"] for r in rows] == ["critical", "warn", "warn", "resolved", "reminder"]


@needs_db
def test_smtp_missing_keeps_everything_and_sends_later(opsdb):
    from blockid_agents.ops.incidents import IncidentStore, Notifier

    crit = _chk("t.crit")
    c = cfg()
    st = IncidentStore(opsdb, c, {crit.id: crit})
    iid = st.apply(crit, [Result("critical", "down")], {}, NOW)[0]["id"]
    m = FakeMailer(configured=False)
    n = Notifier(opsdb, m, c, st)
    assert n.run(NOW)["skipped"] == "SMTP not configured"
    inc = st.get(iid)
    assert inc["emailed"] is False and inc["email_reason"] == "SMTP not configured"
    assert n.unsent_count() == 1
    # SMTP configured but failing: reason stored, back-off for 10 min, then retried
    m.configured, m.fail = True, True
    n.run(NOW + timedelta(minutes=1))
    assert st.get(iid)["email_reason"].startswith("send failed: SMTPAuthenticationError")
    assert n.run(NOW + timedelta(minutes=2))["skipped"].startswith("send failed")  # back-off
    m.fail = False
    assert n.run(NOW + timedelta(minutes=12))["sent"] == ["critical"]
    inc = st.get(iid)
    assert inc["emailed"] is True and inc["email_reason"] is None
    ev = [e["kind"] for e in st.events(iid)]
    assert "email_failed" in ev and "emailed" in ev
    # an incident resolved before it could be emailed produces no resolve email
    st.apply(crit, [Result("ok", "fine")], {}, NOW + timedelta(minutes=13))
    m2 = _chk("t.other")
    st.registry[m2.id] = m2
    oid = st.apply(m2, [Result("critical", "x")], {}, NOW + timedelta(minutes=13))[0]["id"]
    st.apply(m2, [Result("ok", "y")], {}, NOW + timedelta(minutes=14))
    out = n.run(NOW + timedelta(minutes=15))
    assert out["sent"] == ["resolved"]  # only the first one (it had been emailed)
    assert st.get(oid)["email_reason"] == "resolved before it was emailed"


@needs_db
def test_error_capture_handler_dedupes_into_ops_errors(opsdb):
    from blockid_agents.ops.errors import DbErrorHandler, ErrorStore

    h = DbErrorHandler(ErrorStore(opsdb), "api", flush_s=3600)
    lg = logging.getLogger("blockid_agents.test_ops_capture")
    lg.addHandler(h)
    try:
        for i in range(3):
            try:
                raise RuntimeError(f"issuer 50{i}")
            except RuntimeError:
                lg.exception("approve %s failed", i)
        lg.warning("not stored")
        h.flush_now()
    finally:
        lg.removeHandler(h)
        h.close()
    rows = opsdb.all("SELECT * FROM studio.ops_errors")
    assert len(rows) == 1 and rows[0]["count"] == 3 and rows[0]["source"] == "api"
    assert "RuntimeError" in rows[0]["traceback"]
    opsdb.exec("UPDATE studio.ops_errors SET last_seen = now() - interval '40 days'")
    assert ErrorStore(opsdb).purge(30) == 1


@needs_db
def test_leader_lock_single_holder(opsdb):
    from blockid_agents.ops.monitor import Leader

    a, b = Leader(TEST_DB, key="test.ops.leader"), Leader(TEST_DB, key="test.ops.leader")
    try:
        assert a.acquire() is True and a.is_leader
        assert b.acquire() is False and not b.is_leader
        assert a.acquire() is True  # still held
        a.release()
        assert b.acquire() is True
        assert a.acquire() is False
    finally:
        a.release()
        b.release()
    assert Leader("postgresql://nobody:x@127.0.0.1:1/none").acquire() is None


def _seed_activity(db):
    now = datetime.now(timezone.utc)
    db.exec("INSERT INTO studio.accounts (provider, subject, email, created_at) VALUES ('google','s1','a@x',%s),"
            "('google','s2','b@x',%s)", (now - timedelta(days=1), now - timedelta(days=20)))
    db.exec("INSERT INTO studio.account_wallets (account_id, address) SELECT id, '0xAA' FROM studio.accounts LIMIT 1")
    for addr, method, days in (("0xAA", "google", 1), ("0xBB", "guest", 2), ("0xBB", "guest", 3),
                               ("0xCC", "wallet", 10), ("0xDD", "demo", 0)):
        db.exec("INSERT INTO studio.sessions (id, address, role, created_at, expires_at, auth_method) VALUES "
                "(md5(random()::text), %s, 'user', %s, %s, %s)",
                (addr, now - timedelta(days=days), now - timedelta(days=days) + timedelta(hours=12), method))
    db.exec("INSERT INTO studio.sessions (id, username, role, created_at, expires_at) VALUES "
            "('p1','admin','admin',%s,%s)", (now - timedelta(hours=1), now + timedelta(hours=11)))
    for vid, status, days in (("v1", "approved", 1), ("v2", "failed", 2), ("v3", "queued", 0), ("v4", "approved", 12)):
        db.exec("INSERT INTO studio.valuations (id, url, requested_by, status, created_at) VALUES (%s,'https://x',"
                "'0xAA',%s,%s)", (vid, status, now - timedelta(days=days)))
    db.audit("0xAA", "something", "t")


@needs_db
def test_usage_stats(opsdb):
    from blockid_agents.ops import stats

    _seed_activity(opsdb)
    s = stats.collect(opsdb, days=30)
    assert s["accounts"] == {"total": 2, "new_7d": 1, "new_period": 2}
    assert s["wallets"]["linked_total"] == 1 and s["wallets"]["signed_in_7d"] == 3
    assert s["sign_ins"]["7d"] == {"wallet": 0, "guest": 2, "google": 1, "demo": 1, "password": 1}
    assert s["sign_ins"]["period"]["wallet"] == 1
    assert s["active_users"]["d7"] == 4 and s["active_users"]["d30"] == 5
    assert s["valuations"]["started_7d"] == 3 and s["valuations"]["finished_7d"] == 1
    assert s["valuations"]["failed_7d"] == 1 and s["valuations"]["running"] == 1
    assert s["admin_actions_7d"] == 1
    assert len(s["registrations_daily"]) == 31 and sum(d["wallets"] for d in s["registrations_daily"]) == 4
    w = stats.window(opsdb, datetime.now(timezone.utc) - timedelta(days=7), datetime.now(timezone.utc))
    assert w["new_wallets"] == 3 and w["valuations_started"] == 3
    opsdb.exec("INSERT INTO studio.ops_traffic_daily (day, host, page_views, unique_visitors) VALUES "
               "(current_date, 'eth.blockid.au', 10, 4), (current_date - 8, 'eth.blockid.au', 7, 3)")
    opsdb.exec("INSERT INTO studio.ai_usage (model_id, provider, outcome, cost_usd) VALUES ('m','deepinfra','ok',0.25)")
    k = stats.kpis(opsdb)
    assert set(k) == {"visitors_7d", "page_views_7d", "registered_users_total", "new_registrations_7d",
                      "active_users_7d", "valuations_7d", "hr_reports_7d", "ai_spend_today_usd"}
    assert k["visitors_7d"] == {"current": 4, "previous": 3} and k["page_views_7d"] == {"current": 10, "previous": 7}
    # 2 Google accounts + 0xBB, 0xCC, 0xDD (0xAA is linked to an account); 7 days ago: 1 account + 0xCC
    assert k["registered_users_total"] == {"current": 5, "previous": 2}
    assert k["new_registrations_7d"]["current"] == 4 and k["valuations_7d"]["current"] == 3
    assert k["ai_spend_today_usd"] == {"current": 0.25, "previous": 0.0}


@needs_db
def test_weekly_report_build_store_and_delivery(opsdb, tmp_path):
    from blockid_agents.ops.incidents import IncidentStore, Notifier
    from blockid_agents.ops.report import Reports
    from blockid_agents.ops.traffic import TrafficStore

    _seed_activity(opsdb)
    end = datetime.now(timezone.utc)
    logdir = tmp_path / "logs"
    logdir.mkdir()
    day = (end - timedelta(days=2)).strftime("%d/%b/%Y")
    (logdir / "eth.blockid.au.access.log").write_text(
        f'203.0.113.1 - - [{day}:10:00:00 +0000] "GET / HTTP/1.1" 200 5 "-" "Mozilla/5.0 Firefox"\n'
        f'203.0.113.2 - - [{day}:10:00:01 +0000] "GET /i HTTP/1.1" 200 5 "-" "Mozilla/5.0 Safari"\n')
    res = TrafficStore(opsdb).parse_all(str(logdir), ["eth.blockid.au", "hr.blockid.au"], "k")
    assert res["hosts"]["eth.blockid.au"]["written"] == 1 and res["hosts"]["hr.blockid.au"]["files"] == 0
    # a shorter re-parse (logs rotated away) never shrinks a stored day
    (logdir / "eth.blockid.au.access.log").write_text("")
    TrafficStore(opsdb).parse_all(str(logdir), ["eth.blockid.au"], "k")
    assert opsdb.one("SELECT page_views FROM studio.ops_traffic_daily")["page_views"] == 2
    c = _chk("t.crit")
    IncidentStore(opsdb, cfg(), {c.id: c}).apply(c, [Result("critical", "down")], {}, end - timedelta(hours=3))
    opsdb.exec("INSERT INTO studio.ops_errors (fingerprint, source, logger, level, message, count) VALUES "
               "('f1','api','blockid_agents.x','ERROR','boom',12)")
    (tmp_path / "deploys.log").write_text(f"{(end - timedelta(days=1)).isoformat()}\tabc123def456\tWeb: fix\tlong\n"
                                          "2020-01-01T00:00:00Z\told\told\tx\n")
    rc = cfg(deploy_log=str(tmp_path / "deploys.log"))
    rs = Reports(opsdb, rc, FakeMailer(configured=False))
    rep = rs.build("weekly", end)
    d = rep["data"]
    assert d["traffic"]["current"]["total"]["page_views"] == 2 and d["traffic"]["source"] == "nginx"
    assert d["users"]["current"]["new_accounts"] == 1 and d["incidents"]["opened"] == 1
    assert [x["sha"] for x in d["deploys"]] == ["abc123def456"]
    assert any("Configure SMTP" in x for x in d["recommendations"])
    assert any("#1" in x for x in d["recommendations"])
    for s in ("== Traffic ==", "== Users ==", "== Product activity ==", "== Incidents ==", "== AI usage ==",
              "== Issuer balances ==", "== Top errors ==", "== Deploys this week ==", "== Recommended actions =="):
        assert s in rep["text"]
    assert rep["subject"].startswith("BlockID weekly report") and "<table" in rep["html"]
    # scheduled slot: stored once, then delivered when SMTP works
    monday = datetime(2026, 9, 27, 22, 30, tzinfo=timezone.utc)
    ids = rs.due(monday)
    assert len(ids) == 1 and rs.due(monday) == []
    assert rs.due(monday + timedelta(days=2)) == []  # more than a day late: no backfill
    m = FakeMailer()
    n = Notifier(opsdb, m, rc)
    n.run(monday, rs)  # SMTP missing for the notifier? no: FakeMailer() is configured
    got = rs.get(ids[0])
    assert got["emailed"] is True and got["sent_at"] and any("weekly report" in x[1] for x in m.sent)
    assert rs.list()[0]["id"] == ids[0]


@needs_db
def test_monitor_round_end_to_end(opsdb, tmp_path):
    from blockid_agents.ops.monitor import Monitor, beat

    calls = {"n": 0}

    def detect(e):
        calls["n"] += 1
        return Result("critical" if calls["n"] == 1 else "ok", "state %d" % calls["n"])

    c = Check("t.round", "Round check", "critical", "site-down", "impact", ["fix"], detect)
    (tmp_path / "eth.blockid.au.access.log").write_text(SAMPLE.read_text())
    m = FakeMailer()
    e = env(db=opsdb, cfg=cfg(nginx_log_dir=str(tmp_path)), mailer=m)
    mon = Monitor(opsdb, e, registry={c.id: c}, mailer=m)
    out = mon.round(NOW)
    assert out["checks"]["t.round"]["status"] == "critical" and out["mail"]["sent"] == ["critical"]
    assert out["traffic"]["readable"] and opsdb.one("SELECT count(*) AS n FROM studio.ops_traffic_daily")["n"] == 2
    out = mon.round(NOW + timedelta(minutes=1))
    assert out["checks"]["t.round"]["actions"][0]["action"] == "resolved" and out["mail"]["sent"] == ["resolved"]
    assert out["traffic"] is None  # parsed hourly
    st = opsdb.one("SELECT * FROM studio.ops_checks_state WHERE check_id='t.round'")
    assert st["status"] == "ok" and st["last_ok_at"] is not None
    assert opsdb.one("SELECT 1 AS x FROM studio.ops_checks_state WHERE check_id='_monitor'")
    # worker heartbeat feeds worker.heartbeat
    e2 = env(db=opsdb)
    assert run_check(REGISTRY["worker.heartbeat"], e2)[0].status == "unknown"
    beat(opsdb, "worker")
    e2.now = lambda: datetime.now(timezone.utc)
    assert run_check(REGISTRY["worker.heartbeat"], e2)[0].status == "ok"
    e2.now = lambda: datetime.now(timezone.utc) + timedelta(minutes=10)
    assert run_check(REGISTRY["worker.heartbeat"], e2)[0].status == "critical"


@needs_db
def test_db_backed_checks_on_empty_and_seeded_tables(opsdb):
    e = env(db=opsdb)
    for cid in ("jobs.backlog", "jobs.failures", "chain.sync", "automation.errors", "db.postgres", "app.errors"):
        assert {r.status for r in run_check(REGISTRY[cid], e)} <= {"ok"}, cid
    opsdb.exec("INSERT INTO studio.valuations (id, url, status, updated_at) VALUES ('q1','https://x','queued', "
               "now() - interval '90 minutes')")
    rs = {r.key: r.status for r in run_check(REGISTRY["jobs.backlog"], e)}
    assert rs == {"valuations": "critical", "hr": "ok"}


# ================================================================== admin API
@needs_db
def test_ops_admin_api_authz_and_flows(studio_env, caplog):
    from blockid_agents.ops.incidents import IncidentStore

    db = studio_env["db"]
    c = studio_env["client"]()
    assert c.get("/v1/admin/ops/summary").status_code == 401
    r = c.get("/v1/admin/ops/summary")
    assert re.fullmatch(r"[0-9a-f]{16}", r.headers["x-request-id"])
    assert c.get("/healthz", headers={"X-Request-ID": "abcdef1234567890"}).headers["x-request-id"] == \
        "abcdef1234567890"
    siwe_login(c, USER_KEY)
    for path in ("/v1/admin/ops/summary", "/v1/admin/ops/incidents", "/v1/admin/ops/errors",
                 "/v1/admin/ops/traffic", "/v1/admin/ops/stats", "/v1/admin/ops/reports"):
        assert c.get(path).status_code == 403, path
    assert c.post("/v1/admin/ops/test-email").status_code == 403
    assert c.post("/v1/admin/ops/reports/send-now").status_code == 403

    a = studio_env["client"]()
    siwe_login(a, ADMIN_KEY)
    with caplog.at_level(logging.INFO, logger="blockid.access"):
        s = a.get("/v1/admin/ops/summary").json()
    line = [r for r in caplog.records if r.name == "blockid.access"][-1]
    assert line.route == "/v1/admin/ops/summary" and line.status == 200 and re.fullmatch(r"[0-9a-f]{12}", line.user)
    assert line.user != ADMIN_KEY and "0x" not in line.user  # hashed actor, never the address
    assert s["enabled"] is True and s["alert_to"] and {x["id"] for x in s["checks"]} == set(REGISTRY)
    assert s["open_incidents"] == {"critical": 0, "warn": 0, "info": 0, "total": 0}
    assert s["kpis"]["valuations_7d"] == {"current": 0, "previous": 0}
    chk = REGISTRY["wallet.balances"]
    iid = IncidentStore(db).apply(chk, [Result("warn", "HSK low", key="hsk")], {})[0]["id"]
    lst = a.get("/v1/admin/ops/incidents").json()["incidents"]
    assert lst[0]["id"] == iid and lst[0]["fix_steps"] == chk.fix_steps
    assert lst[0]["runbook_url"].endswith("#wallet-balances")
    one = a.get(f"/v1/admin/ops/incidents/{iid}").json()
    assert one["events"][0]["kind"] == "opened"
    assert a.get("/v1/admin/ops/incidents/99999").status_code == 404
    r = a.post(f"/v1/admin/ops/incidents/{iid}/ack", json={"note": "topping up"})
    assert r.json()["incident"]["status"] == "acknowledged"
    assert a.post(f"/v1/admin/ops/incidents/{iid}/resolve").json()["incident"]["status"] == "resolved"
    assert a.post(f"/v1/admin/ops/incidents/{iid}/resolve").status_code == 409
    assert a.get("/v1/admin/ops/incidents?status=resolved").json()["incidents"][0]["id"] == iid
    assert a.get("/v1/admin/ops/incidents?status=bogus").status_code == 422
    # errors / traffic / stats shapes
    db.exec("INSERT INTO studio.ops_errors (fingerprint, source, logger, level, message) VALUES "
            "('f','worker','l','ERROR','m')")
    er = a.get("/v1/admin/ops/errors?source=worker").json()
    assert er["total"] == 1 and er["errors"][0]["message"] == "m"
    t = a.get("/v1/admin/ops/traffic?days=7").json()
    assert t["days"] == 7 and "eth.blockid.au" in t["hosts"] and t["totals"]["page_views"] == 0
    st = a.get("/v1/admin/ops/stats").json()
    assert "sign_ins" in st and "valuations" in st
    # reports: preview, send now (SMTP missing -> stored, not emailed), get
    pv = a.get("/v1/admin/ops/reports/preview").json()
    assert pv["subject"].startswith("BlockID weekly report") and pv["html"].startswith("<!doctype html>")
    sn = a.post("/v1/admin/ops/reports/send-now", json={"kind": "weekly"}).json()
    assert sn["ok"] is True and sn["emailed"] is False and sn["reason"] == "SMTP not configured"
    got = a.get(f"/v1/admin/ops/reports/{sn['report']['id']}").json()
    assert got["html"].startswith("<!doctype html>") and got["trigger"] == "manual"
    assert a.get("/v1/admin/ops/reports").json()["reports"][0]["id"] == sn["report"]["id"]
    assert a.get("/v1/admin/ops/reports/424242").status_code == 404
    te = a.post("/v1/admin/ops/test-email", json={"to": "x@example.test"}).json()
    assert te == {"ok": False, "to": "x@example.test", "reason": "SMTP not configured"}
    assert a.post("/v1/admin/ops/test-email", json={"to": "not-an-email"}).status_code == 422
    # SMTP working (fake) -> test email sent and logged
    fake = FakeMailer()
    a.app.state.ops.mailer = fake
    assert a.post("/v1/admin/ops/test-email").json()["ok"] is True and fake.sent[0][1] == "BlockID ops test email"
    acts = {r["action"] for r in db.all("SELECT action FROM studio.audit WHERE action LIKE 'ops_%%'")}
    assert acts == {"ops_incident_ack", "ops_incident_resolved", "ops_report_sent", "ops_test_email"}
