"""Founding-team / person reviews: Postgres access, the worker job and the valuation blend (API in studio/hr.py).

Job: POST /v1/hr/teams/{id}/run sets status 'queued' (one studio.hr_runs row per request, daily limit per wallet);
the worker (worker.py -> HrRunner.drain) claims queued reports with FOR UPDATE SKIP LOCKED — a report linked to a
valuation that is still queued/running waits, so the team runs after the valuation's research — runs the People
Analyst (agents/people.py), appends progress steps (visible via GET) and stores the result.

Valuation blend (apply_to_valuation): when a DONE team report is linked to a valuation that is waiting_approval or
approved and no company has been created from it yet, founder_quality := team score (basis "team_report") and the
stored valuation result is re-scored deterministically (agents/valuation.apply_team_score: same inputs, no LLM, no
web; SVI index + v3 triangulation recomputed with the v4 weights; narrative kept). An admin override of
founder_quality at the gate ("[set by ...]") wins. The report hash (studio/report_hash.py) covers `svi`, so it changes
with the blend — which is why the blend is refused once a company exists (its hash may already be anchored on chain).
"""
from __future__ import annotations

import logging
import secrets
import uuid

from psycopg.types.json import Jsonb

from ..agents import people as analyst
from ..deps import Deps
from .db import LimitError, Studio, jsonable, now

log = logging.getLogger(__name__)

MAX_STEPS = 200
PERSON_COLS = ("full_name", "role", "kind", "headline", "full_time", "start_year", "equity_pct", "urls", "bio", "cv")
BLENDABLE = ("waiting_approval", "approved")


def new_id() -> str:
    return "t_" + uuid.uuid4().hex[:12]


def step(step: str, person: str | None, msg: str) -> dict:
    return {"at": now().isoformat(), "step": step, "person": person, "msg": msg[:300]}


