# lobbyeasy-mcp

<!-- mcp-name: io.github.orrevua/lobbyeasy-mcp -->

A [Model Context Protocol](https://modelcontextprotocol.io) server for **LobbyEasy**, a building lobby
and package management app (Next.js + Supabase) used by doormen (*porteiros*) in Brazilian
condominiums. It lets Claude, Cursor or any MCP client answer *"which packages have been waiting the
longest?"*, summarise the day for the building manager, and (if you allow it) log a package or mark it
picked up, with a human confirmation step in between.

![demo](docs/demo.gif)
<!-- Placeholder: record with `vhs docs/demo.tape` (https://github.com/charmbracelet/vhs). -->

## The problem

The lobby already has the data: every package, who it is for, when it arrived and when it left. What
it lacks is a way to *ask* it things without clicking through filters, and a safe way to let an
assistant act on it. Exposing it over MCP means one integration works in every MCP client, but it also
means an LLM is now reading tenant data with personal information (phone, CPF) and could be talked
into writing. Most of this repo is about doing that safely: tenant scoping from credentials, PII masked
by default, writes that only *propose*, rate limits and an audit trail.

## Install in under 5 minutes

You need [uv](https://docs.astral.sh/uv/). No database is needed to try it: the default backend is a
built-in demo condominium.

```bash
# 1. Run it once (stdio server; Ctrl+C to stop). From PyPI once published:
uvx lobbyeasy-mcp --version
#    ...or straight from GitHub before that:
uvx --from git+https://github.com/orrevua/lobbyeasy-mcp lobbyeasy-mcp --version

# 2. Add it to Claude Code
claude mcp add lobbyeasy -- uvx lobbyeasy-mcp

# 3. Ask: "Quais encomendas estão esperando há mais tempo na portaria?"
```

Point it at your real LobbyEasy database (Supabase > Project Settings > Database > Connection string):

```bash
claude mcp add lobbyeasy \
  -e LOBBY_BACKEND=postgres \
  -e LOBBY_DATABASE_URL='postgresql://postgres.xxxx:PASSWORD@aws-0-sa-east-1.pooler.supabase.com:5432/postgres' \
  -e LOBBY_CONDOMINIUM_ID=<your condominios.id> \
  -- uvx lobbyeasy-mcp
psql "$LOBBY_DATABASE_URL" -f sql/mcp.sql   # once: audit/idempotency/API-key tables (additive)
```

### Other clients

Claude Desktop (`claude_desktop_config.json`) and Cursor (`.cursor/mcp.json`) use the same shape:

```json
{
  "mcpServers": {
    "lobbyeasy": {
      "command": "uvx",
      "args": ["lobbyeasy-mcp"],
      "env": { "LOBBY_ROLE": "viewer" }
    }
  }
}
```

From a clone instead of PyPI: `"command": "uv", "args": ["--directory", "/abs/path/lobbyeasy-mcp", "run", "lobbyeasy-mcp"]`.
Docker: `"command": "docker", "args": ["run", "-i", "--rm", "ghcr.io/orrevua/lobbyeasy-mcp", "lobbyeasy-mcp", "stdio"]`.

### Remote server (streamable HTTP + API keys)

```bash
uv run lobbyeasy-mcp keys create --condominium 11111111-1111-4111-8111-111111111111 \
    --role viewer --file api_keys.json        # prints the key ONCE, stores only its SHA-256
LOBBY_API_KEYS_FILE=api_keys.json uv run lobbyeasy-mcp http --port 8000
claude mcp add --transport http lobbyeasy http://127.0.0.1:8000/mcp --header "Authorization: Bearer lbe_..."
```

Cursor: `{"mcpServers": {"lobbyeasy": {"url": "https://.../mcp", "headers": {"Authorization": "Bearer lbe_..."}}}}`.
Deploying to Fly.io or Render (Dockerfile, `fly.toml`, `render.yaml`): [docs/deploy.md](docs/deploy.md).

## Quickstart for development (one command)

```bash
make setup && make test     # uv sync + 54 tests, offline; Postgres tests auto-skip if unreachable
make demo                   # drives the server through the MCP protocol and prints what a client sees
make db                     # optional: create local p4_lobby with schema + seed (Postgres at localhost)
```

## Architecture

```mermaid
flowchart LR
    C["Claude Desktop / Claude Code / Cursor"] -- "stdio (local, trusts env)" --> G
    C -- "streamable HTTP + Bearer lbe_..." --> V["ApiKeyVerifier<br/>(SDK TokenVerifier)"] --> G
    subgraph S["lobbyeasy-mcp (mcp.server.mcpserver.MCPServer)"]
        G["Gateway middleware<br/>identity, write gating,<br/>rate limit, audit"] --> T["7 read tools, 3 resources,<br/>2 prompts, 5 write tools"]
        T --> L["LobbyService<br/>tenant scope, PII masking,<br/>cursors, time zone"]
        T --> W["WriteService<br/>propose, confirm,<br/>idempotency"]
        W --> L
    end
    L --> R{{"LobbyRepository"}}
    R --> M[("in-memory fixtures")]
    R --> P[("Postgres / Supabase")]
    W --> N["Notifier (stub)"]
    G --> A[("mcp_audit_log")]
```

| Layer | File | Responsibility |
|---|---|---|
| Transport + auth | `http.py`, `auth.py`, `cli.py` | stdio / streamable HTTP, API keys -> `Principal` |
| Gateway | `middleware.py` | runs for every request: hide/refuse writes, rate limit, audit |
| MCP surface | `tools/read.py`, `tools/write.py`, `resources.py`, `prompts.py` | thin adapters, schemas in `views.py` |
| Business rules | `service.py`, `actions.py` | scoping, masking, pagination, two-step writes |
| Data | `data/base.py`, `data/postgres.py`, `data/memory.py` | one protocol, two backends, same contract tests |
| Safety | `safety/*.py`, `notifier.py` | token bucket, audit sinks, idempotency, confirmations |

## Tools, resources, prompts

| Tool | Kind | What it does |
|---|---|---|
| `list_pending_packages` | read | Packages still in the lobby (`pendente`), newest first; optional apartment |
| `get_package` | read | One package with resident and apartment |
| `search_packages` | read | Status, apartment, resident name, tracking code, arrival dates; keyset cursor pagination |
| `find_residents` | read | By name/apartment; phone and CPF **masked** unless `reveal_pii` and role has `pii` |
| `list_apartments` | read | Ids and `BLOCK-NUMBER` labels |
| `get_apartment_summary` | read | Residents, pending packages, totals, recent QR/manual withdrawal sessions |
| `get_daily_stats` | read | Arrivals, pickups, end-of-day backlog, avg hours to pickup, arrivals per hour, oldest waiting |
| `register_package` | write (propose) | Log an arrival; returns summary + `confirmation_token` |
| `mark_package_withdrawn` | write (propose) | Pending -> `retirada` |
| `notify_resident` | write (propose) | Message a resident through the (stub) notifier |
| `confirm_action` | write (commit) | Re-validates and executes a proposal; single-use, key-bound, expiring token |
| `cancel_action` | write | Discards a proposal |

Write tools exist only with `LOBBY_ENABLE_WRITES=true` and are hidden from / refused for roles
without `write`. Roles: `viewer` (read), `porteiro` (read, pii, write), `admin` (all).

Resources: `lobby://condominiums/{condominium_id}/summary` (JSON), `lobby://condominiums/{condominium_id}/pending`
(markdown), `lobby://reference/package-lifecycle`. Prompts: `daily_lobby_report(day, language)`,
`stale_package_followup(min_days)`; both prefetch data so the model reports real numbers.

## Results

Measured in this build environment (4 vCPU container, Python 3.12, local PostgreSQL 16, no LLM involved).
Latency is one `tools/call` through the full MCP stack (in-process client, argument validation,
gateway middleware incl. audit write, JSON serialisation), 50 calls after warm-up
(`uv run python scripts/bench.py`):

| tool | memory p50 / p95 (ms) | postgres (local) p50 / p95 (ms) |
|---|---|---|
| `list_pending_packages` | 2.49 / 2.97 | 5.12 / 5.58 |
| `search_packages` | 1.73 / 2.07 | 3.93 / 4.66 |
| `find_residents` | 0.76 / 0.95 | 3.54 / 4.91 |
| `get_apartment_summary` | 1.14 / 1.30 | 5.49 / 6.93 |
| `get_daily_stats` | 0.97 / 1.10 | 5.35 / 7.48 |

| Check | Result |
|---|---|
| Test suite (`uv run pytest`, offline) | 54 passed (contract tests on both backends, in-process MCP client, real stdio subprocess, uvicorn + streamable HTTP client in both protocol eras) |
| Postgres backend vs local Postgres 16 | same contract tests pass; writes, audit rows and idempotency rows verified in SQL |
| How well an LLM uses the tools | **not measured here** (no API key in the build environment). See `docs/writeup-draft.md` for the planned eval. |

## Schema provenance and assumptions

`sql/schema.sql` mirrors the app (read-only reference, never modified). Sources:

- `docs/schema.sql`: the authoritative incremental migration (sections 1-8), folded into CREATE TABLEs
  with identical names, types, defaults, FKs and indexes.
- `src/domain/entities/*.ts`: status unions and enums (`pendente | retirada | entregue`, session statuses,
  confirmation methods, manual reasons `sem_celular | idoso | portador_necessidades | outro`).
- `src/infrastructure/supabase/*-repository.ts`: column usage, joins, what each write sets.
- `src/application/use-cases/**`: rules (5-minute withdrawal session TTL, only pending packages of that
  apartment in a session, CPF check digits, invite validity).
- `src/infrastructure/supabase/server.ts`, `src/lib/actions/auth.ts`, `src/middleware.ts`: roles
  (`porteiro`, `morador`) and `condominio_id` in Supabase `app_metadata`.
- `docs/specs/*.md`: intent (pt-BR UI, no notifications yet, multi-tenancy by condominium).

Guesses and deliberate differences (please review):

1. **`entregue` is never written** by current code (both manual and QR withdrawals write `retirada`). It is
   kept in the enum and treated as "not in the lobby".
2. **Tenant scoping is indirect**: `encomendas` and `withdrawal_sessions` have no `condominio_id`; the server
   scopes through `moradores.condominio_id` / `apartamentos.condominio_id`. Rows with a NULL `condominio_id`
   (pre-multi-tenancy data) are invisible to the MCP server.
3. **RLS policies** that use Supabase's `auth.role()` are omitted locally; `created_by` columns hold Supabase
   auth user ids with no FK (as upstream).
4. **Stricter than the app**: `mark_package_withdrawn` requires status `pendente` (the app's `markWithdrawn`
   does not check); `register_package` requires `received_by` (required in the UI, not the server action) and a
   description or tracking code.
5. **Roles**: `porteiro` mirrors the app; `viewer` and `admin` are MCP-only. Resident (`morador`) keys are not
   supported (they would need per-apartment scoping).
6. **Time zone**: "today" is `America/Sao_Paulo` (configurable). The app stores `timestamptz` and has no setting.
7. **Notifications** do not exist in the app; the notifier is a stub and the channel is a guess.
8. `sql/mcp.sql` (API keys, audit, idempotency, one pagination index) is MCP-owned and additive.

Observations about the app made while reading it (not changed): `listPending`/`search` fetch rows for all
condominiums and filter in JavaScript after paginating, so page sizes and `total` can be wrong;
`findWithdrawalSession` sets an overdue session to `cancelled` (not `expired`); `incrementUseCount` on
invites is read-then-write and can lose updates under concurrency.

## Listing in MCP directories

- **Official MCP Registry**: `server.json` is ready; after the PyPI release run
  `mcp-publisher login github && mcp-publisher publish`. The registry checks the
  `mcp-name: io.github.orrevua/lobbyeasy-mcp` marker at the top of this README (an HTML comment, so it is
  invisible here) against the PyPI package.
- Community directories (e.g. mcp.so, Glama, PulseMCP, Smithery) mostly index GitHub or the official
  registry; submit the repo URL once it is public.
- None of this has been done yet: there is no remote, PyPI release or image push from this environment.

## Configuration

All settings are environment variables with the `LOBBY_` prefix (see `.env.example` and
`src/lobbyeasy_mcp/config.py`): backend and database URL, stdio condominium/role, HTTP host/port/public URL,
key store, writes on/off, confirmation TTL, rate-limit capacity and refill.

## Lessons learned

- **The SDK moved under me.** `mcp` 2.x renamed `FastMCP` to `mcp.server.mcpserver.MCPServer` and added a
  stateless 2026-07-28 protocol era (`server/discover`) next to the classic `initialize` handshake. Testing
  both eras over stdio and HTTP caught nothing broken, but would have.
- **Error text is prompt text.** "Package 17 not found. Use search_packages ..." lets the model recover by
  itself; a stack trace does not. Domain errors are shown verbatim, everything else becomes a reference id.
- **Scope comes from the credential, never from arguments.** No tool takes a condominium id, so a
  prompt-injected "now look at condominium X" has nothing to bind to. The repository signature forces it.
- **Writes need a human-shaped pause.** Propose/confirm costs one extra tool call and turns "the model did
  something" into "the user approved this exact sentence". Re-validating at confirm time catches races.
- **Allowlists fail closed.** Audit redaction keeps only known-safe argument names; a new free-text field is
  redacted by default.
- **Idempotency is reserve-then-complete**, not check-then-insert; only the former is safe concurrently.
- **Middleware is where cross-cutting rules belong.** A new tool is audited and rate limited without anyone
  remembering to do it.

## More

- [LEARNING.md](LEARNING.md): study path through the code and exercises.
- [docs/deploy.md](docs/deploy.md): Fly.io / Render, Supabase connection strings, key management.
- [docs/writeup-draft.md](docs/writeup-draft.md): blog post draft.

License: MIT.
