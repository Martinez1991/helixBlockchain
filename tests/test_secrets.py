"""Secret management: file-based secrets and token rotation (#6)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from helix_blockchain.config import Settings
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


# ── file-based secrets ─────────────────────────────────────────────────
def test_private_key_read_from_file(tmp_path):
    key = PrivateKey.generate()
    f = tmp_path / "key"
    f.write_text(key.to_hex() + "\n")  # trailing newline trimmed
    settings = Settings(node={"private_key_file": str(f)})
    assert settings.resolved_private_key_hex() == key.to_hex()


def test_inline_private_key_used_when_no_file():
    settings = Settings(node={"private_key_hex": "ab" * 32})
    assert settings.resolved_private_key_hex() == "ab" * 32


def test_cluster_token_read_from_file(tmp_path):
    f = tmp_path / "tok"
    f.write_text("super-secret-token\n")
    settings = Settings(cluster_token_file=str(f))
    assert settings.resolved_cluster_token() == "super-secret-token"


def test_file_takes_precedence_over_inline(tmp_path):
    f = tmp_path / "tok"
    f.write_text("from-file")
    settings = Settings(cluster_token="from-inline", cluster_token_file=str(f))
    assert settings.resolved_cluster_token() == "from-file"


# ── token rotation (multiple accepted tokens) ──────────────────────────
def _client(token: str) -> TestClient:
    key = PrivateKey.generate()
    node = Node(
        node_id="solo", private_key=key, validators=ValidatorSet([key.public]),
        repo=SqlBlockRepository("sqlite:///:memory:"), transport=NullTransport(),
        now_ms=lambda: 1,
    )
    return TestClient(create_app(node, debug_api=True, cluster_token=token))


def test_rotation_accepts_both_old_and_new_tokens():
    client = _client("new-token,old-token")
    for tok in ("new-token", "old-token"):
        r = client.post("/admin/submit", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200


def test_rotation_rejects_unknown_token():
    client = _client("new-token,old-token")
    r = client.post("/admin/submit", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_build_node_tolerates_self_in_peers(monkeypatch):
    # k8s gives every pod the same full peer list (including itself).
    from helix_blockchain import app
    from helix_blockchain.config import Peer

    k = PrivateKey.generate()
    other = PrivateKey.generate().public
    settings = Settings(
        node={"private_key_hex": k.to_hex()},
        storage={"url": "sqlite:///:memory:"},
    )
    settings.consensus.peers = [Peer("self", "h", 8000, k.public),
                                Peer("other", "h2", 8000, other)]
    node, _transport, _wh = app.build_node(settings)
    assert node.validators.size == 2  # self deduped against the peer entry
