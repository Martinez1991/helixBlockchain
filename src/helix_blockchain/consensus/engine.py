"""IBFT/PBFT-style consensus state machine with round change.

A *pure* state machine: it consumes signed :class:`ConsensusMessage` objects and
returns a :class:`StepResult` describing what to broadcast and whether a block
was finalized. No networking or storage — the surrounding :mod:`helix_blockchain.network`
node transports messages, persists blocks and drives the round timer.

Per height ``h``, round ``r`` (happy path):

1. **PRE-PREPARE** — round ``r``'s proposer broadcasts a block.
2. **PREPARE** — every validator (proposer included) that accepts the proposal
   broadcasts a PREPARE. A quorum of PREPAREs *locks* the block (the validator
   becomes ``prepared`` at round ``r``) and proves agreement on one value.
3. **COMMIT** — a locked validator broadcasts a COMMIT carrying a commit seal
   over the block hash; a quorum of COMMITs finalizes the block.

**Round change (liveness).** If a round does not commit in time the node calls
:meth:`on_timeout`, which broadcasts a ROUND_CHANGE for the next round carrying
its *prepared certificate* (proof of any locked value). On ``f+1`` ROUND_CHANGEs
for a higher round a node accelerates by sending its own; on a quorum it adopts
the new round, and its proposer re-proposes the highest locked value among the
certificate (preserving safety) or a fresh block if none is locked.
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from dataclasses import dataclass, field

from helix_blockchain.consensus.journal import (
    COMMIT,
    PREPARE,
    NullVoteJournal,
    VoteJournal,
)
from helix_blockchain.consensus.messages import ConsensusMessage, MessageType
from helix_blockchain.consensus.validator_set import ValidatorSet
from helix_blockchain.domain.block import ZERO_HASH, Block
from helix_blockchain.domain.crypto import PrivateKey, PublicKey
from helix_blockchain.domain.membership import ValidatorChange
from helix_blockchain.domain.records import IntegrityRecord


class Phase(enum.IntEnum):
    NEW_ROUND = 0
    PRE_PREPARED = 1
    PREPARED = 2
    COMMITTED = 3


@dataclass
class StepResult:
    """What the caller should do after a step: broadcast messages, maybe commit."""

    broadcast: list[ConsensusMessage] = field(default_factory=list)
    committed: Block | None = None

    def extend(self, other: StepResult) -> None:
        self.broadcast.extend(other.broadcast)
        if other.committed is not None:
            self.committed = other.committed


class ConsensusEngine:
    def __init__(
        self,
        *,
        validators: ValidatorSet,
        private_key: PrivateKey,
        height: int,
        previous_hash: str,
        now_ms: Callable[[], int],
        journal: VoteJournal | None = None,
    ) -> None:
        if not validators.contains(private_key.public):
            raise ValueError("this node is not part of the validator set")
        self.validators = validators
        self.private_key = private_key
        self.me: PublicKey = private_key.public
        self.height = height
        self.previous_hash = previous_hash
        self._now_ms = now_ms
        # Durable record of our own votes, so a restart cannot equivocate.
        self._journal = journal or NullVoteJournal()

        self._pending: list[IntegrityRecord] = []
        self._pending_changes: list[ValidatorChange] = []
        # The lock: the highest round at which we prepared, and its proof.
        self.prepared_round: int | None = None
        self.prepared_block: Block | None = None
        self._prepared_cert: list[ConsensusMessage] = []
        # Restore the prepared lock from the journal (crash-recovery).
        restored = self._journal.prepared()
        if restored is not None:
            self.prepared_round, self.prepared_block, self._prepared_cert = restored
        # Round-change messages seen, keyed by target round then sender.
        self._round_changes: dict[int, dict[str, ConsensusMessage]] = {}
        self._rc_sent: set[int] = set()
        # PREPARE/COMMIT messages for rounds we have not adopted yet.
        self._buffer: list[ConsensusMessage] = []
        self.start_round(0)

    # ── round lifecycle ────────────────────────────────────────────────
    def start_round(self, round_: int) -> None:
        self.round = round_
        self.phase = Phase.NEW_ROUND
        self.proposal: Block | None = None
        self._prepares: dict[str, dict[str, ConsensusMessage]] = {}
        self._commits: dict[str, dict[str, str]] = {}

    @property
    def proposer(self) -> PublicKey:
        return self.validators.proposer(self.height, self.round)

    def is_proposer(self) -> bool:
        return self.me == self.proposer

    @property
    def committed(self) -> bool:
        return self.phase == Phase.COMMITTED

    # ── pending records / proposing ────────────────────────────────────
    def set_pending(
        self,
        records: list[IntegrityRecord],
        changes: list[ValidatorChange] | None = None,
    ) -> StepResult:
        """Update what this node wants to include and propose if due."""
        self._pending = list(records)
        self._pending_changes = list(changes or [])
        result = StepResult()
        self._maybe_propose_round0(result)
        return result

    def propose(self, records: list[IntegrityRecord]) -> StepResult:
        """Convenience for round 0: set pending and propose immediately."""
        return self.set_pending(records)

    def _maybe_propose_round0(self, result: StepResult) -> None:
        if (
            self.round == 0
            and self.phase == Phase.NEW_ROUND
            and self.is_proposer()
            and (self._pending or self._pending_changes)
        ):
            block = self._build_block(self._pending)
            self._emit_pre_prepare(block, round_change_cert=None, result=result)

    def _build_block(self, records: list[IntegrityRecord]) -> Block:
        return Block.create(
            index=self.height,
            previous_hash=self.previous_hash,
            timestamp=self._now_ms(),
            proposer=self.me.to_hex(),
            records=records,
            validator_changes=self._pending_changes,
        )

    def _emit_pre_prepare(
        self,
        block: Block,
        round_change_cert: list[ConsensusMessage] | None,
        result: StepResult,
    ) -> None:
        pre_prepare = ConsensusMessage.create(
            type=MessageType.PRE_PREPARE,
            height=self.height,
            round=self.round,
            block_hash=block.hash,
            signer=self.private_key,
            block=block,
            round_change_cert=round_change_cert,
        )
        result.broadcast.append(pre_prepare)
        self._accept_proposal(block, result)

    # ── message handling ───────────────────────────────────────────────
    def handle(self, msg: ConsensusMessage) -> StepResult:
        result = StepResult()
        if msg.height != self.height:
            return result
        if not self._authentic(msg):
            return result
        if msg.type is MessageType.ROUND_CHANGE:
            self._handle_round_change(msg, result)
        elif msg.type is MessageType.PRE_PREPARE:
            self._handle_pre_prepare(msg, result)
        elif msg.type is MessageType.PREPARE:
            self._handle_vote(msg, result, self._handle_prepare)
        elif msg.type is MessageType.COMMIT:
            self._handle_vote(msg, result, self._handle_commit)
        return result

    def on_timeout(self) -> StepResult:
        """Give up on the current round and broadcast a ROUND_CHANGE."""
        result = StepResult()
        if self.committed:
            return result
        target = self.round + 1
        while target in self._rc_sent:
            target += 1
        self._send_round_change(target, result)
        self._process_round_changes(result)
        return result

    def _authentic(self, msg: ConsensusMessage) -> bool:
        try:
            sender = PublicKey.from_hex(msg.sender)
        except ValueError:
            return False
        return self.validators.contains(sender) and msg.verify_signature()

    def _handle_vote(self, msg, result, handler) -> None:
        if msg.round == self.round:
            handler(msg, result)
        elif msg.round > self.round:
            self._buffer.append(msg)  # replayed once we adopt that round

    # ── PRE-PREPARE ────────────────────────────────────────────────────
    def _handle_pre_prepare(self, msg: ConsensusMessage, result: StepResult) -> None:
        if msg.round > self.round:
            # A future-round proposal must justify its round with a quorum
            # round-change certificate before we adopt the round.
            ok, _ = self._verify_round_change_cert(msg.round_change_cert, msg.round)
            if not ok:
                return
            self._ingest_round_change_cert(msg.round_change_cert)
            self._adopt_round(msg.round, result)
        if msg.round != self.round or self.phase != Phase.NEW_ROUND:
            return
        if PublicKey.from_hex(msg.sender) != self.proposer:
            return
        block = msg.block
        if block is None or block.hash != msg.block_hash:
            return
        if not self._structurally_valid(block):
            return
        if self.round > 0 and not self._proposal_justified(msg):
            return
        self._accept_proposal(block, result)

    def _structurally_valid(self, block: Block) -> bool:
        return (
            block.index == self.height
            and block.header.previous_hash == self.previous_hash
            and block.has_consistent_merkle_root()
        )

    def _proposal_justified(self, msg: ConsensusMessage) -> bool:
        ok, justified = self._verify_round_change_cert(msg.round_change_cert, msg.round)
        if not ok:
            return False
        if justified is not None:
            return msg.block is not None and msg.block.hash == justified
        return True  # nothing locked anywhere: proposer may pick a fresh block

    def _accept_proposal(self, block: Block, result: StepResult) -> None:
        # Crash-recovery guard: never PREPARE a block that contradicts a vote we
        # already journaled for this round (would be equivocation).
        prior = self._journal.voted_hash(self.round, PREPARE)
        if prior is not None and prior != block.hash:
            return
        self.proposal = block
        self.phase = Phase.PRE_PREPARED
        self._journal.record_vote(self.round, PREPARE, block.hash)
        prepare = ConsensusMessage.create(
            type=MessageType.PREPARE,
            height=self.height,
            round=self.round,
            block_hash=block.hash,
            signer=self.private_key,
        )
        self._record_prepare(prepare)
        result.broadcast.append(prepare)
        self._maybe_advance(result)

    # ── PREPARE / COMMIT ───────────────────────────────────────────────
    def _handle_prepare(self, msg: ConsensusMessage, result: StepResult) -> None:
        self._record_prepare(msg)
        self._maybe_advance(result)

    def _record_prepare(self, msg: ConsensusMessage) -> None:
        self._prepares.setdefault(msg.block_hash, {})[msg.sender] = msg

    def _handle_commit(self, msg: ConsensusMessage, result: StepResult) -> None:
        if not self._valid_commit_seal(msg):
            return
        self._commits.setdefault(msg.block_hash, {})[msg.sender] = msg.commit_seal  # type: ignore[assignment]
        self._maybe_advance(result)

    @staticmethod
    def _valid_commit_seal(msg: ConsensusMessage) -> bool:
        if not msg.commit_seal:
            return False
        sender = PublicKey.from_hex(msg.sender)
        return sender.verify(
            bytes.fromhex(msg.commit_seal), msg.block_hash.encode("utf-8")
        )

    def _maybe_advance(self, result: StepResult) -> None:
        if self.proposal is None:
            return
        h = self.proposal.hash
        quorum = self.validators.quorum

        if self.phase == Phase.PRE_PREPARED and len(self._prepares.get(h, {})) >= quorum:
            # Crash-recovery guard: never COMMIT a block contradicting a journaled commit.
            prior = self._journal.voted_hash(self.round, COMMIT)
            if prior is not None and prior != h:
                return
            self.phase = Phase.PREPARED
            self.prepared_round = self.round
            self.prepared_block = self.proposal
            self._prepared_cert = list(self._prepares[h].values())
            self._journal.record_prepared(self.round, self.proposal, self._prepared_cert)
            self._journal.record_vote(self.round, COMMIT, h)
            commit = ConsensusMessage.create(
                type=MessageType.COMMIT,
                height=self.height,
                round=self.round,
                block_hash=h,
                signer=self.private_key,
            )
            self._commits.setdefault(h, {})[self.me.to_hex()] = commit.commit_seal  # type: ignore[assignment]
            result.broadcast.append(commit)

        if self.phase == Phase.PREPARED and len(self._commits.get(h, {})) >= quorum:
            self.phase = Phase.COMMITTED
            result.committed = self._finalize(h)

    def _finalize(self, block_hash: str) -> Block:
        assert self.proposal is not None
        block = self.proposal
        for sender_hex, seal_hex in self._commits[block_hash].items():
            block.add_commit_signature(
                PublicKey.from_hex(sender_hex), bytes.fromhex(seal_hex)
            )
        return block

    # ── ROUND CHANGE ───────────────────────────────────────────────────
    def _send_round_change(self, target: int, result: StepResult) -> None:
        if target in self._rc_sent:
            return
        if self.prepared_block is not None:
            block_hash = self.prepared_block.hash
            block = self.prepared_block
            cert = self._prepared_cert
        else:
            block_hash, block, cert = ZERO_HASH, None, []
        msg = ConsensusMessage.create(
            type=MessageType.ROUND_CHANGE,
            height=self.height,
            round=target,
            block_hash=block_hash,
            signer=self.private_key,
            block=block,
            prepared_round=self.prepared_round,
            prepared_cert=cert,
        )
        self._rc_sent.add(target)
        self._round_changes.setdefault(target, {})[self.me.to_hex()] = msg
        result.broadcast.append(msg)

    def _handle_round_change(self, msg: ConsensusMessage, result: StepResult) -> None:
        if msg.round <= self.round:
            return
        if not self._valid_round_change(msg):
            return
        self._round_changes.setdefault(msg.round, {})[msg.sender] = msg
        self._process_round_changes(result)

    def _valid_round_change(self, msg: ConsensusMessage) -> bool:
        if msg.prepared_round is None:
            return True
        # The locked-value claim must be backed by a quorum prepared certificate.
        return self._verify_prepares(
            msg.prepared_cert, msg.prepared_round, msg.block_hash
        )

    def _process_round_changes(self, result: StepResult) -> None:
        for _ in range(self.validators.size + 1):  # bounded fixpoint
            changed = False
            # Acceleration: f+1 round-changes for a higher round -> join it.
            for target in sorted(self._round_changes):
                if (
                    target > self.round
                    and target not in self._rc_sent
                    and len(self._round_changes[target]) >= self.validators.max_faulty + 1
                ):
                    self._send_round_change(target, result)
                    changed = True
            # Adoption: a quorum of round-changes for a higher round.
            best = max(
                (
                    t
                    for t in self._round_changes
                    if t > self.round
                    and len(self._round_changes[t]) >= self.validators.quorum
                ),
                default=None,
            )
            if best is not None:
                self._adopt_round(best, result)
                self._propose_for_round_change(best, result)
                changed = True
            if not changed:
                break

    def _adopt_round(self, target: int, result: StepResult) -> None:
        if target <= self.round:
            return
        self.start_round(target)
        # Replay buffered votes that belong to the adopted round.
        replay = [m for m in self._buffer if m.round == target]
        self._buffer = [m for m in self._buffer if m.round > target]
        for m in replay:
            if m.type is MessageType.PREPARE:
                self._handle_prepare(m, result)
            elif m.type is MessageType.COMMIT:
                self._handle_commit(m, result)

    def _propose_for_round_change(self, target: int, result: StepResult) -> None:
        if self.round != target or self.phase != Phase.NEW_ROUND:
            return
        if not self.is_proposer():
            return
        cert = list(self._round_changes[target].values())
        _, justified = self._verify_round_change_cert(cert, target)
        if justified is not None:
            block = self._locked_block_from_cert(cert, justified)
        else:
            block = self._build_block(self._pending)
        if block is None:
            return
        self._emit_pre_prepare(block, round_change_cert=cert, result=result)

    @staticmethod
    def _locked_block_from_cert(
        cert: list[ConsensusMessage], justified_hash: str
    ) -> Block | None:
        for m in cert:
            if m.block is not None and m.block.hash == justified_hash:
                return m.block
        return None

    def _ingest_round_change_cert(self, cert: list[ConsensusMessage]) -> None:
        for m in cert:
            if self._authentic(m) and self._valid_round_change(m):
                self._round_changes.setdefault(m.round, {})[m.sender] = m

    # ── certificate verification ───────────────────────────────────────
    def _verify_prepares(
        self, cert: list[ConsensusMessage], round_: int, block_hash: str
    ) -> bool:
        senders: set[str] = set()
        for m in cert:
            if (
                m.type is MessageType.PREPARE
                and m.height == self.height
                and m.round == round_
                and m.block_hash == block_hash
                and self._authentic(m)
            ):
                senders.add(m.sender)
        return len(senders) >= self.validators.quorum

    def _verify_round_change_cert(
        self, cert: list[ConsensusMessage], target_round: int
    ) -> tuple[bool, str | None]:
        """Return (cert is a valid quorum for ``target_round``, justified block hash)."""
        valid: dict[str, ConsensusMessage] = {}
        for m in cert:
            if (
                m.type is MessageType.ROUND_CHANGE
                and m.height == self.height
                and m.round == target_round
                and self._authentic(m)
                and self._valid_round_change(m)
            ):
                valid[m.sender] = m
        if len(valid) < self.validators.quorum:
            return False, None
        justified_hash: str | None = None
        best_round = -1
        for m in valid.values():
            if m.prepared_round is not None and m.prepared_round > best_round:
                best_round = m.prepared_round
                justified_hash = m.block_hash
        return True, justified_hash


def verify_finality(block: Block, validators: ValidatorSet) -> bool:
    """Verify a persisted block carries a valid BFT finality certificate.

    Returns ``True`` iff at least ``quorum`` distinct validators from ``validators``
    each contributed a valid commit seal over the block hash. Round-independent,
    so blocks finalized after a round change verify identically.
    """
    valid = 0
    block_hash = block.hash.encode("utf-8")
    for sender_hex, seal_hex in block.commit_signatures.items():
        try:
            key = PublicKey.from_hex(sender_hex)
        except ValueError:
            continue
        if not validators.contains(key):
            continue
        if key.verify(bytes.fromhex(seal_hex), block_hash):
            valid += 1
    return valid >= validators.quorum