class HrStore:
    def __init__(self, db: Studio):
        self.db = db

    # -------------------------------------------------------------- reads
    def team(self, tid: str) -> dict | None:
        return self.db.one("SELECT * FROM studio.hr_teams WHERE id=%s", (tid,))

    def people(self, tid: str) -> list[dict]:
        return self.db.all("SELECT * FROM studio.hr_people WHERE team_id=%s ORDER BY position, id", (tid,))

    def linked_company(self, t: dict) -> int | None:
        if t.get("company_id"):
            return t["company_id"]
        if t.get("valuation_id"):
            c = self.db.one("SELECT id FROM studio.companies WHERE valuation_id=%s AND status NOT IN ('rejected','failed') "
                            "ORDER BY id DESC LIMIT 1", (t["valuation_id"],))
            return c["id"] if c else None
        return None

    # -------------------------------------------------------------- writes
    @staticmethod
    def _insert_people(c, tid: str, people: list[dict]) -> None:
        for i, p in enumerate(people):
            c.execute(
                "INSERT INTO studio.hr_people(team_id,full_name,role,kind,headline,full_time,start_year,equity_pct,"
                "urls,bio,cv,position) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (tid, p["full_name"], p.get("role") or "", p.get("kind") or "employee", p.get("headline"),
                 p.get("full_time"), p.get("start_year"), p.get("equity_pct"), Jsonb(p.get("urls") or []),
                 p.get("bio"), p.get("cv"), i))

    def create(self, *, mode: str, name: str, website: str | None, valuation_id: str | None,
               company_id: int | None, target: dict | None, requested_by: str, people: list[dict]) -> str:
        tid = new_id()
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO studio.hr_teams(id,mode,valuation_id,company_id,name,website,target,requested_by,consent,"
                "consented_at,status,steps) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,true,now(),'draft','[]')",
                (tid, mode, valuation_id, company_id, name, website, Jsonb(target) if target else None, requested_by))
            self._insert_people(c, tid, people)
        return tid

    def replace_people(self, tid: str, people: list[dict]) -> None:
        with self.db.tx() as c:
            row = c.execute("SELECT status FROM studio.hr_teams WHERE id=%s FOR UPDATE", (tid,)).fetchone()
            if row is None or row["status"] in ("queued", "running"):
                raise LimitError("report is queued or running")
            c.execute("DELETE FROM studio.hr_people WHERE team_id=%s", (tid,))
            self._insert_people(c, tid, people)
            c.execute("UPDATE studio.hr_teams SET status='draft', result=NULL, error=NULL, steps='[]', "
                      "updated_at=now() WHERE id=%s", (tid,))

    def set_target(self, tid: str, target: dict | None) -> None:
        with self.db.tx() as c:
            row = c.execute("SELECT status FROM studio.hr_teams WHERE id=%s FOR UPDATE", (tid,)).fetchone()
            if row is None or row["status"] in ("queued", "running"):
                raise LimitError("report is queued or running")
            c.execute("UPDATE studio.hr_teams SET target=%s, status='draft', result=NULL, error=NULL, steps='[]', "
                      "updated_at=now() WHERE id=%s", (Jsonb(target) if target else None, tid))

    def queue_run(self, tid: str, actor: str, *, per_wallet: int | None, max_active: int | None) -> None:
        """Queue a run under an advisory lock so concurrent requests cannot all pass the daily count."""
        with self.db.tx() as c:
            c.execute("SELECT pg_advisory_xact_lock(hashtext('studio.hr_runs'))")
            row = c.execute("SELECT status FROM studio.hr_teams WHERE id=%s FOR UPDATE", (tid,)).fetchone()
            if row is None:
                raise LimitError("unknown report")
            if row["status"] in ("queued", "running"):
                raise LimitError("report is already queued or running")
            if max_active:
                n = c.execute("SELECT count(*) AS n FROM studio.hr_teams WHERE status IN ('queued','running')"
                              ).fetchone()["n"]
                if n >= max_active:
                    raise LimitError("busy, try later")
            if per_wallet is not None:
                n = c.execute("SELECT count(*) AS n FROM studio.hr_runs WHERE lower(requested_by)=lower(%s) "
                              "AND at > now() - interval '1 day'", (actor,)).fetchone()["n"]
                if n >= per_wallet:
                    raise LimitError(f"limit of {per_wallet} people reports per day reached")
            c.execute("INSERT INTO studio.hr_runs(team_id,requested_by) VALUES (%s,%s)", (tid, actor))
            c.execute("UPDATE studio.hr_teams SET status='queued', error=NULL, steps=%s, updated_at=now() WHERE id=%s",
                      (Jsonb([step("queued", None, "waiting for the People Analyst")]), tid))

    def claim(self) -> dict | None:
        return self.db.one(
            "UPDATE studio.hr_teams SET status='running', started_at=now(), updated_at=now() WHERE id = ("
            " SELECT t.id FROM studio.hr_teams t WHERE t.status='queued' AND (t.valuation_id IS NULL OR NOT EXISTS ("
            "  SELECT 1 FROM studio.valuations v WHERE v.id=t.valuation_id AND v.status IN ('queued','running')))"
            " ORDER BY t.updated_at FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *")

    def add_step(self, tid: str, st: dict) -> None:
        with self.db.tx() as c:
            row = c.execute("SELECT steps FROM studio.hr_teams WHERE id=%s FOR UPDATE", (tid,)).fetchone()
            if row is None:
                return
            steps = (row["steps"] or []) + [st]
            c.execute("UPDATE studio.hr_teams SET steps=%s, updated_at=now() WHERE id=%s",
                      (Jsonb(steps[-MAX_STEPS:]), tid))

    def finish(self, tid: str, result: dict) -> None:
        self.db.exec("UPDATE studio.hr_teams SET status='done', result=%s, error=NULL, finished_at=now(), "
                     "updated_at=now() WHERE id=%s", (Jsonb(jsonable(result)), tid))

    def fail(self, tid: str, error: str) -> None:
        self.db.exec("UPDATE studio.hr_teams SET status='failed', error=%s, finished_at=now(), updated_at=now() "
                     "WHERE id=%s", (error[:1000], tid))

    def set_result(self, tid: str, result: dict) -> None:
        self.db.exec("UPDATE studio.hr_teams SET result=%s, updated_at=now() WHERE id=%s",
                     (Jsonb(jsonable(result)), tid))

    def rotate_share(self, tid: str) -> str:
        tok = secrets.token_urlsafe(18)
        self.db.exec("UPDATE studio.hr_teams SET share_token=%s, updated_at=now() WHERE id=%s", (tok, tid))
        return tok


