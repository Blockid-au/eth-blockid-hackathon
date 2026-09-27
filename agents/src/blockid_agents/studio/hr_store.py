"""Founding-team / person reviews: Postgres access, the worker job and the valuation blend (API in studio/hr.py).

Job: POST /v1/hr/teams/{id}/run sets status 'queued' (one studio.hr_runs row per request, daily limit per wallet);
the worker (worker.py -> HrRunner.drain) claims queued reports with FOR UPDATE SKIP LOCKED — a report linked to a
valuation that is still queued/running waits, so the team runs after the valuation's research — runs the People
Analyst (agents/people.py), appends progress steps (visible via GET) and stores the result.

Live progress (docs/PLAN-HR-V2.md §1, contract in studio/hr.py): HrProgress is the People Analyst's Tracker. It keeps
the `progress` JSON on the row (feed, counters, current step, per-person partial results, pct, ETA) and the
`heartbeat_at` column: every step writes, and a heartbeat thread writes at least every HEARTBEAT_S while a long
model call or search runs — unless that one step has run longer than STEP_MAX_S (a hung call), so the run shows as
stalled. pct is monotonic. ETA (docs/PLAN-AI-GATEWAY.md §2): a percentile model per step kind over the last
ETA_SAMPLES finished steps (studio.hr_step_timings): `eta_s` = remaining planned steps x p50, `eta_range_s` =
[remaining x p25, remaining x p75]; the planned steps scale with the number of people (one person_model step per
person, searches per person, and team_model is timed PER PERSON of its run and multiplied by the team size).
Fewer than ETA_MIN_SAMPLES samples of a kind -> DEFAULT_STEP_S with the range DEFAULT_RANGE x the default.

User-facing errors (docs/PLAN-AI-GATEWAY.md §2): a failed run stores `error` = one plain English sentence
(ERROR_TEXT), `error_code` = its short code (classify_error) and `error_detail` = the internal exception text, which
only platform admins see (API) and the audit log records ("hr_run_failed").
Each claim increments `attempt`; every write of a run is conditional on its attempt, so a run the watchdog re-queued
cannot be overwritten by the worker that lost it (it stops with Superseded at its next write).
Watchdog (watchdog(): the worker calls it on every drain, the API every HR_WATCHDOG_SECONDS): a running report
with no heartbeat for STALL_S is re-queued once (feed line), and failed with a clear reason the second time.

Valuation blend (apply_to_valuation): when a DONE team report is linked to a valuation that is waiting_approval or
approved and no company has been created from it yet, founder_quality := team score (basis "team_report") and the
stored valuation result is re-scored deterministically (agents/valuation.apply_team_score: same inputs, no LLM, no
web; SVI index + v3 triangulation recomputed with the v4 weights; narrative kept). An admin override of
founder_quality at the gate ("[set by ...]") wins. The report hash (studio/report_hash.py) covers `svi`, so it changes
with the blend — which is why the blend is refused once a company exists (its hash may already be anchored on chain).
"""
from __future__ import annotations

import logging
import os
import secrets
import threading
import time
import uuid
from datetime import datetime

from psycopg.types.json import Jsonb

from ..agents import people as analyst
from ..deps import Deps
from ..llm import provider_label
from .db import LimitError, Studio, jsonable, now

log = logging.getLogger(__name__)

MAX_STEPS = 200
STALL_S = 90  # running with no heartbeat for this long -> "stalled" (API view) and the watchdog acts
HEARTBEAT_S = 5.0  # heartbeat thread: write at least this often while running (contract: <= 10 s)
STEP_MAX_S = 180.0  # one step longer than this stops the heartbeat (a hung call must become visible in <= ~4.5 min;
# the gateway's per-call deadlines end a hung model call well before this)
MAX_REQUEUES = 1
FEED_MAX = 60
CV_PART_S, CV_PARTS = 30.0, ("timeline", "insights")  # progress weight of each model-made CV review part
DEFAULT_STEP_S = {"fetch": 4.0, "search": 15.0, "person_model": 90.0, "team_model": 45.0}
DEFAULT_TEAM_PEOPLE = 3  # DEFAULT_STEP_S["team_model"] is for a team of this size (scaled per person)
PER_PERSON_KINDS = ("team_model",)  # timed per person of the run, multiplied by the team size
DEFAULT_RANGE = (0.6, 1.8)  # p25 / p75 as multiples of the default p50 before there is history
ETA_SAMPLES = 30
ETA_MIN_SAMPLES = 3
ERROR_TEXT = {
    "sources_unreachable": "We could not reach the public websites and search services this review needs. "
                           "Please try again in a few minutes.",
    "models_busy": "Our AI models are busy right now. Please run the review again in a few minutes.",
    "no_public_info": "We found no public professional information about these people. Add a public profile link, "
                      "a short bio or a CV, then run the review again.",
    "timeout": "The review took too long and was stopped. Please run it again in a few minutes.",
    "stalled": "The review stopped responding and a restart did not help. Please run it again in a few minutes.",
    "no_people": "Add at least one person before running the review.",
    "internal": "Something went wrong on our side while writing the review. Please try again; if it keeps "
                "happening, contact support.",
}
PHASES = ("queued", "reading", "searching", "extracting", "scoring", "done", "failed", "stalled")
PERSON_COLS = ("full_name", "role", "kind", "headline", "full_time", "start_year", "equity_pct", "urls", "bio", "cv")
BLENDABLE = ("waiting_approval", "approved")


def new_id() -> str:
    return "t_" + uuid.uuid4().hex[:12]


def step(step: str, person: str | None, msg: str) -> dict:
    return {"at": now().isoformat(), "step": step, "person": person, "msg": msg[:300]}


