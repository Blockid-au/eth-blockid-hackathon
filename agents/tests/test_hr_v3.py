"""HR v3 (docs/PLAN-HR-V3.md): the CV claim ledger (golden set of honest / inflated / shifted / fabricated /
namesake CVs), trust index, fit lenses (claimed vs verified, knockouts, relevant years, verdict, decision), the JD
fairness check, role templates, structured lookups and the full pipeline with claim-led searches."""
import json
import time

import httpx
import pytest

from blockid_agents.agents import cv_ledger as cl
from blockid_agents.agents import hr_fit as hf
from blockid_agents.agents import people as pa
from blockid_agents.fakes import fake_people_llm
from blockid_agents.llm import FakeLLM
from blockid_agents.schemas import EvidenceItem
from blockid_agents.tools.people_lookups import PeopleLookups, github_logins

from test_cv_review import CV, Rec
from test_people import JANE, deps_for

NAME = "An Tran"


def ev(url: str, text: str, kind: str = "web") -> tuple:
    return (EvidenceItem(url=url, title=url, snippet="", retrieved_at=time.time(), content_sha256="x", query="q",
                         kind=kind), text)


def fact(fid: str, url: str, quote: str, text: str | None = None) -> dict:
    return {"id": fid, "text": text or quote, "quote": quote, "url": url, "category": "role"}


def claim(cid="c1", kind="role", org="FarmLink", title="Head of Engineering", start="2016", end="2019",
          metric="", importance=2) -> dict:
    return {"id": cid, "kind": kind, "text": f"{title} at {org}", "org": org, "title": title, "start": start,
            "end": end, "metric": metric, "cv_quote": "", "importance": importance}


def ledger_one(c: dict, facts: list[dict], evidence: list, check: cl.ClaimCheck | None = None, **kw) -> dict:
    ids = {f["id"]: f["id"] for f in facts}
    lg = cl.build_ledger([c], facts, [check] if check else [], ids, evidence, person=NAME, **kw)
    return lg["claims"][0]


# ================================================================== golden set: the claim ledger
def test_honest_role_on_the_org_site_is_verified():
    url = "https://farmlink.example/team"
    q = "An Tran was Head of Engineering at FarmLink from 2016 to 2019"
    c = ledger_one(claim(), [fact("f1", url, q)], [ev(url, q)])
    assert c["status"] == "verified" and c["best_tier"] == 1  # the organisation's own site
    assert c["dims"] == {"identity": True, "org": True, "title": True, "dates": True, "degree": None, "metric": None}


def test_one_ordinary_page_is_only_partly_verified_two_hosts_verify():
    q = "An Tran, Head of Engineering at FarmLink"
    a, b = "https://blog-one.example/post", "https://blog-two.example/story"
    assert ledger_one(claim(), [fact("f1", a, q)], [ev(a, q)])["status"] == "partly_verified"
    c = ledger_one(claim(), [fact("f1", a, q), fact("f2", b, q)], [ev(a, q), ev(b, q)])
    assert c["status"] == "verified" and c["best_tier"] == 3


def test_snippet_only_is_partly_verified():
    url = "https://news.example.org/x"
    q = "An Tran, Head of Engineering at FarmLink"
    c = ledger_one(claim(), [fact("f1", url, q)], [ev(url, q, kind="search_snippet")])
    assert c["status"] == "partly_verified" and c["best_tier"] == 4


def test_org_confirmed_but_other_title_is_partly_not_contradicted_without_a_quote():
    url = "https://farmlink.example/about"
    q = "An Tran founded FarmLink in 2016"
    c = ledger_one(claim(title="Head of Sales"), [fact("f1", url, q)], [ev(url, q)])
    assert c["status"] == "partly_verified" and c["dims"]["title"] is None and "title" in c["note"]


def test_inflated_title_with_a_checked_quote_is_contradicted():
    url = "https://press.example.com/farmlink"
    page = "FarmLink hired An Tran as Senior Developer in 2016. The team grew to 12."
    chk = cl.ClaimCheck(claim_id="c1", conflict=cl.ClaimConflict(
        source_url=url, quote="FarmLink hired An Tran as Senior Developer in 2016", field="title",
        source_value="Senior Developer"))
    c = ledger_one(claim(title="CTO"), [], [ev(url, page)], chk)
    assert c["status"] == "contradicted" and c["dims"]["title"] is False
    assert c["conflict"]["source_value"] == "Senior Developer" and c["conflict"]["url"] == url


