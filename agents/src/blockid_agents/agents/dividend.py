"""Agent 6 — Dividend: snapshot -> pro-rata amounts -> Merkle root -> UNSIGNED Safe batch.

Deterministic maths (integer arithmetic, rounding down); the undistributable remainder stays with
the issuer. Balances come from the chain indexer at `record_block` (read_balances tool).
"""
from __future__ import annotations

import hashlib
import time

from ..deps import Deps
from ..schemas import DividendPlan
from ..tools import chain
from ..tools.merkle import build_distribution

AGENT = "dividend"


def allocate(balances: dict[str, int], total_amount: int) -> tuple[dict[str, int], int]:
    shares = {a: int(b) for a, b in balances.items() if int(b) > 0}
    supply = sum(shares.values())
    if supply == 0:
        raise ValueError("no shareholders at record block")
    alloc = {a: total_amount * s // supply for a, s in shares.items()}
    alloc = {a: v for a, v in alloc.items() if v > 0}
    return alloc, total_amount - sum(alloc.values())


def plan(state: dict, deps: Deps) -> dict:
    req = state["dividend"]
    deps.tool(AGENT, "read_balances", record_block=req["record_block"], holders=len(req["balances"]))
    alloc, remainder = allocate(req["balances"], int(req["total_amount"]))
    deps.tool(AGENT, "build_merkle", holders=len(alloc))
    dist = build_distribution(alloc)
    p = DividendPlan(
        record_block=int(req["record_block"]),
        pay_token=req["pay_token"],
        total_amount=dist.total,
        merkle_root=dist.root,
        holders=len(alloc),
        claims=dist.claims,
        remainder_to_issuer=remainder,
    )
    return {"dividend_plan": p.model_dump(), "status": "dividend_planned"}


def build_batch(state: dict, deps: Deps) -> dict:
    req, p = state["dividend"], DividendPlan.model_validate(state["dividend_plan"])
    deps.tool(AGENT, "build_unsigned_tx", round_total=p.total_amount)
    resolution = "0x" + hashlib.sha256(req.get("board_resolution_id", state["job_id"]).encode()).hexdigest()
    deadline = int(req.get("claim_deadline", time.time() + 180 * 86400))
    txs = [
        chain.tx_approve(p.pay_token, req["distributor"], p.total_amount),
        chain.tx_create_round(
            req["distributor"], p.merkle_root, p.pay_token, p.total_amount, p.record_block, deadline, resolution
        ),
    ]
    batch = chain.safe_batch(deps.settings.chain_id, f"Dividend — {state['job_id']}", txs, created_by=AGENT)
    return {"safe_batch": batch.model_dump(), "status": "awaiting_safe_signatures"}
