"""Evaluation v5 Studio API (studio/evaluation.py) against a throwaway Postgres (TEST_DATABASE_URL)."""
import hashlib

import pytest
from test_studio import ADMIN_KEY, USER_KEY, needs_db, siwe_login, studio_env  # noqa: F401 - fixture

from blockid_agents.schemas import DeckFacts, MetricClaim

SHA = hashlib.sha256(b"file").hexdigest()
CSV = ("month,mrr_aud,expansion_mrr,contraction_mrr,churned_mrr,customers,cash_aud,burn_aud\n"
       + "\n".join(f"2025-{m:02d},{10000 + 1000 * m},100,50,100,{40 + m},{900000 - 40000 * m},40000"
                    for m in range(1, 13)) + "\n2026-01,23000,100,50,100,53,380000,40000\n")


@pytest.fixture
def v5(monkeypatch):
    monkeypatch.setenv("VALUATION_V5", "1")
    monkeypatch.setenv("LOOKUPS_OFFLINE", "1")


def _valuation(env, metrics=None):
    u = env["client"]()
    siwe_login(u, USER_KEY)
    r = u.post("/v1/studio/valuations", json={"url": "agritrace.example", "metrics": metrics or {}})
    assert r.status_code == 202, r.text
    vid = r.json()["id"]
    env["runner"].drain()
    v = u.get(f"/v1/studio/valuations/{vid}").json()
    assert v["status"] == "waiting_approval", v["error"]
    return u, vid, v


@needs_db
def test_flag_off_keeps_v4_and_hides_endpoints(studio_env, monkeypatch):
    monkeypatch.setenv("VALUATION_V5", "0")  # the flag-off contract, in both suite runs
    from blockid_agents.graph import build_site_valuation

    runner = studio_env["runner"]  # the worker builds its graph at start-up: rebuild it with the flag off
    runner.graph = build_site_valuation(runner.deps, runner.graph.checkpointer, runner.progress)
    u = studio_env["client"]()
    assert u.get("/v1/studio/evaluation/config").json()["enabled"] is False
    siwe_login(u, USER_KEY)
    r = u.post("/v1/studio/valuations", json={"url": "agritrace.example", "metrics": {"arr_aud": 5}})
    assert r.status_code == 422 and "evaluation v5" in r.text
    vid = u.post("/v1/studio/valuations", json={"url": "agritrace.example"}).json()["id"]
    studio_env["runner"].drain()
    assert u.post(f"/v1/studio/valuations/{vid}/rescore").status_code == 404
    assert "analysis" not in u.get(f"/v1/studio/valuations/{vid}").json()["svi"]


