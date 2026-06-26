"""Dynamic validator membership: domain derivation and on-chain set changes."""

from __future__ import annotations

import pytest

from helix_blockchain.consensus.validator_set import ValidatorSet
from helix_blockchain.domain.block import Block
from helix_blockchain.domain.crypto import PrivateKey
from helix_blockchain.domain.membership import (
    ChangeAction,
    ValidatorChange,
    apply_changes,
)
from helix_blockchain.domain.records import IntegrityRecord, Verdict
from helix_blockchain.network.node import Node
from helix_blockchain.network.transport import InMemoryNetwork
from helix_blockchain.storage.sql import SqlBlockRepository


def record(entity: str) -> IntegrityRecord:
    return IntegrityRecord(
        entity_id=entity, attribute="t", value_hash=IntegrityRecord.hash_value(1),
        source_broker="b", verdict=Verdict.OK, observed_at=1,
    )


# ── domain ─────────────────────────────────────────────────────────────
def test_change_serialization_roundtrip():
    c = ValidatorChange(ChangeAction.ADD, "ab" * 32)
    assert ValidatorChange.from_dict(c.to_dict()) == c


def test_apply_changes_add_and_remove():
    keys = [PrivateKey.generate().public for _ in range(3)]
    vs = ValidatorSet(keys[:2])
    added = apply_changes(vs, [ValidatorChange(ChangeAction.ADD, keys[2].to_hex())])
    assert added.size == 3
    removed = apply_changes(added, [ValidatorChange(ChangeAction.REMOVE, keys[0].to_hex())])
    assert removed.size == 2
    assert not removed.contains(keys[0])


def test_apply_changes_idempotent_noops():
    keys = [PrivateKey.generate().public for _ in range(2)]
    vs = ValidatorSet(keys)
    # Add existing + remove absent -> unchanged.
    out = apply_changes(vs, [
        ValidatorChange(ChangeAction.ADD, keys[0].to_hex()),
        ValidatorChange(ChangeAction.REMOVE, "cd" * 32),
    ])
    assert out.size == 2


def test_apply_changes_rejects_emptying_the_set():
    key = PrivateKey.generate().public
    with pytest.raises(ValueError):
        apply_changes(ValidatorSet([key]), [ValidatorChange(ChangeAction.REMOVE, key.to_hex())])


def test_block_commits_to_validator_changes_via_merkle():
    change = ValidatorChange(ChangeAction.ADD, "ab" * 32)
    block = Block.create(1, "0" * 64, 1, "p", [record("S:1")], [change])
    assert block.has_consistent_merkle_root()
    # Tampering with a change breaks the root.
    block.validator_changes.append(ValidatorChange(ChangeAction.REMOVE, "cd" * 32))
    assert not block.has_consistent_merkle_root()


def test_block_validator_changes_roundtrip():
    change = ValidatorChange(ChangeAction.REMOVE, "ab" * 32)
    block = Block.create(1, "0" * 64, 1, "p", [], [change])
    restored = Block.from_dict(block.to_dict())
    assert restored.validator_changes == [change]
    assert restored.hash == block.hash


# ── node-level ─────────────────────────────────────────────────────────
class Cluster:
    def __init__(self, n: int):
        self.keys = [PrivateKey.generate() for _ in range(n)]
        self.validators = ValidatorSet([k.public for k in self.keys])
        self.network = InMemoryNetwork()
        self.clock = 1_700_000_000_000
        self.nodes: dict[str, Node] = {}
        for i, key in enumerate(self.keys):
            repo = SqlBlockRepository("sqlite:///:memory:")
            node = Node(
                node_id=f"node-{i}", private_key=key, validators=self.validators,
                repo=repo, transport=None, now_ms=lambda: self.clock,
            )
            node.transport = self.network.register(
                node.node_id, node.on_message, lambda idx, r=repo: _aget(r, idx),
                _records_handler(node),
                lambda payload, nd=node: nd.ingest_block(Block.from_dict(payload)),
                _changes_handler(node),
            )
            self.nodes[node.node_id] = node

    def node_for(self, pub) -> Node:
        idx = next(i for i, k in enumerate(self.keys) if k.public == pub)
        return self.nodes[f"node-{idx}"]

    def proposer(self, height: int, round_: int) -> Node:
        return self.node_for(self.validators.proposer(height, round_))


