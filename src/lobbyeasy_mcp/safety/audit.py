"""Audit log of every tool call, with arguments redacted.

Redaction is an **allowlist**: only argument names known to be harmless (ids,
limits, statuses, dates, flags) are stored verbatim. Every other string (names,
free-text descriptions, notification messages, tokens) becomes `[redacted:<len>]`.
A blocklist ("hide cpf and phone") fails open the day someone adds a new field;
an allowlist fails closed.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

log = logging.getLogger("lobbyeasy_mcp.audit")

Outcome = Literal["ok", "error", "denied", "rate_limited"]

SAFE_KEYS = frozenset(
    {
        "package_id",
        "resident_id",
        "apartment",
        "status",
        "limit",
        "day",
        "arrived_from",
        "arrived_to",
        "reveal_pii",
        "cursor",
        "filters",
        "package_ids",
        "idempotency_key",
        "tracking_code",
    }
)


def redact(value: Any, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, key) for v in value]
    if value is None or isinstance(value, bool | int | float):
        return value
    if key in SAFE_KEYS:
        return value if len(str(value)) <= 200 else f"{str(value)[:200]}..."
    if key == "confirmation_token":
        return f"{str(value)[:6]}..."  # enough to correlate prepare/confirm, useless to replay
    return f"[redacted:{len(str(value))}]"


@dataclass
class AuditEntry:
    key_id: str
    condominium_id: str | None
    role: str | None
    tool: str
    arguments: dict[str, Any]
    outcome: Outcome
    duration_ms: int
    error: str | None = None
    request_id: str | None = None
    at: datetime = field(default_factory=lambda: datetime.now(UTC))


class AuditSink(Protocol):
    async def record(self, entry: AuditEntry) -> None: ...


class InMemoryAuditSink:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def record(self, entry: AuditEntry) -> None:
        self.entries.append(entry)
        log.debug("audit %s", json.dumps(asdict(entry), default=str))


class PostgresAuditSink:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self.pool = pool

    async def record(self, entry: AuditEntry) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO mcp_audit_log
                  (at, key_id, condominium_id, role, tool, arguments, outcome, error, duration_ms, request_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    entry.at,
                    entry.key_id,
                    entry.condominium_id,
                    entry.role,
                    entry.tool,
                    Jsonb(entry.arguments),
                    entry.outcome,
                    entry.error,
                    entry.duration_ms,
                    entry.request_id,
                ),
            )
