"""Signed consensus messages exchanged between validators.

Every message is authenticated: the sender signs a canonical payload with its
Ed25519 key and receivers verify it against the claimed sender's public key, so a
Byzantine node cannot forge votes attributed to an honest validator.

Round change (IBFT liveness) requires two nested certificates, both carried as
lists of independently-signed messages so any receiver can verify them:

* ``prepared_cert`` — on a ROUND_CHANGE, a quorum of PREPARE messages proving the
  sender really *prepared* the block it claims to be locked on. Without this a
  Byzantine node could lie about a locked value and hijack the next proposal.
* ``round_change_cert`` — on a PRE_PREPARE for round > 0, the quorum of
  ROUND_CHANGE messages that justify the new round and the chosen block.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
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
    block: Block | None = None  # PRE_PREPARE (proposed) / ROUND_CHANGE (prepared)
    commit_seal: str | None = None  # COMMIT only: hex signature over block_hash bytes
    prepared_round: int | None = None  # ROUND_CHANGE: round at which sender prepared
    prepared_cert: list[ConsensusMessage] = field(default_factory=list)
    round_change_cert: list[ConsensusMessage] = field(default_factory=list)

    def signing_payload(self) -> bytes:
        """Canonical bytes that the sender signs and receivers verify.

        ROUND_CHANGE additionally binds ``prepared_round`` so the locked-value
        claim cannot be altered; the certificates are verified separately via
        each contained message's own signature, so they need not be signed here.
        """
        payload: dict[str, Any] = {
            "type": self.type.value,
            "height": self.height,
            "round": self.round,
            "block_hash": self.block_hash,
        }
        if self.type is MessageType.ROUND_CHANGE:
            payload["prepared_round"] = self.prepared_round
        return canonical_bytes(payload)

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
        prepared_round: int | None = None,
        prepared_cert: list[ConsensusMessage] | None = None,
        round_change_cert: list[ConsensusMessage] | None = None,
    ) -> ConsensusMessage:
        partial = cls(
            type=type,
            height=height,
            round=round,
            block_hash=block_hash,
            sender=signer.public.to_hex(),
            signature="",
            prepared_round=prepared_round,
        )
        signature = signer.sign(partial.signing_payload()).hex()
        # COMMIT carries a round-independent seal over the block hash, collected
        # into the block as its finality certificate.
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
            prepared_round=prepared_round,
            prepared_cert=list(prepared_cert or []),
            round_change_cert=list(round_change_cert or []),
        )

    def verify_signature(self) -> bool:
        """Verify the message signature against its declared ``sender``.

        Returns ``False`` (never raises) on malformed sender/signature hex, so
        adversarial/garbage messages are safely ignored."""
        try:
            sender_key = PublicKey.from_hex(self.sender)
            sig = bytes.fromhex(self.signature)
        except ValueError:
            return False
        return sender_key.verify(sig, self.signing_payload())

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
            "prepared_round": self.prepared_round,
            "prepared_cert": [m.to_dict() for m in self.prepared_cert],
            "round_change_cert": [m.to_dict() for m in self.round_change_cert],
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
            prepared_round=data.get("prepared_round"),
            prepared_cert=[cls.from_dict(m) for m in data.get("prepared_cert", [])],
            round_change_cert=[
                cls.from_dict(m) for m in data.get("round_change_cert", [])
            ],
        )
