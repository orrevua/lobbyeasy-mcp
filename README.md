# lobbyeasy-mcp

A [Model Context Protocol](https://modelcontextprotocol.io) server for **LobbyEasy**, a building
lobby / package management app (Next.js + Supabase). It lets an AI assistant answer questions like
"which packages are still waiting in the lobby?".

> Milestone 4: role-gated, two-step write tools; rate limiting, audit log and idempotency keys.

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

## Remote server (streamable HTTP)

```bash
uv run lobbyeasy-mcp keys create --condominium 11111111-1111-4111-8111-111111111111 \
    --role viewer --file api_keys.json          # prints the key once, stores its SHA-256
LOBBY_API_KEYS_FILE=api_keys.json uv run lobbyeasy-mcp http --port 8000
claude mcp add --transport http lobbyeasy http://127.0.0.1:8000/mcp --header "Authorization: Bearer lbe_..."
```

Each key is bound to one condominium and one role (`viewer`, `porteiro`, `admin`); tools never take a
condominium id from the model. Deploy notes for Fly.io / Render: [docs/deploy.md](docs/deploy.md).

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

### Write tools (off by default)

`LOBBY_ENABLE_WRITES=true` registers `register_package`, `mark_package_withdrawn`, `notify_resident`
(stubbed notifier), `confirm_action` and `cancel_action`. They are hidden from and refused for roles
without the `write` permission. Proposing tools return a summary plus a single-use `confirmation_token`;
only `confirm_action` writes. Every tool call is rate limited per key (token bucket) and recorded in an
audit log (`mcp_audit_log` on Postgres) with arguments redacted by allowlist. Writes accept an
`idempotency_key` so a retry never registers the same package twice.

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
