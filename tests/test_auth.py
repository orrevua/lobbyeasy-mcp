from __future__ import annotations

import json
from uuid import UUID

import pytest

from lobbyeasy_mcp.auth import (
    ApiKeyVerifier,
    FileKeyStore,
    generate_api_key,
    hash_key,
    parse_key_id,
    principal_from_access_token,
)
from lobbyeasy_mcp.cli import main as cli_main
from lobbyeasy_mcp.fixtures import JARDIM_ID
from lobbyeasy_mcp.principal import Permission, Role

from .conftest import PG_AVAILABLE, PG_URL, reset_postgres


def test_key_format_and_hash():
    key, record = generate_api_key(JARDIM_ID, Role.PORTEIRO, "desk")
    assert key.startswith(f"lbe_{record.key_id}_")
    assert parse_key_id(key) == record.key_id
    assert record.key_hash == hash_key(key) and key not in json.dumps(record.__dict__)
    assert parse_key_id("Bearer something") is None


async def test_file_store_and_verifier(tmp_path):
    store = FileKeyStore(tmp_path / "keys.json")
    key, record = generate_api_key(JARDIM_ID, Role.VIEWER)
    store.add(record)
    token = await ApiKeyVerifier(store).verify_token(key)
    assert token is not None and token.client_id == record.key_id
    assert token.scopes == [Permission.READ.value]
    who = principal_from_access_token(token)
    assert who.condominium_id == JARDIM_ID and who.role == Role.VIEWER
    assert await ApiKeyVerifier(store).verify_token(key + "x") is None


def test_cli_creates_hashed_key(tmp_path, capsys):
    path = tmp_path / "keys.json"
    cli_main(["keys", "create", "--condominium", str(JARDIM_ID), "--role", "porteiro", "--file", str(path)])
    printed = capsys.readouterr().out
    key = next(line.strip() for line in printed.splitlines() if line.strip().startswith("lbe_"))
    stored = json.loads(path.read_text())
    assert stored[0]["key_hash"] == hash_key(key)
    assert key not in path.read_text()


@pytest.mark.postgres
async def test_postgres_key_store():
    if not PG_AVAILABLE:
        pytest.skip("Postgres not reachable")
    from psycopg_pool import AsyncConnectionPool

    from lobbyeasy_mcp.auth import PostgresKeyStore

    reset_postgres()
    key, record = generate_api_key(UUID(str(JARDIM_ID)), Role.ADMIN, "pg")
    async with AsyncConnectionPool(PG_URL, open=False) as pool:
        store = PostgresKeyStore(pool)
        await store.add(record)
        token = await ApiKeyVerifier(store).verify_token(key)
        assert token is not None and token.claims["role"] == "admin"
        async with pool.connection() as conn:
            await conn.execute(
                "UPDATE mcp_api_keys SET revoked_at = now() WHERE key_id = %s", (record.key_id,)
            )
        assert await ApiKeyVerifier(store).verify_token(key) is None
