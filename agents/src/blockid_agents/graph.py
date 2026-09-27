"""Supervisor: LangGraph workflows with hard human-approval gates.

The ORDER of steps is code, not a prompt. Gates use `interrupt()`: the run pauses, its state is
checkpointed (Postgres in production), and resumes only when an authorised reviewer answers via
the API. Nothing reaches the chain without (1) valuation sign-off, (2) contract sign-off plus a
human-run deployment, (3) Safe multisig signatures.

    onboarding:  intake -> research -> valuation -> [GATE valuation] -> contract_builder
                 -> [GATE contract + deployment addresses + cap table] -> registry -> END
    dividend:    plan -> [GATE board-approved amounts] -> build_batch -> END
    site_valuation (Issuance Studio):
                 read_site -> profile -> competitors -> market -> svi -> narrative -> [GATE valuation] -> END
    (valuation v3: the market step also gathers verified market anchors / multiples, the svi step triangulates)
"""
from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .agents import competitors, contract_builder, dividend, intake, registry, research, site_intake, valuation
from .deps import Deps
from .llm import track_providers, untrack_providers
from .tools.search import summary as search_summary


class OnboardingState(TypedDict, total=False):
    job_id: str
    dataroom: dict[str, str]
    issuance_inputs: dict[str, Any]
    profile: dict
    market: dict | None
    valuation_evidence: dict | None
    valuation_inputs: dict | None  # valuation v5 (agents/valuation_agent.py)
    evidence_count: int
    searches: list[dict]
    qualitative: dict
    svi: dict
    warnings: list[str]
    token_params: dict
    contract_check: dict
    deployment: dict
    cap_table: list[dict]
    kyc: dict
    safe_batch: dict
    status: str
    reviewers: dict[str, str]


class DividendState(TypedDict, total=False):
    job_id: str
    dividend: dict
    dividend_plan: dict
    safe_batch: dict
    status: str
    reviewers: dict[str, str]


class SiteValuationState(TypedDict, total=False):
    job_id: str
    url: str
    self_reported: dict | None  # founder-provided figures (SelfReportedMetrics), labelled in the report
    site_url: str
    site_pages: int
    profile: dict
    competitors: list[dict]
    market: dict | None
    valuation_evidence: dict | None  # v3: verified anchors / listing / comps / sector multiples (market_evidence)
    valuation_inputs: dict | None  # v5: industry, startup ratings, deals, projection, admin assumptions
    evidence_count: int
    searches: list[dict]  # web searches run for this valuation (budget: SEARCH_MAX_QUERIES)
    llm_providers_used: list[str]  # which LLM backends answered, first-use order
    qualitative: dict
    svi: dict
    status: str
    reviewers: dict[str, str]
    warnings: list[str]
    analysis: dict | None  # evaluation v5 (VALUATION_V5): partial Analysis from the `analysts` step


def _reviewer(decision: dict) -> str:
    r = (decision or {}).get("reviewer", "")
    if not r:
        raise ValueError("approval must name the reviewer")
    return r


