"""Users and product activity from the existing studio tables (docs/PLAN-OPS.md §3).

Sources: accounts (Google), account_wallets, sessions (one row per sign-in, auth_method wallet | guest | google |
demo | password; expired rows are kept 45 days for these numbers), valuations, hr_teams, companies, offerings,
dividends, audit. "Active users" = distinct addresses / usernames that signed in within the window.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..studio.db import jsonable

METHODS = ("wallet", "guest", "google", "demo", "password")
FINISHED = ("waiting_approval", "approved", "rejected")
METHOD_SQL = ("coalesce(auth_method, CASE WHEN username IS NOT NULL THEN 'password' ELSE 'wallet' END)")
ACTOR_SQL = "coalesce(lower(address), 'user:' || username)"


def _n(db, sql: str, params=()) -> int:
    row = db.one(sql, params)
    return int((row or {}).get("n") or 0)


def collect(db, days: int = 30, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    p_start, w_start = now - timedelta(days=days), now - timedelta(days=7)
    return jsonable({
        "generated_at": now, "days": days,
        "accounts": {
            "total": _n(db, "SELECT count(*) AS n FROM studio.accounts"),
            "new_7d": _n(db, "SELECT count(*) AS n FROM studio.accounts WHERE created_at >= %s", (w_start,)),
            "new_period": _n(db, "SELECT count(*) AS n FROM studio.accounts WHERE created_at >= %s", (p_start,)),
        },
        "wallets": {
            "linked_total": _n(db, "SELECT count(DISTINCT lower(address)) AS n FROM studio.account_wallets"),
            "signed_in_7d": _n(db, "SELECT count(DISTINCT lower(address)) AS n FROM studio.sessions WHERE "
                                   "address IS NOT NULL AND created_at >= %s", (w_start,)),
            "signed_in_period": _n(db, "SELECT count(DISTINCT lower(address)) AS n FROM studio.sessions WHERE "
                                       "address IS NOT NULL AND created_at >= %s", (p_start,)),
        },
        "sign_ins": {"7d": _by_method(db, w_start, now), "period": _by_method(db, p_start, now)},
        "active_users": {f"d{d}": _n(db, f"SELECT count(DISTINCT {ACTOR_SQL}) AS n FROM studio.sessions WHERE "
                                         "created_at >= %s", (now - timedelta(days=d),)) for d in (1, 7, 30)},
        "registrations_daily": registrations_daily(db, p_start, now),
        "valuations": _valuations(db, w_start, p_start),
        "hr": {
            "teams_7d": _n(db, "SELECT count(*) AS n FROM studio.hr_teams WHERE created_at >= %s", (w_start,)),
            "done_7d": _n(db, "SELECT count(*) AS n FROM studio.hr_teams WHERE status='done' AND "
                              "coalesce(finished_at, updated_at) >= %s", (w_start,)),
            "failed_7d": _n(db, "SELECT count(*) AS n FROM studio.hr_teams WHERE status='failed' AND updated_at >= %s",
                            (w_start,)),
            "teams_period": _n(db, "SELECT count(*) AS n FROM studio.hr_teams WHERE created_at >= %s", (p_start,)),
        },
        "companies": {
            "total": _n(db, "SELECT count(*) AS n FROM studio.companies"),
            "created_7d": _n(db, "SELECT count(*) AS n FROM studio.companies WHERE created_at >= %s", (w_start,)),
            "by_status": {r["status"]: int(r["n"]) for r in db.all(
                "SELECT status, count(*) AS n FROM studio.companies GROUP BY status ORDER BY 2 DESC")},
        },
        "offerings": {
            "total": _n(db, "SELECT count(*) AS n FROM studio.offerings"),
            "open": _n(db, "SELECT count(*) AS n FROM studio.offerings WHERE status='open'"),
            "created_7d": _n(db, "SELECT count(*) AS n FROM studio.offerings WHERE created_at >= %s", (w_start,)),
        },
        "dividends": {
            "total": _n(db, "SELECT count(*) AS n FROM studio.dividends"),
            "created_7d": _n(db, "SELECT count(*) AS n FROM studio.dividends WHERE created_at >= %s", (w_start,)),
            "paid_7d": _n(db, "SELECT count(*) AS n FROM studio.dividends WHERE status='paid' AND created_at >= %s",
                          (w_start,)),
        },
        "admin_actions_7d": _n(db, "SELECT count(*) AS n FROM studio.audit WHERE at >= %s", (w_start,)),
    })


def _by_method(db, since: datetime, until: datetime) -> dict:
    out = dict.fromkeys(METHODS, 0)
    for r in db.all(f"SELECT {METHOD_SQL} AS m, count(*) AS n FROM studio.sessions WHERE created_at >= %s AND "
                    "created_at < %s GROUP BY 1", (since, until)):
        out[r["m"]] = out.get(r["m"], 0) + int(r["n"])
    return out


def _valuations(db, w_start: datetime, p_start: datetime) -> dict:
    q = ("SELECT count(*) FILTER (WHERE created_at >= %(s)s) AS started, count(*) FILTER (WHERE created_at >= %(s)s "
         "AND status = ANY(%(f)s)) AS finished, count(*) FILTER (WHERE created_at >= %(s)s AND status='failed') AS "
         "failed FROM studio.valuations")
    w = db.one(q, {"s": w_start, "f": list(FINISHED)})
    p = db.one(q, {"s": p_start, "f": list(FINISHED)})
    return {"started_7d": int(w["started"]), "finished_7d": int(w["finished"]), "failed_7d": int(w["failed"]),
            "started_period": int(p["started"]), "finished_period": int(p["finished"]),
            "failed_period": int(p["failed"]),
            "running": _n(db, "SELECT count(*) AS n FROM studio.valuations WHERE status IN ('queued','running')")}


def registrations_daily(db, since: datetime, until: datetime) -> list[dict]:
    acc = {r["d"]: int(r["n"]) for r in db.all(
        "SELECT (created_at AT TIME ZONE 'UTC')::date AS d, count(*) AS n FROM studio.accounts WHERE created_at >= %s "
        "AND created_at < %s GROUP BY 1", (since, until))}
    wal = {r["d"]: int(r["n"]) for r in db.all(
        "SELECT (first AT TIME ZONE 'UTC')::date AS d, count(*) AS n FROM (SELECT lower(address) AS a, "
        "min(created_at) AS first FROM studio.sessions WHERE address IS NOT NULL GROUP BY 1) x "
        "WHERE first >= %s AND first < %s GROUP BY 1", (since, until))}
    out, d = [], since.date()
    while d <= until.date():
        out.append({"day": d.isoformat(), "accounts": acc.get(d, 0), "wallets": wal.get(d, 0)})
        d += timedelta(days=1)
    return out


def window(db, start: datetime, end: datetime) -> dict:
    """Counts for one arbitrary window (week-over-week in the report)."""
    return {
        "new_accounts": _n(db, "SELECT count(*) AS n FROM studio.accounts WHERE created_at >= %s AND created_at < %s",
                           (start, end)),
        "new_wallets": _n(db, "SELECT count(*) AS n FROM (SELECT lower(address) AS a, min(created_at) AS f FROM "
                              "studio.sessions WHERE address IS NOT NULL GROUP BY 1) x WHERE f >= %s AND f < %s",
                          (start, end)),
        "active_users": _n(db, f"SELECT count(DISTINCT {ACTOR_SQL}) AS n FROM studio.sessions WHERE created_at >= %s "
                               "AND created_at < %s", (start, end)),
        "sign_ins": _by_method(db, start, end),
        "valuations_started": _n(db, "SELECT count(*) AS n FROM studio.valuations WHERE created_at >= %s AND "
                                     "created_at < %s", (start, end)),
        "valuations_finished": _n(db, "SELECT count(*) AS n FROM studio.valuations WHERE created_at >= %s AND "
                                      "created_at < %s AND status = ANY(%s)", (start, end, list(FINISHED))),
        "valuations_failed": _n(db, "SELECT count(*) AS n FROM studio.valuations WHERE created_at >= %s AND "
                                    "created_at < %s AND status='failed'", (start, end)),
        "hr_reports": _n(db, "SELECT count(*) AS n FROM studio.hr_teams WHERE created_at >= %s AND created_at < %s",
                         (start, end)),
        "hr_done": _n(db, "SELECT count(*) AS n FROM studio.hr_teams WHERE status='done' AND created_at >= %s AND "
                          "created_at < %s", (start, end)),
        "companies_created": _n(db, "SELECT count(*) AS n FROM studio.companies WHERE created_at >= %s AND "
                                    "created_at < %s", (start, end)),
        "offerings_created": _n(db, "SELECT count(*) AS n FROM studio.offerings WHERE created_at >= %s AND "
                                    "created_at < %s", (start, end)),
        "dividends_created": _n(db, "SELECT count(*) AS n FROM studio.dividends WHERE created_at >= %s AND "
                                    "created_at < %s", (start, end)),
    }


def registered_users(db, before: datetime) -> int:
    """Google accounts + distinct wallets that signed in without a linked Google account, created before `before`."""
    return _n(db, "SELECT (SELECT count(*) FROM studio.accounts WHERE created_at < %s) + (SELECT count(DISTINCT "
                  "lower(s.address)) FROM studio.sessions s WHERE s.address IS NOT NULL AND s.created_at < %s AND "
                  "NOT EXISTS (SELECT 1 FROM studio.account_wallets w WHERE lower(w.address) = lower(s.address))) AS n",
              (before, before))


def kpis(db, now: datetime | None = None) -> dict:
    """Headline numbers for Admin > Ops: {name: {"current": x, "previous": y}} (see ops/__init__.py)."""
    now = now or datetime.now(timezone.utc)
    w, pw = now - timedelta(days=7), now - timedelta(days=14)
    today = now.date()
    cur_w, prev_w = window(db, w, now), window(db, pw, w)

    def traffic(start, end) -> dict:
        r = db.one("SELECT coalesce(sum(unique_visitors),0)::int AS v, coalesce(sum(page_views),0)::int AS p FROM "
                   "studio.ops_traffic_daily WHERE day >= %s AND day < %s", (start, end))
        return {"v": int(r["v"]), "p": int(r["p"])}

    t_cur = traffic(today - timedelta(days=6), today + timedelta(days=1))
    t_prev = traffic(today - timedelta(days=13), today - timedelta(days=6))
    day0 = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)

    def spend(start, end) -> float:
        r = db.one("SELECT coalesce(sum(cost_usd),0) AS c FROM studio.ai_usage WHERE at >= %s AND at < %s",
                   (start, end))
        return round(float(r["c"]), 4)

    def kv(c, p):
        return {"current": c, "previous": p}

    return {
        "visitors_7d": kv(t_cur["v"], t_prev["v"]),
        "page_views_7d": kv(t_cur["p"], t_prev["p"]),
        "registered_users_total": kv(registered_users(db, now), registered_users(db, w)),
        "new_registrations_7d": kv(cur_w["new_accounts"] + cur_w["new_wallets"],
                                   prev_w["new_accounts"] + prev_w["new_wallets"]),
        "active_users_7d": kv(cur_w["active_users"], prev_w["active_users"]),
        "valuations_7d": kv(cur_w["valuations_started"], prev_w["valuations_started"]),
        "hr_reports_7d": kv(cur_w["hr_reports"], prev_w["hr_reports"]),
        "ai_spend_today_usd": kv(spend(day0, now + timedelta(seconds=1)), spend(day0 - timedelta(days=1), day0)),
    }