# ------------------------------------------------------------------ summary + valuation blend
def summary(t: dict, public_url: str) -> dict:
    """Public-safe: score, grade, names + roles + numbers, top strengths / gaps. No facts, no sources."""
    res = t.get("result") or {}
    block = res.get("team") or {}
    cards = res.get("people") or []
    if t.get("mode") == "person" and cards:
        c0 = cards[0]
        score = (c0.get("fit") or {}).get("score", c0.get("score"))
        strengths, gaps = c0.get("strengths") or [], (c0.get("fit") or {}).get("missing") or c0.get("gaps") or []
    else:
        score = block.get("score")
        strengths, gaps = block.get("strengths") or [], block.get("gaps") or []
    return {"id": t["id"], "mode": t.get("mode") or "team", "name": t.get("name"), "status": t.get("status"),
            "valuation_id": t.get("valuation_id"), "score": score, "grade": analyst.grade(score),
            "people": [{"full_name": c.get("full_name"), "role": c.get("role"), "kind": c.get("kind"),
                        "score": c.get("score"), "fit": (c.get("fit") or {}).get("score")} for c in cards],
            "strengths": strengths[:3], "gaps": gaps[:3], "url": f"{public_url}/r/{t['id']}"}


def apply_to_valuation(db: Studio, t: dict, public_url: str) -> dict:
    """Blend a done team report into its linked valuation (see module docstring). Always records the team summary
    on the valuation result (`result.team`, shown on the eth valuation card). Returns {applied, reason, svi}."""
    from ..agents.valuation import apply_team_score

    vid = t.get("valuation_id")
    if not vid:
        return {"applied": False, "reason": "no linked valuation", "svi": None}
    val = db.get_valuation(vid)
    if not val:
        return {"applied": False, "reason": "unknown valuation", "svi": None}
    res = (t.get("result") or {}).get("team") if t.get("status") == "done" else None
    reason, patch = None, None
    if t.get("mode") != "team" or not res:
        reason = "team report is not done"
    elif val["status"] not in BLENDABLE:
        reason = f"valuation is {val['status']}"
    elif db.one("SELECT 1 AS x FROM studio.companies WHERE valuation_id=%s AND status NOT IN ('rejected','failed') "
                "LIMIT 1", (vid,)):
        reason = "a company was already created from this valuation (its report hash may be anchored)"
    else:
        n = len((t.get("result") or {}).get("people") or [])
        facts = ((t.get("result") or {}).get("counters") or {}).get("facts_verified", 0)
        rationale = (f"Founding-team report {t['id']}: team score {res['score']} (grade {res['grade']}), {n} people, "
                     f"{facts} verified fact(s) — {public_url}/r/{t['id']}")
        patch = apply_team_score(val.get("result") or {}, res["score"], rationale, [f"{public_url}/r/{t['id']}"])
        if patch is None:
            reason = "an admin override of founder_quality wins" if (val.get("result") or {}).get("qualitative") \
                else "valuation has no scores yet"
    team = {**summary(t, public_url), "applied": patch is not None, "reason": reason}
    db.merge_result(vid, {**(patch or {}), "team": team})
    db.audit("people_analyst", "hr_team_applied" if patch else "hr_team_not_applied", vid, team_id=t["id"],
             reason=reason, founder_quality=(res or {}).get("score"))
    return {"applied": patch is not None, "reason": reason, "svi": (patch or {}).get("svi")}


