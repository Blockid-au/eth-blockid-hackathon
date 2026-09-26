"""OpenZeppelin StandardMerkleTree-compatible tree for ["address", "uint256"] leaves.

Matches @openzeppelin/merkle-tree `StandardMerkleTree.of(values, ["address","uint256"])`:
  leaf  = keccak256(bytes.concat(keccak256(abi.encode(address, uint256))))
  leaves sorted ascending by hash, laid out in a complete binary tree array
  (tree[len-1-i] = leaves[i]; tree[i] = hashPair(tree[2i+1], tree[2i+2])), sorted-pair hashing.
Proofs verify with OZ MerkleProof (used by DividendDistributor.claim and CapTableAnchor.verify).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..tools.merkle import keccak256, leaf_hash  # same leaf encoding, proven against Solidity


def _hash_pair(a: bytes, b: bytes) -> bytes:
    return keccak256(a + b) if a < b else keccak256(b + a)


def _hex(b: bytes) -> str:
    return "0x" + b.hex()


@dataclass(frozen=True)
class CapTableTree:
    root: str
    total: int
    # lower-case address -> {"amount": int, "proof": [hex32]}
    entries: dict[str, dict]

    def proof(self, address: str) -> list[str]:
        return self.entries[address.lower()]["proof"]


def build_tree(balances: dict[str, int] | list[tuple[str, int]]) -> CapTableTree:
    """balances: address -> amount (zero amounts are skipped). Duplicate addresses are summed."""
    items = balances.items() if isinstance(balances, dict) else balances
    merged: dict[str, int] = {}
    for addr, amt in items:
        a = addr.lower()
        if len(a.removeprefix("0x")) != 40:
            raise ValueError(f"invalid address: {addr}")
        merged[a] = merged.get(a, 0) + int(amt)
    values = [(a, v) for a, v in merged.items() if v > 0]
    if not values:
        raise ValueError("empty cap table / allocation")

    hashed = sorted(((leaf_hash(a, v), a, v) for a, v in values), key=lambda t: t[0])
    n = len(hashed)
    tree: list[bytes] = [b""] * (2 * n - 1)
    for i, (h, _, _) in enumerate(hashed):
        tree[len(tree) - 1 - i] = h
    for i in range(len(tree) - 1 - n, -1, -1):
        tree[i] = _hash_pair(tree[2 * i + 1], tree[2 * i + 2])

    entries: dict[str, dict] = {}
    for i, (_, a, v) in enumerate(hashed):
        idx = len(tree) - 1 - i
        proof = []
        while idx > 0:
            sib = idx + 1 if idx % 2 == 1 else idx - 1
            proof.append(_hex(tree[sib]))
            idx = (idx - 1) // 2
        entries[a] = {"amount": v, "proof": proof}
    return CapTableTree(root=_hex(tree[0]), total=sum(v for _, v in values), entries=entries)


def verify(root: str, address: str, amount: int, proof: list[str]) -> bool:
    node = leaf_hash(address, amount)
    for p in proof:
        node = _hash_pair(node, bytes.fromhex(p.removeprefix("0x")))
    return _hex(node) == root.lower()
