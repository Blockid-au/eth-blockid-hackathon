"""Accounts for people who sign in without MetaMask.

* Guest ("Try it now"): the browser creates a secp256k1 key, keeps it locally and signs a normal SIWE message.
  The server only ever sees the address and the signature.
* Google: the browser gets a Google ID token (Google Identity Services) and signs a SIWE message with the key it
  holds for that Google account. The API verifies both and links google:<sub> <-> address in studio.accounts.

Keys never reach the server, so neither path changes the rule that only the issuer signs transactions server-side.
Device-key sessions are always role "user", never "admin".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


class GoogleError(Exception):
    pass


@dataclass
class GoogleIdentity:
    sub: str
    email: str | None
    name: str | None
    picture: str | None


def verify_google(credential: str, client_id: str, verifier=None) -> GoogleIdentity:
    """Verify a Google ID token (signature against Google's certs, audience, issuer, expiry, verified email)."""
    if not client_id:
        raise GoogleError("Google sign-in is not configured")
    if verifier is None:
        from google.auth.transport import requests as ga_requests
        from google.oauth2 import id_token

        def verifier(tok: str, aud: str) -> dict:
            return id_token.verify_oauth2_token(tok, ga_requests.Request(), aud, clock_skew_in_seconds=10)
    try:
        info = verifier(credential, client_id)
    except Exception as e:  # noqa: BLE001 - any failure is a bad token
        raise GoogleError(f"invalid Google token: {e}") from None
    if info.get("iss") not in GOOGLE_ISSUERS:
        raise GoogleError("invalid Google token issuer")
    if info.get("aud") != client_id:
        raise GoogleError("Google token was issued for another app")
    if info.get("email") and not info.get("email_verified", False):
        raise GoogleError("Google email is not verified")
    if not info.get("sub"):
        raise GoogleError("Google token has no subject")
    return GoogleIdentity(sub=str(info["sub"]), email=info.get("email"), name=info.get("name"),
                          picture=info.get("picture"))


def link_google(db, ident: GoogleIdentity, address: str) -> tuple[int, bool]:
    """Upsert the account and link the wallet. Returns (account_id, first_time_for_this_account)."""
    row = db.one(
        "INSERT INTO studio.accounts(provider, subject, email, name, picture, last_login_at) "
        "VALUES ('google', %s, %s, %s, %s, now()) "
        "ON CONFLICT (provider, subject) DO UPDATE SET email=EXCLUDED.email, name=EXCLUDED.name, "
        "picture=EXCLUDED.picture, last_login_at=now() RETURNING id, (xmax = 0) AS inserted",
        (ident.sub, ident.email, ident.name, ident.picture),
    )
    acc = int(row["id"])
    db.exec(
        "INSERT INTO studio.account_wallets(account_id, address, kind) VALUES (%s, %s, 'device') "
        "ON CONFLICT (account_id, address) DO NOTHING", (acc, address))
    return acc, bool(row["inserted"])


def account_view(db, account_id: int | None) -> dict | None:
    if not account_id:
        return None
    a = db.one("SELECT id, provider, email, name, picture FROM studio.accounts WHERE id=%s", (account_id,))
    if not a:
        return None
    ws = db.all("SELECT address FROM studio.account_wallets WHERE account_id=%s ORDER BY linked_at", (account_id,))
    return {"provider": a["provider"], "email": a["email"], "name": a["name"], "picture": a["picture"],
            "wallets": [w["address"] for w in ws]}


def account_wallets(db, account_id: int | None, address: str | None) -> list[str]:
    out = [address] if address else []
    if account_id:
        for w in db.all("SELECT address FROM studio.account_wallets WHERE account_id=%s", (account_id,)):
            if w["address"].lower() not in {x.lower() for x in out}:
                out.append(w["address"])
    return out
