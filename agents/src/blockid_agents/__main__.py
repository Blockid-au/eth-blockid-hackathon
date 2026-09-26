"""CLI entry point.

    python -m blockid_agents api            # HTTP API (uvicorn) on :8080
    python -m blockid_agents worker         # drain the AI job queue forever (batch mode)
    python -m blockid_agents worker --once  # drain once then exit (cron / Cloud Scheduler style)
    python -m blockid_agents issuer         # internal issuer service on :8090 (holds the keys)
    python -m blockid_agents demo           # full offline demo: fakes only, no API spend, no GPU
    python -m blockid_agents verify-audit   # check the audit hash chain
    python -m blockid_agents svi profile.json [--no-research]
                                            # live: Brave research -> SVI valuation for one StartupProfile
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile
import uuid
from dataclasses import replace
from pathlib import Path


def _demo() -> None:
    from .audit import AuditLog
    from .config import get_settings
    from .deps import Deps
    from .fakes import (DEMO_CAP_TABLE, DEMO_DATAROOM, DEMO_DEPLOYMENT, DEMO_INPUTS, DEMO_KYC, fake_brave_transport,
                        fake_fetch, fake_forge_runner, fake_llm)
    from .jobs import JobQueue
    from .tools.brave import BraveSearch, EvidenceStore
    from .worker import Worker, make_checkpointer

    tmp = Path(tempfile.mkdtemp(prefix="blockid-demo-"))
    s = replace(get_settings(), data_dir=str(tmp), contracts_dir=str(tmp / "contracts"), database_url="")
    store = EvidenceStore(tmp / "evidence.sqlite")
    deps = Deps(
        llm=fake_llm(), audit=AuditLog(tmp / "audit.jsonl"), evidence=store, settings=s,
        brave=BraveSearch("demo-key", store, max_rps=0, transport=fake_brave_transport()),
        forge_runner=fake_forge_runner, fetcher=fake_fetch,
    )
    w = Worker(deps, JobQueue(tmp / "jobs.sqlite"), make_checkpointer(deps))
    q = w.queue

    def show(title, wid):
        j = q.latest_for_thread(wid)
        print(f"\n=== {title}: status={j['status']}")
        return j

    wid = q.enqueue("onboarding", "onboarding", {"dataroom": DEMO_DATAROOM, "issuance_inputs": DEMO_INPUTS})
    w.drain()
    j = show("Onboarding -> valuation gate", wid)
    svi = j["gate"]["svi"]
    print(f"SVI index {svi['index']} ({svi['band']}); valuation mid A${svi['valuation_mid_aud']:,.0f}")
    print("Needs review:", *svi["needs_human_review"], sep="\n  - ")

    q.enqueue("resume", "onboarding", {"decision": {"approved": True, "reviewer": "long@blockid.au",
                                                    "overrides": {"investment_readiness": 50}}}, thread_id=wid)
    w.drain()
    j = show("Contract gate", wid)
    print("Checks:", j["gate"]["contract_check"]["forge_summary"], "|", j["gate"]["contract_check"]["slither_summary"])

    q.enqueue("resume", "onboarding", {"decision": {"approved": True, "reviewer": "long@blockid.au",
                                                    "deployment": DEMO_DEPLOYMENT, "cap_table": DEMO_CAP_TABLE,
                                                    "kyc": DEMO_KYC}}, thread_id=wid)
    w.drain()
    j = show("Registry", wid)
    for t in j["result"]["safe_batch"]["transactions"]:
        print("  -", t["description"])

    did = q.enqueue("dividend", "dividend", {"dividend": {
        "record_block": 1234, "total_amount": 50_000_000_000, "pay_token": "0x4444444444444444444444444444444444444444",
        "distributor": DEMO_DEPLOYMENT["distributor"], "board_resolution_id": "AGRITRACE-DIV-2026-12",
        "balances": {e["wallet"]: e["shares"] for e in DEMO_CAP_TABLE}}})
    w.drain()
    j = show("Dividend gate", did)
    print(json.dumps(j["gate"]["summary"], indent=2))
    q.enqueue("resume", "dividend", {"decision": {"approved": True, "reviewer": "long@blockid.au"}}, thread_id=did)
    w.drain()
    show("Dividend batch", did)
    print(f"\nAudit chain valid: {deps.audit.verify()}  (files in {tmp})")


def _load_dotenv() -> None:
    """Local dev only: read KEY=VALUE lines from the nearest .env without overriding the real environment."""
    for d in [Path.cwd(), *Path.cwd().parents]:
        f = d / ".env"
        if f.is_file():
            for line in f.read_text().splitlines():
                k, sep, v = line.strip().partition("=")
                if sep and k and not k.startswith("#"):
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def _svi(profile_path: str, research_enabled: bool) -> None:
    from .agents import research, valuation
    from .deps import Deps
    from .llm import build_llm
    from .schemas import StartupProfile

    llm = build_llm()
    deps = Deps.default(llm)
    profile = StartupProfile.model_validate_json(Path(profile_path).read_text())
    state: dict = {"job_id": f"svi-{uuid.uuid4().hex[:8]}", "profile": profile.model_dump()}
    if research_enabled:
        state |= research.run(state, deps)
        print(f"Evidence collected: {state['evidence_count']}"
              + ("" if state["market"] else "  (no market data — Brave key/quota? see audit log)"))
    state |= valuation.run(state, deps)
    r = state["svi"]
    print(json.dumps(r, indent=2, ensure_ascii=False))
    print(f"\nSVI {r['index']} ({r['band']}); valuation A${r['valuation_low_aud']:,.0f} – "
          f"A${r['valuation_mid_aud']:,.0f} – A${r['valuation_high_aud']:,.0f}")
    for backend in {b for inner in getattr(llm, "routes", {}).values() for b in getattr(inner, "used", [])}:
        print("LLM:", *backend)


def main() -> None:
    ap = argparse.ArgumentParser(prog="blockid_agents")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("api")
    wp = sub.add_parser("worker")
    wp.add_argument("--once", action="store_true")
    sub.add_parser("demo")
    sub.add_parser("issuer")
    sub.add_parser("verify-audit")
    sp = sub.add_parser("svi")
    sp.add_argument("profile", help="StartupProfile JSON file")
    sp.add_argument("--no-research", action="store_true", help="skip Brave search")
    args = ap.parse_args()
    _load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.cmd == "demo":
        logging.getLogger().setLevel(logging.WARNING)
        _demo()
    elif args.cmd == "api":
        import uvicorn

        from .api import create_app

        uvicorn.run(create_app(), host="0.0.0.0", port=8080)
    elif args.cmd == "worker":
        from .deps import Deps
        from .llm import build_llm
        from .worker import Worker

        w = Worker.from_settings(Deps.default(build_llm()))
        w.drain() if args.once else w.forever()
    elif args.cmd == "issuer":
        try:
            from .issuer.app import run
        except ImportError as e:
            raise SystemExit(f"issuer service is not available in this build ({e}); "
                             "expected blockid_agents/issuer/app.py with run()") from e
        run()
    elif args.cmd == "svi":
        _svi(args.profile, not args.no_research)
    elif args.cmd == "verify-audit":
        from .audit import AuditLog
        from .config import get_settings

        ok = AuditLog(Path(get_settings().data_dir) / "audit.jsonl").verify()
        print("audit chain OK" if ok else "AUDIT CHAIN BROKEN")
        raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
