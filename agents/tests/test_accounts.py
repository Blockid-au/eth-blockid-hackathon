"""Guest (browser key) and Google sign-in, investor holdings, mail config (accounts.py, mailer.py)."""
import pytest
from eth_account import Account

from blockid_agents.studio import accounts as acct
from blockid_agents.studio.mailer import Mailer, welcome
from test_studio import ADMIN_KEY, USER, USER_KEY, needs_db, sign, siwe_message, studio_env  # noqa: F401

GUEST_KEY = "0x" + "c3" * 32
GUEST = Account.from_key(GUEST_KEY).address


def _nonce_msg(c, key):
    n = c.get("/v1/auth/nonce").json()["nonce"]
    m = siwe_message(Account.from_key(key).address, n)
    return m, sign(m, key)


def test_verify_google_checks_audience_issuer_and_email():
    good = {"iss": "https://accounts.google.com", "aud": "cid", "sub": "123", "email": "a@b.co", "email_verified": True}
    ok = acct.verify_google("tok", "cid", verifier=lambda t, a: good)
    assert ok.sub == "123" and ok.email == "a@b.co"
    for bad in ({**good, "aud": "other"}, {**good, "iss": "evil"}, {**good, "email_verified": False},
                {**good, "sub": ""}):
        with pytest.raises(acct.GoogleError):
            acct.verify_google("tok", "cid", verifier=lambda t, a, b=bad: b)
    with pytest.raises(acct.GoogleError, match="not configured"):
        acct.verify_google("tok", "", verifier=lambda t, a: good)

    def boom(t, a):
        raise ValueError("bad signature")
    with pytest.raises(acct.GoogleError, match="invalid"):
        acct.verify_google("tok", "cid", verifier=boom)


def test_mailer_unconfigured_skips_and_builds_headers(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    m = Mailer()
    assert not m.configured and m.send("x@y.z", "s", "t") is False
    msg = m.build("x@y.z", "Hi", "body")
    assert "info@blockid.au" in msg["From"] and msg["Reply-To"] == "info@blockid.au"
    subj, text, html = welcome("Ana", "0xabc", "vi")
    assert "0xabc" in text and subj.startswith("Chào mừng") and "<p>" in html


@needs_db
def test_guest_and_google_sign_in(studio_env, monkeypatch):
    c = studio_env["client"]()
    assert c.get("/v1/auth/config").json()["open_issue"] in (True, False)
    # guest: browser key, never admin even when the address is on the admin list
    m, sig = _nonce_msg(c, ADMIN_KEY)
    r = c.post("/v1/auth/siwe", json={"message": m, "signature": sig, "method": "guest"})
    assert r.status_code == 200 and r.json()["role"] == "user"
    me = c.get("/v1/auth/me").json()
    assert me["auth_method"] == "guest" and me["role"] == "user"
    assert c.get("/v1/me/holdings").json()["positions"] == []

    # google: token verified + SIWE with the browser key -> account linked
    monkeypatch.setattr(acct, "verify_google", lambda cred, cid: acct.GoogleIdentity("g-1", "a@b.co", "Ana", None))
    g = studio_env["client"]()
    m, sig = _nonce_msg(g, GUEST_KEY)
    r = g.post("/v1/auth/google", json={"credential": "x", "message": m, "signature": sig})
    assert r.status_code == 200 and r.json()["email"] == "a@b.co"
    me = g.get("/v1/auth/me").json()
    assert me["auth_method"] == "google" and me["account"]["wallets"] == [GUEST]
    # replayed SIWE message is refused
    assert g.post("/v1/auth/google", json={"credential": "x", "message": m, "signature": sig}).status_code == 401

    def bad(cred, cid):
        raise acct.GoogleError("invalid Google token")
    monkeypatch.setattr(acct, "verify_google", bad)
    m, sig = _nonce_msg(g, GUEST_KEY)
    assert g.post("/v1/auth/google", json={"credential": "x", "message": m, "signature": sig}).status_code == 401
    assert g.get("/v1/demo/holdings").json()["demo"] is True
