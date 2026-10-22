"""Idempotency keys for write actions.

A client that times out and retries must not register the same package twice. The
caller sends an `idempotency_key` (any unique string, e.g. a UUID) with the write;
the first execution reserves `(api key, idempotency_key)`, later attempts get the
stored result back instead of running again.

Reserve-then-complete (not check-then-insert) is what makes it safe under
concurrency: the reservation is a primary-key insert, so only one caller can win.
Reusing a key with *different* arguments is an error, never a silent replay.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool


def request_hash(tool: str, args: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps([tool, args], sort_keys=True, default=str).encode()).hexdigest()


@dataclass(frozen=True)
class IdempotencyRecord:
    tool: str
    request_hash: str
    status: Literal["in_progress", "completed"]
    result: dict[str, Any] | None


class IdempotencyStore(Protocol):
    async def reserve(self, key_id: str, idem_key: str, tool: str, req_hash: str) -> IdempotencyRecord | None:
        """Reserve the key. Returns None if we now own it, else the existing record."""
        ...

    async def complete(self, key_id: str, idem_key: str, result: dict[str, Any]) -> None: ...
    async def release(self, key_id: str, idem_key: str) -> None:
        """Drop a reservation whose action failed, so the client can retry."""
        ...

    async def get(self, key_id: str, idem_key: str) -> IdempotencyRecord | None: ...


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], IdempotencyRecord] = {}

    async def reserve(self, key_id: str, idem_key: str, tool: str, req_hash: str) -> IdempotencyRecord | None:
        existing = self._rows.get((key_id, idem_key))
        if existing:
            return existing
        self._rows[(key_id, idem_key)] = IdempotencyRecord(tool, req_hash, "in_progress", None)
        return None

    async def complete(self, key_id: str, idem_key: str, result: dict[str, Any]) -> None:
        row = self._rows[(key_id, idem_key)]
        self._rows[(key_id, idem_key)] = IdempotencyRecord(row.tool, row.request_hash, "completed", result)

    async def release(self, key_id: str, idem_key: str) -> None:
        self._rows.pop((key_id, idem_key), None)

    async def get(self, key_id: str, idem_key: str) -> IdempotencyRecord | None:
        return self._rows.get((key_id, idem_key))


class PostgresIdempotencyStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self.pool = pool

    async def reserve(self, key_id: str, idem_key: str, tool: str, req_hash: str) -> IdempotencyRecord | None:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO mcp_idempotency (key_id, idempotency_key, tool, request_hash)"
                " VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (key_id, idem_key, tool, req_hash),
            )
            if cur.rowcount == 1:
                return None
        return await self.get(key_id, idem_key)

    async def complete(self, key_id: str, idem_key: str, result: dict[str, Any]) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE mcp_idempotency SET status = 'completed', result = %s, completed_at = now()"
                " WHERE key_id = %s AND idempotency_key = %s",
                (Jsonb(result), key_id, idem_key),
            )

    async def release(self, key_id: str, idem_key: str) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "DELETE FROM mcp_idempotency WHERE key_id = %s AND idempotency_key = %s AND status = 'in_progress'",
                (key_id, idem_key),
            )

    async def get(self, key_id: str, idem_key: str) -> IdempotencyRecord | None:
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                "SELECT tool, request_hash, status, result FROM mcp_idempotency"
                " WHERE key_id = %s AND idempotency_key = %s",
                (key_id, idem_key),
            )
            row = await cur.fetchone()
        return IdempotencyRecord(**row) if row else None
