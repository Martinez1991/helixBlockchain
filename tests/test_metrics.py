"""Prometheus /metrics endpoint and instrumentation (#5)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from helix_blockchain import metrics
from helix_blockchain.consensus.validator_set import ValidatorSet
from helix_blockchain.domain.crypto import PrivateKey
from helix_blockchain.domain.records import IntegrityRecord, Verdict
from helix_blockchain.network.node import Node
from helix_blockchain.network.server import create_app
from helix_blockchain.storage.sql import SqlBlockRepository


class NullTransport:
    async def broadcast(self, m): ...
    async def fetch_block(self, i): return None
    async def gossip_records(self, r): ...
    async def gossip_changes(self, c): ...
    async def gossip_block(self, b): ...
    async def fetch_peers(self): return []
    async def announce(self, s): ...


def build_node() -> Node:
    key = PrivateKey.generate()
    return Node(
        node_id="solo", private_key=key, validators=ValidatorSet([key.public]),
        repo=SqlBlockRepository("sqlite:///:memory:"), transport=NullTransport(),
        now_ms=lambda: 1_700_000_000_000,
    )


def test_metrics_endpoint_exposes_collectors():
    client = TestClient(create_app(build_node()))
    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.text
    for name in ("helix_chain_height", "helix_blocks_committed_total",
                 "helix_validators_active", "helix_tampering_detected_total"):
        assert name in body


def test_commit_increments_block_and_tampering_counters():
    import asyncio

    node = build_node()
    before_blocks = metrics.BLOCKS_COMMITTED._value.get()
    before_tamper = metrics.TAMPERING_DETECTED._value.get()

    rec = IntegrityRecord(
        entity_id="S:bad", attribute="t", value_hash=IntegrityRecord.hash_value(1),
        source_broker="b", verdict=Verdict.TAMPERED, observed_at=1,
    )
    asyncio.run(node.submit_records([rec]))  # N=1 commits immediately

    assert node.height == 1
    assert metrics.BLOCKS_COMMITTED._value.get() == before_blocks + 1
    assert metrics.TAMPERING_DETECTED._value.get() == before_tamper + 1
    assert metrics.CHAIN_HEIGHT._value.get() == 1
