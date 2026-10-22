from datetime import datetime

import pytest

from lobbyeasy_mcp.data.seed import render_seed_sql
from lobbyeasy_mcp.errors import InvalidInputError
from lobbyeasy_mcp.fixtures import build_dataset, make_cpf
from lobbyeasy_mcp.pii import format_cpf, mask_cpf, mask_phone
from lobbyeasy_mcp.service import decode_cursor, encode_cursor

from .conftest import ROOT


def test_masking():
    assert mask_phone("(11) 98765-4321") == "(**) *****-4321"
    assert mask_phone("fernanda.rocha@example.com") == "f***@example.com"
    assert mask_phone(None) is None
    assert mask_cpf("12345678909") == "***.***.***-09"
    assert format_cpf("12345678909") == "123.456.789-09"


def test_fixture_cpfs_have_valid_check_digits():
    assert make_cpf("123456789") == "12345678909"  # well-known valid CPF
    for r in build_dataset().residents:
        if r.cpf:
            assert make_cpf(r.cpf[:9]) == r.cpf


def test_cursor_roundtrip_and_rejections():
    ts = datetime.fromisoformat("2026-10-21T10:00:00-03:00")
    cur = encode_cursor(ts, 9, "abc")
    assert decode_cursor(cur, "abc") == (ts, 9)
    with pytest.raises(InvalidInputError, match="different filters"):
        decode_cursor(cur, "other")
    with pytest.raises(InvalidInputError, match="malformed"):
        decode_cursor("not-a-cursor", "abc")


def test_seed_sql_is_up_to_date():
    committed = (ROOT / "sql" / "seed.sql").read_text()
    assert committed == render_seed_sql(), "run: uv run python -m lobbyeasy_mcp.data.seed > sql/seed.sql"
