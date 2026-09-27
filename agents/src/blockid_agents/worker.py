"""Worker: drains the job queue in batch. Run with `python -m blockid_agents worker`."""
from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

from langgraph.types import Command

from .deps import Deps
from .graph import build_dividend, build_onboarding, build_site_valuation
from .jobs import GceGpuController, GpuController, JobQueue

log = logging.getLogger(__name__)

# Jobs that call the local model need the GPU VM; dividends are pure maths.
NEEDS_GPU = {"onboarding"}


def make_checkpointer(deps: Deps):
    url = deps.settings.database_url
    if url.startswith("postgres"):
        import psycopg
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg.rows import dict_row

        conn = psycopg.Connection.connect(url, autocommit=True, prepare_threshold=0, row_factory=dict_row)
        saver = PostgresSaver(conn)
        saver.setup()
        return saver
    from langgraph.checkpoint.sqlite import SqliteSaver

    path = Path(deps.settings.data_dir) / "checkpoints.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(path, check_same_thread=False))


class Worker:
    def __init__(self, deps: Deps, queue: JobQueue, checkpointer, gpu: GpuController | None = None, studio=None):
        self.deps, self.queue = deps, queue
        self.graphs = {
            "onboarding": build_onboarding(deps, checkpointer),
            "dividend": build_dividend(deps, checkpointer),
            "site_valuation": build_site_valuation(deps, checkpointer),
        }
        self.gpu = gpu or GpuController()
        self.valuations = None  # Issuance Studio: studio.valuations rows are the queue for site valuations
        if studio is not None:
            from .studio.runner import ValuationRunner

            self.valuations = ValuationRunner(deps, checkpointer, studio)
        self.hr = None  # founding-team / person reviews (studio/hr_store.py); run after valuations each drain
        if studio is not None:
            from .studio.hr_store import HrRunner

            self.hr = HrRunner(deps, studio)

    @classmethod
    def from_settings(cls, deps: Deps) -> "Worker":
        s = deps.settings
        gpu = (
            GceGpuController(s.gcp_project, s.ai_vm_zone, s.ai_vm_name, s.llm_gateway_url.rsplit("/v1", 1)[0] + "/health/liveliness")
            if s.gpu_autostart
            else GpuController()
        )
        studio = None
        if s.database_url.startswith("postgres"):
            from .studio.db import Studio

            studio = Studio(s.database_url, max_size=4)
            studio.apply_schema()
        return cls(deps, JobQueue(Path(s.data_dir) / "jobs.sqlite"), make_checkpointer(deps), gpu, studio)

    def process(self, job: dict) -> str:
        graph = self.graphs[job["graph"]]
        config = {"configurable": {"thread_id": job["thread_id"]}}
        if job["kind"] == "resume":
            decision = job["payload"].get("decision") or {}
            # Validate BEFORE touching the graph: a malformed resume value would be stored in the
            # checkpoint and replayed on every later resume, poisoning the workflow.
            if not decision.get("reviewer") or not isinstance(decision.get("approved"), bool):
                self.queue.set(job["id"], "rejected_input", error="decision needs 'reviewer' and boolean 'approved'")
                return "rejected_input"
            state = graph.get_state(config)
            if not state.interrupts:
                self.queue.set(job["id"], "rejected_input", error="workflow is not paused at a gate")
                return "rejected_input"
            inp = Command(resume=decision)
        else:
            inp = {**job["payload"], "job_id": job["thread_id"]}
        try:
            if job["graph"] in NEEDS_GPU:
                self.gpu.ensure_running()
            out = graph.invoke(inp, config)
        except Exception as e:  # checkpoint keeps progress; Spot pre-emption -> retry up to 3 times
            log.exception("job %s failed", job["id"])
            if job["attempts"] < 3:
                self.queue.requeue(job["id"])
                return "requeued"
            self.queue.set(job["id"], "failed", error=str(e))
            return "failed"

        interrupts = out.get("__interrupt__") or []
        clean = {k: v for k, v in out.items() if k not in ("__interrupt__", "dataroom")}
        if interrupts:
            self.queue.set(job["id"], "waiting_human", gate=interrupts[0].value, result=clean)
            return "waiting_human"
        self.queue.set(job["id"], "done", result=clean)
        return "done"

    def drain(self) -> int:
        n = 0
        while (job := self.queue.claim_next()) is not None:
            log.info("job %s (%s/%s) -> %s", job["id"], job["kind"], job["graph"], self.process(job))
            n += 1
        if self.valuations is not None:
            n += self.valuations.drain()
        if self.hr is not None:
            n += self.hr.drain()
        return n

    def forever(self, poll_s: float = 10) -> None:
        while True:
            if self.drain() == 0:
                time.sleep(poll_s)
