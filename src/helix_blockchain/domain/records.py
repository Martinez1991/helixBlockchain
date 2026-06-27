"""Integrity records — the transactions carried by blocks.

An :class:`IntegrityRecord` is the observation the blockchain commits to: the
state of a FIWARE Orion entity attribute at a point in time, plus a verdict on
whether it matched the federated source. Recording these in a BFT-agreed,
tamper-evident chain is the whole point of the system.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any

from helix_blockchain.domain.canonical import canonical_bytes
from helix_blockchain.domain.crypto import PrivateKey, PublicKey, sha256_hex


class Verdict(enum.StrEnum):
    """Outcome of comparing a broker's value against its federated source."""

    OK = "OK"
    TAMPERED = "TAMPERED"
    UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True)
class IntegrityRecord:
    """A single integrity observation about one entity attribute.

    ``value_hash`` is the hash of the observed value rather than the raw value,
    keeping the chain compact and avoiding storing payloads that may be large or
    sensitive (the system guarantees integrity, not confidentiality).
    """

    entity_id: str
    attribute: str
    value_hash: str
    source_broker: str
    verdict: Verdict
    observed_at: int  # epoch milliseconds
    observer: str = ""    # public key (hex) of the validator that observed it
    signature: str = ""   # Ed25519 signature over signing_bytes()

    def _core(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "attribute": self.attribute,
            "value_hash": self.value_hash,
            "source_broker": self.source_broker,
            "verdict": self.verdict.value,
            "observed_at": self.observed_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._core(), "observer": self.observer, "signature": self.signature}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntegrityRecord:
        return cls(
            entity_id=data["entity_id"],
            attribute=data["attribute"],
            value_hash=data["value_hash"],
            source_broker=data["source_broker"],
            verdict=Verdict(data["verdict"]),
            observed_at=int(data["observed_at"]),
            observer=data.get("observer", ""),
            signature=data.get("signature", ""),
        )

    def signing_bytes(self) -> bytes:
        """Canonical bytes of the observation that the observer signs."""
        return canonical_bytes(self._core())

    def signed(self, private_key: PrivateKey) -> IntegrityRecord:
        """Return a copy signed by ``private_key`` (sets observer + signature).

        ``signing_bytes`` excludes observer/signature, so signing is stable and
        deterministic (Ed25519) regardless of prior signature state."""
        from dataclasses import replace

        return replace(
            self,
            observer=private_key.public.to_hex(),
            signature=private_key.sign(self.signing_bytes()).hex(),
        )

    def verify(self, allowed: object) -> bool:
        """True iff signed by a member of ``allowed`` (a ValidatorSet-like with
        ``contains``) over the observation content."""
        if not self.observer or not self.signature:
            return False
        try:
            key = PublicKey.from_hex(self.observer)
        except ValueError:
            return False
        if not allowed.contains(key):  # type: ignore[attr-defined]
            return False
        return key.verify(bytes.fromhex(self.signature), self.signing_bytes())

    def canonical(self) -> bytes:
        """Canonical bytes used as the Merkle leaf for this record."""
        return canonical_bytes(self.to_dict())

    @property
    def id(self) -> str:
        """Stable hash of the full (signed) record — the Merkle-leaf identity."""
        return sha256_hex(self.canonical())

    @property
    def content_key(self) -> str:
        """Hash of the observation alone (excludes observer/signature), so the
        same observation deduplicates regardless of which validator signed it."""
        return sha256_hex(self.signing_bytes())

    @staticmethod
    def hash_value(value: Any) -> str:
        """Hash an observed attribute value into ``value_hash``."""
        return sha256_hex(canonical_bytes(value))
