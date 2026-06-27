"""The consensus-driving node: glue between engine, storage and transport.

A :class:`Node` runs one BFT height at a time. It keeps pending integrity records
(and pending validator-set changes), feeds them to the :class:`ConsensusEngine`
(which proposes when this node is the round proposer), processes peer messages,
persists finalized blocks, advances to the next height, and drives the
round-change timer for liveness.

**Dynamic membership.** The node is configured with the *genesis* validator set;
the *active* set at the working height is derived by replaying every committed
block's validator changes onto it (effective at the next height). If this node is
not in the active set it has no engine and runs as a passive follower — it still
tracks the chain and can rejoin if re-added. It is transport-agnostic (see
:mod:`.transport`) so it can be tested in-process and deployed over HTTP unchanged.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from helix_blockchain import metrics
from helix_blockchain.consensus.engine import (
    ConsensusEngine,
    StepResult,
    verify_finality,
)
from helix_blockchain.consensus.journal import ConsensusJournalStore, NullJournalStore
from helix_blockchain.consensus.messages import ConsensusMessage
from helix_blockchain.consensus.validator_set import ValidatorSet
from helix_blockchain.domain.block import Block, genesis_block
from helix_blockchain.domain.crypto import PrivateKey, PublicKey
from helix_blockchain.domain.membership import (
    ChangeAction,
    ValidatorChange,
    apply_changes,
    derive_validator_set,
)
from helix_blockchain.domain.records import IntegrityRecord, Verdict
from helix_blockchain.network.discovery import PeerRegistry
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
        peer_registry: PeerRegistry | None = None,
        journal_store: ConsensusJournalStore | None = None,
        max_inbox: int = 10_000,
    ) -> None:
        self.node_id = node_id
        self.private_key = private_key
        self.me = private_key.public
        self._genesis_validators = validators
        self.repo = repo
        self.transport = transport
        self.now_ms = now_ms
        self.on_commit = on_commit
        self.peer_registry = peer_registry or PeerRegistry(self.me.to_hex())
        # Durable write-ahead journal of consensus votes for crash-recovery.
        self._journal_store = journal_store or NullJournalStore()

        self._pending: list[IntegrityRecord] = []
        self._pending_changes: list[ValidatorChange] = []
        # Every record id ever seen (pending or committed): the mempool filter
        # that stops gossiped records from looping or being recorded twice.
        self._mempool_seen: set[str] = set()
        self._lock = asyncio.Lock()
        # Inbound consensus messages are queued and processed by a single worker
        # so the HTTP handler returns immediately. This is what prevents a
        # re-entrant deadlock: a node broadcasting under its lock would otherwise
        # block on a peer that synchronously broadcasts back to it.
        self._inbox: asyncio.Queue[ConsensusMessage] = asyncio.Queue(maxsize=max_inbox)

        if self.repo.height() < 0:
            # Genesis embeds the initial validator set, making the chain
            # self-describing.
            self.repo.append(genesis_block(self._genesis_validators))
        # Derive the active validator set purely from the chain: genesis carries
        # an ADD per initial validator, later blocks carry the changes.
        all_changes = [
            change
            for block in self.repo.load_all()
            for change in block.validator_changes
        ]
        self._active = derive_validator_set(all_changes)
        self._engine = self._new_engine()

    # ── validator set ──────────────────────────────────────────────────
    @property
    def validators(self) -> ValidatorSet:
        """The validator set active at the current working height."""
        return self._active

    def _new_engine(self) -> ConsensusEngine | None:
        """Build the engine for the next height, or ``None`` if this node is not
        a validator in the active set (passive follower)."""
        latest = self.repo.latest()
        assert latest is not None
        if not self._active.contains(self.me):
            return None
        height = latest.index + 1
        return ConsensusEngine(
            validators=self._active,
            private_key=self.private_key,
            height=height,
            previous_hash=latest.hash,
            now_ms=self.now_ms,
            journal=self._journal_store.view(height),
        )

    @property
    def height(self) -> int:
        """Current chain tip index."""
        return self.repo.height()

    @property
    def round(self) -> int:
        """Current consensus round at the working height (0 for a follower)."""
        return self._engine.round if self._engine else 0

    @property
    def is_validator(self) -> bool:
        return self._engine is not None

    # ── public API ─────────────────────────────────────────────────────
    async def submit_records(self, records: list[IntegrityRecord]) -> None:
        """Sign locally observed records, gossip them to peers, and maybe propose."""
        signed = [r.signed(self.private_key) for r in records]
        await self._ingest_records(signed, gossip=True)

    async def receive_records(self, records: list[IntegrityRecord]) -> None:
        """Add records gossiped by a peer (no re-gossip in a full-mesh network)."""
        await self._ingest_records(records, gossip=False)

    async def submit_validator_change(self, change: ValidatorChange) -> None:
        """Queue an add/remove of a validator, gossip it, and maybe propose."""
        await self._ingest_changes([change], gossip=True)

    async def receive_validator_changes(self, changes: list[ValidatorChange]) -> None:
        """Apply validator changes gossiped by a peer (no re-gossip)."""
        await self._ingest_changes(changes, gossip=False)

    async def _ingest_changes(
        self, changes: list[ValidatorChange], *, gossip: bool
    ) -> None:
        async with self._lock:
            fresh = [
                c for c in changes
                if self._is_effective(c) and c not in self._pending_changes
            ]
            if not fresh:
                return
            self._pending_changes.extend(fresh)
            if gossip:
                await self.transport.gossip_changes([c.to_dict() for c in fresh])
            await self._apply_locked(self._set_pending())

    def _is_effective(self, change: ValidatorChange) -> bool:
        """A change is effective only if it actually alters the active set, so
        no-ops (add-existing / remove-absent) never spawn pointless blocks."""
        try:
            present = self._active.contains(PublicKey.from_hex(change.validator))
        except ValueError:
            return False
        if change.action is ChangeAction.ADD:
            return not present
        return present

    async def _ingest_records(
        self, records: list[IntegrityRecord], *, gossip: bool
    ) -> None:
        async with self._lock:
            # Anti-injection: only records validly signed by a current validator
            # are accepted; unsigned/forged records are dropped.
            authentic = []
            for r in records:
                if r.verify(self._active):
                    authentic.append(r)
                else:
                    log.warning("node=%s dropping unsigned/invalid record for %s",
                                self.node_id, r.entity_id)
            metrics.observe_records_dropped(len(records) - len(authentic))
            fresh = [r for r in authentic if r.content_key not in self._mempool_seen]
            if not fresh:
                return
            self._mempool_seen.update(r.content_key for r in fresh)
            self._pending.extend(fresh)
            if gossip:
                await self.transport.gossip_records([r.to_dict() for r in fresh])
            await self._apply_locked(self._set_pending())

    async def ingest_block(self, block: Block) -> None:
        """Apply a finalized block pushed by a peer (proactive gossip)."""
        async with self._lock:
            await self._apply_pushed_block_locked(block)

    async def tick(self) -> None:
        """Re-evaluate whether to propose with the current pending items."""
        async with self._lock:
            await self._apply_locked(self._set_pending())

    async def force_timeout(self) -> None:
        """Trigger a round change for the current height (test/operator hook)."""
        async with self._lock:
            if self._engine is not None:
                await self._apply_locked(self._engine.on_timeout())

    def enqueue_inbound(self, message: ConsensusMessage) -> bool:
        """Queue a peer message for the worker. Returns ``False`` (backpressure)
        if the inbox is full, so the caller can shed load."""
        try:
            self._inbox.put_nowait(message)
        except asyncio.QueueFull:
            log.warning("node=%s inbox full; dropping inbound message", self.node_id)
            metrics.observe_inbound(self._inbox.qsize())
            return False
        metrics.observe_inbound(self._inbox.qsize())
        return True

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
            working_height = self.repo.height() + 1
            if message.height > working_height:
                await self._sync_locked(up_to=message.height - 1)
            if self._engine is None or message.height != self._engine.height:
                return  # follower, or stale/future after sync; ignore
            await self._apply_locked(self._engine.handle(message))

    async def discovery_loop(self, interval_s: float) -> None:
        """Announce ourselves and pull peers' registries to learn new addresses."""
        while True:
            try:
                await self._announce_self()
                discovered = await self.transport.fetch_peers()
                added = self.peer_registry.merge(discovered) if discovered else 0
                if added:
                    log.info("node=%s discovered %d new peer(s)", self.node_id, added)
            except Exception:  # noqa: BLE001 — discovery is best-effort
                log.exception("node=%s discovery iteration failed", self.node_id)
            await asyncio.sleep(interval_s)

    async def _announce_self(self) -> None:
        specs = self.peer_registry.specs()
        if specs:
            await self.transport.announce(specs)

    async def round_timer_loop(self, timeout_s: float) -> None:
        """Background task: round-change if the height stalls for ``timeout_s``."""
        while True:
            start_height = self.height
            await asyncio.sleep(timeout_s)
            async with self._lock:
                if self._engine is None:
                    continue
                stalled = self.height == start_height
                waiting = (
                    bool(self._pending)
                    or bool(self._pending_changes)
                    or self._engine.round > 0
                    or self._engine.proposal is not None
                )
                if stalled and waiting and not self._engine.committed:
                    log.info(
                        "node=%s round timeout at height=%s round=%s",
                        self.node_id, self._engine.height, self._engine.round,
                    )
                    metrics.observe_timeout()
                    await self._apply_locked(self._engine.on_timeout())
                    metrics.observe_round(self._engine.round if self._engine else 0)

    # ── internal (lock held) ───────────────────────────────────────────
    def _set_pending(self) -> StepResult | None:
        if self._engine is None:
            return None
        return self._engine.set_pending(self._pending, self._pending_changes)

    async def _apply_locked(self, result: StepResult | None) -> None:
        while result is not None:
            for msg in result.broadcast:
                await self.transport.broadcast(msg)
            if result.committed is None:
                return
            appended = self._commit_locked(result.committed)
            if appended is not None:
                await self.transport.gossip_block(appended.to_dict())
            # A fresh engine may immediately propose the next height's items.
            result = self._set_pending()

    def _commit_locked(self, block: Block) -> Block | None:
        if not verify_finality(block, self._active):
            log.warning("node=%s refusing block %s: invalid finality cert",
                        self.node_id, block.index)
            self._engine = self._new_engine()
            return None
        round_ = self._engine.round if self._engine else 0
        self._append_and_advance(block)
        log.info("node=%s committed block height=%s round=%s hash=%s",
                 self.node_id, block.index, round_, block.hash[:12])
        if self.on_commit is not None:
            self.on_commit(block)
        return block

    def _append_and_advance(self, block: Block) -> None:
        """Persist ``block``, forget its committed items, advance the active
        validator set by its changes, and rebuild the engine for the next height."""
        self.repo.append(block)
        self._forget_committed(block)
        # The block is finalized: its height's vote journal is no longer needed.
        self._journal_store.prune_below(block.index + 1)
        if block.validator_changes:
            self._active = apply_changes(self._active, block.validator_changes)
            log.info("node=%s validator set now size=%d quorum=%d after height %s",
                     self.node_id, self._active.size, self._active.quorum, block.index)
        self._engine = self._new_engine()
        tampered = sum(1 for r in block.records if r.verdict is Verdict.TAMPERED)
        metrics.observe_commit(tampered)
        metrics.observe_chain_state(
            height=self.height, validators=self._active.size,
            quorum=self._active.quorum, is_validator=self.is_validator,
            pending=len(self._pending),
        )

    def _forget_committed(self, block: Block) -> None:
        """Drop a committed block's records and changes from local buffers (incl.
        ones we never held), so they are never re-proposed or re-gossiped."""
        committed = {r.content_key for r in block.records}
        self._pending = [r for r in self._pending if r.content_key not in committed]
        self._mempool_seen.update(committed)
        if block.validator_changes:
            applied = set(block.validator_changes)
            self._pending_changes = [
                c for c in self._pending_changes if c not in applied
            ]

    async def _apply_pushed_block_locked(self, block: Block) -> None:
        if block.index != self.repo.height() + 1:
            return  # gap or stale; on-demand pull-sync handles larger gaps
        if block.header.previous_hash != self.repo.latest().hash:  # type: ignore[union-attr]
            return
        if not verify_finality(block, self._active):
            log.warning("node=%s rejecting pushed block %s: invalid finality",
                        self.node_id, block.index)
            return
        self._append_and_advance(block)
        log.info("node=%s applied pushed block height=%s", self.node_id, block.index)
        if self.on_commit is not None:
            self.on_commit(block)
        await self._apply_locked(self._set_pending())

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
            if not verify_finality(block, self._active):
                log.warning("node=%s sync: block %s has invalid finality cert",
                            self.node_id, want)
                break
            self._append_and_advance(block)
            log.info("node=%s synced block height=%s", self.node_id, want)
