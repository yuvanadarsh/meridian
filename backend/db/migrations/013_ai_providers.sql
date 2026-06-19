-- Multi-provider AI: store API keys (encrypted) and per-task model config for
-- each provider, with exactly one active at a time. Also seeds the configurable
-- embedding-model settings used by the revectorize flow.
-- Run once: psql -U your_user -d meridian -f backend/db/migrations/013_ai_providers.sql

CREATE TABLE IF NOT EXISTS ai_providers (
    id              SERIAL PRIMARY KEY,
    provider        VARCHAR(50) UNIQUE NOT NULL,  -- anthropic, openai, gemini, deepseek, ollama
    api_key         TEXT,                          -- encrypted at rest (Fernet via SECRET_KEY)
    base_url        VARCHAR(255),                  -- e.g. ollama: http://localhost:11434
    is_active       BOOLEAN DEFAULT FALSE,
    model_chat      VARCHAR(100),                  -- model for chat
    model_classify  VARCHAR(100),                  -- model for classification/triage
    model_draft     VARCHAR(100),                  -- model for email drafting
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

-- Default Anthropic entry is active and pulls its key from the environment.
INSERT INTO ai_providers (provider, is_active, model_chat, model_classify, model_draft)
VALUES ('anthropic', true, 'claude-sonnet-4-6', 'claude-haiku-4-5-20251001', 'claude-sonnet-4-6')
ON CONFLICT (provider) DO NOTHING;

-- Configurable embedding model (used by the revectorize flow in Phase 4).
INSERT INTO user_settings (key, value) VALUES
    ('embedding_model', 'voyage-3-lite'),
    ('embedding_dim', '512')
ON CONFLICT (key) DO NOTHING;
