"""Tool input and output schemas.

These are the shapes the *model* sees. The SDK turns each into JSON Schema (inputs
in `tools/list`, outputs as `outputSchema` + `structuredContent`), so field
descriptions are prompt text: keep them short, concrete and unambiguous.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field

from lobbyeasy_mcp.models import ConfirmationMethod, ManualReason, PackageStatus, WithdrawalStatus

# Reusable argument types -------------------------------------------------------------
PackageId = Annotated[int, Field(ge=1, description="Numeric package id (encomendas.id)")]
ResidentId = Annotated[int, Field(ge=1, description="Numeric resident id (moradores.id)")]
ApartmentRefArg = Annotated[
    int | str | None,
    Field(
        description="Apartment as numeric id (e.g. 3) or 'BLOCK-NUMBER' label (e.g. 'A-101'). "
        "Call list_apartments to see valid values."
    ),
]
Limit = Annotated[int, Field(ge=1, le=100, description="Max items to return (1-100)")]


class PackageFilters(BaseModel):
    """Filters for search_packages. All optional; combined with AND."""

    status: PackageStatus | None = Field(
        default=None, description="'pendente' (in the lobby) or 'retirada' (picked up)"
    )
    apartment: int | str | None = Field(default=None, description="Apartment id or label like 'A-101'")
    resident_name: str | None = Field(
        default=None, min_length=2, max_length=150, description="Case-insensitive part of the resident name"
    )
    tracking_code: str | None = Field(
        default=None, min_length=3, max_length=100, description="Case-insensitive part of the tracking code"
    )
    arrived_from: date | None = Field(default=None, description="First arrival day, inclusive (lobby time)")
    arrived_to: date | None = Field(default=None, description="Last arrival day, inclusive (lobby time)")


# Outputs -------------------------------------------------------------------------------
class ApartmentView(BaseModel):
    id: int
    block: str
    number: str
    label: str = Field(description="'BLOCK-NUMBER', e.g. 'A-101'")


class ResidentRef(BaseModel):
    id: int
    name: str


class PackageView(BaseModel):
    id: int
    status: PackageStatus
    tracking_code: str | None
    description: str | None
    arrived_at: datetime = Field(description="Arrival time in lobby-local time")
    withdrawn_at: datetime | None
    received_by: str | None = Field(description="Doorman who logged the arrival")
    days_waiting: float | None = Field(description="For pending packages: days since arrival")
    resident: ResidentRef
    apartment: ApartmentView | None


class PendingPackages(BaseModel):
    total_pending: int = Field(description="All pending packages matching the scope, even beyond `limit`")
    packages: list[PackageView]


class PackagePage(BaseModel):
    items: list[PackageView]
    has_more: bool
    next_cursor: str | None = Field(description="Pass back as `cursor` to get the next page")


class ResidentView(BaseModel):
    id: int
    name: str
    apartment: ApartmentView | None
    phone: str | None = Field(description="`contato`; masked unless reveal_pii was granted")
    cpf: str | None = Field(description="CPF; masked unless reveal_pii was granted")
    has_signature_on_file: bool
    pii_masked: bool


class WithdrawalSessionView(BaseModel):
    id: UUID
    status: WithdrawalStatus
    method: ConfirmationMethod | None
    manual_reason: ManualReason | None
    package_ids: list[int]
    created_at: datetime
    confirmed_at: datetime | None
    created_by: str | None


class ApartmentSummary(BaseModel):
    apartment: ApartmentView
    residents: list[ResidentView]
    pending_count: int
    pending_packages: list[PackageView]
    total_packages: int
    recent_withdrawal_sessions: list[WithdrawalSessionView]


class DailyStats(BaseModel):
    date: date
    timezone: str
    arrivals: int
    withdrawals: int
    pending_at_end_of_day: int = Field(description="Packages still in the lobby at the end of the day")
    avg_hours_to_withdrawal: float | None = Field(
        description="Arrival->pickup, for packages picked up this day"
    )
    arrivals_by_hour: dict[str, int] = Field(description="Local hour '08' -> arrivals")
    busiest_hour: str | None
    withdrawal_sessions: dict[str, int] = Field(
        description="confirmed_qr_scan / confirmed_manual / expired / cancelled / pending counts"
    )
    oldest_pending: PackageView | None


class CondominiumSummary(BaseModel):
    id: UUID
    name: str
    address: str | None
    apartments: int
    pending_packages: int
    oldest_pending: PackageView | None
    today: DailyStats
