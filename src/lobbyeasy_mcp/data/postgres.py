"""Postgres backend (psycopg 3, async, connection pool).

Works against local Postgres (`sql/schema.sql` + `sql/seed.sql`) and against the
real Supabase database: use the "Session pooler" or direct connection string from
Supabase > Project Settings > Database. Prepared statements are disabled
(`prepare_threshold=None`) so the "Transaction pooler" (PgBouncer, port 6543)
works too.

Security notes:
* Every query has `m.condominio_id = %(cid)s` (or the apartment equivalent). The
  app filters tenants in JavaScript *after* fetching; doing it in SQL is both
  safer and makes pagination counts correct.
* SQL text is only ever assembled from constant fragments in this file. User
  input travels exclusively as bound parameters, never via string formatting.
* Point `LOBBY_DATABASE_URL` at a role with the least privilege you can: SELECT on
  the app tables, plus INSERT/UPDATE on `encomendas` only if writes are enabled.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from lobbyeasy_mcp.data.base import DailyCounts, NewPackage, PackageQuery, PackageRecord
from lobbyeasy_mcp.models import (
    Apartment,
    Condominium,
    Package,
    PackageStatus,
    Resident,
    WithdrawalSession,
)

_PACKAGE_COLUMNS = """
    e.id, e.codigo_rastreio, e.descricao, e.status, e.data_chegada, e.data_retirada,
    e.received_by, e.morador_id, e.created_at
"""

_PACKAGE_SELECT = f"""
SELECT {_PACKAGE_COLUMNS},
       m.id AS m_id, m.condominio_id AS m_condominio_id, m.nome AS m_nome, m.contato AS m_contato,
       m.cpf AS m_cpf, m.apartamento_id AS m_apartamento_id,
       (m.signature_url IS NOT NULL) AS m_has_signature, m.created_at AS m_created_at,
       a.id AS a_id, a.condominio_id AS a_condominio_id, a.numero AS a_numero, a.bloco AS a_bloco,
       a.created_at AS a_created_at
FROM encomendas e
JOIN moradores m ON m.id = e.morador_id
LEFT JOIN apartamentos a ON a.id = m.apartamento_id
WHERE m.condominio_id = %(cid)s
"""

_RESIDENT_SELECT = """
SELECT id, condominio_id, nome, contato, cpf, apartamento_id,
       (signature_url IS NOT NULL) AS has_signature, created_at
FROM moradores
WHERE condominio_id = %(cid)s
"""

# A package counts as "still in the lobby at time T" if it arrived before T and had
# not been withdrawn by T. 'entregue' rows have no data_retirada in practice, so they
# are excluded explicitly.
_PENDING_AT = "e.data_chegada < %(end)s AND e.status <> 'entregue' AND (e.data_retirada IS NULL OR e.data_retirada >= %(end)s)"


def _like(term: str) -> str:
    """Substring pattern for ILIKE with the user's own % and _ escaped."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _package(row: dict[str, Any]) -> Package:
    return Package(
        id=row["id"],
        tracking_code=row["codigo_rastreio"],
        description=row["descricao"],
        status=PackageStatus(row["status"]),
        arrived_at=row["data_chegada"],
        withdrawn_at=row["data_retirada"],
        received_by=row["received_by"],
        resident_id=row["morador_id"],
        created_at=row["created_at"],
    )


def _resident(row: dict[str, Any], prefix: str = "") -> Resident:
    p = prefix
    return Resident(
        id=row[f"{p}id"],
        condominium_id=row[f"{p}condominio_id"],
        name=row[f"{p}nome"],
        phone=row[f"{p}contato"],
        cpf=row[f"{p}cpf"],
        apartment_id=row[f"{p}apartamento_id"],
        has_signature=row[f"{p}has_signature"],
        created_at=row[f"{p}created_at"],
    )


