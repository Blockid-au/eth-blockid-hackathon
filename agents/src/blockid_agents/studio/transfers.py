"""Secondary share transfers + investor KYC requests (BlockID Chain is the register; Hoodi/HSK are re-anchored).

Two modes per company (studio.companies.transfer_mode, admin checkbox):
  free      token unpaused: any KYC'd holder sends BlockIDShareToken.transfer from MetaMask, then reports the
            tx hash here; the API checks the receipt and records it, the issuer re-anchors the mirrors.
  approval  token paused (plain transfers revert with EnforcedPause): the holder files a request, an admin
            approves, the issuer executes forcedTransfer(from, to, n, keccak("studio-transfer:<id>")).
The receiver must be KYC'd in the company's IdentityRegistry either way (KYC request -> admin -> issuer).

GET  /v1/companies/{tk}/transfer-info          mode, paused, token, registry
POST /v1/companies/{tk}/transfers/check        {from_wallet,to_wallet,shares} -> {ok, reason, ...} (eth_call)
POST /v1/companies/{tk}/transfers              free: {to_wallet,shares,tx_hash}; approval: {to_wallet,shares}
GET  /v1/companies/{tk}/transfers              history
POST /v1/companies/{tk}/kyc                    {wallet?, name} -> pending KYC request (wallet = signed-in one)
GET  /v1/admin/transfers | /v1/admin/kyc       queues
POST /v1/admin/transfers/{id}/approve|reject   POST /v1/admin/kyc/{id}/approve|reject
POST /v1/admin/companies/{cid}/transfer-mode   {mode: free|approval} -> issuer pauses / unpauses the token
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from .auth import COOKIE, Session
from .company_admins import CompanyAuthz
from .db import ONCHAIN_STATUSES, jsonable
from .services import IssuerError

log = logging.getLogger(__name__)

TOKEN_ABI = [
    {"type": "function", "name": "transfer", "stateMutability": "nonpayable",
     "inputs": [{"name": "to", "type": "address"}, {"name": "value", "type": "uint256"}],
     "outputs": [{"name": "", "type": "bool"}]},
    {"type": "function", "name": "paused", "stateMutability": "view", "inputs": [],
     "outputs": [{"name": "", "type": "bool"}]},
    {"type": "function", "name": "balanceOf", "stateMutability": "view",
     "inputs": [{"name": "a", "type": "address"}], "outputs": [{"name": "", "type": "uint256"}]},
    {"type": "event", "name": "Transfer", "anonymous": False,
     "inputs": [{"name": "from", "type": "address", "indexed": True},
                {"name": "to", "type": "address", "indexed": True},
                {"name": "value", "type": "uint256", "indexed": False}]},
]
REGISTRY_ABI = [
    {"type": "function", "name": "isVerified", "stateMutability": "view",
     "inputs": [{"name": "w", "type": "address"}], "outputs": [{"name": "", "type": "bool"}]},
]
# custom errors of BlockIDShareToken / OZ v5 ERC20 + Pausable -> reason code for the UI
ERRORS = {
    "NotVerified(address)": "not_verified",
    "WalletIsFrozen(address)": "frozen",
    "LockupActive(uint64)": "lockup",
    "ShareholderCapReached(uint32)": "cap",
    "EnforcedPause()": "paused",
    "ERC20InsufficientBalance(address,uint256,uint256)": "balance",
    "ERC20InvalidReceiver(address)": "receiver",
}


class CheckBody(BaseModel):
    from_wallet: str = Field(max_length=64)
    to_wallet: str = Field(max_length=64)
    shares: int = Field(gt=0, le=10**15)


class TransferBody(BaseModel):
    to_wallet: str = Field(max_length=64)
    to_name: str = Field(default="", max_length=120)
    shares: int = Field(gt=0, le=10**15)
    tx_hash: str | None = Field(default=None, max_length=80)
    note: str = Field(default="", max_length=500)


class KycBody(BaseModel):
    wallet: str | None = Field(default=None, max_length=64)
    name: str = Field(min_length=1, max_length=120)


class ModeBody(BaseModel):
    mode: Literal["free", "approval"]


class ReasonBody(BaseModel):
    reason: str = Field(default="", max_length=500)


def build_transfer_router(ctx) -> APIRouter:
    from web3 import Web3

    r = APIRouter()
    s = ctx.settings
    state: dict[str, Any] = {}
    authz = CompanyAuthz(ctx)  # company admins act on their own company's queue

    def w3() -> Web3:
        if "w3" not in state:
            state["w3"] = Web3(Web3.HTTPProvider(s.local_rpc_url, request_kwargs={"timeout": 8}))
        return state["w3"]

    selectors = {Web3.keccak(text=sig)[:4].hex(): code for sig, code in ERRORS.items()}

    # ---------------------------------------------------------------- session helpers (same rules as routes.py)
    def session(request: Request) -> Session | None:
        sid = request.cookies.get(COOKIE)
        return ctx.sessions.get(sid) if sid else None

    def require_user(sess: Session | None = Depends(session)) -> Session:
        if sess is None:
            raise HTTPException(401, "sign in required")
        return sess

    def require_admin(sess: Session = Depends(require_user)) -> Session:
        if not sess.is_admin:
            raise HTTPException(403, "admin only")
        if sess.must_change:
            raise HTTPException(403, "password change required")
        return sess

    def audit(sess: Session, action: str, target: Any = None, **detail) -> None:
        detail.setdefault("role", "platform_admin" if sess.is_admin else "user")  # company actions pass their role
        ctx.need_db().audit(sess.actor, action, None if target is None else str(target), **detail)

    def company(tk: str) -> dict:
        c = ctx.need_db().one("SELECT * FROM studio.companies WHERE ticker=%s", (tk.upper(),))
        if not c or c["status"] not in ONCHAIN_STATUSES or not c.get("local_token"):
            raise HTTPException(404, "unknown or not-issued ticker")
        return c

    def addr(a: str, field: str = "wallet") -> str:
        try:
            return Web3.to_checksum_address(a.strip())
        except (ValueError, AttributeError):
            raise HTTPException(422, f"{field}: not an address") from None

    def mode(c: dict) -> str:
        return c.get("transfer_mode") or "free"

    def verified(c: dict, wallet: str) -> bool:
        reg = w3().eth.contract(address=Web3.to_checksum_address(c["local_registry"]), abi=REGISTRY_ABI)
        return bool(reg.functions.isVerified(wallet).call())

    def paused(c: dict) -> bool | None:
        try:
            tok = w3().eth.contract(address=Web3.to_checksum_address(c["local_token"]), abi=TOKEN_ABI)
            return bool(tok.functions.paused().call())
        except Exception:  # noqa: BLE001
            return None

    def simulate(c: dict, frm: str, to: str, n: int) -> tuple[bool, str | None]:
        tok = w3().eth.contract(address=Web3.to_checksum_address(c["local_token"]), abi=TOKEN_ABI)
        try:
            tok.functions.transfer(to, n).call({"from": frm})
            return True, None
        except Exception as e:  # noqa: BLE001 - ContractCustomError / ContractLogicError / RPC error
            data = getattr(e, "data", None) or (e.args[1] if len(e.args) > 1 else None) or str(e)
            text = str(data).lower().removeprefix("0x")
            for sel, code in selectors.items():
                if sel.removeprefix("0x") in text:
                    return False, code
            return False, "reverted"

    def notify_issuer(path: str, body: dict) -> str | None:
        try:
            ctx.need_issuer().post(path, body)
            return None
        except (IssuerError, HTTPException) as e:
            log.warning("issuer %s %s: %s", path, body, e)
            return str(getattr(e, "detail", e))[:300]

    # ---------------------------------------------------------------- public
    @r.get("/v1/companies/{tk}/transfer-info")
    def transfer_info(tk: str):
        c = company(tk)
        return {"ticker": c["ticker"], "mode": mode(c), "paused": paused(c), "token": c["local_token"],
                "registry": c["local_registry"], "chain_id": s.local_chain_id}

    @r.post("/v1/companies/{tk}/transfers/check")
    def check(tk: str, body: CheckBody):
        c = company(tk)
        frm, to = addr(body.from_wallet, "from_wallet"), addr(body.to_wallet, "to_wallet")
        out: dict[str, Any] = {"mode": mode(c), "from_verified": verified(c, frm), "to_verified": verified(c, to)}
        tok = w3().eth.contract(address=Web3.to_checksum_address(c["local_token"]), abi=TOKEN_ABI)
        out["balance"] = int(tok.functions.balanceOf(frm).call())
        if frm == to:
            return {**out, "ok": False, "reason": "self"}
        if out["balance"] < body.shares:
            return {**out, "ok": False, "reason": "balance"}
        if not out["to_verified"]:
            return {**out, "ok": False, "reason": "not_verified"}
        if mode(c) == "approval":  # executed by the issuer (forcedTransfer): checks above are what matters
            return {**out, "ok": True, "reason": None, "via": "request"}
        ok, reason = simulate(c, frm, to, body.shares)
        return {**out, "ok": ok, "reason": reason, "via": "wallet"}

    @r.get("/v1/companies/{tk}/transfers")
    def history(tk: str):
        c = company(tk)
        rows = ctx.need_db().all("SELECT id, from_wallet, to_wallet, to_name, shares, mode, status, tx_hash, note, "
                                 "created_at, decided_at FROM studio.transfers WHERE company_id=%s "
                                 "ORDER BY id DESC LIMIT 100", (c["id"],))
        return jsonable(rows)

    @r.post("/v1/companies/{tk}/transfers", status_code=201)
    def create_transfer(tk: str, body: TransferBody, sess: Session = Depends(require_user)):
        db = ctx.need_db()
        c = company(tk)
        if not sess.address:
            raise HTTPException(403, "sign in with the wallet that holds the shares (MetaMask)")
        frm, to = addr(sess.address), addr(body.to_wallet, "to_wallet")
        if frm == to:
            raise HTTPException(422, "sender and receiver are the same wallet")
        m = mode(c)
        if m == "free":
            if not body.tx_hash:
                raise HTTPException(422, "free-transfer mode: send the transfer from your wallet and pass tx_hash")
            try:
                rc = w3().eth.get_transaction_receipt(body.tx_hash)
            except Exception:  # noqa: BLE001
                raise HTTPException(409, "transaction not found (yet) on BlockID Chain") from None
            if rc["status"] != 1:
                raise HTTPException(409, "transaction reverted")
            tok = w3().eth.contract(address=Web3.to_checksum_address(c["local_token"]), abi=TOKEN_ABI)
            logs = [lg for lg in tok.events.Transfer().process_receipt(rc) if lg["address"] == tok.address]
            hit = [lg for lg in logs if lg["args"]["from"] == frm and lg["args"]["to"] == to
                   and int(lg["args"]["value"]) == body.shares]
            if not hit:
                raise HTTPException(409, "the transaction is not this transfer of this company's shares")
            try:
                row = db.one("INSERT INTO studio.transfers(company_id,from_wallet,to_wallet,to_name,shares,mode,status,"
                             "tx_hash,block,note,requested_by,decided_at) VALUES (%s,%s,%s,%s,%s,'free','done',%s,%s,%s,"
                             "%s,now()) RETURNING *",
                             (c["id"], frm, to, body.to_name.strip(), body.shares, body.tx_hash.lower(),
                              int(rc["blockNumber"]), body.note, sess.actor))
            except UniqueViolation:
                raise HTTPException(409, "this transaction is already recorded") from None
            db.exec("INSERT INTO studio.events(company_id,kind,chain,tx_hash,block,data) "
                    "VALUES (%s,'transferred','blockid',%s,%s,%s)",
                    (c["id"], body.tx_hash.lower(), int(rc["blockNumber"]),
                     Jsonb({"transfer_id": row["id"], "from": frm, "to": to, "name": body.to_name.strip(),
                            "shares": body.shares, "mode": "free"})))
            audit(sess, "transfer_recorded", c["ticker"], transfer_id=row["id"], shares=body.shares, to=to)
            err = notify_issuer("/reanchor", {"company_id": c["id"]})
            return {**jsonable(row), "reanchor_error": err}
        # approval mode: a request for the admin queue
        tok = w3().eth.contract(address=Web3.to_checksum_address(c["local_token"]), abi=TOKEN_ABI)
        pending = db.one("SELECT coalesce(sum(shares),0) AS n FROM studio.transfers WHERE company_id=%s AND "
                         "lower(from_wallet)=lower(%s) AND status IN ('pending','approved','executing')",
                         (c["id"], frm))
        if int(tok.functions.balanceOf(frm).call()) < body.shares + int(pending["n"]):
            raise HTTPException(409, "not enough shares (including your pending requests)")
        row = db.one("INSERT INTO studio.transfers(company_id,from_wallet,to_wallet,to_name,shares,mode,status,note,"
                     "requested_by) VALUES (%s,%s,%s,%s,%s,'approval','pending',%s,%s) RETURNING *",
                     (c["id"], frm, to, body.to_name.strip(), body.shares, body.note, sess.actor))
        db.exec("INSERT INTO studio.events(company_id,kind,data) VALUES (%s,'transfer_requested',%s)",
                (c["id"], Jsonb({"transfer_id": row["id"], "from": frm, "to": to, "shares": body.shares})))
        audit(sess, "transfer_requested", c["ticker"], transfer_id=row["id"], shares=body.shares, to=to)
        return jsonable(row)

    @r.post("/v1/companies/{tk}/kyc", status_code=201)
    def request_kyc(tk: str, body: KycBody, sess: Session = Depends(require_user)):
        db = ctx.need_db()
        c = company(tk)
        wallet = addr(body.wallet or sess.address or "", "wallet")
        if verified(c, wallet):
            return {"wallet": wallet, "status": "verified"}
        dup = db.one("SELECT * FROM studio.kyc_requests WHERE company_id=%s AND lower(wallet)=lower(%s) "
                     "AND status IN ('pending','approved')", (c["id"], wallet))
        if dup:
            return jsonable(dup)
        row = db.one("INSERT INTO studio.kyc_requests(company_id,wallet,name,status,requested_by) "
                     "VALUES (%s,%s,%s,'pending',%s) RETURNING *", (c["id"], wallet, body.name.strip(), sess.actor))
        audit(sess, "kyc_requested", c["ticker"], kyc_id=row["id"], wallet=wallet)
        return jsonable(row)

    # ---------------------------------------------------------------- admin
    def queue(sess: Session, sql: str) -> list:
        ids = authz.scope(sess)  # platform admin: all; company admin: own companies only
        where = "" if ids is None else "WHERE c.id = ANY(%(ids)s) "
        return jsonable(ctx.need_db().all(sql.format(where=where), None if ids is None else {"ids": ids}))

    @r.get("/v1/admin/transfers")
    def admin_transfers(sess: Session = Depends(require_user)):
        return queue(sess, "SELECT t.*, c.ticker, c.name AS company_name FROM studio.transfers t "
                           "JOIN studio.companies c ON c.id=t.company_id {where}"
                           "ORDER BY (t.status='pending') DESC, t.id DESC LIMIT 200")

    @r.get("/v1/admin/kyc")
    def admin_kyc(sess: Session = Depends(require_user)):
        return queue(sess, "SELECT k.*, c.ticker, c.name AS company_name FROM studio.kyc_requests k "
                           "JOIN studio.companies c ON c.id=k.company_id {where}"
                           "ORDER BY (k.status='pending') DESC, k.id DESC LIMIT 200")

    def approve(table: str, item_id: int, path: str, key: str, sess: Session, action: str) -> dict:
        _, role = authz.check_item(sess, table, item_id)  # platform admin or an admin of the item's company
        db = ctx.need_db()
        row = db.one(f"UPDATE studio.{table} SET status='approved', decided_by=%s, decided_at=now() "
                     "WHERE id=%s AND status IN ('pending','failed') RETURNING id, company_id",
                     (sess.actor, item_id))
        if not row:
            ex = db.one(f"SELECT status FROM studio.{table} WHERE id=%s", (item_id,))
            raise HTTPException(404 if not ex else 409, "unknown id" if not ex else f"status is {ex['status']}")
        audit(sess, action, item_id, company_id=row["company_id"], role=role)
        err = notify_issuer(path, {key: item_id})
        if err:
            db.exec(f"UPDATE studio.{table} SET status='pending' WHERE id=%s AND status='approved'", (item_id,))
            raise HTTPException(502, err)
        return {"id": item_id, "status": "approved"}

    def reject(table: str, item_id: int, sess: Session, action: str, reason: str) -> dict:
        _, role = authz.check_item(sess, table, item_id)
        row = ctx.need_db().one(f"UPDATE studio.{table} SET status='rejected', decided_by=%s, decided_at=now(), "
                                "note=coalesce(nullif(%s,''), note) WHERE id=%s AND status='pending' RETURNING id",
                                (sess.actor, reason, item_id))
        if not row:
            raise HTTPException(409, "not pending")
        audit(sess, action, item_id, reason=reason, role=role)
        return {"id": item_id, "status": "rejected"}

    @r.post("/v1/admin/transfers/{tid}/approve", status_code=202)
    def approve_transfer(tid: int, sess: Session = Depends(require_user)):
        return approve("transfers", tid, "/transfer", "transfer_id", sess, "transfer_approved")

    @r.post("/v1/admin/transfers/{tid}/reject")
    def reject_transfer(tid: int, body: ReasonBody, sess: Session = Depends(require_user)):
        return reject("transfers", tid, sess, "transfer_rejected", body.reason)

    @r.post("/v1/admin/kyc/{kid}/approve", status_code=202)
    def approve_kyc(kid: int, sess: Session = Depends(require_user)):
        return approve("kyc_requests", kid, "/kyc", "kyc_id", sess, "kyc_approved")

    @r.post("/v1/admin/kyc/{kid}/reject")
    def reject_kyc(kid: int, body: ReasonBody, sess: Session = Depends(require_user)):
        return reject("kyc_requests", kid, sess, "kyc_rejected", body.reason)

    @r.post("/v1/admin/companies/{cid}/transfer-mode", status_code=202)
    def set_mode(cid: int, body: ModeBody, sess: Session = Depends(require_admin)):
        db = ctx.need_db()
        c = db.one("UPDATE studio.companies SET transfer_mode=%s WHERE id=%s AND local_token IS NOT NULL "
                   "RETURNING id, ticker", (body.mode, cid))
        if not c:
            raise HTTPException(404, "unknown or not-issued company")
        audit(sess, "transfer_mode_set", c["ticker"], mode=body.mode)
        err = notify_issuer("/transfer-mode", {"company_id": cid})
        if err:
            raise HTTPException(502, err)
        return {"id": cid, "mode": body.mode}

    return r
