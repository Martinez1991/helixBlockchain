"""Genesis bootstrap from a peer (#16)."""

from __future__ import annotations

import asyncio

from helix_blockchain.consensus.validator_set import ValidatorSet
from helix_blockchain.domain.block import Block, genesis_block
from helix_blockchain.domain.crypto import PrivateKey
from helix_blockchain.domain.records import IntegrityRecord, Verdict
from helix_blockchain.network.bootstrap import fetch_genesis, is_valid_genesis


class FetchTransport:
    def __init__(self, block):
        self._block = block

    async def fetch_block(self, index):
        return self._block if index == 0 else None

    async def broadcast(self, m): ...
    async def gossip_records(self, r): ...
    async def gossip_changes(self, c): ...
    async def gossip_block(self, b): ...
    async def fetch_peers(self): return []
    async def announce(self, s): ...


def _vs(n=4):
    return ValidatorSet([PrivateKey.generate().public for _ in range(n)])


def test_is_valid_genesis_accepts_real_genesis():
    assert is_valid_genesis(genesis_block(_vs())) is True


def test_is_valid_genesis_rejects_empty_validator_set():
    # genesis with no embedded validators is not adoptable
    assert is_valid_genesis(genesis_block()) is False


def test_is_valid_genesis_rejects_non_genesis_block():
    rec = IntegrityRecord(
        entity_id="S", attribute="t", value_hash=IntegrityRecord.hash_value(1),
        source_broker="b", verdict=Verdict.OK, observed_at=1,
    )
    block = Block.create(1, "0" * 64, 1, "p", [rec])
    assert is_valid_genesis(block) is False


def test_fetch_genesis_returns_valid_block():
    vs = _vs()
    genesis = genesis_block(vs)
    got = asyncio.run(fetch_genesis(FetchTransport(genesis)))
    assert got is not None and got.hash == genesis.hash


def test_fetch_genesis_rejects_invalid():
    bad = genesis_block()  # no embedded validators
    assert asyncio.run(fetch_genesis(FetchTransport(bad))) is None
    assert asyncio.run(fetch_genesis(FetchTransport(None))) is None


def test_bootstrapped_node_derives_validator_set():
    # A node built over a repo pre-seeded with a peer's genesis derives the same
    # active validator set from the chain — no genesis set needed in its config.
    from helix_blockchain.network.node import Node
    from helix_blockchain.storage.sql import SqlBlockRepository

    keys = [PrivateKey.generate() for _ in range(4)]
    vs = ValidatorSet([k.public for k in keys])
    peer_genesis = genesis_block(vs)

    # A new validator (keys[0]) joins: repo seeded with the fetched genesis.
    repo = SqlBlockRepository("sqlite:///:memory:")
    repo.append(peer_genesis)
    node = Node(
        node_id="joiner", private_key=keys[0],
        validators=ValidatorSet([keys[0].public]),  # unused: repo already seeded
        repo=repo, transport=FetchTransport(peer_genesis), now_ms=lambda: 1,
    )
    assert node.validators.size == 4  # derived from the bootstrapped chain
    assert node.is_validator is True
