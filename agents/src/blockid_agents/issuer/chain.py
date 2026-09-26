"""Thin, thread-safe web3.py v7 wrapper for one chain + one signing account.

- one lock per Chain: nonce allocation, signing, sending and waiting for the receipt are serialised
- fee mode autodetected per tx: EIP-1559 when the latest block has a non-zero base fee (Hoodi),
  legacy gasPrice otherwise (BlockID Chain: zero base fee, eth_gasPrice ~20 wei)
- every transaction waits for its receipt and raises TxFailed on revert
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

from eth_account.signers.local import LocalAccount
from hexbytes import HexBytes
from web3 import Web3
from web3.contract import Contract
from web3.exceptions import ContractCustomError, ContractLogicError

from . import artifacts

log = logging.getLogger(__name__)

TIP_FLOOR = int(os.environ.get("GAS_TIP_FLOOR_WEI", "1000000"))      # 0.001 gwei
TIP_CAP = int(os.environ.get("GAS_TIP_CAP_WEI", "50000000"))         # 0.05 gwei
STUCK_AFTER_S = float(os.environ.get("GAS_STUCK_AFTER_S", "90"))
MAX_BUMPS = int(os.environ.get("GAS_MAX_BUMPS", "4"))


class TxFailed(RuntimeError):
    def __init__(self, msg: str, tx_hash: str | None = None):
        super().__init__(msg)
        self.tx_hash = tx_hash


@dataclass(frozen=True)
class Receipt:
    tx_hash: str
    block: int
    status: int
    gas_used: int
    contract_address: str | None
    logs: list

    @classmethod
    def of(cls, r) -> Receipt:
        return cls(tx_hash=_hex(r["transactionHash"]), block=int(r["blockNumber"]), status=int(r["status"]),
                   gas_used=int(r["gasUsed"]), contract_address=r.get("contractAddress"), logs=list(r["logs"]))


def _hex(v) -> str:
    h = HexBytes(v).hex()
    return h if h.startswith("0x") else "0x" + h


class Chain:
    def __init__(self, name: str, rpc_url: str, chain_id: int, account: LocalAccount | None = None, *,
                 receipt_timeout: float = 300, gas_multiplier: float = 1.25, min_gas_price: int = 0,
                 poll_latency: float = 1.0, w3: Web3 | None = None, read_lag_s: float = 0.0):
        self.name = name
        self.read_lag_s = float(read_lag_s)
        self.rpc_url = rpc_url
        self.chain_id = int(chain_id)
        self.account = account
        self.w3 = w3 or Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 60}))
        self.lock = threading.RLock()
        self.receipt_timeout = receipt_timeout
        self.gas_multiplier = gas_multiplier
        self.min_gas_price = min_gas_price
        self.poll_latency = poll_latency
        self._next_nonce: int | None = None

    # ------------------------------------------------------------------ basics
    @property
    def address(self) -> str:
        if self.account is None:
            raise RuntimeError(f"{self.name}: no signing account configured")
        return self.account.address

    def with_account(self, account: LocalAccount) -> Chain:
        """Another signer on the same RPC (own lock + nonce tracking)."""
        return Chain(self.name, self.rpc_url, self.chain_id, account, receipt_timeout=self.receipt_timeout,
                     gas_multiplier=self.gas_multiplier, min_gas_price=self.min_gas_price,
                     poll_latency=self.poll_latency, w3=self.w3, read_lag_s=self.read_lag_s)

    def check_chain_id(self) -> None:
        actual = self.w3.eth.chain_id
        if actual != self.chain_id:
            raise RuntimeError(f"{self.name}: RPC chain id {actual} != expected {self.chain_id}")

    def block_number(self) -> int:
        return int(self.w3.eth.block_number)

    def balance(self, address: str) -> int:
        return int(self.w3.eth.get_balance(Web3.to_checksum_address(address)))

    def contract(self, name: str, address: str, file: str | None = None) -> Contract:
        abi, _ = artifacts.load(name, file)
        return self.w3.eth.contract(address=Web3.to_checksum_address(address), abi=abi)

    # ------------------------------------------------------------------ fees
    def fee_fields(self) -> dict[str, int]:
        """Lowest fee that still gets included: tip clamped to [GAS_TIP_FLOOR_WEI, GAS_TIP_CAP_WEI]
        (default 0.001–0.05 gwei) and maxFee = 1.25 x base + tip on EIP-1559 chains; on legacy chains the
        node's eth_gasPrice (already the minimum it accepts). Stuck txs are re-sent with higher fees (send())."""
        base = self.w3.eth.get_block("latest").get("baseFeePerGas")
        if base:  # EIP-1559 chain with a live base fee
            try:
                tip = int(self.w3.eth.max_priority_fee)
            except Exception:  # noqa: BLE001 - RPC without eth_maxPriorityFeePerGas
                tip = TIP_CAP
            tip = min(max(tip, TIP_FLOOR), TIP_CAP)
            return {"maxPriorityFeePerGas": tip, "maxFeePerGas": int(base) * 5 // 4 + tip}
        return {"gasPrice": max(int(self.w3.eth.gas_price), self.min_gas_price)}

    @staticmethod
    def _bumped(fees: dict[str, int]) -> dict[str, int]:
        """Replacement-tx fees: +15% on every fee field (nodes require >= +10% to replace)."""
        return {k: v * 115 // 100 + 1 for k, v in fees.items()}

    def expected_gas_price(self) -> int:
        """Price actually expected per gas unit (base fee + tip, or legacy gasPrice) for balance checks."""
        f = self.fee_fields()
        if "gasPrice" in f:
            return int(f["gasPrice"])
        base = int(self.w3.eth.get_block("latest").get("baseFeePerGas") or 0)
        return base + int(f["maxPriorityFeePerGas"])

    # ------------------------------------------------------------------ sending
    def _nonce(self) -> int:
        chain_nonce = int(self.w3.eth.get_transaction_count(self.address, "pending"))
        if self._next_nonce is None or chain_nonce > self._next_nonce:
            self._next_nonce = chain_nonce
        return self._next_nonce

    def send(self, tx: dict[str, Any], *, wait: bool = True) -> Receipt:
        """Fill nonce/gas/fees/chainId, sign, send, wait for the receipt; raise TxFailed on revert."""
        with self.lock:
            base = {k: v for k, v in tx.items() if k in ("to", "data", "value")}
            base["from"] = self.address
            if base.get("to"):
                base["to"] = Web3.to_checksum_address(base["to"])
            base.setdefault("value", 0)
            if "gas" in tx:
                gas = int(tx["gas"])
            else:
                try:
                    gas = int(self.w3.eth.estimate_gas(base) * self.gas_multiplier) + 10_000
                except (ContractLogicError, ContractCustomError) as e:
                    raise TxFailed(f"{self.name}: would revert: {e}") from None
            full = {**base, "gas": gas, "chainId": self.chain_id, **self.fee_fields()}
            last_err: Exception | None = None
            for _attempt in range(3):
                full["nonce"] = self._nonce()
                signed = self.account.sign_transaction(full)
                try:
                    h = self.w3.eth.send_raw_transaction(signed.raw_transaction)
                except Exception as e:  # noqa: BLE001
                    msg = str(e).lower()
                    last_err = e
                    if "nonce too low" in msg or "invalid nonce" in msg or "invalid sequence" in msg:
                        self._next_nonce = None
                        continue
                    if "already known" in msg:
                        h = signed.hash
                    else:
                        raise TxFailed(f"{self.name}: send failed: {e}") from None
                self._next_nonce = full["nonce"] + 1
                tx_hash = _hex(h)
                log.info("%s tx %s sent (nonce %s)", self.name, tx_hash, full["nonce"])
                if not wait:
                    return Receipt(tx_hash, 0, 1, 0, None, [])
                # Low default fees: if not mined within STUCK_AFTER_S, replace the same nonce with +15% fees.
                hashes = [tx_hash]
                for bump in range(MAX_BUMPS):
                    for hh in hashes:  # any earlier version may still be the one that gets mined
                        try:
                            self.w3.eth.wait_for_transaction_receipt(hh, timeout=STUCK_AFTER_S if hh == hashes[-1] else 1,
                                                                     poll_latency=self.poll_latency)
                            return self.wait(hh)
                        except Exception:  # noqa: BLE001 - timeout / not found yet
                            continue
                    fees = self._bumped({k: full[k] for k in ("maxPriorityFeePerGas", "maxFeePerGas", "gasPrice") if k in full})
                    full.update(fees)
                    signed = self.account.sign_transaction(full)
                    try:
                        hh = _hex(self.w3.eth.send_raw_transaction(signed.raw_transaction))
                        hashes.append(hh)
                        log.warning("%s tx nonce %s not mined after %ss; replaced with +15%% fees (bump %s): %s",
                                    self.name, full["nonce"], STUCK_AFTER_S, bump + 1, hh)
                    except Exception as e:  # noqa: BLE001 - e.g. already mined meanwhile
                        log.info("%s replacement not sent (%s); waiting for the original", self.name, e)
                        break
                for hh in reversed(hashes):
                    try:
                        return self.wait(hh)
                    except TxFailed:
                        raise
                    except Exception:  # noqa: BLE001
                        continue
                raise TxFailed(f"{self.name}: tx nonce {full['nonce']} not mined after {MAX_BUMPS} fee bumps", tx_hash)
            raise TxFailed(f"{self.name}: send failed after retries: {last_err}")

    def wait(self, tx_hash: str) -> Receipt:
        r = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=self.receipt_timeout,
                                                     poll_latency=self.poll_latency)
        rec = Receipt.of(r)
        if rec.status != 1:
            raise TxFailed(f"{self.name}: tx reverted: {tx_hash}{self._revert_reason(tx_hash, rec.block)}", tx_hash)
        self._await_reads(rec.block)
        return rec

    def _await_reads(self, block: int) -> None:
        """Load-balanced public RPCs (e.g. HashKey testnet) may serve reads from a node that has not seen the
        block yet; stale reads (balanceOf, code) would make the mirror logic re-issue or fail. Wait until the
        read path reports the receipt's block, then a short grace period."""
        if not self.read_lag_s:
            return
        deadline = time.monotonic() + max(10.0, self.read_lag_s * 5)
        while time.monotonic() < deadline:
            try:
                if int(self.w3.eth.block_number) >= int(block):
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.5)
        time.sleep(self.read_lag_s)

    def _revert_reason(self, tx_hash: str, block: int) -> str:
        try:
            tx = self.w3.eth.get_transaction(tx_hash)
            call = {"from": tx["from"], "to": tx.get("to"), "data": tx["input"], "value": tx["value"]}
            self.w3.eth.call(call, block - 1 if block else "latest")
        except Exception as e:  # noqa: BLE001
            return f" ({e})"
        return ""

    def transact(self, fn, *, value: int = 0) -> Receipt:
        """fn = contract.functions.foo(args...)"""
        return self.send({"to": fn.address, "data": fn._encode_transaction_data(), "value": value})

    def call(self, fn, block: int | str = "latest"):
        return fn.call({"from": self.account.address} if self.account else {}, block_identifier=block)

    def transfer(self, to: str, value: int) -> Receipt:
        return self.send({"to": to, "value": int(value), "data": b""})

    def deploy(self, name: str, *args, file: str | None = None) -> tuple[Contract, Receipt]:
        abi, bytecode = artifacts.load(name, file)
        if not bytecode or bytecode == "0x":
            raise RuntimeError(f"{name}: empty bytecode")
        factory = self.w3.eth.contract(abi=abi, bytecode=bytecode)
        data = factory.constructor(*args).data_in_transaction
        rec = self.send({"data": data, "value": 0})
        if not rec.contract_address:
            raise TxFailed(f"{self.name}: {name} deploy produced no contract address", rec.tx_hash)
        if self.read_lag_s:  # make sure reads can see the new contract before the caller calls it
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and self.w3.eth.get_code(rec.contract_address) in (b"", "0x", None):
                time.sleep(1)
        log.info("%s deployed %s at %s", self.name, name, rec.contract_address)
        return self.w3.eth.contract(address=rec.contract_address, abi=abi), rec
