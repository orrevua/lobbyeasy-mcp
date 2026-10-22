"""`make demo`: drive the server through the MCP protocol and print what a client sees.

Offline by default (in-memory demo data). `LOBBY_BACKEND=postgres make demo` runs
the same calls against Postgres.
"""

import json

import anyio
from mcp import Client

from lobbyeasy_mcp.fixtures import DEMO_DAY, JARDIM_ID
from lobbyeasy_mcp.server import build_server


def show(title: str, payload: object) -> None:
    print(f"\n=== {title}")
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str)[:1500])


async def main() -> None:
    async with Client(build_server()) as client:
        tools = (await client.list_tools()).tools
        show("tools/list", [t.name for t in tools])
        for name, args in [
            ("list_pending_packages", {"limit": 3}),
            ("search_packages", {"filters": {"resident_name": "nunes"}, "limit": 2}),
            ("find_residents", {"apartment": "A-101"}),
            ("get_daily_stats", {"day": DEMO_DAY}),
        ]:
            result = await client.call_tool(name, args)
            show(f"tools/call {name} {args}", result.structured_content or result.content[0].text)
        res = await client.read_resource(f"lobby://condominiums/{JARDIM_ID}/pending")
        print("\n=== resources/read pending\n" + res.contents[0].text)


if __name__ == "__main__":
    anyio.run(main)
