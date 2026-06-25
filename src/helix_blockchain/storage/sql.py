"""SQLAlchemy-backed block repository (SQLite for dev, Postgres for prod).

Each block is stored as one row: indexed scalar columns for fast lookup
(``index``, ``hash``, ``previous_hash``, ``timestamp``) plus the full canonical
block as JSON, which is the source of truth on read-back. Storing the whole
block verbatim means persistence never silently drops a field the domain adds
later.
"""

from __future__ import annotations

import json

from sqlalchemy import String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from helix_blockchain.domain.block import Block


class _Base(DeclarativeBase):
    pass


class _BlockRow(_Base):
    __tablename__ = "blocks"

    index: Mapped[int] = mapped_column(primary_key=True)
    hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    previous_hash: Mapped[str] = mapped_column(String(64), index=True)
    timestamp: Mapped[int] = mapped_column(index=True)
    body: Mapped[str] = mapped_column(Text)  # canonical JSON of the full block


class DuplicateBlockError(Exception):
    """Raised when appending a block whose index already exists or skips ahead."""


class SqlBlockRepository:
    """A :class:`~helix_blockchain.storage.repository.BlockRepository` over SQLAlchemy."""

    def __init__(self, url: str = "sqlite:///:memory:") -> None:
        # In-memory SQLite gives each connection its own private database. The
        # HTTP server serves requests from a threadpool, so we pin a single
        # shared connection (StaticPool) and allow cross-thread use; otherwise
        # the chain would appear empty to handler threads.
        kwargs: dict = {}
        if url.startswith("sqlite") and ":memory:" in url:
            kwargs = {
                "poolclass": StaticPool,
                "connect_args": {"check_same_thread": False},
            }
        elif url.startswith("sqlite"):
            kwargs = {"connect_args": {"check_same_thread": False}}
        self._engine = create_engine(url, **kwargs)
        _Base.metadata.create_all(self._engine)

    def append(self, block: Block) -> None:
        expected = self.height() + 1
        if block.index != expected:
            raise DuplicateBlockError(
                f"expected block index {expected}, got {block.index}"
            )
        with Session(self._engine) as session:
            session.add(
                _BlockRow(
                    index=block.index,
                    hash=block.hash,
                    previous_hash=block.header.previous_hash,
                    timestamp=block.header.timestamp,
                    body=json.dumps(block.to_dict()),
                )
            )
            session.commit()

    def get(self, index: int) -> Block | None:
        with Session(self._engine) as session:
            row = session.get(_BlockRow, index)
            return self._to_block(row) if row else None

    def height(self) -> int:
        with Session(self._engine) as session:
            row = session.scalars(
                select(_BlockRow).order_by(_BlockRow.index.desc()).limit(1)
            ).first()
            return row.index if row else -1

    def latest(self) -> Block | None:
        return self.get(self.height()) if self.height() >= 0 else None

    def load_all(self) -> list[Block]:
        with Session(self._engine) as session:
            rows = session.scalars(
                select(_BlockRow).order_by(_BlockRow.index.asc())
            ).all()
            return [self._to_block(r) for r in rows]

    @staticmethod
    def _to_block(row: _BlockRow) -> Block:
        return Block.from_dict(json.loads(row.body))