def test_shifted_dates_contradicted_only_outside_the_tolerance():
    url = "https://press.example.com/coles"
    page = "An Tran joined Coles as Head of Sales in 2019, the retailer said."
    mk = lambda v: cl.ClaimCheck(claim_id="c1", conflict=cl.ClaimConflict(  # noqa: E731
        source_url=url, quote="An Tran joined Coles as Head of Sales in 2019", field="dates", source_value=v))
    c = claim(org="Coles", title="Head of Sales", start="2012", end="2015")
    assert ledger_one(c, [], [ev(url, page)], mk("2019"))["status"] == "contradicted"
    near = claim(org="Coles", title="Head of Sales", start="2016", end="2018")  # 2019 is within ±1 year
    assert ledger_one(near, [], [ev(url, page)], mk("2019"))["status"] != "contradicted"


def test_degree_level_conflict():
    url = "https://unsw.edu.au/alumni"
    page = "An Tran holds a Bachelor of Science from UNSW and joined FarmLink."
    chk = cl.ClaimCheck(claim_id="c1", conflict=cl.ClaimConflict(
        source_url=url, quote="An Tran holds a Bachelor of Science from UNSW", field="degree",
        source_value="Bachelor of Science"))
    c = ledger_one(claim(kind="education", org="UNSW", title="PhD", start="", end=""), [], [ev(url, page)], chk)
    assert c["status"] == "contradicted" and c["dims"]["degree"] is False


@pytest.mark.parametrize("why,conflict,page", [
    ("quote not on the page", dict(quote="An Tran was an intern at FarmLink", field="title", source_value="intern"),
     "An Tran was Head of Engineering at FarmLink."),
    ("value not in the quote", dict(quote="An Tran worked at FarmLink", field="title", source_value="Intern"),
     "An Tran worked at FarmLink."),
    ("quote does not name the organisation", dict(quote="An Tran was a Senior Developer", field="title",
                                                  source_value="Senior Developer"),
     "An Tran was a Senior Developer at Atlassian."),
    ("same role family", dict(quote="An Tran, Engineering Manager at FarmLink", field="title",
                              source_value="Engineering Manager"), "An Tran, Engineering Manager at FarmLink."),
    ("page names someone else", dict(quote="Bo Le was CTO at FarmLink", field="title", source_value="CTO"),
     "Bo Le was CTO at FarmLink."),
    ("unsupported field", dict(quote="An Tran worked at FarmLink", field="org", source_value="FarmLink"),
     "An Tran worked at FarmLink."),
    ("metric within 25 %", dict(quote="FarmLink revenue grew 2.8x under An Tran", field="metric",
                                source_value="2.8x"), "FarmLink revenue grew 2.8x under An Tran."),
])
def test_no_false_contradictions(why, conflict, page):
    url = "https://press.example.com/p"
    c = claim(kind="achievement", metric="3x", title="") if conflict["field"] == "metric" else claim()
    chk = cl.ClaimCheck(claim_id="c1", conflict=cl.ClaimConflict(source_url=url, **conflict))
    assert ledger_one(c, [], [ev(url, page)], chk)["status"] != "contradicted", why


def test_conflict_on_a_snippet_is_ignored():
    url = "https://press.example.com/s"
    page = "FarmLink hired An Tran as Senior Developer in 2016"
    chk = cl.ClaimCheck(claim_id="c1", conflict=cl.ClaimConflict(source_url=url, quote=page, field="title",
                                                                 source_value="Senior Developer"))
    assert ledger_one(claim(title="CTO"), [], [ev(url, page, kind="search_snippet")], chk)["status"] != "contradicted"


