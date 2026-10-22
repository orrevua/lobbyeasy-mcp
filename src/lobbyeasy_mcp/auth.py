"""API keys for the remote (streamable HTTP) server.

Key format: `lbe_<key_id>_<secret>`
  * `key_id` (8 hex chars) is public: it names the key in logs and the audit table and
    lets us look the record up without scanning every hash.
  * `secret` is 32 random bytes (base64url). Only its SHA-256 is stored.

Why plain SHA-256 and not bcrypt/argon2? Slow hashes exist to protect *low-entropy*
human passwords from offline guessing. A 256-bit random secret cannot be guessed, so
a fast hash is enough, and it keeps per-request verification cheap. The comparison
still uses `hmac.compare_digest` so timing does not leak how many bytes matched.

Each key maps to exactly one condominium and one role. The MCP SDK calls
`ApiKeyVerifier.verify_token` for every HTTP request carrying
`Authorization: Bearer <key>` and rejects the request with 401 if it returns None.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from mcp.server.auth.provider import AccessToken
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from lobbyeasy_mcp.principal import ROLE_PERMISSIONS, Principal, Role

PREFIX = "lbe"


@dataclass(frozen=True)
class ApiKeyRecord:
    key_id: str
    key_hash: str  # sha256 hex of the full key string
    condominium_id: str
    role: str
    label: str = ""
    revoked: bool = False


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key(
    condominium_id: UUID | str, role: Role | str, label: str = ""
) -> tuple[str, ApiKeyRecord]:
    """Return (plaintext key to hand out once, record to store)."""
    key_id = secrets.token_hex(4)
    key = f"{PREFIX}_{key_id}_{secrets.token_urlsafe(32)}"
    record = ApiKeyRecord(
        key_id=key_id,
        key_hash=hash_key(key),
        condominium_id=str(UUID(str(condominium_id))),
        role=Role(role).value,
        label=label,
    )
    return key, record


def parse_key_id(key: str) -> str | None:
    parts = key.split("_", 2)
    if len(parts) != 3 or parts[0] != PREFIX or len(parts[1]) != 8:
        return None
    return parts[1]


class KeyStore(Protocol):
    async def get(self, key_id: str) -> ApiKeyRecord | None: ...


class FileKeyStore:
    """Keys in a JSON file: `[{"key_id": ..., "key_hash": ..., "condominium_id": ..., "role": ...}]`.

    Good for a single small deployment (mount it as a Fly secret/file). Re-read on
    every lookup so revoking a key is just editing the file.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[ApiKeyRecord]:
        if not self.path.exists():
            return []
        return [ApiKeyRecord(**item) for item in json.loads(self.path.read_text())]

    def add(self, record: ApiKeyRecord) -> None:
        records = [r for r in self.load() if r.key_id != record.key_id] + [record]
        self.path.write_text(json.dumps([asdict(r) for r in records], indent=2) + "\n")

    async def get(self, key_id: str) -> ApiKeyRecord | None:
        return next((r for r in self.load() if r.key_id == key_id), None)


class InMemoryKeyStore:
    def __init__(self, records: list[ApiKeyRecord] | None = None) -> None:
        self.records = {r.key_id: r for r in records or []}

    async def get(self, key_id: str) -> ApiKeyRecord | None:
        return self.records.get(key_id)


class PostgresKeyStore:
    """Keys in the `mcp_api_keys` table (see sql/mcp.sql)."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self.pool = pool

    async def get(self, key_id: str) -> ApiKeyRecord | None:
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                "SELECT key_id, key_hash, condominium_id::text AS condominium_id, role, label,"
                " (revoked_at IS NOT NULL) AS revoked FROM mcp_api_keys WHERE key_id = %s",
                (key_id,),
            )
            row = await cur.fetchone()
        return ApiKeyRecord(**row) if row else None

    async def add(self, record: ApiKeyRecord) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO mcp_api_keys (key_id, key_hash, condominium_id, role, label)"
                " VALUES (%s, %s, %s, %s, %s)",
                (record.key_id, record.key_hash, record.condominium_id, record.role, record.label),
            )


class ApiKeyVerifier:
    """`mcp.server.auth.provider.TokenVerifier` implementation backed by a KeyStore."""

    def __init__(self, store: KeyStore) -> None:
        self.store = store

    async def verify_token(self, token: str) -> AccessToken | None:
        key_id = parse_key_id(token)
        if key_id is None:
            return None
        record = await self.store.get(key_id)
        if record is None or record.revoked:
            return None
        if not hmac.compare_digest(record.key_hash, hash_key(token)):
            return None
        role = Role(record.role)
        return AccessToken(
            token=token,
            client_id=record.key_id,
            scopes=sorted(p.value for p in ROLE_PERMISSIONS[role]),
            claims={"condominium_id": record.condominium_id, "role": role.value, "label": record.label},
        )


def principal_from_access_token(token: AccessToken) -> Principal:
    claims: dict[str, Any] = token.claims or {}
    return Principal(
        key_id=token.client_id,
        condominium_id=UUID(claims["condominium_id"]),
        role=Role(claims["role"]),
    )
