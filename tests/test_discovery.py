"""Peer discovery: the registry and the /peers exchange endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from helix_blockchain.config import Peer
from helix_blockchain.consensus.validator_set import ValidatorSet
from helix_blockchain.domain.crypto import PrivateKey
from helix_blockchain.network.discovery import PeerRegistry
from helix_blockchain.network.node import Node
from helix_blockchain.network.server import create_app
from helix_blockchain.storage.sql import SqlBlockRepository


def peer(node_id: str, host: str, port: int) -> Peer:
    return Peer(node_id, host, port, PrivateKey.generate().public)


class NullTransport:
    async def broadcast(self, m): ...
    async def fetch_block(self, i): return None
    async def gossip_records(self, r): ...
    async def gossip_changes(self, c): ...
    async def gossip_block(self, b): ...
    async def fetch_peers(self): return []
    async def announce(self, specs): ...


# ── registry ───────────────────────────────────────────────────────────
def test_registry_seed_and_current_excludes_self():
    me = PrivateKey.generate().public
    reg = PeerRegistry(me.to_hex())
    p1, p2 = peer("n1", "h1", 1), peer("n2", "h2", 2)
    reg.seed([p1, p2])
    assert {p.node_id for p in reg.current()} == {"n1", "n2"}


def test_registry_ignores_self():
    me = PrivateKey.generate()
    self_peer = Peer("self", "h", 9, me.public)
    reg = PeerRegistry(me.public.to_hex(), self_peer=self_peer)
    reg.merge([self_peer, peer("other", "h", 1)])
    assert [p.node_id for p in reg.current()] == ["other"]


def test_registry_merge_counts_only_new():
    reg = PeerRegistry(PrivateKey.generate().public.to_hex())
    p1 = peer("n1", "h1", 1)
    assert reg.merge([p1]) == 1
    assert reg.merge([p1]) == 0  # already known


def test_registry_refresh_address_in_place():
    reg = PeerRegistry(PrivateKey.generate().public.to_hex())
    key = PrivateKey.generate().public
    reg.merge([Peer("n", "old", 1, key)])
    reg.merge([Peer("n", "new", 2, key)])  # same pubkey, new address
    current = reg.current()
    assert len(current) == 1
    assert current[0].host == "new" and current[0].port == 2


def test_specs_include_self():
    me = PrivateKey.generate()
    self_peer = Peer("self", "selfhost", 8000, me.public)
    reg = PeerRegistry(me.public.to_hex(), self_peer=self_peer)
    reg.merge([peer("n1", "h1", 1)])
    specs = reg.specs()
    assert any(s.startswith("self@selfhost:8000|") for s in specs)
    assert any(s.startswith("n1@h1:1|") for s in specs)


# ── endpoints ──────────────────────────────────────────────────────────
def build_node() -> Node:
    key = PrivateKey.generate()
    self_peer = Peer("solo", "solo", 8000, key.public)
    registry = PeerRegistry(key.public.to_hex(), self_peer=self_peer)
    return Node(
        node_id="solo", private_key=key, validators=ValidatorSet([key.public]),
        repo=SqlBlockRepository("sqlite:///:memory:"), transport=NullTransport(),
        now_ms=lambda: 1, peer_registry=registry,
    )


def test_get_peers_returns_self_spec():
    client = TestClient(create_app(build_node()))
    specs = client.get("/peers").json()["peers"]
    assert any(s.startswith("solo@solo:8000|") for s in specs)


def test_post_peers_merges_into_registry():
    node = build_node()
    client = TestClient(create_app(node))
    newcomer = peer("node-9", "10.0.0.9", 8000)
    spec = f"node-9@10.0.0.9:8000|{newcomer.public_key.to_hex()}"
    resp = client.post("/peers", json={"peers": [spec]})
    assert resp.json()["added"] == 1
    assert any(p.node_id == "node-9" for p in node.peer_registry.current())


def test_post_peers_rejects_malformed():
    client = TestClient(create_app(build_node()))
    assert client.post("/peers", json={"peers": ["garbage"]}).status_code == 400


def test_peers_endpoints_require_token():
    node = build_node()
    client = TestClient(create_app(node, cluster_token="tok"))
    assert client.get("/peers").status_code == 401
    ok = client.get("/peers", headers={"Authorization": "Bearer tok"})
    assert ok.status_code == 200
