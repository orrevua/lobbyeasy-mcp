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
