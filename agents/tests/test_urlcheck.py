"""Website link check (studio/urlcheck.py, POST /v1/studio/check-url) and the valuation read rule."""
import httpx
import pytest

from blockid_agents.studio import urlcheck
from blockid_agents.studio.urlcheck import CheckFailed, RateLimiter, check_url, normalise
from blockid_agents.tools.safefetch import FetchError, SafeFetcher
from test_studio import ADMIN_KEY, USER_KEY, needs_db, siwe_login, studio_env  # noqa: F401 (fixture)


# ------------------------------------------------------------------ syntax
@pytest.mark.parametrize("raw,want", [
    ("canva.com", "https://canva.com/"),
    ("  HTTPS://WWW.Canva.com/au  ", "https://www.canva.com/au"),
    ("http://shop.example.com.au/path?q=1#x", "http://shop.example.com.au/path"),
    ("airwallex.com.au", "https://airwallex.com.au/"),
])
def test_normalise_adds_scheme_and_lowercases(raw, want):
    assert normalise(raw) == want


@pytest.mark.parametrize("raw,reason", [
    ("", "empty"),
    ("   ", "empty"),
    ("canva .com", "spaces"),
    ("my company.com", "spaces"),
    ("canva", "no_tld"),
    ("canva.c0m", "no_tld"),
    ("canva.c", "no_tld"),
    ("http://127.0.0.1/", "ip"),
    ("https://[::1]/", "ip"),
    ("localhost", "not_public"),
    ("http://localhost:8080", "not_public"),
    ("printer.local", "not_public"),
    ("site.internal", "not_public"),
    ("ftp://canva.com", "bad_url"),
    ("https://user:pw@canva.com", "bad_url"),
    ("https://-bad-.com", "bad_url"),
    ("https://a..com", "bad_url"),
])
def test_normalise_rejects_bad_hosts(raw, reason):
    with pytest.raises(CheckFailed) as e:
        normalise(raw)
    assert e.value.reason == reason


def test_punycode_and_lookalike_hosts_get_a_did_you_mean_hint():
    # "cаnva.com" with a Cyrillic "а", typed in its xn-- form
    puny = "саnva.com".encode("idna").decode()
    assert puny.startswith("xn--")
    for raw in (puny, "https://" + puny + "/about", "саnva.com"):
        with pytest.raises(CheckFailed) as e:
            normalise(raw)
        assert e.value.reason == "lookalike"
        assert e.value.suggestion and e.value.suggestion.startswith("https://canva.com/")
    # accents fold too
    with pytest.raises(CheckFailed) as e:
        normalise("https://" + "cánva.com.au".encode("idna").decode())
    assert e.value.suggestion == "https://canva.com.au/"
    r = check_url(puny, resolve=lambda h: pytest.fail("no DNS for look-alikes"))
    assert r["ok"] is False and r["reason"] == "lookalike" and "Did you mean canva.com?" in r["message"]


# ------------------------------------------------------------------ network (mocked)
def _fetcher(handler):
    return lambda: SafeFetcher(httpx.MockTransport(handler), host_ok=lambda h: True, timeout=2, page_deadline=3)


def test_check_url_ok_follows_redirect_and_reads_title():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "canva.com":
            return httpx.Response(301, headers={"location": "https://www.canva.com/en_au/"})
        return httpx.Response(200, text="<html><head><title> Canva &amp; friends\n</title></head></html>",
                              headers={"content-type": "text/html"})
    r = check_url("canva.com", resolve=lambda h: ["93.184.216.34"], fetcher=_fetcher(handler))
    assert r == {"ok": True, "url": "https://www.canva.com/en_au/", "title": "Canva & friends", "reason": None,
                 "message": None, "suggestion": None}


def test_check_url_dns_failure_and_private_hosts():
    def nx(host):
        raise FetchError(f"host {host!r} does not resolve")

    def private(host):
        raise FetchError(f"host {host!r} is not a public internet host")
    r = check_url("canvaa-nope.com.au", resolve=nx, fetcher=lambda: pytest.fail("no fetch after DNS failure"))
    assert r["ok"] is False and r["reason"] == "dns" and r["url"] is None and "couldn't find" in r["message"]
    assert check_url("intranet.corp.com", resolve=private)["reason"] == "not_public"


