"""Tamper-evident audit log (hash chain, JSON Lines).

Each entry stores the hash of the previous entry; editing or deleting any line breaks the chain.
The daily head hash can be anchored on-chain (see scripts/anchor-audit-head.sh) so the log
itself becomes verifiable evidence for ASIC / auditors.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

GENESIS = "0" * 64


def _digest(entry: dict) -> str:
    body = json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(body.encode()).hexdigest()


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _head(self) -> str:
        if not self.path.exists():
            return GENESIS
        last = None
        with self.path.open("rb") as f:
            for line in f:
                if line.strip():
                    last = line
        return json.loads(last)["hash"] if last else GENESIS

    def record(self, actor: str, action: str, **data) -> str:
        with self._lock:
            entry = {"ts": time.time(), "actor": actor, "action": action, "data": data, "prev": self._head()}
            entry["hash"] = _digest(entry)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            return entry["hash"]

    def verify(self) -> bool:
        prev = GENESIS
        if not self.path.exists():
            return True
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                entry = json.loads(line)
                h = entry.pop("hash")
                if entry["prev"] != prev or _digest(entry) != h:
                    return False
                prev = h
        return True
