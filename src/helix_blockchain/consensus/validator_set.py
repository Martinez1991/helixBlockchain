"""The permissioned validator set and BFT quorum arithmetic.

For a set of ``N`` validators, the protocol tolerates up to ``f = (N-1)//3``
Byzantine (arbitrarily faulty) validators and requires a quorum of ``N - f``
(== ``2f + 1`` when ``N == 3f + 1``) matching votes to make progress. The
proposer for a given height/round is chosen deterministically by round-robin so
every honest node agrees on who may propose.
"""

from __future__ import annotations

from helix_blockchain.domain.crypto import PublicKey


class ValidatorSet:
    """An ordered, immutable set of validator public keys."""

    def __init__(self, validators: list[PublicKey]) -> None:
        if not validators:
            raise ValueError("validator set must not be empty")
        # Deterministic order shared by all nodes: sort by hex public key.
        unique = {v.to_hex(): v for v in validators}
        if len(unique) != len(validators):
            raise ValueError("duplicate validators in set")
        self._validators = [unique[h] for h in sorted(unique)]

    @property
    def size(self) -> int:
        return len(self._validators)

    @property
    def max_faulty(self) -> int:
        """``f`` — the maximum number of Byzantine validators tolerated."""
        return (self.size - 1) // 3

    @property
    def quorum(self) -> int:
        """Number of matching votes required to commit (``N - f``)."""
        return self.size - self.max_faulty

    def __iter__(self):
        return iter(self._validators)

    def __len__(self) -> int:
        return self.size

    def contains(self, key: PublicKey) -> bool:
        return any(key == v for v in self._validators)

    def proposer(self, height: int, round_: int) -> PublicKey:
        """Deterministic round-robin proposer for ``(height, round_)``."""
        return self._validators[(height + round_) % self.size]

    def index_of(self, key: PublicKey) -> int:
        for i, v in enumerate(self._validators):
            if v == key:
                return i
        raise KeyError("validator not in set")
