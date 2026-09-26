"""Postgres access for the issuer (schema `studio`, see docs/IMPLEMENTATION.md). One short connection per call."""
from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

_COMPANY_COLS = {
    "status", "error", "total_shares", "local_registry", "local_token", "local_distributor", "local_block",
    "hoodi_registry", "hoodi_token", "hoodi_anchor_tx", "merkle_root", "anchored_block", "anchored_at",
}
_MINT_COLS = {"status", "tx_hash"}
_DIVIDEND_COLS = {"status", "merkle_root", "claims", "round_id", "tx_hash"}


def _j(v: Any) -> Any:
    return Jsonb(v) if isinstance(v, (dict, list)) else v


class Store:
    def __init__(self, dsn: str):
        if not dsn:
            raise RuntimeError("DATABASE_URL is not set")
        self.dsn = dsn

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
