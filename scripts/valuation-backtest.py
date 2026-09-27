#!/usr/bin/env python3
"""Valuation v3 backtest: run the site-valuation graph (worker code path) on known companies and compare the
blended value with the latest public valuation / market cap (docs/valuation-reference.md).

Offline (default) — no keys, no network: the graph runs end to end with the recorded research fixtures in
scripts/fixtures/valuation-backtest.json (search results, page excerpts, and the model's extraction answers).
Everything deterministic still runs for real: quote verification, FX, dating, weighting, blending.

    cd agents && .venv/bin/python ../scripts/valuation-backtest.py
    cd agents && .venv/bin/python ../scripts/valuation-backtest.py --ablation   # also: without market anchors

Live — the real search chain (Claude bridge /search, Brave) and LLM chain (SambaNova -> claude_bridge -> DeepInfra),
same env as the worker (never the production API, never ports 8080/5432/8545):

    sudo cat /opt/blockid/app.env > /tmp/w.env   # root-only; or export the same variables by hand
    cd agents && set -a && . /tmp/w.env && set +a && \\
      BLOCKID_DATA_DIR=$(mktemp -d) DATABASE_URL= .venv/bin/python ../scripts/valuation-backtest.py --live
    rm /tmp/w.env

Live mode needs LLM_BACKEND=hosted (+ SAMBANOVA_API_KEY / CLAUDE_SEARCH_URL + CLAUDE_SEARCH_TOKEN / DEEPINFRA_API_KEY)
and SEARCH_PROVIDERS; the bridge URL must be reachable from where you run it (the worker uses the docker host
address). Each company costs <= 8 searches and ~9 LLM calls.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agents" / "src"))

FIXTURES = ROOT / "scripts" / "fixtures" / "valuation-backtest.json"

# Latest public valuation / market cap (mirrors docs/valuation-reference.md). AUD at the app's dated FX table
# (config.FX_TO_AUD, USD 1.50 as of 2026-09-26) so reference and engine use the same conversion.
REFERENCE = [
    {"company": "Canva", "value": 34.9e9, "currency": "USD", "date": "2026-08-17", "basis": "investor mark (Blackbird/Airtree)",
     "url": "https://www.startupdaily.net/advice/business-strategy/canva-wipes-10-billion-from-its-valuation-putting-ipo-plans-in-doubt/"},
    {"company": "Airwallex", "value": 11e9, "currency": "USD", "date": "2026-06-25", "basis": "Series H post-money",
     "url": "https://www.airwallex.com/global/newsroom/airwallex-secures-320-million-in-series-h-funding-valuation-hits-11-billion"},
    {"company": "SafetyCulture", "value": 2.5e9, "currency": "AUD", "date": "2024-09-09", "basis": "funding round",
     "url": "https://www.forbes.com.au/news/investing/safetyculture-valued-at-2-5-billion-after-165-million-funding-round/"},
    {"company": "Go1", "value": 2e9, "currency": "USD", "date": "2022-06-07", "basis": "funding round",
     "url": "https://www.startupdaily.net/topic/funding/go1-doubles-its-valuation-to-2-8-billion-after-100-million-raise/"},
    {"company": "Airtasker", "value": 97.9e6, "currency": "AUD", "date": "2026-09-25", "basis": "ASX:ART market cap",
     "url": "https://stockanalysis.com/quote/asx/ART/market-cap/"},
    {"company": "Employment Hero", "value": 2.2e9, "currency": "AUD", "date": "2025-02-18",
     "basis": "secondary sale (Seek -> KKR), implied",
     "url": "https://www.startupdaily.net/topic/seek-offloads-a-95-million-slice-of-its-employment-hero-investment-to-us-private-equity-firm-kkr/"},
    {"company": "Culture Amp", "value": 2e9, "currency": "AUD", "date": "2021-07", "basis": "Series F (Blackbird marked -23.5% in 2025)",
     "url": "https://www.startupdaily.net/topic/business/just-days-after-blackbird-slashed-its-valuation-by-nearly-a-quarter-culture-amp-reveals-it-lost-another-37-million-last-financial-year/"},
    {"company": "Linktree", "value": 1.3e9, "currency": "USD", "date": "2022-03-16", "basis": "funding round",
     "url": "https://techcrunch.com/2022/03/16/linktree-link-in-bio-series-c-valuation/"},
]
# What eth.blockid.au showed on 2026-09-27 (GET /api/v1/companies, valuation v2) — for comparison only.
CURRENT_V2_AUD = {"Canva": 81.3e9, "Airwallex": 5.08e9, "Go1": 79.4e6, "SafetyCulture": 77.1e6, "Airtasker": 75.5e6,
                  "Employment Hero": 65.3e6}


def ref_aud(r: dict) -> float:
    from blockid_agents.config import fx_to_aud

    return r["value"] * fx_to_aud(r["currency"])


# ------------------------------------------------------------------ offline replay deps
KIND_PATTERNS = (("competitors alternatives", "competitors"), ("market size growth", "market"),
                 ("revenue ARR funding valuation", "company"), ("post-money", "valuation"),
                 ("market cap", "market_cap"), ("EV/revenue multiple", "comps"), ("valuation revenue", "comps_named"))


class ReplaySearch:
    def __init__(self, fx: dict):
        self.fx, self.queries = fx, []

    def search(self, query, count=8, **_):
        self.queries.append(query)
        kind = next((k for pat, k in KIND_PATTERNS if pat.lower() in query.lower()), "")
        return [dict(x, query=query) for x in self.fx["results"].get(kind, [])][:count]


def offline_deps(name: str, fx: dict, workdir: Path, *, ablate_anchors: bool = False):
    import httpx

    from blockid_agents.audit import AuditLog
    from blockid_agents.config import get_settings
    from blockid_agents.deps import Deps
    from blockid_agents.llm import FakeLLM
    from blockid_agents.schemas import (
        CompanyFinancials,
        CompetitorList,
        DimensionScore,
        Finding,
        FundingClaims,
        MarketAnalysis,
        Narrative,
        QualitativeScores,
        RelevanceVerdicts,
        StartupProfile,
        ValuationEvidence,
    )
    from blockid_agents.tools.brave import EvidenceStore
    from blockid_agents.tools.search import SearchChain

    claims = fx["claims"]

    def market(_s, u):
        import re
        urls = re.findall(r"URL: (\S+)", u)
        return MarketAnalysis(market_summary=f"{fx['profile']['sector']} market (recorded fixture).",
                              key_findings=[Finding(claim="sector context", source_urls=urls[:1])] if urls else [],
                              confidence="medium")

    def qual(_s, _u):
        d = lambda: DimensionScore(score=65, basis="ai_suggested", rationale="fixture: neutral")
        return QualitativeScores(founder_quality=d(), product_strength=d(), market_attractiveness=d(),
                                 investment_readiness=d(), trust_verification=d())

    def valuation_evidence(_s, _u):
        ve = ValuationEvidence.model_validate(claims.get("valuation_evidence") or {})
        if ablate_anchors:
            ve.anchors, ve.listing = [], None
        return ve

    def company_financials(_s, _u):
        cf = CompanyFinancials.model_validate(claims["company_financials"] or {})
        if ablate_anchors:
            cf.last_valuation, cf.valuation_quote = None, ""
        return cf

    llm = FakeLLM({
        StartupProfile: lambda _s, _u: StartupProfile.model_validate(fx["profile"]),
        CompetitorList: lambda _s, _u: CompetitorList(),
        FundingClaims: lambda _s, _u: FundingClaims(),
        RelevanceVerdicts: lambda _s, _u: RelevanceVerdicts(),
        MarketAnalysis: market,
        CompanyFinancials: company_financials,
        ValuationEvidence: valuation_evidence,
        QualitativeScores: qual,
        Narrative: lambda _s, _u: Narrative(summary="Indicative valuation (backtest).", strengths=[], concerns=[]),
    })
    llm.name = "replay"

    def site(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=f"<html><head><title>{name}</title></head><body><p>{fx['profile']['description']}"
                                        "</p></body></html>", headers={"content-type": "text/html"})

    s = replace(get_settings(), data_dir=str(workdir), database_url="", svi_tier="cloud", competitor_homepages_max=0,
                search_max_queries=8, search_fetch_per_query=3)
    store = EvidenceStore(workdir / "evidence.sqlite")
    return Deps(llm=llm, audit=AuditLog(workdir / "audit.jsonl"), evidence=store, settings=s,
                search=SearchChain([("replay", ReplaySearch(fx))]),
                fetcher=lambda url: fx["pages"].get(url, ""), site_transport=httpx.MockTransport(site),
                host_check=lambda h: True)


def live_deps(workdir: Path):
    from blockid_agents.config import get_settings
    from blockid_agents.deps import Deps
    from blockid_agents.llm import build_llm

    s = replace(get_settings(), data_dir=str(workdir), database_url="")
    return Deps.default(build_llm(s), s)


# ------------------------------------------------------------------ run
def run_one(deps, vid: str, url: str) -> dict:
    from langgraph.checkpoint.memory import InMemorySaver

    from blockid_agents.graph import build_site_valuation
    from blockid_agents.studio.db import MemoryProgress

    prog = MemoryProgress()
    build_site_valuation(deps, InMemorySaver(), prog).invoke({"job_id": vid, "url": url},
                                                             {"configurable": {"thread_id": vid}})
    return prog.results[vid]


def pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="real search + LLM chain (worker env)")
    ap.add_argument("--ablation", action="store_true", help="offline: also run without market anchors")
    ap.add_argument("--companies", default="", help="comma-separated subset")
    ap.add_argument("--json", default="", help="write per-company results to this file")
    a = ap.parse_args()

    fixtures = json.loads(FIXTURES.read_text())["companies"]
    wanted = [c.strip() for c in a.companies.split(",") if c.strip()]
    refs = [r for r in REFERENCE if not wanted or r["company"] in wanted]
    rows = []
    for r in refs:
        name, fx = r["company"], fixtures[r["company"]]
        row = {"company": name, "reference_aud": ref_aud(r), "reference_date": r["date"], "reference_url": r["url"]}
        try:
            with tempfile.TemporaryDirectory() as tmp:
                deps = live_deps(Path(tmp)) if a.live else offline_deps(name, fx, Path(tmp))
                res = run_one(deps, f"bt-{name.lower().replace(' ', '-')}", fx["url"])
        except Exception as e:  # noqa: BLE001 - one company failing (e.g. robots.txt) must not end the run
            print(f"{name}: FAILED {type(e).__name__}: {str(e)[:160]}", file=sys.stderr)
            continue
        tri = res["svi"]["triangulation"]
        row.update(value_aud=tri["value_aud"], low_aud=tri["low_aud"], high_aud=tri["high_aud"],
                   confidence=tri["confidence"], searches=len(res["searches"]),
                   methods=[(m["method"], round(m["weight"], 2), m["value_aud"]) for m in tri["methods"] if m["weight"]])
        row["error"] = row["value_aud"] / row["reference_aud"] - 1
        row["in_range"] = row["low_aud"] <= row["reference_aud"] <= row["high_aud"]
        if a.ablation and not a.live:
            with tempfile.TemporaryDirectory() as tmp:
                res = run_one(offline_deps(name, fx, Path(tmp), ablate_anchors=True), "bt-abl", fx["url"])
            row["no_anchor_value_aud"] = res["svi"]["triangulation"]["value_aud"]
            row["no_anchor_error"] = row["no_anchor_value_aud"] / row["reference_aud"] - 1
        if name in CURRENT_V2_AUD:
            row["v2_error"] = CURRENT_V2_AUD[name] / row["reference_aud"] - 1
        rows.append(row)

    mode = "LIVE (real search + LLM chain)" if a.live else "OFFLINE (recorded fixtures, 2026-09-27)"
    print(f"Valuation v3 backtest — {mode}\n")
    hdr = f"{'company':<16}{'reference A$':>16}{'v3 value A$':>16}{'error':>9}  {'in range':<9}{'conf':<7}{'v2 err':>9}"
    if a.ablation:
        hdr += f"{'no-anchor err':>15}"
    print(hdr)
    for x in rows:
        line = (f"{x['company']:<16}{x['reference_aud']:>16,.0f}{x['value_aud']:>16,.0f}{pct(x['error']):>9}  "
                f"{'yes' if x['in_range'] else 'no':<9}{x['confidence']:<7}"
                f"{pct(x['v2_error']) if 'v2_error' in x else '-':>9}")
        if a.ablation:
            line += f"{pct(x['no_anchor_error']):>15}"
        print(line)
        print(f"{'':<16}methods: " + ", ".join(f"{m} {w:.0%} (A${v:,.0f})" for m, w, v in x["methods"])
              + f"; searches {x['searches']}")
    med = statistics.median(abs(x["error"]) for x in rows)
    print(f"\nmedian |error| v3: {med * 100:.1f}%  (target <= 30%)  · in range: "
          f"{sum(x['in_range'] for x in rows)}/{len(rows)}")
    v2 = [abs(x["v2_error"]) for x in rows if "v2_error" in x]
    if v2:
        print(f"median |error| v2 (live site values, {len(v2)} companies): {statistics.median(v2) * 100:.1f}%")
    if a.ablation:
        print(f"median |error| without market anchors: "
              f"{statistics.median(abs(x['no_anchor_error']) for x in rows) * 100:.1f}%")
    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=1))
    return 0 if med <= 0.30 else 1


if __name__ == "__main__":
    sys.exit(main())