def _records_handler(node: Node):
    async def handle(payloads):
        await node.receive_records([IntegrityRecord.from_dict(p) for p in payloads])
    return handle


def _changes_handler(node: Node):
    async def handle(payloads):
        await node.receive_validator_changes(
            [ValidatorChange.from_dict(p) for p in payloads]
        )
    return handle


async def _aget(repo, index):
    return repo.get(index)


async def test_remove_validator_shrinks_active_set_next_height():
    cluster = Cluster(4)  # quorum 3
    proposer = cluster.proposer(1, 0)
    victim = next(n for n in cluster.nodes.values() if n is not proposer)
    change = ValidatorChange(ChangeAction.REMOVE, victim.private_key.public.to_hex())

    await proposer.submit_validator_change(change)
    await cluster.network.run_until_idle()

    # All committed the membership block at height 1.
    assert all(n.height == 1 for n in cluster.nodes.values())
    # Active set is now 3 for everyone from the next height. With N=3, f=0 so
    # the quorum is 3 (a 3-node BFT set tolerates no Byzantine fault).
    for n in cluster.nodes.values():
        assert n.validators.size == 3
        assert n.validators.quorum == 3
    # The removed node is no longer a validator (passive follower).
    assert victim.is_validator is False
    assert all(n.is_validator for n in cluster.nodes.values() if n is not victim)


async def test_shrunken_cluster_keeps_committing_without_removed_node():
    cluster = Cluster(4)
    proposer = cluster.proposer(1, 0)
    victim = next(n for n in cluster.nodes.values() if n is not proposer)
    await proposer.submit_validator_change(
        ValidatorChange(ChangeAction.REMOVE, victim.private_key.public.to_hex())
    )
    await cluster.network.run_until_idle()
    assert victim.is_validator is False

    # The remaining 3 validators commit a normal block at height 2.
    remaining = [n for n in cluster.nodes.values() if n is not victim]
    new_proposer = cluster.node_for(remaining[0].validators.proposer(2, 0))
    await new_proposer.submit_records([record("S:after")])
    await cluster.network.run_until_idle()

    assert all(n.height == 2 for n in remaining)
    assert len({n.repo.get(2).hash for n in remaining}) == 1


async def test_change_submitted_to_non_proposer_is_gossiped_and_committed():
    cluster = Cluster(4)
    proposer = cluster.proposer(1, 0)
    # Submit the change to a node that is NOT the height-1 proposer.
    submitter = next(n for n in cluster.nodes.values() if n is not proposer)
    victim = next(
        n for n in cluster.nodes.values() if n not in (proposer, submitter)
    )
    await submitter.submit_validator_change(
        ValidatorChange(ChangeAction.REMOVE, victim.private_key.public.to_hex())
    )
    await cluster.network.run_until_idle()

    # Gossip carried the change to the proposer, which committed it.
    assert all(n.height == 1 for n in cluster.nodes.values())
    assert victim.is_validator is False
    assert all(n.validators.size == 3 for n in cluster.nodes.values())


async def test_noop_change_is_ignored():
    cluster = Cluster(3)
    proposer = cluster.proposer(1, 0)
    existing = next(iter(cluster.nodes.values())).private_key.public.to_hex()
    # Adding an already-present validator is a no-op: nothing should be proposed.
    await proposer.submit_validator_change(ValidatorChange(ChangeAction.ADD, existing))
    await cluster.network.run_until_idle()
    assert all(n.height == 0 for n in cluster.nodes.values())


async def test_removed_validator_can_be_added_back():
    cluster = Cluster(4)
    p1 = cluster.proposer(1, 0)
    victim = next(n for n in cluster.nodes.values() if n is not p1)
    vkey = victim.private_key.public.to_hex()

    await p1.submit_validator_change(ValidatorChange(ChangeAction.REMOVE, vkey))
    await cluster.network.run_until_idle()
    assert victim.is_validator is False

    # Re-add it; a current validator proposes the change.
    remaining = [n for n in cluster.nodes.values() if n is not victim]
    p2 = cluster.node_for(remaining[0].validators.proposer(2, 0))
    await p2.submit_validator_change(ValidatorChange(ChangeAction.ADD, vkey))
    await cluster.network.run_until_idle()

    assert victim.is_validator is True
    assert all(n.validators.size == 4 for n in cluster.nodes.values())