def test_not_found_vs_unverifiable_and_namesakes():
    chef = "https://other.example/an-tran-chef"
    evidence = [ev(chef, "An Tran is a pastry chef in Hanoi who won a baking award.")]
    c = claim(kind="education", org="University of Sydney", title="PhD", start="", end="")
    lg = cl.build_ledger([c, claim("c2", org="Initech"), claim("c3", kind="certification", org="", title="PMP")],
                         [], [], {}, evidence, person=NAME, searched={"c1"}, anchors=["FarmLink"], provided=set())
    st = {x["id"]: x["status"] for x in lg["claims"]}
    assert st == {"c1": "not_found", "c2": "unverifiable", "c3": "unverifiable"}
    assert "not the same as false" in lg["claims"][0]["note"]
    assert lg["namesakes"] and lg["namesakes"][0]["url"] == chef
    assert lg["counts"]["not_found"] == 1 and lg["counts"]["unverifiable"] == 2


def test_metric_claim_verified_by_number():
    url = "https://farmlink.example/news"
    q = "Under An Tran, FarmLink revenue grew 3x in four years"
    c = ledger_one(claim(kind="achievement", title="", metric="3x revenue"), [fact("f1", url, q)], [ev(url, q)])
    assert c["dims"]["metric"] is True and c["status"] == "verified"


def test_model_mapping_without_the_org_is_partly():
    url = "https://blog.example/x"
    q = "An Tran led the engineering team for years"
    chk = cl.ClaimCheck(claim_id="c1", fact_ids=["f1"])
    c = ledger_one(claim(), [fact("f1", url, q)], [ev(url, q)], chk)
    assert c["status"] == "partly_verified" and c["dims"]["org"] is None


# ================================================================== trust index
def _lg(*statuses_imp):
    claims = [{**claim(f"c{i}", importance=imp), "status": st} for i, (st, imp) in enumerate(statuses_imp, 1)]
    return {"claims": claims, "counts": {s: sum(1 for c in claims if c["status"] == s) for s in cl.STATUSES}}


def test_trust_index_bands():
    t = cl.trust_index(_lg(("verified", 3), ("verified", 2), ("partly_verified", 1)))
    assert t["band"] == "high" and t["score"] == round(100 * (3 + 2 + 0.6) / 6, 1) and t["coverage_pct"] == 100
    t = cl.trust_index(_lg(("verified", 3), ("contradicted", 2), ("verified", 1)))
    assert t["band"] == "low" and t["contradicted_key"] == 1  # a conflict on a key claim
    t = cl.trust_index(_lg(("not_found", 3), ("unverifiable", 2)))
    assert t["band"] == "low" and t["score"] < 45
    t = cl.trust_index(_lg(("partly_verified", 3), ("verified", 2), ("not_found", 1)))
    assert t["band"] == "medium"
    assert cl.trust_index({"claims": []}) is None


# ================================================================== helpers
def test_source_tiers():
    assert cl.source_tier("https://abr.business.gov.au/x", "web") == 1
    assert cl.source_tier("https://www.unimelb.edu.au/x", "web") == 1
    assert cl.source_tier("https://farmlink.com.au/team", "web", org="FarmLink Pty Ltd") == 1
    assert cl.source_tier("https://agritrace.example/team", "provided", business_host="agritrace.example") == 2
    assert cl.source_tier("https://www.afr.com/story", "web") == 2
    assert cl.source_tier("https://web.archive.org/web/2021/https://x", "web") == 2
    assert cl.source_tier("https://someblog.example/a", "web") == 3
    assert cl.source_tier("https://www.afr.com/story", "search_snippet") == 4


def test_role_families_and_degrees():
    assert cl.families("Chief Technology Officer") >= {"cto", "engineering"}
    assert "engineering" in cl.families("led engineering at FarmLink")
    assert not cl.families("Head of Sales") & cl.families("founded FarmLink")
    assert cl.titles_agree("CTO", "Senior Developer") is False  # inflated title: same function, 3 levels apart
    assert cl.titles_agree("Head of Engineering", "Engineering Manager") is True
    assert cl.titles_agree("Head of Sales", "Software Engineer") is False
    assert cl.titles_agree("Founder", "Chef") is None
    assert cl.degree_level("MBA, University of Melbourne") == "master"
    assert cl.degree_level("Tiến sĩ Khoa học máy tính") == "phd"