def build_onboarding(deps: Deps, checkpointer):
    def gate_valuation(state: OnboardingState) -> dict:
        decision = interrupt(
            {
                "gate": "valuation",
                "question": "Confirm or override the AI-suggested SVI dimension scores.",
                "svi": state["svi"],
                "evidence_count": state.get("evidence_count", 0),
            }
        )
        who = _reviewer(decision)
        if not decision.get("approved"):
            deps.audit.record("human", "valuation_rejected", reviewer=who, reason=decision.get("reason", ""))
            return {"status": "rejected_at_valuation", "reviewers": {"valuation": who}}
        out = valuation.apply_overrides(state, decision.get("overrides", {}), who, deps)
        return {**out, "status": "valuation_approved", "reviewers": {"valuation": who}}

    def gate_contract(state: OnboardingState) -> dict:
        decision = interrupt(
            {
                "gate": "contract",
                "question": "Approve parameters, deploy with scripts/deploy-company.sh, then return the addresses "
                "together with the board-approved cap table.",
                "token_params": state["token_params"],
                "contract_check": state["contract_check"],
            }
        )
        who = _reviewer(decision)
        reviewers = {**state.get("reviewers", {}), "contract": who}
        if state.get("status") == "contract_blocked":
            deps.audit.record("human", "contract_blocked_cannot_approve", reviewer=who)
            return {"status": "rejected_contract_checks_failed", "reviewers": reviewers}
        if not decision.get("approved") or not decision.get("deployment"):
            deps.audit.record("human", "contract_rejected", reviewer=who)
            return {"status": "rejected_at_contract", "reviewers": reviewers}
        deps.audit.record("human", "contract_approved", reviewer=who, deployment=decision["deployment"])
        return {
            "deployment": decision["deployment"],
            "cap_table": decision["cap_table"],
            "kyc": decision.get("kyc", {}),
            "status": "contract_approved",
            "reviewers": reviewers,
        }

    g = StateGraph(OnboardingState)
    g.add_node("intake", lambda s: intake.run(s, deps))
    g.add_node("research", lambda s: research.run(s, deps))
    g.add_node("valuation", lambda s: valuation.run(s, deps))
    g.add_node("gate_valuation", gate_valuation)
    g.add_node("contract_builder", lambda s: contract_builder.run(s, deps))
    g.add_node("gate_contract", gate_contract)
    g.add_node("registry", lambda s: registry.run(s, deps))

    g.add_edge(START, "intake")
    g.add_edge("intake", "research")
    g.add_edge("research", "valuation")
    g.add_edge("valuation", "gate_valuation")
    g.add_conditional_edges(
        "gate_valuation", lambda s: "contract_builder" if s["status"] == "valuation_approved" else END
    )
    g.add_edge("contract_builder", "gate_contract")
    g.add_conditional_edges("gate_contract", lambda s: "registry" if s["status"] == "contract_approved" else END)
    g.add_edge("registry", END)
    return g.compile(checkpointer=checkpointer)


def build_dividend(deps: Deps, checkpointer):
    def gate(state: DividendState) -> dict:
        p = state["dividend_plan"]
        decision = interrupt(
            {
                "gate": "dividend",
                "question": "Confirm this matches the board resolution (amount, record block, pay token).",
                "summary": {k: p[k] for k in ("record_block", "pay_token", "total_amount", "holders", "merkle_root",
                                              "remainder_to_issuer")},
            }
        )
        who = _reviewer(decision)
        if not decision.get("approved"):
            deps.audit.record("human", "dividend_rejected", reviewer=who)
            return {"status": "rejected_at_dividend", "reviewers": {"dividend": who}}
        deps.audit.record("human", "dividend_approved", reviewer=who, root=p["merkle_root"])
        return {"status": "dividend_approved", "reviewers": {"dividend": who}}

    g = StateGraph(DividendState)
    g.add_node("plan", lambda s: dividend.plan(s, deps))
    g.add_node("gate", gate)
    g.add_node("build_batch", lambda s: dividend.build_batch(s, deps))
    g.add_edge(START, "plan")
    g.add_edge("plan", "gate")
    g.add_conditional_edges("gate", lambda s: "build_batch" if s["status"] == "dividend_approved" else END)
    g.add_edge("build_batch", END)
    return g.compile(checkpointer=checkpointer)


# ------------------------------------------------------------------ Issuance Studio: website -> SVI
class NullProgress:
    def step(self, vid: str, key: str, status: str, detail: str = "") -> None: ...
    def result(self, vid: str, **patch) -> None: ...
    def status(self, vid: str, status: str, error: str | None = None) -> None: ...


def site_evidence(deps: Deps, vid: str) -> list[dict]:
    """All evidence gathered for a valuation (site pages first), de-duplicated by URL."""
    out, seen = [], set()
    for subject in (site_intake.site_subject(vid), vid, competitors.comp_subject(vid)):
        for ev, _text in deps.evidence.for_subject(subject, limit=500):
            if ev.url not in seen:
                seen.add(ev.url)
                kind = ev.kind or ("site" if ev.query == "site" else "web")
                out.append({"url": ev.url, "title": ev.title, "snippet": ev.snippet[:300],
                            "retrieved_at": ev.retrieved_at, "kind": kind})
    return out


SELF_REPORTED_WARNING = "Includes self-reported figures (not independently verified)"


