"""In-memory backend over `fixtures.build_dataset()`.

Used by the test suite, by `make demo`, and as the zero-setup default for
`uvx lobbyeasy-mcp`. It must behave exactly like the Postgres backend; the
contract tests in `tests/test_repository_contract.py` run against both.
"""

from __future__ import annotations

import copy
from collections import Counter
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from lobbyeasy_mcp.data.base import DailyCounts, NewPackage, PackageQuery, PackageRecord
from lobbyeasy_mcp.fixtures import Dataset, build_dataset
from lobbyeasy_mcp.models import (
    Apartment,
    Condominium,
    Package,
    PackageStatus,
    Resident,
    WithdrawalSession,
    WithdrawalStatus,
)


class InMemoryRepository:
    def __init__(self, dataset: Dataset | None = None) -> None:
        self.data = copy.deepcopy(dataset) if dataset else build_dataset()

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    # -- helpers ---------------------------------------------------------------
    def _residents(self, cid: UUID) -> dict[int, Resident]:
        return {r.id: r for r in self.data.residents if r.condominium_id == cid}

    def _apartments(self, cid: UUID) -> dict[int, Apartment]:
        return {a.id: a for a in self.data.apartments if a.condominium_id == cid}

    def _records(self, cid: UUID) -> list[PackageRecord]:
        residents, apartments = self._residents(cid), self._apartments(cid)
        out = []
        for p in self.data.packages:
            r = residents.get(p.resident_id)
            if r is None:  # belongs to another condominium
                continue
            apt = apartments.get(r.apartment_id) if r.apartment_id is not None else None
            out.append(PackageRecord(package=p, resident=r, apartment=apt))
        return out

    # -- condominium / apartments ------------------------------------------------
    async def get_condominium(self, condominium_id: UUID) -> Condominium | None:
        return next((c for c in self.data.condominiums if c.id == condominium_id), None)

    async def list_apartments(self, condominium_id: UUID) -> list[Apartment]:
        return sorted(self._apartments(condominium_id).values(), key=lambda a: (a.block, a.number))

    async def get_apartment(self, condominium_id: UUID, apartment_id: int) -> Apartment | None:
        return self._apartments(condominium_id).get(apartment_id)

    async def find_apartment(self, condominium_id: UUID, block: str, number: str) -> Apartment | None:
        for a in self._apartments(condominium_id).values():
            if a.block.casefold() == block.strip().casefold() and a.number == number.strip():
                return a
        return None

    # -- residents -----------------------------------------------------------------
    async def search_residents(
        self,
        condominium_id: UUID,
        *,
        name: str | None = None,
        apartment_id: int | None = None,
        limit: int = 20,
    ) -> list[Resident]:
        rows = list(self._residents(condominium_id).values())
        if name:
            rows = [r for r in rows if name.casefold() in r.name.casefold()]
        if apartment_id is not None:
            rows = [r for r in rows if r.apartment_id == apartment_id]
        return sorted(rows, key=lambda r: (r.name, r.id))[:limit]

    async def get_resident(self, condominium_id: UUID, resident_id: int) -> Resident | None:
        return self._residents(condominium_id).get(resident_id)

    # -- packages ------------------------------------------------------------------
    async def get_package(self, condominium_id: UUID, package_id: int) -> PackageRecord | None:
        return next((r for r in self._records(condominium_id) if r.package.id == package_id), None)

    async def search_packages(self, condominium_id: UUID, query: PackageQuery) -> list[PackageRecord]:
        def keep(rec: PackageRecord) -> bool:
            p = rec.package
            if query.status and p.status != query.status:
                return False
            if query.apartment_id is not None and rec.resident.apartment_id != query.apartment_id:
                return False
            if query.resident_id is not None and p.resident_id != query.resident_id:
                return False
            if query.resident_name and query.resident_name.casefold() not in rec.resident.name.casefold():
                return False
            if (
                query.tracking_code
                and query.tracking_code.casefold() not in (p.tracking_code or "").casefold()
            ):
                return False
            if query.arrived_from and p.arrived_at < query.arrived_from:
                return False
            if query.arrived_before and p.arrived_at >= query.arrived_before:
                return False
            return not (query.after and (p.arrived_at, p.id) >= query.after)

        rows = [r for r in self._records(condominium_id) if keep(r)]
        rows.sort(key=lambda r: (r.package.arrived_at, r.package.id), reverse=True)
        return rows[: query.limit]

    async def count_packages(
        self, condominium_id: UUID, *, status: PackageStatus | None = None, apartment_id: int | None = None
    ) -> int:
        return sum(
            1
            for r in self._records(condominium_id)
            if (status is None or r.package.status == status)
            and (apartment_id is None or r.resident.apartment_id == apartment_id)
        )

    # -- withdrawal sessions -----------------------------------------------------------
    async def list_withdrawal_sessions(
        self, condominium_id: UUID, *, apartment_id: int | None = None, limit: int = 10
    ) -> list[WithdrawalSession]:
        apts = self._apartments(condominium_id)
        rows = [
            s
            for s in self.data.withdrawal_sessions
            if s.apartment_id in apts and (apartment_id is None or s.apartment_id == apartment_id)
        ]
        return sorted(rows, key=lambda s: s.created_at, reverse=True)[:limit]

    # -- stats ---------------------------------------------------------------------------
    async def daily_counts(
        self, condominium_id: UUID, start: datetime, end: datetime, tz: str
    ) -> DailyCounts:
        zone = ZoneInfo(tz)
        records = self._records(condominium_id)
        arrived = [r.package for r in records if start <= r.package.arrived_at < end]
        withdrawn = [
            r.package for r in records if r.package.withdrawn_at and start <= r.package.withdrawn_at < end
        ]
        still_pending = [
            r
            for r in records
            if r.package.arrived_at < end
            and r.package.status != PackageStatus.DELIVERED
            and (r.package.withdrawn_at is None or r.package.withdrawn_at >= end)
        ]
        dwell = [(p.withdrawn_at - p.arrived_at).total_seconds() / 3600 for p in withdrawn if p.withdrawn_at]
        by_hour = Counter(p.arrived_at.astimezone(zone).hour for p in arrived)

        apts = self._apartments(condominium_id)
        outcomes: Counter[str] = Counter()
        for s in self.data.withdrawal_sessions:
            if s.apartment_id in apts and start <= s.created_at < end:
                key = s.status.value
                if s.status == WithdrawalStatus.CONFIRMED and s.confirmation_method:
                    key = f"confirmed_{s.confirmation_method.value}"
                outcomes[key] += 1

        oldest = min(still_pending, key=lambda r: (r.package.arrived_at, r.package.id), default=None)
        return DailyCounts(
            arrivals=len(arrived),
            withdrawals=len(withdrawn),
            pending_at_end=len(still_pending),
            avg_hours_to_withdrawal=round(sum(dwell) / len(dwell), 2) if dwell else None,
            arrivals_by_hour=dict(sorted(by_hour.items())),
            sessions_by_outcome=dict(sorted(outcomes.items())),
            oldest_pending=oldest,
        )

    # -- writes --------------------------------------------------------------------------
    async def insert_package(self, condominium_id: UUID, new: NewPackage) -> Package:
        if new.resident_id not in self._residents(condominium_id):
            raise LookupError(f"resident {new.resident_id} not in condominium")
        now = datetime.now().astimezone()
        pkg = Package(
            id=max((p.id for p in self.data.packages), default=0) + 1,
            resident_id=new.resident_id,
            tracking_code=new.tracking_code,
            description=new.description,
            received_by=new.received_by,
            status=PackageStatus.PENDING,
            arrived_at=now,
            created_at=now,
        )
        self.data.packages.append(pkg)
        return pkg

    async def mark_withdrawn(self, condominium_id: UUID, package_id: int, at: datetime) -> Package | None:
        rec = await self.get_package(condominium_id, package_id)
        if rec is None or rec.package.status != PackageStatus.PENDING:
            return None
        updated = rec.package.model_copy(update={"status": PackageStatus.WITHDRAWN, "withdrawn_at": at})
        idx = self.data.packages.index(rec.package)
        self.data.packages[idx] = updated
        return updated