def test_claims_from_review_importance_quotes_and_queries():
    rv = {"timeline": {"roles": [
        {"org": "AgriTrace", "title": "CEO", "start": "2021-01", "end": "present", "kind": "founder"},
        {"org": "FarmLink", "title": "Head of Sales", "start": "2016-03", "end": "2019-12"},
        {"org": "Coles", "title": "Buyer", "start": "2012", "end": "2015"}],
        "education": [{"institution": "University of Melbourne", "degree": "MBA"}], "certifications": []},
        "insights": {"achievements": [{"text": "Grew FarmLink revenue", "metric": "3x", "org": "FarmLink"}],
                     "claims": [{"text": "Head of Sales at FarmLink", "org": "FarmLink", "kind": "role"}]}}
    cs = cl.claims_from_review(rv, CV)
    by = {(c["kind"], c["org"]): c for c in cs}
    assert by[("venture", "AgriTrace")]["importance"] == 3 and by[("role", "Coles")]["importance"] == 1
    assert by[("education", "University of Melbourne")]["importance"] == 2
    assert by[("role", "FarmLink")]["cv_quote"] in CV  # an exact excerpt of the CV
    assert [c["id"] for c in cs] == [f"c{i}" for i in range(1, len(cs) + 1)]
    assert sum(1 for c in cs if c["org"] == "FarmLink" and c["kind"] == "role") == 1  # insight claim not repeated
    qs = cl.claim_queries("Jane Nguyen", cs, "AgriTrace", [], 3)
    assert len(qs) == 3 and all(q.startswith('"Jane Nguyen"') for _, q in qs)
    assert not any("AgriTrace" in q for _, q in qs)  # the business is covered by the general searches
    assert '"Jane Nguyen" "University of Melbourne"' in [q for _, q in qs]


# ================================================================== fairness + templates
@pytest.mark.parametrize("text", ["Young and dynamic", "Male candidates only", "Under 35", "Must be single",
                                  "Native English speaker", "Good-looking", "Vietnamese nationals only",
                                  "Physically fit and healthy"])
def test_protected_requirements_flagged(text):
    keep, flagged = hf.split_protected([text, "5+ years of Python"])
    assert keep == ["5+ years of Python"] and flagged[0]["text"] == text


@pytest.mark.parametrize("text", ["Australian work rights", "Driver licence", "Baseline security clearance",
                                  "Fluent Vietnamese", "Enterprise sales in agri-food", "Degree in engineering"])
def test_lawful_requirements_kept(text):
    assert hf.protected_reason(text) is None


def test_role_templates_and_stage_bands():
    assert hf.stage_band("seed") == "early" and hf.stage_band("series-a") == "scale"
    assert hf.stage_band("growth") == "growth" and hf.stage_band(None) == "scale"
    t = hf.role_template("Co-founder & CTO", "seed")
    assert t["key"] == "cto" and t["stage_band"] == "early" and len(t["competencies"]) == 5
    assert hf.role_template("Chief Executive Officer", "growth")["key"] == "ceo"
    assert hf.role_template("Senior Software Engineer", None)["key"] == "engineer"
    assert hf.role_template("", "seed") is None and hf.role_template("Chef", "seed") is None


def test_clean_jd_moves_protected_wording_to_flagged():
    j = hf.JDParse(title="CTO", seniority="executive", min_years=8, must=["Scaled a team of 20", "Young founder"],
                   nice=["Male preferred"], knockouts=["Australian work rights"])
    out = hf.clean_jd(j)
    assert out["must"] == ["Scaled a team of 20"] and out["knockouts"] == ["Australian work rights"]
    assert {f["text"] for f in out["flagged"]} == {"Young founder", "Male preferred"}


# ================================================================== fit lenses
def _base(reqs, comps=None):
    comps = comps or {k: {"score": 80.0, "fact_ids": ["p1f1"], "self_reported": False, "weight": w}
                      for k, w in pa.FIT_WEIGHTS.items() if k != "gaps"}
    comps["gaps"] = {"score": 0.0, "fact_ids": [], "self_reported": False, "weight": pa.FIT_WEIGHTS["gaps"]}
    return {"target_type": "role", "label": "role fit", "score": 0, "components": comps, "requirements": reqs}


def _req(text, status="matched", fact_ids=(), self_reported=False, must=True):
    return {"requirement": text, "must_have": must, "status": status, "fact_ids": list(fact_ids),
            "self_reported": self_reported, "note": ""}


