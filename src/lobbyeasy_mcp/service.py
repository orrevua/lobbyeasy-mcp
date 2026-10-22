"""Read-side business logic, independent of MCP.

Layering: MCP tools/resources/prompts (server.py) -> LobbyService (this file) ->
LobbyRepository (data/). The service is where permissions, PII masking, time zone
handling and pagination cursors live, so every MCP surface (tool, resource,
prompt) gets the same rules for free and the logic is unit-testable without MCP.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from lobbyeasy_mcp.data.base import LobbyRepository, PackageQuery, PackageRecord
from lobbyeasy_mcp.errors import InvalidInputError, NotFoundError, PermissionDeniedError
from lobbyeasy_mcp.models import Apartment, PackageStatus, Resident, WithdrawalSession
from lobbyeasy_mcp.pii import format_cpf, mask_cpf, mask_phone
from lobbyeasy_mcp.principal import Permission, Principal
from lobbyeasy_mcp.views import (
    ApartmentSummary,
    ApartmentView,
    CondominiumSummary,
    DailyStats,
    PackageFilters,
    PackagePage,
    PackageView,
    PendingPackages,
    ResidentRef,
    ResidentView,
    WithdrawalSessionView,
)

_LABEL = re.compile(r"^\s*(?P<block>[^\s-]+)\s*[- /]\s*(?P<number>\w+)\s*$")


class LobbyService:
    def __init__(
        self,
        repo: LobbyRepository,
        *,
        timezone: str = "America/Sao_Paulo",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repo = repo
        self.tz_name = timezone
        self.tz = ZoneInfo(timezone)
        self._clock = clock or (lambda: datetime.now(self.tz))

    def now(self) -> datetime:
        return self._clock().astimezone(self.tz)

    # -- mapping helpers ---------------------------------------------------------------
    @staticmethod
    def apartment_view(a: Apartment) -> ApartmentView:
        return ApartmentView(id=a.id, block=a.block, number=a.number, label=a.label)

    def package_view(self, rec: PackageRecord) -> PackageView:
        p = rec.package
        waiting = None
        if p.status == PackageStatus.PENDING:
            waiting = max(0.0, round((self.now() - p.arrived_at).total_seconds() / 86400, 1))
        return PackageView(
            id=p.id,
            status=p.status,
            tracking_code=p.tracking_code,
            description=p.description,
            arrived_at=p.arrived_at.astimezone(self.tz),
            withdrawn_at=p.withdrawn_at.astimezone(self.tz) if p.withdrawn_at else None,
            received_by=p.received_by,
            days_waiting=waiting,
            resident=ResidentRef(id=rec.resident.id, name=rec.resident.name),
            apartment=self.apartment_view(rec.apartment) if rec.apartment else None,
        )

    @staticmethod
    def resident_view(r: Resident, apt: Apartment | None, *, reveal: bool) -> ResidentView:
        return ResidentView(
            id=r.id,
            name=r.name,
            apartment=LobbyService.apartment_view(apt) if apt else None,
            phone=r.phone if reveal else mask_phone(r.phone),
            cpf=format_cpf(r.cpf) if reveal else mask_cpf(r.cpf),
            has_signature_on_file=r.has_signature,
            pii_masked=not reveal,
        )

    def session_view(self, s: WithdrawalSession) -> WithdrawalSessionView:
        return WithdrawalSessionView(
            id=s.id,
            status=s.status,
            method=s.confirmation_method,
            manual_reason=s.manual_reason,
            package_ids=s.package_ids,
            created_at=s.created_at.astimezone(self.tz),
            confirmed_at=s.confirmed_at.astimezone(self.tz) if s.confirmed_at else None,
            created_by=s.created_by,
        )

    def _day_bounds(self, day: date) -> tuple[datetime, datetime]:
        start = datetime.combine(day, time.min, tzinfo=self.tz)
        return start, start + timedelta(days=1)

    # -- apartments ------------------------------------------------------------------------
    async def resolve_apartment(self, who: Principal, ref: int | str) -> Apartment:
        cid = who.condominium_id
        if isinstance(ref, int) or (isinstance(ref, str) and ref.strip().isdigit() and "-" not in ref):
            apt = await self.repo.get_apartment(cid, int(ref))
            if apt is None:
                raise NotFoundError(
                    f"Apartment id {ref} does not exist in this condominium. "
                    "Call list_apartments to see valid ids and labels."
                )
            return apt
        m = _LABEL.match(ref)
        if not m:
            raise InvalidInputError(
                f"Could not parse apartment '{ref}'. Use the 'BLOCK-NUMBER' label (e.g. 'A-101') "
                "or the numeric id from list_apartments."
            )
        apt = await self.repo.find_apartment(cid, m["block"], m["number"])
        if apt is None:
            raise NotFoundError(
                f"No apartment '{m['block']}-{m['number']}' in this condominium. "
                "Call list_apartments to see valid labels."
            )
        return apt

    async def list_apartments(self, who: Principal) -> list[ApartmentView]:
        who.require(Permission.READ, "list apartments")
        return [self.apartment_view(a) for a in await self.repo.list_apartments(who.condominium_id)]

    async def apartment_summary(self, who: Principal, ref: int | str) -> ApartmentSummary:
        who.require(Permission.READ, "read apartment summaries")
        apt = await self.resolve_apartment(who, ref)
        cid = who.condominium_id
        residents = await self.repo.search_residents(cid, apartment_id=apt.id, limit=100)
        pending = await self.repo.search_packages(
            cid, PackageQuery(status=PackageStatus.PENDING, apartment_id=apt.id, limit=50)
        )
        sessions = await self.repo.list_withdrawal_sessions(cid, apartment_id=apt.id, limit=5)
        return ApartmentSummary(
            apartment=self.apartment_view(apt),
            residents=[self.resident_view(r, apt, reveal=False) for r in residents],
            pending_count=await self.repo.count_packages(
                cid, status=PackageStatus.PENDING, apartment_id=apt.id
            ),
            pending_packages=[self.package_view(p) for p in pending],
            total_packages=await self.repo.count_packages(cid, apartment_id=apt.id),
            recent_withdrawal_sessions=[self.session_view(s) for s in sessions],
        )

    # -- packages ---------------------------------------------------------------------------
    async def list_pending(self, who: Principal, apartment: int | str | None, limit: int) -> PendingPackages:
        who.require(Permission.READ, "list packages")
        apt_id = (await self.resolve_apartment(who, apartment)).id if apartment is not None else None
        rows = await self.repo.search_packages(
            who.condominium_id, PackageQuery(status=PackageStatus.PENDING, apartment_id=apt_id, limit=limit)
        )
        total = await self.repo.count_packages(
            who.condominium_id, status=PackageStatus.PENDING, apartment_id=apt_id
        )
        return PendingPackages(total_pending=total, packages=[self.package_view(r) for r in rows])

    async def get_package(self, who: Principal, package_id: int) -> PackageView:
        who.require(Permission.READ, "read packages")
        rec = await self.repo.get_package(who.condominium_id, package_id)
        if rec is None:
            raise NotFoundError(
                f"Package {package_id} not found in this condominium. "
                "Use search_packages (e.g. by tracking_code or resident_name) to find the right id."
            )
        return self.package_view(rec)

    async def search_packages(
        self, who: Principal, filters: PackageFilters, cursor: str | None, limit: int
    ) -> PackagePage:
        who.require(Permission.READ, "search packages")
        if filters.arrived_from and filters.arrived_to and filters.arrived_from > filters.arrived_to:
            raise InvalidInputError("arrived_from is after arrived_to; swap them or drop one.")
        apt_id = (
            (await self.resolve_apartment(who, filters.apartment)).id
            if filters.apartment is not None
            else None
        )
        fingerprint = _fingerprint(filters)
        query = PackageQuery(
            status=filters.status,
            apartment_id=apt_id,
            resident_name=filters.resident_name,
            tracking_code=filters.tracking_code,
            arrived_from=self._day_bounds(filters.arrived_from)[0] if filters.arrived_from else None,
            arrived_before=self._day_bounds(filters.arrived_to)[1] if filters.arrived_to else None,
            after=decode_cursor(cursor, fingerprint) if cursor else None,
            limit=limit + 1,  # fetch one extra row to learn whether another page exists
        )
        rows = await self.repo.search_packages(who.condominium_id, query)
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = None
        if has_more:
            last = rows[-1].package
            next_cursor = encode_cursor(last.arrived_at, last.id, fingerprint)
        return PackagePage(
            items=[self.package_view(r) for r in rows], has_more=has_more, next_cursor=next_cursor
        )

    # -- residents ----------------------------------------------------------------------------
    async def find_residents(
        self,
        who: Principal,
        *,
        name: str | None,
        apartment: int | str | None,
        reveal_pii: bool,
        limit: int,
    ) -> list[ResidentView]:
        who.require(Permission.READ, "look up residents")
        if reveal_pii and not who.can(Permission.PII):
            raise PermissionDeniedError(
                f"Role '{who.role}' cannot reveal resident phone/CPF. Call again with reveal_pii=false "
                "(masked values still show the last digits for disambiguation)."
            )
        if not name and apartment is None:
            raise InvalidInputError("Give at least `name` (2+ letters) or `apartment` to look residents up.")
        apt = await self.resolve_apartment(who, apartment) if apartment is not None else None
        residents = await self.repo.search_residents(
            who.condominium_id, name=name, apartment_id=apt.id if apt else None, limit=limit
        )
        apartments = {a.id: a for a in await self.repo.list_apartments(who.condominium_id)}
        return [
            self.resident_view(r, apartments.get(r.apartment_id or -1), reveal=reveal_pii) for r in residents
        ]

    # -- stats ----------------------------------------------------------------------------------
    async def daily_stats(self, who: Principal, day: date | None) -> DailyStats:
        who.require(Permission.READ, "read lobby statistics")
        day = day or self.now().date()
        start, end = self._day_bounds(day)
        counts = await self.repo.daily_counts(who.condominium_id, start, end, self.tz_name)
        by_hour = {f"{h:02d}": n for h, n in sorted(counts.arrivals_by_hour.items())}
        busiest = max(by_hour, key=lambda h: by_hour[h]) if by_hour else None
        return DailyStats(
            date=day,
            timezone=self.tz_name,
            arrivals=counts.arrivals,
            withdrawals=counts.withdrawals,
            pending_at_end_of_day=counts.pending_at_end,
            avg_hours_to_withdrawal=counts.avg_hours_to_withdrawal,
            arrivals_by_hour=by_hour,
            busiest_hour=busiest,
            withdrawal_sessions=counts.sessions_by_outcome,
            oldest_pending=self.package_view(counts.oldest_pending) if counts.oldest_pending else None,
        )

    async def condominium_summary(self, who: Principal, condominium_id: UUID | str) -> CondominiumSummary:
        who.require(Permission.READ, "read the condominium summary")
        try:
            requested = UUID(str(condominium_id))
        except ValueError as exc:
            raise InvalidInputError(f"'{condominium_id}' is not a condominium UUID.") from exc
        if requested != who.condominium_id:
            raise PermissionDeniedError(
                f"This key is scoped to condominium {who.condominium_id}; it cannot read {requested}."
            )
        condo = await self.repo.get_condominium(requested)
        if condo is None:
            raise NotFoundError(f"Condominium {requested} does not exist.")
        today = await self.daily_stats(who, None)
        return CondominiumSummary(
            id=condo.id,
            name=condo.name,
            address=condo.address,
            apartments=len(await self.repo.list_apartments(requested)),
            pending_packages=await self.repo.count_packages(requested, status=PackageStatus.PENDING),
            oldest_pending=today.oldest_pending,
            today=today,
        )


# -- cursors ---------------------------------------------------------------------------------
def _fingerprint(filters: PackageFilters) -> str:
    """Short hash of the filters, embedded in cursors so a cursor cannot be replayed
    against different filters (which would silently skip or repeat rows)."""
    raw = json.dumps(filters.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def encode_cursor(arrived_at: datetime, package_id: int, fingerprint: str) -> str:
    payload = json.dumps({"t": arrived_at.isoformat(), "i": package_id, "f": fingerprint})
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, fingerprint: str) -> tuple[datetime, int]:
    """Opaque keyset cursor -> (arrived_at, id). Cursors are not secrets: they only
    narrow a query that is already scoped to the caller's condominium."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded))
        position = (datetime.fromisoformat(data["t"]), int(data["i"]))
        cursor_fingerprint = data["f"]
    except (binascii.Error, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise InvalidInputError("`cursor` is malformed. Repeat the search without a cursor.") from exc
    if cursor_fingerprint != fingerprint:
        raise InvalidInputError(
            "`cursor` was produced by a search with different filters. Repeat the search without a cursor."
        )
    return position
