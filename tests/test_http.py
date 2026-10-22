"""The remote server for real: uvicorn on a free port, a real streamable HTTP MCP
client, bearer API keys. Still offline (loopback only)."""

from __future__ import annotations

import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
import httpx2
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from lobbyeasy_mcp.auth import InMemoryKeyStore, generate_api_key
from lobbyeasy_mcp.config import Settings
from lobbyeasy_mcp.data.memory import InMemoryRepository
from lobbyeasy_mcp.fixtures import ATLANTICO_ID, JARDIM_ID
from lobbyeasy_mcp.http import build_http_app
from lobbyeasy_mcp.principal import Role

VIEWER_KEY, VIEWER = generate_api_key(JARDIM_ID, Role.VIEWER, "jardim viewer")
ATLANTICO_KEY, ATLANTICO = generate_api_key(ATLANTICO_ID, Role.PORTEIRO, "atlantico doorman")
REVOKED_KEY, _revoked = generate_api_key(JARDIM_ID, Role.ADMIN)
REVOKED = _revoked.__class__(**{**_revoked.__dict__, "revoked": True})


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@asynccontextmanager
async def running_server(**overrides) -> AsyncIterator[str]:
    port = free_port()
    settings = Settings(_env_file=None, host="127.0.0.1", port=port, **overrides)  # type: ignore[call-arg]
    app = build_http_app(
        settings,
        repo=InMemoryRepository(),
        key_store=InMemoryKeyStore([VIEWER, ATLANTICO, REVOKED]),
    )
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    async with anyio.create_task_group() as tg:
        tg.start_soon(server.serve)
        with anyio.fail_after(10):
            while not server.started:
                await anyio.sleep(0.02)
        try:
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True


def mcp_client(base: str, key: str | None, mode: str = "auto") -> Client:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    http = httpx2.AsyncClient(headers=headers, timeout=10)
    return Client(streamable_http_client(f"{base}/mcp", http_client=http), mode=mode)


@pytest.mark.parametrize("stateless", [True, False])
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_tools_over_http(stateless: bool, mode: str):
    async with (
        running_server(stateless_http=stateless, json_response=stateless) as base,
        mcp_client(base, VIEWER_KEY, mode) as client,
    ):
        names = {t.name for t in (await client.list_tools()).tools}
        assert "search_packages" in names
        result = await client.call_tool("list_pending_packages", {"limit": 2})
        assert not result.is_error
        assert result.structured_content["total_pending"] == 9


async def test_key_decides_the_condominium():
    async with running_server() as base, mcp_client(base, ATLANTICO_KEY) as client:
        result = await client.call_tool("list_pending_packages", {})
        assert [p["id"] for p in result.structured_content["packages"]] == [19, 17]


async def test_rejects_missing_wrong_and_revoked_keys():
    async with running_server() as base, httpx2.AsyncClient() as http:
        health = await http.get(f"{base}/healthz")
        assert health.status_code == 200 and health.json()["status"] == "ok"

        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        for headers in (
            {},
            {"Authorization": "Bearer nope"},
            {"Authorization": f"Bearer {VIEWER_KEY[:-2]}xx"},  # right key id, wrong secret
            {"Authorization": f"Bearer {REVOKED_KEY}"},
        ):
            r = await http.post(f"{base}/mcp", json=body, headers=headers)
            assert r.status_code == 401, headers
            assert "Bearer" in r.headers["www-authenticate"]
