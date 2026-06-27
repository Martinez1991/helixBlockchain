"""Peer transport abstraction.

The :class:`Node` depends only on the :class:`Transport` protocol, so the same
consensus logic runs over real HTTP (:class:`HttpTransport`) in production or
over an in-process bus (:class:`InMemoryTransport`) in tests.

Three peer interactions are modelled:

* ``broadcast`` — fan out a signed consensus message (PRE-PREPARE/PREPARE/…).
* ``gossip_records`` — share newly observed integrity records so any node's
  observations reach whichever node is the next proposer (mempool reconciliation).
* ``gossip_block`` — proactively push a finalized block so peers that missed the
  consensus rounds catch up immediately (complements pull-based ``fetch_block``).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import httpx

from helix_blockchain.config import Peer, TlsSettings
from helix_blockchain.consensus.messages import ConsensusMessage
from helix_blockchain.domain.block import Block
from helix_blockchain.network.discovery import PeerRegistry
from helix_blockchain.tls import httpx_tls_kwargs, scheme


class Transport(Protocol):
    async def broadcast(self, message: ConsensusMessage) -> None:
        """Send ``message`` to every peer (best-effort; failures are tolerated)."""

    async def fetch_block(self, index: int) -> Block | None:
        """Fetch a finalized block by index from any peer, for catch-up sync."""

    async def gossip_records(self, records: list[dict[str, Any]]) -> None:
        """Share newly observed integrity records with every peer."""

    async def gossip_changes(self, changes: list[dict[str, Any]]) -> None:
        """Share pending validator-set changes with every peer."""

    async def gossip_block(self, block: dict[str, Any]) -> None:
        """Push a finalized block to every peer."""

    async def fetch_peers(self) -> list[Peer]:
        """Pull peers' registries for discovery (empty if not supported)."""

    async def announce(self, specs: list[str]) -> None:
        """Announce peer specs (including our own) to every peer."""


_MessageHandler = Callable[[ConsensusMessage], Awaitable[None]]
_BlockGetter = Callable[[int], Awaitable[Block | None]]
_PayloadHandler = Callable[[list[dict[str, Any]]], Awaitable[None]]
_RecordsHandler = _PayloadHandler
_ChangesHandler = _PayloadHandler
_BlockHandler = Callable[[dict[str, Any]], Awaitable[None]]


