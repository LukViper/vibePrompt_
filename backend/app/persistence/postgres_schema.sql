-- PostgreSQL schema for VibePrompt (Neon / RDS / Supabase).
-- Apply with: psql "$DATABASE_URL" -f backend/app/persistence/postgres_schema.sql
-- SQLite remains local-dev only.

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    password_hash TEXT,
    display_name TEXT,
    avatar_url TEXT,
    auth_provider TEXT DEFAULT 'legacy',
    default_org_id TEXT,
    mfa_enabled INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users (lower(email));

CREATE TABLE IF NOT EXISTS organizations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'personal',
    plan TEXT NOT NULL DEFAULT 'free',
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    mfa_required INTEGER NOT NULL DEFAULT 0,
    saml_enabled INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS org_memberships (
    org_id TEXT NOT NULL REFERENCES organizations(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    role TEXT NOT NULL DEFAULT 'member',
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (org_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_org_memberships_user ON org_memberships(user_id);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    owner_id TEXT,
    org_id TEXT REFERENCES organizations(id),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_projects_org ON projects(org_id) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS free_tier_allocations (
    user_id TEXT PRIMARY KEY REFERENCES users(id),
    generations_allocated INTEGER NOT NULL,
    generations_used INTEGER NOT NULL DEFAULT 0,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS generation_usage (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    org_id TEXT,
    project_id TEXT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    latency_ms INTEGER,
    cost_usd_estimate DOUBLE PRECISION,
    trace_id TEXT,
    status TEXT NOT NULL,
    funding_source TEXT NOT NULL,
    error_message TEXT,
    idempotency_key TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS user_provider_configs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    encrypted_api_key TEXT NOT NULL,
    base_url TEXT,
    is_active INTEGER NOT NULL DEFAULT 0,
    validated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    UNIQUE (user_id, provider)
);

CREATE TABLE IF NOT EXISTS rate_limit_buckets (
    bucket_key TEXT PRIMARY KEY,
    window_start TIMESTAMPTZ NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS guest_sessions (
    id TEXT PRIMARY KEY,
    ip_hash TEXT,
    generations_allocated INTEGER NOT NULL,
    generations_used INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    day_key TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS global_usage_counters (
    counter_key TEXT PRIMARY KEY,
    window_start TIMESTAMPTZ NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES organizations(id),
    user_id TEXT,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT,
    before_json TEXT,
    after_json TEXT,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_logs_org_created ON audit_logs(org_id, created_at);

CREATE TABLE IF NOT EXISTS user_mfa (
    user_id TEXT PRIMARY KEY REFERENCES users(id),
    totp_secret TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
