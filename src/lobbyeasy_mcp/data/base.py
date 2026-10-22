"""The data access contract both backends implement.

Design rules (they are what keep a multi-tenant MCP server safe):

1. **Every method takes `condominium_id` first.** There is no "get package by id"
   that could cross tenants; scoping is part of the signature, not an afterthought.
   In LobbyEasy only `apartamentos` and `moradores` carry `condominio_id`; packages
   and withdrawal sessions are scoped *through* those joins.
2. **Return domain models, not rows.** Tools never see SQL or dicts.
3. **No business rules here** beyond what the query needs. "Is this package still
   pending?" lives in the service layer so both backends enforce it identically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID

from lobbyeasy_mcp.models import (
    Apartment,
    Condominium,
    Package,
    PackageStatus,
    Resident,
    WithdrawalSession,
)


@dataclass(frozen=True)
class PackageRecord:
    """A package joined with its resident and (nullable) apartment, like the app's
    `EncomendaComMorador` (`*, morador:moradores(*, apartamento:apartamentos(*))`)."""

    package: Package
    resident: Resident
    apartment: Apartment | None


@dataclass(frozen=True)
class PackageQuery:
    """Filters for `search_packages`. Results are ordered newest arrival first,
    ties broken by id, so `(arrived_at, id)` is a stable keyset cursor."""

    status: PackageStatus | None = None
    apartment_id: int | None = None
    resident_id: int | None = None
    resident_name: str | None = None  # case-insensitive substring (ILIKE)
    tracking_code: str | None = None  # case-insensitive substring (ILIKE)
    arrived_from: datetime | None = None  # inclusive
    arrived_before: datetime | None = None  # exclusive
    after: tuple[datetime, int] | None = None  # keyset: rows strictly "older" than this
    limit: int = 20


@dataclass(frozen=True)
class DailyCounts:
    """Aggregates for one lobby-local day `[start, end)`."""

    arrivals: int
    withdrawals: int
    pending_at_end: int
    avg_hours_to_withdrawal: float | None
    arrivals_by_hour: dict[int, int] = field(default_factory=dict)
    sessions_by_outcome: dict[str, int] = field(default_factory=dict)
    oldest_pending: PackageRecord | None = None


@dataclass(frozen=True)
class NewPackage:
    resident_id: int
    tracking_code: str | None
    description: str | None
    received_by: str | None


class LobbyRepository(Protocol):
    async def open(self) -> None: ...
    async def close(self) -> None: ...

    async def get_condominium(self, condominium_id: UUID) -> Condominium | None: ...
    async def list_apartments(self, condominium_id: UUID) -> list[Apartment]: ...
    async def get_apartment(self, condominium_id: UUID, apartment_id: int) -> Apartment | None: ...
    async def find_apartment(self, condominium_id: UUID, block: str, number: str) -> Apartment | None: ...

    async def search_residents(
        self,
        condominium_id: UUID,
        *,
        name: str | None = None,
        apartment_id: int | None = None,
        limit: int = 20,
    ) -> list[Resident]: ...
    async def get_resident(self, condominium_id: UUID, resident_id: int) -> Resident | None: ...

    async def get_package(self, condominium_id: UUID, package_id: int) -> PackageRecord | None: ...
    async def search_packages(self, condominium_id: UUID, query: PackageQuery) -> list[PackageRecord]: ...
    async def count_packages(
        self, condominium_id: UUID, *, status: PackageStatus | None = None, apartment_id: int | None = None
    ) -> int: ...

    async def list_withdrawal_sessions(
        self, condominium_id: UUID, *, apartment_id: int | None = None, limit: int = 10
    ) -> list[WithdrawalSession]: ...

    async def daily_counts(
        self, condominium_id: UUID, start: datetime, end: datetime, tz: str
    ) -> DailyCounts: ...

    # Writes (used by milestone 4's confirmed write tools)
    async def insert_package(self, condominium_id: UUID, new: NewPackage) -> Package: ...
    async def mark_withdrawn(self, condominium_id: UUID, package_id: int, at: datetime) -> Package | None:
        """Flip a *pending* package to 'retirada'. Returns None if it was not pending."""
        ...