class InMemoryNetwork:
    """An in-process bus connecting several nodes for tests.

    Payloads are *enqueued* rather than delivered synchronously, mirroring the
    fire-and-forget semantics of real HTTP transport. This avoids re-entrant
    lock acquisition (a node sending while holding its own lock would otherwise
    deadlock when a peer replies synchronously). Drain with :meth:`run_until_idle`.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, _MessageHandler] = {}
        self._getters: dict[str, _BlockGetter] = {}
        self._record_handlers: dict[str, _RecordsHandler] = {}
        self._change_handlers: dict[str, _ChangesHandler] = {}
        self._block_handlers: dict[str, _BlockHandler] = {}
        self.partitioned: set[str] = set()
        # Each item is (kind, sender_id, payload).
        self._queue: list[tuple[str, str, Any]] = []

    def register(
        self,
        node_id: str,
        on_message: _MessageHandler,
        get_block: _BlockGetter,
        on_records: _RecordsHandler | None = None,
        on_block: _BlockHandler | None = None,
        on_changes: _ChangesHandler | None = None,
    ) -> InMemoryTransport:
        self._handlers[node_id] = on_message
        self._getters[node_id] = get_block
        if on_records is not None:
            self._record_handlers[node_id] = on_records
        if on_block is not None:
            self._block_handlers[node_id] = on_block
        if on_changes is not None:
            self._change_handlers[node_id] = on_changes
        return InMemoryTransport(self, node_id)

    def _enqueue(self, kind: str, sender_id: str, payload: Any) -> None:
        if sender_id not in self.partitioned:
            self._queue.append((kind, sender_id, payload))

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
        """Deliver everything queued (and anything it triggers) until quiescent."""
        steps = 0
        handlers_by_kind = {
            "msg": self._handlers,
            "records": self._record_handlers,
            "changes": self._change_handlers,
            "block": self._block_handlers,
        }
        while self._queue:
            steps += 1
            if steps > max_steps:
                raise RuntimeError("network did not reach quiescence")
            kind, sender_id, payload = self._queue.pop(0)
            for node_id, handler in list(handlers_by_kind[kind].items()):
                if node_id == sender_id or node_id in self.partitioned:
                    continue
                await handler(payload)


class InMemoryTransport:
    """Per-node handle onto an :class:`InMemoryNetwork`."""

    def __init__(self, network: InMemoryNetwork, self_id: str) -> None:
        self._network = network
        self.self_id = self_id

    async def broadcast(self, message: ConsensusMessage) -> None:
        self._network._enqueue("msg", self.self_id, message)

    async def fetch_block(self, index: int) -> Block | None:
        return await self._network._fetch(self.self_id, index)

    async def gossip_records(self, records: list[dict[str, Any]]) -> None:
        self._network._enqueue("records", self.self_id, records)

    async def gossip_changes(self, changes: list[dict[str, Any]]) -> None:
        self._network._enqueue("changes", self.self_id, changes)

    async def gossip_block(self, block: dict[str, Any]) -> None:
        self._network._enqueue("block", self.self_id, block)

    async def fetch_peers(self) -> list[Peer]:
        return []  # in-process tests wire handlers directly; no discovery needed

    async def announce(self, specs: list[str]) -> None:
        return None


class HttpTransport:
    """Production transport over HTTP(S) using ``httpx``."""

    def __init__(
        self,
        registry: PeerRegistry,
        timeout: float = 3.0,
        cluster_token: str = "",
        tls: TlsSettings | None = None,
    ) -> None:
        self._registry = registry
        self._scheme = scheme(tls) if tls else "http"
        # Use the first token for outbound requests (peers accept any during rotation).
        primary = next((t.strip() for t in cluster_token.split(",") if t.strip()), "")
        headers = {"Authorization": f"Bearer {primary}"} if primary else None
        self._client = httpx.AsyncClient(
            timeout=timeout, headers=headers, **(httpx_tls_kwargs(tls) if tls else {})
        )

    def _url(self, peer: Peer, path: str) -> str:
        return f"{self._scheme}://{peer.host}:{peer.port}{path}"

    async def _post_all(self, path: str, payload: Any) -> None:
        async def _post(peer):
            # Best-effort: BFT tolerates unreachable peers up to f.
            with contextlib.suppress(httpx.HTTPError):
                await self._client.post(self._url(peer, path), json=payload)

        # Peers come from the dynamic registry, so newly discovered validators
        # are reached without a restart. Concurrent so one slow peer can't stall.
        await asyncio.gather(*(_post(p) for p in self._registry.current()))

    async def broadcast(self, message: ConsensusMessage) -> None:
        await self._post_all("/consensus", message.to_dict())

    async def gossip_records(self, records: list[dict[str, Any]]) -> None:
        await self._post_all("/mempool", {"records": records})

    async def gossip_changes(self, changes: list[dict[str, Any]]) -> None:
        await self._post_all("/membership", {"changes": changes})

    async def gossip_block(self, block: dict[str, Any]) -> None:
        await self._post_all("/block", block)

    async def fetch_block(self, index: int) -> Block | None:
        for peer in self._registry.current():
            try:
                resp = await self._client.get(self._url(peer, f"/blocks/{index}"))
                if resp.status_code == 200:
                    return Block.from_dict(resp.json())
            except httpx.HTTPError:
                continue
        return None

    async def fetch_peers(self) -> list[Peer]:
        discovered: list[Peer] = []
        for peer in self._registry.current():
            try:
                resp = await self._client.get(self._url(peer, "/peers"))
                if resp.status_code == 200:
                    for spec in resp.json().get("peers", []):
                        with contextlib.suppress(ValueError):
                            discovered.append(Peer.parse(spec))
            except httpx.HTTPError:
                continue
        return discovered

    async def announce(self, specs: list[str]) -> None:
        await self._post_all("/peers", {"peers": specs})

    async def aclose(self) -> None:
        await self._client.aclose()
