"""Time source, injectable so logic stays deterministic under test."""

from __future__ import annotations

import time


def now_ms() -> int:
    """Current wall-clock time in epoch milliseconds."""
    return int(time.time() * 1000)
