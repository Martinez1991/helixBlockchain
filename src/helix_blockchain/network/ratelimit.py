"""A small per-source token-bucket rate limiter for the P2P/admin endpoints.

Validator endpoints accept signed/authenticated traffic, but an authenticated or
misbehaving peer could still flood them. A token bucket per source IP allows
normal bursts while capping sustained rate, with no external dependency. The
clock is injectable so the logic is deterministically testable.
"""

from __future__ import annotations

import time
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self,
        rate_per_sec: float,
        burst: int,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.rate = rate_per_sec
        self.burst = max(1, burst)
        self._now = now
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, ts)

    @property
    def enabled(self) -> bool:
        return self.rate > 0

    def allow(self, key: str) -> bool:
        """Consume one token for ``key``; return ``False`` if the bucket is empty."""
        if not self.enabled:
            return True
        now = self._now()
        tokens, ts = self._buckets.get(key, (float(self.burst), now))
        tokens = min(self.burst, tokens + (now - ts) * self.rate)
        if tokens < 1.0:
            self._buckets[key] = (tokens, now)
            return False
        self._buckets[key] = (tokens - 1.0, now)
        return True
