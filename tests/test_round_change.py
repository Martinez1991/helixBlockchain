"""Round-change tests: liveness under a faulty proposer and Byzantine safety."""

from __future__ import annotations

from helix_blockchain.consensus.engine import ConsensusEngine
from helix_blockchain.consensus.messages import ConsensusMessage, MessageType
from helix_blockchain.consensus.validator_set import ValidatorSet
from helix_blockchain.domain.block import ZERO_HASH, Block, genesis_block
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
                node.node_id, node.on_message, lambda idx, r=repo: _aget(r, idx)
            )
            self.nodes[node.node_id] = node

    def node_for(self, pub) -> Node:
        idx = next(i for i, k in enumerate(self.keys) if k.public == pub)
        return self.nodes[f"node-{idx}"]

    def proposer(self, height: int, round_: int) -> Node:
        return self.node_for(self.validators.proposer(height, round_))

    def active(self):
        return [n for nid, n in self.nodes.items() if nid not in self.network.partitioned]


async def _aget(repo, index):
    return repo.get(index)


async def test_round_change_commits_when_round0_proposer_is_down():
    cluster = Cluster(4)  # f=1, quorum=3
    p0 = cluster.proposer(1, 0)
    cluster.network.partitioned.add(p0.node_id)

    # Everyone still up wants a block; the round-0 proposer never proposes.
    for node in cluster.active():
        await node.submit_records(make_records(2))
    await cluster.network.run_until_idle()
    assert all(n.height == 0 for n in cluster.active())  # stalled

    # Each active node times out and round-changes; the round-1 proposer takes over.
    for node in cluster.active():
        await node.force_timeout()
    await cluster.network.run_until_idle()

    active = cluster.active()
    assert len(active) == 3
    # Committed at height 1 despite the round-0 proposer being down -> round change worked.
    assert all(n.height == 1 for n in active), [n.height for n in active]
    # All agree on the same block.
    assert len({n.repo.get(1).hash for n in active}) == 1
    assert p0.height == 0  # the down node committed nothing


async def test_chain_continues_after_a_round_change():
    cluster = Cluster(4)
    p0 = cluster.proposer(1, 0)
    cluster.network.partitioned.add(p0.node_id)
    for node in cluster.active():
        await node.submit_records(make_records(1))
    for node in cluster.active():
        await node.force_timeout()
    await cluster.network.run_until_idle()
    assert all(n.height == 1 for n in cluster.active())

    # Heal the partition; a later height with an honest proposer still commits.
    cluster.network.partitioned.discard(p0.node_id)
    proposer2 = cluster.proposer(2, 0)
    await proposer2.submit_records(make_records(1, base=50))
    await cluster.network.run_until_idle()
    assert proposer2.height == 2


# ── Byzantine safety: locked values and forged claims ──────────────────

def _prepared_round_change(
    keys: list[PrivateKey],
    validators: ValidatorSet,
    height: int,
    target_round: int,
    prepared_round: int,
    block: Block,
):
    """Build `quorum` ROUND_CHANGE messages each carrying a valid prepared cert
    proving `block` was prepared at `prepared_round`."""
    quorum = validators.quorum
    prepares = [
        ConsensusMessage.create(
            type=MessageType.PREPARE,
            height=height,
            round=prepared_round,
            block_hash=block.hash,
            signer=keys[i],
        )
        for i in range(quorum)
    ]
    return [
        ConsensusMessage.create(
            type=MessageType.ROUND_CHANGE,
            height=height,
            round=target_round,
            block_hash=block.hash,
            signer=keys[i],
            block=block,
            prepared_round=prepared_round,
            prepared_cert=prepares,
        )
        for i in range(quorum)
    ]


def test_locked_block_is_reproposed_after_round_change():
    keys = [PrivateKey.generate() for _ in range(4)]
    validators = ValidatorSet([k.public for k in keys])
    prev = genesis_block().hash
    # A block prepared (locked) at round 0 by a quorum.
    proposer0 = validators.proposer(1, 0)
    locked = Block.create(1, prev, 1000, proposer0.to_hex(), make_records(2))

    # Map sorted-validator order to keys so cert senders are valid.
    ordered_keys = [next(k for k in keys if k.public == v) for v in validators]
    rcs = _prepared_round_change(ordered_keys, validators, 1, 1, 0, locked)

    # Feed the round-change quorum to the round-1 proposer's engine.
    p1 = validators.proposer(1, 1)
    p1_key = next(k for k in keys if k.public == p1)
    engine = ConsensusEngine(
        validators=validators, private_key=p1_key, height=1,
        previous_hash=prev, now_ms=lambda: 2000,
    )
    engine.set_pending(make_records(5, base=99))  # different records available

    broadcast = []
    for rc in rcs:
        broadcast.extend(engine.handle(rc).broadcast)

    pre_prepares = [m for m in broadcast if m.type is MessageType.PRE_PREPARE]
    assert pre_prepares, "new proposer did not propose after round change"
    # Safety: it MUST re-propose the locked block, not a fresh one.
    assert pre_prepares[0].block_hash == locked.hash
    assert pre_prepares[0].round == 1


def test_forged_prepared_claim_is_rejected():
    keys = [PrivateKey.generate() for _ in range(4)]
    validators = ValidatorSet([k.public for k in keys])
    prev = genesis_block().hash
    fake_block = Block.create(1, prev, 1000, keys[0].public.to_hex(), make_records(1))

    # A ROUND_CHANGE claiming a locked value but with NO prepared certificate.
    ordered_keys = [next(k for k in keys if k.public == v) for v in validators]
    forged = [
        ConsensusMessage.create(
            type=MessageType.ROUND_CHANGE,
            height=1,
            round=1,
            block_hash=fake_block.hash,
            signer=ordered_keys[i],
            block=fake_block,
            prepared_round=0,
            prepared_cert=[],  # <-- no proof
        )
        for i in range(validators.quorum)
    ]

    p1_key = next(k for k in keys if k.public == validators.proposer(1, 1))
    engine = ConsensusEngine(
        validators=validators, private_key=p1_key, height=1,
        previous_hash=prev, now_ms=lambda: 2000,
    )
    broadcast = []
    for rc in forged:
        broadcast.extend(engine.handle(rc).broadcast)
    # The unbacked claims are ignored, so no quorum forms and nothing is proposed.
    assert [m for m in broadcast if m.type is MessageType.PRE_PREPARE] == []
    assert engine.round == 0


def test_round_change_with_no_lock_allows_fresh_block():
    keys = [PrivateKey.generate() for _ in range(4)]
    validators = ValidatorSet([k.public for k in keys])
    prev = genesis_block().hash
    ordered_keys = [next(k for k in keys if k.public == v) for v in validators]

    # Quorum round-changes with nothing locked.
    rcs = [
        ConsensusMessage.create(
            type=MessageType.ROUND_CHANGE,
            height=1, round=1, block_hash=ZERO_HASH, signer=ordered_keys[i],
            prepared_round=None,
        )
        for i in range(validators.quorum)
    ]
    p1_key = next(k for k in keys if k.public == validators.proposer(1, 1))
    engine = ConsensusEngine(
        validators=validators, private_key=p1_key, height=1,
        previous_hash=prev, now_ms=lambda: 2000,
    )
    engine.set_pending(make_records(2, base=7))
    broadcast = []
    for rc in rcs:
        broadcast.extend(engine.handle(rc).broadcast)
    pre = [m for m in broadcast if m.type is MessageType.PRE_PREPARE]
    assert pre and pre[0].round == 1  # free to propose a fresh block
