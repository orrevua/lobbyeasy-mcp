"""Shared fixtures.

Everything runs offline against the in-memory backend. Tests marked `postgres`
additionally run against `LOBBY_TEST_DATABASE_URL` (default: local `p4_lobby`) and
are skipped automatically when that database is unreachable.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

import psycopg
import pytest

from lobbyeasy_mcp.config import Settings
from lobbyeasy_mcp.data.memory import InMemoryRepository
from lobbyeasy_mcp.fixtures import SAO_PAULO

ROOT = Path(__file__).resolve().parents[1]
PG_URL = os.environ.get("LOBBY_TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/p4_lobby")
# "Now" for every test: mid-day after the demo data, so `days_waiting` is deterministic.
NOW = datetime(2026, 10, 22, 12, 0, tzinfo=SAO_PAULO)


def fixed_clock() -> datetime:
    return NOW


def _pg_available() -> bool:
    try:
        with psycopg.connect(PG_URL, connect_timeout=2):
            return True
    except psycopg.Error:
        return False


PG_AVAILABLE = _pg_available()


def reset_postgres() -> None:
    """Recreate schema + MCP tables and reload the seed (fast: a few dozen rows)."""
    with psycopg.connect(PG_URL, autocommit=True) as conn:
        conn.execute(
            "DROP TABLE IF EXISTS withdrawal_sessions, encomendas, moradores, apartamentos, "
            "invite_tokens, condominios CASCADE"
        )
        for name in ("schema.sql", "mcp.sql", "seed.sql"):
            conn.execute((ROOT / "sql" / name).read_text())  # type: ignore[arg-type]


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.postgres)])
async def repo(request: pytest.FixtureRequest) -> AsyncIterator[object]:
    if request.param == "memory":
        yield InMemoryRepository()
        return
    if not PG_AVAILABLE:
        pytest.skip(f"Postgres not reachable at {PG_URL}")
    from lobbyeasy_mcp.data.postgres import PostgresRepository

    reset_postgres()
    pg = PostgresRepository(PG_URL)
    await pg.open()
    try:
        yield pg
    finally:
        await pg.close()
