"""Agent 4 — Contract Builder.

Never writes Solidity. It proposes a TokenParams JSON for the audited templates in /contracts,
runs forge tests + a deploy dry-run + Slither with those params, and asks the cloud model to
review the PARAMETERS for business/legal red flags. Deployment is done by a human operator.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from ..deps import Deps
from ..schemas import ContractCheck, ContractReview, StartupProfile, TokenParams

AGENT = "contract_builder"

SYSTEM_REVIEW = """You review parameters for a permissioned digital share register (ERC-3643-style) on an
enterprise EVM chain. Flag anything that is inconsistent or risky: symbol/name mismatch, missing company number,
lock-up in the past, shareholder cap inconsistent with an Australian proprietary company (max 50 non-employee
shareholders), zero or placeholder addresses for the issuer multisig or agents, missing legal document hash.
approve=false if any blocking issue exists."""


def _symbol(company: str, share_class: str) -> str:
    base = re.sub(r"[^A-Z0-9]", "", re.sub(r"\b(PTY|LTD|LIMITED|INC|JSC|CO)\b", "", company.upper()))[:8] or "CO"
    return f"{base}-{share_class}"[:16]


def propose(profile: StartupProfile, inputs: dict) -> TokenParams:
    share_class = inputs.get("share_class", "ORD")
    proprietary = "PTY" in profile.company_name.upper()
    return TokenParams(
        name=f"{profile.company_name} {share_class}",
        symbol=inputs.get("symbol") or _symbol(profile.company_name, share_class),
        companyName=profile.company_name,
        companyNumber=inputs.get("company_number") or profile.company_number or "PENDING",
        shareClass=share_class,
        issuerSafe=inputs["issuer_safe"],
        transferAgent=inputs["transfer_agent"],
        kycAgent=inputs["kyc_agent"],
        identityRegistry=inputs.get("identity_registry", "0x" + "0" * 40),
        lockupUntil=int(inputs.get("lockup_until", time.time() + 365 * 86400)),
        maxShareholders=int(inputs.get("max_shareholders", 50 if proprietary else 0)),
        legalDocHash=inputs["legal_doc_hash"],
    )


def run(state: dict, deps: Deps) -> dict:
    profile = StartupProfile.model_validate(state["profile"])
    params = propose(profile, state["issuance_inputs"])

    slug = state["job_id"]
    params_dir = Path(deps.settings.contracts_dir) / "deployments" / "params"
    params_dir.mkdir(parents=True, exist_ok=True)
    params_path = params_dir / f"{slug}.json"
    params_path.write_text(json.dumps(params.model_dump(), indent=2))
    deps.tool(AGENT, "render_params", path=str(params_path))

    deps.tool(AGENT, "forge_test", params=str(params_path))
    deps.tool(AGENT, "slither")
    from ..tools.foundry import check_contracts

    check: ContractCheck = check_contracts(
        deps.settings.contracts_dir, f"deployments/params/{slug}.json", runner=deps.forge_runner
    )

    review = deps.ask(AGENT, "cloud", SYSTEM_REVIEW, f"<data>\n{params.model_dump_json()}\n</data>", ContractReview)
    check.ai_review = review.notes
    check.ai_review_blocking_issues = review.blocking_issues

    blocked = (not check.forge_passed) or check.slither_high > 0 or check.slither_medium > 0 or not review.approve
    return {
        "token_params": params.model_dump(),
        "contract_check": check.model_dump(),
        "status": "contract_blocked" if blocked else "contract_ready",
    }
