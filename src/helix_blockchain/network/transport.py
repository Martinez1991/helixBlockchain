"""Peer transport abstraction.

The :class:`Node` depends only on the :class:`Transport` protocol, so the same
consensus logic runs over real HTTP (:class:`HttpTransport`) in production or
over an in-process bus (:class:`InMemoryTransport`) in tests.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

import httpx

from helix_blockchain.config import Peer
from helix_blockchain.consensus.messages import ConsensusMessage
from helix_blockchain.domain.block import Block


class Transport(Protocol):
    async def broadcast(self, message: ConsensusMessage) -> None:
        """Send ``message`` to every peer (best-effort; failures are tolerated)."""

    async def fetch_block(self, index: int) -> Block | None:
        """Fetch a finalized block by index from any peer, for catch-up sync."""


_MessageHandler = Callable[[ConsensusMessage], Awaitable[None]]
_BlockGetter = Callable[[int], Awaitable[Block | None]]


class InMemoryNetwork:
    """An in-process message bus connecting several nodes for tests.

    Broadcasts are *enqueued* rather than delivered synchronously, mirroring the
    fire-and-forget semantics of real HTTP transport. This avoids re-entrant
    lock acquisition (a node broadcasting while holding its own lock would
    otherwise deadlock when a peer replies synchronously). Drain delivery with
    :meth:`run_until_idle`.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, _MessageHandler] = {}
        self._getters: dict[str, _BlockGetter] = {}
        self.partitioned: set[str] = set()
        self._queue: list[tuple[str, ConsensusMessage]] = []

    def register(
        self, node_id: str, on_message: _MessageHandler, get_block: _BlockGetter
    ) -> InMemoryTransport:
        self._handlers[node_id] = on_message
        self._getters[node_id] = get_block
        return InMemoryTransport(self, node_id)

    def _enqueue(self, sender_id: str, message: ConsensusMessage) -> None:
        if sender_id not in self.partitioned:
            self._queue.append((sender_id, message))

    async def _fetch(self, requester_id: str, index: int) -> Block | None:
        if requester_id in self.partitioned:
            return None
        for peer_id, getter in self._getters.items():
            if peer_id == requester_id or peer_id in self.partitioned:
                continue
            block = await getter(index)
            if block is not None:
                return block
        return None

    async def run_until_idle(self, max_steps: int = 10_000) -> None:
        """Deliver queued messages (and any they trigger) until quiescent."""
        steps = 0
        while self._queue:
            steps += 1
            if steps > max_steps:
                raise RuntimeError("network did not reach quiescence")
            sender_id, message = self._queue.pop(0)
            for node_id, handler in list(self._handlers.items()):
                if node_id == sender_id or node_id in self.partitioned:
                    continue
                await handler(message)


class InMemoryTransport:
    """Per-node handle onto an :class:`InMemoryNetwork`."""

    def __init__(self, network: InMemoryNetwork, self_id: str) -> None:
        self._network = network
        self.self_id = self_id

    async def broadcast(self, message: ConsensusMessage) -> None:
        self._network._enqueue(self.self_id, message)

    async def fetch_block(self, index: int) -> Block | None:
        return await self._network._fetch(self.self_id, index)


class HttpTransport:
    """Production transport over HTTP using ``httpx``."""

    def __init__(self, peers: list[Peer], timeout: float = 3.0) -> None:
        self._peers = peers
        self._client = httpx.AsyncClient(timeout=timeout)

    async def broadcast(self, message: ConsensusMessage) -> None:
        payload = message.to_dict()
        for peer in self._peers:
            try:
                await self._client.post(f"{peer.base_url}/consensus", json=payload)
            except httpx.HTTPError:
                # Best-effort: BFT tolerates unreachable peers up to f.
                continue

    async def fetch_block(self, index: int) -> Block | None:
        for peer in self._peers:
            try:
                resp = await self._client.get(f"{peer.base_url}/blocks/{index}")
                if resp.status_code == 200:
                    return Block.from_dict(resp.json())
            except httpx.HTTPError:
                continue
        return None

    async def aclose(self) -> None:
        await self._client.aclose()