def site_result(deps: Deps, state: dict) -> dict:
    """The part of the graph state that the Studio API serves (see GET /v1/studio/valuations/{id})."""
    ev = site_evidence(deps, state["job_id"])
    warnings = list(state.get("warnings") or [])
    if state.get("self_reported"):
        warnings.insert(0, SELF_REPORTED_WARNING)
    return {
        "site_url": state.get("site_url"),
        "counters": {"pages": state.get("site_pages", 0), "competitors": len(state.get("competitors") or []),
                     "sources": sum(1 for e in ev if e["kind"] in ("web", "search_snippet")),
                     "searches": len(state.get("searches") or [])},
        "profile": state.get("profile"),
        "competitors": state.get("competitors") or [],
        "market": state.get("market"),
        # the company's own revenue / funding / valuation, only when a source states it verbatim (research agent)
        "company_financials": (state.get("market") or {}).get("company_financials"),
        "svi": state.get("svi"),
        # v3: how the value was reached (methods, weights, sources, confidence) — also inside svi.triangulation
        "valuation_methods": (state.get("svi") or {}).get("triangulation"),
        "valuation_evidence": state.get("valuation_evidence"),
        "qualitative": state.get("qualitative"),
        "evidence": ev,
        "self_reported": state.get("self_reported") or None,
        "warnings": list(dict.fromkeys(warnings)),
        "searches": state.get("searches") or [],
        "llm_providers_used": state.get("llm_providers_used") or [],
        # valuation v5 only (absent otherwise): inputs the deterministic re-runs need (studio/finalise.py)
        **({"valuation_inputs": state["valuation_inputs"]} if state.get("valuation_inputs") else {}),
    }


