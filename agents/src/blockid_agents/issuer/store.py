"""Postgres access for the issuer (schema `studio`, see docs/IMPLEMENTATION.md). One short connection per call."""
from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

_COMPANY_COLS = {
    "status", "error", "total_shares", "local_registry", "local_token", "local_distributor", "local_block",
    "hoodi_registry", "hoodi_token", "hoodi_anchor_tx", "merkle_root", "anchored_block", "anchored_at",
    "hsk_registry", "hsk_token", "hsk_anchor_tx", "hsk_merkle_root", "hsk_block", "hsk_anchored_at", "sync",
    "valuation_report_hash",
}

# idempotent: the API applies schema.sql at start, but the issuer may come up first after a deploy
_MIGRATIONS = [
    "ALTER TABLE studio.companies ADD COLUMN IF NOT EXISTS hsk_registry text",
    "ALTER TABLE studio.companies ADD COLUMN IF NOT EXISTS hsk_token text",
    "ALTER TABLE studio.companies ADD COLUMN IF NOT EXISTS hsk_anchor_tx text",
    "ALTER TABLE studio.companies ADD COLUMN IF NOT EXISTS hsk_merkle_root text",
    "ALTER TABLE studio.companies ADD COLUMN IF NOT EXISTS hsk_block bigint",
    "ALTER TABLE studio.companies ADD COLUMN IF NOT EXISTS hsk_anchored_at timestamptz",
    "ALTER TABLE studio.companies ADD COLUMN IF NOT EXISTS sync jsonb NOT NULL DEFAULT '{}'",
    "ALTER TABLE studio.companies ADD COLUMN IF NOT EXISTS valuation_report_hash text",
    # company admins (studio/company_admins.py, issuer/roles.py) and gas allowances (studio/gas.py); = schema.sql
    "CREATE TABLE IF NOT EXISTS studio.company_admins (id serial PRIMARY KEY, company_id int NOT NULL REFERENCES "
    "studio.companies(id) ON DELETE CASCADE, address text NOT NULL, label text NOT NULL DEFAULT '', role text NOT NULL "
    "DEFAULT 'manager' CHECK (role IN ('owner','manager')), status text NOT NULL DEFAULT 'active' CHECK (status IN "
    "('active','pending_grant','revoked')), onchain boolean NOT NULL DEFAULT false, grant_tx text, revoke_tx text, "
    "error text, added_by text, added_at timestamptz NOT NULL DEFAULT now(), revoked_at timestamptz, "
    "UNIQUE (company_id, address))",
    "CREATE TABLE IF NOT EXISTS studio.gas_drips (address text PRIMARY KEY, amount_wei numeric NOT NULL, tx_hash text, "
    "reason text, created_at timestamptz NOT NULL DEFAULT now())",
]
_ADMIN_COLS = {"status", "onchain", "grant_tx", "revoke_tx", "error"}
_MINT_COLS = {"status", "tx_hash"}
_DIVIDEND_COLS = {"status", "merkle_root", "claims", "round_id", "tx_hash"}


def _j(v: Any) -> Any:
    return Jsonb(v) if isinstance(v, (dict, list)) else v


