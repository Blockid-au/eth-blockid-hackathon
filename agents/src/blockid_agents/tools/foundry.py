"""Run the contract test-suite and static analysis. Used by the Contract Builder agent.

The agent only changes a params JSON; this proves the audited templates still pass with those
parameters (deploy dry-run) and that Slither reports no High/Medium issues.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Callable

from ..schemas import ContractCheck

Runner = Callable[[list[str], str, dict], subprocess.CompletedProcess]


def _default_runner(cmd: list[str], cwd: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, env={**os.environ, **env}, capture_output=True, text=True, timeout=900)


def check_contracts(contracts_dir: str, params_file: str, runner: Runner = _default_runner) -> ContractCheck:
    cwd = str(Path(contracts_dir))
    env = {"PARAMS_FILE": params_file}

    test = runner(["forge", "test", "--offline"], cwd, env)
    dry = runner(["forge", "script", "script/DeployCompany.s.sol", "--offline"], cwd, env)
    forge_ok = test.returncode == 0 and dry.returncode == 0
    tail = (test.stdout or "").strip().splitlines()[-1:] + (dry.stdout or dry.stderr or "").strip().splitlines()[-3:]

    sl = runner(
        ["slither", ".", "--filter-paths", "lib|test|script", "--exclude-dependencies", "--json", "-"], cwd, env
    )
    high = med = 0
    try:
        detectors = json.loads(sl.stdout or "{}").get("results", {}).get("detectors", [])
        high = sum(1 for d in detectors if d.get("impact") == "High")
        med = sum(1 for d in detectors if d.get("impact") == "Medium")
        sl_summary = f"{len(detectors)} findings (High {high}, Medium {med})"
    except json.JSONDecodeError:
        high, sl_summary = 1, "slither output unreadable — treated as blocking"

    return ContractCheck(
        forge_passed=forge_ok,
        forge_summary=" | ".join(tail),
        slither_high=high,
        slither_medium=med,
        slither_summary=sl_summary,
    )
