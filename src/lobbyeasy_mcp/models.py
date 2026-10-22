"""Domain models: Pydantic mirrors of the LobbyEasy tables.

Column names are translated to English for the MCP surface (an LLM reads these
field names and descriptions), but each model documents the Portuguese column it
comes from so you can map it back to `sql/schema.sql` and the Next.js app.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PackageStatus(StrEnum):
    """`encomendas.status` (VARCHAR(20), default 'pendente').

    The app's TypeScript type allows three values. In the current code base only
    'pendente' and 'retirada' are ever written (both the manual "mark withdrawn"
    action and the QR withdrawal flow write 'retirada'); 'entregue' exists in the
    type and the UI label map only.
    """

    PENDING = "pendente"  # waiting in the lobby
    WITHDRAWN = "retirada"  # picked up by the resident
    DELIVERED = "entregue"  # legacy/unused label, kept for fidelity


class WithdrawalStatus(StrEnum):
    """`withdrawal_sessions.status`."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ConfirmationMethod(StrEnum):
    QR_SCAN = "qr_scan"
    MANUAL = "manual"


class ManualReason(StrEnum):
    """Why a doorman confirmed a withdrawal by hand instead of via QR code."""

    NO_PHONE = "sem_celular"
    ELDERLY = "idoso"
    SPECIAL_NEEDS = "portador_necessidades"
    OTHER = "outro"


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True)


class Condominium(_Model):
    """`condominios`: the tenant boundary. Every query is scoped to one."""

    id: UUID
    name: str
    address: str | None = None
    created_at: datetime


class Apartment(_Model):
    """`apartamentos` (unique per condominium on (numero, bloco))."""

    id: int
    condominium_id: UUID
    number: str = Field(description="`numero`, e.g. '101'")
    block: str = Field(description="`bloco`, e.g. 'A'")
    created_at: datetime

    @property
    def label(self) -> str:
        return f"{self.block}-{self.number}"


class Resident(_Model):
    """`moradores`. Holds PII (`contato` phone, `cpf` national id)."""

    id: int
    condominium_id: UUID
    name: str = Field(description="`nome`")
    phone: str | None = Field(default=None, description="`contato` (free text, usually a phone)")
    cpf: str | None = Field(default=None, description="`cpf`, 11 digits, Brazilian taxpayer id")
    apartment_id: int | None = Field(default=None, description="`apartamento_id`")
    has_signature: bool = Field(default=False, description="whether `signature_url` is set")
    created_at: datetime


class Package(_Model):
    """`encomendas`. Tenant scoping is indirect: package -> morador -> condominio."""

    id: int
    tracking_code: str | None = Field(default=None, description="`codigo_rastreio`")
    description: str | None = Field(default=None, description="`descricao`")
    status: PackageStatus
    arrived_at: datetime = Field(description="`data_chegada`")
    withdrawn_at: datetime | None = Field(default=None, description="`data_retirada`")
    received_by: str | None = Field(default=None, description="doorman who logged the arrival")
    resident_id: int = Field(description="`morador_id`")
    created_at: datetime


class WithdrawalSession(_Model):
    """`withdrawal_sessions`: a short-lived (5 min) QR/manual pickup of N packages."""

    id: UUID
    apartment_id: int
    package_ids: list[int]
    status: WithdrawalStatus
    confirmation_method: ConfirmationMethod | None = None
    manual_reason: ManualReason | None = None
    doorman_note: str | None = None
    created_by: str | None = None
    confirmed_by: str | None = None
    created_at: datetime
    expires_at: datetime
    confirmed_at: datetime | None = None


class InviteToken(_Model):
    """`invite_tokens`: how residents sign up into a condominium. Not exposed as a tool."""

    id: UUID
    condominium_id: UUID
    token: str
    created_by: UUID
    expires_at: datetime | None = None
    max_uses: int | None = None
    use_count: int = 0
    invalidated_at: datetime | None = None
    created_at: datetime
