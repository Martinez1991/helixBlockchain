import pytest

from helix_blockchain.domain.merkle import (
    EMPTY_ROOT,
    merkle_proof,
    merkle_root,
    verify_proof,
)


def test_empty_root():
    assert merkle_root([]) == EMPTY_ROOT


def test_single_leaf_root_is_stable():
    a = merkle_root([b"only"])
    b = merkle_root([b"only"])
    assert a == b
    assert a != EMPTY_ROOT


def test_order_matters():
    assert merkle_root([b"a", b"b"]) != merkle_root([b"b", b"a"])


def test_tampering_changes_root():
    leaves = [b"r1", b"r2", b"r3"]
    root = merkle_root(leaves)
    tampered = [b"r1", b"X2", b"r3"]
    assert merkle_root(tampered) != root


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 8, 9, 16])
def test_proof_roundtrip_all_indices(n):
    leaves = [f"leaf-{i}".encode() for i in range(n)]
    root = merkle_root(leaves)
    for i in range(n):
        proof = merkle_proof(leaves, i)
        assert verify_proof(leaves[i], proof, root) is True


def test_proof_rejects_wrong_leaf():
    leaves = [b"a", b"b", b"c", b"d"]
    root = merkle_root(leaves)
    proof = merkle_proof(leaves, 1)
    assert verify_proof(b"not-b", proof, root) is False


def test_proof_index_out_of_range():
    with pytest.raises(IndexError):
        merkle_proof([b"a"], 5)


def test_second_preimage_resistance_leaf_vs_node():
    # A leaf value crafted to look like an internal-node concatenation must not
    # collide with the real internal node, thanks to domain-separation prefixes.
    leaves = [b"a", b"b"]
    root = merkle_root(leaves)
    forged_leaf = merkle_root([b"a"]) + merkle_root([b"b"])
    assert merkle_root([forged_leaf]) != root
