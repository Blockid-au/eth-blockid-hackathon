"""Valuation REPORT hash anchored on-chain (BlockIDShareToken.anchorValuation on BlockID Chain + the Hoodi/HSK mirrors).

report_hash = keccak256(utf8(canonical_json(canonical_report(v)))) where `v` is the object returned by
GET /v1/studio/valuations/{id}, restricted to REPORT_KEYS (every key always present, null when absent), and
canonical JSON = keys sorted recursively, separators (",", ":"), ensure_ascii=False.
The public /verify page recomputes exactly this.
"""
from __future__ import annotations

import json
from typing import Any

REPORT_KEYS = ("url", "profile", "competitors", "market", "svi", "self_reported")


def report_view_from_row(row: dict) -> dict:
    """studio.valuations row -> the REPORT_KEYS subset of the API valuation view (same derivation as routes.py)."""
    res = row.get("result") or {}
    return {
        "url": row.get("url"),
        "profile": res.get("profile"),
        "competitors": res.get("competitors") or [],
        "market": res.get("market"),
        "svi": res.get("svi"),
        "self_reported": row.get("self_reported") or res.get("self_reported") or None,
    }


def canonical_report(val: dict) -> dict:
    return {k: val.get(k) for k in REPORT_KEYS}


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def report_hash(val: dict) -> str:
    """'0x' + keccak256 hex of the canonical report JSON (val = API valuation view or anything with REPORT_KEYS)."""
    from eth_utils import keccak

    return "0x" + keccak(canonical_json(canonical_report(val)).encode("utf-8")).hex()


def report_hash_from_row(row: dict) -> str:
    return report_hash(report_view_from_row(row))
