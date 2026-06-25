import pytest

from helix_blockchain.domain.block import (
    Block,
    Blockchain,
    ValidationError,
    genesis_block,
)
from helix_blockchain.domain.crypto import PrivateKey
from helix_blockchain.domain.records import IntegrityRecord, Verdict


def make_record(entity: str = "Sensor:1", verdict: Verdict = Verdict.OK) -> IntegrityRecord:
    return IntegrityRecord(
        entity_id=entity,
        attribute="temperature",
        value_hash=IntegrityRecord.hash_value(21.5),
        source_broker="broker-main",
        verdict=verdict,
        observed_at=1_700_000_000_000,
    )


def test_block_hash_is_deterministic():
    b1 = Block.create(1, "0" * 64, 1000, "proposer", [make_record()])
    b2 = Block.create(1, "0" * 64, 1000, "proposer", [make_record()])
    assert b1.hash == b2.hash


def test_block_merkle_root_consistent():
    block = Block.create(1, "0" * 64, 1000, "proposer", [make_record(), make_record("S:2")])
    assert block.has_consistent_merkle_root()


def test_block_serialization_roundtrip():
    block = Block.create(1, "0" * 64, 1000, "proposer", [make_record()])
    restored = Block.from_dict(block.to_dict())
    assert restored.hash == block.hash
    assert restored.records == block.records


def test_chain_append_valid_block():
    chain = Blockchain(genesis_block())
    block = Block.create(1, chain.latest.hash, 1000, "proposer", [make_record()])
    chain.append(block)
    assert chain.height == 1
    assert len(chain) == 2


def test_chain_rejects_bad_previous_hash():
    chain = Blockchain(genesis_block())
    block = Block.create(1, "f" * 64, 1000, "proposer", [make_record()])
    with pytest.raises(ValidationError):
        chain.append(block)


def test_chain_rejects_non_sequential_index():
    chain = Blockchain(genesis_block())
    block = Block.create(2, chain.latest.hash, 1000, "proposer", [make_record()])
    with pytest.raises(ValidationError):
        chain.append(block)


def test_chain_rejects_backwards_timestamp():
    chain = Blockchain(genesis_block(timestamp=5000))
    block = Block.create(1, chain.latest.hash, 1000, "proposer", [make_record()])
    with pytest.raises(ValidationError):
        chain.append(block)


def test_commit_signatures_excluded_from_hash():
    block = Block.create(1, "0" * 64, 1000, "proposer", [make_record()])
    before = block.hash
    key = PrivateKey.generate()
    block.add_commit_signature(key.public, key.sign(block.hash.encode()))
    assert block.hash == before
    assert key.public.to_hex() in block.commit_signatures


def test_tampering_with_record_breaks_merkle_consistency():
    block = Block.create(1, "0" * 64, 1000, "proposer", [make_record()])
    block.records.append(make_record("S:injected"))
    assert not block.has_consistent_merkle_root()
