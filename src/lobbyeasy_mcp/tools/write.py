"""Write tools: registered only when `LOBBY_ENABLE_WRITES=true`, hidden from (and
refused for) callers whose role lacks the `write` permission, and two-step.

None of these tools changes anything by itself. Each returns a `Proposal` with a
`confirmation_token`; `confirm_action` performs the write. Annotations tell clients
the truth about the *confirm* step: it is destructive and not read-only.
"""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from lobbyeasy_mcp.actions import ActionOutcome, Proposal, WriteService
from lobbyeasy_mcp.deps import Deps, tool_errors
from lobbyeasy_mcp.errors import InvalidInputError
from lobbyeasy_mcp.views import PackageId, ResidentId

WRITE_TOOL_NAMES = frozenset(
    {"register_package", "mark_package_withdrawn", "notify_resident", "confirm_action", "cancel_action"}
)

PROPOSE = ToolAnnotations(readOnlyHint=True, idempotentHint=False, openWorldHint=False)
COMMIT = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True)

IdempotencyKey = Annotated[
    str | None,
    Field(
        min_length=8,
        max_length=100,
        description="Optional unique id for this action (e.g. a UUID). Retrying with the same key "
        "never performs the action twice.",
    ),
]


def register_write_tools(mcp: MCPServer, deps: Deps, writes: WriteService) -> None:
    @mcp.tool(title="Register package (propose)", annotations=PROPOSE)
    @tool_errors
    async def register_package(
        ctx: Context,
        resident_id: ResidentId,
        received_by: Annotated[
            str, Field(min_length=2, max_length=100, description="Doorman name logging the arrival")
        ],
        description: Annotated[str | None, Field(max_length=500, description="e.g. 'Caixa Amazon'")] = None,
        tracking_code: Annotated[str | None, Field(max_length=100)] = None,
        idempotency_key: IdempotencyKey = None,
    ) -> Proposal | ActionOutcome:
        """Propose logging a newly arrived package for a resident. Returns a summary and a
        confirmation_token; nothing is saved until confirm_action is called."""
        if not (description or tracking_code):
            raise InvalidInputError(
                "Give a description or a tracking_code so the package can be found later."
            )
        args = {
            "resident_id": resident_id,
            "received_by": received_by.strip(),
            "description": description,
            "tracking_code": tracking_code,
        }
        return await writes.propose(deps.principal(ctx), "register_package", args, idempotency_key)

    @mcp.tool(title="Mark package withdrawn (propose)", annotations=PROPOSE)
    @tool_errors
    async def mark_package_withdrawn(
        ctx: Context, package_id: PackageId, idempotency_key: IdempotencyKey = None
    ) -> Proposal | ActionOutcome:
        """Propose marking a pending package as picked up by its resident. Returns a
        confirmation_token; nothing changes until confirm_action is called."""
        return await writes.propose(
            deps.principal(ctx), "mark_package_withdrawn", {"package_id": package_id}, idempotency_key
        )

    @mcp.tool(title="Notify resident (propose)", annotations=PROPOSE)
    @tool_errors
    async def notify_resident(
        ctx: Context,
        resident_id: ResidentId,
        message: Annotated[str, Field(min_length=5, max_length=500, description="Text to send, in pt-BR")],
        package_ids: Annotated[
            list[int] | None, Field(max_length=20, description="Packages this message is about (validated)")
        ] = None,
        idempotency_key: IdempotencyKey = None,
    ) -> Proposal | ActionOutcome:
        """Propose sending a short message to a resident (e.g. 'your package is at the lobby').
        Returns a confirmation_token; nothing is sent until confirm_action is called."""
        args = {"resident_id": resident_id, "message": message.strip(), "package_ids": package_ids or []}
        return await writes.propose(deps.principal(ctx), "notify_resident", args, idempotency_key)

    @mcp.tool(title="Confirm a proposed action", annotations=COMMIT)
    @tool_errors
    async def confirm_action(
        ctx: Context,
        confirmation_token: Annotated[str, Field(min_length=10, max_length=100)],
    ) -> ActionOutcome:
        """Execute a previously proposed write. Call ONLY after the user explicitly approved
        the exact summary returned by the proposing tool. Tokens are single-use and expire."""
        return await writes.confirm(deps.principal(ctx), confirmation_token)

    @mcp.tool(title="Cancel a proposed action", annotations=PROPOSE)
    @tool_errors
    async def cancel_action(
        ctx: Context,
        confirmation_token: Annotated[str, Field(min_length=10, max_length=100)],
    ) -> ActionOutcome:
        """Discard a proposed write the user declined."""
        return writes.cancel(deps.principal(ctx), confirmation_token)
