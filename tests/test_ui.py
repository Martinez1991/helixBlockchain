"""Read-only web console (/ui) and its supporting endpoints (#portal)."""

from __future__ import annotations

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
    return TestClient(create_app(node))


def test_ui_served():
    resp = _client().get("/ui")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Helix" in resp.text and "Console" in resp.text


def test_chain_exposes_round_for_the_board():
    body = _client().get("/chain").json()
    assert "round" in body
    assert body["height"] == 0


def test_cors_allows_cross_origin_reads():
    resp = _client().get("/chain", headers={"Origin": "http://localhost:8001"})
    assert resp.headers.get("access-control-allow-origin") == "*"


def test_static_asset_is_packaged():
    from importlib import resources

    html = resources.files("helix_blockchain.static").joinpath("index.html").read_text(
        encoding="utf-8"
    )
    assert "Verificar Merkle" in html  # the console tabs are present
