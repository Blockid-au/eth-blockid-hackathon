"""Document Reader (evaluation v5, docs/PLAN-EVALUATION-V5.md §2 / §3.2): uploaded pitch deck text -> DeckFacts.

Runs once per uploaded deck (on /rescore), one `extract_json` call (≤ 60k chars; the gateway moves a > 30k-token
prompt to `long_context`). Every claim must quote the deck verbatim and state its number; kept claims are level L1
("claimed in deck") with source_url "doc:<id>"; a typed figure matching the deck within 5 % becomes L2
(tools/consistency). No web, no tools.
"""
from __future__ import annotations

from ..deps import Deps
from ..schemas import DeckFacts, StartupProfile
from .analysts import Verifier

AGENT = "deck_reader"
MAX_CHARS = 60_000
ALLOWED = {"arr", "revenue", "mrr", "revenue_growth_yoy", "paying_customers", "customers", "active_users", "mau",
           "dau", "waitlist", "pilots_paid", "lois", "contracted_backlog", "pipeline", "gross_margin", "gmv",
           "take_rate", "nrr", "grr", "logo_churn_monthly", "m3_retention", "m12_retention", "nps", "tam", "sam",
           "cagr", "target_customer_count", "annual_price", "burn_monthly", "cash", "raised_to_date",
           "top_customer_share", "integrations"}
SYSTEM = """You read a startup's pitch deck (text of the slides) and list the figures it states about the company and
its market. For each: metric (one of: """ + ", ".join(sorted(ALLOWED)) + """), value as stated (plain number in
`unit`), unit (AUD, USD, %, count, ...), period as written, source_url = the document id given (e.g. "doc:12"),
quote = the exact slide text (<= 300 chars) containing the number, subject = company (market for tam/sam/cagr).
round_type: the round being raised or last raised, as written, with round_quote. Never compute or estimate."""


def read_deck(doc_id: str, text: str, profile: StartupProfile | dict, deps: Deps, site_url: str = "") -> dict:
    """-> {"claims": [VerifiedClaim dicts], "dropped": [...], "round_type": str, "chars": int}"""
    prof = StartupProfile.model_validate(profile) if isinstance(profile, dict) else profile
    body = (text or "")[:MAX_CHARS]
    try:
        facts = deps.ask(AGENT, deps.settings.svi_tier, SYSTEM,
                         f"Startup: {prof.company_name}\nDocument id: doc:{doc_id}\n\n<data>\n{body}\n</data>",
                         DeckFacts)
    except Exception as e:  # noqa: BLE001
        deps.audit.record(AGENT, "deck_error", doc=doc_id, error=str(e)[:300])
        return {"claims": [], "dropped": [f"deck: extraction failed ({type(e).__name__})"], "round_type": "",
                "chars": len(body)}
    for c in facts.claims:
        c.source_url = f"doc:{doc_id}"  # the deck is the only source this reader may cite
    v = Verifier([], prof, site_url, docs={doc_id: body})
    claims, dropped = v.claims(facts.claims, "deck", ALLOWED, limit=20)
    rt = facts.round_type if facts.round_quote and facts.round_quote.lower() in body.lower() else ""
    deps.audit.record(AGENT, "deck_read", doc=doc_id, kept=len(claims), dropped=len(dropped))
    return {"claims": [c.model_dump() for c in claims], "dropped": dropped, "round_type": rt, "chars": len(body)}
