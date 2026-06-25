"""Cryptographic primitives: SHA-256 hashing and Ed25519 signatures.

Ed25519 is used for validator identities and for signing consensus messages
and blocks. Keys are represented as raw 32-byte values, hex-encoded for
configuration and transport.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


def sha256(data: bytes) -> bytes:
    """Return the raw 32-byte SHA-256 digest of ``data``."""
    return hashlib.sha256(data).digest()


def sha256_hex(data: bytes) -> str:
    """Return the hex-encoded SHA-256 digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class PublicKey:
    """An Ed25519 public key used to verify signatures and identify a validator."""

    _key: Ed25519PublicKey

    @classmethod
    def from_hex(cls, hex_str: str) -> PublicKey:
        raw = bytes.fromhex(hex_str)
        return cls(Ed25519PublicKey.from_public_bytes(raw))

    def to_hex(self) -> str:
        raw = self._key.public_bytes(Encoding.Raw, PublicFormat.Raw)
        return raw.hex()

    def verify(self, signature: bytes, message: bytes) -> bool:
        """Return ``True`` iff ``signature`` is a valid signature of ``message``."""
        try:
            self._key.verify(signature, message)
            return True
        except InvalidSignature:
            return False

    def __eq__(self, other: object) -> bool:
        return isinstance(other, PublicKey) and self.to_hex() == other.to_hex()

    def __hash__(self) -> int:
        return hash(self.to_hex())


@dataclass(frozen=True)
class PrivateKey:
    """An Ed25519 private key for signing. Derived public key is exposed via ``public``."""

    _key: Ed25519PrivateKey

    @classmethod
    def generate(cls) -> PrivateKey:
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_hex(cls, hex_str: str) -> PrivateKey:
        raw = bytes.fromhex(hex_str)
        if len(raw) != 32:
            raise ValueError("Ed25519 private seed must be 32 bytes (64 hex chars)")
        return cls(Ed25519PrivateKey.from_private_bytes(raw))

    def to_hex(self) -> str:
        raw = self._key.private_bytes(
            Encoding.Raw, PrivateFormat.Raw, NoEncryption()
        )
        return raw.hex()

    @property
    def public(self) -> PublicKey:
        return PublicKey(self._key.public_key())

    def sign(self, message: bytes) -> bytes:
        return self._key.sign(message)
