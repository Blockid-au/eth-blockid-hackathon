"""Offline fakes: deterministic LLM, Brave transport and Foundry runner.

Used by the test-suite and by `python -m blockid_agents demo`, so the whole pipeline can be shown
(e.g. at a hackathon) with zero API spend and no GPU.
"""
from __future__ import annotations

import json
import re
import subprocess

import httpx

from .llm import FakeLLM
from .schemas import (
    CompanyFinancials,
    CompetitorCandidate,
    CompetitorList,
    ContractReview,
    DimensionScore,
    Finding,
    FundingClaim,
    FundingClaims,
    MarketAnalysis,
    Narrative,
    QualitativeScores,
    RelevanceVerdict,
    RelevanceVerdicts,
    SectorMultipleClaim,
    StartupProfile,
    ValuationEvidence,
)

DEMO_DATAROOM = {
    "pitch.md": (
        "AgriTrace Pty Ltd (ACN 123 456 789) — blockchain traceability for Australian and Vietnamese exporters.\n"
        "Founders: Jane Nguyen (CEO, 12 years supply-chain, 1 prior exit), Tom Lee (CTO, 9 years).\n"
        "Stage: seed. Competitors: TE-FOOD, OpenSC."
    ),
    "financials.csv": "revenue_ttm_aud,480000\nrevenue_growth_yoy_pct,140\ngross_margin_pct,72\nburn_monthly_aud,60000\nrunway_months,14\npaying_customers,23",
}


def _url_list(text: str) -> list[str]:
    return re.findall(r"URL: (\S+)", text)


def fake_llm() -> FakeLLM:
    def profile(_s, _u):
        return StartupProfile(
            company_name="AgriTrace Pty Ltd",
            company_number="ACN 123 456 789",
            country="AU",
            sector="agri-food supply chain traceability",
            stage="seed",
            description="Blockchain traceability SaaS for food exporters",
            founders=[
                {"name": "Jane Nguyen", "role": "CEO", "years_experience": 12, "prior_exits": 1, "domain_expertise": True},
                {"name": "Tom Lee", "role": "CTO", "years_experience": 9},
            ],
            metrics={
                "revenue_ttm_aud": 480000, "revenue_growth_yoy_pct": 140, "gross_margin_pct": 72,
                "burn_monthly_aud": 60000, "runway_months": 14, "paying_customers": 23,
            },
            competitors=["TE-FOOD", "OpenSC"],
            search_keywords=["food traceability software", "agtech"],
            missing_items=["audited financial statements", "IP assignment deeds"],
        )

    def market(_s, u):
        urls = _url_list(u) or ["https://example.org/none"]
        return MarketAnalysis(
            market_summary="Food traceability software is growing on export-compliance demand.",
            market_growth_pct=18,
            revenue_multiple_low=3,
            revenue_multiple_median=6,
            revenue_multiple_high=10,
            key_findings=[
                Finding(claim="Sector SaaS deals price at mid-single-digit revenue multiples", source_urls=[urls[0]]),
                Finding(claim="Invented claim citing an unfetched page", source_urls=["https://not-fetched.example"]),
            ],
            confidence="medium",
        )

    def qual(_s, u):
        assert "Jane Nguyen" not in u, "PII leaked into valuation prompt"
        def mk(s, r):  # basis is overwritten to "ai_suggested" by the valuation agent
            return DimensionScore(score=s, basis="human", rationale=r)

        return QualitativeScores(
            founder_quality=mk(78, "experienced CEO with prior exit"),
            product_strength=mk(70, "live product, 23 paying customers"),
            market_attractiveness=mk(68, "growing niche, export regulation tailwind"),
            investment_readiness=mk(55, "missing audited accounts and IP deeds"),
            trust_verification=mk(60, "claims partly verifiable"),
        )

    def competitor_list(s, _u):
        if "Web search is unavailable" in s:  # fallback: model suggestions with homepages (verified by fetching)
            return CompetitorList(competitors=[
                CompetitorCandidate(name="TE-FOOD", url="https://te-food.example/", note="food traceability"),
                CompetitorCandidate(name="OpenSC", url="https://opensc.example/", note="homepage is down -> dropped"),
                CompetitorCandidate(name="ShoeCo", url="https://shoes.example/", note="off-topic -> dropped"),
                CompetitorCandidate(name="AgriTrace", url=FAKE_SITE, note="the startup itself -> dropped"),
            ])
        return CompetitorList(competitors=[
            CompetitorCandidate(name="TE-FOOD", url="https://te-food.example", note="farm-to-table traceability"),
            CompetitorCandidate(name="OpenSC", url="https://opensc.example", note="supply-chain transparency"),
            CompetitorCandidate(name="AgriTrace", note="the startup itself — must be dropped"),
            CompetitorCandidate(name="Imaginary Rival", note="not in evidence — must be dropped"),
        ])

    def funding(_s, u):
        items = []
        for block in u.split("### Competitor: ")[1:]:
            name = block.split("\n", 1)[0].strip()
            for url, text in re.findall(r"URL: (\S+)\n(.*?)(?=\nURL: |\Z)", block, re.DOTALL):
                if "raised US$10 million" in text:
                    items.append(FundingClaim(name=name, amount=10_000_000, currency="USD", source_url=url,
                                              quote="raised US$10 million"))
            items.append(FundingClaim(name=name, amount=99e6, currency="USD", source_url="https://invented.example",
                                      quote="raised a fortune"))  # hallucination: must be dropped
        return FundingClaims(items=items)

    def relevance(_s, u):
        items = []
        for block in u.split("### ")[1:]:
            name = block.split("\n", 1)[0].strip()
            items.append(RelevanceVerdict(name=name, relevant="running shoes" not in block))
        return RelevanceVerdicts(items=items)

    def valuation_evidence(_s, u):
        # the fake pages state "Median EV/Revenue for traceability SaaS: 6x" -> one verifiable sector multiple,
        # plus one invented claim that verification must drop
        for url, text in re.findall(r"URL: (\S+)\n(?:Retrieved: \S+\n)?(?:Search snippet: [^\n]*\n)?(.*?)(?=\n\n\[|\Z)", u,
                                    re.S):
            if "Median EV/Revenue for traceability SaaS: 6x" in text:
                return ValuationEvidence(sector_multiples=[
                    SectorMultipleClaim(multiple=6, sector="traceability SaaS", public=False, source_url=url,
                                        quote="Median EV/Revenue for traceability SaaS: 6x"),
                    SectorMultipleClaim(multiple=25, sector="invented", source_url="https://invented.example",
                                        quote="trades at 25x revenue")])
        return ValuationEvidence()

    return FakeLLM(
        {
            RelevanceVerdicts: relevance,
            ValuationEvidence: valuation_evidence,
            CompetitorList: competitor_list,
            FundingClaims: funding,
            StartupProfile: profile,
            MarketAnalysis: market,
            CompanyFinancials: lambda _s, _u: CompanyFinancials(),  # no figures stated
            QualitativeScores: qual,
            Narrative: lambda _s, _u: Narrative(summary="Indicative SVI narrative (not financial advice).", strengths=["traction"], concerns=["data-room gaps"]),
            ContractReview: lambda _s, _u: ContractReview(approve=True, notes="parameters consistent"),
        }
    )


