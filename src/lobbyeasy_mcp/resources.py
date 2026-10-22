"""MCP resources: read-only context the *application* (or user) attaches, as opposed
to tools, which the *model* decides to call.

URI scheme `lobby://`. Templates (`{condominium_id}`) are listed via
`resources/templates/list`; a key may only read its own condominium.
"""

from __future__ import annotations

from mcp.server.mcpserver import Context, MCPServer

from lobbyeasy_mcp.deps import Deps, as_json, resource_errors

LIFECYCLE = """\
# LobbyEasy package lifecycle

| Field | Values | Meaning |
|---|---|---|
| `encomendas.status` | `pendente` | Package is waiting in the lobby |
| | `retirada` | Resident picked it up (`data_retirada` set) |
| | `entregue` | Declared in the app's types but never written by current code |
| `withdrawal_sessions.status` | `pending` -> `confirmed` / `expired` / `cancelled` | A 5-minute QR (or manual) pickup of several packages of one apartment |
| `confirmation_method` | `qr_scan`, `manual` | Manual needs a reason: `sem_celular`, `idoso`, `portador_necessidades`, `outro` |

Rules mirrored from the app:
- A package belongs to a resident (`morador`), who belongs to an apartment and a condominium.
- Only `pendente` packages can be withdrawn; withdrawal sets `status='retirada'` and `data_retirada=now()`.
- A withdrawal session only accepts packages that are pending *and* belong to that apartment.
- Residents' phone (`contato`) and CPF are personal data: masked unless explicitly revealed.
"""


def register_resources(mcp: MCPServer, deps: Deps) -> None:
    service = deps.service

    @mcp.resource(
        "lobby://condominiums/{condominium_id}/summary",
        title="Condominium summary",
        description="Name, apartment count, pending packages, oldest waiting package and today's stats.",
        mime_type="application/json",
    )
    @resource_errors
    async def condominium_summary(condominium_id: str, ctx: Context) -> str:
        return as_json(await service.condominium_summary(deps.principal(ctx), condominium_id))

    @mcp.resource(
        "lobby://condominiums/{condominium_id}/pending",
        title="Pending packages (markdown)",
        description="Every package still waiting in the lobby, as a markdown table.",
        mime_type="text/markdown",
    )
    @resource_errors
    async def pending_markdown(condominium_id: str, ctx: Context) -> str:
        who = deps.principal(ctx)
        summary = await service.condominium_summary(who, condominium_id)  # also enforces scoping
        pending = await service.list_pending(who, None, 100)
        lines = [
            f"# Pending packages - {summary.name}",
            "",
            f"{pending.total_pending} package(s) waiting.",
            "",
            "| id | apartment | resident | description | tracking | arrived | days |",
            "|---|---|---|---|---|---|---|",
        ]
        for p in pending.packages:
            lines.append(
                f"| {p.id} | {p.apartment.label if p.apartment else '-'} | {p.resident.name} | "
                f"{p.description or '-'} | {p.tracking_code or '-'} | {p.arrived_at:%Y-%m-%d %H:%M} | "
                f"{p.days_waiting} |"
            )
        return "\n".join(lines) + "\n"

    @mcp.resource(
        "lobby://reference/package-lifecycle",
        title="Package lifecycle and statuses",
        description="What each status means and the business rules the server enforces.",
        mime_type="text/markdown",
    )
    def lifecycle() -> str:
        return LIFECYCLE
