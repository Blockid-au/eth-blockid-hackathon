"""Agent 5 — Registry: approved cap table -> UNSIGNED Safe batch (KYC register + issue + anchor valuation).

Fully deterministic — no LLM is needed to encode transactions, so none is used. The agent has no
key material; the issuer's signers review and co-sign the batch in Safe{Wallet}.
"""
from __future__ import annotations

import hashlib

from ..deps import Deps
from ..schemas import CapTableEntry, SVIResult
from ..tools import chain

AGENT = "registry"

ISO_NUMERIC = {"AU": 36, "VN": 704, "SG": 702, "US": 840, "NZ": 554, "NG": 566, "GB": 826, "JP": 392}


def _ref(text: str) -> str:
    return "0x" + hashlib.sha256(text.encode()).hexdigest()


def run(state: dict, deps: Deps) -> dict:
    dep = state["deployment"]  # addresses supplied by the operator after the human-run deployment
    token, registry = dep["token"], dep["identity_registry"]
    cap = [CapTableEntry.model_validate(x) for x in state["cap_table"]]
    svi = SVIResult.model_validate(state["svi"])
    kyc = state.get("kyc", {})  # holder_ref -> {"country": "AU", "expires_at": 0}
    resolution = _ref(state["issuance_inputs"].get("board_resolution_id", state["job_id"]))

    deps.tool(AGENT, "build_unsigned_tx", holders=len(cap))
    txs = []
    for e in cap:
        k = kyc.get(e.holder_ref, {})
        country = ISO_NUMERIC.get(str(k.get("country", "AU")).upper(), 0)
        txs.append(chain.tx_register_investor(registry, e.wallet, country, int(k.get("expires_at", 0)), _ref(e.holder_ref)))
    txs += [chain.tx_issue(token, e.wallet, e.shares, resolution) for e in cap]

    total_shares = sum(e.shares for e in cap)
    per_share_cents = int(round(svi.valuation_mid_aud * 100 / total_shares)) if total_shares else 0
    txs.append(chain.tx_anchor_valuation(token, chain.to_bytes32_hex(svi.report_sha256), per_share_cents))

    batch = chain.safe_batch(deps.settings.chain_id, f"Issue shares — {state['job_id']}", txs, created_by=AGENT)
    return {"safe_batch": batch.model_dump(), "status": "awaiting_safe_signatures"}
