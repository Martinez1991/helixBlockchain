"""The consensus-driving node: glue between engine, storage and transport.

A :class:`Node` runs one BFT height at a time. It keeps a set of pending
integrity records, feeds them to the :class:`ConsensusEngine` (which proposes
when this node is the round proposer), processes peer messages, persists
finalized blocks, advances to the next height, and drives the round-change timer
for liveness. It is transport-agnostic (see :mod:`.transport`) so it can be
tested in-process and deployed over HTTP unchanged.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from helix_blockchain.consensus.engine import (
    ConsensusEngine,
    StepResult,
    verify_finality,
)
from helix_blockchain.consensus.messages import ConsensusMessage
from helix_blockchain.consensus.validator_set import ValidatorSet
from helix_blockchain.domain.block import Block, genesis_block
from helix_blockchain.domain.crypto import PrivateKey
from helix_blockchain.domain.records import IntegrityRecord
from helix_blockchain.network.transport import Transport
from helix_blockchain.storage.repository import BlockRepository

log = logging.getLogger(__name__)

# A callback invoked with each finalized block (e.g. to drive notifications).
CommitHook = Callable[[Block], None]


class Node:
    def __init__(
        self,
        *,
        node_id: str,
        private_key: PrivateKey,
        validators: ValidatorSet,
        repo: BlockRepository,
        transport: Transport,
        now_ms: Callable[[], int],
        on_commit: CommitHook | None = None,
    ) -> None:
        self.node_id = node_id
        self.private_key = private_key
        self.validators = validators
        self.repo = repo
        self.transport = transport
        self.now_ms = now_ms
        self.on_commit = on_commit

        self._pending: list[IntegrityRecord] = []
        self._lock = asyncio.Lock()
        # Inbound consensus messages are queued and processed by a single worker
        # so the HTTP handler returns immediately. This is what prevents a
        # re-entrant deadlock: a node broadcasting under its lock would otherwise
        # block on a peer that synchronously broadcasts back to it.
        self._inbox: asyncio.Queue[ConsensusMessage] = asyncio.Queue()

        if self.repo.height() < 0:
            self.repo.append(genesis_block())
        self._engine = self._new_engine()

    # ── lifecycle ──────────────────────────────────────────────────────
    def _new_engine(self) -> ConsensusEngine:
        latest = self.repo.latest()
        assert latest is not None
        engine = ConsensusEngine(
            validators=self.validators,
            private_key=self.private_key,
            height=latest.index + 1,
            previous_hash=latest.hash,
            now_ms=self.now_ms,
        )
        return engine

    @property
    def height(self) -> int:
        """Current chain tip index."""
        return self.repo.height()

    @property
    def round(self) -> int:
        """Current consensus round at the working height."""
        return self._engine.round

    # ── public API ─────────────────────────────────────────────────────
    async def submit_records(self, records: list[IntegrityRecord]) -> None:
        """Queue integrity records for inclusion and propose if it's our turn."""
        async with self._lock:
            self._pending.extend(records)
            await self._apply_locked(self._engine.set_pending(self._pending))

    async def tick(self) -> None:
        """Re-evaluate whether to propose with the current pending records."""
        async with self._lock:
            await self._apply_locked(self._engine.set_pending(self._pending))

    async def force_timeout(self) -> None:
        """Trigger a round change for the current height (test/operator hook)."""
        async with self._lock:
            await self._apply_locked(self._engine.on_timeout())

    def enqueue_inbound(self, message: ConsensusMessage) -> None:
        """Queue a peer message for the worker (called from the HTTP handler)."""
        self._inbox.put_nowait(message)

    async def inbound_worker(self) -> None:
        """Process queued inbound messages serially, off the HTTP request path."""
        while True:
            message = await self._inbox.get()
            try:
                await self.on_message(message)
            except Exception:  # noqa: BLE001 — never let one bad message kill the worker
                log.exception("node=%s failed to process inbound message", self.node_id)
            finally:
                self._inbox.task_done()

    async def on_message(self, message: ConsensusMessage) -> None:
        """Handle an inbound consensus message from a peer."""
        async with self._lock:
            if message.height > self._engine.height:
                await self._sync_locked(up_to=message.height - 1)
            if message.height != self._engine.height:
                return  # stale or still-future after sync; ignore
            await self._apply_locked(self._engine.handle(message))

    async def round_timer_loop(self, timeout_s: float) -> None:
        """Background task: round-change if the height stalls for ``timeout_s``."""
        while True:
            start_height = self.height
            await asyncio.sleep(timeout_s)
            async with self._lock:
                stalled = self.height == start_height
                waiting = (
                    bool(self._pending)
                    or self._engine.round > 0
                    or self._engine.proposal is not None
                )
                if stalled and waiting and not self._engine.committed:
                    log.info(
                        "node=%s round timeout at height=%s round=%s",
                        self.node_id, self._engine.height, self._engine.round,
                    )
                    await self._apply_locked(self._engine.on_timeout())

    # ── internal (lock held) ───────────────────────────────────────────
    async def _apply_locked(self, result: StepResult) -> None:
        while True:
            for msg in result.broadcast:
                await self.transport.broadcast(msg)
            if result.committed is None:
                return
            self._commit_locked(result.committed)
            # A fresh engine may immediately propose the next height's records.
            result = self._engine.set_pending(self._pending)

    def _commit_locked(self, block: Block) -> None:
        if not verify_finality(block, self.validators):
            log.warning("node=%s refusing block %s: invalid finality cert",
                        self.node_id, block.index)
            self._engine = self._new_engine()
            return
        self.repo.append(block)
        committed_ids = {r.id for r in block.records}
        self._pending = [r for r in self._pending if r.id not in committed_ids]
        log.info("node=%s committed block height=%s round=%s hash=%s",
                 self.node_id, block.index, self._engine.round, block.hash[:12])
        if self.on_commit is not None:
            self.on_commit(block)
        self._engine = self._new_engine()

    async def _sync_locked(self, up_to: int) -> None:
        """Fetch and apply missing finalized blocks from peers up to ``up_to``."""
        while self.repo.height() < up_to:
            want = self.repo.height() + 1
            block = await self.transport.fetch_block(want)
            if block is None or block.index != want:
                break
            if block.header.previous_hash != self.repo.latest().hash:  # type: ignore[union-attr]
                log.warning("node=%s sync: block %s does not link; aborting",
                            self.node_id, want)
                break
            if not verify_finality(block, self.validators):
                log.warning("node=%s sync: block %s has invalid finality cert",
                            self.node_id, want)
                break
            self.repo.append(block)
            committed_ids = {r.id for r in block.records}
            self._pending = [r for r in self._pending if r.id not in committed_ids]
            self._engine = self._new_engine()
            log.info("node=%s synced block height=%s", self.node_id, want)
