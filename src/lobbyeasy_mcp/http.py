"""Remote MCP server: streamable HTTP + bearer API keys.

    client --Authorization: Bearer lbe_...--> Starlette (SDK)
        AuthenticationMiddleware -> ApiKeyVerifier.verify_token()  (401 if None)
        RequireAuthMiddleware     -> /mcp only; /healthz stays public
        StreamableHTTPSessionManager -> MCPServer -> tools (principal from the token)

The SDK's auth plumbing is OAuth-shaped (it also serves RFC 9728 protected-resource
metadata). We plug static API keys into it through the `TokenVerifier` protocol,
which is the documented extension point for "I already have tokens".
"""

from __future__ import annotations

from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.context import ServerRequestContext
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from lobbyeasy_mcp import __version__
from lobbyeasy_mcp.auth import (
    ApiKeyVerifier,
    FileKeyStore,
    KeyStore,
    PostgresKeyStore,
    principal_from_access_token,
)
from lobbyeasy_mcp.config import Backend, Settings
from lobbyeasy_mcp.data import make_repository
from lobbyeasy_mcp.data.base import LobbyRepository
from lobbyeasy_mcp.errors import PermissionDeniedError
from lobbyeasy_mcp.principal import Principal
from lobbyeasy_mcp.server import build_server


def http_principal(ctx: ServerRequestContext[Any, Any]) -> Principal:
    """The caller is whoever the bearer token says. Never trust tool arguments for this."""
    request = ctx.request
    user = request.scope.get("user") if isinstance(request, Request) else None
    token = getattr(user, "access_token", None) or get_access_token()
    if token is None:  # RequireAuthMiddleware should make this unreachable
        raise PermissionDeniedError("No valid API key on this request. Send 'Authorization: Bearer lbe_...'.")
    return principal_from_access_token(token)


def make_key_store(settings: Settings, repo: LobbyRepository) -> KeyStore:
    choice = settings.key_store
    if choice == "auto":
        choice = (
            "file" if settings.api_keys_file else ("postgres" if settings.backend == Backend.POSTGRES else "")
        )
    if choice == "file":
        if not settings.api_keys_file:
            raise SystemExit("LOBBY_KEY_STORE=file needs LOBBY_API_KEYS_FILE")
        return FileKeyStore(settings.api_keys_file)
    if choice == "postgres":
        pool = getattr(repo, "pool", None)
        if pool is None:
            raise SystemExit("LOBBY_KEY_STORE=postgres needs LOBBY_BACKEND=postgres")
        return PostgresKeyStore(pool)
    raise SystemExit(
        "No API key store configured. Set LOBBY_API_KEYS_FILE (see `lobbyeasy-mcp keys create`) "
        "or use LOBBY_BACKEND=postgres with the mcp_api_keys table."
    )


def build_http_app(
    settings: Settings | None = None,
    *,
    repo: LobbyRepository | None = None,
    key_store: KeyStore | None = None,
) -> Starlette:
    settings = settings or Settings()
    repo = repo or make_repository(settings)
    store = key_store or make_key_store(settings, repo)
    mcp = build_server(
        settings,
        repo=repo,
        resolve_principal=http_principal,
        token_verifier=ApiKeyVerifier(store),
        auth=AuthSettings(
            issuer_url=settings.base_url,  # type: ignore[arg-type]
            resource_server_url=f"{settings.base_url}/mcp",  # type: ignore[arg-type]
            validate_token_resource=False,  # API keys carry no RFC 8707 audience; the key store is the audience
        ),
    )

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "version": __version__})

    return mcp.streamable_http_app(
        stateless_http=settings.stateless_http,
        json_response=settings.json_response,
        host=settings.host,
    )


def serve(settings: Settings | None = None) -> None:
    import uvicorn

    settings = settings or Settings()
    uvicorn.run(build_http_app(settings), host=settings.host, port=settings.port, proxy_headers=True)
