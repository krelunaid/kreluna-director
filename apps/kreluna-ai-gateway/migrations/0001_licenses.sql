PRAGMA foreign_keys = ON;

CREATE TABLE licenses (
  id TEXT PRIMARY KEY,
  token_hash TEXT NOT NULL UNIQUE,
  token_prefix TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  tenant_name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'revoked')),
  plan TEXT NOT NULL DEFAULT 'studio',
  daily_request_limit INTEGER NOT NULL DEFAULT 500 CHECK (daily_request_limit > 0),
  monthly_token_limit INTEGER NOT NULL DEFAULT 2000000 CHECK (monthly_token_limit > 0),
  requests_today INTEGER NOT NULL DEFAULT 0 CHECK (requests_today >= 0),
  tokens_this_month INTEGER NOT NULL DEFAULT 0 CHECK (tokens_this_month >= 0),
  current_day TEXT NOT NULL,
  current_month TEXT NOT NULL,
  expires_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_used_at TEXT,
  revoked_at TEXT
);

CREATE INDEX idx_licenses_tenant ON licenses (tenant_id);
CREATE INDEX idx_licenses_status ON licenses (status);

CREATE TABLE minute_limits (
  license_id TEXT NOT NULL REFERENCES licenses(id) ON DELETE CASCADE,
  minute_bucket TEXT NOT NULL,
  requests INTEGER NOT NULL DEFAULT 0 CHECK (requests >= 0),
  PRIMARY KEY (license_id, minute_bucket)
);

CREATE TABLE usage_events (
  id TEXT PRIMARY KEY,
  license_id TEXT NOT NULL REFERENCES licenses(id) ON DELETE RESTRICT,
  request_id TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  status TEXT NOT NULL,
  input_tokens INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
  output_tokens INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
  total_tokens INTEGER NOT NULL DEFAULT 0 CHECK (total_tokens >= 0),
  cost_usd_ticks INTEGER NOT NULL DEFAULT 0 CHECK (cost_usd_ticks >= 0),
  latency_ms INTEGER NOT NULL DEFAULT 0 CHECK (latency_ms >= 0),
  error_code TEXT NOT NULL DEFAULT ''
);

CREATE INDEX idx_usage_license_created ON usage_events (license_id, created_at DESC);