class Store:
    def __init__(self, dsn: str):
        if not dsn:
            raise RuntimeError("DATABASE_URL is not set")
        self.dsn = dsn

    def migrate(self) -> None:
        """Add the multi-chain columns if the API has not done it yet (never fatal)."""
        try:
            with self._conn() as c:
                if not c.execute("SELECT 1 FROM information_schema.tables WHERE table_schema='studio' "
                                 "AND table_name='companies'").fetchone():
                    return
                for sql in _MIGRATIONS:
                    c.execute(sql)
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).exception("issuer column migration failed (API will apply schema.sql)")

    def _conn(self):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self.dsn, autocommit=True, row_factory=dict_row)

    def _one(self, sql: str, args: tuple = ()) -> dict | None:
        with self._conn() as c:
            return c.execute(sql, args).fetchone()

    def _all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._conn() as c:
            return list(c.execute(sql, args).fetchall())

    def _exec(self, sql: str, args: tuple = ()) -> None:
        with self._conn() as c:
            c.execute(sql, args)

    def _update(self, table: str, allowed: set[str], row_id: int, fields: dict, touch: bool) -> None:
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"cannot update {table}.{sorted(bad)}")
        if not fields:
            return
        sets = [f"{k} = %s" for k in fields] + (["updated_at = now()"] if touch else [])
        self._exec(f"UPDATE {table} SET {', '.join(sets)} WHERE id = %s",
                   (*[_j(v) for v in fields.values()], row_id))

    # ------------------------------------------------------------------ companies / holders
    def company(self, company_id: int) -> dict | None:
        return self._one("SELECT * FROM studio.companies WHERE id = %s", (company_id,))

    def update_company(self, company_id: int, **fields) -> None:
        self._update("studio.companies", _COMPANY_COLS, company_id, fields, touch=True)

    def valuation(self, valuation_id: str) -> dict | None:
        return self._one("SELECT * FROM studio.valuations WHERE id = %s", (valuation_id,))

    def holders(self, company_id: int) -> list[dict]:
        return self._all("SELECT * FROM studio.holders WHERE company_id = %s ORDER BY id", (company_id,))

    def add_holder_shares(self, company_id: int, wallet: str, name: str, shares: int) -> None:
        """Keep studio.holders in sync with the chain after a mint (pct recomputed from shares)."""
        with self._conn() as c, c.transaction():
            row = c.execute("SELECT id FROM studio.holders WHERE company_id = %s AND lower(wallet) = lower(%s) "
                            "ORDER BY id LIMIT 1", (company_id, wallet)).fetchone()
            if row:
                c.execute("UPDATE studio.holders SET shares = shares + %s WHERE id = %s", (shares, row["id"]))
            else:
                c.execute("INSERT INTO studio.holders (company_id, name, wallet, pct, shares) VALUES (%s,%s,%s,0,%s)",
                          (company_id, name, wallet, shares))
            tot = c.execute("SELECT COALESCE(sum(shares),0) AS t FROM studio.holders WHERE company_id = %s",
                            (company_id,)).fetchone()["t"]
            if tot:
                c.execute("UPDATE studio.holders SET pct = round(shares * 100.0 / %s, 2) WHERE company_id = %s",
                          (tot, company_id))
                c.execute("UPDATE studio.companies SET total_shares = %s, updated_at = now() WHERE id = %s",
                          (tot, company_id))

    def reconcile_holders(self, company_id: int, balances: dict[str, int]) -> dict[str, int]:
        """Make studio.holders equal to the chain: one row per wallet with a positive balance.
        New wallets (secondary transfers) are named from the transfer / KYC request that brought them in.
        Returns counts of what changed ({} when already in sync)."""
        bal = {w.lower(): (w, int(n)) for w, n in balances.items() if int(n) > 0}
        added = updated = removed = 0
        with self._conn() as c, c.transaction():
            rows = c.execute("SELECT id, wallet, shares FROM studio.holders WHERE company_id = %s ORDER BY id",
                             (company_id,)).fetchall()
            seen: set[str] = set()
            for r in rows:
                w = r["wallet"].lower()
                if w in seen or w not in bal:  # duplicate row, or the wallet no longer holds shares
                    c.execute("DELETE FROM studio.holders WHERE id = %s", (r["id"],))
                    removed += 1
                    continue
                seen.add(w)
                if int(r["shares"]) != bal[w][1]:
                    c.execute("UPDATE studio.holders SET shares = %s WHERE id = %s", (bal[w][1], r["id"]))
                    updated += 1
            for w, (addr, n) in bal.items():
                if w in seen:
                    continue
                name = c.execute(
                    "SELECT name FROM (SELECT to_name AS name, id FROM studio.transfers WHERE company_id = %s "
                    "AND lower(to_wallet) = %s AND coalesce(to_name,'') <> '' ORDER BY id DESC LIMIT 1) t "
                    "UNION ALL SELECT name FROM (SELECT name, id FROM studio.kyc_requests WHERE company_id = %s "
                    "AND lower(wallet) = %s ORDER BY id DESC LIMIT 1) k LIMIT 1",
                    (company_id, w, company_id, w)).fetchone()
                c.execute("INSERT INTO studio.holders (company_id, name, wallet, pct, shares) VALUES (%s,%s,%s,0,%s)",
                          (company_id, (name or {}).get("name") or "Unlabelled holder", addr, n))
                added += 1
            if added or updated or removed:
                tot = sum(n for _, n in bal.values())
                if tot:
                    c.execute("UPDATE studio.holders SET pct = round(shares * 100.0 / %s, 2) WHERE company_id = %s",
                              (tot, company_id))
                    c.execute("UPDATE studio.companies SET total_shares = %s, updated_at = now() WHERE id = %s",
                              (tot, company_id))
        return {k: v for k, v in (("added", added), ("updated", updated), ("removed", removed)) if v}

    # ------------------------------------------------------------------ events / marks
    def add_event(self, company_id: int | None, kind: str, chain: str | None = None, tx_hash: str | None = None,
                  block: int | None = None, data: dict | None = None) -> None:
        self._exec("INSERT INTO studio.events (company_id, kind, chain, tx_hash, block, data) VALUES (%s,%s,%s,%s,%s,%s)",
                   (company_id, kind, chain, tx_hash, block, Jsonb(data or {})))

    def add_mark(self, company_id: int, valuation_aud, mark_aud, source: str, ref: str | None = None) -> None:
        self._exec("INSERT INTO studio.marks (company_id, valuation_aud, mark_aud, source, ref) VALUES (%s,%s,%s,%s,%s)",
                   (company_id, valuation_aud, mark_aud, source, ref))

    def latest_mark(self, company_id: int) -> dict | None:
        return self._one("SELECT * FROM studio.marks WHERE company_id = %s ORDER BY at DESC, id DESC LIMIT 1",
                         (company_id,))

    # ------------------------------------------------------------------ mints / dividends
    def mint(self, mint_id: int) -> dict | None:
        return self._one("SELECT * FROM studio.mints WHERE id = %s", (mint_id,))

    def claim_mint(self, mint_id: int) -> dict | None:
        """Atomically take an admin-approved mint (approved -> minting). None if not approved / already taken."""
        return self._one("UPDATE studio.mints SET status = 'minting' WHERE id = %s AND status = 'approved' "
                         "RETURNING *", (mint_id,))

    def claim_dividend(self, dividend_id: int) -> dict | None:
        """Atomically take an admin-approved dividend (approved -> paying)."""
        return self._one("UPDATE studio.dividends SET status = 'paying' WHERE id = %s AND status = 'approved' "
                         "RETURNING *", (dividend_id,))

    def update_mint(self, mint_id: int, **fields) -> None:
        self._update("studio.mints", _MINT_COLS, mint_id, fields, touch=False)

    def dividend(self, dividend_id: int) -> dict | None:
        return self._one("SELECT * FROM studio.dividends WHERE id = %s", (dividend_id,))

    def update_dividend(self, dividend_id: int, **fields) -> None:
        self._update("studio.dividends", _DIVIDEND_COLS, dividend_id, fields, touch=False)

    # ------------------------------------------------------------------ share offerings (studio/offerings.py)
    def offering(self, offering_id: int) -> dict | None:
        return self._one("SELECT * FROM studio.offerings WHERE id = %s", (offering_id,))

    def offering_mints(self, offering_id: int) -> list[dict]:
        return self._all("SELECT * FROM studio.mints WHERE offering_id = %s ORDER BY id", (offering_id,))

    def fail_offering(self, offering_id: int, error: str) -> None:
        """Settlement failed: unfinished allocations -> failed (approving the settlement again retries them)."""
        with self._conn() as c, c.transaction():
            c.execute("UPDATE studio.mints SET status = 'failed' WHERE offering_id = %s AND status IN "
                      "('approved', 'minting')", (offering_id,))
            c.execute("UPDATE studio.offerings SET status = 'failed', error = %s, updated_at = now() "
                      "WHERE id = %s AND status = 'settling'", (error[:1000], offering_id))

    def finish_offering(self, offering_id: int) -> None:
        """Every allocation minted: reservations -> allocated (with their mint), offering -> settled."""
        with self._conn() as c, c.transaction():
            c.execute("UPDATE studio.reservations r SET status = 'allocated', mint_id = m.id, updated_at = now() "
                      "FROM studio.mints m WHERE r.offering_id = %s AND r.status = 'reserved' "
                      "AND m.offering_id = r.offering_id AND lower(m.to_wallet) = lower(r.wallet) "
                      "AND m.status = 'minted'", (offering_id,))
            c.execute("UPDATE studio.offerings SET status = 'settled', settled_at = now(), error = NULL, "
                      "updated_at = now() WHERE id = %s AND status = 'settling'", (offering_id,))

    # ------------------------------------------------------------------ company admins (issuer/roles.py)
    def company_admin(self, company_id: int, address: str) -> dict | None:
        return self._one("SELECT * FROM studio.company_admins WHERE company_id = %s AND lower(address) = lower(%s)",
                         (company_id, address))

    def update_company_admin(self, admin_id: int, **fields) -> None:
        self._update("studio.company_admins", _ADMIN_COLS, admin_id, fields, touch=False)

    # ------------------------------------------------------------------ gas allowances (studio/gas.py)
    def record_drip(self, address: str, tx_hash: str, amount_wei: int) -> None:
        self._exec("UPDATE studio.gas_drips SET tx_hash = %s, amount_wei = %s WHERE lower(address) = lower(%s)",
                   (tx_hash, amount_wei, address))
