-- =====================================================================
-- Objects owned by lobbyeasy-mcp (NOT part of the LobbyEasy app schema).
-- Safe to run against the real Supabase database: additive and idempotent.
-- =====================================================================

-- Keyset pagination index for search_packages (ORDER BY data_chegada DESC, id DESC).
CREATE INDEX IF NOT EXISTS idx_encomendas_chegada_id ON encomendas(data_chegada DESC, id DESC);
