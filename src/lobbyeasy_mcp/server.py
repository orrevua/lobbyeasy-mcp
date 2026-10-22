"""Milestone 1: the smallest useful MCP server.

Two read-only tools over the in-memory demo data, served over stdio.
"""

from __future__ import annotations

import os
from uuid import UUID

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from lobbyeasy_mcp import __version__
from lobbyeasy_mcp.fixtures import JARDIM_ID, build_dataset
from lobbyeasy_mcp.models import Package, PackageStatus


def build_server() -> MCPServer:
    data = build_dataset()
    condominium_id = UUID(os.environ.get("LOBBY_CONDOMINIUM_ID", str(JARDIM_ID)))
    residents = {r.id: r for r in data.residents if r.condominium_id == condominium_id}
    packages = [p for p in data.packages if p.resident_id in residents]

    mcp = MCPServer(
        "lobbyeasy",
        version=__version__,
        instructions="Read-only access to the LobbyEasy package log of one condominium.",
    )

    @mcp.tool()
    def list_pending_packages() -> list[Package]:
        """List packages still waiting in the lobby (status 'pendente'), newest first."""
        pending = [p for p in packages if p.status is PackageStatus.PENDING]
        return sorted(pending, key=lambda p: p.arrived_at, reverse=True)

    @mcp.tool()
    def get_package(package_id: int) -> Package:
        """Get one package by its numeric id."""
        for p in packages:
            if p.id == package_id:
                return p
        raise ToolError(f"Package {package_id} not found. Call list_pending_packages to see valid ids.")

    return mcp


def main() -> None:
    build_server().run("stdio")
