"""Merkle tree over a block's transactions.

A Merkle root commits to an ordered set of leaves (the integrity records in a
block) with a single 32-byte hash, and lets any single leaf be proven to belong
to the block without revealing the others. This replaces the legacy proof-of-work
as the integrity mechanism: tampering with any record changes the root, which is
signed into the block header and agreed by consensus.

Domain separation: leaves are prefixed with 0x00 and internal nodes with 0x01 to
prevent second-preimage attacks where an internal node is reinterpreted as a leaf.
"""

from __future__ import annotations

from dataclasses import dataclass

from helix_blockchain.domain.crypto import sha256

_LEAF_PREFIX = b"\x00"
_NODE_PREFIX = b"\x01"

# Merkle root of an empty set of leaves: hash of the empty string.
EMPTY_ROOT = sha256(b"")


def _hash_leaf(data: bytes) -> bytes:
    return sha256(_LEAF_PREFIX + data)


def _hash_node(left: bytes, right: bytes) -> bytes:
    return sha256(_NODE_PREFIX + left + right)


def merkle_root(leaves: list[bytes]) -> bytes:
    """Compute the Merkle root of ``leaves``.

    An empty list yields :data:`EMPTY_ROOT`. When a level has an odd number of
    nodes, the last node is duplicated (Bitcoin-style) to pair it.
    """
    if not leaves:
        return EMPTY_ROOT
    level = [_hash_leaf(leaf) for leaf in leaves]
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        level = [_hash_node(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


@dataclass(frozen=True)
class ProofStep:
    """One sibling hash in a Merkle proof and whether it sits on the right."""

    sibling: bytes
    sibling_on_right: bool


def merkle_proof(leaves: list[bytes], index: int) -> list[ProofStep]:
    """Build an inclusion proof for ``leaves[index]``."""
    if not 0 <= index < len(leaves):
        raise IndexError("leaf index out of range")
    level = [_hash_leaf(leaf) for leaf in leaves]
    proof: list[ProofStep] = []
    idx = index
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        if idx % 2 == 0:
            proof.append(ProofStep(sibling=level[idx + 1], sibling_on_right=True))
        else:
            proof.append(ProofStep(sibling=level[idx - 1], sibling_on_right=False))
        level = [_hash_node(level[i], level[i + 1]) for i in range(0, len(level), 2)]
        idx //= 2
    return proof


def verify_proof(leaf: bytes, proof: list[ProofStep], root: bytes) -> bool:
    """Return ``True`` iff ``leaf`` combined with ``proof`` reproduces ``root``."""
    acc = _hash_leaf(leaf)
    for step in proof:
        if step.sibling_on_right:
            acc = _hash_node(acc, step.sibling)
        else:
            acc = _hash_node(step.sibling, acc)
    return acc == root
