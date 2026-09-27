"""CV review (agents/cv_review.py): code-only stats and timeline maths, parts pushed live, claims checked against
verified facts, and a failing model never failing the report."""
from blockid_agents.agents import cv_review as cvr
from blockid_agents.agents import people as pa
from blockid_agents.llm import FakeLLM

from test_people import JANE, deps_for

CV = """Jane Nguyen
Summary
Agri supply-chain founder. jane@agritrace.au
Experience
CEO, AgriTrace (2021 - present)
Head of Sales, FarmLink (03/2016 - 12/2019) https://www.linkedin.com/in/jane
Buyer, Coles 2012 - 2015
Education
MBA, University of Melbourne
Skills
Enterprise sales, supply chain
""" + "Grew revenue three times in four years. " * 20


def test_read_stats_sections_years_links():
    st = cvr.read_stats(pa.redact(CV))
    assert {"summary", "experience", "education", "skills"} <= set(st["sections"])
    assert st["years"] == [2012, 2021] and st["redacted"] == 1
    assert st["links"] == ["https://www.linkedin.com/in/jane"]


def test_timeline_years_gaps_and_tenure():
    roles = [{"org": "A", "start": "2021-01", "end": "2021-12", "kind": "employee"},
             {"org": "B", "start": "2016-03", "end": "2019-12", "kind": "employee"},
             {"org": "C", "start": "Jan 2012", "end": "Dec 2015", "kind": "employee"},
             {"org": "D", "start": "2017", "end": "2018", "kind": "advisor"}]
    t = cvr.timeline(roles)
    assert t["gaps"] == [{"from": "2020-01", "to": "2020-12", "months": 12}]
    assert t["years"] == 8.8 and t["roles"] == 4 and t["overlaps"] == 0  # advisor role overlaps but is not a main job
    assert roles[1]["months"] == 46 and t["short_stints"] == 0


class Rec(pa.Tracker):
    def __init__(self):
        self.parts, self.notes = [], []

    def cv(self, pid, part, data):
        self.parts.append(part)

    def note(self, msg, **kw):
        self.notes.append(msg)


def test_person_report_has_cv_review_and_live_parts(tmp_path):
    tr = Rec()
    res = pa.analyse({"id": "t_cv", "mode": "person", "name": "Jane Nguyen"}, [{**JANE, "cv": CV}],
                     deps_for(tmp_path), tracker=tr)
    rv = res["people"][0]["cv_review"]
    assert tr.parts[0] == "read" and {"timeline", "insights"} <= set(tr.parts)
    assert rv["timeline"]["stats"]["gaps"][0]["months"] == 12
    assert [r["org"] for r in rv["timeline"]["roles"]] == ["AgriTrace", "FarmLink", "Coles"]
    claims = {c["org"]: c for c in rv["claims"]}
    assert "x" not in claims  # a claim with a phone number is dropped
    assert claims["FarmLink"]["status"] == "confirmed" and claims["FarmLink"]["fact_ids"]
    assert claims["Coles"]["status"] == "unconfirmed"
    assert any(n.startswith("CV read:") for n in tr.notes)


def test_cv_review_failure_does_not_fail_report(tmp_path):
    base = deps_for(tmp_path).agent_llm["people_analyst"]
    llm = FakeLLM({k: v for k, v in base.handlers.items() if k not in (cvr.CVStructure, cvr.CVInsights)})
    res = pa.analyse({"id": "t_cv2", "mode": "person", "name": "Jane Nguyen"}, [{**JANE, "cv": CV}],
                     deps_for(tmp_path, llm=llm))
    rv = res["people"][0]["cv_review"]
    assert rv["timeline"] is None and rv["insights"] is None and rv["read"]["words"] > 100
    assert res["people"][0]["score"] is not None


def test_short_cv_skips_review(tmp_path):
    res = pa.analyse({"id": "t_cv3", "mode": "person", "name": "Jane Nguyen"}, [{**JANE, "cv": "CEO at AgriTrace"}],
                     deps_for(tmp_path))
    assert "cv_review" not in res["people"][0]
