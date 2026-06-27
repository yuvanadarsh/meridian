-- Meridian complete schema — reflects all migrations through 020
-- Fresh installs: run this file only
-- Existing installs: run individual migration files in db/migrations/
-- Last updated: 2026-06-27
--
-- Prerequisites: PostgreSQL with pgvector installed.
--   psql -U your_user -c "CREATE DATABASE meridian;"
--   psql -U your_user -d meridian -f backend/db/init.sql

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------------
-- Gmail accounts: one row per connected Google account.
-- auth_status tracks OAuth health ('ok', 'expired') — set by the email-poll
-- task on invalid_grant errors, reset to 'ok' after successful re-auth.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gmail_accounts (
    id            SERIAL PRIMARY KEY,
    email         VARCHAR(255) UNIQUE NOT NULL,
    label         VARCHAR(50),               -- 'personal', 'school', 'work', 'professional'
    oauth_token   JSONB,
    last_synced_at TIMESTAMP,
    auth_status   VARCHAR(20) DEFAULT 'ok',  -- 'ok' | 'expired'
    created_at    TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Email threads: groups of messages sharing a Gmail thread_id.
-- search_vector is maintained by trigger (see below) because array_to_string
-- is not immutable and cannot be used in a GENERATED ALWAYS column.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS email_threads (
    id              SERIAL PRIMARY KEY,
    account_id      INTEGER REFERENCES gmail_accounts(id),
    thread_id       VARCHAR(255) NOT NULL,
    subject         TEXT,
    participants    TEXT[],
    message_count   INTEGER DEFAULT 0,
    last_message_at TIMESTAMP,
    embedding       vector(512),
    is_vectorized   BOOLEAN DEFAULT FALSE,
    search_vector   tsvector,
    created_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(account_id, thread_id)
);

CREATE INDEX IF NOT EXISTS idx_threads_account ON email_threads(account_id);
CREATE INDEX IF NOT EXISTS idx_threads_vectorized ON email_threads(is_vectorized);
CREATE INDEX IF NOT EXISTS idx_threads_fts ON email_threads USING GIN(search_vector);

-- Trigger: keep email_threads.search_vector in sync with subject changes.
CREATE OR REPLACE FUNCTION update_thread_search_vector()
RETURNS trigger AS $$
BEGIN
    NEW.search_vector := to_tsvector('english', coalesce(NEW.subject, ''));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS thread_search_vector_trigger ON email_threads;
CREATE TRIGGER thread_search_vector_trigger
    BEFORE INSERT OR UPDATE ON email_threads
    FOR EACH ROW EXECUTE FUNCTION update_thread_search_vector();

-- ---------------------------------------------------------------------------
-- Emails: raw messages from Gmail with triage classification and embeddings.
-- search_vector is GENERATED from subject + body for full-text (BM25) search.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS emails (
    id             SERIAL PRIMARY KEY,
    account_id     INTEGER REFERENCES gmail_accounts(id),
    gmail_id       VARCHAR(255) UNIQUE NOT NULL,
    thread_id      VARCHAR(255),
    thread_db_id   INTEGER REFERENCES email_threads(id),
    from_address   VARCHAR(255),
    to_addresses   TEXT[],
    subject        TEXT,
    body_text      TEXT,
    snippet        TEXT,
    summary        TEXT,                                 -- one-sentence AI summary
    received_at    TIMESTAMP,
    triage_status  VARCHAR(20) DEFAULT 'pending',        -- 'keep', 'archive', 'trash', 'pending', 'unreadable'
    is_vectorized  BOOLEAN DEFAULT FALSE,
    embedding      vector(512),
    search_vector  tsvector GENERATED ALWAYS AS (
                       to_tsvector('english', coalesce(subject, '') || ' ' || coalesce(body_text, ''))
                   ) STORED,
    created_at     TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_emails_triage ON emails(triage_status);
CREATE INDEX IF NOT EXISTS idx_emails_account ON emails(account_id);
CREATE INDEX IF NOT EXISTS idx_emails_received ON emails(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_emails_thread_db ON emails(thread_db_id);
CREATE INDEX IF NOT EXISTS idx_emails_fts ON emails USING GIN(search_vector);

-- ---------------------------------------------------------------------------
-- Sweep progress: resumable sweep state per account.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sweep_progress (
    account_id          INTEGER PRIMARY KEY REFERENCES gmail_accounts(id),
    status              VARCHAR(20) DEFAULT 'idle',  -- idle, running, classifying, triage_complete, completed, error
    total_estimated     INTEGER DEFAULT 0,
    fetched             INTEGER DEFAULT 0,
    stored              INTEGER DEFAULT 0,
    skipped             INTEGER DEFAULT 0,
    last_gmail_id       VARCHAR(255),
    error               TEXT,
    sweep_completed_at  TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Obsidian notes: vault .md files indexed for RAG retrieval.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS obsidian_notes (
    id            SERIAL PRIMARY KEY,
    file_path     TEXT UNIQUE NOT NULL,
    title         TEXT,
    content       TEXT,
    wikilinks     TEXT[],              -- extracted [[links]]
    embedding     vector(512),
    last_modified TIMESTAMP,
    is_vectorized BOOLEAN DEFAULT FALSE,
    created_at    TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_obsidian_vectorized ON obsidian_notes(is_vectorized);

-- ---------------------------------------------------------------------------
-- Calendar events: upcoming and recent events synced from Google Calendar.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS calendar_events (
    id              SERIAL PRIMARY KEY,
    account_id      INTEGER REFERENCES gmail_accounts(id),
    google_event_id VARCHAR(255) UNIQUE NOT NULL,
    title           TEXT,
    description     TEXT,
    start_time      TIMESTAMP,
    end_time        TIMESTAMP,
    attendees       TEXT[],
    meet_link       VARCHAR(500),
    source_email_id INTEGER REFERENCES emails(id),
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Chat messages: conversation history shown in the UI and used for RAG context.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_messages (
    id          SERIAL PRIMARY KEY,
    role        VARCHAR(20) NOT NULL,    -- 'user' or 'assistant'
    content     TEXT NOT NULL,
    tokens_used INTEGER,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Drafts: AI-generated email drafts awaiting user review.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS drafts (
    id              SERIAL PRIMARY KEY,
    account_id      INTEGER REFERENCES gmail_accounts(id),
    to_email        VARCHAR(255),
    subject         TEXT,
    body            TEXT,
    thread_email_id INTEGER REFERENCES emails(id),
    status          VARCHAR(20) DEFAULT 'pending',   -- 'pending', 'sent', 'discarded'
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_drafts_status ON drafts(status);

-- ---------------------------------------------------------------------------
-- User settings: key/value preferences.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_settings (
    id         SERIAL PRIMARY KEY,
    key        VARCHAR(100) UNIQUE NOT NULL,
    value      TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW()
);

INSERT INTO user_settings (key, value) VALUES
    ('response_tone',   'concise'),
    ('digest_schedule', '08:00'),
    ('voice_enabled',   'true'),
    ('agent_name',      'Meridian'),
    ('timezone',        'America/New_York'),
    ('triage_mode',     'normal'),
    ('embedding_model', 'voyage-3-lite'),
    ('embedding_dim',   '512')
ON CONFLICT (key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Digest cache: one row per day, upserted when the morning brief is built.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS digest_cache (
    id         SERIAL PRIMARY KEY,
    cache_date DATE UNIQUE NOT NULL DEFAULT CURRENT_DATE,
    calendar   TEXT,
    emails     TEXT,
    news       TEXT,
    stocks     TEXT,
    full_text  TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Contacts: aggregate stats per person derived from email history.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS contacts (
    id              SERIAL PRIMARY KEY,
    email_address   VARCHAR(255) UNIQUE NOT NULL,
    display_name    VARCHAR(255),
    email_count     INTEGER DEFAULT 0,
    sent_count      INTEGER DEFAULT 0,
    received_count  INTEGER DEFAULT 0,
    first_contacted TIMESTAMP,
    last_contacted  TIMESTAMP,
    topics          TEXT[],
    embedding       vector(512),
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email_address);

-- ---------------------------------------------------------------------------
-- AI providers: encrypted API keys and per-task model config. Exactly one
-- provider is active at a time. Anthropic is seeded and active by default.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ai_providers (
    id              SERIAL PRIMARY KEY,
    provider        VARCHAR(50) UNIQUE NOT NULL,  -- anthropic, openai, gemini, deepseek, ollama
    api_key         TEXT,                          -- encrypted at rest (Fernet via SECRET_KEY)
    base_url        VARCHAR(255),
    is_active       BOOLEAN DEFAULT FALSE,
    model_chat      VARCHAR(100),
    model_classify  VARCHAR(100),
    model_draft     VARCHAR(100),
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

INSERT INTO ai_providers (provider, is_active, model_chat, model_classify, model_draft)
VALUES ('anthropic', true, 'claude-sonnet-4-6', 'claude-haiku-4-5-20251001', 'claude-sonnet-4-6')
ON CONFLICT (provider) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Supercharge imports: tracks uploads of AI chat-export JSON files
-- (Claude, ChatGPT, Gemini) parsed into the Obsidian vault.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS supercharge_imports (
    id                      SERIAL PRIMARY KEY,
    provider                VARCHAR(50) NOT NULL,    -- claude, chatgpt, gemini
    filename                VARCHAR(255),
    total_conversations     INTEGER DEFAULT 0,
    processed_conversations INTEGER DEFAULT 0,
    status                  VARCHAR(20) DEFAULT 'pending',  -- pending, processing, complete, error
    created_at              TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Scheduled tasks: dynamic task registry read by the scheduler once a minute.
-- task_key matches a registered BaseTask subclass in services/tasks/.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id                SERIAL PRIMARY KEY,
    task_key          VARCHAR(100) NOT NULL,
    display_name      VARCHAR(200),
    schedule_time     VARCHAR(5) NOT NULL,          -- HH:MM
    schedule_days     VARCHAR(20) DEFAULT 'daily',  -- 'daily', 'weekdays', 'weekends'
    enabled           BOOLEAN DEFAULT TRUE,
    last_run_at       TIMESTAMP,
    last_run_status   VARCHAR(20),                  -- 'success', 'error', 'running'
    last_run_summary  TEXT,
    created_at        TIMESTAMP DEFAULT NOW()
);

INSERT INTO scheduled_tasks (task_key, display_name, schedule_time, schedule_days) VALUES
    ('morning_brief',     'Morning Brief',            '08:00', 'daily'),
    ('email_poll',        'Email Sync',               '00:00', 'daily'),
    ('afternoon_review',  'Afternoon Email Review',   '17:00', 'daily'),
    ('calendar_sync',     'Calendar Sync',            '07:00', 'daily')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- Afternoon reviews: one row per day, holds the reviewed emails as JSON for
-- the Daily Review panel. The user approves or dismisses before any mutation.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS afternoon_reviews (
    id          SERIAL PRIMARY KEY,
    review_date DATE UNIQUE NOT NULL DEFAULT CURRENT_DATE,
    emails_json JSONB NOT NULL DEFAULT '[]',
    status      VARCHAR(20) DEFAULT 'pending',  -- 'pending', 'approved', 'dismissed'
    approved_at TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Usage log: per-call API usage across all providers with calculated cost.
-- Source of truth for the cost-tracking UI (GET /usage/today).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS usage_log (
    id         SERIAL PRIMARY KEY,
    provider   VARCHAR(50) NOT NULL,      -- 'anthropic', 'elevenlabs', 'voyageai', 'openai', etc.
    model      VARCHAR(100),
    usage_type VARCHAR(50) NOT NULL,      -- 'input_tokens', 'output_tokens', 'characters', 'embed_tokens'
    units      INTEGER NOT NULL DEFAULT 0,
    cost_usd   DECIMAL(10, 6) NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_usage_log_created ON usage_log(created_at);
CREATE INDEX IF NOT EXISTS idx_usage_log_provider ON usage_log(provider);

-- ---------------------------------------------------------------------------
-- OAuth state: short-lived PKCE verifier storage for the OAuth callback flow.
-- Rows are deleted immediately after the code exchange completes.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS oauth_state (
    state         VARCHAR(255) PRIMARY KEY,
    code_verifier VARCHAR(255) NOT NULL,
    label         VARCHAR(100),
    account_id    INTEGER REFERENCES gmail_accounts(id) ON DELETE CASCADE,
    created_at    TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oauth_state_created_at ON oauth_state(created_at);

-- ---------------------------------------------------------------------------
-- DEPRECATED: token_usage was the Phase 1 Anthropic-only token counter.
-- Kept for backward compatibility with existing installs. New code reads and
-- writes usage_log instead. Do not use this table in new features.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS token_usage (
    id           SERIAL PRIMARY KEY,
    session_date DATE DEFAULT CURRENT_DATE UNIQUE,
    input_tokens  INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    total_tokens  INTEGER DEFAULT 0,
    updated_at   TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Persistent chats: long-lived conversations that survive the daily chat reset.
-- Listed on the /chat page and mirrored into the Obsidian vault (Chats/).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS persistent_chats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255),
    auto_titled BOOLEAN DEFAULT FALSE,
    obsidian_note_path TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS persistent_chat_messages (
    id SERIAL PRIMARY KEY,
    chat_id UUID NOT NULL REFERENCES persistent_chats(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,  -- 'user' or 'assistant'
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pcm_chat_id ON persistent_chat_messages(chat_id);
CREATE INDEX IF NOT EXISTS idx_pc_updated ON persistent_chats(updated_at DESC);
