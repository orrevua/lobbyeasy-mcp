"""Deterministic demo data shared by the in-memory backend and `sql/seed.sql`.

This module is the single source of truth: `scripts/gen_seed.py` renders it into
`sql/seed.sql`, and a test fails if the two drift apart. That is what lets the
same "contract tests" run against both backends and expect identical answers.

Two condominiums exist on purpose: tests assert that a key scoped to one of them
can never see the other's rows (tenant isolation).

All people, phones and CPFs are fictional. CPFs are generated with a valid check
digit so they pass the app's `validateCPF` rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from lobbyeasy_mcp.models import (
    Apartment,
    Condominium,
    ConfirmationMethod,
    InviteToken,
    ManualReason,
    Package,
    PackageStatus,
    Resident,
    WithdrawalSession,
    WithdrawalStatus,
)

SAO_PAULO = ZoneInfo("America/Sao_Paulo")

JARDIM_ID = UUID("11111111-1111-4111-8111-111111111111")
ATLANTICO_ID = UUID("22222222-2222-4222-8222-222222222222")
DOORMAN_USER_ID = UUID("33333333-3333-4333-8333-333333333333")

# The day the demo data is centred on. Pass it explicitly (e.g. `date=2026-10-21`)
# to stats tools in demos and tests so results do not depend on the wall clock.
DEMO_DAY = "2026-10-21"


def local(ts: str) -> datetime:
    """'2026-10-21 08:15' in São Paulo time -> aware datetime (UTC offset kept)."""
    return datetime.fromisoformat(ts).replace(tzinfo=SAO_PAULO)


def make_cpf(base9: str) -> str:
    """Append the two CPF check digits (same algorithm as the app's validateCPF)."""
    nums = [int(c) for c in base9]
    for weight_start in (10, 11):
        total = sum(n * w for n, w in zip(nums, range(weight_start, 1, -1), strict=False))
        check = 11 - total % 11
        nums.append(0 if check >= 10 else check)
    return "".join(map(str, nums))


@dataclass
class Dataset:
    condominiums: list[Condominium] = field(default_factory=list)
    apartments: list[Apartment] = field(default_factory=list)
    residents: list[Resident] = field(default_factory=list)
    packages: list[Package] = field(default_factory=list)
    withdrawal_sessions: list[WithdrawalSession] = field(default_factory=list)
    invite_tokens: list[InviteToken] = field(default_factory=list)


def build_dataset() -> Dataset:
    created = local("2026-09-01 09:00")
    ds = Dataset()

    ds.condominiums = [
        Condominium(
            id=JARDIM_ID,
            name="Residencial Jardim das Flores",
            address="Rua das Acácias, 120 - São Paulo/SP",
            created_at=created,
        ),
        Condominium(
            id=ATLANTICO_ID,
            name="Edifício Atlântico",
            address="Av. Beira Mar, 900 - Santos/SP",
            created_at=created,
        ),
    ]

    apartments = [
        # id, condo, bloco, numero
        (1, JARDIM_ID, "A", "101"),
        (2, JARDIM_ID, "A", "102"),
        (3, JARDIM_ID, "A", "201"),
        (4, JARDIM_ID, "A", "202"),
        (5, JARDIM_ID, "B", "101"),
        (6, JARDIM_ID, "B", "102"),
        (7, JARDIM_ID, "B", "201"),  # vacant: no residents
        (8, ATLANTICO_ID, "Único", "11"),
        (9, ATLANTICO_ID, "Único", "12"),
    ]
    ds.apartments = [
        Apartment(id=i, condominium_id=c, block=b, number=n, created_at=created) for i, c, b, n in apartments
    ]

    residents = [
        # id, condo, apt, nome, contato, cpf base, has signature
        (1, JARDIM_ID, 1, "Ana Beatriz Souza", "(11) 98765-4321", "123456789", True),
        (2, JARDIM_ID, 1, "Carlos Souza", "(11) 97654-3210", "234567891", False),
        (3, JARDIM_ID, 2, "Mariana Lima", "(11) 96543-2109", "345678912", True),
        (4, JARDIM_ID, 3, "João Pedro Alves", "(11) 95432-1098", None, False),
        (5, JARDIM_ID, 4, "Fernanda Rocha", "fernanda.rocha@example.com", "456789123", False),
        (6, JARDIM_ID, 5, "Roberto Nunes", "(11) 94321-0987", "567891234", True),
        (7, JARDIM_ID, 5, "Helena Nunes", None, None, False),
        (8, JARDIM_ID, 6, "Lucas Martins", "(11) 93210-9876", "678912345", False),
        (9, ATLANTICO_ID, 8, "Paula Ferreira", "(13) 99876-5432", "789123456", False),
        (10, ATLANTICO_ID, 9, "Ricardo Gomes", "(13) 98765-1234", "891234567", True),
    ]
    ds.residents = [
        Resident(
            id=i,
            condominium_id=c,
            apartment_id=apt,
            name=nome,
            phone=contato,
            cpf=make_cpf(cpf) if cpf else None,
            has_signature=sig,
            created_at=created,
        )
        for i, c, apt, nome, contato, cpf, sig in residents
    ]

    packages = [
        # id, morador, codigo_rastreio, descricao, chegada, retirada, porteiro
        (1, 1, "BR123456789BR", "Caixa média Amazon", "2026-10-15 10:12", "2026-10-15 19:40", "Seu Zé"),
        (2, 3, "LB998877665BR", "Envelope Correios", "2026-10-16 14:03", None, "Seu Zé"),
        (3, 6, None, "Sacola farmácia", "2026-10-18 09:30", "2026-10-18 12:05", "Dona Rita"),
        (4, 4, "ML445566778", "Mercado Livre - pacote pequeno", "2026-10-19 11:45", None, "Dona Rita"),
        (5, 1, "AM000111222", "Amazon - 2 volumes", "2026-10-20 08:20", "2026-10-21 18:10", "Seu Zé"),
        (6, 2, "SH555444333", "Shopee", "2026-10-20 15:55", None, "Seu Zé"),
        (7, 5, None, "Flores (entrega local)", "2026-10-21 07:50", "2026-10-21 08:30", "Dona Rita"),
        (8, 8, "BR222333444BR", "Caixa grande", "2026-10-21 09:10", None, "Dona Rita"),
        (9, 3, "ML112233445", "Mercado Livre", "2026-10-21 10:25", "2026-10-21 19:02", "Dona Rita"),
        (10, 6, "AM333222111", "Amazon", "2026-10-21 11:40", "2026-10-21 19:15", "Dona Rita"),
        (11, 7, "SH777888999", "Shopee - roupa", "2026-10-21 11:42", "2026-10-21 19:15", "Dona Rita"),
        (12, 1, None, "Documento do cartório", "2026-10-21 13:05", None, "Seu Zé"),
        (13, 4, "LG123123123", "Loggi", "2026-10-21 14:30", None, "Seu Zé"),
        (14, 8, "BR555666777BR", "Envelope", "2026-10-21 16:45", None, "Seu Zé"),
        (15, 2, "AM999888777", "Amazon - livro", "2026-10-22 08:05", None, "Dona Rita"),
        (16, 5, "ML667788990", "Mercado Livre - eletrônico", "2026-10-22 09:15", None, "Dona Rita"),
        # Edifício Atlântico (must never leak into Jardim queries)
        (17, 9, "BR777000111BR", "Caixa Atlântico", "2026-10-20 10:00", None, "Porteiro Atlântico"),
        (
            18,
            10,
            "AM444555666",
            "Amazon Atlântico",
            "2026-10-21 12:00",
            "2026-10-21 18:00",
            "Porteiro Atlântico",
        ),
        (19, 9, None, "Sacola Atlântico", "2026-10-21 15:00", None, "Porteiro Atlântico"),
    ]
    ds.packages = [
        Package(
            id=i,
            resident_id=m,
            tracking_code=code,
            description=desc,
            status=PackageStatus.WITHDRAWN if out else PackageStatus.PENDING,
            arrived_at=local(arrived),
            withdrawn_at=local(out) if out else None,
            received_by=doorman,
            created_at=local(arrived),
        )
        for i, m, code, desc, arrived, out, doorman in packages
    ]

    def session(
        sid: str,
        apt: int,
        pkgs: list[int],
        status: WithdrawalStatus,
        created_at: str,
        method: ConfirmationMethod | None = None,
        reason: ManualReason | None = None,
        note: str | None = None,
        confirmed_by: str | None = None,
    ) -> WithdrawalSession:
        start = local(created_at)
        return WithdrawalSession(
            id=UUID(sid),
            apartment_id=apt,
            package_ids=pkgs,
            status=status,
            confirmation_method=method,
            manual_reason=reason,
            doorman_note=note,
            created_by="Dona Rita",
            confirmed_by=confirmed_by,
            created_at=start,
            expires_at=start.replace(minute=start.minute + 5),
            confirmed_at=start.replace(minute=start.minute + 1) if status == "confirmed" else None,
        )

    ds.withdrawal_sessions = [
        session(
            "aaaaaaaa-0000-4000-8000-000000000001",
            5,
            [10, 11],
            WithdrawalStatus.CONFIRMED,
            "2026-10-21 19:14",
            ConfirmationMethod.QR_SCAN,
            confirmed_by="resident",
        ),
        session(
            "aaaaaaaa-0000-4000-8000-000000000002",
            2,
            [9],
            WithdrawalStatus.CONFIRMED,
            "2026-10-21 19:01",
            ConfirmationMethod.MANUAL,
            ManualReason.ELDERLY,
            note="Moradora sem celular no momento",
            confirmed_by="Dona Rita",
        ),
        session(
            "aaaaaaaa-0000-4000-8000-000000000003",
            3,
            [4],
            WithdrawalStatus.EXPIRED,
            "2026-10-21 17:30",
        ),
        session(
            "aaaaaaaa-0000-4000-8000-000000000004",
            6,
            [8],
            WithdrawalStatus.CANCELLED,
            "2026-10-21 18:20",
        ),
    ]

    ds.invite_tokens = [
        InviteToken(
            id=UUID("bbbbbbbb-0000-4000-8000-000000000001"),
            condominium_id=JARDIM_ID,
            token="f" * 64,
            created_by=DOORMAN_USER_ID,
            expires_at=local("2026-12-31 23:59"),
            max_uses=10,
            use_count=3,
            created_at=created,
        )
    ]
    return ds