def test_check_url_unreachable_and_http_errors():
    ok_dns = lambda h: ["93.184.216.34"]  # noqa: E731

    def down(req):
        raise httpx.ConnectError("refused")
    assert check_url("down.com.au", resolve=ok_dns, fetcher=_fetcher(down))["reason"] == "unreachable"
    gone = _fetcher(lambda req: httpx.Response(404, text="nope"))
    assert check_url("gone.com.au", resolve=ok_dns, fetcher=gone)["reason"] == "http_error"
    walled = _fetcher(lambda req: httpx.Response(403, text="<title>Just a moment</title>"))
    assert check_url("walled.com.au", resolve=ok_dns, fetcher=walled)["ok"] is True


def test_rate_limiter_window(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(urlcheck.time, "time", lambda: t[0])
    lim = RateLimiter(limit=3, window_s=60)
    assert [lim.allow("1.1.1.1") for _ in range(4)] == [True, True, True, False]
    assert lim.allow("2.2.2.2")
    t[0] += 61
    assert lim.allow("1.1.1.1")


# ------------------------------------------------------------------ API
@needs_db
def test_check_url_endpoint_rate_limit(studio_env):
    c = studio_env["client"]()
    ctx = c.app.state.studio
    seen = []
    ctx.url_checker = lambda u: (seen.append(u), {"ok": True, "url": "https://canva.com/", "title": "Canva",
                                                  "reason": None, "message": None, "suggestion": None})[1]
    ctx.url_limiter = RateLimiter(limit=2, window_s=60)
    h = {"X-Real-IP": "7.7.7.7"}
    assert c.post("/v1/studio/check-url", json={"url": "canva.com"}, headers=h).json()["ok"] is True
    assert c.post("/v1/studio/check-url", json={"url": "canva.com"}, headers=h).status_code == 200
    assert c.post("/v1/studio/check-url", json={"url": "canva.com"}, headers=h).status_code == 429
    assert c.post("/v1/studio/check-url", json={"url": "canva.com"}, headers={"X-Real-IP": "6.6.6.6"}).status_code == 200
    assert seen == ["canva.com"] * 3
    # the real checker, syntax-only failure: no network touched
    ctx.url_checker = check_url
    r = c.post("/v1/studio/check-url", json={"url": "http://10.0.0.1"}, headers={"X-Real-IP": "5.5.5.5"}).json()
    assert r["ok"] is False and r["reason"] == "ip"


@needs_db
def test_valuation_readable_once_linked_to_a_listed_business(studio_env):
    db = studio_env["db"]
    owner, other, admin = studio_env["client"](), studio_env["client"](), studio_env["client"]()
    siwe_login(owner, USER_KEY)
    siwe_login(other, "0x" + "c3" * 32)
    siwe_login(admin, ADMIN_KEY)
    from test_studio import USER
    db.exec("INSERT INTO studio.valuations(id,url,status,requested_by) VALUES "
            "('vpub','https://a.example','approved',%s), ('vdraft','https://b.example','approved',%s)", (USER, USER))
    cid = db.one("INSERT INTO studio.companies(ticker,name,valuation_aud,total_shares,status,valuation_id) "
                 "VALUES ('PUB','Pub',100,100,'draft','vpub') RETURNING id")["id"]
    anon = studio_env["client"]()
    assert anon.get("/v1/studio/valuations/vpub").status_code == 401
    # draft company: still requester / admin only
    assert other.get("/v1/studio/valuations/vpub").status_code == 403
    assert owner.get("/v1/studio/valuations/vpub").status_code == 200
    assert admin.get("/v1/studio/valuations/vpub").status_code == 200
    for st in ("pending_issue", "issuing"):
        db.exec("UPDATE studio.companies SET status=%s WHERE id=%s", (st, cid))
        assert other.get("/v1/studio/valuations/vpub").status_code == 403
    # listed (on-chain): any signed-in viewer can read the report and its sources
    for st in ("issued", "anchored", "partially_anchored"):
        db.exec("UPDATE studio.companies SET status=%s WHERE id=%s", (st, cid))
        assert other.get("/v1/studio/valuations/vpub").status_code == 200
        assert other.get("/v1/studio/valuations/vpub/evidence").status_code == 200
    # ...but not the unlinked one, nor the list of someone else's valuations, nor the decision
    assert other.get("/v1/studio/valuations/vdraft").status_code == 403
    assert "vpub" not in {v["id"] for v in other.get("/v1/studio/valuations").json()}
    assert other.post("/v1/studio/valuations/vpub/decision", json={"approved": True}).status_code == 403