def test_claimed_vs_verified_fit_and_evidence_levels():
    base = _base([_req("Python", fact_ids=["p1f1"]), _req("Led a team of 10", self_reported=True),
                  _req("Fintech domain", self_reported=True)])
    claims = {"c1": {"status": "contradicted"}, "c2": {"status": "not_found"}}
    f = hf.lens_fit(base, "jd", claims=claims, req_claims={"Led a team of 10": ["c1"], "Fintech domain": ["c2"]})
    ev = {r["requirement"]: r["evidence"] for r in f["requirements"]}
    assert ev == {"Python": "verified", "Led a team of 10": "contradicted", "Fintech domain": "cv_only"}
    assert f["components"]["gaps"]["suggested"] == 100.0 and f["components"]["gaps"]["score"] == round(
        100 * (1 + 0 + 0.5) / 3, 1)
    assert f["claimed_score"] > f["verified_score"] == f["score"]
    assert f["cap"] == hf.CAP_MUST_CONTRADICTED and f["verified_score"] <= 40  # a must-have rests on a conflict
    assert f["verdict"] in ("weak", "not_suitable")


def test_missing_must_have_caps_and_downgrades_strong():
    f = hf.lens_fit(_base([_req("Python", fact_ids=["p1f1"]), _req("Kubernetes", status="missing")]), "jd",
                    claims={}, req_claims={})
    assert f["knockouts"] == ["Kubernetes"] and f["cap"] == 60 and f["verified_score"] <= 60
    assert f["verdict"] == "conditional"
    strong = hf.lens_fit(_base([_req("Python", fact_ids=["p1f1"])]), "jd", claims={}, req_claims={})
    assert strong["verdict"] == "strong" and strong["cap"] is None and not strong["knockouts"]


def test_knockout_marked_must_have_and_self_reported_component_halved():
    comps = {k: {"score": 90.0, "fact_ids": [], "self_reported": True, "weight": w}
             for k, w in pa.FIT_WEIGHTS.items() if k != "gaps"}
    f = hf.lens_fit(_base([_req("Driver licence", must=False, fact_ids=["p1f2"])], comps), "jd", claims={},
                    req_claims={}, knockouts=["Driver licence"])
    r = f["requirements"][0]
    assert r["knockout"] and r["must_have"]
    assert f["claimed_score"] > f["verified_score"]  # 90 claimed -> 70 verified on each self-reported component


def test_relevant_years_and_short_experience_knockout():
    roles = [{"org": "A", "title": "Data Engineer", "end": "present", "months": 24},
             {"org": "B", "title": "Analyst", "end": "2012", "months": 60}]
    rel = hf.relevant_experience(roles, [hf.RoleRelevance(role=1, relevance="high"),
                                         hf.RoleRelevance(role=2, relevance="medium")], 8)
    assert rel["years"] == round((24 + 60 * 0.5 * hf.OLD_ROLE_WEIGHT) / 12, 1) and rel["min_years"] == 8
    f = hf.lens_fit(_base([_req("Python", fact_ids=["p1f1"])]), "jd", claims={}, req_claims={}, relevant=rel)
    assert any("years of relevant experience" in k for k in f["knockouts"]) and f["verdict"] != "strong"


def test_alt_role_only_when_clearly_better():
    base = _base([_req("Kubernetes", status="missing")])
    f = hf.lens_fit(base, "jd", claims={}, req_claims={}, alt=hf.AltRole(role="Head of Partnerships", score=82))
    assert f["alt_role"]["role"] == "Head of Partnerships" and f["alt_role"]["model_suggested"]
    g = hf.lens_fit(_base([_req("Python", fact_ids=["p1f1"])]), "jd", claims={}, req_claims={},
                    alt=hf.AltRole(role="X", score=82))
    assert g["alt_role"] is None


