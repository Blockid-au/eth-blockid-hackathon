"""Turn raw issuer errors into something a person can act on.

`classify(text)` returns a stable `code`, the `action` that fixes it and the page section (`target`) the UI should
scroll to and highlight. The UI owns the wording (EN/VI) per code; `detail` carries numbers for the message.
"""
from __future__ import annotations

import re
from typing import Any

_CAP = re.compile(r"sum\(balances\)=(\d+) != totalSupply=(\d+)")

# (code, pattern, action, target). First match wins.
RULES: list[tuple[str, re.Pattern[str], str, str]] = [
    ("cap_table_mismatch", re.compile(r"cap table incomplete", re.I), "refresh", "cap-table"),
    ("transfer_scan_failed", re.compile(r"could not scan share transfers", re.I), "refresh", "cap-table"),
    ("insufficient_gas", re.compile(r"InsufficientFunds|needs about .* gas|top up the issuer", re.I),
     "top_up", "issuer-wallets"),
    ("chain_not_configured", re.compile(r"is not configured", re.I), "configure", "sync"),
    ("mint_failed", re.compile(r"^mint \d+", re.I), "retry_item", "approvals"),
    ("dividend_failed", re.compile(r"^dividend \d+", re.I), "retry_item", "approvals"),
    ("not_issued", re.compile(r"not issued", re.I), "approve_issue", "tracker"),
    ("network", re.compile(r"timed? ?out|timeout|connection|502|503|504|nonce too low|replacement", re.I),
     "resync", "sync"),
]


def classify(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    for code, pat, action, target in RULES:
        if pat.search(text):
            info: dict[str, Any] = {"code": code, "action": action, "target": target}
            if m := _CAP.search(text):
                held, supply = int(m.group(1)), int(m.group(2))
                info["detail"] = {"on_chain_in_table": held, "total_supply": supply, "missing": supply - held}
            return info
    return {"code": "unknown", "action": "refresh", "target": "tracker"}


def company_error_info(c: dict) -> dict[str, Any] | None:
    """Error summary for a company row: overall error plus per-chain sync errors."""
    info = classify(c.get("error"))
    per_chain = {}
    for chain, err in ((c.get("sync") or {}).get("errors") or {}).items():
        if err:
            per_chain[chain] = classify(err)
    if not info and not per_chain:
        return None
    return {**(info or next(iter(per_chain.values()))), "chains": per_chain}
