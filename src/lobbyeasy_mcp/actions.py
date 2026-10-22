"""Write actions: validate -> propose (confirmation token) -> confirm -> execute.

Every write goes through `WriteService.propose()` and `WriteService.confirm()`:

    register_package(...)          -> Proposal(confirmation_token, summary)   # nothing written
    confirm_action(token)          -> ActionOutcome(status="executed", result) # written once

Validation happens twice on purpose: at proposal time (so the summary is truthful
and errors surface early) and again at execution (state may have changed in the
minutes between, e.g. another doorman already handed the package over).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from lobbyeasy_mcp.data.base import NewPackage
from lobbyeasy_mcp.errors import ConflictError, InvalidInputError, NotFoundError
from lobbyeasy_mcp.models import PackageStatus
from lobbyeasy_mcp.notifier import Notifier
from lobbyeasy_mcp.pii import mask_phone
from lobbyeasy_mcp.principal import Permission, Principal
from lobbyeasy_mcp.safety import Safety
from lobbyeasy_mcp.safety.confirmations import PendingAction
from lobbyeasy_mcp.safety.idempotency import request_hash
from lobbyeasy_mcp.service import LobbyService


class Proposal(BaseModel):
    status: Literal["confirmation_required"] = "confirmation_required"
    action: str
    summary: str = Field(description="Show this to the user verbatim and ask for a yes/no")
    confirmation_token: str
    expires_at: datetime
    next_step: str


class ActionOutcome(BaseModel):
    status: Literal["executed", "already_executed", "cancelled"]
    action: str
    result: dict[str, Any] | None = None


@dataclass(frozen=True)
class _Plan:
    summary: str
    execute: Callable[[], Awaitable[dict[str, Any]]]


class WriteService:
    def __init__(self, lobby: LobbyService, safety: Safety, notifier: Notifier) -> None:
        self.lobby = lobby
        self.repo = lobby.repo
        self.safety = safety
        self.notifier = notifier

    # -- planning: each returns a summary + a closure that performs the write -----------
    async def _plan(self, who: Principal, action: str, args: dict[str, Any]) -> _Plan:
        cid = who.condominium_id
        if action == "register_package":
            resident = await self.repo.get_resident(cid, args["resident_id"])
            if resident is None:
                raise NotFoundError(
                    f"Resident {args['resident_id']} not found in this condominium. Use find_residents first."
                )
            apt = await self.repo.get_apartment(cid, resident.apartment_id) if resident.apartment_id else None
            what = args.get("description") or "package"
            code = f", tracking {args['tracking_code']}" if args.get("tracking_code") else ""

            async def do_register() -> dict[str, Any]:
                pkg = await self.repo.insert_package(
                    cid,
                    NewPackage(
                        resident_id=resident.id,
                        tracking_code=args.get("tracking_code"),
                        description=args.get("description"),
                        received_by=args["received_by"],
                    ),
                )
                rec = await self.repo.get_package(cid, pkg.id)
                assert rec is not None
                return self.lobby.package_view(rec).model_dump(mode="json")

            return _Plan(
                f"Register '{what}'{code} for {resident.name} ({apt.label if apt else 'no apartment'}), "
                f"received by {args['received_by']}.",
                do_register,
            )

        if action == "mark_package_withdrawn":
            rec = await self.repo.get_package(cid, args["package_id"])
            if rec is None:
                raise NotFoundError(f"Package {args['package_id']} not found in this condominium.")
            if rec.package.status != PackageStatus.PENDING:
                raise ConflictError(
                    f"Package {rec.package.id} is '{rec.package.status}', not 'pendente'; nothing to withdraw."
                )
            label = rec.apartment.label if rec.apartment else "no apartment"

            async def do_withdraw() -> dict[str, Any]:
                updated = await self.repo.mark_withdrawn(cid, rec.package.id, self.lobby.now())
                if updated is None:  # compare-and-set lost: someone else got there first
                    raise ConflictError(f"Package {rec.package.id} is no longer pending; it was not changed.")
                fresh = await self.repo.get_package(cid, rec.package.id)
                assert fresh is not None
                return self.lobby.package_view(fresh).model_dump(mode="json")

            return _Plan(
                f"Mark package {rec.package.id} ('{rec.package.description or 'package'}') for "
                f"{rec.resident.name} ({label}) as picked up now.",
                do_withdraw,
            )

        if action == "notify_resident":
            resident = await self.repo.get_resident(cid, args["resident_id"])
            if resident is None:
                raise NotFoundError(f"Resident {args['resident_id']} not found. Use find_residents first.")
            if not resident.phone:
                raise ConflictError(
                    f"{resident.name} has no contact on file; tell the doorman to call the unit."
                )
            for pid in args.get("package_ids") or []:
                rec = await self.repo.get_package(cid, pid)
                if rec is None or rec.resident.id != resident.id:
                    raise InvalidInputError(f"Package {pid} does not belong to {resident.name}.")
            phone, message = resident.phone, args["message"]

            async def do_notify() -> dict[str, Any]:
                sent = await self.notifier.send(phone, message)
                return {
                    "resident_id": resident.id,
                    "to": mask_phone(sent.to),
                    "channel": sent.channel,
                    "provider_id": sent.provider_id,
                    "sent_at": sent.sent_at.isoformat(),
                }

            return _Plan(
                f'Send to {resident.name} at {mask_phone(phone)} via {self.notifier.channel}: "{message}"',
                do_notify,
            )

        raise InvalidInputError(f"Unknown action '{action}'.")

    # -- public API ---------------------------------------------------------------------
    async def propose(
        self, who: Principal, action: str, args: dict[str, Any], idempotency_key: str | None
    ) -> Proposal | ActionOutcome:
        who.require(Permission.WRITE, action.replace("_", " "))
        if idempotency_key:
            done = await self.safety.idempotency.get(who.key_id, idempotency_key)
            if done is not None:
                return self._replay(done, action, args, idempotency_key)
        plan = await self._plan(who, action, args)
        pending = self.safety.confirmations.create(
            key_id=who.key_id,
            condominium_id=str(who.condominium_id),
            action=action,
            args=args,
            summary=plan.summary,
            idempotency_key=idempotency_key,
        )
        return Proposal(
            action=action,
            summary=plan.summary,
            confirmation_token=pending.token,
            expires_at=pending.expires_at,
            next_step="Show `summary` to the user. Only if they explicitly agree, call "
            "confirm_action with this confirmation_token. Otherwise call cancel_action.",
        )

    async def confirm(self, who: Principal, token: str) -> ActionOutcome:
        who.require(Permission.WRITE, "confirm actions")
        pending = self.safety.confirmations.take(token, who.key_id)
        if pending == "expired":
            raise ConflictError(
                "This confirmation expired. Call the original tool again for a fresh summary."
            )
        if not isinstance(pending, PendingAction):
            raise NotFoundError(
                "Unknown or already used confirmation_token. Call the original write tool again."
            )
        idem = pending.idempotency_key
        if idem:
            existing = await self.safety.idempotency.reserve(
                who.key_id, idem, pending.action, request_hash(pending.action, pending.args)
            )
            if existing is not None:
                return self._replay(existing, pending.action, pending.args, idem)
        try:
            plan = await self._plan(who, pending.action, pending.args)  # re-validate against current state
            result = await plan.execute()
        except BaseException:  # includes cancellation: never leave a reservation dangling
            if idem:
                await self.safety.idempotency.release(who.key_id, idem)
            raise
        if idem:
            await self.safety.idempotency.complete(who.key_id, idem, result)
        return ActionOutcome(status="executed", action=pending.action, result=result)

    def cancel(self, who: Principal, token: str) -> ActionOutcome:
        pending = self.safety.confirmations.discard(token, who.key_id)
        if pending is None:
            raise NotFoundError("Unknown or already used confirmation_token; nothing to cancel.")
        return ActionOutcome(status="cancelled", action=pending.action)

    @staticmethod
    def _replay(record: Any, action: str, args: dict[str, Any], idem: str) -> ActionOutcome:
        if record.tool != action or record.request_hash != request_hash(action, args):
            raise ConflictError(
                f"idempotency_key '{idem}' was already used for a different request. "
                "Use a new key for a new action."
            )
        if record.status != "completed":
            raise ConflictError(
                f"The action for idempotency_key '{idem}' is still running; retry in a moment."
            )
        return ActionOutcome(status="already_executed", action=action, result=record.result)