def fake_brave_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-Subscription-Token"), "missing Brave token"
        q = request.url.params.get("q", "")
        slug = re.sub(r"[^a-z0-9]+", "-", q.lower()).strip("-")[:40]
        item = {"title": f"Result for {q}", "url": f"https://news.example.com/{slug}", "description": f"About {q}"}
        body = {"results": [item]} if "news" in request.url.path else {"web": {"results": [item]}}
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handler)


def fake_fetch(url: str) -> str:
    return f"Page content for {url}. Median EV/Revenue for traceability SaaS: 6x (range 3x-10x)."


def fake_forge_runner(cmd, cwd, env) -> subprocess.CompletedProcess:
    if cmd[0] == "slither":
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"results": {"detectors": [{"impact": "Low"}]}}), "")
    return subprocess.CompletedProcess(cmd, 0, "Suite result: ok. 20 passed; 0 failed", "")


DEMO_INPUTS = {
    "issuer_safe": "0x1111111111111111111111111111111111111111",
    "transfer_agent": "0x2222222222222222222222222222222222222222",
    "kyc_agent": "0x3333333333333333333333333333333333333333",
    "legal_doc_hash": "0x" + "ab" * 32,
    "board_resolution_id": "AGRITRACE-BR-2026-09-01",
    "share_class": "ORD",
}

DEMO_DEPLOYMENT = {
    "token": "0xBb2180ebd78ce97360503434eD37fcf4a1Df61c3",
    "identity_registry": "0x7FA9385bE102ac3EAc297483Dd6233D62b3e1496",
    "distributor": "0xDB8cFf278adCCF9E9b5da745B44E754fC4EE3C76",
}

