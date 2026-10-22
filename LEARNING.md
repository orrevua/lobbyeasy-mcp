# Learning path: lobbyeasy-mcp

A guided tour for a backend developer learning MCP. Read in this order; each step names the concept
the file teaches and the test that pins it down. Budget: one evening for steps 1-5, another for 6-10.

## Study path

| # | Read | Concept | Pinned by |
|---|---|---|---|
| 1 | `git show 90a398e` (milestone 1) | The smallest MCP server: `MCPServer`, `@tool`, stdio, return types become `outputSchema` | `tests/test_stdio.py` |
| 2 | `src/lobbyeasy_mcp/views.py` | Tool schemas are prompts: `Annotated[..., Field(description=...)]`, input models (`PackageFilters`), output models | `test_tool_catalog` |
| 3 | `src/lobbyeasy_mcp/tools/read.py` | Thin adapters, `Context` injection, `ToolAnnotations` (`readOnlyHint`) | `tests/test_tools_e2e.py` |
| 4 | `src/lobbyeasy_mcp/deps.py` | Error design: `ToolError` vs `ResourceError` vs `MCPError`, actionable messages, reference ids | `test_get_package...`, `test_resources` |
| 5 | `src/lobbyeasy_mcp/service.py` | Business layer: PII masking, keyset cursors with a filter fingerprint, time zones | `tests/test_units.py` |
| 6 | `src/lobbyeasy_mcp/data/base.py` -> `memory.py` -> `postgres.py` | Repository protocol, tenant scoping in every signature, parameterised SQL, keyset pagination, compare-and-set updates | `tests/test_repository_contract.py` (runs on both) |
| 7 | `src/lobbyeasy_mcp/resources.py`, `prompts.py` | Resources (app-attached context, URI templates) vs tools (model-called) vs prompts (user-invoked) | `test_resources`, `test_prompts` |
| 8 | `src/lobbyeasy_mcp/auth.py`, `http.py` | Streamable HTTP, `TokenVerifier`, API keys hashed at rest, principal from the token | `tests/test_http.py`, `tests/test_auth.py` |
| 9 | `src/lobbyeasy_mcp/middleware.py`, `safety/ratelimit.py`, `safety/audit.py` | Server middleware for cross-cutting rules: write gating, token bucket, allowlist redaction | `tests/test_safety.py` |
| 10 | `src/lobbyeasy_mcp/actions.py`, `safety/confirmations.py`, `safety/idempotency.py`, `tools/write.py` | Human-in-the-loop writes (propose/confirm), re-validation, idempotency keys | `tests/test_safety.py` |
| 11 | `Dockerfile`, `fly.toml`, `docs/deploy.md`, `pyproject.toml`, `server.json` | Shipping: uv in Docker, stateless HTTP, PyPI/uvx, the MCP Registry | `uv build` |

Try it interactively along the way:

```bash
npx @modelcontextprotocol/inspector uv run lobbyeasy-mcp      # browse tools/resources/prompts in a UI
LOBBY_ENABLE_WRITES=true LOBBY_ROLE=porteiro npx @modelcontextprotocol/inspector uv run lobbyeasy-mcp
```

## Official docs worth reading next to the code

- MCP specification (tools, resources, prompts, transports, authorization): https://modelcontextprotocol.io/specification
- Python SDK v2 docs and migration guide (FastMCP -> MCPServer): https://py.sdk.modelcontextprotocol.io/v2/
- MCP security best practices: https://modelcontextprotocol.io/specification/draft/basic/security_best_practices
- MCP Registry publishing: https://github.com/modelcontextprotocol/registry
- psycopg 3 (async, pools, row factories): https://www.psycopg.org/psycopg3/docs/
- Supabase connection strings and poolers: https://supabase.com/docs/guides/database/connecting-to-postgres
- Keyset pagination ("use the index, Luke"): https://use-the-index-luke.com/no-offset
- Stripe on idempotency keys: https://stripe.com/blog/idempotency
- LGPD overview (why phone/CPF are masked): https://www.gov.br/anpd/
- uv in Docker: https://docs.astral.sh/uv/guides/integration/docker/
- vhs (terminal GIFs): https://github.com/charmbracelet/vhs

## Improve it yourself

1. **[easy] Accent-insensitive search.** "Joao" should find "João Pedro". Use Postgres `unaccent` and
   `unicodedata` normalisation in the memory backend; extend the contract test so both agree.
2. **[easy] `get_withdrawal_session` tool.** Expose a session by id with its packages, statuses and expiry.
   Reuse `session_view`; scope through the apartment.
3. **[easy] Audit reader for admins.** A `get_audit_log(since, tool, outcome)` tool gated by a new `audit`
   permission. Make sure the audit rows themselves are not leaking anything you redacted.
4. **[medium] Real notifier.** Implement `Notifier` for WhatsApp Cloud API or Twilio behind an env flag;
   keep `StubNotifier` for tests. Add retries and record the provider message id in the result.
5. **[medium] Withdrawal sessions as writes.** Port the app's `createWithdrawalSession` + manual confirmation
   (with `manual_reason`) as propose/confirm tools, honouring the 5-minute TTL and "pending and same
   apartment" rule. Compare with the simpler `mark_package_withdrawn`.
6. **[medium] Shared rate limits and confirmations.** Move the token bucket and pending confirmations to
   Postgres (or Redis) so two Fly machines enforce one budget. Test with two servers sharing a DB.
7. **[medium] Resident-scoped keys.** Support a `morador` role whose key is bound to one apartment: every
   read is filtered to it and `find_residents` is disabled. Where does the scoping belong?
8. **[medium] Resource subscriptions.** Emit `notifications/resources/updated` for
   `lobby://condominiums/{id}/pending` after a confirmed write (`ctx.notify_resource_updated`).
9. **[hard] OAuth instead of API keys.** Replace `ApiKeyVerifier` with a JWT verifier for Supabase Auth
   tokens (JWKS), map `app_metadata.role`/`condominio_id` to the `Principal`, and set
   `validate_token_resource=True` with an audience.
10. **[hard] Tool-use eval.** With an API key, script 20 lobby questions and check Claude picks the right
    tools, never calls `confirm_action` without an explicit "yes" in the transcript, and never reveals PII
    for a `viewer`. Report pass rates in `docs/writeup-draft.md`.
11. **[hard] Elicitation for confirmations.** On clients that support it, ask the user directly with
    `ctx.elicit()` instead of relying on the model to relay the summary; fall back to tokens otherwise.
12. **[hard] Row-level security.** Run the server as a Postgres role with RLS policies keyed on a
    `SET LOCAL app.condominium_id`, so scoping is enforced by the database too (defence in depth).
