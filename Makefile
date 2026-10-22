DB_URL ?= postgresql://postgres:postgres@localhost:5432/p4_lobby
ADMIN_URL ?= postgresql://postgres:postgres@localhost:5432/postgres

.PHONY: setup test lint fmt demo db seed
setup:
	uv sync
test:
	uv run pytest
lint:
	uv run ruff check . && uv run ruff format --check .
fmt:
	uv run ruff format . && uv run ruff check --fix .
demo:
	uv run python scripts/demo.py
db:  ## create p4_lobby and load schema + MCP objects + seed
	psql "$(ADMIN_URL)" -tc "SELECT 1 FROM pg_database WHERE datname = 'p4_lobby'" | grep -q 1 || psql "$(ADMIN_URL)" -c "CREATE DATABASE p4_lobby"
	psql "$(DB_URL)" -v ON_ERROR_STOP=1 -q -f sql/schema.sql -f sql/mcp.sql -f sql/seed.sql
seed:  ## regenerate sql/seed.sql from src/lobbyeasy_mcp/fixtures.py
	uv run python -m lobbyeasy_mcp.data.seed > sql/seed.sql
