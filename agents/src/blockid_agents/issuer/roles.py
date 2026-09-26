"""On-chain roles for company admins (studio/company_admins.py) on the company's BlockID EVM contracts.

grant  -> BlockIDShareToken: ISSUER_ROLE, PAUSER_ROLE, TRANSFER_AGENT_ROLE; IdentityRegistry: KYC_AGENT_ROLE
revoke -> the same roles are revoked (only those the wallet actually holds).

The issuer can do this because Service._ensure_registry deploys IdentityRegistry(admin = issuer) and _ensure_token
deploys BlockIDShareToken(issuerSafe = issuer), so the issuer holds DEFAULT_ADMIN_ROLE (the admin of every role) on
both; this is re-checked on chain before any tx and the job fails with a clear error otherwise.
The issuer keeps its own roles (it never grants DEFAULT_ADMIN_ROLE and refuses to touch its own address), so the
platform flows (issue, mint, dividend, forcedTransfer, pause) keep working. DividendDistributor is not granted.
Hoodi / HashKey mirrors stay issuer-controlled (paused) and are never granted.

Acts only on a DB row the API wrote: grant needs studio.company_admins.status = 'pending_grant', revoke needs
status = 'revoked' and onchain = true. Every tx is a studio.events row (kind role_granted / role_revoked,
chain 'blockid').
"""
from __future__ import annotations

import logging

from web3 import Web3

log = logging.getLogger(__name__)

LOCAL = "blockid"
TOKEN_ROLES = ("ISSUER_ROLE", "PAUSER_ROLE", "TRANSFER_AGENT_ROLE")
REGISTRY_ROLES = ("KYC_AGENT_ROLE",)
DEFAULT_ADMIN_ROLE = b"\x00" * 32


class RoleError(RuntimeError):
    pass


def role_plan(token, registry) -> list[tuple[str, object, str, bytes]]:
    """[(contract name, contract, role name, role id)] in execution order (reads the role ids from the contracts)."""
    plan = [("BlockIDShareToken", token, name, getattr(token.functions, name)().call()) for name in TOKEN_ROLES]
    plan += [("IdentityRegistry", registry, name, getattr(registry.functions, name)().call()) for name in REGISTRY_ROLES]
    return plan


def _short(a: str) -> str:
    return f"{a[:6]}…{a[-4:]}"


def company_roles(svc, company_id: int, address: str, grant: bool) -> None:
    with svc._exclusive(f"company-roles:{company_id}:{address.lower()}") as ok:
        if ok:
            _run(svc, company_id, Web3.to_checksum_address(address), grant)


def _run(svc, company_id: int, address: str, grant: bool) -> None:
    st = svc.store
    row = st.company_admin(company_id, address)
    if not row:
        log.warning("company-roles: %s is not an admin of company %s; skipped", address, company_id)
        return
    if grant and row["status"] != "pending_grant":
        log.warning("company-roles grant: %s on %s is %s, expected pending_grant; skipped", address, company_id,
                    row["status"])
        return
    if not grant and not (row["status"] == "revoked" and row["onchain"]):
        log.warning("company-roles revoke: %s on %s is %s/onchain=%s; skipped", address, company_id, row["status"],
                    row["onchain"])
        return
    try:
        last = _apply(svc, company_id, address, grant)
    except Exception as e:
        log.exception("company-roles %s %s on %s failed", "grant" if grant else "revoke", address, company_id)
        st.update_company_admin(row["id"], error=f"{type(e).__name__}: {e}"[:500])
        svc._event(company_id, "role_grant_failed" if grant else "role_revoke_failed", LOCAL, None,
                   address=address, error=f"{type(e).__name__}: {e}"[:300])
        return
    if grant:
        # the row may have been revoked while the job ran: then leave it for the revoke job
        cur = st.company_admin(company_id, address) or {}
        st.update_company_admin(row["id"], status="active" if cur.get("status") == "pending_grant" else cur.get("status"),
                                onchain=True, grant_tx=last or row.get("grant_tx"), error=None)
    else:
        st.update_company_admin(row["id"], onchain=False, revoke_tx=last or row.get("revoke_tx"), error=None)


def _apply(svc, company_id: int, address: str, grant: bool) -> str | None:
    """Grant/revoke every role the wallet lacks/holds; returns the last tx hash (None when nothing to do)."""
    L = svc.local
    if address.lower() == L.address.lower():
        raise RoleError("refusing to change the issuer's own roles")
    c = svc.store.company(company_id)
    if not c or not c.get("local_token") or not c.get("local_registry"):
        raise RoleError("company is not issued on BlockID EVM (no token / registry)")
    token = L.contract("BlockIDShareToken", c["local_token"])
    registry = L.contract("IdentityRegistry", c["local_registry"])
    for name, ct in (("BlockIDShareToken", token), ("IdentityRegistry", registry)):
        if not ct.functions.hasRole(DEFAULT_ADMIN_ROLE, L.address).call():
            raise RoleError(f"issuer {L.address} lacks DEFAULT_ADMIN_ROLE on {name} {ct.address}; "
                            "on-chain roles cannot be managed for this company")
    last = None
    if grant:
        try:  # so the new admin can pay gas for its own role actions (never blocks the grant)
            svc._drip_if_needed(address, company_id)
        except Exception:
            log.exception("drip to new company admin %s failed", address)
    for cname, ct, rname, rid in role_plan(token, registry):
        has = ct.functions.hasRole(rid, address).call()
        if has == grant:
            continue
        fn = ct.functions.grantRole(rid, address) if grant else ct.functions.revokeRole(rid, address)
        rec = L.transact(fn)
        last = rec.tx_hash
        verb = "granted to" if grant else "revoked from"
        svc._event(company_id, "role_granted" if grant else "role_revoked", LOCAL, rec, address=address,
                   contract=cname, contract_address=ct.address, role=rname,
                   text=f"{rname} {verb} {_short(address)} on {cname}")
    return last
