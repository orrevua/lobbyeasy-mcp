# Deploying the remote server

The remote server is `lobbyeasy-mcp http`: MCP over **streamable HTTP** at `/mcp`, a public
`/healthz`, and bearer API keys. It is stateless by default (`LOBBY_STATELESS_HTTP=true`), so any
instance can answer any request and the platform can scale it to zero.

> Free tiers change often. At the time of writing Render has a free web-service plan that sleeps when
> idle; Fly.io bills per second with no permanent free allowance for new orgs, but a stopped 256 MB
> machine costs close to nothing. Check current pricing before relying on either.
> Neither deployment below was executed from the build environment (no Docker daemon, no cloud
> credentials); the image build and configs are untested there.

## 1. Database

Point `LOBBY_DATABASE_URL` at Supabase (Project Settings > Database > Connection string):

- **Session pooler** (port 5432) or **direct connection**: work as-is.
- **Transaction pooler** (port 6543): also works; the server disables prepared statements.

Run the MCP-owned objects once (additive; does not touch app tables):

```bash
psql "$LOBBY_DATABASE_URL" -f sql/mcp.sql
```

Use a dedicated least-privilege role: `SELECT` on the app tables; `INSERT, UPDATE` on `encomendas`
only if you enable writes; full access to the `mcp_*` tables.

## 2. API keys

```bash
LOBBY_DATABASE_URL=... uv run lobbyeasy-mcp keys create \
  --condominium <condominio uuid> --role viewer --label "síndico assistant" --db
```

The plaintext key is printed once; only its SHA-256 is stored. Revoke with
`UPDATE mcp_api_keys SET revoked_at = now() WHERE key_id = '...'`.
Without Postgres, use `--file api_keys.json` and `LOBBY_API_KEYS_FILE`.

## 3a. Fly.io

```bash
fly launch --no-deploy --copy-config          # uses fly.toml (region gru)
fly secrets set LOBBY_DATABASE_URL='postgresql://...'
fly deploy
curl https://lobbyeasy-mcp.fly.dev/healthz
```

## 3b. Render

New > Blueprint > this repo (`render.yaml`), then set `LOBBY_DATABASE_URL` and
`LOBBY_PUBLIC_URL=https://<service>.onrender.com` in the dashboard.

## 4. Connect a client

```bash
claude mcp add --transport http lobbyeasy https://lobbyeasy-mcp.fly.dev/mcp \
  --header "Authorization: Bearer lbe_..."
```

Cursor (`~/.cursor/mcp.json`):

```json
{ "mcpServers": { "lobbyeasy": {
    "url": "https://lobbyeasy-mcp.fly.dev/mcp",
    "headers": { "Authorization": "Bearer lbe_..." } } } }
```

Claude Desktop connects to remote servers through Settings > Connectors (OAuth-oriented); for a static
API key, bridge it locally with `npx mcp-remote https://.../mcp --header "Authorization: Bearer lbe_..."`.

## Operational notes

- Rate-limit buckets and pending write confirmations live in process memory: run **one** machine
  (the configs above do), or move them to Postgres/Redis before scaling out.
- The SDK also serves OAuth protected-resource metadata at
  `/.well-known/oauth-protected-resource/mcp`. API keys are a pragmatic stand-in for OAuth; moving to a
  real authorization server (Supabase Auth, Auth0, ...) only means swapping the `TokenVerifier`.
