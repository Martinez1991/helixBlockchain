"""Access audit trail on sensitive endpoints (#17)."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi.testclient import TestClient

from helix_blockchain.consensus.validator_set import ValidatorSet
from helix_blockchain.domain.crypto import PrivateKey
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


def _client() -> TestClient:
    key = PrivateKey.generate()
    node = Node(
        node_id="solo", private_key=key, validators=ValidatorSet([key.public]),
        repo=SqlBlockRepository("sqlite:///:memory:"), transport=NullTransport(),
        now_ms=lambda: 1,
    )
    return TestClient(create_app(node, debug_api=True, cluster_token="tok"))


def test_protected_access_is_audited(caplog):
    client = _client()
    with caplog.at_level(logging.INFO, logger="helix.audit"):
        client.post("/admin/submit", headers={"Authorization": "Bearer tok"})
    line = caplog.text
    assert "path=/admin/submit" in line
    assert "authenticated=True" in line
    assert "status=200" in line


def test_unauthenticated_access_is_audited_with_status(caplog):
    client = _client()
    with caplog.at_level(logging.INFO, logger="helix.audit"):
        client.post("/mempool", json={"records": []})  # no token -> 401
    assert "path=/mempool" in caplog.text
    assert "authenticated=False" in caplog.text
    assert "status=401" in caplog.text


def test_health_is_not_audited(caplog):
    client = _client()
    with caplog.at_level(logging.INFO, logger="helix.audit"):
        client.get("/health")
    assert caplog.text == ""  # read/liveness endpoints are not in the audit scope


def test_compliance_docs_exist():
    root = Path(__file__).resolve().parent.parent / "docs" / "compliance"
    assert (root / "lgpd.md").exists()
    assert (root / "data-classification.md").exists()
