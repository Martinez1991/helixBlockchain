"""Crash-recovery: consensus vote journal (WAL) prevents equivocation."""

from __future__ import annotations

from helix_blockchain.consensus.engine import ConsensusEngine
from helix_blockchain.consensus.journal import (
    COMMIT,
    PREPARE,
    InMemoryVoteJournal,
    SqlConsensusJournalStore,
)
from helix_blockchain.consensus.messages import ConsensusMessage, MessageType
from helix_blockchain.consensus.validator_set import ValidatorSet
from helix_blockchain.domain.block import Block, genesis_block
from helix_blockchain.domain.crypto import PrivateKey
from helix_blockchain.domain.records import IntegrityRecord, Verdict
from helix_blockchain.network.node import Node
from helix_blockchain.storage.sql import SqlBlockRepository


class CollectingTransport:
    def __init__(self):
        self.sent = []

    async def broadcast(self, m):
        self.sent.append(m)

    async def fetch_block(self, i):
        return None

    async def gossip_records(self, r): ...
    async def gossip_changes(self, c): ...
    async def gossip_block(self, b): ...
    async def fetch_peers(self):
        return []

    async def announce(self, specs): ...


def make_records(n: int, base: int = 0):
    return [
        IntegrityRecord(
            entity_id=f"S:{base + i}", attribute="t",
            value_hash=IntegrityRecord.hash_value(i), source_broker="b",
            verdict=Verdict.OK, observed_at=1,
        )
        for i in range(n)
    ]


def cluster(n: int):
    keys = [PrivateKey.generate() for _ in range(n)]
    return keys, ValidatorSet([k.public for k in keys])


def proposer_pre_prepare(keys, validators, prev, block):
    pk = next(k for k in keys if k.public == validators.proposer(1, 0))
    return ConsensusMessage.create(
        type=MessageType.PRE_PREPARE, height=1, round=0,
        block_hash=block.hash, signer=pk, block=block,
    ), pk


# ── equivocation guard ─────────────────────────────────────────────────
def test_refuses_to_prepare_a_block_conflicting_with_journal():
    keys, validators = cluster(4)
    prev = genesis_block(validators).hash
    proposer = validators.proposer(1, 0)
    block = Block.create(1, prev, 1000, proposer.to_hex(), make_records(2))

    # A follower whose journal already records a PREPARE for a DIFFERENT hash.
    follower = next(k for k in keys if k.public != proposer)
    journal = InMemoryVoteJournal()
    journal.record_vote(0, PREPARE, "ff" * 32)  # voted for something else
    engine = ConsensusEngine(
        validators=validators, private_key=follower, height=1,
        previous_hash=prev, now_ms=lambda: 2000, journal=journal,
    )
    pre_prepare, _ = proposer_pre_prepare(keys, validators, prev, block)
    result = engine.handle(pre_prepare)

    assert result.broadcast == []  # refused to equivocate
    assert engine.proposal is None


def test_prepares_normally_when_journal_matches():
    keys, validators = cluster(4)
    prev = genesis_block(validators).hash
    proposer = validators.proposer(1, 0)
    block = Block.create(1, prev, 1000, proposer.to_hex(), make_records(2))
    follower = next(k for k in keys if k.public != proposer)

    journal = InMemoryVoteJournal()
    journal.record_vote(0, PREPARE, block.hash)  # same hash -> idempotent
    engine = ConsensusEngine(
        validators=validators, private_key=follower, height=1,
        previous_hash=prev, now_ms=lambda: 2000, journal=journal,
    )
    pre_prepare, _ = proposer_pre_prepare(keys, validators, prev, block)
    result = engine.handle(pre_prepare)

    prepares = [m for m in result.broadcast if m.type is MessageType.PREPARE]
    assert prepares and prepares[0].block_hash == block.hash


def test_engine_records_its_prepare_vote_to_journal():
    keys, validators = cluster(4)
    prev = genesis_block(validators).hash
    proposer = validators.proposer(1, 0)
    block = Block.create(1, prev, 1000, proposer.to_hex(), make_records(1))
    follower = next(k for k in keys if k.public != proposer)

    journal = InMemoryVoteJournal()
    engine = ConsensusEngine(
        validators=validators, private_key=follower, height=1,
        previous_hash=prev, now_ms=lambda: 2000, journal=journal,
    )
    pre_prepare, _ = proposer_pre_prepare(keys, validators, prev, block)
    engine.handle(pre_prepare)
    assert journal.voted_hash(0, PREPARE) == block.hash


