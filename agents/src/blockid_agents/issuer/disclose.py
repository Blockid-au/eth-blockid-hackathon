"""Issuer job for business updates (studio/updates.py): record an approved update's content hash on BlockID Chain.

Only a row a platform admin approved (status 'publishing', content_hash set by the API) is executed. The issuer
recomputes the hash from the row itself and refuses if it differs (the text changed after approval). The record is
a 0-value transaction from the issuer to itself on BlockID Chain (gas price 0) with calldata
0x424944550000 ("BIDU" + version 0) + the 32-byte sha256 content hash: no contract, no state overwritten, and the
explorer shows it at scan.blockid.au/tx/<hash>. A retried row that already has a transaction is not re-sent.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from psycopg.types.json import Jsonb

from ..studio import update_draft as ud

log = logging.getLogger(__name__)

LOCAL = "blockid"


def disclose(svc, update_id: str) -> None:
    with svc._exclusive(f"update:{update_id}") as ok:
        if ok:
            _disclose(svc, update_id)


def _fail(st, update_id: str, company_id: int | None, err: str) -> None:
    st._exec("UPDATE studio.updates SET status='failed', error=%s, updated_at=now() WHERE id=%s AND status='publishing'",
             (err[:1000], update_id))
    st._exec("INSERT INTO studio.audit (actor, action, target, detail) VALUES ('issuer','update_publish_failed',%s,%s)",
             (update_id, Jsonb({"company_id": company_id, "error": err[:300]})))


def _disclose(svc, update_id: str) -> None:
    st = svc.store
    u = st._one("SELECT * FROM studio.updates WHERE id=%s", (update_id,))
    if not u or u["status"] != "publishing" or not u.get("content_hash"):
        log.warning("update %s is not approved for publishing; skipped", update_id)
        return
    c = st.company(u["company_id"])
    try:
        if not c:
            raise RuntimeError("unknown company")
        h = ud.content_hash(u, c)
        if h != u["content_hash"]:
            raise RuntimeError("the update changed after it was approved; approve it again")
        anchor = u.get("anchor") or {}
        if isinstance(anchor, str):
            anchor = json.loads(anchor)
        if anchor.get("tx_hash") and anchor.get("content_hash") == h:
            tx, block = anchor["tx_hash"], anchor.get("block")
            log.warning("update %s already recorded in %s; not re-sent", update_id, tx)
        else:
            L = svc.local
            rec = L.send({"to": L.address, "data": ud.disclosure_calldata(h), "value": 0})
            tx, block = rec.tx_hash, rec.block
        anchor = {"chain": LOCAL, "chain_id": svc.local.chain_id, "tx_hash": tx, "block": block,
                  "to": svc.local.address, "content_hash": h}
        st._exec("UPDATE studio.updates SET status='published', anchor=%s, published_at=%s, error=NULL, "
                 "updated_at=now() WHERE id=%s AND status='publishing'",
                 (Jsonb(anchor), datetime.now(UTC), update_id))
        st.add_event(c["id"], "update_published", LOCAL, tx, block,
                     {"update_id": update_id, "title": u.get("title"), "cadence": u["cadence"],
                      "period_end": u["period_end"].isoformat(), "content_hash": h, "approved_by": u.get("approved_by")})
        st._exec("INSERT INTO studio.audit (actor, action, target, detail) VALUES ('issuer','update_published',%s,%s)",
                 (c["ticker"], Jsonb({"company_id": c["id"], "update_id": update_id, "content_hash": h,
                                      "tx_hash": tx, "block": block})))
    except Exception as e:  # noqa: BLE001
        log.exception("disclose %s failed", update_id)
        _fail(st, update_id, u["company_id"], f"{type(e).__name__}: {e}")
