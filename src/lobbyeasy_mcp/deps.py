"""Wiring shared by tools, resources and prompts: dependencies, caller identity,
and the translation of domain errors into MCP tool errors."""

from __future__ import annotations

import functools
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, ParamSpec, TypeVar

from mcp.server.context import ServerRequestContext
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ResourceError, ResourceNotFoundError, ToolError
from mcp.shared.exceptions import MCPError
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS

from lobbyeasy_mcp.config import Settings
from lobbyeasy_mcp.data.base import LobbyRepository
from lobbyeasy_mcp.errors import LobbyError, NotFoundError
from lobbyeasy_mcp.principal import Principal
from lobbyeasy_mcp.service import LobbyService

log = logging.getLogger("lobbyeasy_mcp")

# Resolves the caller from the low-level request context, which tools, resources,
# prompts *and* server middleware all have access to.
PrincipalResolver = Callable[[ServerRequestContext[Any, Any]], Principal]


@dataclass
class Deps:
    settings: Settings
    repo: LobbyRepository
    service: LobbyService
    resolve_principal: PrincipalResolver

    def principal(self, ctx: Context) -> Principal:
        return self.resolve_principal(ctx.request_context)


P = ParamSpec("P")
R = TypeVar("R")


def _translating(
    expected: Callable[[LobbyError], Exception], unexpected: Callable[[str], Exception]
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Build a decorator that maps domain errors to the right MCP error type.

    * `LobbyError` (anticipated, message written for the model) -> shown verbatim.
    * Anything else -> logged with a short reference id; the caller only gets the id.
      The SDK already withholds unexpected exception text; the id is what lets an
      operator find the traceback when a user reports "it said ref 3f9c2a1b".

    `functools.wraps` keeps `__wrapped__`, and the SDK builds input schemas from
    `inspect.signature`, which follows it, so the decorated function's schema is unchanged.
    """

    def decorator(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return await fn(*args, **kwargs)
            except LobbyError as exc:
                raise expected(exc) from exc
            except (ToolError, ResourceError, MCPError):
                raise
            except Exception as exc:
                ref = uuid.uuid4().hex[:8]
                log.exception("unexpected error in %s (ref %s)", getattr(fn, "__name__", "?"), ref)
                raise unexpected(
                    f"Internal error (ref {ref}). This is a server problem, not your input."
                ) from exc

        return wrapper

    return decorator


def _resource_error(exc: LobbyError) -> Exception:
    return ResourceNotFoundError(str(exc)) if isinstance(exc, NotFoundError) else ResourceError(str(exc))


tool_errors = _translating(lambda e: ToolError(str(e)), ToolError)
resource_errors = _translating(_resource_error, ResourceError)
prompt_errors = _translating(
    lambda e: MCPError(code=INVALID_PARAMS, message=str(e)),
    lambda msg: MCPError(code=INTERNAL_ERROR, message=msg),
)


def as_json(model: Any) -> str:
    return model.model_dump_json(indent=2)
