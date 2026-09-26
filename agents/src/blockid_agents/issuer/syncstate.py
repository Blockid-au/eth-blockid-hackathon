"""Per-chain sync state of a company (pure functions, shared by the issuer and the API).

`studio.companies.sync` (jsonb) is written only by the issuer:
    {"blockid": "done", "hoodi": "running", "hsk": "pending",
     "errors": {"hsk": "..."}, "step": {"chain": "hoodi", "action": "mirror_balances", "n": 1, "of": 3, "at": iso},
     "started_at": iso, "updated_at": iso, "finished_at": iso | null}
States: pending | running | done | failed | skipped (external chain not configured).
Rows created before the column existed have sync = {} / NULL: `view()` derives the state from the other columns.

Company status: issuing -> issued -> anchoring -> anchored (every external chain done)
                                             +-> partially_anchored (some done, some failed) / issued (none done)
"""
from __future__ import annotations

from typing import Any

LOCAL = "blockid"
EXTERNAL = ("hoodi", "hsk")          # sync order after BlockID Chain
CHAINS = (LOCAL, *EXTERNAL)
STATES = ("pending", "running", "done", "failed", "skipped")

# company column per (chain, field)
COLUMNS: dict[str, dict[str, str]] = {
    "hoodi": {"registry": "hoodi_registry", "token": "hoodi_token", "anchor_tx": "hoodi_anchor_tx",
              "merkle_root": "merkle_root", "block": "anchored_block", "anchored_at": "anchored_at"},
    "hsk": {"registry": "hsk_registry", "token": "hsk_token", "anchor_tx": "hsk_anchor_tx",
            "merkle_root": "hsk_merkle_root", "block": "hsk_block", "anchored_at": "hsk_anchored_at"},
}
LABELS = {"blockid": "BlockID Chain", "hoodi": "Ethereum Hoodi", "hsk": "HashKey Chain testnet"}


def _derived(c: dict, chain: str) -> str:
    status = c.get("status") or ""
    if chain == LOCAL:
        if c.get("local_block") or status in ("issued", "pending_anchor", "anchoring", "anchored",
                                              "partially_anchored"):
            return "done"
        if status == "issuing":
            return "running"
        if status == "failed" and not c.get("local_block"):
            return "failed"
        return "pending"
    col = COLUMNS[chain]
    if c.get(col["anchor_tx"]):
        return "done"
    if status == "anchoring":
        return "running"
    return "pending"


def view(c: dict) -> dict[str, Any]:
    """Complete sync dict for a company row (explicit values win, missing ones are derived)."""
    raw = c.get("sync") or {}
    out: dict[str, Any] = {}
    for ch in CHAINS:
        s = raw.get(ch)
        out[ch] = s if s in STATES else _derived(c, ch)
    out["errors"] = {k: v for k, v in (raw.get("errors") or {}).items() if v}
    for k in ("step", "started_at", "updated_at", "finished_at"):
        out[k] = raw.get(k)
    return out


def overall(sync: dict) -> str:
    """Company status after an external-chain sync pass."""
    states = [sync.get(ch) for ch in EXTERNAL]
    if all(s == "done" for s in states):
        return "anchored"
    if any(s == "done" for s in states):
        return "partially_anchored"
    return "issued"


def missing(c: dict) -> list[str]:
    """External chains that still need a (re-)sync."""
    v = view(c)
    return [ch for ch in EXTERNAL if v[ch] != "done"]
