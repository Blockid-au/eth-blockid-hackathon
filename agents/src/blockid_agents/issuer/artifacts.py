"""Load compiled Foundry artifacts: CONTRACTS_OUT/<File>.sol/<Contract>.json -> (abi, bytecode)."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path


def contracts_out() -> Path:
    return Path(os.environ.get("CONTRACTS_OUT") or Path(__file__).resolve().parents[4] / "contracts" / "out")


@lru_cache(maxsize=32)
def load(name: str, file: str | None = None, out_dir: str | None = None) -> tuple[list, str]:
    base = Path(out_dir) if out_dir else contracts_out()
    p = base / f"{file or name}.sol" / f"{name}.json"
    if not p.is_file():
        raise FileNotFoundError(f"artifact not found: {p} (run `forge build` in contracts/)")
    j = json.loads(p.read_text())
    bytecode = j["bytecode"]["object"] if isinstance(j.get("bytecode"), dict) else j.get("bytecode", "")
    return j["abi"], bytecode


def abi(name: str) -> list:
    return load(name)[0]
