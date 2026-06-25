"""The consensus-driving node: glue between engine, storage and transport.

A :class:`Node` runs one BFT height at a time. It buffers incoming integrity
records, proposes a block when it is the round proposer, processes peer messages
through the :class:`ConsensusEngine`, persists finalized blocks, and advances to
the next height. It is transport-agnostic (see :mod:`.transport`) so it can be
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

        if self.repo.height() < 0:
            self.repo.append(genesis_block())
        self._engine = self._new_engine()

    # ── lifecycle ──────────────────────────────────────────────────────
    def _new_engine(self) -> ConsensusEngine:
        latest = self.repo.latest()
        assert latest is not None
        return ConsensusEngine(
            validators=self.validators,
            private_key=self.private_key,
            height=latest.index + 1,
            previous_hash=latest.hash,
            now_ms=self.now_ms,
        )

    @property
    def height(self) -> int:
        """Current chain tip index."""
        return self.repo.height()

    # ── public API ─────────────────────────────────────────────────────
    async def submit_records(self, records: list[IntegrityRecord]) -> None:
        """Queue integrity records for inclusion and propose if it's our turn."""
        async with self._lock:
            self._pending.extend(records)
            await self._maybe_propose_locked()

    async def tick(self) -> None:
        """Drive a proposal if records are pending and we are the proposer."""
        async with self._lock:
            await self._maybe_propose_locked()

    async def on_message(self, message: ConsensusMessage) -> None:
        """Handle an inbound consensus message from a peer."""
        async with self._lock:
            if message.height > self._engine.height:
                await self._sync_locked(up_to=message.height - 1)
            if message.height != self._engine.height:
                return  # stale or still-future after sync; ignore
            result = self._engine.handle(message)
            await self._apply_locked(result)

    # ── internal (lock held) ───────────────────────────────────────────
    async def _maybe_propose_locked(self) -> None:
        if not self._pending:
            return
        if not self._engine.is_proposer() or self._engine.phase != 0:
            return
        batch, self._pending = self._pending, []
        log.info("node=%s proposing block height=%s txs=%d",
                 self.node_id, self._engine.height, len(batch))
        result = self._engine.propose(batch)
        await self._apply_locked(result)

    async def _apply_locked(self, result: StepResult) -> None:
        for msg in result.broadcast:
            await self.transport.broadcast(msg)
        if result.committed is not None:
            self._commit_locked(result.committed)
            await self._maybe_propose_locked()

    def _commit_locked(self, block: Block) -> None:
        if not verify_finality(block, self.validators):
            log.warning("node=%s refusing block %s: invalid finality cert",
                        self.node_id, block.index)
            return
        self.repo.append(block)
        log.info("node=%s committed block height=%s hash=%s",
                 self.node_id, block.index, block.hash[:12])
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
            self._engine = self._new_engine()
            log.info("node=%s synced block height=%s", self.node_id, want)
