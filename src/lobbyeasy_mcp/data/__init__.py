"""Data access layer: one `LobbyRepository` protocol, two interchangeable backends."""

from lobbyeasy_mcp.config import Backend, Settings
from lobbyeasy_mcp.data.base import LobbyRepository


def make_repository(settings: Settings) -> LobbyRepository:
    if settings.backend == Backend.POSTGRES:
        from lobbyeasy_mcp.data.postgres import PostgresRepository

        return PostgresRepository(settings.database_url)
    from lobbyeasy_mcp.data.memory import InMemoryRepository

    return InMemoryRepository()
