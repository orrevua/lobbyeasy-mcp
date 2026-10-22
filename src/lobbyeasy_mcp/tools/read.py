"""Read-only tools. Each is a thin adapter: resolve the caller, call the service.

Annotations (`readOnlyHint`, `openWorldHint`) let clients skip confirmation
prompts for safe tools and are part of the tool's public contract.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from lobbyeasy_mcp.deps import Deps, tool_errors
from lobbyeasy_mcp.views import (
    ApartmentRefArg,
    ApartmentSummary,
    ApartmentView,
    DailyStats,
    Limit,
    PackageFilters,
    PackageId,
    PackagePage,
    PackageView,
    PendingPackages,
    ResidentView,
)

READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


def register_read_tools(mcp: MCPServer, deps: Deps) -> None:
    service = deps.service

    @mcp.tool(title="List pending packages", annotations=READ_ONLY)
    @tool_errors
    async def list_pending_packages(
        ctx: Context, apartment: ApartmentRefArg = None, limit: Limit = 50
    ) -> PendingPackages:
        """Packages still waiting in the lobby (status 'pendente'), newest first.
        Optionally only for one apartment. `total_pending` counts all of them."""
        return await service.list_pending(deps.principal(ctx), apartment, limit)

    @mcp.tool(title="Get package", annotations=READ_ONLY)
    @tool_errors
    async def get_package(ctx: Context, package_id: PackageId) -> PackageView:
        """One package by id, with its resident and apartment."""
        return await service.get_package(deps.principal(ctx), package_id)

    @mcp.tool(title="Search packages", annotations=READ_ONLY)
    @tool_errors
    async def search_packages(
        ctx: Context,
        filters: PackageFilters | None = None,
        cursor: Annotated[
            str | None, Field(description="`next_cursor` from the previous page; omit for page 1")
        ] = None,
        limit: Limit = 20,
    ) -> PackagePage:
        """Search the package history (newest first) by status, apartment, resident name,
        tracking code and arrival dates. Paginated: follow `next_cursor` while `has_more`."""
        return await service.search_packages(deps.principal(ctx), filters or PackageFilters(), cursor, limit)

    @mcp.tool(title="Find residents", annotations=READ_ONLY)
    @tool_errors
    async def find_residents(
        ctx: Context,
        name: Annotated[
            str | None, Field(min_length=2, max_length=150, description="Part of the resident's name")
        ] = None,
        apartment: ApartmentRefArg = None,
        reveal_pii: Annotated[
            bool,
            Field(
                description="Return full phone and CPF. Only for roles with the 'pii' permission, "
                "and only when the user actually needs them. Calls are audited."
            ),
        ] = False,
        limit: Limit = 20,
    ) -> list[ResidentView]:
        """Look residents up by name and/or apartment. Phone and CPF are masked by default."""
        return await service.find_residents(
            deps.principal(ctx), name=name, apartment=apartment, reveal_pii=reveal_pii, limit=limit
        )

    @mcp.tool(title="List apartments", annotations=READ_ONLY)
    @tool_errors
    async def list_apartments(ctx: Context) -> list[ApartmentView]:
        """All apartments of the condominium with their ids and 'BLOCK-NUMBER' labels."""
        return await service.list_apartments(deps.principal(ctx))

    @mcp.tool(title="Apartment summary", annotations=READ_ONLY)
    @tool_errors
    async def get_apartment_summary(
        ctx: Context,
        apartment: Annotated[int | str, Field(description="Apartment id (e.g. 3) or label like 'A-101'")],
    ) -> ApartmentSummary:
        """Residents (masked), pending packages, totals and recent QR/manual withdrawal
        sessions for one apartment."""
        return await service.apartment_summary(deps.principal(ctx), apartment)

    @mcp.tool(title="Daily lobby stats", annotations=READ_ONLY)
    @tool_errors
    async def get_daily_stats(
        ctx: Context,
        day: Annotated[
            date | None, Field(description="Lobby-local date YYYY-MM-DD; defaults to today")
        ] = None,
    ) -> DailyStats:
        """Arrivals, pickups, packages left at end of day, average hours to pickup,
        arrivals per hour, withdrawal-session outcomes and the oldest waiting package."""
        return await service.daily_stats(deps.principal(ctx), day)
