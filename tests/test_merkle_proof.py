"""Merkle inclusion-proof endpoint, verifiable offline (#13)."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from helix_blockchain.consensus.validator_set import ValidatorSet
from helix_blockchain.domain.crypto import PrivateKey
from helix_blockchain.domain.merkle import ProofStep, verify_proof
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


def _client_with_block(n_records: int):
    key = PrivateKey.generate()
    node = Node(
        node_id="solo", private_key=key, validators=ValidatorSet([key.public]),
        repo=SqlBlockRepository("sqlite:///:memory:"), transport=NullTransport(),
        now_ms=lambda: 1,
    )
    recs = [
        IntegrityRecord(
            entity_id=f"S:{i}", attribute="t", value_hash=IntegrityRecord.hash_value(i),
            source_broker="b", verdict=Verdict.OK, observed_at=1,
        )
        for i in range(n_records)
    ]
    asyncio.run(node.submit_records(recs))
    return TestClient(create_app(node)), node


def _verify(body) -> bool:
    record = IntegrityRecord.from_dict(body["record"])
    proof = [ProofStep(bytes.fromhex(s["sibling"]), s["right"]) for s in body["proof"]]
    return verify_proof(record.canonical(), proof, bytes.fromhex(body["merkle_root"]))


def test_proof_verifies_offline_for_each_record():
    client, node = _client_with_block(5)
    for i in range(5):
        body = client.get(f"/proof/1/{i}").json()
        assert _verify(body) is True


def test_proof_with_single_record():
    client, _ = _client_with_block(1)
    assert _verify(client.get("/proof/1/0").json()) is True


def test_tampered_record_fails_verification():
    client, _ = _client_with_block(3)
    body = client.get("/proof/1/1").json()
    body["record"]["value_hash"] = IntegrityRecord.hash_value(999)  # tamper
    assert _verify(body) is False


def test_proof_404s():
    client, _ = _client_with_block(2)
    assert client.get("/proof/99/0").status_code == 404   # no such block
    assert client.get("/proof/1/9").status_code == 404     # record index OOR