class Superseded(RuntimeError):
    """This worker's run was re-queued or failed by the watchdog; it must stop without writing."""


def _iso(v) -> str | None:
    if v is None:
        return None
    return v.isoformat() if isinstance(v, datetime) else str(v)


# ------------------------------------------------------------------ user-facing errors
_BUSY_WORDS = ("rate-limit", "rate limit", "ratelimit", "429", "overloaded", "quota", "budget", "cooling",
               "backends failed", "circuit", "busy", "llmerror", "503")
_TIMEOUT_WORDS = ("timed out", "timeout", "deadline")
_SOURCE_WORDS = ("searchunavailable", "connecterror", "connection", "unreachable", "search", "dns", "fetch")


def classify_text(text: str) -> str:
    """Error code of an internal error text (also used for rows written before error codes existed)."""
    t = (text or "").lower()
    if "stopped responding" in t or "no progress for" in t:
        return "stalled"
    if "no people" in t:
        return "no_people"
    if any(w in t for w in _BUSY_WORDS):
        return "models_busy"
    if any(w in t for w in _TIMEOUT_WORDS):
        return "timeout"
    if any(w in t for w in _SOURCE_WORDS):
        return "sources_unreachable"
    return "internal"


def classify_error(e: BaseException) -> str:
    """Short user-facing code (ERROR_TEXT) of an exception raised by a run."""
    import httpx

    from ..llm import LLMError
    from ..tools.search import SearchUnavailable

    if isinstance(e, analyst.ReviewError):
        return e.code if e.code in ERROR_TEXT else "internal"
    name = type(e).__name__.lower()
    if isinstance(e, LLMError) or any(w in name for w in ("quota", "ratelimit", "budget", "circuit")):
        return "models_busy"
    if isinstance(e, (TimeoutError, httpx.TimeoutException)):
        return "timeout"
    if isinstance(e, (SearchUnavailable, httpx.TransportError, ConnectionError)):
        return "sources_unreachable"
    return classify_text(f"{type(e).__name__}: {e}")


def public_error(t: dict) -> tuple[str | None, str | None]:
    """(error_code, plain sentence) of a report row; old rows (internal text in `error`) are classified here."""
    if t.get("status") != "failed" and not t.get("error"):
        return None, None
    code = t.get("error_code")
    if code in ERROR_TEXT:
        return code, t.get("error") or ERROR_TEXT[code]
    if not t.get("error"):
        return None, None
    code = classify_text(str(t["error"]))
    return code, ERROR_TEXT[code]


def error_detail(t: dict) -> str | None:
    """Internal detail (platform admins only): the stored detail, or the raw text of an old row."""
    if t.get("error_detail"):
        return t["error_detail"]
    return None if t.get("error_code") else t.get("error")


