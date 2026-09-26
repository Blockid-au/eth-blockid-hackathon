"""Merkle tree compatible with OpenZeppelin StandardMerkleTree / MerkleProof.

Leaf  = keccak256(bytes.concat(keccak256(abi.encode(address, uint256))))
Node  = keccak256(sorted(a, b))

Used by the Dividend agent: the snapshot of holders -> amounts becomes a root that the
issuer Safe publishes on DividendDistributor; each holder claims with a proof.
Pure Python (pycryptodome keccak) so it runs without web3 dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass

from Crypto.Hash import keccak


def keccak256(data: bytes) -> bytes:
    h = keccak.new(digest_bits=256)
    h.update(data)
    return h.digest()


def _abi_encode_address_uint(address: str, amount: int) -> bytes:
    addr = address.lower().removeprefix("0x")
    if len(addr) != 40:
        raise ValueError(f"invalid address: {address}")
    if amount < 0 or amount >= 2**256:
        raise ValueError("amount out of uint256 range")
    return bytes(12) + bytes.fromhex(addr) + amount.to_bytes(32, "big")


def leaf_hash(address: str, amount: int) -> bytes:
    return keccak256(keccak256(_abi_encode_address_uint(address, amount)))


def _hash_pair(a: bytes, b: bytes) -> bytes:
    return keccak256(a + b) if a < b else keccak256(b + a)


@dataclass(frozen=True)
class MerkleDistribution:
    root: str
    total: int
    claims: dict[str, dict]  # address -> {"amount": int, "proof": [hex]}


def build_distribution(allocations: dict[str, int]) -> MerkleDistribution:
    """allocations: checksum-agnostic address -> amount (smallest unit of the pay token)."""
    if not allocations:
        raise ValueError("empty allocation")
    items = sorted((a.lower(), int(v)) for a, v in allocations.items() if int(v) > 0)
    leaves = [leaf_hash(a, v) for a, v in items]

    # Build levels bottom-up; odd node is promoted unchanged (OZ MerkleProof compatible).
    levels = [leaves]
    while len(levels[-1]) > 1:
        cur = levels[-1]
        nxt = []
        for i in range(0, len(cur), 2):
            if i + 1 < len(cur):
                nxt.append(_hash_pair(cur[i], cur[i + 1]))
            else:
                nxt.append(cur[i])
        levels.append(nxt)
    root = levels[-1][0]

    claims: dict[str, dict] = {}
    for idx, (addr, amount) in enumerate(items):
        proof = []
        pos = idx
        for level in levels[:-1]:
            sibling = pos ^ 1
            if sibling < len(level):
                proof.append("0x" + level[sibling].hex())
            pos //= 2
        claims[addr] = {"amount": amount, "proof": proof}

    return MerkleDistribution(root="0x" + root.hex(), total=sum(v for _, v in items), claims=claims)


def verify(root: str, address: str, amount: int, proof: list[str]) -> bool:
    node = leaf_hash(address, amount)
    for p in proof:
        node = _hash_pair(node, bytes.fromhex(p.removeprefix("0x")))
    return "0x" + node.hex() == root.lower()