DEMO_CAP_TABLE = [
    {"wallet": "0x1000000000000000000000000000000000000001", "shares": 600_000, "holder_ref": "INV-0001"},
    {"wallet": "0x2000000000000000000000000000000000000002", "shares": 300_000, "holder_ref": "INV-0002"},
    {"wallet": "0x3000000000000000000000000000000000000003", "shares": 100_000, "holder_ref": "INV-0003"},
]
DEMO_KYC = {"INV-0001": {"country": "AU"}, "INV-0002": {"country": "VN"}, "INV-0003": {"country": "SG"}}


# ------------------------------------------------------------------ Issuance Studio fakes
FAKE_SITE = "https://agritrace.example"

_SITE_PAGES = {
    "/robots.txt": ("text/plain", "User-agent: *\nDisallow: /private\n"),
    "/": ("text/html", "<html><head><title>AgriTrace — food traceability</title>"
          "<meta name='description' content='Traceability SaaS for food exporters'></head><body>"
          "<h1>AgriTrace Pty Ltd</h1><p>Blockchain traceability for Australian exporters.</p>"
          "<a href='/about'>About</a> <a href='/private/secret'>x</a> <a href='/contact#top'>Contact</a>"
          "<a href='https://elsewhere.example/'>ext</a> <a href='/logo.png'>logo</a> <a href='/old'>old</a>"
          "<a href='/evil'>evil</a></body></html>"),
    "/about": ("text/html", "<html><head><title>About us</title></head><body><p>Founded in Melbourne. "
               "23 paying customers.</p></body></html>"),
    "/contact": ("text/html", "<html><body><p>Email jane@agritrace.au or call +61 481 993 178.</p></body></html>"),
}


_OTHER_SITES = {  # competitor homepages used by the search-unavailable fallback
    "te-food.example": {"/": "<html><head><title>TE-FOOD</title></head><body><p>TE-FOOD is a farm-to-table food "
                             "traceability solution. TE-FOOD raised US$10 million in its latest round.</p></body></html>"},
    "shoes.example": {"/": "<html><head><title>ShoeCo</title></head><body><p>ShoeCo sells running shoes.</p>"
                           "</body></html>"},
    "opensc.example": {},  # every page 404
}


def fake_site_transport(seen: list | None = None) -> httpx.MockTransport:
    """A tiny public website; /private is disallowed by robots.txt, /evil redirects to an internal host."""
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(str(request.url))
        host, path = request.url.host, request.url.path
        if host in _OTHER_SITES:
            page = _OTHER_SITES[host].get(path)
            if page is None:
                return httpx.Response(404, text="not found")
            return httpx.Response(200, text=page, headers={"content-type": "text/html; charset=utf-8"})
        assert not path.startswith("/private"), "robots.txt was not respected"
        if path == "/old":
            return httpx.Response(301, headers={"location": "/about"})
        if path == "/evil":
            return httpx.Response(302, headers={"location": "http://issuer:8090/health"})
        if path in _SITE_PAGES:
            ctype, body = _SITE_PAGES[path]
            return httpx.Response(200, text=body, headers={"content-type": f"{ctype}; charset=utf-8"})
        return httpx.Response(404, text="not found")

    return httpx.MockTransport(handler)


def fake_competitor_brave_transport() -> httpx.MockTransport:
    """Brave results that name TE-FOOD and OpenSC (plus the startup's own site, which must be dropped)."""
    def handler(request: httpx.Request) -> httpx.Response:
        q = request.url.params.get("q", "")
        slug = re.sub(r"[^a-z0-9]+", "-", q.lower()).strip("-")[:40]
        items = [
            {"title": f"Top alternatives: TE-FOOD and OpenSC ({q})", "url": f"https://news.example.com/{slug}",
             "description": "TE-FOOD and OpenSC compete in food traceability"},
            {"title": "AgriTrace home", "url": "https://www.agritrace.example/", "description": "own site"},
        ]
        body = {"results": items} if "news" in request.url.path else {"web": {"results": items}}
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handler)


def fake_competitor_fetch(url: str) -> str:
    if "te-food" in url.lower():
        return "TE-FOOD raised US$10 million in its latest round, the company said."
    return (f"Page content for {url}. TE-FOOD and OpenSC are traceability platforms. "
            "Median EV/Revenue for traceability SaaS: 6x (range 3x-10x).")


