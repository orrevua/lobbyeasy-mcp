"""Two-step confirmation for writes ("propose, then commit").

A write tool never writes. It validates the request, stores it here under a random
single-use token, and returns a human-readable summary. Only `confirm_action(token)`
executes it. This gives the user a moment to read "Mark package 12 (Documento do
cartório, A-101) as picked up?" before anything changes, and means a prompt-injected
tool call cannot complete a write on its own in one step.

Tokens are bound to the API key that created them, expire after a TTL, and are
deleted on first use. Process memory is enough: a lost token just means "ask again".
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal


@dataclass(frozen=True)
class PendingAction:
    token: str
    key_id: str
    condominium_id: str
    action: str
    args: dict[str, Any]
    summary: str
    expires_at: datetime
    idempotency_key: str | None = None


class ConfirmationStore:
    def __init__(self, ttl_seconds: int = 300, clock: Callable[[], datetime] | None = None) -> None:
        self.ttl = timedelta(seconds=ttl_seconds)
        self.clock = clock or (lambda: datetime.now(UTC))
        self._pending: dict[str, PendingAction] = {}
        self._lock = threading.Lock()

    def create(self, **fields: Any) -> PendingAction:
        pending = PendingAction(token=secrets.token_urlsafe(16), expires_at=self.clock() + self.ttl, **fields)
        with self._lock:
            self._purge()
            self._pending[pending.token] = pending
        return pending

    def take(self, token: str, key_id: str) -> PendingAction | Literal["expired"] | None:
        """Pop the action if it belongs to `key_id`. Returns 'expired' for stale tokens."""
        with self._lock:
            pending = self._pending.get(token)
            if pending is None or pending.key_id != key_id:
                return None  # another key's token looks exactly like a missing one
            del self._pending[token]
        if pending.expires_at < self.clock():
            return "expired"
        return pending

    def discard(self, token: str, key_id: str) -> PendingAction | None:
        with self._lock:
            pending = self._pending.get(token)
            if pending is None or pending.key_id != key_id:
                return None
            del self._pending[token]
            return pending

    def _purge(self) -> None:
        now = self.clock()
        for token in [t for t, p in self._pending.items() if p.expires_at < now]:
            del self._pending[token]
