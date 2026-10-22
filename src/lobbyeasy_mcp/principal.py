"""Who is calling, and what may they do?

A `Principal` is resolved for every request: from the bearer token on the remote
HTTP server, or from the environment on a local stdio server. It carries the one
condominium the caller is scoped to, so tools never accept a condominium id from
the model (a prompt-injected "now look at condominium X" has nothing to bind to).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from lobbyeasy_mcp.errors import PermissionDeniedError


class Permission(StrEnum):
    READ = "read"  # packages, apartments, masked residents, stats
    PII = "pii"  # may ask for unmasked phone / CPF
    WRITE = "write"  # register / withdraw packages, notify residents (two-step)


class Role(StrEnum):
    """MCP-side roles. `porteiro` mirrors the app's doorman role (`app_metadata.role`)."""

    VIEWER = "viewer"  # e.g. a building manager's analytics assistant
    PORTEIRO = "porteiro"  # the doorman's assistant: reads, PII, writes
    ADMIN = "admin"  # same as porteiro today; reserved for key/audit management


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: frozenset({Permission.READ}),
    Role.PORTEIRO: frozenset({Permission.READ, Permission.PII, Permission.WRITE}),
    Role.ADMIN: frozenset(Permission),
}


@dataclass(frozen=True)
class Principal:
    key_id: str  # API key id, or "stdio" for a local server
    condominium_id: UUID
    role: Role

    def can(self, permission: Permission) -> bool:
        return permission in ROLE_PERMISSIONS[self.role]

    def require(self, permission: Permission, action: str) -> None:
        if not self.can(permission):
            raise PermissionDeniedError(
                f"Role '{self.role}' (key '{self.key_id}') lacks the '{permission}' permission needed to "
                f"{action}. Ask the server operator for a key with a role that grants it."
            )
