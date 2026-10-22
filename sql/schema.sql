-- =====================================================================
-- LobbyEasy schema, consolidated for local development.
--
-- Mirrors the *final* state of the app's incremental migration file
-- `docs/schema.sql` (sections 1-8) in orrevua/lobby-order-storing, with the
-- ALTER TABLE steps folded into the CREATE TABLE statements. Column names,
-- types, defaults, FKs and indexes are kept identical so the MCP server can be
-- pointed at the real Supabase database unchanged.
--
-- Deliberate differences from Supabase (marked LOCAL-DEV below):
--   * RLS policies on withdrawal_sessions use Supabase's `auth.role()`, which
--     does not exist in plain Postgres. They are omitted here. The app uses the
--     service-role client for everything, so RLS does not affect its reads.
--   * `moradores.created_by` and `invite_tokens.created_by` hold Supabase
--     `auth.users` ids; there is no FK because auth.users does not exist locally
--     (the app does not declare one either).
--
-- MCP-specific tables (API keys, audit log, idempotency) live in sql/mcp.sql so
-- this file stays a faithful mirror of the app.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid() (built in since PG13; harmless)

-- 7. Multi-tenancy: condominiums are the tenant boundary
CREATE TABLE IF NOT EXISTS condominios (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(200) NOT NULL,
    address     TEXT,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- 1. Apartamentos (unique per condominium since section 7)
CREATE TABLE IF NOT EXISTS apartamentos (
    id             SERIAL PRIMARY KEY,
    numero         VARCHAR(10) NOT NULL,
    bloco          VARCHAR(10) NOT NULL,
    created_at     TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    condominio_id  UUID REFERENCES condominios(id) ON DELETE CASCADE,
    CONSTRAINT unique_condo_ap_bloco UNIQUE (condominio_id, numero, bloco)
);

-- 2. Moradores (residents). cpf/signature_url from section 5, created_by from 6,
--    condominio_id (denormalised to avoid joins) from 7.
CREATE TABLE IF NOT EXISTS moradores (
    id             SERIAL PRIMARY KEY,
    nome           VARCHAR(150) NOT NULL,
    contato        VARCHAR(50),
    apartamento_id INT REFERENCES apartamentos(id) ON DELETE SET NULL,
    created_at     TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    cpf            VARCHAR(11),
    signature_url  TEXT,
    created_by     UUID,            -- Supabase auth user id (no FK, see header)
    condominio_id  UUID REFERENCES condominios(id) ON DELETE CASCADE
);

-- 3. Encomendas (packages). No condominio_id: scoped via morador_id -> moradores.
--    status is free text in the app ('pendente' | 'retirada' | 'entregue'); no CHECK
--    constraint exists upstream, so none is added here.
CREATE TABLE IF NOT EXISTS encomendas (
    id              SERIAL PRIMARY KEY,
    codigo_rastreio VARCHAR(100),
    descricao       TEXT,
    status          VARCHAR(20) DEFAULT 'pendente',
    data_chegada    TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    data_retirada   TIMESTAMP WITH TIME ZONE,
    morador_id      INT REFERENCES moradores(id) ON DELETE RESTRICT,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    received_by     TEXT            -- section 5: doorman who logged the arrival
);

CREATE INDEX IF NOT EXISTS idx_encomendas_status ON encomendas(status);
CREATE INDEX IF NOT EXISTS idx_encomendas_morador ON encomendas(morador_id);
CREATE INDEX IF NOT EXISTS idx_moradores_nome ON moradores(nome);

-- 4. Withdrawal sessions: a 5-minute QR (or manual) pickup of several packages.
CREATE TABLE IF NOT EXISTS withdrawal_sessions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    apartamento_id      INT NOT NULL REFERENCES apartamentos(id),
    encomenda_ids       INT[] NOT NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- 'pending' | 'confirmed' | 'expired' | 'cancelled'
    confirmation_method VARCHAR(20),   -- 'qr_scan' | 'manual'
    manual_reason       VARCHAR(50),   -- 'sem_celular' | 'idoso' | 'portador_necessidades' | 'outro'
    doorman_note        TEXT,
    created_by          TEXT,          -- doorman name/badge
    confirmed_by        TEXT,          -- 'resident' (QR) or doorman identifier (manual)
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    expires_at          TIMESTAMP WITH TIME ZONE NOT NULL,
    confirmed_at        TIMESTAMP WITH TIME ZONE,
    cpf_confirmacao     VARCHAR(11),   -- section 5
    signature_url       TEXT,          -- section 5
    CONSTRAINT valid_encomenda_ids CHECK (array_length(encomenda_ids, 1) > 0)
);

CREATE INDEX IF NOT EXISTS idx_ws_status ON withdrawal_sessions(status);
CREATE INDEX IF NOT EXISTS idx_ws_apartamento ON withdrawal_sessions(apartamento_id);
CREATE INDEX IF NOT EXISTS idx_ws_expires ON withdrawal_sessions(expires_at) WHERE status = 'pending';
-- LOCAL-DEV: upstream also runs
--   ALTER TABLE withdrawal_sessions ENABLE ROW LEVEL SECURITY;
--   CREATE POLICY ... USING (true);                        -- public read
--   CREATE POLICY ... USING (auth.role() = 'service_role'); -- writes

-- 7/8. Invite tokens for resident signup
CREATE TABLE IF NOT EXISTS invite_tokens (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    condominio_id  UUID NOT NULL REFERENCES condominios(id) ON DELETE CASCADE,
    token          VARCHAR(64) NOT NULL UNIQUE,
    created_by     UUID NOT NULL,
    expires_at     TIMESTAMP WITH TIME ZONE,
    max_uses       INT,
    use_count      INT NOT NULL DEFAULT 0,
    created_at     TIMESTAMP WITH TIME ZONE DEFAULT now(),
    invalidated_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_apartamentos_condominio ON apartamentos(condominio_id);
CREATE INDEX IF NOT EXISTS idx_moradores_condominio ON moradores(condominio_id);
CREATE INDEX IF NOT EXISTS idx_invite_tokens_token ON invite_tokens(token);
CREATE INDEX IF NOT EXISTS idx_invite_tokens_condominio ON invite_tokens(condominio_id);