def test_decision_quadrants():
    strong = hf.lens_fit(_base([_req("Python", fact_ids=["p1f1"])]), "jd", claims={}, req_claims={})
    weak = hf.lens_fit(_base([_req("Python", status="missing")], {k: {"score": 20.0, "fact_ids": ["x"], "weight": w}
                                                                   for k, w in pa.FIT_WEIGHTS.items() if k != "gaps"}),
                       "jd", claims={}, req_claims={})
    hi = {"band": "high", "summary": "s", "score": 80}
    lo = {"band": "low", "summary": "s", "score": 20}
    assert hf.decision({"jd": strong}, hi, None, None)["quadrant"] == "proceed"
    assert hf.decision({"jd": strong}, lo, None, None)["quadrant"] == "verify_first"
    assert hf.decision({"jd": weak}, hi, None, None)["quadrant"] == "other_role"
    assert hf.decision({"jd": weak}, lo, None, None)["quadrant"] == "stop"
    assert hf.decision({}, hi, None, None) is None
    lg = {"claims": [{**claim(), "status": "contradicted"}]}
    d = hf.decision({"jd": strong}, lo, lg, None)
    assert d["verify"][0].startswith("Conflict on") and len(d["reasons"]) <= 3


# ================================================================== lookups
def _gh_transport():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/users/antran":
            return httpx.Response(200, json={"login": "antran", "name": "An Tran", "company": "@farmlink",
                                             "created_at": "2014-05-01T00:00:00Z", "public_repos": 40,
                                             "followers": 12, "bio": "engineer"})
        if req.url.path == "/users/antran/orgs":
            return httpx.Response(200, json=[{"login": "farmlink"}])
        if req.url.host == "api.openalex.org":
            return httpx.Response(200, json={"results": [
                {"id": "https://openalex.org/A1", "display_name": "An Tran", "works_count": 7, "cited_by_count": 90,
                 "affiliations": [{"institution": {"display_name": "UNSW Sydney"}, "years": [2014, 2018]}]},
                {"id": "https://openalex.org/A2", "display_name": "An Tran", "works_count": 50,
                 "affiliations": [{"institution": {"display_name": "Hanoi Medical University"}, "years": [2020]}]}]})
        if req.url.path == "/cdx/search/cdx":
            return httpx.Response(200, json=[["timestamp"], ["20210603120000"]])
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_people_lookups_github_openalex_wayback(tmp_path):
    from blockid_agents.tools.brave import EvidenceStore

    lk = PeopleLookups(EvidenceStore(tmp_path / "e.sqlite"), transport=_gh_transport())
    assert github_logins(["https://github.com/AnTran", "https://github.com/orgs/x", "linkedin.com/in/a"]) == ["antran"]
    g = lk.github("antran")
    assert "Account created: 2014-05-01" in g["page"]["text"] and g["record"]["found"]
    assert g["page"]["kind"] == "provided"
    o = lk.openalex("An Tran", ["UNSW", "FarmLink"])
    assert "openalex.org/A1" in o["page"]["url"] and "UNSW Sydney (2014–2018)" in o["page"]["text"]
    assert lk.openalex("An Tran", ["Stanford"])["record"]["found"] is False  # no namesake page kept
    w = lk.wayback("https://farmlink.example/team", lambda u: "Team: An Tran, CTO")
    assert w["page"]["url"].startswith("https://web.archive.org/web/20210603120000/")
    assert "captured on 2021-06-03" in w["page"]["text"]
    lk.offline = True  # served from the 7-day cache now
    assert lk.github("antran")["record"]["found"]