# ------------------------------------------------------------------ target resolution (at run time)
def resolve_target(db: Studio, t: dict, deps: Deps | None = None) -> dict | None:
    """Business context for founder–business fit (from the stored valuation when there is one), or the role."""
    tg = dict(t.get("target") or {})
    if t.get("mode") == "team":
        name = t.get("name") or ""
        tg = {"type": "business", "valuation_id": t.get("valuation_id"), "website": t.get("website"),
              "company": None if ("." in name and " " not in name) else name}  # a bare host name is not a name
    if not tg:
        return None
    if tg.get("type") == "role":
        return {k: tg.get(k) for k in ("type", "company", "title", "description", "requirements")}
    vid = tg.get("valuation_id")
    if not vid and tg.get("ticker"):
        c = db.one("SELECT valuation_id, name, website FROM studio.companies WHERE ticker=%s", (tg["ticker"].upper(),))
        if c:
            vid = c["valuation_id"]
            tg.setdefault("company", c["name"])
            tg["website"] = tg.get("website") or c["website"]
    out = {"type": "business", "valuation_id": vid, "ticker": tg.get("ticker"), "website": tg.get("website"),
           "company": tg.get("company"), "sector": None, "stage": None, "country": None, "description": None,
           "market": None}
    v = db.get_valuation(vid) if vid else None
    if v:
        res = v.get("result") or {}
        prof = res.get("profile") or {}
        out.update(company=out["company"] or prof.get("company_name"), website=out["website"] or v.get("url"),
                   sector=prof.get("sector"), stage=prof.get("stage"), country=prof.get("country"),
                   description=prof.get("description"),
                   market=(res.get("market") or {}).get("market_summary"))
    elif out["website"] and deps is not None:  # only a website: its homepage text is the business context
        from ..tools.brave import fetch_page

        try:
            deps.tool(analyst.AGENT, "fetch_url", url=out["website"])
            out["description"] = analyst.redact((deps.fetcher or fetch_page)(out["website"]) or "")[:1_500]
        except Exception as e:
            deps.audit.record(analyst.AGENT, "fetch_error", url=out["website"], error=str(e)[:300])
    return out


# ------------------------------------------------------------------ worker job
class HrRunner:
    def __init__(self, deps: Deps, db: Studio):
        self.deps, self.db, self.store = deps, db, HrStore(db)

    def run(self, t: dict) -> str:
        tid = t["id"]
        people = self.store.people(tid)
        if not people:
            self.store.fail(tid, "no people to analyse")
            return "failed"

        def progress(st: str, person: str | None, msg: str) -> None:
            try:
                self.store.add_step(tid, step(st, person, msg))
            except Exception:  # progress must never kill the run
                log.exception("hr progress")

        try:
            target = resolve_target(self.db, t, self.deps)
            name = t.get("name") or ""
            if (t.get("mode") or "team") == "team" and (target or {}).get("company") and " " not in name \
                    and "." in name:  # created at valuation start with the host name: use the company's name
                t = {**t, "name": target["company"]}
                self.db.exec("UPDATE studio.hr_teams SET name=%s WHERE id=%s", (target["company"], tid))
            result = analyst.analyse({"id": tid, "mode": t.get("mode") or "team", "name": t.get("name"),
                                      "website": t.get("website")}, people, self.deps, target=target,
                                     progress=progress)
        except Exception as e:
            log.exception("hr report %s failed", tid)
            progress("failed", None, f"{type(e).__name__}: {e}")
            self.store.fail(tid, f"{type(e).__name__}: {e}")
            return "failed"
        self.store.finish(tid, result)
        if t.get("valuation_id") and (t.get("mode") or "team") == "team":
            try:
                apply_to_valuation(self.db, self.store.team(tid), self.deps.settings.hr_public_url)
            except Exception:
                log.exception("hr blend into valuation %s failed", t.get("valuation_id"))
        return "done"

    def drain(self) -> int:
        n = 0
        while (t := self.store.claim()) is not None:
            log.info("hr report %s (%s) -> %s", t["id"], t.get("mode"), self.run(t))
            n += 1
        return n

