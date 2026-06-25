"""Abstract block repository.

Decouples the chain from any concrete storage engine. The consensus layer only
depends on this interface, so SQLite, Postgres or an in-memory fake are all
interchangeable.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from helix_blockchain.domain.block import Block


@runtime_checkable
class BlockRepository(Protocol):
    """Append-only persistent store of finalized blocks, ordered by index."""

    def append(self, block: Block) -> None:
        """Persist ``block`` as the new tip. Implementations must reject gaps
        and duplicate indices."""

    def get(self, index: int) -> Block | None:
        """Return the block at ``index`` or ``None`` if absent."""

    def height(self) -> int:
        """Index of the tip block, or ``-1`` if the store is empty."""

    def latest(self) -> Block | None:
        """Return the tip block, or ``None`` if the store is empty."""

    def load_all(self) -> list[Block]:
        """Return every block in ascending index order."""
