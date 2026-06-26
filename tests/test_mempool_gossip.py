"""Tests for mempool reconciliation (record gossip) and proactive block gossip."""

from __future__ import annotations

from helix_blockchain.consensus.validator_set import ValidatorSet
from helix_blockchain.domain.block import Block
from helix_blockchain.domain.crypto import PrivateKey
from helix_blockchain.domain.records import IntegrityRecord, Verdict
from helix_blockchain.network.node import Node
from helix_blockchain.network.transport import InMemoryNetwork
from helix_blockchain.storage.sql import SqlBlockRepository


def record(entity: str, observed_at: int = 1) -> IntegrityRecord:
    return IntegrityRecord(
        entity_id=entity,
        attribute="temperature",
        value_hash=IntegrityRecord.hash_value(21.5),
        source_broker="broker-main",
        verdict=Verdict.OK,
        observed_at=observed_at,
    )


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
                node_id=f"node-{i}",
                private_key=key,
                validators=self.validators,
                repo=repo,
                transport=None,
                now_ms=lambda: self.clock,
            )
            node.transport = self.network.register(
                node.node_id,
                node.on_message,
                lambda idx, r=repo: _aget(r, idx),
                _records_handler(node),
                _block_handler(node),
            )
            self.nodes[node.node_id] = node

    def node_for(self, pub) -> Node:
        idx = next(i for i, k in enumerate(self.keys) if k.public == pub)
        return self.nodes[f"node-{idx}"]

    def proposer(self, height: int, round_: int) -> Node:
        return self.node_for(self.validators.proposer(height, round_))

    def active(self):
        return [n for nid, n in self.nodes.items() if nid not in self.network.partitioned]


def _records_handler(node: Node):
    async def handle(payloads):
        await node.receive_records([IntegrityRecord.from_dict(p) for p in payloads])

    return handle


def _block_handler(node: Node):
    async def handle(payload):
        await node.ingest_block(Block.from_dict(payload))

    return handle


async def _aget(repo, index):
    return repo.get(index)


async def test_records_observed_by_a_non_proposer_still_get_committed():
    cluster = Cluster(4)
    proposer = cluster.proposer(1, 0)
    # A node that is NOT the round-0 proposer observes a tampering record.
    observer = next(n for n in cluster.nodes.values() if n is not proposer)
    await observer.submit_records([record("Sensor:tampered")])
    await cluster.network.run_until_idle()

    # Gossip carried it to the proposer, which committed it -> all nodes agree.
    assert all(n.height == 1 for n in cluster.nodes.values())
    block = proposer.repo.get(1)
    assert any(r.entity_id == "Sensor:tampered" for r in block.records)
    assert len({n.repo.get(1).hash for n in cluster.nodes.values()}) == 1


async def test_no_duplicate_records_across_blocks():
    cluster = Cluster(4)
    proposer1 = cluster.proposer(1, 0)
    observer = next(n for n in cluster.nodes.values() if n is not proposer1)
    await observer.submit_records([record("Sensor:A")])
    await cluster.network.run_until_idle()
    assert all(n.height == 1 for n in cluster.nodes.values())

    # Drive a second height; the already-committed record must not reappear.
    proposer2 = cluster.proposer(2, 0)
    await proposer2.submit_records([record("Sensor:B")])
    await cluster.network.run_until_idle()

    all_entities = [
        r.entity_id
        for h in (1, 2)
        for r in proposer1.repo.get(h).records
    ]
    assert all_entities.count("Sensor:A") == 1
    assert all_entities.count("Sensor:B") == 1


async def test_gossip_does_not_loop_on_duplicate_records():
    cluster = Cluster(4)
    proposer = cluster.proposer(1, 0)
    observer = next(n for n in cluster.nodes.values() if n is not proposer)
    # Submitting the same record twice must not double-gossip or double-record.
    await observer.submit_records([record("Sensor:X")])
    await observer.submit_records([record("Sensor:X")])
    await cluster.network.run_until_idle()
    assert all(n.height == 1 for n in cluster.nodes.values())
    assert sum(
        1 for r in proposer.repo.get(1).records if r.entity_id == "Sensor:X"
    ) == 1


async def test_proactive_block_push_reaches_partitioned_node_after_heal():
    cluster = Cluster(4)
    # Lagger is not a proposer for heights 1 or 2 -> cluster progresses without it.
    p1, p2 = cluster.proposer(1, 0), cluster.proposer(2, 0)
    lagger = next(n for n in cluster.nodes.values() if n not in (p1, p2))
    cluster.network.partitioned.add(lagger.node_id)

    await p1.submit_records([record("Sensor:1")])
    await cluster.network.run_until_idle()
    assert lagger.height == 0  # missed it

    # Heal: the next committed block is *pushed* to the lagger, which also
    # pulls the block it missed to fill the gap.
    cluster.network.partitioned.discard(lagger.node_id)
    await p2.submit_records([record("Sensor:2")])
    await cluster.network.run_until_idle()

    assert lagger.height == 2
    assert lagger.repo.get(1).hash == p1.repo.get(1).hash
