import pytest

from helix_blockchain.domain.block import Block, genesis_block
from helix_blockchain.domain.records import IntegrityRecord, Verdict
from helix_blockchain.storage.repository import BlockRepository
from helix_blockchain.storage.sql import DuplicateBlockError, SqlBlockRepository


def make_record(entity: str = "Sensor:1") -> IntegrityRecord:
    return IntegrityRecord(
        entity_id=entity,
        attribute="temperature",
        value_hash=IntegrityRecord.hash_value(21.5),
        source_broker="broker-main",
        verdict=Verdict.OK,
        observed_at=1_700_000_000_000,
    )


@pytest.fixture
def repo() -> SqlBlockRepository:
    r = SqlBlockRepository("sqlite:///:memory:")
    r.append(genesis_block())
    return r


def test_satisfies_repository_protocol(repo):
    assert isinstance(repo, BlockRepository)


def test_empty_repo_height_is_minus_one():
    r = SqlBlockRepository("sqlite:///:memory:")
    assert r.height() == -1
    assert r.latest() is None


def test_append_and_get(repo):
    block = Block.create(1, repo.latest().hash, 1000, "proposer", [make_record()])
    repo.append(block)
    assert repo.height() == 1
    fetched = repo.get(1)
    assert fetched is not None
    assert fetched.hash == block.hash
    assert fetched.records == block.records


def test_roundtrip_preserves_commit_signatures(repo):
    from helix_blockchain.domain.crypto import PrivateKey

    block = Block.create(1, repo.latest().hash, 1000, "proposer", [make_record()])
    key = PrivateKey.generate()
    block.add_commit_signature(key.public, key.sign(block.hash.encode()))
    repo.append(block)
    restored = repo.get(1)
    assert restored.commit_signatures == block.commit_signatures


def test_append_rejects_index_gap(repo):
    block = Block.create(5, repo.latest().hash, 1000, "proposer", [make_record()])
    with pytest.raises(DuplicateBlockError):
        repo.append(block)


def test_append_rejects_duplicate_index(repo):
    block = Block.create(1, repo.latest().hash, 1000, "proposer", [make_record()])
    repo.append(block)
    dup = Block.create(1, repo.latest().hash, 2000, "proposer", [make_record("S:2")])
    with pytest.raises(DuplicateBlockError):
        repo.append(dup)


def test_load_all_is_ordered(repo):
    prev = repo.latest().hash
    ts = 1000
    for i in range(1, 4):
        block = Block.create(i, prev, ts, "proposer", [make_record(f"S:{i}")])
        repo.append(block)
        prev = block.hash
        ts += 1
    chain = repo.load_all()
    assert [b.index for b in chain] == [0, 1, 2, 3]
