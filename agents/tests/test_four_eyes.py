"""Company-level approvals need a second person, and the shared demo account never approves (no Postgres needed)."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from blockid_agents.studio.auth import Session
from blockid_agents.studio.company_admins import MANAGER, PLATFORM, CompanyAuthz

REQ = "0xAAaa000000000000000000000000000000000001"
OTHER = "0xbbbb000000000000000000000000000000000002"


class _DB:
    def one(self, sql, args):
        return {"requested_by": REQ}


def authz(role: str) -> CompanyAuthz:
    a = CompanyAuthz.__new__(CompanyAuthz)
    a.check_item = lambda sess, table, item_id: (7, role)
    a._db = lambda: _DB()
    return a


def sess(address: str, method: str = "wallet", role: str = "user") -> Session:
    return Session(role=role, address=address, auth_method=method)


def test_manager_cannot_approve_own_request():
    with pytest.raises(HTTPException) as e:
        authz(MANAGER).check_approver(sess(REQ.lower()), "mints", 1)  # same wallet, any letter case
    assert e.value.status_code == 403 and "different person" in e.value.detail


def test_another_manager_can_approve():
    assert authz(MANAGER).check_approver(sess(OTHER), "mints", 1) == (7, MANAGER)


def test_shared_demo_account_never_approves():
    with pytest.raises(HTTPException) as e:
        authz(MANAGER).check_approver(sess(OTHER, method="demo"), "dividends", 1)
    assert e.value.status_code == 403 and "demo" in e.value.detail


def test_platform_admin_unchanged():
    assert authz(PLATFORM).check_approver(sess(REQ, role="admin"), "transfers", 1) == (7, PLATFORM)
