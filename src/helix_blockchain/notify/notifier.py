"""Notify operators when a committed block records tampering.

The original TCC printed ``"Divice X foi adulterado"`` to the prompt. Here the
same alert fires only for records that are *finalized by consensus*, so an alert
reflects agreement across the validator set rather than one node's view.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from helix_blockchain.domain.block import Block
from helix_blockchain.domain.records import Verdict

log = logging.getLogger("helix.alert")


@runtime_checkable
class Notifier(Protocol):
    def block_committed(self, block: Block) -> None:
        """Called with each finalized block; implementations surface tampering."""


class ConsoleNotifier:
    """Prints a prominent alert for every tampered record in a block."""

    def block_committed(self, block: Block) -> None:
        tampered = [r for r in block.records if r.verdict is Verdict.TAMPERED]
        for record in tampered:
            banner = (
                f"\n{'~' * 60}\n"
                f"  TAMPERING DETECTED — block #{block.index}\n"
                f"  device  : {record.entity_id}\n"
                f"  attribute: {record.attribute}\n"
                f"  broker  : {record.source_broker}\n"
                f"  observed: {record.observed_at}\n"
                f"{'~' * 60}"
            )
            log.warning(banner)

    def __call__(self, block: Block) -> None:  # convenience as a commit hook
        self.block_committed(block)
