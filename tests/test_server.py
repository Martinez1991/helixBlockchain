"""HTTP API tests using FastAPI's TestClient against a single node."""

from __future__ import annotations

from fastapi.testclient import TestClient

from helix_blockchain.consensus.validator_set import ValidatorSet
from helix_blockchain.domain.crypto import PrivateKey
from helix_blockchain.domain.records import IntegrityRecord, Verdict
from helix_blockchain.network.node import Node
from helix_blockchain.network.server import create_app
from helix_blockchain.storage.sql import SqlBlockRepository


class NullTransport:
    async def broadcast(self, message):
        return None

    async def fetch_block(self, index):
        return None


def build_single_node() -> Node:
    key = PrivateKey.generate()
    validators = ValidatorSet([key.public])  # N=1, quorum=1
    return Node(
        node_id="solo",
        private_key=key,
        validators=validators,
        repo=SqlBlockRepository("sqlite:///:memory:"),
        transport=NullTransport(),
        now_ms=lambda: 1_700_000_000_000,
    )


def test_health():
    client = TestClient(create_app(build_single_node()))
    assert client.get("/health").json() == {"status": "ok"}


def test_chain_reports_genesis():
    client = TestClient(create_app(build_single_node()))
    body = client.get("/chain").json()
    assert body["height"] == 0
    assert body["validators"] == 1
    assert body["quorum"] == 1


def test_get_block_genesis_and_missing():
    client = TestClient(create_app(build_single_node()))
    assert client.get("/blocks/0").json()["header"]["index"] == 0
    assert client.get("/blocks/999").status_code == 404


def test_consensus_endpoint_rejects_malformed():
    client = TestClient(create_app(build_single_node()))
    resp = client.post("/consensus", json={"not": "a message"})
    assert resp.status_code == 400


def test_solo_node_commits_via_submit_then_serves_block():
    import asyncio

    node = build_single_node()
    client = TestClient(create_app(node))
    record = IntegrityRecord(
        entity_id="S:1",
        attribute="temperature",
        value_hash=IntegrityRecord.hash_value(21.5),
        source_broker="broker-main",
        verdict=Verdict.OK,
        observed_at=1_700_000_000_000,
    )
    # A solo validator (N=1, quorum=1) finalizes as soon as it proposes.
    asyncio.run(node.submit_records([record]))
    assert node.height == 1
    assert client.get("/blocks/1").json()["records"][0]["entity_id"] == "S:1"
