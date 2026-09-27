"""Share code check before the shareholder step (GET /v1/studio/tickers/check) and the create-time guard."""
from blockid_agents.tools import ticker
from test_studio import USER_KEY, needs_db, siwe_login, studio_env  # noqa: F401


@needs_db
def test_ticker_check(studio_env):
    db, c = studio_env["db"], studio_env["client"]()
    assert c.get("/v1/studio/tickers/check?ticker=ABC").status_code == 401  # signed-in users only
    siwe_login(c, USER_KEY)
    db.ensure_schema()
    db.exec("INSERT INTO studio.companies(ticker,name,valuation_aud,total_shares,status) "
            "VALUES ('CNV','Canva',1,1,'anchored')")
    r = c.get("/v1/studio/tickers/check?ticker=cnv&name=Canva").json()
    assert r["ok"] is False and r["reason"] == "taken" and r["ticker"] == "CNV"
    assert r["suggestions"] and "CNV" not in r["suggestions"]
    bad = sorted(ticker.BLOCKLIST)[0]
    assert c.get(f"/v1/studio/tickers/check?ticker={bad}").json()["reason"] == "reserved"
    for x in ("AB", "AB1", "ABCD", ""):
        assert c.get(f"/v1/studio/tickers/check?ticker={x}").json()["reason"] == "format"
    ok = c.get("/v1/studio/tickers/check?ticker=QZX").json()
    assert ok == {"ticker": "QZX", "ok": True, "reason": None, "suggestions": []}
