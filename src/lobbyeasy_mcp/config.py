"""Runtime configuration, read from environment variables (prefix `LOBBY_`) or a `.env` file."""

from __future__ import annotations

from enum import StrEnum
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
