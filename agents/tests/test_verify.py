"""Public verifier: canonical report JSON stability, keccak hash, deterministic SVI recompute, endpoints (offline)."""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from blockid_agents.studio import verify
from blockid_agents.studio.report_hash import canonical_json, canonical_report, report_hash
from blockid_agents.tools import svi as svi_tools

DIMS = {"founder_quality": 70, "product_strength": 60, "market_attractiveness": 75, "revenue_performance": 55.5,
        "growth_capability": 48.2, "investment_readiness": 40, "trust_verification": 90}


def sample_report(**over) -> dict:
    index = round(sum(svi_tools.WEIGHTS[k] * v for k, v in DIMS.items()), 2)
    f = 0.5 + index / 100
    rev, med = 400_000.0, 6.0
    rep = {
        "url": "https://example.com.au", "self_reported": None,
        "profile": {"company_name": "Ví dụ Pty Ltd", "stage": "seed", "metrics": {"revenue_ttm_aud": rev}},
        "competitors": [{"name": "B", "raised_aud": None}],
        "market": {"revenue_multiple_median": med, "revenue_multiple_low": None, "revenue_multiple_high": 9.0},
        "svi": {"index": index, "band": svi_tools.band(index),
                "dimensions": {k: {"score": v, "basis": "computed"} for k, v in DIMS.items()},
                "weights": dict(svi_tools.WEIGHTS),
                "valuation_low_aud": round(rev * med * 0.6 * f, -3), "valuation_mid_aud": round(rev * med * f, -3),
                "valuation_high_aud": round(rev * 9.0 * f, -3)},
    }
    rep.update(over)
    return rep


def test_canonical_json_sorted_compact_unicode_and_key_order_independent():
    a = {"b": 1, "a": {"z": [1, 2.5, None], "y": "Đông"}}
    b = json.loads(json.dumps({"a": {"y": "Đông", "z": [1, 2.5, None]}, "b": 1}))
    assert canonical_json(a) == canonical_json(b) == '{"a":{"y":"Đông","z":[1,2.5,null]},"b":1}'
    rep = sample_report()
    shuffled = dict(reversed(list(rep.items())))
    assert report_hash(rep) == report_hash(shuffled)
    assert report_hash(rep).startswith("0x") and len(report_hash(rep)) == 66
    # extra (non-report) keys are ignored; missing keys become null
    assert report_hash({**rep, "status": "approved", "steps": [1]}) == report_hash(rep)
    assert canonical_report({"url": "x"}) == {"url": "x", "profile": None, "competitors": None, "market": None,
                                             "svi": None, "self_reported": None}


def test_hash_known_vector_and_tamper():
    # keccak256('{"competitors":null,"market":null,"profile":null,"self_reported":null,"svi":null,"url":"x"}')
    from eth_utils import keccak
    s = '{"competitors":null,"market":null,"profile":null,"self_reported":null,"svi":null,"url":"x"}'
    assert report_hash({"url": "x"}) == "0x" + keccak(s.encode()).hex()
    rep = sample_report()
    t = json.loads(json.dumps(rep))
    t["svi"]["dimensions"]["founder_quality"]["score"] = 71
    assert report_hash(t) != report_hash(rep)


def test_recompute_matches_report_and_is_deterministic():
    rep = sample_report()
    r1, r2 = verify.recompute(rep), verify.recompute(json.loads(canonical_json(rep)))
    assert r1 == r2
    assert r1["index"] == rep["svi"]["index"] and r1["band"] == rep["svi"]["band"]
    assert all(r1["matches_report"].values()), r1["matches_report"]
    assert abs(sum(c["contribution"] for c in r1["contributions"]) - r1["index"]) < 0.01
    # stage fallback when there is no revenue
    pre = sample_report(profile={"stage": "pre-seed", "metrics": {"revenue_ttm_aud": 0}})
    r = verify.recompute(pre)
    f = 0.5 + r["index"] / 100
    assert r["mid"] == round(2_000_000 * f, -3) and not r["matches_report"]["mid"]


def test_recompute_agrees_with_svi_score():
    from blockid_agents.schemas import DimensionScore, MarketAnalysis, Metrics, QualitativeScores, StartupProfile
    q = QualitativeScores(**{k: DimensionScore(score=DIMS[k], basis="human", rationale="r")
                             for k in QualitativeScores.model_fields})
    p = StartupProfile(company_name="X", sector="s", description="d", stage="seed",
                       metrics=Metrics(revenue_ttm_aud=800_000, gross_margin_pct=70, revenue_growth_yoy_pct=90,
                                       runway_months=14))
    m = MarketAnalysis(market_summary="m", revenue_multiple_median=5.0, confidence="medium")
    res = svi_tools.score(p, q, m)
    rep = {"profile": p.model_dump(), "market": m.model_dump(), "svi": res.model_dump()}
    r = verify.recompute(rep)
    assert all(r["matches_report"].values()), (r, res)


def _app():
    app = FastAPI()
    app.include_router(verify.build_verify_router(None))
    return TestClient(app)


def test_hash_endpoint_and_limits():
    c = _app()
    rep = sample_report()
    j = c.post("/v1/verify/hash", json={"report": rep}).json()
    assert j["report_hash"] == report_hash(rep) and all(j["recomputed"]["matches_report"].values())
    assert c.post("/v1/verify/hash", json={"x": 1}).status_code == 422
    assert c.post("/v1/verify/hash", content=b"not json").status_code == 422
    assert c.post("/v1/verify/hash", content=b'{"report":{"url":NaN}}').status_code == 422
    big = {"report": {"url": "x" * (300 * 1024)}}
    assert c.post("/v1/verify/hash", json=big).status_code == 413


def test_onchain_match_and_errors():
    rep = sample_report()
    h = report_hash(rep)
    company = {"local_token": "0x" + "11" * 20, "hoodi_token": "0x" + "22" * 20, "hsk_token": None}

    class S:
        local_rpc_url = "http://local"
        hoodi_rpc_url = "http://hoodi"

    def reader(rpc, token):
        if rpc == "http://hoodi":
            raise RuntimeError("down")
        return h.upper().replace("0X", "0x")

    import os
    os.environ.pop("LOCAL_RPC_URL", None)
    os.environ.pop("HOODI_RPC_URL", None)
    out = verify.onchain(company, h, S(), reader=reader)
    assert [x["chain"] for x in out] == ["blockid", "hoodi"]  # hsk skipped: no token
    assert out[0]["match"] is True and out[0]["explorer_url"].startswith("https://scan.blockid.au/token/")
    assert out[1]["match"] is False and out[1]["error"] == "RPC unavailable"
