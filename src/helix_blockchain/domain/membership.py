"""On-chain validator-set membership changes.

The validator set is not static: validators can be added or removed, but every
node must agree on *who* may vote at each height or they would compute different
quorums and fork. So membership changes are committed *in blocks* (as block
content, covered by the Merkle root and finalized by consensus), and the active
set at a height is a deterministic replay of the genesis set plus every change in
earlier blocks.

A change committed in block ``h`` takes effect at height ``h + 1``. This keeps
the rule unambiguous: block ``h`` is always validated by the set that was active
*before* its own changes applied.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any

from helix_blockchain.consensus.validator_set import ValidatorSet
from helix_blockchain.domain.canonical import canonical_bytes
from helix_blockchain.domain.crypto import PublicKey


class ChangeAction(enum.StrEnum):
    ADD = "ADD"
    REMOVE = "REMOVE"


@dataclass(frozen=True)
class ValidatorChange:
    """Add or remove one validator, identified by its Ed25519 public key (hex)."""

    action: ChangeAction
    validator: str  # public key, hex

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action.value, "validator": self.validator}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValidatorChange:
        return cls(action=ChangeAction(data["action"]), validator=data["validator"])

    def canonical(self) -> bytes:
        """Canonical bytes used as this change's Merkle leaf."""
        return canonical_bytes(self.to_dict())


def apply_changes(
    validators: ValidatorSet, changes: list[ValidatorChange]
) -> ValidatorSet:
    """Return a new :class:`ValidatorSet` with ``changes`` applied in order.

    Adding an existing validator or removing an absent one is a no-op; removing
    the last validator is rejected (the set must never be empty).
    """
    keys = {v.to_hex(): v for v in validators}
    _apply(keys, changes)
    if not keys:
        raise ValueError("a validator change must not empty the validator set")
    return ValidatorSet(list(keys.values()))


def derive_validator_set(changes: list[ValidatorChange]) -> ValidatorSet:
    """Build the active :class:`ValidatorSet` from scratch by replaying every
    change in order, starting from the empty set.

    This is how a node derives the current set from a self-describing chain: the
    genesis block carries an ``ADD`` for each initial validator, and later blocks
    carry the subsequent changes.
    """
    keys: dict[str, PublicKey] = {}
    _apply(keys, changes)
    if not keys:
        raise ValueError("no validators derived from the chain")
    return ValidatorSet(list(keys.values()))


def _apply(keys: dict[str, PublicKey], changes: list[ValidatorChange]) -> None:
    for change in changes:
        if change.action is ChangeAction.ADD:
            keys[change.validator] = PublicKey.from_hex(change.validator)
        else:  # REMOVE
            keys.pop(change.validator, None)
