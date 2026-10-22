"""The packaged entry point over real stdio (subprocess), like Claude Desktop runs it."""

import os
import sys

from mcp import Client
from mcp.client.stdio import StdioServerParameters


async def test_stdio_subprocess_roundtrip():
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "lobbyeasy_mcp", "stdio"],
        env={**os.environ, "LOBBY_BACKEND": "memory", "LOBBY_ROLE": "viewer"},
    )
    async with Client(params) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
        assert "get_daily_stats" in tools and "confirm_action" not in tools
        result = await client.call_tool("get_package", {"package_id": 2})
        assert result.structured_content["tracking_code"] == "LB998877665BR"
