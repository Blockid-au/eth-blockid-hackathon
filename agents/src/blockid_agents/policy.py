"""Least-privilege policy for every agent.

This table is the single source of truth for what each agent may do. It is enforced in code
(`guard`) — not in prompts — so a prompt-injected document cannot widen an agent's powers.
"""
from __future__ import annotations

from dataclasses import dataclass

from .llm import Tier


class PolicyViolation(PermissionError):
    pass


@dataclass(frozen=True)
class AgentPolicy:
    tiers: frozenset[str]  # which model tiers the agent may call
    tools: frozenset[str]  # which tools it may invoke
    handles_pii: bool  # True -> only the local tier is allowed
    description: str


POLICIES: dict[str, AgentPolicy] = {
    "intake": AgentPolicy(
        tiers=frozenset({"local"}),
        tools=frozenset({"read_dataroom", "store_profile"}),
        handles_pii=True,
        description="Reads founder/KYC/data-room files, extracts a structured StartupProfile.",
    ),
    "research": AgentPolicy(
        tiers=frozenset({"local", "cloud"}),  # public web data only — no PII in, so cloud is allowed
        tools=frozenset({"web_search", "fetch_url", "store_evidence"}),
        handles_pii=False,
        description="Pulls fresh market data via web search (Brave / Claude bridge), analyses it locally, stores cited evidence.",
    ),
    "valuation": AgentPolicy(
        tiers=frozenset({"local", "cloud"}),
        tools=frozenset({"svi_score", "hash_report"}),
        handles_pii=False,
        description="Scores the 7 SVI dimensions (deterministic maths) and drafts the narrative.",
    ),
    "contract_builder": AgentPolicy(
        tiers=frozenset({"cloud", "cloud_max"}),
        tools=frozenset({"render_params", "forge_test", "slither"}),
        handles_pii=False,
        description="Fills audited template parameters, runs tests + static analysis. Cannot deploy.",
    ),
    "registry": AgentPolicy(
        tiers=frozenset({"local"}),
        tools=frozenset({"build_unsigned_tx"}),
        handles_pii=True,
        description="Turns the approved cap table into UNSIGNED Safe transactions. Holds no keys.",
    ),
    "dividend": AgentPolicy(
        tiers=frozenset({"local"}),
        tools=frozenset({"read_balances", "build_merkle", "build_unsigned_tx"}),
        handles_pii=False,
        description="Snapshots holders, computes pro-rata amounts + Merkle root, proposes a Safe batch.",
    ),
    "site_intake": AgentPolicy(
        tiers=frozenset({"cloud"}),
        tools=frozenset({"fetch_url", "store_profile"}),
        handles_pii=False,  # public website only; emails/phones are stripped before the model sees the text
        description="Crawls the startup's public website (same domain, robots.txt) and extracts a StartupProfile.",
    ),
    "competitor_discovery": AgentPolicy(
        tiers=frozenset({"local", "cloud"}),
        tools=frozenset({"web_search", "fetch_url", "store_evidence"}),
        handles_pii=False,
        description="Finds up to 9 competitors via web search and extracts funding only when a fetched source states it.",
    ),
    "people_analyst": AgentPolicy(
        tiers=frozenset({"local", "cloud"}),
        tools=frozenset({"web_search", "fetch_url", "store_evidence"}),  # read-only research; no keys, no chain
        handles_pii=False,  # public professional info of people who consented; emails/phones redacted first
        description="Founding-team review: reads provided public profile URLs + budgeted web search, extracts "
                    "verbatim-quoted professional facts per person; code computes person and team scores.",
    ),
}

# Tools that do not exist for ANY agent. Listed explicitly so reviewers see the boundary.
FORBIDDEN_TOOLS = frozenset({"sign_tx", "send_tx", "read_private_key", "deploy_contract", "shell"})


def guard(agent: str, *, tool: str | None = None, tier: Tier | None = None) -> None:
    pol = POLICIES.get(agent)
    if pol is None:
        raise PolicyViolation(f"unknown agent {agent!r}")
    if tool is not None:
        if tool in FORBIDDEN_TOOLS or tool not in pol.tools:
            raise PolicyViolation(f"agent {agent!r} may not use tool {tool!r}")
    if tier is not None:
        if tier not in pol.tiers:
            raise PolicyViolation(f"agent {agent!r} may not call model tier {tier!r}")
        if pol.handles_pii and tier != "local":
            raise PolicyViolation(f"agent {agent!r} handles PII and must stay on the local model")
