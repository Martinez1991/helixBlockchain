"""End-to-end consensus tests driving N in-process engines to agreement."""

from __future__ import annotations

import pytest

from helix_blockchain.consensus.engine import ConsensusEngine, verify_finality
from helix_blockchain.consensus.messages import ConsensusMessage, MessageType
from helix_blockchain.consensus.validator_set import ValidatorSet
from helix_blockchain.domain.block import ZERO_HASH
from helix_blockchain.domain.crypto import PrivateKey
from helix_blockchain.domain.records import IntegrityRecord, Verdict


def make_records(n: int = 1) -> list[IntegrityRecord]:
    return [
        IntegrityRecord(
            entity_id=f"Sensor:{i}",
            attribute="temperature",
            value_hash=IntegrityRecord.hash_value(20 + i),
            source_broker="broker-main",
            verdict=Verdict.OK,
            observed_at=1_700_000_000_000,
        )
        for i in range(n)
    ]


class Cluster:
    """A synchronous message bus driving several engines to quiescence."""

    def __init__(self, n: int, height: int = 1, previous_hash: str = ZERO_HASH):
        self.keys = [PrivateKey.generate() for _ in range(n)]
        self.validators = ValidatorSet([k.public for k in self.keys])
        self.clock = 1_700_000_000_000
        self.engines = {
            k.public.to_hex(): ConsensusEngine(
                validators=self.validators,
                private_key=k,
                height=height,
                previous_hash=previous_hash,
                now_ms=lambda: self.clock,
            )
            for k in self.keys
        }
        self.committed: dict[str, object] = {}

    def deliver(self, messages: list[ConsensusMessage], drop_senders: set[str] | None = None):
        """Deliver messages to all engines, recursively spreading new broadcasts.

        ``drop_senders`` simulates fully partitioned validators: they neither
        emit nor receive messages.
        """
        queue = list(messages)
        drop_senders = drop_senders or set()
        while queue:
            msg = queue.pop(0)
            if msg.sender in drop_senders:
                continue
            for node_id, engine in self.engines.items():
                if node_id in self.committed or node_id in drop_senders:
                    continue
                result = engine.handle(msg)
                queue.extend(result.broadcast)
                if result.committed is not None:
                    self.committed[node_id] = result.committed

    def run(self, proposer_records, drop_senders: set[str] | None = None):
        proposer_id = self.validators.proposer(
            next(iter(self.engines.values())).height, 0
        ).to_hex()
        proposer = self.engines[proposer_id]
        first = proposer.propose(proposer_records)
        if first.committed is not None:
            self.committed[proposer_id] = first.committed
        self.deliver(first.broadcast, drop_senders=drop_senders)


@pytest.mark.parametrize("n", [1, 4, 7, 10])
def test_cluster_reaches_agreement(n):
    cluster = Cluster(n)
    cluster.run(make_records(3))

    # Every honest node committed.
    assert len(cluster.committed) == n
    # They all committed the same block hash.
    hashes = {b.hash for b in cluster.committed.values()}  # type: ignore[attr-defined]
    assert len(hashes) == 1
    # The committed block carries a valid BFT finality certificate.
    block = next(iter(cluster.committed.values()))
    assert verify_finality(block, cluster.validators)  # type: ignore[arg-type]
    assert len(block.commit_signatures) >= cluster.validators.quorum  # type: ignore[attr-defined]


def test_tolerates_f_silent_validators():
    # N=4 tolerates f=1. Drop one validator entirely; the rest must still commit.
    cluster = Cluster(4)
    # Silence a follower (not the round-0 proposer); the rest must still commit.
    proposer = cluster.validators.proposer(1, 0).to_hex()
    follower = next(
        v.to_hex() for v in cluster.validators if v.to_hex() != proposer
    )
    cluster.run(make_records(2), drop_senders={follower})

    # The 3 remaining validators (== quorum) still reach agreement.
    assert len(cluster.committed) == 3
    assert follower not in cluster.committed


def test_does_not_commit_below_quorum():
    # N=4, quorum=3. Silence two validators -> only 2 active < quorum -> no commit.
    cluster = Cluster(4)
    proposer = cluster.validators.proposer(1, 0).to_hex()
    followers = [v.to_hex() for v in cluster.validators if v.to_hex() != proposer]
    cluster.run(make_records(2), drop_senders=set(followers[:2]))
    assert len(cluster.committed) == 0


def test_quorum_arithmetic():
    def q(n):
        vs = ValidatorSet([PrivateKey.generate().public for _ in range(n)])
        return vs.max_faulty, vs.quorum

    assert q(1) == (0, 1)
    assert q(4) == (1, 3)
    assert q(7) == (2, 5)
    assert q(10) == (3, 7)


def test_forged_signature_is_ignored():
    cluster = Cluster(4)
    proposer = cluster.validators.proposer(1, 0).to_hex()
    victim = next(v.to_hex() for v in cluster.validators if v.to_hex() != proposer)
    attacker = PrivateKey.generate()  # not in the validator set

    # Attacker fabricates a PREPARE claiming to be from `victim` but signs it itself.
    forged = ConsensusMessage(
        type=MessageType.PREPARE,
        height=1,
        round=0,
        block_hash="ab" * 32,
        sender=victim,
        signature=attacker.sign(b"whatever").hex(),
    )
    engine = cluster.engines[proposer]
    result = engine.handle(forged)
    assert result.broadcast == []
    assert result.committed is None


def test_non_proposer_pre_prepare_rejected():
    cluster = Cluster(4)
    proposer = cluster.validators.proposer(1, 0).to_hex()
    non_proposer_key = next(
        k for k in cluster.keys if k.public.to_hex() != proposer
    )
    from helix_blockchain.domain.block import Block

    block = Block.create(1, ZERO_HASH, cluster.clock, non_proposer_key.public.to_hex(), [])
    rogue = ConsensusMessage.create(
        type=MessageType.PRE_PREPARE,
        height=1,
        round=0,
        block_hash=block.hash,
        signer=non_proposer_key,
        block=block,
    )
    # A validator that is itself not the proposer must reject this pre-prepare.
    other = next(
        nid for nid in cluster.engines if nid not in (proposer, non_proposer_key.public.to_hex())
    )
    result = cluster.engines[other].handle(rogue)
    assert result.broadcast == []
    assert result.committed is None
