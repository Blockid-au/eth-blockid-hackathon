"""Issuer jobs for secondary transfers (see studio/transfers.py): admin-approved transfer, KYC, transfer mode.

Only 'approved' rows are executed (atomically taken to 'executing'); a retried transfer first looks for a
ForcedTransfer log with the same reason ref, so it is never sent twice. Every job ends with Service.reanchor so
the Hoodi / HSK mirrors and their cap-table roots follow the BlockID Chain register.
"""
from __future__ import annotations

import logging

from web3 import Web3

log = logging.getLogger(__name__)

LOCAL = "blockid"


def _ref(transfer_id: int) -> bytes:
    return Web3.keccak(text=f"studio-transfer:{transfer_id}")


def _landed(token, ref: bytes, from_block: int):
    logs = token.events.ForcedTransfer().get_logs(from_block=max(0, int(from_block or 0)),
                                                   argument_filters={"courtOrReason": ref})
    return logs[-1] if logs else None


def transfer(svc, transfer_id: int) -> None:
    with svc._exclusive(f"transfer:{transfer_id}") as ok:
        if ok:
            _transfer(svc, transfer_id)


def _transfer(svc, transfer_id: int) -> None:
    st = svc.store
    t = st._one("UPDATE studio.transfers SET status='executing' WHERE id=%s AND status='approved' RETURNING *",
                (transfer_id,))
    if not t:
        log.warning("transfer %s is not 'approved'; skipped", transfer_id)
        return
    c = st.company(t["company_id"])
    try:
        if not c or not c.get("local_token") or not c.get("local_registry"):
            raise RuntimeError("company not issued on BlockID Chain")
        L, cid = svc.local, c["id"]
        token = L.contract("BlockIDShareToken", c["local_token"])
        reg = L.contract("IdentityRegistry", c["local_registry"])
        frm, to, n = Web3.to_checksum_address(t["from_wallet"]), Web3.to_checksum_address(t["to_wallet"]), int(t["shares"])
        ref = _ref(transfer_id)
        lg = _landed(token, ref, c.get("local_block") or 0)
        if lg is None:
            if int(token.functions.balanceOf(frm).call()) < n:
                raise RuntimeError("sender no longer holds enough shares")
            svc._kyc(L, reg, to, t.get("to_name") or "transferee", cid)
            rec = L.transact(token.functions.forcedTransfer(frm, to, n, ref))
            tx, block = rec.tx_hash, rec.block
        else:
            tx, block, rec = Web3.to_hex(lg["transactionHash"]), int(lg["blockNumber"]), None
            log.warning("transfer %s already on chain in %s; not re-sent", transfer_id, tx)
        st._exec("UPDATE studio.transfers SET status='done', tx_hash=%s, block=%s WHERE id=%s",
                 (tx.lower(), block, transfer_id))
        svc._event(cid, "transferred", LOCAL, rec, transfer_id=transfer_id, **{"from": frm}, to=to,
                   name=t.get("to_name"), shares=n, mode="approval", tx=tx)
    except Exception as e:  # noqa: BLE001
        log.exception("transfer %s failed", transfer_id)
        st._exec("UPDATE studio.transfers SET status='failed', note=%s WHERE id=%s",
                 (f"issuer: {str(e)[:300]}", transfer_id))
        return
    svc.reanchor(c["id"])


def kyc(svc, kyc_id: int) -> None:
    with svc._exclusive(f"kyc:{kyc_id}") as ok:
        if not ok:
            return
        st = svc.store
        k = st._one("UPDATE studio.kyc_requests SET status='executing' WHERE id=%s AND status='approved' RETURNING *",
                    (kyc_id,))
        if not k:
            log.warning("kyc %s is not 'approved'; skipped", kyc_id)
            return
        try:
            c = st.company(k["company_id"])
            if not c or not c.get("local_registry"):
                raise RuntimeError("company not issued on BlockID Chain")
            reg = svc.local.contract("IdentityRegistry", c["local_registry"])
            rec = svc._kyc(svc.local, reg, k["wallet"], k["name"], c["id"])
            svc._drip_if_needed(k["wallet"], c["id"])  # a little BLKD so MetaMask can send the transfer
            st._exec("UPDATE studio.kyc_requests SET status='done', tx_hash=%s WHERE id=%s",
                     (rec.tx_hash.lower() if rec else None, kyc_id))
        except Exception as e:  # noqa: BLE001
            log.exception("kyc %s failed", kyc_id)
            st._exec("UPDATE studio.kyc_requests SET status='failed', note=%s WHERE id=%s",
                     (f"issuer: {str(e)[:300]}", kyc_id))


def transfer_mode(svc, company_id: int) -> None:
    """approval -> pause() (plain transfers revert; issuer uses forcedTransfer); free -> unpause()."""
    with svc._exclusive(f"mode:{company_id}") as ok:
        if not ok:
            return
        c = svc.store.company(company_id)
        if not c or not c.get("local_token"):
            return
        want = (c.get("transfer_mode") or "free") == "approval"
        L = svc.local
        token = L.contract("BlockIDShareToken", c["local_token"])
        if bool(token.functions.paused().call()) == want:
            return
        rec = L.transact(token.functions.pause() if want else token.functions.unpause())
        svc._event(company_id, "transfer_mode", LOCAL, rec, mode="approval" if want else "free", paused=want)
