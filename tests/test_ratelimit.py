"""Rate limiting, payload limits and inbound backpressure (#9)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from helix_blockchain.consensus.messages import ConsensusMessage, MessageType
from helix_blockchain.consensus.validator_set import ValidatorSet
from helix_blockchain.domain.crypto import PrivateKey
from helix_blockchain.network.node import Node
from helix_blockchain.network.ratelimit import RateLimiter
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


# ── token bucket ───────────────────────────────────────────────────────
def test_token_bucket_allows_burst_then_blocks():
    clock = [0.0]
    rl = RateLimiter(rate_per_sec=1, burst=3, now=lambda: clock[0])
    assert [rl.allow("a") for _ in range(3)] == [True, True, True]
    assert rl.allow("a") is False  # burst exhausted


def test_token_bucket_refills_over_time():
    clock = [0.0]
    rl = RateLimiter(rate_per_sec=2, burst=2, now=lambda: clock[0])
    assert rl.allow("a") and rl.allow("a")
    assert rl.allow("a") is False
    clock[0] = 1.0  # 1s -> +2 tokens
    assert rl.allow("a") is True


def test_disabled_when_rate_zero():
    rl = RateLimiter(0, 0)
    assert all(rl.allow("a") for _ in range(1000))


def test_buckets_are_per_key():
    clock = [0.0]
    rl = RateLimiter(1, 1, now=lambda: clock[0])
    assert rl.allow("a") and rl.allow("b")  # independent buckets
    assert rl.allow("a") is False


# ── server middleware ──────────────────────────────────────────────────
def _node() -> Node:
    key = PrivateKey.generate()
    return Node(
        node_id="solo", private_key=key, validators=ValidatorSet([key.public]),
        repo=SqlBlockRepository("sqlite:///:memory:"), transport=NullTransport(),
        now_ms=lambda: 1,
    )


def _msg(node) -> dict:
    return ConsensusMessage.create(
        type=MessageType.PREPARE, height=1, round=0, block_hash="ab" * 32,
        signer=node.private_key,
    ).to_dict()


def test_rate_limit_returns_429():
    node = _node()
    client = TestClient(create_app(node, rate_limit_rps=1, rate_limit_burst=2))
    codes = [client.post("/consensus", json=_msg(node)).status_code for _ in range(4)]
    assert codes[:2] == [200, 200]
    assert 429 in codes[2:]


def test_payload_too_large_returns_413():
    node = _node()
    client = TestClient(create_app(node, max_body_bytes=10))
    # content-length far exceeds the cap.
    resp = client.post("/mempool", json={"records": [{"x": "y" * 1000}]})
    assert resp.status_code == 413


def test_read_endpoints_not_rate_limited():
    node = _node()
    client = TestClient(create_app(node, rate_limit_rps=1, rate_limit_burst=1))
    assert all(client.get("/health").status_code == 200 for _ in range(20))


# ── inbound backpressure ───────────────────────────────────────────────
def test_inbox_full_sheds_load():
    key = PrivateKey.generate()
    node = Node(
        node_id="n", private_key=key, validators=ValidatorSet([key.public]),
        repo=SqlBlockRepository("sqlite:///:memory:"), transport=NullTransport(),
        now_ms=lambda: 1, max_inbox=2,
    )
    msg = ConsensusMessage.create(
        type=MessageType.PREPARE, height=1, round=0, block_hash="ab" * 32,
        signer=key,
    )
    assert node.enqueue_inbound(msg) is True
    assert node.enqueue_inbound(msg) is True
    assert node.enqueue_inbound(msg) is False  # full -> shed