def test_restores_prepared_lock_from_journal():
    keys, validators = cluster(4)
    prev = genesis_block(validators).hash
    block = Block.create(1, prev, 1000, validators.proposer(1, 0).to_hex(), make_records(1))

    journal = InMemoryVoteJournal()
    # Simulate having prepared this block at round 2 before a crash.
    cert = [
        ConsensusMessage.create(
            type=MessageType.PREPARE, height=1, round=2,
            block_hash=block.hash, signer=k,
        )
        for k in keys[:validators.quorum]
    ]
    journal.record_prepared(2, block, cert)

    engine = ConsensusEngine(
        validators=validators, private_key=keys[0], height=1,
        previous_hash=prev, now_ms=lambda: 2000, journal=journal,
    )
    assert engine.prepared_round == 2
    assert engine.prepared_block is not None
    assert engine.prepared_block.hash == block.hash


# ── durable SQL journal ────────────────────────────────────────────────
def test_sql_journal_persists_votes_across_views():
    store = SqlConsensusJournalStore("sqlite:///:memory:")
    v = store.view(1)
    v.record_vote(0, PREPARE, "ab" * 32)
    v.record_vote(0, COMMIT, "ab" * 32)
    # A fresh view (as after a restart) reloads the journaled votes.
    reloaded = store.view(1)
    assert reloaded.voted_hash(0, PREPARE) == "ab" * 32
    assert reloaded.voted_hash(0, COMMIT) == "ab" * 32


def test_sql_journal_persists_prepared_and_prunes():
    keys, validators = cluster(4)
    prev = genesis_block(validators).hash
    block = Block.create(1, prev, 1000, validators.proposer(1, 0).to_hex(), make_records(1))
    cert = [
        ConsensusMessage.create(
            type=MessageType.PREPARE, height=1, round=0,
            block_hash=block.hash, signer=k,
        )
        for k in keys[:validators.quorum]
    ]
    store = SqlConsensusJournalStore("sqlite:///:memory:")
    store.view(1).record_prepared(0, block, cert)

    restored = store.view(1).prepared()
    assert restored is not None
    rnd, rblock, rcert = restored
    assert rnd == 0 and rblock.hash == block.hash and len(rcert) == validators.quorum

    # After finalizing height 1, pruning clears its journal.
    store.prune_below(2)
    assert store.view(1).prepared() is None
    assert store.view(1).voted_hash(0, PREPARE) is None


# ── node restart (end-to-end) ──────────────────────────────────────────
async def test_node_restart_does_not_equivocate():
    keys, validators = cluster(4)
    prev = genesis_block(validators).hash
    proposer_key = next(k for k in keys if k.public == validators.proposer(1, 0))
    follower_key = next(k for k in keys if k.public != validators.proposer(1, 0))

    repo = SqlBlockRepository("sqlite:///:memory:")
    store = SqlConsensusJournalStore("sqlite:///:memory:")

    def build_node(transport):
        return Node(
            node_id="n", private_key=follower_key, validators=validators,
            repo=repo, transport=transport, now_ms=lambda: 1000,
            journal_store=store,
        )

    block = Block.create(1, prev, 1000, proposer_key.public.to_hex(), make_records(2))
    pre_prepare = ConsensusMessage.create(
        type=MessageType.PRE_PREPARE, height=1, round=0,
        block_hash=block.hash, signer=proposer_key, block=block,
    )

    t1 = CollectingTransport()
    node1 = build_node(t1)
    await node1.on_message(pre_prepare)
    # It prepared the proposed block and journaled the vote.
    assert any(m.type is MessageType.PREPARE for m in t1.sent)
    assert store.view(1).voted_hash(0, PREPARE) == block.hash

    # "Restart": a fresh Node over the same repo + journal. A Byzantine proposer
    # now offers a DIFFERENT block in the same round; the node must refuse.
    rogue = Block.create(1, prev, 1000, proposer_key.public.to_hex(), make_records(2, base=99))
    rogue_pp = ConsensusMessage.create(
        type=MessageType.PRE_PREPARE, height=1, round=0,
        block_hash=rogue.hash, signer=proposer_key, block=rogue,
    )
    t2 = CollectingTransport()
    node2 = build_node(t2)
    await node2.on_message(rogue_pp)
    assert [m for m in t2.sent if m.type is MessageType.PREPARE] == []
