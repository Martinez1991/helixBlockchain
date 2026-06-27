"""Storage and journal round-trips against the configured database (#10).

Runs against ``HELIX_TEST_DB_URL`` when set (CI provides a Postgres service),
otherwise skips. Proves the SQLAlchemy repository and the consensus journal work
on a real Postgres backend, not just SQLite.
"""

from __future__ import annotations

import os

import pytest

from helix_blockchain.consensus.journal import PREPARE, SqlConsensusJournalStore
from helix_blockchain.consensus.messages import ConsensusMessage, MessageType
from helix_blockchain.consensus.validator_set import ValidatorSet
from helix_blockchain.domain.block import Block, genesis_block
from helix_blockchain.domain.crypto import PrivateKey
from helix_blockchain.domain.records import IntegrityRecord, Verdict
from helix_blockchain.storage.sql import SqlBlockRepository

DB_URL = os.environ.get("HELIX_TEST_DB_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="HELIX_TEST_DB_URL not set")


def _records(n):
    return [
        IntegrityRecord(
            entity_id=f"S:{i}", attribute="t", value_hash=IntegrityRecord.hash_value(i),
            source_broker="b", verdict=Verdict.OK, observed_at=1,
        )
        for i in range(n)
    ]


def test_block_repository_roundtrip_on_real_db():
    repo = SqlBlockRepository(DB_URL)
    keys = [PrivateKey.generate() for _ in range(4)]
    vs = ValidatorSet([k.public for k in keys])
    repo.append(genesis_block(vs))
    block = Block.create(1, repo.latest().hash, 1000, vs.proposer(1, 0).to_hex(), _records(3))
    repo.append(block)
    assert repo.height() == 1
    assert repo.get(1).hash == block.hash
    assert [b.index for b in repo.load_all()] == [0, 1]


def test_consensus_journal_roundtrip_on_real_db():
    store = SqlConsensusJournalStore(DB_URL)
    keys = [PrivateKey.generate() for _ in range(4)]
    vs = ValidatorSet([k.public for k in keys])
    block = Block.create(1, genesis_block(vs).hash, 1000, vs.proposer(1, 0).to_hex(), _records(1))
    cert = [
        ConsensusMessage.create(
            type=MessageType.PREPARE, height=1, round=0, block_hash=block.hash, signer=k,
        )
        for k in keys[: vs.quorum]
    ]
    view = store.view(1)
    view.record_vote(0, PREPARE, block.hash)
    view.record_prepared(0, block, cert)

    reloaded = store.view(1)
    assert reloaded.voted_hash(0, PREPARE) == block.hash
    assert reloaded.prepared()[1].hash == block.hash

    store.prune_below(2)
    assert store.view(1).prepared() is None
