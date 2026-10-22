"""End to end through the MCP protocol, using the SDK's in-process client.

`Client(server)` connects to the server object directly (no subprocess, no
network) but still goes through tools/list, argument validation, structured
output and error mapping exactly like a real client would.
"""

from __future__ import annotations

import pytest
from mcp import Client
from mcp.shared.exceptions import MCPError

from lobbyeasy_mcp.data.memory import InMemoryRepository
from lobbyeasy_mcp.fixtures import ATLANTICO_ID, JARDIM_ID
from lobbyeasy_mcp.principal import Principal, Role
from lobbyeasy_mcp.server import build_server

from .conftest import fixed_clock

READ_TOOLS = {
    "list_pending_packages",
    "get_package",
    "search_packages",
    "find_residents",
    "list_apartments",
    "get_apartment_summary",
    "get_daily_stats",
}


def make_client(settings, role: Role = Role.VIEWER, condo=JARDIM_ID) -> Client:
    who = Principal("test", condo, role)
    server = build_server(
        settings, repo=InMemoryRepository(), resolve_principal=lambda _: who, clock=fixed_clock
    )
    return Client(server)


async def call(client: Client, name: str, args: dict | None = None):
    result = await client.call_tool(name, args or {})
    assert not result.is_error, result.content[0].text
    return result.structured_content


async def error_text(client: Client, name: str, args: dict) -> str:
    result = await client.call_tool(name, args)
    assert result.is_error
    return result.content[0].text


async def test_tool_catalog(settings):
    async with make_client(settings) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert set(tools) == READ_TOOLS
        for tool in tools.values():
            assert tool.annotations.read_only_hint is True
            assert tool.description and tool.output_schema


async def test_list_pending_and_get_package(settings):
    async with make_client(settings) as client:
        out = await call(client, "list_pending_packages", {"limit": 3})
        assert out["total_pending"] == 9
        assert [p["id"] for p in out["packages"]] == [16, 15, 14]
        only_a101 = await call(client, "list_pending_packages", {"apartment": "A-101"})
        assert [p["id"] for p in only_a101["packages"]] == [15, 12, 6]

        pkg = await call(client, "get_package", {"package_id": 2})
        assert pkg["apartment"]["label"] == "A-102"
        assert pkg["days_waiting"] == 5.9
        assert "search_packages" in await error_text(client, "get_package", {"package_id": 17})


async def test_search_paginates_with_cursor(settings):
    async with make_client(settings) as client:
        seen, cursor = [], None
        while True:
            args = {"filters": {"status": "retirada"}, "limit": 3}
            if cursor:
                args["cursor"] = cursor
            page = await call(client, "search_packages", args)
            seen += [p["id"] for p in page["items"]]
            if not page["has_more"]:
                assert page["next_cursor"] is None
                break
            cursor = page["next_cursor"]
        assert seen == [11, 10, 9, 7, 5, 3, 1]

        first = await call(client, "search_packages", {"limit": 1})
        msg = await error_text(
            client,
            "search_packages",
            {"filters": {"status": "pendente"}, "cursor": first["next_cursor"]},
        )
        assert "different filters" in msg


async def test_search_filters_and_validation(settings):
    async with make_client(settings) as client:
        page = await call(
            client,
            "search_packages",
            {"filters": {"arrived_from": "2026-10-21", "arrived_to": "2026-10-21", "resident_name": "lima"}},
        )
        assert [p["id"] for p in page["items"]] == [9]
        msg = await error_text(client, "search_packages", {"filters": {"status": "lost"}})
        assert "status" in msg
        msg = await error_text(
            client, "search_packages", {"filters": {"arrived_from": "2026-10-22", "arrived_to": "2026-10-01"}}
        )
        assert "swap" in msg
        assert "list_apartments" in await error_text(client, "list_pending_packages", {"apartment": "Z-99"})


async def test_residents_are_masked_by_default(settings):
    async with make_client(settings) as client:
        people = (await call(client, "find_residents", {"name": "souza"}))["result"]
        assert [p["name"] for p in people] == ["Ana Beatriz Souza", "Carlos Souza"]
        assert people[0]["phone"] == "(**) *****-4321"
        assert people[0]["cpf"] == "***.***.***-09"
        assert people[0]["pii_masked"] is True
        assert "reveal_pii=false" in await error_text(
            client, "find_residents", {"name": "souza", "reveal_pii": True}
        )
        assert "at least" in await error_text(client, "find_residents", {})


async def test_porteiro_can_reveal_pii(settings):
    async with make_client(settings, Role.PORTEIRO) as client:
        people = (await call(client, "find_residents", {"apartment": 1, "reveal_pii": True}))["result"]
        assert people[0]["phone"] == "(11) 98765-4321"
        assert people[0]["cpf"] == "123.456.789-09"


async def test_apartment_summary_and_stats(settings):
    async with make_client(settings) as client:
        s = await call(client, "get_apartment_summary", {"apartment": "B-101"})
        assert s["pending_count"] == 0 and s["total_packages"] == 3
        assert [r["name"] for r in s["residents"]] == ["Helena Nunes", "Roberto Nunes"]
        assert s["recent_withdrawal_sessions"][0]["method"] == "qr_scan"

        stats = await call(client, "get_daily_stats", {"day": "2026-10-21"})
        assert stats["arrivals"] == 8 and stats["busiest_hour"] == "11"
        assert stats["oldest_pending"]["id"] == 2
        today = await call(client, "get_daily_stats")
        assert today["date"] == "2026-10-22" and today["arrivals"] == 2

        apts = (await call(client, "list_apartments"))["result"]
        assert len(apts) == 7 and apts[0]["label"] == "A-101"


async def test_other_condominium_sees_only_its_data(settings):
    async with make_client(settings, condo=ATLANTICO_ID) as client:
        out = await call(client, "list_pending_packages")
        assert [p["id"] for p in out["packages"]] == [19, 17]


async def test_resources(settings):
    async with make_client(settings) as client:
        templates = {t.uri_template for t in (await client.list_resource_templates()).resource_templates}
        assert "lobby://condominiums/{condominium_id}/summary" in templates
        static = {str(r.uri) for r in (await client.list_resources()).resources}
        assert "lobby://reference/package-lifecycle" in static

        summary = await client.read_resource(f"lobby://condominiums/{JARDIM_ID}/summary")
        assert '"pending_packages": 9' in summary.contents[0].text
        table = await client.read_resource(f"lobby://condominiums/{JARDIM_ID}/pending")
        assert "| 2 | A-102 | Mariana Lima |" in table.contents[0].text

        with pytest.raises(MCPError, match="scoped to condominium"):
            await client.read_resource(f"lobby://condominiums/{ATLANTICO_ID}/summary")


async def test_prompts(settings):
    async with make_client(settings) as client:
        names = {p.name for p in (await client.list_prompts()).prompts}
        assert names == {"daily_lobby_report", "stale_package_followup"}
        report = await client.get_prompt("daily_lobby_report", {"day": "2026-10-21"})
        text = report.messages[0].content.text
        assert '"arrivals": 8' in text and "pt-BR" in text
        followup = await client.get_prompt("stale_package_followup", {"min_days": "2"})
        text = followup.messages[0].content.text
        assert "package 2:" in text and "package 4:" in text and "package 6:" not in text
        assert "98765" not in text  # no phone numbers leak into prompts
