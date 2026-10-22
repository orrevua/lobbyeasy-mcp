-- =====================================================================
-- Objects owned by lobbyeasy-mcp (NOT part of the LobbyEasy app schema).
-- Safe to run against the real Supabase database: additive and idempotent.
-- =====================================================================

-- Keyset pagination index for search_packages (ORDER BY data_chegada DESC, id DESC).
CREATE INDEX IF NOT EXISTS idx_encomendas_chegada_id ON encomendas(data_chegada DESC, id DESC);

-- API keys for the remote server. Only the SHA-256 of each key is stored.
-- Create rows with: lobbyeasy-mcp keys create --condominium <uuid> --role viewer --db
CREATE TABLE IF NOT EXISTS mcp_api_keys (
    key_id          VARCHAR(16) PRIMARY KEY,           -- public part of 'lbe_<key_id>_<secret>'
    key_hash        CHAR(64) NOT NULL,                 -- sha256 hex of the whole key
    condominium_id  UUID NOT NULL REFERENCES condominios(id) ON DELETE CASCADE,
    role            VARCHAR(20) NOT NULL CHECK (role IN ('viewer', 'porteiro', 'admin')),
    label           TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at      TIMESTAMPTZ
);

-- Audit log: one row per tools/call, arguments redacted by the server (allowlist).
-- No FK to condominios on purpose: audit rows must outlive what they describe.
CREATE TABLE IF NOT EXISTS mcp_audit_log (
    id              BIGSERIAL PRIMARY KEY,
    at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    key_id          TEXT NOT NULL,
    condominium_id  UUID,
    role            TEXT,
    tool            TEXT NOT NULL,
    arguments       JSONB NOT NULL,
    outcome         TEXT NOT NULL CHECK (outcome IN ('ok', 'error', 'denied', 'rate_limited')),
    error           TEXT,
    duration_ms     INT NOT NULL,
    request_id      TEXT
);
CREATE INDEX IF NOT EXISTS idx_mcp_audit_condo_at ON mcp_audit_log (condominium_id, at DESC);
CREATE INDEX IF NOT EXISTS idx_mcp_audit_key_at ON mcp_audit_log (key_id, at DESC);

-- Idempotency keys for write actions: reserve (insert) -> complete (update) or release (delete).
CREATE TABLE IF NOT EXISTS mcp_idempotency (
    key_id           TEXT NOT NULL,
    idempotency_key  TEXT NOT NULL,
    tool             TEXT NOT NULL,
    request_hash     CHAR(64) NOT NULL,
    status           TEXT NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress', 'completed')),
    result           JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at     TIMESTAMPTZ,
    PRIMARY KEY (key_id, idempotency_key)
);
