"""Per-company admin wallets ("company admins"): each startup token can be run by its own wallets.

Roles (studio.company_admins.role):
  owner    manage the company's admins (add / revoke) + everything a manager can do
  manager  request AND approve mints, dividends, transfers, KYC and revaluations of THAT company; see its private
           data (draft / pending items). Initial issuance (approve-issue), re-sync, reject and transfer mode stay
           platform-admin only.
Only rows with status 'active' confer rights. A wallet that created a company is seeded as its first owner.

On-chain (optional, `onchain: true`): the issuer grants the wallet ISSUER_ROLE, PAUSER_ROLE and TRANSFER_AGENT_ROLE on
the company's BlockIDShareToken and KYC_AGENT_ROLE on its IdentityRegistry, on BlockID EVM only (issuer/roles.py).
The Hoodi / HashKey mirrors stay issuer-controlled (paused) and are never granted.

GET    /v1/companies/{tk}/admins                         platform admin or any company admin
POST   /v1/companies/{tk}/admins                         platform admin or company owner  {address,label,role,onchain}
POST   /v1/companies/{tk}/admins/{address}/revoke        platform admin or company owner  (never the last owner)
DELETE /v1/companies/{tk}/admins/{address}               same as revoke
GET    /v1/me/companies                                  companies where the session wallet is an active admin
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ..tools import captable
from .auth import COOKIE, Session
from .db import ONCHAIN_STATUSES, jsonable
from .gas import GasDripper
from .services import IssuerError

log = logging.getLogger(__name__)

PLATFORM, OWNER, MANAGER = "platform_admin", "company_owner", "company_manager"
_COLS = ("id, company_id, address, label, role, status, onchain, grant_tx, revoke_tx, error, added_by, added_at, "
         "revoked_at")


class AdminBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    address: str = Field(max_length=64)
    label: str = Field(default="", max_length=120)
    role: Literal["owner", "manager"] = "manager"
    onchain: bool = False


def checksum(address: str) -> str:
    """EIP-55: a mixed-case address must carry a valid checksum; all-lower / all-upper is normalised."""
    try:
        return captable.checksum(address)
    except captable.CapTableError as e:
        raise HTTPException(422, str(e)) from None


def seed_owner(conn, company_id: int, address: str | None, added_by: str | None = None) -> None:
    """Make the creating wallet the company's first owner (inside the create-company transaction)."""
    if not address or not address.startswith("0x") or len(address) != 42:
        return
    try:
        addr = captable.checksum(address)
    except captable.CapTableError:
        return
    conn.execute("INSERT INTO studio.company_admins (company_id, address, label, role, status, added_by) "
                 "VALUES (%s, %s, 'creator', 'owner', 'active', %s) ON CONFLICT (company_id, address) DO NOTHING",
                 (company_id, addr, added_by or addr))


class CompanyAuthz:
    """Who may act on a company: a platform admin, or an ACTIVE company admin of THAT company (wallet sessions)."""

    def __init__(self, ctx):
        self.ctx = ctx

    def _db(self):
        return self.ctx.need_db()

    def admin_role(self, sess: Session, company_id: int) -> str | None:
        """'owner' | 'manager' | None for the session wallet on this company."""
        if not sess.address:
            return None
        row = self._db().one("SELECT role FROM studio.company_admins WHERE company_id=%s AND lower(address)=lower(%s) "
                             "AND status='active'", (company_id, sess.address))
        return row["role"] if row else None

    def company_ids(self, sess: Session) -> list[int]:
        if not sess.address:
            return []
        return [r["company_id"] for r in self._db().all(
            "SELECT company_id FROM studio.company_admins WHERE lower(address)=lower(%s) AND status='active' "
            "ORDER BY company_id", (sess.address,))]

    def role(self, sess: Session, company_id: int) -> str | None:
        """Audit label of the session's strongest right on this company, or None."""
        if sess.is_admin and not sess.must_change:
            return PLATFORM
        r = self.admin_role(sess, company_id)
        return {"owner": OWNER, "manager": MANAGER}.get(r or "")

    def check(self, sess: Session, company_id: int, *, owner: bool = False) -> str:
        """Raise 403 unless platform admin (or company owner/manager); returns the audit role label."""
        if sess.is_admin:
            if sess.must_change:
                raise HTTPException(403, "password change required")
            return PLATFORM
        r = self.admin_role(sess, company_id)
        if r is None:
            raise HTTPException(403, "platform admin or an admin of this company only")
        if owner and r != "owner":
            raise HTTPException(403, "only a company owner (or a platform admin) can do this")
        return OWNER if r == "owner" else MANAGER

    def scope(self, sess: Session) -> list[int] | None:
        """None = every company (platform admin); else the company ids this wallet administers (403 when none)."""
        if sess.is_admin:
            if sess.must_change:
                raise HTTPException(403, "password change required")
            return None
        ids = self.company_ids(sess)
        if not ids:
            raise HTTPException(403, "admin only")
        return ids

    def check_item(self, sess: Session, table: str, item_id: int) -> tuple[int, str]:
        """(company_id, role) for a mints / dividends / transfers / kyc_requests row; 404 unknown, 403 other company."""
        if table not in ("mints", "dividends", "transfers", "kyc_requests"):
            raise ValueError(table)
        row = self._db().one(f"SELECT company_id FROM studio.{table} WHERE id=%s", (item_id,))
        if not row:
            if sess.is_admin:
                raise HTTPException(404, "unknown id")
            raise HTTPException(403, "platform admin or an admin of this company only")
        return row["company_id"], self.check(sess, row["company_id"])


