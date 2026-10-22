"""Command line entry point: `lobbyeasy-mcp [stdio|http|keys ...]`."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from lobbyeasy_mcp import __version__
from lobbyeasy_mcp.config import Settings
from lobbyeasy_mcp.principal import Role


def _keys_create(args: argparse.Namespace) -> None:
    from lobbyeasy_mcp.auth import FileKeyStore, generate_api_key

    key, record = generate_api_key(args.condominium, args.role, args.label)
    if args.db:
        from psycopg_pool import AsyncConnectionPool

        from lobbyeasy_mcp.auth import PostgresKeyStore

        async def insert() -> None:
            async with AsyncConnectionPool(Settings().database_url, open=False) as pool:
                await PostgresKeyStore(pool).add(record)

        asyncio.run(insert())
        where = "table mcp_api_keys"
    elif args.file:
        FileKeyStore(Path(args.file)).add(record)
        where = args.file
    else:
        where = "nowhere (printed only)"
    print(f"API key (shown once, store it in your MCP client config):\n  {key}\n")
    print(f"Stored hash in {where}:\n{json.dumps(asdict(record), indent=2)}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="lobbyeasy-mcp", description="LobbyEasy MCP server")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("stdio", help="serve over stdin/stdout (default)")
    http = sub.add_parser("http", help="serve streamable HTTP with API-key auth")
    http.add_argument("--host")
    http.add_argument("--port", type=int)

    keys = sub.add_parser("keys", help="manage API keys").add_subparsers(dest="keys_command", required=True)
    create = keys.add_parser("create", help="generate a key for one condominium + role")
    create.add_argument("--condominium", required=True, help="condominium UUID")
    create.add_argument("--role", choices=[r.value for r in Role], default=Role.VIEWER.value)
    create.add_argument("--label", default="")
    target = create.add_mutually_exclusive_group()
    target.add_argument("--file", help="append the hashed record to this JSON file")
    target.add_argument("--db", action="store_true", help="insert into mcp_api_keys (LOBBY_DATABASE_URL)")

    args = parser.parse_args(argv)
    if args.command == "keys":
        _keys_create(args)
    elif args.command == "http":
        from lobbyeasy_mcp.http import serve

        overrides = {k: v for k, v in {"host": args.host, "port": args.port}.items() if v is not None}
        serve(Settings(**overrides))
    else:
        from lobbyeasy_mcp.server import build_server

        build_server().run("stdio")


if __name__ == "__main__":
    main()
