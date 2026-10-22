"""Guard rails around the tools: rate limiting, audit, idempotency, confirmations."""

from __future__ import annotations

from dataclasses import dataclass, field

from lobbyeasy_mcp.config import Settings
from lobbyeasy_mcp.data.base import LobbyRepository
from lobbyeasy_mcp.safety.audit import AuditSink, InMemoryAuditSink, PostgresAuditSink
from lobbyeasy_mcp.safety.confirmations import ConfirmationStore
from lobbyeasy_mcp.safety.idempotency import (
    IdempotencyStore,
    InMemoryIdempotencyStore,
    PostgresIdempotencyStore,
)
from lobbyeasy_mcp.safety.ratelimit import RateLimiter


@dataclass
class Safety:
    rate_limiter: RateLimiter
    audit: AuditSink
    idempotency: IdempotencyStore
    confirmations: ConfirmationStore = field(default_factory=ConfirmationStore)


def make_safety(settings: Settings, repo: LobbyRepository) -> Safety:
    """Persist audit + idempotency next to the data when it is Postgres, else in memory."""
    pool = getattr(repo, "pool", None)
    return Safety(
        rate_limiter=RateLimiter(settings.rate_limit_capacity, settings.rate_limit_refill_per_second),
        audit=PostgresAuditSink(pool) if pool else InMemoryAuditSink(),
        idempotency=PostgresIdempotencyStore(pool) if pool else InMemoryIdempotencyStore(),
        confirmations=ConfirmationStore(settings.confirmation_ttl_seconds),
    )
