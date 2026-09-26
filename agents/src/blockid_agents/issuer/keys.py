"""Decrypt Foundry/geth JSON keystores. Secrets are never logged or returned outside a LocalAccount."""
from __future__ import annotations

import json
import os
from pathlib import Path

from eth_account import Account
from eth_account.signers.local import LocalAccount


def password_file(account: str, password_dir: str | Path) -> Path:
    """blockid-deployer -> deployer.password (fallback: blockid-deployer.password)."""
    d = Path(password_dir)
    short = account.removeprefix("blockid-")
    for cand in (d / f"{short}.password", d / f"{account}.password"):
        if cand.is_file():
            return cand
    raise FileNotFoundError(f"no password file for keystore account {account!r} in {d}")


def load_account(account: str, keystore_dir: str | Path | None = None,
                 password_dir: str | Path | None = None) -> LocalAccount:
    kdir = Path(keystore_dir or os.environ.get("KEYSTORE_DIR", "/keys"))
    pdir = Path(password_dir or os.environ.get("KEYSTORE_PASSWORD_DIR") or kdir)
    ks = kdir / account
    if not ks.is_file():
        raise FileNotFoundError(f"keystore not found: {ks}")
    password = password_file(account, pdir).read_text().strip()
    try:
        key = Account.decrypt(json.loads(ks.read_text()), password)
    except ValueError as e:  # wrong password / MAC mismatch; never include the password in the message
        raise ValueError(f"cannot decrypt keystore {account!r}: {type(e).__name__}") from None
    finally:
        password = ""
    return Account.from_key(key)
