"""Targeted confidentiality for what the chain stores.

The chain never stores raw values (only a fingerprint of each observation), but a
plain ``SHA-256(value)`` is brute-forceable for low-entropy values (a boolean, a
temperature in a small range). With a shared cluster key, the fingerprint becomes
a **keyed commitment** ``HMAC-SHA256(key, value)`` that a chain reader without the
key cannot invert, while validators that hold the key still compute the same
value deterministically — so tamper-detection (comparison) and cross-validator
agreement are preserved.

``entity_id`` may be personal data (LGPD); when enabled it is **pseudonymized**
with the same key (``pid:HMAC(key, entity_id)``), reversible only by the key
holder — supporting crypto-shredding for the right to erasure.

Confidentiality here is against *external* readers (leaked DB, non-validator
nodes, backups, auditors), **not** against the trusted validator quorum (they
hold the key) — hiding from validators would break the cross-broker comparison
that is the system's whole purpose.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from helix_blockchain.domain.canonical import canonical_bytes


class Confidentiality:
    """Computes the stored fingerprint of a value and (optionally) a pseudonym
    for an entity id. With no key, behaviour is identical to the plain SHA-256
    scheme (fully backward compatible)."""

    def __init__(
        self, key: bytes | None = None, *, pseudonymize_entities: bool = False
    ) -> None:
        self._key = key or None
        self._pseudonymize = pseudonymize_entities

    @property
    def enabled(self) -> bool:
        return self._key is not None

    def commit_value(self, value: Any) -> str:
        """Keyed commitment of ``value`` (HMAC) when a key is set, else SHA-256.

        Deterministic, so all validators sharing the key agree."""
        data = canonical_bytes(value)
        if self._key is not None:
            return hmac.new(self._key, data, hashlib.sha256).hexdigest()
        return hashlib.sha256(data).hexdigest()

    def entity_ref(self, entity_id: str) -> str:
        """The entity id to store: pseudonymized (``pid:`` + HMAC) when enabled,
        otherwise the raw id."""
        if self._key is not None and self._pseudonymize:
            mac = hmac.new(self._key, entity_id.encode("utf-8"), hashlib.sha256)
            return "pid:" + mac.hexdigest()
        return entity_id
