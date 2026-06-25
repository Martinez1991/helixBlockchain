"""Deterministic (canonical) serialization for hashing and signing.

Hashes and signatures must be reproducible across nodes and machines, so we
serialize with sorted keys, no insignificant whitespace, and UTF-8. This module
is the single source of truth for "the bytes that get hashed".
"""

from __future__ import annotations

import json
from typing import Any


def canonical_bytes(obj: Any) -> bytes:
    """Serialize ``obj`` to canonical, deterministic UTF-8 bytes.

    Uses sorted object keys and compact separators so that semantically equal
    objects always produce byte-identical output.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
