"""One behavioural contract, two backends (in-memory and Postgres).

If these pass for both, tools behave the same whichever backend is configured.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from lobbyeasy_mcp.data.base import NewPackage, PackageQuery
from lobbyeasy_mcp.fixtures import ATLANTICO_ID, JARDIM_ID, SAO_PAULO
from lobbyeasy_mcp.models import PackageStatus


def ids(records):
    return [r.package.id for r in records]


async def test_tenant_isolation(repo):
    jardim = ids(await repo.search_packages(JARDIM_ID, PackageQuery(limit=100)))
    atlantico = ids(await repo.search_packages(ATLANTICO_ID, PackageQuery(limit=100)))
    assert set(jardim).isdisjoint(atlantico)
    assert sorted(atlantico) == [17, 18, 19]
    # Direct lookups across tenants return nothing rather than the other tenant's row.
    assert await repo.get_package(JARDIM_ID, 17) is None
    assert await repo.get_resident(JARDIM_ID, 9) is None
    assert await repo.get_apartment(JARDIM_ID, 8) is None
    assert await repo.list_withdrawal_sessions(ATLANTICO_ID) == []


async def test_search_order_and_filters(repo):
    pending = await repo.search_packages(JARDIM_ID, PackageQuery(status=PackageStatus.PENDING, limit=100))
    assert ids(pending) == [16, 15, 14, 13, 12, 8, 6, 4, 2]  # newest first
    by_apt = await repo.search_packages(JARDIM_ID, PackageQuery(apartment_id=1, limit=100))
    assert ids(by_apt) == [15, 12, 6, 5, 1]
    by_name = await repo.search_packages(JARDIM_ID, PackageQuery(resident_name="NUNES", limit=100))
    assert ids(by_name) == [11, 10, 3]
    by_code = await repo.search_packages(JARDIM_ID, PackageQuery(tracking_code="br", limit=100))
    assert ids(by_code) == [14, 8, 2, 1]
    day = datetime(2026, 10, 21, tzinfo=SAO_PAULO)
    in_day = await repo.search_packages(
        JARDIM_ID, PackageQuery(arrived_from=day, arrived_before=day + timedelta(days=1), limit=100)
    )
    assert ids(in_day) == [14, 13, 12, 11, 10, 9, 8, 7]


async def test_like_wildcards_are_literal(repo):
    assert await repo.search_packages(JARDIM_ID, PackageQuery(tracking_code="%", limit=100)) == []
    assert await repo.search_residents(JARDIM_ID, name="_") == []


async def test_keyset_pagination_walks_everything_once(repo):
    seen, after = [], None
    while True:
        page = await repo.search_packages(JARDIM_ID, PackageQuery(after=after, limit=4))
        if not page:
            break
        seen += ids(page)
        last = page[-1].package
        after = (last.arrived_at, last.id)
    assert seen == ids(await repo.search_packages(JARDIM_ID, PackageQuery(limit=100)))
    assert len(seen) == 16


async def test_joined_record_and_residents(repo):
    rec = await repo.get_package(JARDIM_ID, 10)
    assert rec.resident.name == "Roberto Nunes"
    assert rec.apartment.label == "B-101"
    residents = await repo.search_residents(JARDIM_ID, apartment_id=5)
    assert [r.name for r in residents] == ["Helena Nunes", "Roberto Nunes"]
    assert residents[1].has_signature is True
    apt = await repo.find_apartment(JARDIM_ID, "b", "101")
    assert apt.id == 5
    assert [a.label for a in await repo.list_apartments(JARDIM_ID)][:2] == ["A-101", "A-102"]


async def test_counts_and_sessions(repo):
    assert await repo.count_packages(JARDIM_ID, status=PackageStatus.PENDING) == 9
    assert await repo.count_packages(JARDIM_ID, apartment_id=1) == 5
    sessions = await repo.list_withdrawal_sessions(JARDIM_ID)
    assert [s.status.value for s in sessions] == ["confirmed", "confirmed", "cancelled", "expired"]


async def test_daily_counts(repo):
    start = datetime(2026, 10, 21, tzinfo=SAO_PAULO)
    c = await repo.daily_counts(JARDIM_ID, start, start + timedelta(days=1), "America/Sao_Paulo")
    assert (c.arrivals, c.withdrawals, c.pending_at_end) == (8, 5, 7)
    assert c.avg_hours_to_withdrawal == 11.65
    assert c.arrivals_by_hour == {7: 1, 9: 1, 10: 1, 11: 2, 13: 1, 14: 1, 16: 1}
    assert c.sessions_by_outcome == {
        "cancelled": 1,
        "confirmed_manual": 1,
        "confirmed_qr_scan": 1,
        "expired": 1,
    }
    assert c.oldest_pending.package.id == 2


async def test_writes_are_scoped_and_compare_and_set(repo):
    pkg = await repo.insert_package(JARDIM_ID, NewPackage(3, "XX1", "Teste", "Bot"))
    assert pkg.status == PackageStatus.PENDING
    assert (await repo.get_package(JARDIM_ID, pkg.id)).resident.id == 3

    at = datetime(2026, 10, 22, 13, 0, tzinfo=SAO_PAULO)
    done = await repo.mark_withdrawn(JARDIM_ID, pkg.id, at)
    assert done.status == PackageStatus.WITHDRAWN and done.withdrawn_at == at
    assert await repo.mark_withdrawn(JARDIM_ID, pkg.id, at) is None  # already withdrawn
    assert await repo.mark_withdrawn(JARDIM_ID, 17, at) is None  # other tenant

    try:
        await repo.insert_package(JARDIM_ID, NewPackage(9, None, None, None))  # Atlântico resident
    except LookupError:
        pass
    else:
        raise AssertionError("cross-tenant insert must fail")
