"""MCP prompts: reusable, user-invoked templates (they show up as slash commands in
Claude Desktop / Claude Code). These prefetch the data so the report is grounded in
real numbers rather than whatever the model remembers to call."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from lobbyeasy_mcp.deps import Deps, as_json, prompt_errors


def register_prompts(mcp: MCPServer, deps: Deps) -> None:
    service = deps.service

    @mcp.prompt(
        title="Daily lobby report",
        description="Summarise one day in the lobby for the building manager (síndico).",
    )
    @prompt_errors
    async def daily_lobby_report(
        ctx: Context,
        day: Annotated[str | None, Field(description="YYYY-MM-DD, default today")] = None,
        language: Annotated[str, Field(description="Report language")] = "pt-BR",
    ) -> str:
        who = deps.principal(ctx)
        stats = await service.daily_stats(who, date.fromisoformat(day) if day else None)
        pending = await service.list_pending(who, None, 20)
        return (
            f"You are writing the daily lobby report for {stats.date} in {language}.\n"
            "Use ONLY the data below. Structure: 1) one-line headline, 2) arrivals vs pickups,\n"
            "3) packages waiting the longest (name the apartment, not the resident's phone),\n"
            "4) anything unusual (expired/cancelled withdrawal sessions, busy hours),\n"
            "5) one concrete suggestion for the doormen. Keep it under 200 words.\n\n"
            f"## Stats\n```json\n{as_json(stats)}\n```\n\n"
            f"## Currently pending (top 20 of {pending.total_pending})\n```json\n{as_json(pending)}\n```"
        )

    @mcp.prompt(
        title="Stale package follow-up",
        description="Draft friendly reminders for packages waiting more than N days.",
    )
    @prompt_errors
    async def stale_package_followup(
        ctx: Context,
        min_days: Annotated[str, Field(description="Minimum days waiting (integer)")] = "3",
    ) -> str:
        who = deps.principal(ctx)
        threshold = float(min_days)
        pending = await service.list_pending(who, None, 100)
        stale = [p for p in pending.packages if (p.days_waiting or 0) >= threshold]
        listing = "\n".join(
            f"- package {p.id}: {p.description or 'package'} for {p.resident.name} "
            f"({p.apartment.label if p.apartment else 'no apartment'}), waiting {p.days_waiting} days"
            for p in stale
        )
        return (
            f"{len(stale)} package(s) have been waiting at least {threshold:g} days:\n{listing or '- none'}\n\n"
            "For each, draft a short, polite WhatsApp-style reminder in pt-BR from the lobby to the resident. "
            "Do not include phone numbers or CPF. If write tools are available, you may propose "
            "notify_resident calls, but wait for the user's go-ahead."
        )