# ------------------------------------------------------------------ People Analyst fakes (agents/people.py)
FAKE_PEOPLE_PAGES = {
    "https://agritrace.example/team": (
        "Our team. Jane Nguyen is the CEO and co-founder of AgriTrace. Jane Nguyen previously founded FarmLink, "
        "which was acquired by Elders in 2019. Tom Lee is the CTO of AgriTrace and led engineering at FarmLink "
        "from 2016 to 2019. Contact jane@agritrace.au or +61 481 993 178."),
    "https://news.example.com/jane-nguyen": (
        "Jane Nguyen, founder of AgriTrace, told the conference that traceability cuts export delays. "
        "Nguyen is married with two children."),
    "https://other.example/jane-nguyen-chef": "Jane Nguyen is a pastry chef in Hanoi who won a baking award in 2022.",
    "https://news.example.com/tom-lee": "Tom Lee, CTO at AgriTrace, holds a PhD in computer science from UNSW.",
}


class FakePeopleSearch:
    """Search provider stand-in: results keyed on the person's name in the query."""

    name = "fake-search"
    available = True

    def __init__(self):
        self.queries: list[str] = []

    def search(self, query: str, *, count: int = 8, **_):
        self.queries.append(query)
        q = query.lower()
        out = []
        if "jane nguyen" in q:
            out = [{"title": "Jane Nguyen — AgriTrace", "url": "https://news.example.com/jane-nguyen",
                    "description": "Jane Nguyen, founder of AgriTrace", "query": query},
                   {"title": "Jane Nguyen chef", "url": "https://other.example/jane-nguyen-chef",
                    "description": "pastry chef", "query": query}]
        elif "tom lee" in q:
            out = [{"title": "Tom Lee CTO", "url": "https://news.example.com/tom-lee",
                    "description": "Tom Lee, CTO at AgriTrace", "query": query}]
        return out[:count]


def fake_people_fetch(url: str) -> str:
    if url in FAKE_PEOPLE_PAGES:
        return FAKE_PEOPLE_PAGES[url]
    raise httpx.ConnectError(f"no fake page for {url}")