# ================================================================== the pipeline
def test_pipeline_ledger_trust_fits_decision_and_live_parts(tmp_path):
    tr = Rec()
    deps = deps_for(tmp_path)
    target = {"type": "role", "company": "Acme", "title": "Head of Supply Chain", "description": "Lead ops",
              "requirements": ["agri-food supply chain expertise", "enterprise sales"], "min_years": 5,
              "knockouts": ["enterprise sales"]}
    res = pa.analyse({"id": "t_v3", "mode": "person", "name": "Jane Nguyen"}, [{**JANE, "cv": CV}], deps,
                     tracker=tr, target=target)
    card = res["people"][0]
    lg = card["cv_review"]["ledger"]
    st = {c["org"]: c["status"] for c in lg["claims"] if c["kind"] in ("role", "venture")}
    assert st["FarmLink"] == "partly_verified"  # the team page names FarmLink, but as founder, not Head of Sales
    assert st["Coles"] in ("not_found", "unverifiable")
    assert "ledger" in tr.parts and any(n.startswith("Checked ") and "CV claims" in n for n in tr.notes)
    # claim-led searches ran for the CV's organisations
    queries = [s["query"] for s in res["searches"]]
    assert any('"FarmLink"' in q for q in queries) and len(queries) <= 6
    assert card["trust"]["band"] in ("low", "medium", "high")
    assert card["subscores"]["verifiability"]["score"] == card["trust"]["score"]
    assert card["subscores"]["verifiability"]["computed"]
    assert set(card["fits"]) == {"jd", "current_role"}
    jd = card["fits"]["jd"]
    assert jd is card["fit"] and jd["relevant"]["min_years"] == 5 and jd["relevant"]["roles"]
    assert any(r["knockout"] for r in jd["requirements"])
    assert card["fits"]["current_role"]["template"]["key"] == "ceo" and card["fits"]["current_role"]["lens"] == \
        "current_role"
    d = card["decision"]
    assert d["quadrant"] in ("proceed", "verify_first", "other_role", "stop") and d["fit_lens"] == "jd"
    assert card["contribution"] == round(0.5 * card["score"] + 0.5 * jd["verified_score"], 1)
    assert res["version"] == "hr-2" and "trust" in res["method"]
    # v2 clients keep the old claims shape
    assert {c["status"] for c in card["cv_review"]["claims"]} <= {"confirmed", "unconfirmed"}


def test_pipeline_uses_injected_lookups(tmp_path):
    from blockid_agents.tools.brave import EvidenceStore

    deps = deps_for(tmp_path)
    deps.people_lookups = PeopleLookups(EvidenceStore(tmp_path / "lk.sqlite"), transport=_gh_transport())
    tr = Rec()
    p = {**JANE, "full_name": "Jane Nguyen", "urls": ["https://agritrace.example/team", "https://github.com/antran"],
         "cv": CV}
    res = pa.analyse({"id": "t_v3l", "mode": "person", "name": "Jane Nguyen"}, [p], deps, tracker=tr)
    lookups = res["people"][0]["cv_review"]["ledger"]["lookups"]
    kinds = {x["kind"] for x in lookups}
    assert {"github", "wayback"} <= kinds
    assert any(n.startswith("GitHub:") for n in tr.notes)


def test_team_report_has_business_and_current_role_lenses(tmp_path):
    from test_people import TEAM, TOM

    res = pa.analyse(TEAM, [JANE, TOM], deps_for(tmp_path))
    for c in res["people"]:
        assert "business" in c["fits"] and c["fit"]["lens"] == "business"
    tom = next(c for c in res["people"] if c["full_name"] == "Tom Lee")
    assert tom["fits"]["current_role"]["template"]["key"] == "cto"
    assert tom["trust"] is None and "cv_review" not in tom  # no CV -> no ledger


def test_share_view_hides_conflicts_and_trust_number():
    from blockid_agents.studio.hr import _public_result

    res = {"people": [{"trust": {"score": 40, "band": "low"}, "cv_review": {"ledger": {
        "claims": [{"id": "c1", "status": "contradicted", "conflict": {"quote": "x"}}], "namesakes": [{"url": "u"}]}}}],
        "team_inputs": {"x": 1}}
    full = _public_result(res)
    assert full["people"][0]["trust"]["score"] == 40 and "team_inputs" not in full
    lim = _public_result(res, full=False)
    c = lim["people"][0]
    assert c["trust"] == {"score": None, "band": "low"}
    assert c["cv_review"]["ledger"]["claims"][0]["conflict"] is None
    assert c["cv_review"]["ledger"]["claims"][0]["status"] == "contradicted"
    assert c["cv_review"]["ledger"]["namesakes"] == [] and c["cv_review"]["ledger"]["restricted"]
    assert res["people"][0]["trust"]["score"] == 40  # the stored report is untouched


