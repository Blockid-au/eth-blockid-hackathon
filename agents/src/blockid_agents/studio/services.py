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
# BlockIDShareToken: the holder cap is enforced by the token itself (reverts ShareholderCapReached)
SHARE_TOKEN_ABI = [
    {"type": "function", "name": "maxShareholders", "stateMutability": "view", "inputs": [],
     "outputs": [{"name": "", "type": "uint32"}]},
    {"type": "function", "name": "shareholderCount", "stateMutability": "view", "inputs": [],
     "outputs": [{"name": "", "type": "uint32"}]},
]


class ChainReader(Protocol):
    def block_number(self) -> int: ...
    def balances(self, token: str, wallets: list[str]) -> dict[str, int]: ...
    def shareholders(self, token: str) -> tuple[int, int]:
        """(maxShareholders, shareholderCount) of a BlockIDShareToken; a cap of 0 means no limit."""
        ...


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

    def shareholders(self, token: str) -> tuple[int, int]:
        from web3 import Web3

        c = self.w3.eth.contract(address=Web3.to_checksum_address(token), abi=SHARE_TOKEN_ABI)
        return int(c.functions.maxShareholders().call()), int(c.functions.shareholderCount().call())

    def transfer_facts(self, token: str, registry: str, frm: str, to: str) -> dict:
        """What BlockIDShareToken._update checks for a secondary transfer (see transfer_blocker)."""
        from web3 import Web3

        tok = self.w3.eth.contract(address=Web3.to_checksum_address(token), abi=SHARE_TOKEN_FACTS_ABI)
        reg = self.w3.eth.contract(address=Web3.to_checksum_address(registry), abi=REGISTRY_FACTS_ABI)
        f, t = Web3.to_checksum_address(frm), Web3.to_checksum_address(to)
        return {
            "balance_from": int(tok.functions.balanceOf(f).call()),
            "balance_to": int(tok.functions.balanceOf(t).call()),
            "from_verified": bool(reg.functions.isVerified(f).call()),
            "to_verified": bool(reg.functions.isVerified(t).call()),
            "frozen_from": bool(tok.functions.frozen(f).call()),
            "frozen_to": bool(tok.functions.frozen(t).call()),
            "lockup_until": int(tok.functions.lockupUntil().call()),
            "holders": int(tok.functions.shareholderCount().call()),
            "max_holders": int(tok.functions.maxShareholders().call()),
            "now": int(self.w3.eth.get_block("latest")["timestamp"]),
        }


def _view(name: str, inputs: list[str], out: str) -> dict:
    return {"type": "function", "name": name, "stateMutability": "view",
            "inputs": [{"name": f"a{i}", "type": x} for i, x in enumerate(inputs)],
            "outputs": [{"name": "", "type": out}]}


SHARE_TOKEN_FACTS_ABI = [_view("balanceOf", ["address"], "uint256"), _view("frozen", ["address"], "bool"),
                         _view("lockupUntil", [], "uint64"), _view("shareholderCount", [], "uint32"),
                         _view("maxShareholders", [], "uint32")]
REGISTRY_FACTS_ABI = [_view("isVerified", ["address"], "bool")]


REASON_TEXT = {
    "self": "sender and receiver are the same wallet",
    "balance": "not enough shares (including pending requests)",
    "frozen": "a wallet in this transfer is frozen by the transfer agent",
    "lockup": "the lock-up period is still active; shares cannot move yet",
    "not_verified": "the sender or the receiver is not KYC-verified for this company",
    "cap": "the company has reached its maximum number of shareholders",
}


def transfer_blocker(f: dict, shares: int, *, pending: int = 0) -> str | None:
    """First rule a secondary transfer breaks, as a reason code (same codes as the on-chain custom errors), else None.

    Mirrors BlockIDShareToken._update for a plain transfer: freeze, lock-up, sender and receiver KYC, shareholder
    cap. Used for admin-approval transfers too (the issuer's forcedTransfer skips freeze / lock-up / sender KYC on
    chain, so the platform enforces them here and again in the issuer right before sending).
    """
    if f["balance_from"] < shares + pending:
        return "balance"
    if f["frozen_from"] or f["frozen_to"]:
        return "frozen"
    if f["now"] < f["lockup_until"]:
        return "lockup"
    if not f["from_verified"] or not f["to_verified"]:
        return "not_verified"
    # the contract counts the new holder before it removes a sender who sends everything, so no relief for that
    if f["max_holders"] and f["balance_to"] == 0 and shares > 0 and f["holders"] + 1 > f["max_holders"]:
        return "cap"
    return None


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
