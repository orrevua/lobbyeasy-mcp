"""Per-API-key token bucket.

Each key owns a bucket of `capacity` tokens that refills continuously at
`refill_per_second`. A call spends `cost` tokens or is refused with the number of
seconds until it would succeed. Bursts up to `capacity` are fine; the sustained rate
is capped. This protects the database (and your LLM bill) from a looping agent.

State is in process memory, which is correct for a single instance. With several
replicas each would enforce its own bucket; move the state to Redis/Postgres then.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    updated: float


class RateLimiter:
    def __init__(
        self,
        capacity: float,
        refill_per_second: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacity <= 0 or refill_per_second <= 0:
            raise ValueError("capacity and refill_per_second must be positive")
        self.capacity = capacity
        self.refill = refill_per_second
        self.clock = clock
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def try_acquire(self, key: str, cost: float = 1.0) -> tuple[bool, float]:
        """Spend `cost` tokens. Returns (allowed, seconds_to_wait_if_not)."""
        now = self.clock()
        with self._lock:
            bucket = self._buckets.setdefault(key, _Bucket(self.capacity, now))
            bucket.tokens = min(self.capacity, bucket.tokens + (now - bucket.updated) * self.refill)
            bucket.updated = now
            if bucket.tokens >= cost:
                bucket.tokens -= cost
                return True, 0.0
            return False, (cost - bucket.tokens) / self.refill