def build_company_admins_router(ctx) -> APIRouter:
    r = APIRouter()
    authz = CompanyAuthz(ctx)
    gas = GasDripper(ctx)

    def session(request: Request) -> Session | None:
        sid = request.cookies.get(COOKIE)
        return ctx.sessions.get(sid) if sid else None

    def require_user(sess: Session | None = Depends(session)) -> Session:
        if sess is None:
            raise HTTPException(401, "sign in required")
        return sess

    def company(tk: str) -> dict:
        c = ctx.need_db().one("SELECT * FROM studio.companies WHERE ticker=%s", (tk.upper(),))
        if not c:
            raise HTTPException(404, "unknown ticker")
        return c

    def rows(cid: int) -> list[dict]:
        return jsonable(ctx.need_db().all(
            f"SELECT {_COLS} FROM studio.company_admins WHERE company_id=%s "
            "ORDER BY (status='revoked'), (role='owner') DESC, added_at, id", (cid,)))

    def audit(sess: Session, role: str, action: str, c: dict, **detail) -> None:
        ctx.need_db().audit(sess.actor, action, c["ticker"], company_id=c["id"], role=role, **detail)

    def ask_issuer(sess: Session, role: str, c: dict, addr: str, grant: bool) -> str | None:
        try:
            ctx.need_issuer().post("/company-roles", {"company_id": c["id"], "address": addr, "grant": grant})
            return None
        except (IssuerError, HTTPException) as e:
            err = str(getattr(e, "detail", e))[:300]
            ctx.need_db().exec("UPDATE studio.company_admins SET error=%s WHERE company_id=%s AND address=%s",
                               (err, c["id"], addr))
            audit(sess, role, "company_admin_issuer_error", c, address=addr, grant=grant, error=err)
            return err

    @r.get("/v1/companies/{tk}/admins")
    def list_admins(tk: str, sess: Session = Depends(require_user)):
        c = company(tk)
        role = authz.check(sess, c["id"])
        return {"ticker": c["ticker"], "company_id": c["id"], "you": role, "issued": bool(c.get("local_token")),
                "admins": rows(c["id"])}

    @r.post("/v1/companies/{tk}/admins", status_code=201)
    def add_admin(tk: str, body: AdminBody, background: BackgroundTasks, sess: Session = Depends(require_user)):
        db = ctx.need_db()
        c = company(tk)
        role = authz.check(sess, c["id"], owner=True)
        addr = checksum(body.address)
        label = body.label.strip()
        if body.onchain and (c["status"] not in ONCHAIN_STATUSES or not c.get("local_token")
                             or not c.get("local_registry")):
            raise HTTPException(409, "the company is not issued on BlockID EVM yet; add the admin without on-chain "
                                     "roles and grant them after issuance")
        with db.tx() as tx:
            prev = tx.execute(f"SELECT {_COLS} FROM studio.company_admins WHERE company_id=%s AND lower(address)="
                              "lower(%s) FOR UPDATE", (c["id"], addr)).fetchone()
            if prev and prev["role"] == "owner" and body.role != "owner" and prev["status"] == "active":
                n = tx.execute("SELECT count(*) AS n FROM studio.company_admins WHERE company_id=%s AND role='owner' "
                               "AND status='active' AND id<>%s", (c["id"], prev["id"])).fetchone()["n"]
                if not n:
                    raise HTTPException(409, "a company must keep at least one active owner")
            already_onchain = bool(prev and prev["onchain"] and prev["status"] == "active")
            grant = body.onchain and not already_onchain
            status = "pending_grant" if grant else "active"
            onchain = bool(grant or already_onchain)
            if prev:
                row = tx.execute(
                    "UPDATE studio.company_admins SET label=%s, role=%s, status=%s, onchain=%s, error=NULL, "
                    "revoked_at=NULL, revoke_tx=CASE WHEN %s THEN NULL ELSE revoke_tx END, "
                    "added_by=CASE WHEN status='revoked' THEN %s ELSE added_by END, "
                    "added_at=CASE WHEN status='revoked' THEN now() ELSE added_at END "
                    f"WHERE id=%s RETURNING {_COLS}",
                    (label or prev["label"], body.role, status, onchain, grant, sess.actor, prev["id"])).fetchone()
            else:
                row = tx.execute(
                    "INSERT INTO studio.company_admins (company_id, address, label, role, status, onchain, added_by) "
                    f"VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING {_COLS}",
                    (c["id"], addr, label, body.role, status, onchain, sess.actor)).fetchone()
        audit(sess, role, "company_admin_added" if not prev or prev["status"] == "revoked" else "company_admin_updated",
              c, address=addr, admin_role=body.role, label=label, onchain=body.onchain)
        out = jsonable(row)
        background.add_task(gas.drip, addr, "company_admin", c["id"])
        if grant:
            err = ask_issuer(sess, role, c, addr, True)
            if err:
                raise HTTPException(502, f"saved as pending_grant, but the issuer could not be reached: {err}; "
                                         "add the wallet again to retry")
            out["issuer"] = "queued"
        return out

    def revoke(tk: str, address: str, sess: Session) -> dict:
        db = ctx.need_db()
        c = company(tk)
        role = authz.check(sess, c["id"], owner=True)
        with db.tx() as tx:
            prev = tx.execute(f"SELECT {_COLS} FROM studio.company_admins WHERE company_id=%s AND lower(address)="
                              "lower(%s) FOR UPDATE", (c["id"], address.strip())).fetchone()
            if not prev:
                raise HTTPException(404, "not an admin of this company")
            if prev["role"] == "owner" and prev["status"] == "active":
                n = tx.execute("SELECT count(*) AS n FROM studio.company_admins WHERE company_id=%s AND role='owner' "
                               "AND status='active' AND id<>%s", (c["id"], prev["id"])).fetchone()["n"]
                if not n:
                    raise HTTPException(409, "cannot remove the last owner; add another owner first")
            row = tx.execute("UPDATE studio.company_admins SET status='revoked', error=NULL, "
                             f"revoked_at=COALESCE(revoked_at, now()) WHERE id=%s RETURNING {_COLS}",
                             (prev["id"],)).fetchone()
        onchain = bool(prev["onchain"] or prev["status"] == "pending_grant")
        if prev["status"] != "revoked":
            audit(sess, role, "company_admin_revoked", c, address=prev["address"], admin_role=prev["role"],
                  onchain=onchain)
        out = jsonable(row)
        if onchain:  # also a retry when a previous on-chain revoke failed
            err = ask_issuer(sess, role, c, prev["address"], False)
            out["issuer"] = "queued" if not err else f"error: {err}"
        return out

    @r.post("/v1/companies/{tk}/admins/{address}/revoke")
    def revoke_post(tk: str, address: str, sess: Session = Depends(require_user)):
        return revoke(tk, address, sess)

    @r.delete("/v1/companies/{tk}/admins/{address}")
    def revoke_delete(tk: str, address: str, sess: Session = Depends(require_user)):
        return revoke(tk, address, sess)

    @r.get("/v1/me/companies")
    def me_companies(sess: Session = Depends(require_user)) -> list[dict[str, Any]]:
        if not sess.address:
            return []
        return jsonable(ctx.need_db().all(
            "SELECT c.id, c.ticker, c.name, c.status, c.local_token, a.role, a.onchain, a.label "
            "FROM studio.company_admins a JOIN studio.companies c ON c.id=a.company_id "
            "WHERE lower(a.address)=lower(%s) AND a.status='active' ORDER BY c.ticker", (sess.address,)))

    return r
