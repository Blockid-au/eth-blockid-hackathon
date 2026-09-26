"""Runs the `site_valuation` graph for rows of studio.valuations.

The worker calls `run()` for queued rows; the API calls `decide()` when an admin answers the
valuation gate (the resume only re-scores deterministically — no LLM or web calls — so it is
done synchronously and the updated valuation is returned to the admin at once).
Both processes share the LangGraph checkpointer (Postgres in production).
"""
from __future__ import annotations

import logging

from langgraph.types import Command

from ..agents import valuation
from ..deps import Deps
from ..graph import build_site_valuation, site_result
from .db import Studio, StudioProgress

log = logging.getLogger(__name__)


def thread(vid: str) -> dict:
    return {"configurable": {"thread_id": f"studio-valuation-{vid}"}}


class ValuationRunner:
    def __init__(self, deps: Deps, checkpointer, db: Studio, progress=None):
        self.deps, self.db = deps, db
        self.progress = progress or StudioProgress(db)
        self.graph = build_site_valuation(deps, checkpointer, self.progress)

    def run(self, vid: str, url: str, self_reported: dict | None = None) -> str:
        try:
            out = self.graph.invoke({"job_id": vid, "url": url, "self_reported": self_reported or None}, thread(vid))
        except Exception as e:
            log.exception("valuation %s failed", vid)
            self.progress.status(vid, "failed", f"{type(e).__name__}: {e}"[:1000])
            return "failed"
        self.progress.result(vid, **site_result(self.deps, out))
        if out.get("__interrupt__"):
            self.progress.status(vid, "waiting_approval")
            return "waiting_approval"
        status = out.get("status") if out.get("status") in ("approved", "rejected") else "failed"
        self.progress.status(vid, status)
        return status

    def drain(self) -> int:
        n = 0
        while (row := self.db.claim_valuation()) is not None:
            status = self.run(row["id"], row["url"], row.get("self_reported"))
            log.info("valuation %s (%s) -> %s", row["id"], row["url"], status)
            n += 1
        return n

    def decide(self, vid: str, approved: bool, overrides: dict[str, float], reviewer: str) -> str:
        decision = {"approved": approved, "overrides": overrides, "reviewer": reviewer}
        cfg = thread(vid)
        if self.graph.get_state(cfg).interrupts:
            out = self.graph.invoke(Command(resume=decision), cfg)
            patch = {k: out[k] for k in ("svi", "qualitative") if approved and out.get(k)}
        else:  # checkpoint unavailable (e.g. separate SQLite files): re-score from the stored result
            row = self.db.get_valuation(vid) or {}
            res = {**(row.get("result") or {}), "self_reported": row.get("self_reported")}
            if not (res.get("qualitative") and res.get("profile") and res.get("svi")):
                raise RuntimeError("valuation has no scores to decide on")
            patch = {}
            if approved:
                patch = valuation.apply_overrides(res, overrides, reviewer, self.deps)
            else:
                self.deps.audit.record("human", "valuation_rejected", reviewer=reviewer)
        if patch:
            self.progress.result(vid, **patch)
        status = "approved" if approved else "rejected"
        self.progress.status(vid, status)
        return status
