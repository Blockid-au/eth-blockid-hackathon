"""Agent 1 — Intake (local model only: the data room contains personal information)."""
from __future__ import annotations

from ..deps import Deps
from ..schemas import StartupProfile

AGENT = "intake"

SYSTEM = """You are the BlockID intake analyst. Extract a factual StartupProfile from the startup's data room.
Rules:
- Use ONLY facts stated in the documents. Unknown numbers stay 0; do not estimate.
- Monetary values in AUD. Percentages as numbers (35 means 35%).
- List every expected item that is absent (financials, cap table, constitution, IP assignment, KYC) in missing_items.
- search_keywords: 3-6 neutral market terms (sector, product category, region). Never include people's names,
  emails or phone numbers."""


def run(state: dict, deps: Deps) -> dict:
    docs = state["dataroom"]  # {filename: text}
    deps.tool(AGENT, "read_dataroom", files=sorted(docs))
    body = "\n\n".join(f"### {name}\n{text[:30_000]}" for name, text in docs.items())
    profile = deps.ask(AGENT, "local", SYSTEM, f"<data>\n{body}\n</data>", StartupProfile)
    profile.documents_reviewed = sorted(docs)
    deps.tool(AGENT, "store_profile", company=profile.company_name, missing=len(profile.missing_items))
    return {"profile": profile.model_dump(), "status": "profiled"}
