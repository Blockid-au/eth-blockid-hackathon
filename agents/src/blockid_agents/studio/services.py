"""Read-only BlockID Chain access (web3) and the internal issuer-service client (httpx).

The API never signs anything: it reads balances/blocks and asks the issuer service (which holds
the keys) to act on rows an admin has approved.
"""
from __future__ import annotations

import logging
from typing import Protocol

import httpx

log = logging.getLogger(__name__)

ERC20_ABI = [
    {"type": "function", "name": "balanceOf", "stateMutability": "view",
     "inputs": [{"name": "a", "type": "address"}], "outputs": [{"name": "", "type": "uint256"}]},
    {"type": "function", "name": "totalSupply", "stateMutability": "view", "inputs": [],
     "outputs": [{"name": "", "type": "uint256"}]},
]


class ChainReader(Protocol):
    def block_number(self) -> int: ...
    def balances(self, token: str, wallets: list[str]) -> dict[str, int]: ...


class Web3ChainReader:
    def __init__(self, rpc_url: str, timeout: float = 5):
        from web3 import Web3

        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": timeout}))

    def block_number(self) -> int:
        return int(self.w3.eth.block_number)

    def balances(self, token: str, wallets: list[str]) -> dict[str, int]:
        from web3 import Web3

        c = self.w3.eth.contract(address=Web3.to_checksum_address(token), abi=ERC20_ABI)
        return {w: int(c.functions.balanceOf(Web3.to_checksum_address(w)).call()) for w in wallets}


class IssuerError(RuntimeError):
    pass


class IssuerClient:
    def __init__(self, base_url: str, token: str, transport: httpx.BaseTransport | None = None, timeout: float = 10):
        self.http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport,
                                 headers={"X-Internal-Token": token})

    def post(self, path: str, body: dict) -> dict:
        try:
            r = self.http.post(path, json=body)
        except httpx.HTTPError as e:
            raise IssuerError(f"issuer unreachable: {e}") from e
        if r.status_code >= 300:
            raise IssuerError(f"issuer {path} -> HTTP {r.status_code}: {r.text[:300]}")
        try:
            return r.json()
        except ValueError:
            return {}

    def health(self) -> dict:
        try:
            r = self.http.get("/health")
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001 - shown to admins as-is
            return {"ok": False, "error": str(e)[:300]}
