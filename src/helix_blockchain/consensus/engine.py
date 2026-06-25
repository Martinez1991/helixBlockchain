"""IBFT/PBFT-style consensus state machine for a single block height.

This is intentionally a *pure* state machine. It never touches the network or
disk: it consumes signed :class:`ConsensusMessage` objects and returns a
:class:`StepResult` describing what to broadcast and whether a block was
finalized. The surrounding node (:mod:`helix_blockchain.network`) is responsible
for transporting messages and persisting committed blocks.

Happy-path protocol for height ``h``:

1. **PRE-PREPARE** — the round's proposer builds a block and broadcasts it.
2. **PREPARE** — each validator that accepts the proposal broadcasts a PREPARE.
   Collecting ``quorum`` PREPAREs proves a quorum saw the *same* proposal.
3. **COMMIT** — on reaching ``quorum`` PREPAREs a validator locks the block and
   broadcasts a COMMIT carrying its *commit seal* (a signature over the block
   hash). Collecting ``quorum`` COMMITs finalizes the block; the seals become
   the block's persisted finality certificate.

Round changes (liveness under a faulty proposer) are exposed via
:meth:`on_timeout` / :meth:`start_round`; the certificate-based safety of the
happy path above is what this module fully implements and tests.
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from dataclasses import dataclass, field

from helix_blockchain.consensus.messages import ConsensusMessage, MessageType
from helix_blockchain.consensus.validator_set import ValidatorSet
from helix_blockchain.domain.block import Block
from helix_blockchain.domain.crypto import PrivateKey, PublicKey
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


class ConsensusEngine:
    def __init__(
        self,
        *,
        validators: ValidatorSet,
        private_key: PrivateKey,
        height: int,
        previous_hash: str,
        now_ms: Callable[[], int],
    ) -> None:
        if not validators.contains(private_key.public):
            raise ValueError("this node is not part of the validator set")
        self.validators = validators
        self.private_key = private_key
        self.me: PublicKey = private_key.public
        self.height = height
        self.previous_hash = previous_hash
        self._now_ms = now_ms
        self.start_round(0)

    # ── round lifecycle ────────────────────────────────────────────────
    def start_round(self, round_: int) -> None:
        self.round = round_
        self.phase = Phase.NEW_ROUND
        self.proposal: Block | None = None
        # Votes are buffered per block hash so out-of-order arrival is fine.
        self._prepares: dict[str, set[str]] = {}
        self._commits: dict[str, dict[str, str]] = {}

    @property
    def proposer(self) -> PublicKey:
        return self.validators.proposer(self.height, self.round)

    def is_proposer(self) -> bool:
        return self.me == self.proposer

    # ── proposing ──────────────────────────────────────────────────────
    def propose(self, records: list[IntegrityRecord]) -> StepResult:
        """Build and broadcast a PRE-PREPARE. Only valid for the round proposer."""
        if not self.is_proposer():
            raise RuntimeError("only the round proposer may propose")
        if self.phase != Phase.NEW_ROUND:
            raise RuntimeError("already proposed this round")
        block = Block.create(
            index=self.height,
            previous_hash=self.previous_hash,
            timestamp=self._now_ms(),
            proposer=self.me.to_hex(),
            records=records,
        )
        pre_prepare = ConsensusMessage.create(
            type=MessageType.PRE_PREPARE,
            height=self.height,
            round=self.round,
            block_hash=block.hash,
            signer=self.private_key,
            block=block,
        )
        # Accept our own proposal exactly as a peer would, then broadcast it.
        result = self._accept_proposal(block)
        result.broadcast.insert(0, pre_prepare)
        return result

    # ── message handling ───────────────────────────────────────────────
    def handle(self, msg: ConsensusMessage) -> StepResult:
        """Process an incoming consensus message and return required actions."""
        if not self._is_relevant(msg):
            return StepResult()
        if msg.type is MessageType.PRE_PREPARE:
            return self._handle_pre_prepare(msg)
        if msg.type is MessageType.PREPARE:
            return self._handle_prepare(msg)
        if msg.type is MessageType.COMMIT:
            return self._handle_commit(msg)
        return StepResult()

    def _is_relevant(self, msg: ConsensusMessage) -> bool:
        if msg.height != self.height or msg.round != self.round:
            return False
        sender = self._valid_sender(msg)
        return sender is not None

    def _valid_sender(self, msg: ConsensusMessage) -> PublicKey | None:
        try:
            sender = PublicKey.from_hex(msg.sender)
        except ValueError:
            return None
        if not self.validators.contains(sender):
            return None
        if not msg.verify_signature():
            return None
        return sender

    def _handle_pre_prepare(self, msg: ConsensusMessage) -> StepResult:
        if self.phase != Phase.NEW_ROUND:
            return StepResult()
        if PublicKey.from_hex(msg.sender) != self.proposer:
            return StepResult()  # only the designated proposer may pre-prepare
        block = msg.block
        if block is None or block.hash != msg.block_hash:
            return StepResult()
        if not self._proposal_is_valid(block):
            return StepResult()
        return self._accept_proposal(block)

    def _proposal_is_valid(self, block: Block) -> bool:
        return (
            block.index == self.height
            and block.header.previous_hash == self.previous_hash
            and block.header.proposer == self.proposer.to_hex()
            and block.has_consistent_merkle_root()
        )

    def _accept_proposal(self, block: Block) -> StepResult:
        self.proposal = block
        self.phase = Phase.PRE_PREPARED
        # The proposer's PRE-PREPARE counts as its PREPARE.
        self._record_prepare(block.hash, self.proposer.to_hex())
        # Broadcast our own PREPARE and count it.
        prepare = ConsensusMessage.create(
            type=MessageType.PREPARE,
            height=self.height,
            round=self.round,
            block_hash=block.hash,
            signer=self.private_key,
        )
        self._record_prepare(block.hash, self.me.to_hex())
        result = StepResult(broadcast=[prepare])
        self._maybe_advance(result)
        return result

    def _handle_prepare(self, msg: ConsensusMessage) -> StepResult:
        self._record_prepare(msg.block_hash, msg.sender)
        result = StepResult()
        self._maybe_advance(result)
        return result

    def _handle_commit(self, msg: ConsensusMessage) -> StepResult:
        if not self._valid_commit_seal(msg):
            return StepResult()
        self._commits.setdefault(msg.block_hash, {})[msg.sender] = msg.commit_seal  # type: ignore[assignment]
        result = StepResult()
        self._maybe_advance(result)
        return result

    def _valid_commit_seal(self, msg: ConsensusMessage) -> bool:
        if not msg.commit_seal:
            return False
        sender = PublicKey.from_hex(msg.sender)
        return sender.verify(bytes.fromhex(msg.commit_seal), msg.block_hash.encode("utf-8"))

    def _record_prepare(self, block_hash: str, sender: str) -> None:
        self._prepares.setdefault(block_hash, set()).add(sender)

    # ── state transitions ──────────────────────────────────────────────
    def _maybe_advance(self, result: StepResult) -> None:
        if self.proposal is None:
            return
        h = self.proposal.hash
        quorum = self.validators.quorum

        if self.phase == Phase.PRE_PREPARED and len(self._prepares.get(h, ())) >= quorum:
            self.phase = Phase.PREPARED
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

    @property
    def committed(self) -> bool:
        return self.phase == Phase.COMMITTED


def verify_finality(block: Block, validators: ValidatorSet) -> bool:
    """Verify a persisted block carries a valid BFT finality certificate.

    Returns ``True`` iff at least ``quorum`` distinct validators from ``validators``
    each contributed a valid commit seal over the block hash.
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
