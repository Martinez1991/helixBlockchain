"""Signed consensus messages exchanged between validators.

Every message is authenticated: the sender signs the canonical tuple
``(type, height, round, block_hash)`` with its Ed25519 key. Receivers verify the
signature against the claimed sender's public key before acting, so a Byzantine
node cannot forge votes attributed to an honest validator.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any

from helix_blockchain.domain.block import Block
from helix_blockchain.domain.canonical import canonical_bytes
from helix_blockchain.domain.crypto import PrivateKey, PublicKey


class MessageType(enum.StrEnum):
    PRE_PREPARE = "PRE_PREPARE"  # proposer broadcasts the proposed block
    PREPARE = "PREPARE"          # validators agree the proposal is valid
    COMMIT = "COMMIT"            # validators lock and sign for finality
    ROUND_CHANGE = "ROUND_CHANGE"  # validators give up on a stalled round


@dataclass(frozen=True)
class ConsensusMessage:
    type: MessageType
    height: int
    round: int
    block_hash: str
    sender: str           # sender validator public key (hex)
    signature: str        # hex signature over signing_payload()
    block: Block | None = None  # carried only by PRE_PREPARE
    commit_seal: str | None = None  # COMMIT only: hex signature over block_hash bytes

    def signing_payload(self) -> bytes:
        """Canonical bytes that the sender signs and receivers verify."""
        return canonical_bytes(
            {
                "type": self.type.value,
                "height": self.height,
                "round": self.round,
                "block_hash": self.block_hash,
            }
        )

    @classmethod
    def create(
        cls,
        *,
        type: MessageType,
        height: int,
        round: int,
        block_hash: str,
        signer: PrivateKey,
        block: Block | None = None,
    ) -> ConsensusMessage:
        partial = cls(
            type=type,
            height=height,
            round=round,
            block_hash=block_hash,
            sender=signer.public.to_hex(),
            signature="",
            block=block,
        )
        signature = signer.sign(partial.signing_payload()).hex()
        # COMMIT messages carry a round-independent seal over the block hash,
        # which is collected into the block as its finality certificate.
        seal = (
            signer.sign(block_hash.encode("utf-8")).hex()
            if type is MessageType.COMMIT
            else None
        )
        return cls(
            type=type,
            height=height,
            round=round,
            block_hash=block_hash,
            sender=signer.public.to_hex(),
            signature=signature,
            block=block,
            commit_seal=seal,
        )

    def verify_signature(self) -> bool:
        """Verify the message signature against its declared ``sender``."""
        try:
            sender_key = PublicKey.from_hex(self.sender)
        except ValueError:
            return False
        return sender_key.verify(bytes.fromhex(self.signature), self.signing_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "height": self.height,
            "round": self.round,
            "block_hash": self.block_hash,
            "sender": self.sender,
            "signature": self.signature,
            "block": self.block.to_dict() if self.block is not None else None,
            "commit_seal": self.commit_seal,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConsensusMessage:
        raw_block = data.get("block")
        return cls(
            type=MessageType(data["type"]),
            height=int(data["height"]),
            round=int(data["round"]),
            block_hash=data["block_hash"],
            sender=data["sender"],
            signature=data["signature"],
            block=Block.from_dict(raw_block) if raw_block is not None else None,
            commit_seal=data.get("commit_seal"),
        )
