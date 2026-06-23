-- Track per-call API usage across all providers with calculated cost.
-- Run: psql -U your_user -d meridian -f backend/db/migrations/018_usage_log.sql

CREATE TABLE IF NOT EXISTS usage_log (
    id SERIAL PRIMARY KEY,
    provider VARCHAR(50) NOT NULL,      -- 'anthropic', 'elevenlabs', 'voyageai', 'openai', etc.
    model VARCHAR(100),                  -- e.g. 'claude-sonnet-4-6', 'voyage-3-lite'
    usage_type VARCHAR(50) NOT NULL,     -- 'input_tokens', 'output_tokens', 'characters', 'embed_tokens'
    units INTEGER NOT NULL DEFAULT 0,
    cost_usd DECIMAL(10, 6) NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_usage_log_created ON usage_log(created_at);
CREATE INDEX IF NOT EXISTS idx_usage_log_provider ON usage_log(provider);
