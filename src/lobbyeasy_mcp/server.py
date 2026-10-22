"""Assemble the MCP server: settings -> repository -> service -> tools/resources/prompts."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime

from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer

from lobbyeasy_mcp import __version__
from lobbyeasy_mcp.config import Settings
from lobbyeasy_mcp.data import make_repository
from lobbyeasy_mcp.data.base import LobbyRepository
from lobbyeasy_mcp.deps import Deps, PrincipalResolver
from lobbyeasy_mcp.principal import Principal, Role
from lobbyeasy_mcp.prompts import register_prompts
from lobbyeasy_mcp.resources import register_resources
from lobbyeasy_mcp.service import LobbyService
from lobbyeasy_mcp.tools.read import register_read_tools

INSTRUCTIONS = """\
LobbyEasy: packages (encomendas) received by the lobby of ONE condominium.
- Statuses: 'pendente' = waiting in the lobby, 'retirada' = picked up.
- Find ids first: list_apartments for apartments, find_residents for people,
  search_packages for packages; then use get_* tools.
- Times are lobby-local. Resident phone/CPF are masked unless reveal_pii is granted.
"""


def stdio_principal(settings: Settings) -> PrincipalResolver:
    """A local stdio server trusts its own environment: one condominium, one role."""
    principal = Principal(key_id="stdio", condominium_id=settings.condominium_id, role=Role(settings.role))
    return lambda _ctx: principal


def build_server(
    settings: Settings | None = None,
    *,
    repo: LobbyRepository | None = None,
    resolve_principal: PrincipalResolver | None = None,
    clock: Callable[[], datetime] | None = None,
    token_verifier: TokenVerifier | None = None,
    auth: AuthSettings | None = None,
) -> MCPServer:
    settings = settings or Settings()
    repo = repo or make_repository(settings)
    deps = Deps(
        settings=settings,
        repo=repo,
        service=LobbyService(repo, timezone=settings.timezone, clock=clock),
        resolve_principal=resolve_principal or stdio_principal(settings),
    )

    # The SDK may enter the lifespan more than once (e.g. once per in-process client),
    # so the repository is opened on first entry and closed on last exit.
    active = 0

    @asynccontextmanager
    async def lifespan(_server: MCPServer) -> AsyncIterator[Deps]:
        nonlocal active
        if active == 0:
            await repo.open()
        active += 1
        try:
            yield deps
        finally:
            active -= 1
            if active == 0:
                await repo.close()

    mcp = MCPServer(
        "lobbyeasy",
        title="LobbyEasy",
        version=__version__,
        instructions=INSTRUCTIONS,
        website_url="https://orrevua.dev",
        lifespan=lifespan,
        token_verifier=token_verifier,
        auth=auth,
    )
    register_read_tools(mcp, deps)
    register_resources(mcp, deps)
    register_prompts(mcp, deps)
    return mcp
