# lobbyeasy-mcp

A [Model Context Protocol](https://modelcontextprotocol.io) server for **LobbyEasy**, a building
lobby / package management app (Next.js + Supabase). It lets an AI assistant answer questions like
"which packages are still waiting in the lobby?".

> Milestone 2: data access layer (Postgres + in-memory), 7 read tools, resources and prompts.

## Run it

```bash
uv sync
uv run lobbyeasy-mcp          # speaks MCP over stdin/stdout
```

## Connect a client

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "lobbyeasy": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/lobbyeasy-mcp", "run", "lobbyeasy-mcp"]
    }
  }
}
```

### Claude Code

```bash
claude mcp add lobbyeasy -- uv --directory /absolute/path/to/lobbyeasy-mcp run lobbyeasy-mcp
```

### Cursor (`.cursor/mcp.json` or `~/.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "lobbyeasy": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/lobbyeasy-mcp", "run", "lobbyeasy-mcp"]
    }
  }
}
```

## Tools

| Tool | What it does |
|---|---|
| `list_pending_packages` | Packages still in the lobby (`pendente`), newest first, optional apartment filter |
| `get_package` | One package with resident and apartment |
| `search_packages` | Filters (status, apartment, resident name, tracking code, arrival dates) + cursor pagination |
| `find_residents` | Resident lookup by name/apartment; phone and CPF masked unless `reveal_pii` (role-gated) |
| `list_apartments` | Ids and `BLOCK-NUMBER` labels |
| `get_apartment_summary` | Residents, pending packages, totals, recent withdrawal sessions |
| `get_daily_stats` | Arrivals, pickups, end-of-day backlog, avg hours to pickup, per-hour arrivals |

Resources: `lobby://condominiums/{id}/summary` (JSON), `lobby://condominiums/{id}/pending` (markdown),
`lobby://reference/package-lifecycle`. Prompts: `daily_lobby_report`, `stale_package_followup`.

## Backends

| `LOBBY_BACKEND` | Data | Use |
|---|---|---|
| `memory` (default) | `src/lobbyeasy_mcp/fixtures.py` | tests, demos, `uvx` try-out |
| `postgres` | `LOBBY_DATABASE_URL` | local Postgres (`make db`) or Supabase's Postgres connection string |

## Schema provenance

`sql/schema.sql` was inferred from the app (read-only reference, not modified):

- `docs/schema.sql`: the authoritative incremental migration (sections 1-8); folded into CREATE TABLEs.
- `src/domain/entities/*.ts`: status unions (`pendente | retirada | entregue`, session statuses, manual reasons).
- `src/infrastructure/supabase/*-repository.ts`: column names, joins, which status each write sets.
- `src/application/use-cases/**`: business rules (5-minute session TTL, only pending packages can be withdrawn
  in a session, CPF validation, invite validity).
- `src/infrastructure/supabase/server.ts`, `src/lib/actions/auth.ts`: roles (`porteiro`, `morador`) in `app_metadata`.
