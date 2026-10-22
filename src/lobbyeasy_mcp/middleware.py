"""Server middleware: one place that sees every request before any tool runs.

For `tools/call` it (1) identifies the caller, (2) refuses write tools to roles
without `write`, (3) applies the per-key rate limit and (4) writes an audit entry
with redacted arguments and the outcome. For `tools/list` it hides write tools from
roles that cannot use them, so the model is not even tempted.

Putting this in middleware rather than in each tool means a new tool is audited and
rate-limited by default; forgetting is not possible.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.types import CallToolResult, TextContent

from lobbyeasy_mcp.deps import PrincipalResolver
from lobbyeasy_mcp.errors import LobbyError
from lobbyeasy_mcp.principal import Permission, Principal
from lobbyeasy_mcp.safety import Safety
from lobbyeasy_mcp.safety.audit import AuditEntry, Outcome, redact

log = logging.getLogger("lobbyeasy_mcp.gateway")

WRITE_COST = 3.0  # writes spend more of the bucket than reads


def _error(text: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], is_error=True)


class Gateway:
    def __init__(
        self, resolve_principal: PrincipalResolver, safety: Safety, write_tools: frozenset[str]
    ) -> None:
        self.resolve = resolve_principal
        self.safety = safety
        self.write_tools = write_tools

    def _who(self, ctx: ServerRequestContext[Any, Any]) -> Principal | None:
        try:
            return self.resolve(ctx)
        except LobbyError:
            return None

    async def __call__(self, ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
        if ctx.method == "tools/list":
            return self._filter_tools(ctx, await call_next(ctx))
        if ctx.method != "tools/call":
            return await call_next(ctx)

        params = ctx.params or {}
        tool = str(params.get("name", "?"))
        args = params.get("arguments") or {}
        who = self._who(ctx)
        started = time.perf_counter()
        outcome: Outcome = "ok"
        error: str | None = None
        try:
            if who is None:
                outcome, error = "denied", "unauthenticated"
                return _error("No caller identity on this request.")
            if tool in self.write_tools and not who.can(Permission.WRITE):
                outcome, error = "denied", "role lacks write"
                return _error(
                    f"Tool '{tool}' needs the 'write' permission; role '{who.role}' does not have it."
                )
            allowed, wait = self.safety.rate_limiter.try_acquire(
                who.key_id, WRITE_COST if tool in self.write_tools else 1.0
            )
            if not allowed:
                outcome, error = "rate_limited", f"retry in {wait:.1f}s"
                return _error(f"Rate limit exceeded for this API key. Retry in {wait:.1f} seconds.")
            result = await call_next(ctx)
            if isinstance(result, dict) and result.get("isError"):
                outcome = "error"
                content = result.get("content") or [{}]
                error = str(content[0].get("text", ""))[:500]
            return result
        except Exception as exc:
            outcome, error = "error", type(exc).__name__
            raise
        finally:
            entry = AuditEntry(
                key_id=who.key_id if who else "anonymous",
                condominium_id=str(who.condominium_id) if who else None,
                role=who.role.value if who else None,
                tool=tool,
                arguments=redact(args),
                outcome=outcome,
                duration_ms=int((time.perf_counter() - started) * 1000),
                error=error,
                request_id=str(ctx.request_id) if ctx.request_id is not None else None,
            )
            try:
                await self.safety.audit.record(entry)
            except Exception:  # an audit outage must be loud, but must not take reads down
                log.exception("failed to write audit entry for %s", tool)

    def _filter_tools(self, ctx: ServerRequestContext[Any, Any], result: HandlerResult) -> HandlerResult:
        who = self._who(ctx)
        if who is not None and who.can(Permission.WRITE):
            return result
        if isinstance(result, dict) and isinstance(result.get("tools"), list):
            return {**result, "tools": [t for t in result["tools"] if t.get("name") not in self.write_tools]}
        return result
