"""Cluster-token authentication on the peer-to-peer endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from helix_blockchain.consensus.messages import ConsensusMessage, MessageType
from helix_blockchain.consensus.validator_set import ValidatorSet
from helix_blockchain.domain.crypto import PrivateKey
from helix_blockchain.network.node import Node
from helix_blockchain.network.server import create_app
from helix_blockchain.storage.sql import SqlBlockRepository

TOKEN = "s3cr3t-cluster-token"


class NullTransport:
    async def broadcast(self, message):
        return None

    async def fetch_block(self, index):
        return None

    async def gossip_records(self, records):
        return None

    async def gossip_changes(self, changes):
        return None

    async def gossip_block(self, block):
        return None

    async def fetch_peers(self):
        return []

    async def announce(self, specs):
        return None


def build_node() -> Node:
    key = PrivateKey.generate()
    return Node(
        node_id="solo",
        private_key=key,
        validators=ValidatorSet([key.public]),
        repo=SqlBlockRepository("sqlite:///:memory:"),
        transport=NullTransport(),
        now_ms=lambda: 1_700_000_000_000,
    )


def a_message(node: Node) -> dict:
    return ConsensusMessage.create(
        type=MessageType.PREPARE,
        height=1,
        round=0,
        block_hash="ab" * 32,
        signer=node.private_key,
    ).to_dict()


def client(token: str = "") -> tuple[TestClient, Node]:
    node = build_node()
    return TestClient(create_app(node, debug_api=True, cluster_token=token)), node


def test_p2p_rejected_without_token():
    c, node = client(TOKEN)
    assert c.post("/consensus", json=a_message(node)).status_code == 401
    assert c.post("/mempool", json={"records": []}).status_code == 401
    assert c.post("/block", json={}).status_code == 401


def test_p2p_rejected_with_wrong_token():
    c, node = client(TOKEN)
    headers = {"Authorization": "Bearer wrong"}
    assert c.post("/consensus", json=a_message(node), headers=headers).status_code == 401


def test_p2p_accepted_with_correct_token():
    c, node = client(TOKEN)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    assert c.post("/consensus", json=a_message(node), headers=headers).status_code == 200


def test_read_endpoints_stay_open():
    c, _ = client(TOKEN)
    assert c.get("/health").status_code == 200
    assert c.get("/chain").status_code == 200
    assert c.get("/blocks/0").status_code == 200  # genesis, no token needed


def test_auth_disabled_when_no_token():
    c, node = client("")  # no token configured
    assert c.post("/consensus", json=a_message(node)).status_code == 200


def test_admin_submit_requires_token():
    c, _ = client(TOKEN)
    assert c.post("/admin/submit").status_code == 401
    ok = c.post("/admin/submit", headers={"Authorization": f"Bearer {TOKEN}"})
    assert ok.status_code == 200