def test_model_without_v3_fields_still_works(tmp_path):
    """An older / smaller model that ignores the new fields: no current-role lens, claims still checked by code."""
    base = fake_people_llm()
    orig = base.handlers[pa.PersonAnalysis]

    def plain(s, u):
        a = orig(s, u)
        a.role_fit, a.claim_checks, a.role_relevance = None, [], []
        return a
    llm = FakeLLM({**base.handlers, pa.PersonAnalysis: plain})
    res = pa.analyse({"id": "t_v3p", "mode": "person", "name": "Jane Nguyen"}, [{**JANE, "cv": CV}],
                     deps_for(tmp_path, llm=llm))
    card = res["people"][0]
    assert "current_role" not in card["fits"] and card["cv_review"]["ledger"]["claims"]
    assert card["decision"] is None or card["decision"]["fit_lens"] in ("business", "jd")


# ================================================================== API (throwaway Postgres; skipped without it)
from test_hr_api import hr_runner, login  # noqa: E402
from test_studio import USER_KEY, needs_db, studio_env  # noqa: E402,F401 (fixture)


@needs_db
def test_jd_parse_endpoint_flags_protected_wording_and_caches(studio_env):
    env = studio_env
    u = login(env, USER_KEY)
    ctx = u.app.state.studio
    ctx.suggest_llm = FakeLLM({hf.JDParse: lambda s, t: hf.JDParse(
        title="Head of Supply Chain", seniority="lead", min_years=6,
        must=["Agri-food supply chain expertise", "Young and energetic"], nice=["Male preferred", "Mandarin"],
        knockouts=["Australian work rights"], skills=["SAP"])})
    assert u.post("/v1/hr/jd/parse", json={"text": "too short"}).status_code == 422
    jd = "We are hiring a Head of Supply Chain. " * 5 + "Contact hr@acme.example"
    r = u.post("/v1/hr/jd/parse", json={"text": jd})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["must"] == ["Agri-food supply chain expertise"] and got["nice"] == ["Mandarin"]
    assert {f["text"] for f in got["flagged"]} == {"Young and energetic", "Male preferred"}
    assert got["min_years"] == 6 and got["knockouts"] == ["Australian work rights"]
    assert u.post("/v1/hr/jd/parse", json={"text": jd}).json()["cached"] is True
    assert len(ctx.suggest_llm.calls) == 1
    assert env["client"]().post("/v1/hr/jd/parse", json={"text": jd}).status_code == 401


@needs_db
def test_role_target_v3_fields_and_share_view_restrictions(studio_env):
    env = studio_env
    u = login(env, USER_KEY)
    anon = env["client"]()
    role = {"type": "role", "company": "Acme", "title": "Head of Supply Chain", "description": "Lead ops",
            "requirements": ["agri-food supply chain expertise", "enterprise sales", "Under 35"],
            "min_years": 5, "seniority": "lead", "knockouts": ["enterprise sales"]}
    person = {"full_name": "Jane Nguyen", "role": "CEO", "kind": "founder", "urls": ["https://agritrace.example/team"],
              "cv": CV}
    r = u.post("/v1/hr/people-reports", json={"person": person, "target": role, "consent": True})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["target"]["requirements"] == ["agri-food supply chain expertise", "enterprise sales"]
    assert rep["target"]["flagged"][0]["text"] == "Under 35" and rep["target"]["min_years"] == 5
    assert hr_runner(env).drain() == 1
    done = u.get(f"/v1/hr/people-reports/{rep['id']}").json()
    card = done["result"]["people"][0]
    assert done["result"]["version"] == "hr-2" and card["trust"]["score"] is not None
    assert card["fits"]["jd"]["relevant"]["min_years"] == 5 and card["decision"]["fit_lens"] == "jd"
    assert "Under 35" not in json.dumps(card["fit"]["requirements"])
    sm = u.get(f"/v1/hr/teams/{rep['id']}/summary").json()
    assert sm["people"][0]["trust_band"] == card["trust"]["band"]
    assert sm["people"][0]["role_fit_verdict"] == card["fits"]["current_role"]["verdict"]
    tok = u.post(f"/v1/hr/teams/{rep['id']}/share").json()["share_token"]
    shared = anon.get(f"/v1/hr/people-reports/{rep['id']}", params={"share": tok}).json()["result"]["people"][0]
    assert shared["trust"]["score"] is None and shared["trust"]["band"] == card["trust"]["band"]
    lg = shared["cv_review"]["ledger"]
    assert lg["restricted"] and lg["namesakes"] == [] and all(c["conflict"] is None for c in lg["claims"])