def fake_people_llm() -> FakeLLM:
    """Deterministic PersonAnalysis / TeamAnalysis with verifiable, unverifiable and sensitive claims mixed in."""
    from .agents import people as pa

    def s(score, ids=(), self_reported=False, why="r"):
        return pa.SubScore(score=score, rationale=why, fact_ids=list(ids), self_reported=self_reported)

    def person(_s, u):
        target = "TARGET (" in u
        fit = pa.FitSuggestion(
            skills_match=s(80, ["f1"]), domain_match=s(90, ["f1"]), stage_scale_match=s(70),
            seniority_match=s(75, self_reported=True), track_record_relevance=s(85, ["f1"]),
            requirements=[pa.RequirementMatch(requirement="agri-food supply chain expertise", status="matched",
                                              fact_ids=["f1"]),
                          pa.RequirementMatch(requirement="enterprise sales", status="matched"),
                          pa.RequirementMatch(requirement="regulatory affairs", status="missing")],
            risks=["single-market experience"], interview_questions=["How will you hire a sales lead?"])
        if "PERSON: Tom Lee" in u:
            return pa.PersonAnalysis(
                facts=[pa.FactClaim(id="f1", text="CTO of AgriTrace; led engineering at FarmLink",
                                    quote="Tom Lee is the CTO of AgriTrace and led engineering at FarmLink",
                                    source_url="https://agritrace.example/team", category="role"),
                       pa.FactClaim(id="f2", text="PhD in computer science from UNSW",
                                    quote="holds a PhD in computer science from UNSW",
                                    source_url="https://news.example.com/tom-lee", category="education")],
                profile=pa.CVDraft(experience=[pa.ExperienceItem(org="FarmLink", title="Head of Engineering",
                                                                 fact_ids=["f1"])],
                                   education=[pa.EducationItem(institution="UNSW", degree="PhD", fact_ids=["f2"])]),
                scores=pa.PersonScores(domain_fit=s(60, ["f1"]), track_record=s(70, ["f1"]),
                                       leadership=s(60), functional_depth=s(85, ["f2"]),
                                       verifiability=s(80, ["f1", "f2"]), commitment=s(70, self_reported=True)),
                fit=fit if target else None, functions=["tech"], strengths=["deep engineering"],
                gaps=["no commercial experience"], questions=["Who owns security?"])
        return pa.PersonAnalysis(
            facts=[
                pa.FactClaim(id="f1", text="Founded FarmLink, acquired by Elders in 2019",
                             quote="Jane Nguyen previously founded FarmLink, which was acquired by Elders in 2019",
                             source_url="https://agritrace.example/team", category="exit"),
                pa.FactClaim(id="f2", text="Raised A$50m", quote="raised A$50 million from Sequoia",
                             source_url="https://news.example.com/jane-nguyen", category="venture"),  # not on page
                pa.FactClaim(id="f3", text="Won a baking award", quote="won a baking award in 2022",
                             source_url="https://other.example/jane-nguyen-chef",
                             category="achievement"),  # other person: page names neither company nor orgs
                pa.FactClaim(id="f4", text="Nguyen is married with two children",
                             quote="Nguyen is married with two children",
                             source_url="https://news.example.com/jane-nguyen"),  # sensitive: dropped
                pa.FactClaim(id="f5", text="Spoke at a conference", quote="told the conference that traceability",
                             source_url="https://invented.example/talk"),  # URL never stored
            ],
            profile=pa.CVDraft(
                headline=pa.TextItem(text="Agri supply-chain founder", cv_quote="supply-chain founder"),
                location=pa.TextItem(text="Melbourne, Australia", cv_quote="Based in Melbourne"),
                summary="Second-time founder in agri supply chains.",
                experience=[pa.ExperienceItem(org="FarmLink", title="Founder & CEO", start="2014", end="2019",
                                              achievements=["sold to Elders"], fact_ids=["f1"]),
                            pa.ExperienceItem(org="Sequoia", title="Partner", fact_ids=["f2"])],  # unverified
                education=[pa.EducationItem(institution="University of Melbourne", degree="MBA",
                                            cv_quote="MBA, University of Melbourne")],
                skills=[pa.SkillGroup(group="Commercial", items=["enterprise sales"], cv_quote="enterprise sales"),
                        pa.SkillGroup(group="Invented", items=["quantum"])],  # no source: unconfirmed
                ventures=[pa.VentureItem(name="FarmLink", role="founder", outcome="acquired", year="2019",
                                         fact_ids=["f1"])]),
            scores=pa.PersonScores(domain_fit=s(80, ["f1"]), track_record=s(90), leadership=s(70, self_reported=True),
                                   functional_depth=s(60, ["f2"]), verifiability=s(85, self_reported=True),
                                   commitment=s(90, self_reported=True)),
            fit=fit if target else None, functions=["commercial", "domain"], strengths=["prior exit"],
            gaps=["no finance lead"], questions=["What was the FarmLink exit multiple?"])

    def team(_s, u):
        ids = re.findall(r"\[(p\d+f\d+)\]", u)
        return pa.TeamAnalysis(
            worked_together=pa.Component(score=85, rationale="both at FarmLink", fact_ids=ids[:1]),
            strengths=["prior exit together"], gaps=["no CFO"], risks=["key-person risk on the CEO"],
            questions=["Who leads finance?"],
            red_flags=[pa.RedFlagClaim(text="unverified rumour", fact_ids=["p999f1"]),
                       pa.RedFlagClaim(text="FarmLink was sold (verified fact)", fact_ids=ids[:1])])

    from .agents import cv_review as cvr

    def cv_structure(_s, _u):
        return cvr.CVStructure(headline="CEO", location="Melbourne, Australia", roles=[
            cvr.CVRole(org="AgriTrace", title="CEO", start="2021-01", end="present", kind="founder",
                       highlights=["Raised A$2M seed"]),
            cvr.CVRole(org="FarmLink", title="Head of Sales", start="2016-03", end="2019-12", team_size=12),
            cvr.CVRole(org="Coles", title="Buyer", start="2012", end="2015")],
            education=[cvr.CVEducation(institution="University of Melbourne", degree="MBA")], languages=["English"])

    def cv_insights(_s, _u):
        return cvr.CVInsights(summary="Agri supply-chain operator turned founder.", seniority="executive",
                              skills=[cvr.CVSkill(name="Enterprise sales", level="expert", years=8)],
                              achievements=[cvr.CVAchievement(text="Grew FarmLink revenue", metric="3x", org="FarmLink")],
                              concerns=["No detail on the 2020 break"],
                              claims=[cvr.CVClaim(text="Head of Sales at FarmLink", org="FarmLink", kind="role"),
                                      cvr.CVClaim(text="Buyer at Coles", org="Coles", kind="role"),
                                      cvr.CVClaim(text="Call me on +61 481 993 178", org="x")])

    return FakeLLM({pa.PersonAnalysis: person, pa.TeamAnalysis: team, cvr.CVStructure: cv_structure,
                    cvr.CVInsights: cv_insights})
