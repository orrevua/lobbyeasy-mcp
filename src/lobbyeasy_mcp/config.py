"""Runtime configuration, read from environment variables (prefix `LOBBY_`) or a `.env` file."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from uuid import UUID

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from lobbyeasy_mcp.fixtures import JARDIM_ID


class Backend(StrEnum):
    MEMORY = "memory"  # demo fixtures, zero setup; also what the tests use
    POSTGRES = "postgres"  # local Postgres or Supabase's Postgres connection string


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LOBBY_", env_file=".env", extra="ignore")

    backend: Backend = Backend.MEMORY
    database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/p4_lobby",
        description="libpq URL. For Supabase use the 'Session pooler' or direct connection string.",
    )
    timezone: str = Field(default="America/Sao_Paulo", description="Lobby-local time zone for 'today'")

    # stdio identity. A stdio server is launched by the user on their own machine, so it
    # trusts its environment: it acts as one fixed condominium + role, no API key needed.
    condominium_id: UUID = JARDIM_ID
    role: str = "viewer"

    # Remote (streamable HTTP) server
    host: str = "127.0.0.1"
    port: int = 8000
    public_url: str | None = Field(
        default=None, description="External base URL, e.g. https://lobbyeasy-mcp.fly.dev (auth metadata)"
    )
    api_keys_file: Path | None = Field(default=None, description="JSON file of hashed API keys")
    key_store: str = Field(
        default="auto", description="'file', 'postgres' or 'auto' (file if set, else backend)"
    )
    stateless_http: bool = Field(
        default=True, description="No server-side MCP sessions: any instance can serve any request"
    )
    json_response: bool = Field(default=True, description="Plain JSON responses instead of SSE streams")

    @property
    def base_url(self) -> str:
        return (self.public_url or f"http://{self.host}:{self.port}").rstrip("/")

    # Safety
    enable_writes: bool = Field(default=False, description="Register write tools at all (still role-gated)")
    confirmation_ttl_seconds: int = Field(default=300, description="How long a write proposal stays valid")
    rate_limit_capacity: float = Field(default=30, description="Burst size per API key (token bucket)")
    rate_limit_refill_per_second: float = Field(default=0.5, description="Sustained calls/second per key")
