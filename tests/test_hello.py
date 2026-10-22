from mcp import Client

from lobbyeasy_mcp.server import build_server


async def test_lists_tools_and_pending_packages():
    async with Client(build_server()) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        assert {"list_pending_packages", "get_package"} <= names

        result = await client.call_tool("list_pending_packages", {})
        assert not result.is_error
        ids = [p["id"] for p in result.structured_content["result"]]
        assert ids[0] == 16  # newest first
        assert 17 not in ids  # other condominium never leaks


async def test_get_package_not_found_is_actionable():
    async with Client(build_server()) as client:
        result = await client.call_tool("get_package", {"package_id": 9999})
        assert result.is_error
        assert "list_pending_packages" in result.content[0].text
