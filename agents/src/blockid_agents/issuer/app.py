"""Internal issuer HTTP service (:8090). Never exposed publicly; every call needs X-Internal-Token.

Endpoints return 202 immediately; the work runs on ONE background worker thread (jobs are serialised, so
nonces and DB status transitions never race). Progress is visible through studio.* rows.
"""
from __future__ import annotations

import hmac
import logging
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .config import IssuerConfig

log = logging.getLogger(__name__)


class CompanyReq(BaseModel):
    company_id: int


class MintReq(BaseModel):
    mint_id: int


class DividendReq(BaseModel):
    dividend_id: int


class TransferReq(BaseModel):
    transfer_id: int


class KycReq(BaseModel):
    kyc_id: int


class DripReq(BaseModel):
    wallet: str
    company_id: int | None = None
    amount_wei: int | None = Field(default=None, ge=0, le=5 * 10**18)  # gas allowance (top-up target), <= 5 BLKD


class UpdateReq(BaseModel):
    update_id: str = Field(min_length=1, max_length=64)


class CompanyRoleReq(BaseModel):
    company_id: int
    address: str
    grant: bool


def create_app(service=None, cfg: IssuerConfig | None = None) -> FastAPI:
    cfg = cfg or IssuerConfig()
    if not cfg.internal_token:
        raise RuntimeError("ISSUER_INTERNAL_TOKEN must be set")
    app = FastAPI(title="BlockID issuer (internal)", docs_url=None, redoc_url=None, openapi_url=None)
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="issuer")
    state: dict = {"service": service, "pending": 0}

    def svc():
        if state["service"] is None:
            from .service import Service

            state["service"] = Service.from_env(cfg)
        return state["service"]

    def auth(x_internal_token: str = Header(default="")) -> None:
        if not hmac.compare_digest(x_internal_token.encode(), cfg.internal_token.encode()):
            raise HTTPException(401, "invalid internal token")

    def submit(op: str, fn: Callable[[], None], **ref) -> dict:
        def run() -> None:
            try:
                log.info("issuer job %s %s start", op, ref)
                fn()
                log.info("issuer job %s %s done", op, ref)
            except Exception:
                log.exception("issuer job %s %s crashed", op, ref)
            finally:
                state["pending"] -= 1

        state["pending"] += 1
        pool.submit(run)
        return {"accepted": True, "op": op, **ref}

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    @app.get("/health", dependencies=[Depends(auth)])
    def health() -> dict:
        return {**svc().health(), "queue": state["pending"]}

    @app.post("/issue", status_code=202, dependencies=[Depends(auth)])
    def issue(r: CompanyReq) -> dict:
        s = svc()
        return submit("issue", lambda: s.issue(r.company_id), company_id=r.company_id)

    @app.post("/anchor", status_code=202, dependencies=[Depends(auth)])
    def anchor(r: CompanyReq) -> dict:
        s = svc()
        return submit("anchor", lambda: s.anchor(r.company_id), company_id=r.company_id)

    @app.post("/refresh", status_code=202, dependencies=[Depends(auth)])
    def refresh(r: CompanyReq) -> dict:
        s = svc()
        return submit("refresh", lambda: s.refresh(r.company_id), company_id=r.company_id)

    @app.post("/revalue", status_code=202, dependencies=[Depends(auth)])
    def revalue(r: CompanyReq) -> dict:
        s = svc()
        return submit("revalue", lambda: s.revalue(r.company_id), company_id=r.company_id)

    @app.post("/reanchor-valuation", status_code=202, dependencies=[Depends(auth)])
    def reanchor_valuation(r: CompanyReq) -> dict:
        s = svc()
        return submit("reanchor-valuation", lambda: s.reanchor_valuation(r.company_id), company_id=r.company_id)

    @app.post("/mint", status_code=202, dependencies=[Depends(auth)])
    def mint(r: MintReq) -> dict:
        s = svc()
        return submit("mint", lambda: s.mint(r.mint_id), mint_id=r.mint_id)

    @app.post("/dividend", status_code=202, dependencies=[Depends(auth)])
    def dividend(r: DividendReq) -> dict:
        s = svc()
        return submit("dividend", lambda: s.dividend(r.dividend_id), dividend_id=r.dividend_id)

    @app.post("/drip", status_code=202, dependencies=[Depends(auth)])
    def drip(r: DripReq) -> dict:
        from web3 import Web3

        if not Web3.is_address(r.wallet):
            raise HTTPException(422, "invalid wallet")
        s = svc()
        if r.amount_wei is None:
            return submit("drip", lambda: s.drip(r.wallet, r.company_id), wallet=Web3.to_checksum_address(r.wallet))
        return submit("drip", lambda: s.drip(r.wallet, r.company_id, r.amount_wei),
                      wallet=Web3.to_checksum_address(r.wallet), amount_wei=r.amount_wei)

    # ---------------------------------------------------------------- company admin roles (issuer/roles.py)
    @app.post("/company-roles", status_code=202, dependencies=[Depends(auth)])
    def company_roles(r: CompanyRoleReq) -> dict:
        from web3 import Web3

        from . import roles

        if not Web3.is_address(r.address):
            raise HTTPException(422, "invalid address")
        s = svc()
        addr = Web3.to_checksum_address(r.address)
        return submit("company-roles", lambda: roles.company_roles(s, r.company_id, addr, r.grant),
                      company_id=r.company_id, address=addr, grant=r.grant)

    # ---------------------------------------------------------------- secondary transfers (issuer/transfers.py)
    @app.post("/reanchor", status_code=202, dependencies=[Depends(auth)])
    def reanchor(r: CompanyReq) -> dict:
        s = svc()
        return submit("reanchor", lambda: s.reanchor(r.company_id), company_id=r.company_id)

    @app.post("/transfer", status_code=202, dependencies=[Depends(auth)])
    def transfer(r: TransferReq) -> dict:
        from . import transfers

        s = svc()
        return submit("transfer", lambda: transfers.transfer(s, r.transfer_id), transfer_id=r.transfer_id)

    @app.post("/kyc", status_code=202, dependencies=[Depends(auth)])
    def kyc(r: KycReq) -> dict:
        from . import transfers

        s = svc()
        return submit("kyc", lambda: transfers.kyc(s, r.kyc_id), kyc_id=r.kyc_id)

    @app.post("/transfer-mode", status_code=202, dependencies=[Depends(auth)])
    def transfer_mode(r: CompanyReq) -> dict:
        from . import transfers

        s = svc()
        return submit("transfer-mode", lambda: transfers.transfer_mode(s, r.company_id), company_id=r.company_id)

    # ---------------------------------------------------------------- business updates (issuer/disclose.py)
    @app.post("/disclose", status_code=202, dependencies=[Depends(auth)])
    def disclose(r: UpdateReq) -> dict:
        from . import disclose as disc

        s = svc()
        return submit("disclose", lambda: disc.disclose(s, r.update_id), update_id=r.update_id)

    app.state.issuer = state
    app.state.pool = pool
    return app


def run() -> None:
    """Entry point for `python -m blockid_agents issuer`."""
    import uvicorn

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from .service import Service

    cfg = IssuerConfig()
    app = create_app(Service.from_env(cfg), cfg)  # decrypt keystores at startup: fail fast, not on first job
    uvicorn.run(app, host="0.0.0.0", port=cfg.port)


if __name__ == "__main__":
    run()
