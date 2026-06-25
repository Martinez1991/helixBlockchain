"""Integration tests: full nodes (engine + storage + transport) over an
in-process network, across multiple block heights."""

from __future__ import annotations

import pytest

from helix_blockchain.consensus.engine import verify_finality
from helix_blockchain.consensus.validator_set import ValidatorSet
from helix_blockchain.domain.crypto import PrivateKey
from helix_blockchain.domain.records import IntegrityRecord, Verdict
from helix_blockchain.network.node import Node
from helix_blockchain.network.transport import InMemoryNetwork
from helix_blockchain.storage.sql import SqlBlockRepository


def make_records(n: int, base: int = 0) -> list[IntegrityRecord]:
    return [
        IntegrityRecord(
            entity_id=f"Sensor:{base + i}",
            attribute="temperature",
            value_hash=IntegrityRecord.hash_value(20 + base + i),
            source_broker="broker-main",
            verdict=Verdict.OK,
            observed_at=1_700_000_000_000,
        )
        for i in range(n)
    ]


class Fixture:
    def __init__(self, n: int):
        self.keys = [PrivateKey.generate() for _ in range(n)]
        self.validators = ValidatorSet([k.public for k in self.keys])
        self.network = InMemoryNetwork()
        self.clock = 1_700_000_000_000
        self.nodes: list[Node] = []
        for i, key in enumerate(self.keys):
            repo = SqlBlockRepository("sqlite:///:memory:")
            node = Node(
                node_id=f"node-{i}",
                private_key=key,
                validators=self.validators,
                repo=repo,
                transport=None,  # set below
                now_ms=lambda: self.clock,
            )
            node.transport = self.network.register(
                node.node_id,
                node.on_message,
                lambda idx, r=repo: _async_get(r, idx),
            )
            self.nodes.append(node)

    def proposer_for(self, height: int) -> Node:
        pub = self.validators.proposer(height, 0)
        idx = next(i for i, k in enumerate(self.keys) if k.public == pub)
        return self.nodes[idx]


async def _async_get(repo, index):
    return repo.get(index)


@pytest.mark.parametrize("n", [1, 4, 7])
async def test_nodes_commit_block_across_cluster(n):
    fx = Fixture(n)
    proposer = fx.proposer_for(1)
    await proposer.submit_records(make_records(3))
    await fx.network.run_until_idle()

    for node in fx.nodes:
        assert node.height == 1, f"{node.node_id} did not commit"
        block = node.repo.get(1)
        assert verify_finality(block, fx.validators)
    # All nodes agree on the block hash.
    hashes = {node.repo.get(1).hash for node in fx.nodes}
    assert len(hashes) == 1


async def test_multiple_heights_in_sequence():
    fx = Fixture(4)
    for height in range(1, 4):
        proposer = fx.proposer_for(height)
        await proposer.submit_records(make_records(2, base=height * 10))
        await fx.network.run_until_idle()

    for node in fx.nodes:
        assert node.height == 3
        chain = node.repo.load_all()
        assert [b.index for b in chain] == [0, 1, 2, 3]
    # Cross-node agreement at every height.
    for h in range(1, 4):
        assert len({node.repo.get(h).hash for node in fx.nodes}) == 1


async def test_lagging_node_catches_up_via_sync():
    fx = Fixture(4)
    # Pick a lagger that is NOT the proposer for height 1 or 2, so the cluster
    # keeps making progress without it (no round-change needed in the happy path).
    proposer1 = fx.proposer_for(1)
    proposer2 = fx.proposer_for(2)
    lagger = next(
        node for node in fx.nodes if node not in (proposer1, proposer2)
    )
    fx.network.partitioned.add(lagger.node_id)

    proposer = proposer1
    await proposer.submit_records(make_records(2))
    await fx.network.run_until_idle()
    assert lagger.height == 0  # missed it

    # Heal the partition; next height's traffic triggers catch-up sync of h=1.
    fx.network.partitioned.discard(lagger.node_id)
    await proposer2.submit_records(make_records(2, base=99))
    await fx.network.run_until_idle()

    assert lagger.height == 2
    assert lagger.repo.get(1).hash == proposer.repo.get(1).hash


async def test_non_proposer_submission_waits_for_its_turn():
    fx = Fixture(4)
    # A node that is NOT the height-1 proposer submits records.
    proposer1 = fx.proposer_for(1)
    non_proposer = next(node for node in fx.nodes if node is not proposer1)
    await non_proposer.submit_records(make_records(2))
    await fx.network.run_until_idle()
    # No one proposed, so height stays 0 (records remain buffered on that node).
    assert all(node.height == 0 for node in fx.nodes)
