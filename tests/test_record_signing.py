"""Signed integrity records: anti-injection on the mempool path (#4)."""

from __future__ import annotations

from helix_blockchain.consensus.validator_set import ValidatorSet
from helix_blockchain.domain.crypto import PrivateKey
from helix_blockchain.domain.records import IntegrityRecord, Verdict
from helix_blockchain.network.node import Node
from helix_blockchain.network.transport import InMemoryNetwork
from helix_blockchain.storage.sql import SqlBlockRepository


def record(entity: str = "S:1") -> IntegrityRecord:
    return IntegrityRecord(
        entity_id=entity, attribute="temperature",
        value_hash=IntegrityRecord.hash_value(21.5), source_broker="b",
        verdict=Verdict.OK, observed_at=1,
    )


# ── domain ─────────────────────────────────────────────────────────────
def test_sign_and_verify_roundtrip():
    key = PrivateKey.generate()
    vs = ValidatorSet([key.public])
    signed = record().signed(key)
    assert signed.observer == key.public.to_hex()
    assert signed.verify(vs) is True


def test_unsigned_record_does_not_verify():
    vs = ValidatorSet([PrivateKey.generate().public])
    assert record().verify(vs) is False


def test_signature_from_non_validator_rejected():
    outsider = PrivateKey.generate()
    vs = ValidatorSet([PrivateKey.generate().public])
    signed = record().signed(outsider)  # validly signed, but not a validator
    assert signed.verify(vs) is False


def test_tampered_content_breaks_signature():
    from dataclasses import replace

    key = PrivateKey.generate()
    vs = ValidatorSet([key.public])
    signed = record().signed(key)
    forged = replace(signed, value_hash=IntegrityRecord.hash_value(99.9))
    assert forged.verify(vs) is False


def test_signing_is_deterministic():
    key = PrivateKey.generate()
    assert record().signed(key).signature == record().signed(key).signature


def test_content_key_ignores_signer():
    a = record().signed(PrivateKey.generate())
    b = record().signed(PrivateKey.generate())
    assert a.content_key == b.content_key  # same observation, different signers
    assert a.id != b.id  # but distinct full records


# ── node ingestion ─────────────────────────────────────────────────────
class Cluster:
    def __init__(self, n: int):
        self.keys = [PrivateKey.generate() for _ in range(n)]
        self.validators = ValidatorSet([k.public for k in self.keys])
        self.network = InMemoryNetwork()
        self.nodes: dict[str, Node] = {}
        for i, key in enumerate(self.keys):
            repo = SqlBlockRepository("sqlite:///:memory:")
            node = Node(
                node_id=f"node-{i}", private_key=key, validators=self.validators,
                repo=repo, transport=None, now_ms=lambda: 1700000000000,
            )
            node.transport = self.network.register(
                node.node_id, node.on_message, lambda idx, r=repo: _get(r, idx),
                _rec_handler(node),
                lambda payload, nd=node: nd.ingest_block(_blk(payload)),
            )
            self.nodes[node.node_id] = node

    def proposer(self, h, r):
        pub = self.validators.proposer(h, r)
        return self.nodes[f"node-{next(i for i, k in enumerate(self.keys) if k.public == pub)}"]


def _rec_handler(node):
    async def h(payloads):
        await node.receive_records([IntegrityRecord.from_dict(p) for p in payloads])
    return h


def _blk(payload):
    from helix_blockchain.domain.block import Block
    return Block.from_dict(payload)


async def _get(repo, i):
    return repo.get(i)


async def test_node_drops_unsigned_gossiped_record():
    cluster = Cluster(4)
    proposer = cluster.proposer(1, 0)
    # A forged, UNSIGNED record gossiped straight to the proposer.
    await proposer.receive_records([record("S:rogue")])
    await cluster.network.run_until_idle()
    # Nothing committed: the unsigned record was dropped.
    assert all(n.height == 0 for n in cluster.nodes.values())


async def test_node_drops_record_signed_by_non_validator():
    cluster = Cluster(4)
    proposer = cluster.proposer(1, 0)
    outsider = PrivateKey.generate()
    await proposer.receive_records([record("S:rogue").signed(outsider)])
    await cluster.network.run_until_idle()
    assert all(n.height == 0 for n in cluster.nodes.values())


async def test_legitimately_signed_record_is_committed():
    cluster = Cluster(4)
    # submit_records signs with the node's validator key.
    observer = next(iter(cluster.nodes.values()))
    await observer.submit_records([record("S:ok")])
    await cluster.network.run_until_idle()
    assert all(n.height == 1 for n in cluster.nodes.values())
    block = cluster.proposer(1, 0).repo.get(1)
    assert block.records[0].verify(cluster.validators)