# ------------------------------------------------------------------ ETA (percentile model)
def _pct(vals: list[float], q: float) -> float:
    v = sorted(vals)
    if not v:
        return 0.0
    k = (len(v) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def default_stats() -> dict[str, tuple[float, float, float]]:
    """(p25, p50, p75) seconds per step unit (per person for PER_PERSON_KINDS)."""
    out = {}
    for k, v in DEFAULT_STEP_S.items():
        base = v / DEFAULT_TEAM_PEOPLE if k in PER_PERSON_KINDS else v
        out[k] = (base * DEFAULT_RANGE[0], base, base * DEFAULT_RANGE[1])
    return out


def step_stats(db: Studio, last: int = ETA_SAMPLES) -> dict[str, tuple[float, float, float]]:
    """(p25, p50, p75) seconds per step kind over its last `last` samples; PER_PERSON_KINDS are divided by the
    people count of their run (DEFAULT_TEAM_PEOPLE when unknown). Defaults below ETA_MIN_SAMPLES samples."""
    out = default_stats()
    try:
        rows = db.all("SELECT kind, seconds, people FROM ("
                      " SELECT kind, seconds, people, row_number() OVER (PARTITION BY kind ORDER BY at DESC, id DESC)"
                      " AS rn FROM studio.hr_step_timings) x WHERE rn <= %s", (last,))
    except Exception:  # noqa: BLE001 - ETA is best effort
        log.exception("hr step stats")
        return out
    by: dict[str, list[float]] = {}
    for r in rows:
        sec = float(r["seconds"])
        if r["kind"] in PER_PERSON_KINDS:
            sec /= max(1, int(r.get("people") or DEFAULT_TEAM_PEOPLE))
        by.setdefault(r["kind"], []).append(sec)
    for k, vals in by.items():
        if k in out and len(vals) >= ETA_MIN_SAMPLES:
            out[k] = tuple(max(0.2, _pct(vals, q)) for q in (0.25, 0.5, 0.75))
    return out


def per_step(stats: dict[str, tuple[float, float, float]], people: int) -> dict[str, tuple[float, float, float]]:
    """Seconds per planned step for a run of `people` people (PER_PERSON_KINDS multiplied by the team size)."""
    n = max(1, int(people or 1))
    return {k: tuple(x * n for x in v) if k in PER_PERSON_KINDS else tuple(v) for k, v in stats.items()}


def estimate_range(stats: dict[str, tuple[float, float, float]], *, fetches: int, searches: int, people: int,
                   team: bool) -> tuple[float, float, float]:
    """(lo, eta, hi) seconds of a whole run before it starts."""
    st = per_step(stats, people)
    counts = {"fetch": fetches, "search": searches, "person_model": people, "team_model": int(team)}
    return tuple(sum(counts[k] * st[k][i] for k in counts) for i in range(3))


def step_medians(db: Studio, last: int = 30) -> dict[str, float]:
    """Median seconds per step kind over the most recent finished runs (defaults until 3 samples exist)."""
    out = dict(DEFAULT_STEP_S)
    try:
        rows = db.all("SELECT kind, percentile_cont(0.5) WITHIN GROUP (ORDER BY seconds) AS med, count(*) AS n FROM ("
                      " SELECT kind, seconds, row_number() OVER (PARTITION BY kind ORDER BY at DESC, id DESC) AS rn"
                      " FROM studio.hr_step_timings) x WHERE rn <= %s GROUP BY kind", (last,))
    except Exception:  # noqa: BLE001 - ETA is best effort
        log.exception("hr step medians")
        return out
    for r in rows:
        if r["kind"] in out and int(r["n"]) >= 3:
            out[r["kind"]] = max(0.2, float(r["med"]))
    return out


def estimate_s(med: dict[str, float], *, fetches: int, searches: int, people: int, team: bool) -> float:
    return (fetches * med["fetch"] + searches * med["search"] + people * med["person_model"]
            + (med["team_model"] if team else 0.0))


def _partial_person(p: dict) -> dict:
    return {"id": p["id"], "name": p["full_name"], "role": p.get("role") or "", "kind": p.get("kind") or "employee",
            "status": "waiting", "facts": [], "score": None, "fit": None, "grade": None}


def _feed_line(msg: str, level: str = "info", person: str | None = None, source: str | None = None) -> dict:
    line = {"at": now().isoformat(), "level": level if level in ("info", "found", "warn") else "info",
            "msg": msg[:300]}
    if person:
        line["person"] = person
    if source:
        line["source"] = source[:500]
    return line


def initial_progress(people: list[dict], eta_s: float | None, msg: str = "Queued — waiting for the People Analyst",
                     prev: dict | None = None, eta_range: tuple[float, float] | None = None) -> dict:
    feed = list((prev or {}).get("feed") or [])
    feed.append(_feed_line(msg))
    return {"phase": "queued", "pct": int((prev or {}).get("pct") or 0), "eta_s": None if eta_s is None
            else int(round(eta_s)),
            "eta_range_s": None if eta_s is None or eta_range is None else [int(round(eta_range[0])),
                                                                             int(round(eta_range[1]))],
            "started_at": None, "updated_at": now().isoformat(),
            "current": {"person": None, "step": "Queued", "detail": "Waiting for a research worker"},
            "feed": feed[-FEED_MAX:],
            "counters": {"pages_read": 0, "searches": 0, "facts_verified": 0, "facts_unconfirmed": 0,
                         "people_done": 0, "people_total": len(people)},
            "partial": {"people": [_partial_person(p) for p in people]}}


class HrProgress(analyst.Tracker):
    """Live progress of one run (see the module docstring). Thread-safe: the heartbeat thread saves too."""

    def __init__(self, db: Studio, tid: str, attempt: int, medians: dict[str, float] | None = None,
                 prev: dict | None = None, *, heartbeat_s: float = HEARTBEAT_S, step_max_s: float = STEP_MAX_S,
                 stats: dict[str, tuple[float, float, float]] | None = None):
        self.db, self.tid, self.attempt = db, tid, attempt
        if stats is None:  # medians only (older callers): the default range around each median
            stats = default_stats()
            for k, v in (medians or {}).items():
                if k in stats:
                    base = v / DEFAULT_TEAM_PEOPLE if k in PER_PERSON_KINDS else v
                    stats[k] = (base * DEFAULT_RANGE[0], base, base * DEFAULT_RANGE[1])
        self.stats = stats
        self.n_people = max(1, len(((prev or {}).get("partial") or {}).get("people") or []))
        self.st = per_step(self.stats, self.n_people)
        self.med = {k: v[1] for k, v in self.st.items()}
        self.heartbeat_s, self.step_max_s = heartbeat_s, step_max_s
        self.lock = threading.RLock()
        prev = prev or {}
        self.p: dict = {
            "phase": "reading", "pct": int(prev.get("pct") or 0), "eta_s": None, "eta_range_s": None,
            "started_at": now().isoformat(),
            "updated_at": now().isoformat(), "current": {"person": None, "step": "Starting", "detail": ""},
            "feed": list(prev.get("feed") or [])[-FEED_MAX:],
            "counters": {"pages_read": 0, "searches": 0, "facts_verified": 0, "facts_unconfirmed": 0,
                         "people_done": 0, "people_total": len((prev.get("partial") or {}).get("people") or [])},
            "partial": {"people": [{**x, "status": "waiting", "facts": [], "score": None, "fit": None,
                                    "grade": None, "cv": None} for x in (prev.get("partial") or {}).get("people") or []]}}
        self.planned = {k: 0 for k in DEFAULT_STEP_S}
        self.cv_plan = self.cv_done = 0.0  # seconds-weight of the CV review parts (see _estimate)
        self.done = {k: 0 for k in DEFAULT_STEP_S}
        self.cur_kind: str | None = None
        self.cur_t0 = 0.0
        self.timings: list[tuple[str, float]] = []
        self.last_save = 0.0
        self.superseded = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -------------------------------------------------------------- Tracker
    def plan(self, people: list[dict], *, fetches: int, searches: int, team: bool) -> None:
        with self.lock:
            self.planned.update(fetch=fetches, search=searches, person_model=len(people), team_model=int(team))
            self.cv_plan = CV_PART_S * len(CV_PARTS) * sum(1 for p in people if len((p.get("cv") or "").strip()) >= 200)
            self.n_people = max(1, len(people))
            self.st = per_step(self.stats, self.n_people)
            self.med = {k: v[1] for k, v in self.st.items()}
            self.p["counters"]["people_total"] = len(people)
            self.p["partial"]["people"] = [_partial_person(p) for p in people]
        self.save()

    def phase(self, phase: str) -> None:
        with self.lock:
            if phase in PHASES:
                self.p["phase"] = phase
        self.save()

    def begin(self, kind: str, person: str | None, step: str, detail: str = "") -> None:
        with self.lock:
            self.cur_kind, self.cur_t0 = kind, time.monotonic()
            self.p["current"] = {"person": person, "step": step[:120], "detail": (detail or "")[:200]}
        self.save()

    def end(self, kind: str) -> None:
        with self.lock:
            if self.cur_kind == kind:
                self.timings.append((kind, round(time.monotonic() - self.cur_t0, 3)))
            if kind in self.done:
                self.done[kind] += 1
            self.cur_kind = None

    def note(self, msg: str, *, level: str = "info", person: str | None = None, source: str | None = None) -> None:
        with self.lock:
            self.p["feed"] = (self.p["feed"] + [_feed_line(msg, level, person, source)])[-FEED_MAX:]
        self.save()

    def count(self, **inc: int) -> None:
        with self.lock:
            c = self.p["counters"]
            for k, v in inc.items():
                c[k] = int(c.get(k) or 0) + int(v)

    def person(self, pid: int, status: str, *, facts: list | None = None, score: float | None = None,
               fit: float | None = None) -> None:
        with self.lock:
            for x in self.p["partial"]["people"]:
                if x["id"] == pid:
                    x["status"] = status
                    if facts is not None:
                        x["facts"] = [{k: f.get(k) for k in ("id", "text", "quote", "url", "category", "source_id")}
                                      for f in facts][:40]
                    if score is not None:
                        x["score"], x["grade"] = score, analyst.grade(score)
                    if fit is not None:
                        x["fit"] = fit
                    if status in ("working", "done"):
                        self.p["current"]["person"] = x["name"]
        self.save()

    def cv(self, pid: int, part: str, data) -> None:
        """One part of the CV review (read / timeline / insights / claims) as soon as it is ready."""
        with self.lock:
            for x in self.p["partial"]["people"]:
                if x["id"] == pid:
                    if part in CV_PARTS and part not in (x.get("cv") or {}):
                        self.cv_done = min(self.cv_plan, self.cv_done + CV_PART_S)
                    x["cv"] = {**(x.get("cv") or {}), part: data}
        self.save()

    def llm_event(self, event: dict, person: str | None = None) -> None:
        from ..tools.search import LABELS

        t = event.get("type")
        if t in ("llm_rerouted", "llm_hedged") and event.get("message"):  # ai_gateway: quota reroute / hedge
            self.note(event["message"], level="warn", person=person)
        elif t == "llm_fallback":
            nxt = event.get("next")
            with self.lock:  # the next backend starts now: the hung-call clock restarts with it
                if self.cur_kind is not None:
                    self.cur_t0 = time.monotonic()
            self.note(f"{provider_label(event.get('failed'))} busy → using {provider_label(nxt)}" if nxt else
                      f"{provider_label(event.get('failed'))} did not answer and no other model is left",
                      level="warn", person=person)
        elif t == "search_fallback":
            f, nxt = event.get("failed"), event.get("next")
            self.note(f"{LABELS.get(f, f)} unavailable → trying {LABELS.get(nxt, nxt)}" if nxt else
                      f"{LABELS.get(f, f)} unavailable", level="warn", person=person)

    # -------------------------------------------------------------- pct / ETA / writes
    def _estimate(self) -> tuple[int, int | None, list[int] | None]:
        """pct, eta_s (p50) and [lo, hi] (p25 / p75) of the remaining planned steps."""
        med = self.med
        total = sum(max(self.planned[k], self.done[k]) * med[k] for k in med)
        done = sum(self.done[k] * med[k] for k in med)
        elapsed = time.monotonic() - self.cur_t0 if self.cur_kind in med else 0.0
        if self.cur_kind in med:
            done += min(0.9, elapsed / med[self.cur_kind]) * med[self.cur_kind]
        if total <= 0:
            return self.p["pct"], None, None
        # CV review parts run next to the research: they move the ring, not the ETA
        pct = max(int(self.p["pct"]), min(99, int(2 + 97 * (done + self.cv_done) / (total + self.cv_plan))))
        eta = max(3.0, total - done)
        rng = []
        for i in (0, 2):
            rem = 0.0
            for k, v in self.st.items():
                left = max(self.planned.get(k, 0), self.done.get(k, 0)) - self.done.get(k, 0)
                if k == self.cur_kind and left > 0:  # the running step: what is left of it
                    rem += max(0.1 * v[i], v[i] - elapsed)
                    left -= 1
                rem += max(0, left) * v[i]
            rng.append(rem)
        lo, hi = min(rng[0], eta), max(rng[1], eta)
        return pct, int(round(eta)), [int(round(max(1.0, lo))), int(round(max(3.0, hi)))]

    def save(self, *, final: bool = False) -> None:
        with self.lock:
            if not final:
                self.p["pct"], self.p["eta_s"], self.p["eta_range_s"] = self._estimate()
            self.p["updated_at"] = now().isoformat()
            n = self.db.exec("UPDATE studio.hr_teams SET progress=%s, heartbeat_at=now(), updated_at=now() "
                             "WHERE id=%s AND attempt=%s AND status='running'",
                             (Jsonb(jsonable(self.p)), self.tid, self.attempt))
            self.last_save = time.monotonic()
            if n == 0:
                self.superseded = True
                raise Superseded(f"report {self.tid} attempt {self.attempt} is no longer running")

    def complete(self, summary_msg: str) -> None:
        """Last write while the row is still 'running' (HrStore.finish then flips the status)."""
        with self.lock:
            self.p.update(phase="done", pct=100, eta_s=0, eta_range_s=[0, 0])
            self.p["current"] = {"person": None, "step": "Done", "detail": ""}
            self.p["feed"] = (self.p["feed"] + [_feed_line(f"Report written — {summary_msg}", "found")])[-FEED_MAX:]
        self.save(final=True)

    def failed(self, reason: str) -> dict:
        with self.lock:
            self.p.update(phase="failed", eta_s=None, eta_range_s=None)
            self.p["current"] = {"person": None, "step": "Failed", "detail": reason[:200]}
            self.p["feed"] = (self.p["feed"] + [_feed_line(f"The review stopped: {reason}", "warn")])[-FEED_MAX:]
            return jsonable(self.p)

    def flush_timings(self) -> None:
        if not self.timings:
            return
        try:
            with self.db.tx() as c:
                for kind, sec in self.timings:
                    c.execute("INSERT INTO studio.hr_step_timings(kind, seconds, team_id, people) "
                              "VALUES (%s,%s,%s,%s)", (kind, sec, self.tid, self.n_people))
        except Exception:  # noqa: BLE001
            log.exception("hr step timings")

    # -------------------------------------------------------------- heartbeat thread
    def start(self) -> None:
        def beat() -> None:
            while not self._stop.wait(min(1.0, self.heartbeat_s / 2)):
                with self.lock:
                    hung = self.cur_kind is not None and time.monotonic() - self.cur_t0 > self.step_max_s
                    due = time.monotonic() - self.last_save >= self.heartbeat_s
                if hung or not due:
                    continue
                try:
                    self.save()
                except Superseded:
                    return
                except Exception:  # noqa: BLE001 - DB hiccup: try again next beat
                    log.exception("hr heartbeat")

        self._thread = threading.Thread(target=beat, name=f"hr-heartbeat-{self.tid}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)


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
            c.execute("UPDATE studio.hr_teams SET status='draft', result=NULL, error=NULL, steps='[]', progress=NULL, "
                      "updated_at=now() WHERE id=%s", (tid,))

    def set_target(self, tid: str, target: dict | None) -> None:
        with self.db.tx() as c:
            row = c.execute("SELECT status FROM studio.hr_teams WHERE id=%s FOR UPDATE", (tid,)).fetchone()
            if row is None or row["status"] in ("queued", "running"):
                raise LimitError("report is queued or running")
            c.execute("UPDATE studio.hr_teams SET target=%s, status='draft', result=NULL, error=NULL, steps='[]', "
                      "progress=NULL, updated_at=now() WHERE id=%s", (Jsonb(target) if target else None, tid))

    def queue_run(self, tid: str, actor: str, *, per_wallet: int | None, max_active: int | None) -> None:
        """Queue a run under an advisory lock so concurrent requests cannot all pass the daily count."""
        with self.db.tx() as c:
            c.execute("SELECT pg_advisory_xact_lock(hashtext('studio.hr_runs'))")
            row = c.execute("SELECT status, mode FROM studio.hr_teams WHERE id=%s FOR UPDATE", (tid,)).fetchone()
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
            ppl = c.execute("SELECT id, full_name, role, kind, urls FROM studio.hr_people WHERE team_id=%s "
                            "ORDER BY position, id", (tid,)).fetchall()
            lo, eta, hi = self.estimate_range(ppl, mode=row.get("mode"))
            prog = initial_progress(ppl, eta, eta_range=(lo, hi))
            c.execute("UPDATE studio.hr_teams SET status='queued', error=NULL, error_code=NULL, error_detail=NULL, "
                      "steps=%s, progress=%s, "
                      "heartbeat_at=NULL, requeues=0, updated_at=now() WHERE id=%s",
                      (Jsonb([step("queued", None, "waiting for the People Analyst")]), Jsonb(prog), tid))

    def estimate(self, people: list[dict], *, mode: str | None) -> float:
        """Rough ETA (p50) of a whole run before it starts."""
        return self.estimate_range(people, mode=mode)[1]

    def estimate_range(self, people: list[dict], *, mode: str | None) -> tuple[float, float, float]:
        """(p25, p50, p75) seconds of a whole run before it starts (percentile model x the planned steps)."""
        from ..config import get_settings

        s = get_settings()
        per_team = s.hr_searches_per_team if (mode or "team") == "team" else s.hr_searches_per_person
        fetches = len({u for p in people for u in (p.get("urls") or [])[:6] if analyst._readable(u)})
        return estimate_range(step_stats(self.db), fetches=fetches, people=len(people),
                              team=(mode or "team") == "team",
                              searches=min(per_team, len(people) * s.hr_searches_per_person))

    def claim(self) -> dict | None:
        return self.db.one(
            "UPDATE studio.hr_teams SET status='running', started_at=now(), updated_at=now(), heartbeat_at=now(), "
            "attempt=attempt+1 WHERE id = ("
            " SELECT t.id FROM studio.hr_teams t WHERE t.status='queued' AND (t.valuation_id IS NULL OR NOT EXISTS ("
            "  SELECT 1 FROM studio.valuations v WHERE v.id=t.valuation_id AND v.status IN ('queued','running')))"
            " ORDER BY t.updated_at FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *")

    def add_step(self, tid: str, st: dict, attempt: int | None = None) -> None:
        with self.db.tx() as c:
            row = c.execute("SELECT steps, attempt FROM studio.hr_teams WHERE id=%s FOR UPDATE", (tid,)).fetchone()
            if row is None or (attempt is not None and row["attempt"] != attempt):
                return
            steps = (row["steps"] or []) + [st]
            c.execute("UPDATE studio.hr_teams SET steps=%s, updated_at=now() WHERE id=%s",
                      (Jsonb(steps[-MAX_STEPS:]), tid))

    def finish(self, tid: str, result: dict, attempt: int | None = None) -> bool:
        """-> False when this attempt no longer owns the run (re-queued / failed by the watchdog)."""
        if attempt is None:
            return self.db.exec("UPDATE studio.hr_teams SET status='done', result=%s, error=NULL, finished_at=now(), "
                                "updated_at=now() WHERE id=%s", (Jsonb(jsonable(result)), tid)) > 0
        return self.db.exec("UPDATE studio.hr_teams SET status='done', result=%s, error=NULL, finished_at=now(), "
                            "updated_at=now() WHERE id=%s AND attempt=%s AND status='running'",
                            (Jsonb(jsonable(result)), tid, attempt)) > 0

    def fail(self, tid: str, error: str, attempt: int | None = None, progress: dict | None = None, *,
             code: str | None = None, detail: str | None = None) -> bool:
        """`error`: the plain sentence users see; `code`: its ERROR_TEXT code (classified from `error` when not
        given); `detail`: internal text (platform admins / audit only)."""
        code = code if code in ERROR_TEXT else classify_text(error)
        sets = ("status='failed', error=%s, error_code=%s, error_detail=%s, finished_at=now(), updated_at=now()"
                + (", progress=%s" if progress else ""))
        params: list = [error[:1000], code, (detail or None) and detail[:4000]] + (
            [Jsonb(progress)] if progress else []) + [tid]
        if attempt is None:
            return self.db.exec(f"UPDATE studio.hr_teams SET {sets} WHERE id=%s", params) > 0
        return self.db.exec(f"UPDATE studio.hr_teams SET {sets} WHERE id=%s AND attempt=%s AND status='running'",
                            params + [attempt]) > 0

    def watchdog(self, stall_s: float = STALL_S) -> dict:
        """Running reports with no heartbeat for `stall_s`: re-queue once, then fail with a clear reason."""
        out: dict[str, list[str]] = {"requeued": [], "failed": []}
        stale = ("status='running' AND coalesce(heartbeat_at, started_at, updated_at) < "
                 "now() - make_interval(secs => %s)")
        for r in self.db.all(f"SELECT id FROM studio.hr_teams WHERE {stale}", (stall_s,)):
            with self.db.tx() as c:
                t = c.execute(f"SELECT * FROM studio.hr_teams WHERE id=%s AND {stale} FOR UPDATE SKIP LOCKED",
                              (r["id"], stall_s)).fetchone()
                if t is None:
                    continue
                prev = t.get("progress") or {}
                if int(t.get("requeues") or 0) < MAX_REQUEUES:
                    ppl = c.execute("SELECT id, full_name, role, kind, urls FROM studio.hr_people WHERE team_id=%s "
                                    "ORDER BY position, id", (t["id"],)).fetchall()
                    prog = initial_progress(ppl, None, f"No progress for {int(stall_s)} s — the run was restarted "
                                                       f"automatically (retry {int(t['requeues']) + 1} of "
                                                       f"{MAX_REQUEUES})", prev)
                    prog["feed"][-1]["level"] = "warn"
                    c.execute("UPDATE studio.hr_teams SET status='queued', requeues=requeues+1, progress=%s, "
                              "heartbeat_at=NULL, updated_at=now() WHERE id=%s", (Jsonb(jsonable(prog)), t["id"]))
                    out["requeued"].append(t["id"])
                else:
                    reason = ERROR_TEXT["stalled"]
                    detail = (f"watchdog: no heartbeat for {int(stall_s)} s after {int(t.get('requeues') or 0)} "
                              f"restart(s); attempt {t.get('attempt')}")
                    prog = {**prev, "phase": "failed", "eta_s": None, "eta_range_s": None,
                            "updated_at": now().isoformat(),
                            "current": {"person": None, "step": "Failed", "detail": reason[:200]},
                            "feed": (list(prev.get("feed") or []) + [_feed_line(reason, "warn")])[-FEED_MAX:]}
                    c.execute("UPDATE studio.hr_teams SET status='failed', error=%s, error_code='stalled', "
                              "error_detail=%s, progress=%s, finished_at=now(), updated_at=now() WHERE id=%s",
                              (reason, detail, Jsonb(jsonable(prog)), t["id"]))
                    c.execute("INSERT INTO studio.audit(actor,action,target,detail) VALUES (%s,%s,%s,%s)",
                              ("people_analyst", "hr_run_failed", t["id"],
                               Jsonb({"code": "stalled", "detail": detail})))
                    out["failed"].append(t["id"])
        for tid in out["requeued"]:
            log.warning("hr report %s stalled: re-queued", tid)
        for tid in out["failed"]:
            log.warning("hr report %s stalled again: failed", tid)
        return out

    def set_result(self, tid: str, result: dict) -> None:
        self.db.exec("UPDATE studio.hr_teams SET result=%s, updated_at=now() WHERE id=%s",
                     (Jsonb(jsonable(result)), tid))

    def rotate_share(self, tid: str) -> str:
        tok = secrets.token_urlsafe(18)
        self.db.exec("UPDATE studio.hr_teams SET share_token=%s, updated_at=now() WHERE id=%s", (tok, tid))
        return tok


# ------------------------------------------------------------------ progress view (API)
def progress_view(t: dict, *, stall_s: float = STALL_S) -> dict | None:
    """`progress` of GET /v1/hr/teams/{id} (contract in studio/hr.py). None for drafts. Phase "stalled" when
    running with no heartbeat for `stall_s`; the ETA counts down from the last write."""
    status = t.get("status")
    if status == "draft" or not status:
        return None
    p = dict(t.get("progress") or {})
    hb = t.get("heartbeat_at") or t.get("started_at") or t.get("updated_at")
    if not p:  # a report from before live progress
        cards = (t.get("result") or {}).get("people") or []
        p = initial_progress([], None, "Report written" if status == "done" else status.capitalize())
        p["counters"].update(people_total=len(cards), people_done=len(cards) if status == "done" else 0)
        p["partial"] = {"people": [{"id": c.get("person_id"), "name": c.get("full_name"), "role": c.get("role"),
                                    "kind": c.get("kind"), "status": "done", "facts": [], "score": c.get("score"),
                                    "fit": (c.get("fit") or {}).get("score"), "grade": analyst.grade(c.get("score"))}
                                   for c in cards]}
    p["updated_at"] = _iso(hb) or p.get("updated_at")
    p.setdefault("eta_range_s", None)
    if status == "done":
        p.update(phase="done", pct=100, eta_s=0, eta_range_s=[0, 0])
        for x in (p.get("partial") or {}).get("people") or []:
            x["status"] = "done" if x.get("status") in ("done", "working", "waiting") else x.get("status")
    elif status == "failed":
        p.update(phase="failed", eta_s=None, eta_range_s=None)
        plain = public_error(t)[1]
        if plain and (not t.get("error_code") or (p.get("current") or {}).get("step") != "Failed"):
            p["current"] = {"person": None, "step": "Failed", "detail": plain[:200]}
    elif status == "queued":
        p["phase"] = "queued"
    elif status == "running" and isinstance(hb, datetime):
        age = (now() - hb).total_seconds()
        if age > stall_s:
            p.update(phase="stalled", eta_s=None, eta_range_s=None)
            p["current"] = {**(p.get("current") or {}), "step": "Stalled",
                            "detail": f"No progress for {int(age)} s — the watchdog restarts it once, then stops it"}
        elif p.get("eta_s") is not None:
            p["eta_s"] = max(1, int(p["eta_s"] - max(0.0, age)))
            if p.get("eta_range_s"):
                lo, hi = p["eta_range_s"]
                p["eta_range_s"] = [max(1, min(p["eta_s"], int(lo - max(0.0, age)))),
                                    max(p["eta_s"], int(hi - max(0.0, age)))]
    p.setdefault("feed", [])
    p.setdefault("partial", {"people": []})
    return p


# ------------------------------------------------------------------ summary + valuation blend
def person_url(t: dict, pid, public_url: str) -> str:
    return f"{public_url}/p/{t['id']}" if t.get("mode") == "person" else f"{public_url}/r/{t['id']}/p/{pid}"


def confidence_of(cards: list[dict]) -> str | None:
    """Share of the weighted points (fit components, else quality sub-scores) backed by verified facts:
    >= 0.75 high, >= 0.45 medium, else low — the hr UI's confidenceOf (pages/hr/evidence.tsx)."""
    parts = [x for c in cards for x in ((c.get("fit") or {}).get("components") or c.get("subscores") or {}).values()]
    tot = sum(float(x.get("score") or 0) * float(x.get("weight") or 0) for x in parts)
    if not parts or tot <= 0:
        return None
    ver = sum(float(x.get("score") or 0) * float(x.get("weight") or 0) for x in parts
              if not x.get("capped") and not x.get("self_reported") and x.get("fact_ids"))
    share = ver / tot
    return "high" if share >= 0.75 else "medium" if share >= 0.45 else "low"


def summary(t: dict, public_url: str) -> dict:
    """Public-safe: score, grade, names + roles + numbers, top strengths / gaps, live progress. No facts, no
    sources."""
    res = t.get("result") or {}  # a re-run keeps the previous result until it finishes
    block = res.get("team") or {}
    cards = res.get("people") or []
    if t.get("mode") == "person" and cards:
        c0 = cards[0]
        score = (c0.get("fit") or {}).get("score", c0.get("score"))
        strengths, gaps = c0.get("strengths") or [], (c0.get("fit") or {}).get("missing") or c0.get("gaps") or []
    else:
        score = block.get("score")
        strengths, gaps = block.get("strengths") or [], block.get("gaps") or []
    pv = progress_view(t)
    if cards:
        people = [{"id": c.get("person_id"), "full_name": c.get("full_name"), "role": c.get("role"),
                   "kind": c.get("kind"), "score": c.get("score"), "fit": (c.get("fit") or {}).get("score"),
                   "fit_label": (c.get("fit") or {}).get("label"),
                   "fit_matched": ((c.get("fit") or {}).get("matched") or [])[:3],
                   "fit_missing": ((c.get("fit") or {}).get("missing") or [])[:3],
                   "status": "done" if t.get("status") in ("done", "failed") else "working",
                   "url": person_url(t, c.get("person_id"), public_url)} for c in cards]
    else:  # not done yet: names + roles + partial numbers from the live progress
        people = [{"id": x.get("id"), "full_name": x.get("name"), "role": x.get("role") or "",
                   "kind": x.get("kind") or "employee", "score": x.get("score"), "fit": x.get("fit"),
                   "fit_label": None, "fit_matched": [], "fit_missing": [], "status": x.get("status") or "waiting",
                   "url": person_url(t, x.get("id"), public_url)}
                  for x in ((pv or {}).get("partial") or {}).get("people") or []]
    return {"id": t["id"], "mode": t.get("mode") or "team", "name": t.get("name"), "status": t.get("status"),
            "valuation_id": t.get("valuation_id"), "score": score, "grade": analyst.grade(score),
            "people": people, "strengths": strengths[:3], "gaps": gaps[:3], "url": f"{public_url}/r/{t['id']}",
            "confidence": confidence_of(cards),
            "error": (public_error(t)[1] or "")[:300] or None if t.get("status") == "failed" else None,
            "error_code": public_error(t)[0] if t.get("status") == "failed" else None,
            "progress": {k: pv.get(k) for k in ("phase", "pct", "eta_s", "eta_range_s", "updated_at")} if pv else None}


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
    team = {**summary(t, public_url), "applied": patch is not None, "reason": reason,
            "applied_at": now().isoformat() if patch is not None else None}
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
    heartbeat_s = HEARTBEAT_S

    def __init__(self, deps: Deps, db: Studio):
        self.deps, self.db, self.store = deps, db, HrStore(db)

    def run(self, t: dict) -> str:
        tid = t["id"]
        attempt = t.get("attempt")
        people = self.store.people(tid)
        if not people:
            self.store.fail(tid, ERROR_TEXT["no_people"], attempt, code="no_people", detail="no people to analyse")
            return "failed"

        def progress(st: str, person: str | None, msg: str) -> None:
            try:
                self.store.add_step(tid, step(st, person, msg), attempt)
            except Exception:  # progress must never kill the run
                log.exception("hr progress")

        tr = HrProgress(self.db, tid, int(attempt or 0), None, t.get("progress"), heartbeat_s=self.heartbeat_s,
                        stats=step_stats(self.db))
        if attempt is None:  # a row that was not claimed by claim() (tests / manual): do not guard on attempt
            tr.attempt = int(self.db.one("SELECT attempt FROM studio.hr_teams WHERE id=%s", (tid,))["attempt"])
        tr.start()
        try:
            try:
                tr.note("A research worker picked up the review", person=None)
                target = resolve_target(self.db, t, self.deps)
                if (target or {}).get("type") == "business" and (target or {}).get("company"):
                    tr.note(f"Comparing with the business: {target['company']}"
                            + (f" ({target['sector']})" if target.get("sector") else ""))
                name = t.get("name") or ""
                if (t.get("mode") or "team") == "team" and (target or {}).get("company") and " " not in name \
                        and "." in name:  # created at valuation start with the host name: use the company's name
                    t = {**t, "name": target["company"]}
                    self.db.exec("UPDATE studio.hr_teams SET name=%s WHERE id=%s", (target["company"], tid))
                result = analyst.analyse({"id": tid, "mode": t.get("mode") or "team", "name": t.get("name"),
                                          "website": t.get("website")}, people, self.deps, target=target,
                                         progress=progress, tracker=tr)
                block = result.get("team")
                tr.complete(f"team score {block['score']:.0f} (grade {block['grade']})" if block else
                            f"{len(result.get('people') or [])} person report(s)")
            except Superseded:
                log.warning("hr report %s attempt %s was taken over by the watchdog; stopping", tid, attempt)
                return "superseded"
            except Exception as e:
                log.exception("hr report %s failed", tid)
                code = classify_error(e)
                plain, detail = ERROR_TEXT[code], f"{type(e).__name__}: {e}"
                progress("failed", None, plain)
                try:
                    self.db.audit(analyst.AGENT, "hr_run_failed", tid, code=code, detail=detail[:2000])
                    self.deps.audit.record(analyst.AGENT, "hr_run_failed", team=tid, code=code, error=detail[:1000])
                except Exception:  # noqa: BLE001 - the failure itself must still be recorded on the row
                    log.exception("hr failure audit")
                self.store.fail(tid, plain, tr.attempt, tr.failed(plain), code=code, detail=detail)
                return "failed"
        finally:
            tr.stop()
        if not self.store.finish(tid, result, tr.attempt):
            log.warning("hr report %s attempt %s finished after the watchdog took it over; result dropped", tid,
                        attempt)
            return "superseded"
        tr.flush_timings()
        if t.get("valuation_id") and (t.get("mode") or "team") == "team":
            try:
                apply_to_valuation(self.db, self.store.team(tid), self.deps.settings.hr_public_url)
            except Exception:
                log.exception("hr blend into valuation %s failed", t.get("valuation_id"))
        return "done"

    def drain(self) -> int:
        try:
            self.store.watchdog()
        except Exception:  # noqa: BLE001 - the watchdog never blocks the queue
            log.exception("hr watchdog")
        n = 0
        from ..ai_gateway import user_scope

        while (t := self.store.claim()) is not None:
            with user_scope(t.get("requested_by")):  # fair per-user model queue (ai_gateway.FairLimiter)
                log.info("hr report %s (%s) -> %s", t["id"], t.get("mode"), self.run(t))
            n += 1
        return n



# ------------------------------------------------------------------ watchdog loop (API process)
class HrWatchdog:
    """Background loop in the API (like the dividend automation): re-queues / fails stalled HR runs even when the
    worker itself is stuck. HR_WATCHDOG_SECONDS (default 30; 0 disables)."""

    def __init__(self, db: Studio | None):
        self.db = db
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def tick(self) -> dict:
        return HrStore(self.db).watchdog() if self.db is not None else {"requeued": [], "failed": []}

    def start(self, interval_s: float) -> None:
        if interval_s <= 0 or self._thread is not None or self.db is None:
            return

        def loop() -> None:
            while not self._stop.wait(interval_s):
                try:
                    self.db.ensure_schema()
                    self.tick()
                except Exception:  # DB down etc.: try again next time
                    log.exception("hr watchdog tick failed")

        self._thread = threading.Thread(target=loop, name="hr-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


def watchdog_interval_from_env() -> float:
    try:
        return max(0.0, float(os.environ.get("HR_WATCHDOG_SECONDS", "30")))
    except ValueError:
        return 30.0
