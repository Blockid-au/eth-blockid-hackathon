"""Default BLKD gas allowance on BlockID EVM for every new wallet (so users never lack gas).

Triggered (in the background, never blocking the response) on a SIWE sign-in, and when a wallet is added as a
holder, mint recipient or company admin. Each wallet is funded at most once per 24 h (studio.gas_drips, one row per
wallet) and at most GAS_DRIP_DAILY_MAX distinct wallets per 24 h platform-wide. The issuer tops the wallet up to the
allowance (POST /drip {wallet, amount_wei}; it sends nothing when the balance is already there, cap 5 BLKD).

Env: GAS_DRIP_BLKD (default 1, max 5; 0 disables), GAS_DRIP_DAILY_MAX (default 200).
Failures are logged and ignored; a failed issuer call releases the reservation so the next sign-in retries.
"""
from __future__ import annotations

import logging
import os
from decimal import Decimal, InvalidOperation

from eth_utils import is_address, to_checksum_address

log = logging.getLogger(__name__)

MAX_WEI = 5 * 10**18


def allowance_wei() -> int:
    try:
        v = Decimal(os.environ.get("GAS_DRIP_BLKD", "1") or "0")
    except InvalidOperation:
        v = Decimal(1)
    return max(0, min(int(v * 10**18), MAX_WEI))


def daily_max() -> int:
    try:
        return max(0, int(os.environ.get("GAS_DRIP_DAILY_MAX", "200")))
    except ValueError:
        return 200


class GasDripper:
    def __init__(self, ctx):
        self.ctx = ctx

    def reserve(self, address: str, reason: str) -> int | None:
        """Atomically claim today's drip for this wallet; returns amount_wei, or None (recent / cap / disabled)."""
        amount = allowance_wei()
        if amount <= 0 or not is_address(address):
            return None
        addr = to_checksum_address(address)
        db = self.ctx.need_db()
        with db.tx() as c:
            c.execute("SELECT pg_advisory_xact_lock(hashtext('studio.gas_drips'))")
            row = c.execute("SELECT created_at > now() - interval '24 hours' AS recent FROM studio.gas_drips "
                            "WHERE lower(address)=lower(%s)", (addr,)).fetchone()
            if row and row["recent"]:
                return None
            n = c.execute("SELECT count(*) AS n FROM studio.gas_drips WHERE created_at > now() - interval '24 hours'"
                          ).fetchone()["n"]
            if n >= daily_max():
                log.warning("gas drip daily cap (%s wallets) reached; %s not funded", daily_max(), addr)
                return None
            c.execute("INSERT INTO studio.gas_drips (address, amount_wei, reason) VALUES (%s,%s,%s) "
                      "ON CONFLICT (address) DO UPDATE SET amount_wei=EXCLUDED.amount_wei, reason=EXCLUDED.reason, "
                      "tx_hash=NULL, created_at=now()", (addr, amount, reason[:40]))
        return amount

    def drip(self, address: str, reason: str = "login", company_id: int | None = None) -> bool:
        """Reserve + ask the issuer. Never raises. True when the issuer accepted the job."""
        try:
            amount = self.reserve(address, reason)
            if amount is None:
                return False
            addr = to_checksum_address(address)
            try:
                body = {"wallet": addr, "amount_wei": amount}
                if company_id is not None:
                    body["company_id"] = company_id
                self.ctx.need_issuer().post("/drip", body)
                return True
            except Exception as e:  # noqa: BLE001 - issuer down: release the reservation
                log.warning("gas drip to %s failed: %s", addr, getattr(e, "detail", e))
                self.ctx.need_db().exec("DELETE FROM studio.gas_drips WHERE address=%s AND tx_hash IS NULL", (addr,))
                return False
        except Exception:
            log.exception("gas drip to %s failed", address)
            return False

    def drip_many(self, addresses: list[str], reason: str, company_id: int | None = None) -> None:
        seen: set[str] = set()
        for a in addresses:
            if a and a.lower() not in seen:
                seen.add(a.lower())
                self.drip(a, reason, company_id)
