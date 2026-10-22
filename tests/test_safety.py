"""Milestone 4: write tools behind roles, two-step confirmation, idempotency,
rate limiting and the audit log - exercised through the MCP protocol."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from mcp import Client

from lobbyeasy_mcp.config import Settings
from lobbyeasy_mcp.data.memory import InMemoryRepository
from lobbyeasy_mcp.fixtures import JARDIM_ID
from lobbyeasy_mcp.notifier import StubNotifier
from lobbyeasy_mcp.principal import Principal, Role
from lobbyeasy_mcp.safety import Safety, make_safety
from lobbyeasy_mcp.safety.audit import InMemoryAuditSink, redact
from lobbyeasy_mcp.safety.confirmations import ConfirmationStore
from lobbyeasy_mcp.safety.idempotency import InMemoryIdempotencyStore
from lobbyeasy_mcp.safety.ratelimit import RateLimiter
from lobbyeasy_mcp.server import build_server
from lobbyeasy_mcp.tools.write import WRITE_TOOL_NAMES

from .conftest import PG_AVAILABLE, PG_URL, fixed_clock, reset_postgres

# -- units ----------------------------------------------------------------------------


def test_token_bucket_refills():
    now = [0.0]
    limiter = RateLimiter(capacity=2, refill_per_second=1, clock=lambda: now[0])
    assert limiter.try_acquire("k")[0] and limiter.try_acquire("k")[0]
    allowed, wait = limiter.try_acquire("k")
    assert not allowed and wait == pytest.approx(1.0)
    assert limiter.try_acquire("other")[0]  # buckets are per key
    now[0] = 1.0
    assert limiter.try_acquire("k")[0]


def test_redaction_is_an_allowlist():
    out = redact(
        {
            "resident_id": 3,
            "message": "Oi Mariana, CPF 123.456.789-09",
            "received_by": "Seu Zé",
            "filters": {"status": "pendente", "resident_name": "souza"},
            "confirmation_token": "abcdefghijklmnop",
        }
    )
    assert out == {
        "resident_id": 3,
        "message": "[redacted:30]",
        "received_by": "[redacted:6]",
        "filters": {"status": "pendente", "resident_name": "[redacted:5]"},
        "confirmation_token": "abcdef...",
    }


def test_confirmations_expire_and_are_bound_to_the_key():
    now = [datetime(2026, 1, 1, tzinfo=UTC)]
    store = ConfirmationStore(ttl_seconds=60, clock=lambda: now[0])
    p = store.create(key_id="a", condominium_id="c", action="x", args={}, summary="s")
    assert store.take(p.token, "b") is None  # other key: indistinguishable from unknown
    now[0] += timedelta(seconds=61)
    assert store.take(p.token, "a") == "expired"
    assert store.take(p.token, "a") is None  # single use


# -- end to end -------------------------------------------------------------------------


class Harness:
    def __init__(self, role: Role, *, writes: bool = True, capacity: float = 100, repo=None, safety=None):
        self.audit = InMemoryAuditSink()
        self.notifier = StubNotifier()
        self.repo = repo or InMemoryRepository()
        self.safety = safety or Safety(RateLimiter(capacity, 0.001), self.audit, InMemoryIdempotencyStore())
        settings = Settings(_env_file=None, enable_writes=writes)  # type: ignore[call-arg]
        who = Principal(f"key-{role}", JARDIM_ID, role)
        self.server = build_server(
            settings,
            repo=self.repo,
            resolve_principal=lambda _: who,
            clock=fixed_clock,
            safety=self.safety,
            notifier=self.notifier,
        )

    def client(self) -> Client:
        return Client(self.server)


def payload(result):
    """Union return types (Proposal | ActionOutcome) arrive wrapped as {"result": ...}."""
    assert not result.is_error, result.content[0].text
    sc = result.structured_content
    return sc["result"] if set(sc) == {"result"} else sc


async def test_writes_disabled_by_default():
    async with Harness(Role.PORTEIRO, writes=False).client() as client:
        names = {t.name for t in (await client.list_tools()).tools}
        assert names.isdisjoint(WRITE_TOOL_NAMES)


async def test_viewer_cannot_see_or_call_write_tools():
    h = Harness(Role.VIEWER)
    async with h.client() as client:
        names = {t.name for t in (await client.list_tools()).tools}
        assert names.isdisjoint(WRITE_TOOL_NAMES)
        result = await client.call_tool("mark_package_withdrawn", {"package_id": 2})
        assert result.is_error and "write" in result.content[0].text
    assert h.audit.entries[-1].outcome == "denied"
    assert h.repo.data.packages[1].status == "pendente"


async def test_register_package_two_step_flow():
    h = Harness(Role.PORTEIRO)
    async with h.client() as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert set(tools) >= WRITE_TOOL_NAMES
        assert tools["confirm_action"].annotations.destructive_hint is True

        before = len(h.repo.data.packages)
        proposal = payload(
            await client.call_tool(
                "register_package",
                {"resident_id": 3, "received_by": "Seu Zé", "description": "Caixa Natura"},
            )
        )
        assert proposal["status"] == "confirmation_required"
        assert "Mariana Lima (A-102)" in proposal["summary"]
        assert len(h.repo.data.packages) == before  # nothing written yet

        done = payload(
            await client.call_tool("confirm_action", {"confirmation_token": proposal["confirmation_token"]})
        )
        assert done["status"] == "executed"
        assert done["result"]["status"] == "pendente" and done["result"]["resident"]["name"] == "Mariana Lima"
        assert len(h.repo.data.packages) == before + 1

        again = await client.call_tool(
            "confirm_action", {"confirmation_token": proposal["confirmation_token"]}
        )
        assert again.is_error and "already used" in again.content[0].text


async def test_withdraw_cancel_and_conflict():
    h = Harness(Role.PORTEIRO)
    async with h.client() as client:
        p1 = payload(await client.call_tool("mark_package_withdrawn", {"package_id": 2}))
        assert "Envelope Correios" in p1["summary"]
        cancelled = payload(
            await client.call_tool("cancel_action", {"confirmation_token": p1["confirmation_token"]})
        )
        assert cancelled == {"status": "cancelled", "action": "mark_package_withdrawn", "result": None}

        p2 = payload(await client.call_tool("mark_package_withdrawn", {"package_id": 2}))
        p3 = payload(await client.call_tool("mark_package_withdrawn", {"package_id": 2}))
        ok = payload(
            await client.call_tool("confirm_action", {"confirmation_token": p2["confirmation_token"]})
        )
        assert ok["result"]["status"] == "retirada"
        # The second proposal was valid when made, but re-validation at confirm time catches the race.
        late = await client.call_tool("confirm_action", {"confirmation_token": p3["confirmation_token"]})
        assert late.is_error and "not 'pendente'" in late.content[0].text
        withdrawn = await client.call_tool("mark_package_withdrawn", {"package_id": 1})
        assert withdrawn.is_error and "retirada" in withdrawn.content[0].text


async def test_notify_resident_uses_stub_and_validates_packages():
    h = Harness(Role.PORTEIRO)
    async with h.client() as client:
        bad = await client.call_tool(
            "notify_resident", {"resident_id": 3, "message": "Sua encomenda chegou", "package_ids": [1]}
        )
        assert bad.is_error and "does not belong" in bad.content[0].text
        no_phone = await client.call_tool("notify_resident", {"resident_id": 7, "message": "Olá Helena!"})
        assert no_phone.is_error and "no contact" in no_phone.content[0].text

        p = payload(
            await client.call_tool(
                "notify_resident",
                {"resident_id": 3, "message": "Sua encomenda chegou na portaria.", "package_ids": [2]},
            )
        )
        assert "(**) *****-2109" in p["summary"]
        assert h.notifier.outbox == []
        done = payload(
            await client.call_tool("confirm_action", {"confirmation_token": p["confirmation_token"]})
        )
        assert done["result"]["channel"] == "stub"
        assert [n.to for n in h.notifier.outbox] == ["(11) 96543-2109"]


async def test_idempotency_key_prevents_duplicates():
    h = Harness(Role.PORTEIRO)
    args = {
        "resident_id": 1,
        "received_by": "Dona Rita",
        "tracking_code": "QB123",
        "idempotency_key": "idem-0001",
    }
    async with h.client() as client:
        before = len(h.repo.data.packages)
        p1 = payload(await client.call_tool("register_package", args))
        p2 = payload(await client.call_tool("register_package", args))  # client retried before confirming
        first = payload(
            await client.call_tool("confirm_action", {"confirmation_token": p1["confirmation_token"]})
        )
        second = payload(
            await client.call_tool("confirm_action", {"confirmation_token": p2["confirmation_token"]})
        )
        assert first["status"] == "executed" and second["status"] == "already_executed"
        assert second["result"]["id"] == first["result"]["id"]
        assert len(h.repo.data.packages) == before + 1

        replay = payload(await client.call_tool("register_package", args))  # after completion: no new token
        assert replay["status"] == "already_executed"
        clash = await client.call_tool("register_package", {**args, "tracking_code": "OTHER"})
        assert clash.is_error and "different request" in clash.content[0].text


async def test_rate_limit_per_key_is_enforced_and_audited():
    h = Harness(Role.VIEWER, capacity=3)
    async with h.client() as client:
        results = [await client.call_tool("list_apartments", {}) for _ in range(4)]
    assert [r.is_error for r in results] == [False, False, False, True]
    assert "Rate limit" in results[-1].content[0].text
    assert [e.outcome for e in h.audit.entries] == ["ok", "ok", "ok", "rate_limited"]


async def test_every_call_is_audited_with_redacted_args():
    h = Harness(Role.PORTEIRO)
    async with h.client() as client:
        await client.call_tool("find_residents", {"name": "Mariana", "reveal_pii": True})
        await client.call_tool("get_package", {"package_id": 999})
        await client.call_tool("notify_resident", {"resident_id": 3, "message": "Segredo: 1234"})
    e1, e2, e3 = h.audit.entries
    assert (e1.tool, e1.outcome, e1.arguments) == (
        "find_residents",
        "ok",
        {"name": "[redacted:7]", "reveal_pii": True},
    )
    assert e2.outcome == "error" and "not found" in e2.error
    assert e3.arguments["message"] == "[redacted:13]" and e3.key_id == "key-porteiro"
    assert all(e.condominium_id == str(JARDIM_ID) for e in h.audit.entries)


@pytest.mark.postgres
async def test_postgres_audit_and_idempotency():
    if not PG_AVAILABLE:
        pytest.skip("Postgres not reachable")
    from lobbyeasy_mcp.data.postgres import PostgresRepository

    reset_postgres()
    repo = PostgresRepository(PG_URL)
    settings = Settings(_env_file=None, backend="postgres", database_url=PG_URL)  # type: ignore[call-arg]
    h = Harness(Role.PORTEIRO, repo=repo, safety=make_safety(settings, repo))
    args = {
        "resident_id": 4,
        "received_by": "Seu Zé",
        "description": "Pacote PG",
        "idempotency_key": "pg-idem-1",
    }
    async with h.client() as client:
        p1 = payload(await client.call_tool("register_package", args))
        p2 = payload(await client.call_tool("register_package", args))
        r1 = payload(
            await client.call_tool("confirm_action", {"confirmation_token": p1["confirmation_token"]})
        )
        r2 = payload(
            await client.call_tool("confirm_action", {"confirmation_token": p2["confirmation_token"]})
        )
        assert (r1["status"], r2["status"]) == ("executed", "already_executed")
        assert r1["result"]["id"] == r2["result"]["id"] == 20  # sequence continues after the seed
    with psycopg.connect(PG_URL) as conn:
        assert (
            conn.execute("SELECT count(*) FROM encomendas WHERE descricao = 'Pacote PG'").fetchone()[0] == 1
        )
        rows = conn.execute("SELECT tool, outcome, arguments FROM mcp_audit_log ORDER BY id").fetchall()
        assert [r[0] for r in rows] == [
            "register_package",
            "register_package",
            "confirm_action",
            "confirm_action",
        ]
        assert rows[0][2]["received_by"] == "[redacted:6]"
        status = conn.execute(
            "SELECT status FROM mcp_idempotency WHERE idempotency_key = 'pg-idem-1'"
        ).fetchone()
        assert status[0] == "completed"