def build_site_valuation(deps: Deps, checkpointer, progress=None, v5: bool | None = None):
    """v5 (VALUATION_V5=1, default off): adds the parallel `analysts` step between market and svi and scores the
    nine v5 dimensions; with the flag off the graph, results and hashes are exactly v4."""
    from .agents import analysts
    from .tools.stage import v5_enabled as evaluation_v5_enabled

    prog = progress or NullProgress()
    v5 = evaluation_v5_enabled() if v5 is None else v5

    def step(key: str, fn, detail):
        def run(state: SiteValuationState) -> dict:
            vid = state["job_id"]
            prog.step(vid, key, "running")
            used, token = track_providers()
            try:
                out = fn(state)
            except Exception as e:
                prog.step(vid, key, "failed", str(e)[:300])
                raise
            finally:
                untrack_providers(token)
            if used:
                prev = list(state.get("llm_providers_used") or [])
                out = {**out, "llm_providers_used": list(dict.fromkeys(prev + used))}
            merged = {**state, **out}
            prog.step(vid, key, "done", detail(merged))
            prog.result(vid, **site_result(deps, merged))
            return out
        return run

    def gate(state: SiteValuationState) -> dict:
        decision = interrupt({
            "gate": "valuation",
            "question": "Approve the SVI valuation, optionally overriding AI-suggested dimension scores.",
            "svi": state["svi"],
        })
        who = _reviewer(decision)
        if not decision.get("approved"):
            deps.audit.record("human", "valuation_rejected", reviewer=who, reason=decision.get("reason", ""))
            return {"status": "rejected", "reviewers": {"valuation": who}}
        out = valuation.apply_overrides(state, decision.get("overrides") or {}, who, deps)
        if v5 and (state.get("svi") or {}).get("analysis"):  # keep the v5 dimensions after the admin's overrides
            try:
                out["svi"] = analysts.rescore_v5({**state, **out}, svi_dict=out["svi"],
                                                 qualitative=out["qualitative"])
            except Exception as e:  # noqa: BLE001
                deps.audit.record("valuation", "v5_score_failed", error=str(e)[:300])
        return {**out, "status": "approved", "reviewers": {"valuation": who}}

    def svi_step(state):
        """v4 scoring, then (v5) the nine evaluation dimensions from the analysts' evidence (tools/evaluation)."""
        out = valuation.score(state, deps)
        if v5 and state.get("analysis"):
            try:
                out["svi"] = analysts.rescore_v5({**state, **out}, svi_dict=out["svi"],
                                                 qualitative=out["qualitative"])
            except Exception as e:  # noqa: BLE001 - v5 must never fail a valuation: the v4 result stands
                deps.audit.record("valuation", "v5_score_failed", error=str(e)[:300])
        return out

    def market(state):
        out = research.run(state, deps)
        warn = list(state.get("warnings") or [])
        if not out.get("market"):
            warn.append("no market evidence: valuation falls back to the stage benchmark range")
        elif out.pop("market_fallback", False):
            warn.append("Search unavailable: market analysis cites only the company's and competitors' own websites")
        out.pop("market_fallback", None)
        if warn:
            out["warnings"] = warn
        return out

    def with_warning(text: str):
        return lambda m: text + (f" — {m['warnings'][0]}" if m.get("warnings") else "")

    def searched(text: str):
        return lambda m: f"{text} · {search_summary(m.get('searches'), deps.settings.search_max_queries)}"

    def financials(m) -> str:
        cf = (m.get("market") or {}).get("company_financials") or {}
        if cf.get("revenue_ttm_aud"):
            used = "" if cf.get("usable_for_valuation") else ", not used"
            out = f" · company {cf.get('revenue_type') or 'revenue'} A${cf['revenue_ttm_aud']:,.0f} (cited{used})"
        else:
            out = " · no cited company revenue"
        ve = m.get("valuation_evidence") or {}
        if ve:
            out += (f" · {len(ve.get('anchors') or [])} verified valuation(s), {len(ve.get('comps') or [])} comparable"
                    f" multiple(s)" + (f", listed {ve['listing']['exchange']}:{ve['listing']['ticker']}"
                                       if ve.get("listing") else ""))
        return out

    def svi_detail(m) -> str:
        s = m["svi"]
        out = f"SVI {s['index']} ({s['band']})"
        tri = s.get("triangulation")
        if tri:
            out += f" · value A${tri['value_aud']:,.0f} (confidence {tri['confidence']})"
        src = m["profile"].get("metrics_sources", {}).get("revenue_ttm_aud")
        return out + (f" · revenue: {src}" if src else "")

    g = StateGraph(SiteValuationState)
    g.add_node("read_site", step("read_site", lambda s: site_intake.read_site(s, deps),
                                 lambda m: f"{m.get('site_pages', 0)} pages read"))
    g.add_node("profile", step("profile", lambda s: site_intake.profile(s, deps),
                               lambda m: f"{m['profile']['company_name']} · {m['profile']['sector']}"))
    g.add_node("competitors", step("competitors", lambda s: competitors.discover(s, deps),
                                   lambda m: with_warning(searched(f"{len(m.get('competitors') or [])} competitors")(m))(m)))
    g.add_node("market", step("market", market,
                              lambda m: with_warning(searched(f"{m.get('evidence_count', 0)} sources analysed"
                                                              + financials(m))(m))(m)))
    g.add_node("svi", step("svi", svi_step, svi_detail))
    g.add_node("narrative", step("narrative", lambda s: valuation.narrate(s, deps), lambda m: "narrative drafted"))
    g.add_node("gate_valuation", gate)
    g.add_edge(START, "read_site")
    chain = ["read_site", "profile", "competitors", "market", "svi", "narrative", "gate_valuation"]
    if v5:  # evaluation v5 (docs/PLAN-EVALUATION-V5.md §2): four analysts in parallel between market and svi
        g.add_node("analysts", step("analysts", lambda s: analysts.run(s, deps),
                                    lambda m: analysts.detail(m.get("analysis"))))
        chain.insert(chain.index("svi"), "analysts")
    from .tools.valuation_params import v5_enabled

    if v5_enabled():  # valuation v5 (docs/PLAN-VALUATION-V5.md §5): standard methods after the SVI score
        from .agents import valuation_agent

        def methods_detail(m) -> str:
            tri = (m.get("svi") or {}).get("triangulation") or {}
            used = [x["method"] for x in tri.get("methods") or [] if x.get("weight")]
            return (f"value A${tri.get('value_aud', 0):,.0f} (confidence {tri.get('confidence')}) · "
                    f"{tri.get('valuation_class', '')} · methods: {', '.join(used)}")

        g.add_node("valuation_methods", step("valuation_methods", lambda s: valuation_agent.run(s, deps),
                                             methods_detail))
        chain.insert(chain.index("narrative"), "valuation_methods")
    for a, b in zip(chain, chain[1:]):
        g.add_edge(a, b)
    g.add_edge("gate_valuation", END)
    return g.compile(checkpointer=checkpointer)
