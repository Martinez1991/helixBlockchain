"""Write-ahead journal of consensus votes, for safe crash-recovery.

BFT safety requires that a validator never casts two conflicting votes (two
PREPAREs or two COMMITs for different blocks in the same round). In memory the
engine guarantees this, but a process that crashes and restarts would forget
what it voted and could *equivocate* — which, combined with a Byzantine fault,
breaks safety.

The :class:`VoteJournal` is a height-scoped, durable record of this node's own
votes and its prepared lock. The engine consults it before emitting a vote
(refusing to contradict a journaled one) and records each vote *before* it is
broadcast. On restart the engine restores its prepared lock from the journal and
keeps refusing conflicting votes, so recovery cannot cause equivocation.
"""

from __future__ import annotations

import json
from typing import Protocol

from sqlalchemy import String, Text, create_engine, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from helix_blockchain.consensus.messages import ConsensusMessage
from helix_blockchain.domain.block import Block

PREPARE = "PREPARE"
COMMIT = "COMMIT"


class VoteJournal(Protocol):
    """Durable record of one height's self-votes and prepared lock."""

    def voted_hash(self, round_: int, phase: str) -> str | None:
        """The block hash already voted for in ``(round_, phase)``, if any."""

    def record_vote(self, round_: int, phase: str, block_hash: str) -> None:
        """Persist that we voted ``phase`` for ``block_hash`` in ``round_``."""

    def record_prepared(
        self, round_: int, block: Block, cert: list[ConsensusMessage]
    ) -> None:
        """Persist the prepared lock (block + the PREPARE quorum proving it)."""

    def prepared(self) -> tuple[int, Block, list[ConsensusMessage]] | None:
        """The restored prepared lock, if any."""


class NullVoteJournal:
    """No-op journal: votes are not durable (default, e.g. for tests)."""

    def voted_hash(self, round_: int, phase: str) -> str | None:
        return None

    def record_vote(self, round_: int, phase: str, block_hash: str) -> None:
        pass

    def record_prepared(self, round_, block, cert) -> None:
        pass

    def prepared(self):
        return None


class InMemoryVoteJournal:
    """In-memory journal for unit tests (no durability)."""

    def __init__(self) -> None:
        self._votes: dict[tuple[int, str], str] = {}
        self._prepared: tuple[int, Block, list[ConsensusMessage]] | None = None

    def voted_hash(self, round_, phase):
        return self._votes.get((round_, phase))

    def record_vote(self, round_, phase, block_hash):
        self._votes[(round_, phase)] = block_hash

    def record_prepared(self, round_, block, cert):
        self._prepared = (round_, block, list(cert))

    def prepared(self):
        return self._prepared


class ConsensusJournalStore(Protocol):
    def view(self, height: int) -> VoteJournal:
        """A journal bound to ``height`` (the working consensus height)."""

    def prune_below(self, height: int) -> None:
        """Discard journals for heights below ``height`` (already finalized)."""


class NullJournalStore:
    def view(self, height: int) -> VoteJournal:
        return NullVoteJournal()

    def prune_below(self, height: int) -> None:
        pass


# ── SQLAlchemy-backed durable journal ──────────────────────────────────
class _Base(DeclarativeBase):
    pass


class _WalRow(_Base):
    __tablename__ = "consensus_wal"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    height: Mapped[int] = mapped_column(index=True)
    kind: Mapped[str] = mapped_column(String(16))  # "vote" | "prepared"
    round: Mapped[int] = mapped_column()
    phase: Mapped[str] = mapped_column(String(16), default="")
    block_hash: Mapped[str] = mapped_column(String(64), default="")
    payload: Mapped[str] = mapped_column(Text, default="")  # prepared: block+cert


class SqlConsensusJournalStore:
    """Durable journal in the same SQL engine as the chain."""

    def __init__(self, url: str = "sqlite:///:memory:") -> None:
        kwargs: dict = {}
        if url.startswith("sqlite") and ":memory:" in url:
            kwargs = {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
        elif url.startswith("sqlite"):
            kwargs = {"connect_args": {"check_same_thread": False}}
        self._engine = create_engine(url, **kwargs)
        _Base.metadata.create_all(self._engine)

    def view(self, height: int) -> VoteJournal:
        return _SqlHeightView(self._engine, height)

    def prune_below(self, height: int) -> None:
        with Session(self._engine) as session:
            session.execute(delete(_WalRow).where(_WalRow.height < height))
            session.commit()


class _SqlHeightView:
    def __init__(self, engine, height: int) -> None:
        self._engine = engine
        self._height = height
        self._votes: dict[tuple[int, str], str] = {}
        self._prepared: tuple[int, Block, list[ConsensusMessage]] | None = None
        self._load()

    def _load(self) -> None:
        with Session(self._engine) as session:
            rows = session.scalars(
                select(_WalRow).where(_WalRow.height == self._height).order_by(_WalRow.id)
            ).all()
        for row in rows:
            if row.kind == "vote":
                self._votes[(row.round, row.phase)] = row.block_hash
            elif row.kind == "prepared":
                data = json.loads(row.payload)
                block = Block.from_dict(data["block"])
                cert = [ConsensusMessage.from_dict(m) for m in data["cert"]]
                self._prepared = (row.round, block, cert)

    def voted_hash(self, round_, phase):
        return self._votes.get((round_, phase))

    def record_vote(self, round_, phase, block_hash):
        self._votes[(round_, phase)] = block_hash
        with Session(self._engine) as session:
            session.add(_WalRow(
                height=self._height, kind="vote", round=round_,
                phase=phase, block_hash=block_hash,
            ))
            session.commit()

    def record_prepared(self, round_, block, cert):
        self._prepared = (round_, block, list(cert))
        payload = json.dumps({
            "block": block.to_dict(),
            "cert": [m.to_dict() for m in cert],
        })
        with Session(self._engine) as session:
            session.add(_WalRow(
                height=self._height, kind="prepared", round=round_,
                block_hash=block.hash, payload=payload,
            ))
            session.commit()

    def prepared(self):
        return self._prepared
