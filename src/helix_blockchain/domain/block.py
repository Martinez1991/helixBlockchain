"""Blocks and the in-memory chain.

A block commits to an ordered batch of :class:`IntegrityRecord` via a Merkle
root in its header. The block hash is the SHA-256 of the canonical header, so it
transitively commits to every record. There is no proof-of-work: blocks become
final through BFT consensus (see :mod:`helix_blockchain.consensus`), and the
collected commit signatures are stored on the block as the finality proof.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from helix_blockchain.domain.canonical import canonical_bytes
from helix_blockchain.domain.crypto import PublicKey, sha256_hex
from helix_blockchain.domain.merkle import merkle_root
from helix_blockchain.domain.records import IntegrityRecord

# Hash of the genesis block's predecessor.
ZERO_HASH = "0" * 64


@dataclass(frozen=True)
class BlockHeader:
    """The signed, hashed part of a block."""

    index: int
    previous_hash: str
    timestamp: int  # epoch milliseconds
    merkle_root: str
    proposer: str  # proposer validator public key (hex)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "previous_hash": self.previous_hash,
            "timestamp": self.timestamp,
            "merkle_root": self.merkle_root,
            "proposer": self.proposer,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BlockHeader:
        return cls(
            index=int(data["index"]),
            previous_hash=data["previous_hash"],
            timestamp=int(data["timestamp"]),
            merkle_root=data["merkle_root"],
            proposer=data["proposer"],
        )

    def hash(self) -> str:
        """Deterministic block hash = SHA-256 of the canonical header."""
        return sha256_hex(canonical_bytes(self.to_dict()))


@dataclass
class Block:
    """A block: a header, its records, and BFT commit signatures.

    ``commit_signatures`` maps a validator public key (hex) to its hex signature
    over :meth:`hash`. They are gathered during consensus and are *not* part of
    the block hash (otherwise the hash would change as signatures arrive).
    """

    header: BlockHeader
    records: list[IntegrityRecord] = field(default_factory=list)
    commit_signatures: dict[str, str] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        index: int,
        previous_hash: str,
        timestamp: int,
        proposer: str,
        records: list[IntegrityRecord],
    ) -> Block:
        root = merkle_root([r.canonical() for r in records]).hex()
        header = BlockHeader(
            index=index,
            previous_hash=previous_hash,
            timestamp=timestamp,
            merkle_root=root,
            proposer=proposer,
        )
        return cls(header=header, records=list(records))

    @property
    def hash(self) -> str:
        return self.header.hash()

    @property
    def index(self) -> int:
        return self.header.index

    def computed_merkle_root(self) -> str:
        return merkle_root([r.canonical() for r in self.records]).hex()

    def has_consistent_merkle_root(self) -> bool:
        """True iff the header's Merkle root matches the records it carries."""
        return self.header.merkle_root == self.computed_merkle_root()

    def add_commit_signature(self, validator: PublicKey, signature: bytes) -> None:
        """Attach a verified commit signature from ``validator``."""
        self.commit_signatures[validator.to_hex()] = signature.hex()

    def to_dict(self) -> dict[str, Any]:
        return {
            "header": self.header.to_dict(),
            "records": [r.to_dict() for r in self.records],
            "commit_signatures": dict(self.commit_signatures),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Block:
        return cls(
            header=BlockHeader.from_dict(data["header"]),
            records=[IntegrityRecord.from_dict(r) for r in data["records"]],
            commit_signatures=dict(data.get("commit_signatures", {})),
        )


def genesis_block(proposer: str = ZERO_HASH, timestamp: int = 0) -> Block:
    """Deterministic genesis block shared by all nodes in a network."""
    return Block.create(
        index=0,
        previous_hash=ZERO_HASH,
        timestamp=timestamp,
        proposer=proposer,
        records=[],
    )


class ValidationError(Exception):
    """Raised when a block does not validly extend the chain."""


class Blockchain:
    """An append-only, validated chain of blocks held in memory.

    Validation here covers *structural* integrity (linkage, indices, Merkle
    consistency). *Consensus* validity (enough valid commit signatures from the
    validator set) is enforced by the consensus layer before calling
    :meth:`append`, keeping this class free of validator-set knowledge.
    """

    def __init__(self, genesis: Block) -> None:
        if genesis.index != 0:
            raise ValidationError("genesis block must have index 0")
        if not genesis.has_consistent_merkle_root():
            raise ValidationError("genesis block has inconsistent Merkle root")
        self._chain: list[Block] = [genesis]

    @property
    def height(self) -> int:
        """Index of the latest block (genesis == 0)."""
        return self._chain[-1].index

    @property
    def latest(self) -> Block:
        return self._chain[-1]

    def __len__(self) -> int:
        return len(self._chain)

    def __iter__(self):
        return iter(self._chain)

    def get(self, index: int) -> Block:
        return self._chain[index]

    def validate_next(self, block: Block) -> None:
        """Validate that ``block`` may extend the chain; raise otherwise."""
        prev = self.latest
        if block.index != prev.index + 1:
            raise ValidationError(
                f"non-sequential index: expected {prev.index + 1}, got {block.index}"
            )
        if block.header.previous_hash != prev.hash:
            raise ValidationError("previous_hash does not match latest block hash")
        if not block.has_consistent_merkle_root():
            raise ValidationError("block Merkle root inconsistent with its records")
        if block.header.timestamp < prev.header.timestamp:
            raise ValidationError("block timestamp precedes previous block")

    def append(self, block: Block) -> None:
        """Validate and append ``block`` to the chain."""
        self.validate_next(block)
        self._chain.append(block)
