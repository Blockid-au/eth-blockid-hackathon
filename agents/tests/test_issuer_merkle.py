"""Issuer Merkle tree == OpenZeppelin StandardMerkleTree (["address","uint256"])."""
import json
import random
from pathlib import Path

import pytest

from blockid_agents.issuer.merkle import build_tree, verify

FIXTURE = Path(__file__).resolve().parents[2] / "contracts" / "test" / "fixtures" / "dividend_round.json"


def test_root_matches_solidity_fixture():
    fx = json.loads(FIXTURE.read_text())
    tree = build_tree({h["account"]: h["amount"] for h in fx["holders"]})
    assert tree.root == fx["root"]
    assert tree.total == fx["total"]
    for h in fx["holders"]:
        assert tree.proof(h["account"]) == h["proof"]  # identical proofs to the ones forge verifies


def test_openzeppelin_readme_vector():
    # @openzeppelin/merkle-tree README example
    tree = build_tree([("0x1111111111111111111111111111111111111111", 5000000000000000000),
                       ("0x2222222222222222222222222222222222222222", 2500000000000000000)])
    assert tree.root == "0xd4dee0beab2d53f2cc83e567171bd2820e49898130a22622b10ead383e90bd77"


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 7, 8, 9, 16, 33])
def test_all_proofs_verify(n):
    rnd = random.Random(n)
    bal = {"0x" + rnd.randbytes(20).hex(): rnd.randint(1, 10**12) for _ in range(n)}
    tree = build_tree(bal)
    for a, v in bal.items():
        assert verify(tree.root, a, v, tree.proof(a))
        assert not verify(tree.root, a, v + 1, tree.proof(a))


def test_zero_balances_skipped_and_case_insensitive():
    a = "0xAbCdEf0000000000000000000000000000000001"
    t1 = build_tree({a: 5, "0x" + "22" * 20: 0})
    t2 = build_tree({a.lower(): 5})
    assert t1.root == t2.root and len(t1.entries) == 1
    with pytest.raises(ValueError):
        build_tree({"0x" + "22" * 20: 0})
