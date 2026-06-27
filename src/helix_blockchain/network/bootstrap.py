"""Bootstrap a node's genesis block from a peer.

A brand-new node normally builds genesis locally from its configured validator
set. With this, a node that was *not* configured with the genesis set can instead
fetch block 0 from a peer and adopt it — useful when adding a validator to an
existing network. The fetched genesis is validated structurally; because genesis
is deterministic, every honest node produces the same block 0, so an adopted one
is consistent with the rest of the chain (later blocks are still verified by their
finality certificates during catch-up sync).
"""

from __future__ import annotations

import logging

from helix_blockchain.domain.block import ZERO_HASH, Block
from helix_blockchain.domain.membership import ChangeAction
from helix_blockchain.network.transport import Transport

log = logging.getLogger(__name__)


def is_valid_genesis(block: Block) -> bool:
    """A genesis block is index 0, links to ZERO_HASH, has a consistent Merkle
    root, no records, and embeds a non-empty validator set as ADD changes."""
    return (
        block.index == 0
        and block.header.previous_hash == ZERO_HASH
        and block.has_consistent_merkle_root()
        and not block.records
        and len(block.validator_changes) > 0
        and all(c.action is ChangeAction.ADD for c in block.validator_changes)
    )


async def fetch_genesis(transport: Transport) -> Block | None:
    """Fetch and validate block 0 from a peer; ``None`` if unavailable/invalid."""
    block = await transport.fetch_block(0)
    if block is None:
        return None
    if not is_valid_genesis(block):
        log.warning("fetched block 0 is not a valid genesis; ignoring")
        return None
    return block