@needs_db
def test_metrics_documents_rescore_verify_and_lock(v5, studio_env):
    env = studio_env
    runner = env["runner"]
    runner.deps.llm.handlers[DeckFacts] = lambda s, u: DeckFacts(claims=[
        MetricClaim(metric="arr", value=300_000, unit="AUD", source_url="x", quote="ARR A$300k"),
        MetricClaim(metric="lois", value=12, unit="count", source_url="x", quote="twelve LOIs")])
    cfg = env["client"]().get("/v1/studio/evaluation/config").json()
    assert cfg["enabled"] and cfg["weights_by_stage"]["seed"]["founder_quality"] == 0.3
    assert {"key": "nrr_pct", "group": "retention", "unit": "%", "min_stage": "seed"} in cfg["fields"]
    u, vid, v = _valuation(env, {"revenue_ttm_aud": 480_000, "customers": 23, "last_round_type": "Seed",
                                 "last_round_date": "2026-03"})
    s = v["svi"]
    assert s["weights_profile"] == "v5:seed" and s["analysis"]["stage"]["basis"] == "round"
    assert u.post("/v1/studio/evaluation/stage-preview", json={"metrics": {"arr_aud": 3e6}}).json()["stage"] \
        == "series-a"

    other = env["client"]()
    siwe_login(other, ADMIN_KEY.replace("a1", "c3"))
    assert other.post(f"/v1/studio/valuations/{vid}/rescore").status_code == 403

    # typed numbers -> deterministic re-score, no web search
    audit_before = len(env["runner"].deps.audit.path.read_text().splitlines()) if hasattr(
        env["runner"].deps.audit, "path") else 0
    r = u.put(f"/v1/studio/valuations/{vid}/metrics",
              json={"metrics": {"revenue_ttm_aud": 480_000, "customers": 23, "nrr_pct": 108, "grr_pct": 90}})
    assert r.status_code == 200, r.text
    ret = r.json()["svi"]["analysis"]["dimensions"]["retention"]
    assert ret["status"] == "scored" and ret["sub_metrics"][0]["value"]["level"] == 1
    if audit_before:
        new = env["runner"].deps.audit.path.read_text().splitlines()[audit_before:]
        assert not any("search_served" in x for x in new)

    # documents: CSV parsed + limits
    bad = u.post(f"/v1/studio/valuations/{vid}/documents",
                 json={"kind": "metrics_csv", "filename": "m.csv", "sha256": SHA, "text": "foo,bar\n1,2"})
    assert bad.status_code == 422
    d = u.post(f"/v1/studio/valuations/{vid}/documents",
               json={"kind": "metrics_csv", "filename": "m.csv", "sha256": SHA, "text": CSV})
    assert d.status_code == 201, d.text
    assert d.json()["parsed"]["metrics"]["arr_aud"] == 276_000
    deck = u.post(f"/v1/studio/valuations/{vid}/documents",
                  json={"kind": "deck", "filename": "deck.pdf", "sha256": SHA,
                        "text": "Slide 2: ARR A$300k. Contact ceo@agritrace.example +61 400 000 000"}).json()
    lst = u.get(f"/v1/studio/valuations/{vid}/documents").json()
    assert len(lst) == 2 and all("text" not in x for x in lst)
    row = env["db"].one("SELECT text FROM studio.valuation_documents WHERE id=%s", (deck["doc_id"],))
    assert "@" not in row["text"] and "[email]" in row["text"]
    for i in range(3):
        u.post(f"/v1/studio/valuations/{vid}/documents",
               json={"kind": "financials", "filename": f"f{i}.pdf", "sha256": SHA, "text": "P&L"})
    assert u.post(f"/v1/studio/valuations/{vid}/documents",
                  json={"kind": "financials", "filename": "x.pdf", "sha256": SHA, "text": "P&L"}).status_code == 409

    r = u.post(f"/v1/studio/valuations/{vid}/rescore")
    assert r.status_code == 200, r.text
    an = r.json()["svi"]["analysis"]
    assert an["metrics"]["nrr_pct"]["source"] in ("csv", "self_reported")
    assert an["metrics"]["arr_aud"]["level"] == 2  # computed from the uploaded CSV
    deck_claims = [c for c in an["claims"] if c["source_url"] == f"doc:{deck['doc_id']}"]
    assert [c["metric"] for c in deck_claims] == ["arr"]  # 'twelve LOIs' is not in the deck text
    assert any(f["code"] == "cross_source_gap" for f in an["flags"])  # typed 480k vs CSV / deck

    # admin marks a metric verified (L3)
    a = env["client"]()
    siwe_login(a, ADMIN_KEY)
    assert u.post(f"/v1/studio/valuations/{vid}/metrics/verify",
                  json={"metric": "paying_customers", "level": 3}).status_code == 403
    r = a.post(f"/v1/studio/valuations/{vid}/metrics/verify", json={"metric": "paying_customers", "level": 3,
                                                                      "note": "checked invoices"})
    assert r.status_code == 200, r.text
    assert r.json()["svi"]["analysis"]["metrics"]["paying_customers"]["level"] == 3

    # delete a document; lock once a company exists
    assert u.delete(f"/v1/studio/valuations/{vid}/documents/{deck['doc_id']}").json() == {"deleted": True}
    env["db"].exec("INSERT INTO studio.companies (ticker, name, valuation_id, valuation_aud, total_shares, status) "
                   "VALUES ('AGT','AgriTrace',%s,1000000,1000000,'draft')", (vid,))
    assert u.post(f"/v1/studio/valuations/{vid}/rescore").status_code == 409
    assert u.put(f"/v1/studio/valuations/{vid}/metrics", json={"metrics": {"customers": 99}}).status_code == 409


@needs_db
def test_revalue_suggestion_from_published_kpis(v5, studio_env):
    env = studio_env
    u, vid, _ = _valuation(env, {"revenue_ttm_aud": 480_000, "customers": 23})
    db = env["db"]
    cid = db.one("INSERT INTO studio.companies (ticker, name, valuation_id, valuation_aud, total_shares, status) "
                 "VALUES ('AGR','AgriTrace',%s,5000000,5000000,'anchored') RETURNING id", (vid,))["id"]
    a = env["client"]()
    siwe_login(a, ADMIN_KEY)
    assert a.post(f"/v1/admin/companies/{cid}/revalue-suggestion").status_code == 409  # no published KPIs yet
    for q, (start, end, rev) in enumerate([("2025-07-01", "2025-09-30", 150_000), ("2025-10-01", "2025-12-31", 160_000),
                                           ("2026-01-01", "2026-03-31", 200_000), ("2026-04-01", "2026-06-30", 280_000)]):
        db.exec("INSERT INTO studio.updates (id, company_id, cadence, period_start, period_end, status) "
                "VALUES (%s,%s,'quarterly',%s,%s,'published')", (f"u{q}", cid, start, end))
        db.exec("INSERT INTO studio.kpi_values (company_id, period_end, metric, value, cadence) "
                "VALUES (%s,%s,'revenue',%s,'quarterly'), (%s,%s,'customers',%s,'quarterly')",
                (cid, end, rev, cid, end, 30 + q))
    r = a.post(f"/v1/admin/companies/{cid}/revalue-suggestion")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["requires_admin_approval"] and out["kpi_metrics"]["revenue_ttm_aud"]["value"] == 790_000
    assert out["kpi_metrics"]["revenue_ttm_aud"]["level"] == 3 and out["stage"] == "seed"
    assert out["suggested_valuation_aud"] > 0 and out["previous_valuation_aud"] == 5_000_000
    assert db.one("SELECT kind FROM studio.events WHERE company_id=%s AND kind='revaluation_suggested'", (cid,))
    c = db.one("SELECT valuation_aud FROM studio.companies WHERE id=%s", (cid,))
    assert float(c["valuation_aud"]) == 5_000_000  # nothing applied
