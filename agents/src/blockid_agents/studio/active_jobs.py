"""Background jobs of the signed-in user, for the "Running" tray on eth.blockid.au and hr.blockid.au.

GET /v1/me/active-jobs  (signed in; the shared demo account sees the jobs requested by its session address)
    -> {"jobs": [Job], "server_time": str}
Job
    {"kind": "valuation|hr_person|hr_team", "id": str,
     "title": str,                     # company name found by the research, else the site host / person / team name
     "status": "queued|running|done|failed",
     "raw_status": str,                # valuations: waiting_approval|approved|rejected count as "done" (report ready)
     "phase": str,                     # valuation: queued | <step key> | done | failed; HR: progress.phase
     "pct": 0..100, "eta_s": int|null,
     "url": str,                       # absolute, on the right host: PUBLIC_BASE_URL /v/<id>/research|report,
                                       # HR_PUBLIC_URL /r/<id> (team) or /p/<id> (person)
     "started_at": str|null, "updated_at": str|null, "finished_at": str|null}

Listed: queued / running jobs, plus jobs that finished (done or failed) in the last FINISHED_WINDOW so the user sees
"ready". Newest first, at most MAX_JOBS. Read-only: studio.valuations and studio.hr_teams by lower(requested_by).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request

from .auth import COOKIE, Session
from .db import STEP_KEYS, jsonable, now

FINISHED_WINDOW = timedelta(minutes=30)
MAX_JOBS = 20
DEFAULT_VALUATION_S = 180.0  # ETA when no finished valuation exists yet
VAL_DONE = ("waiting_approval", "approved", "rejected")


def _iso(v: Any) -> str | None:
    return v.isoformat() if isinstance(v, datetime) else (v if isinstance(v, str) else None)


def _host(url: str) -> str:
    h = urlparse(url if "://" in url else "https://" + url).hostname or url
    return h.removeprefix("www.")


def valuation_progress(steps: list[dict]) -> tuple[str, int]:
    """(phase, pct) from the step list: done steps count 1, the running one a half."""
    by = {s.get("key"): s.get("status") for s in steps or []}
    keys = list(STEP_KEYS)
    done = sum(1 for k in keys if by.get(k) == "done")
    running = next((k for k in keys if by.get(k) == "running"), None)
    pct = round(100 * (done + (0.5 if running else 0)) / len(keys))
    phase = running or next((k for k in keys if by.get(k) != "done"), keys[-1])
    return phase, max(0, min(99, pct))


def valuation_job(row: dict, base: str, avg_s: float) -> dict:
    st = row["status"]
    res = row.get("result") or {}
    name = (res.get("profile") or {}).get("name")
    title = name if isinstance(name, str) and name.strip() else _host(row["url"])
    vid = row["id"]
    if st in ("queued", "running"):
        phase, pct = ("queued", 0) if st == "queued" else valuation_progress(row.get("steps") or [])
        created = row.get("created_at")
        elapsed = (now() - created).total_seconds() if isinstance(created, datetime) else 0.0
        eta = int(max(5.0, avg_s * (1 - pct / 100), avg_s - elapsed))
        status, url, finished = st, f"{base}/v/{vid}/research", None
    else:
        status = "failed" if st == "failed" else "done"
        if status == "failed":
            phase, pct, eta = "failed", valuation_progress(row.get("steps") or [])[1], None
        else:
            phase, pct, eta = "done", 100, 0
        url = f"{base}/v/{vid}/report" if status == "done" else f"{base}/v/{vid}"
        finished = _iso(row.get("updated_at"))
    return {"kind": "valuation", "id": vid, "title": title[:120], "status": status, "raw_status": st,
            "phase": phase, "pct": pct, "eta_s": eta, "url": url,
            "started_at": _iso(row.get("created_at")), "updated_at": _iso(row.get("updated_at")),
            "finished_at": finished}


def hr_job(t: dict, base: str) -> dict:
    from .hr_store import progress_view  # the live-progress contract of GET /v1/hr/teams/{id}

    person = t.get("mode") == "person"
    st = t["status"]
    p = progress_view(t) or {}
    status = st if st in ("queued", "running", "failed") else "done"
    pct = 100 if status == "done" else int(p.get("pct") or 0)
    return {"kind": "hr_person" if person else "hr_team", "id": t["id"], "title": (t.get("name") or t["id"])[:120],
            "status": status, "raw_status": st, "phase": p.get("phase") or st, "pct": max(0, min(100, pct)),
            "eta_s": 0 if status == "done" else p.get("eta_s"),
            "url": f"{base}/{'p' if person else 'r'}/{t['id']}",
            "started_at": _iso(t.get("started_at") or t.get("created_at")), "updated_at": _iso(t.get("updated_at")),
            "finished_at": _iso(t.get("finished_at") or t.get("updated_at")) if status in ("done", "failed") else None}


def active_jobs(db, actor: str, *, eth_base: str, hr_base: str) -> list[dict]:
    since = now() - FINISHED_WINDOW
    vals = db.all(
        "SELECT id, url, status, steps, result, created_at, updated_at FROM studio.valuations "
        "WHERE lower(requested_by)=lower(%s) AND (status IN ('queued','running') OR updated_at >= %s) "
        "ORDER BY created_at DESC LIMIT %s", (actor, since, MAX_JOBS))
    avg_s = DEFAULT_VALUATION_S
    if any(v["status"] in ("queued", "running") for v in vals):
        r = db.one("SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY s) AS p50 FROM ("
                   " SELECT extract(epoch FROM updated_at - created_at) AS s FROM studio.valuations"
                   " WHERE status = ANY(%s) ORDER BY updated_at DESC LIMIT 20) x", (list(VAL_DONE),))
        if r and r.get("p50"):
            avg_s = float(min(max(float(r["p50"]), 30.0), 3600.0))
    teams = db.all(
        "SELECT * FROM studio.hr_teams WHERE lower(requested_by)=lower(%s) AND (status IN ('queued','running') "
        "OR (status IN ('done','failed') AND coalesce(finished_at, updated_at) >= %s)) "
        "ORDER BY created_at DESC LIMIT %s", (actor, since, MAX_JOBS))
    jobs = [valuation_job(v, eth_base, avg_s) for v in vals] + [hr_job(t, hr_base) for t in teams]
    running = [j for j in jobs if j["status"] in ("queued", "running")]
    finished = [j for j in jobs if j["status"] not in ("queued", "running")]
    running.sort(key=lambda j: j["started_at"] or "", reverse=True)
    finished.sort(key=lambda j: j["finished_at"] or "", reverse=True)
    return jsonable((running + finished)[:MAX_JOBS])


def build_active_jobs_router(ctx) -> APIRouter:
    r = APIRouter()

    def session(request: Request) -> Session | None:
        sid = request.cookies.get(COOKIE)
        return ctx.sessions.get(sid) if sid else None

    @r.get("/v1/me/active-jobs")
    def my_active_jobs(sess: Session | None = Depends(session)):
        if sess is None:
            raise HTTPException(401, "sign in required")
        s = ctx.settings
        jobs = active_jobs(ctx.need_db(), sess.actor, eth_base=s.public_base_url.rstrip("/"),
                           hr_base=s.hr_public_url.rstrip("/"))
        return {"jobs": jobs, "server_time": now().isoformat()}

    return r