def _apartment(row: dict[str, Any], prefix: str = "") -> Apartment:
    p = prefix
    return Apartment(
        id=row[f"{p}id"],
        condominium_id=row[f"{p}condominio_id"],
        number=row[f"{p}numero"],
        block=row[f"{p}bloco"],
        created_at=row[f"{p}created_at"],
    )


def _record(row: dict[str, Any]) -> PackageRecord:
    return PackageRecord(
        package=_package(row),
        resident=_resident(row, "m_"),
        apartment=_apartment(row, "a_") if row["a_id"] is not None else None,
    )


def _session(row: dict[str, Any]) -> WithdrawalSession:
    return WithdrawalSession(
        id=row["id"],
        apartment_id=row["apartamento_id"],
        package_ids=row["encomenda_ids"],
        status=row["status"],
        confirmation_method=row["confirmation_method"],
        manual_reason=row["manual_reason"],
        doorman_note=row["doorman_note"],
        created_by=row["created_by"],
        confirmed_by=row["confirmed_by"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        confirmed_at=row["confirmed_at"],
    )


class PostgresRepository:
    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 5) -> None:
        self.pool = AsyncConnectionPool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            open=False,
            kwargs={"row_factory": dict_row, "prepare_threshold": None, "autocommit": True},
        )

    async def open(self) -> None:
        await self.pool.open(wait=True, timeout=10)

    async def close(self) -> None:
        await self.pool.close()

    async def _all(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(query, params)  # type: ignore[arg-type]  # constant SQL
            return await cur.fetchall()

    async def _one(self, query: str, params: dict[str, Any]) -> dict[str, Any] | None:
        rows = await self._all(query, params)
        return rows[0] if rows else None

    # -- condominium / apartments ---------------------------------------------------
    async def get_condominium(self, condominium_id: UUID) -> Condominium | None:
        row = await self._one(
            "SELECT id, name, address, created_at FROM condominios WHERE id = %(cid)s",
            {"cid": condominium_id},
        )
        return Condominium(**row) if row else None

    async def list_apartments(self, condominium_id: UUID) -> list[Apartment]:
        rows = await self._all(
            "SELECT * FROM apartamentos WHERE condominio_id = %(cid)s ORDER BY bloco, numero",
            {"cid": condominium_id},
        )
        return [_apartment(r) for r in rows]

    async def get_apartment(self, condominium_id: UUID, apartment_id: int) -> Apartment | None:
        row = await self._one(
            "SELECT * FROM apartamentos WHERE condominio_id = %(cid)s AND id = %(id)s",
            {"cid": condominium_id, "id": apartment_id},
        )
        return _apartment(row) if row else None

    async def find_apartment(self, condominium_id: UUID, block: str, number: str) -> Apartment | None:
        row = await self._one(
            "SELECT * FROM apartamentos WHERE condominio_id = %(cid)s"
            " AND lower(bloco) = lower(%(block)s) AND numero = %(number)s",
            {"cid": condominium_id, "block": block.strip(), "number": number.strip()},
        )
        return _apartment(row) if row else None

    # -- residents ----------------------------------------------------------------------
    async def search_residents(
        self,
        condominium_id: UUID,
        *,
        name: str | None = None,
        apartment_id: int | None = None,
        limit: int = 20,
    ) -> list[Resident]:
        query = _RESIDENT_SELECT
        params: dict[str, Any] = {"cid": condominium_id, "limit": limit}
        if name:
            query += " AND nome ILIKE %(name)s"
            params["name"] = _like(name)
        if apartment_id is not None:
            query += " AND apartamento_id = %(apt)s"
            params["apt"] = apartment_id
        query += " ORDER BY nome, id LIMIT %(limit)s"
        return [_resident(r) for r in await self._all(query, params)]

    async def get_resident(self, condominium_id: UUID, resident_id: int) -> Resident | None:
        row = await self._one(
            _RESIDENT_SELECT + " AND id = %(id)s", {"cid": condominium_id, "id": resident_id}
        )
        return _resident(row) if row else None

    # -- packages -------------------------------------------------------------------------
    async def get_package(self, condominium_id: UUID, package_id: int) -> PackageRecord | None:
        row = await self._one(
            _PACKAGE_SELECT + " AND e.id = %(id)s", {"cid": condominium_id, "id": package_id}
        )
        return _record(row) if row else None

    async def search_packages(self, condominium_id: UUID, query: PackageQuery) -> list[PackageRecord]:
        sql = _PACKAGE_SELECT
        params: dict[str, Any] = {"cid": condominium_id, "limit": query.limit}
        if query.status:
            sql += " AND e.status = %(status)s"
            params["status"] = query.status.value
        if query.apartment_id is not None:
            sql += " AND m.apartamento_id = %(apt)s"
            params["apt"] = query.apartment_id
        if query.resident_id is not None:
            sql += " AND e.morador_id = %(rid)s"
            params["rid"] = query.resident_id
        if query.resident_name:
            sql += " AND m.nome ILIKE %(name)s"
            params["name"] = _like(query.resident_name)
        if query.tracking_code:
            sql += " AND e.codigo_rastreio ILIKE %(code)s"
            params["code"] = _like(query.tracking_code)
        if query.arrived_from:
            sql += " AND e.data_chegada >= %(from)s"
            params["from"] = query.arrived_from
        if query.arrived_before:
            sql += " AND e.data_chegada < %(before)s"
            params["before"] = query.arrived_before
        if query.after:
            # Keyset pagination: a row-value comparison walks the (data_chegada, id) index.
            sql += " AND (e.data_chegada, e.id) < (%(after_ts)s, %(after_id)s)"
            params["after_ts"], params["after_id"] = query.after
        sql += " ORDER BY e.data_chegada DESC, e.id DESC LIMIT %(limit)s"
        return [_record(r) for r in await self._all(sql, params)]

    async def count_packages(
        self, condominium_id: UUID, *, status: PackageStatus | None = None, apartment_id: int | None = None
    ) -> int:
        sql = "SELECT count(*) AS n FROM encomendas e JOIN moradores m ON m.id = e.morador_id WHERE m.condominio_id = %(cid)s"
        params: dict[str, Any] = {"cid": condominium_id}
        if status:
            sql += " AND e.status = %(status)s"
            params["status"] = status.value
        if apartment_id is not None:
            sql += " AND m.apartamento_id = %(apt)s"
            params["apt"] = apartment_id
        row = await self._one(sql, params)
        return int(row["n"]) if row else 0

    # -- withdrawal sessions ------------------------------------------------------------------
    async def list_withdrawal_sessions(
        self, condominium_id: UUID, *, apartment_id: int | None = None, limit: int = 10
    ) -> list[WithdrawalSession]:
        sql = (
            "SELECT ws.* FROM withdrawal_sessions ws JOIN apartamentos a ON a.id = ws.apartamento_id"
            " WHERE a.condominio_id = %(cid)s"
        )
        params: dict[str, Any] = {"cid": condominium_id, "limit": limit}
        if apartment_id is not None:
            sql += " AND ws.apartamento_id = %(apt)s"
            params["apt"] = apartment_id
        sql += " ORDER BY ws.created_at DESC LIMIT %(limit)s"
        return [_session(r) for r in await self._all(sql, params)]

    # -- stats ---------------------------------------------------------------------------------
    async def daily_counts(
        self, condominium_id: UUID, start: datetime, end: datetime, tz: str
    ) -> DailyCounts:
        p = {"cid": condominium_id, "start": start, "end": end, "tz": tz}
        base = "FROM encomendas e JOIN moradores m ON m.id = e.morador_id WHERE m.condominio_id = %(cid)s"
        totals = await self._one(
            f"""
            SELECT
              count(*) FILTER (WHERE e.data_chegada >= %(start)s AND e.data_chegada < %(end)s) AS arrivals,
              count(*) FILTER (WHERE e.data_retirada >= %(start)s AND e.data_retirada < %(end)s) AS withdrawals,
              count(*) FILTER (WHERE {_PENDING_AT}) AS pending_at_end,
              avg(extract(epoch FROM e.data_retirada - e.data_chegada) / 3600)
                FILTER (WHERE e.data_retirada >= %(start)s AND e.data_retirada < %(end)s) AS avg_hours
            {base}
            """,
            p,
        )
        by_hour = await self._all(
            f"""
            SELECT extract(hour FROM e.data_chegada AT TIME ZONE %(tz)s)::int AS hour, count(*) AS n
            {base} AND e.data_chegada >= %(start)s AND e.data_chegada < %(end)s
            GROUP BY 1 ORDER BY 1
            """,
            p,
        )
        sessions = await self._all(
            """
            SELECT CASE WHEN ws.status = 'confirmed' AND ws.confirmation_method IS NOT NULL
                        THEN 'confirmed_' || ws.confirmation_method ELSE ws.status END AS outcome,
                   count(*) AS n
            FROM withdrawal_sessions ws JOIN apartamentos a ON a.id = ws.apartamento_id
            WHERE a.condominio_id = %(cid)s AND ws.created_at >= %(start)s AND ws.created_at < %(end)s
            GROUP BY 1 ORDER BY 1
            """,
            p,
        )
        oldest = await self._one(
            _PACKAGE_SELECT + f" AND {_PENDING_AT} ORDER BY e.data_chegada, e.id LIMIT 1",
            p,
        )
        assert totals is not None
        avg = totals["avg_hours"]
        return DailyCounts(
            arrivals=totals["arrivals"],
            withdrawals=totals["withdrawals"],
            pending_at_end=totals["pending_at_end"],
            avg_hours_to_withdrawal=round(float(avg), 2) if avg is not None else None,
            arrivals_by_hour={r["hour"]: r["n"] for r in by_hour},
            sessions_by_outcome={r["outcome"]: r["n"] for r in sessions},
            oldest_pending=_record(oldest) if oldest else None,
        )

    # -- writes ----------------------------------------------------------------------------------
    async def insert_package(self, condominium_id: UUID, new: NewPackage) -> Package:
        # INSERT ... SELECT FROM moradores enforces the tenant check inside the statement:
        # a resident from another condominium yields zero rows instead of a cross-tenant insert.
        row = await self._one(
            """
            INSERT INTO encomendas (morador_id, codigo_rastreio, descricao, received_by, status)
            SELECT m.id, %(code)s, %(desc)s, %(by)s, 'pendente'
            FROM moradores m WHERE m.id = %(rid)s AND m.condominio_id = %(cid)s
            RETURNING id, codigo_rastreio, descricao, status, data_chegada, data_retirada,
                      received_by, morador_id, created_at
            """,
            {
                "cid": condominium_id,
                "rid": new.resident_id,
                "code": new.tracking_code,
                "desc": new.description,
                "by": new.received_by,
            },
        )
        if row is None:
            raise LookupError(f"resident {new.resident_id} not in condominium")
        return _package(row)

    async def mark_withdrawn(self, condominium_id: UUID, package_id: int, at: datetime) -> Package | None:
        # The `status = 'pendente'` guard makes this a compare-and-set: two doormen
        # confirming at once cannot both "win".
        row = await self._one(
            f"""
            UPDATE encomendas e SET status = 'retirada', data_retirada = %(at)s
            FROM moradores m
            WHERE e.id = %(id)s AND m.id = e.morador_id AND m.condominio_id = %(cid)s
              AND e.status = 'pendente'
            RETURNING {_PACKAGE_COLUMNS}
            """,
            {"cid": condominium_id, "id": package_id, "at": at},
        )
        return _package(row) if row else None
