-- Meridian — Phase 1 schema.
-- Run once against your local PostgreSQL:
--   psql -U your_user -d meridian -f backend/db/init.sql

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS gmail_accounts (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    label VARCHAR(50),               -- 'personal', 'school', 'work', 'professional'
    oauth_token JSONB,
    last_synced_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS emails (
    id SERIAL PRIMARY KEY,
    account_id INTEGER REFERENCES gmail_accounts(id),
    gmail_id VARCHAR(255) UNIQUE NOT NULL,
    thread_id VARCHAR(255),
    from_address VARCHAR(255),
    to_addresses TEXT[],
    subject TEXT,
    body_text TEXT,
    snippet TEXT,
    received_at TIMESTAMP,
    triage_status VARCHAR(20) DEFAULT 'pending',  -- 'keep', 'archive', 'trash', 'pending', 'unreadable'
    summary TEXT,                                 -- one-sentence AI summary (see migration 003)
    is_vectorized BOOLEAN DEFAULT FALSE,
    embedding vector(512),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_emails_triage ON emails(triage_status);
CREATE INDEX IF NOT EXISTS idx_emails_account ON emails(account_id);
CREATE INDEX IF NOT EXISTS idx_emails_received ON emails(received_at DESC);

CREATE TABLE IF NOT EXISTS calendar_events (
    id SERIAL PRIMARY KEY,
    account_id INTEGER REFERENCES gmail_accounts(id),
    google_event_id VARCHAR(255) UNIQUE NOT NULL,
    title TEXT,
    description TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    attendees TEXT[],
    meet_link VARCHAR(500),
    source_email_id INTEGER REFERENCES emails(id),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    role VARCHAR(20) NOT NULL,       -- 'user' or 'assistant'
    content TEXT NOT NULL,
    tokens_used INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS token_usage (
    id SERIAL PRIMARY KEY,
    session_date DATE DEFAULT CURRENT_DATE UNIQUE,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS contacts (
    id SERIAL PRIMARY KEY,
    email_address VARCHAR(255) UNIQUE NOT NULL,
    display_name VARCHAR(255),
    email_count INTEGER DEFAULT 0,
    last_contacted TIMESTAMP,
    embedding vector(512),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Tracks resumable email-sweep progress per account so a failed sweep can be
-- observed and resumed (see gmail_service.sweep_account).
CREATE TABLE IF NOT EXISTS sweep_progress (
    account_id INTEGER PRIMARY KEY REFERENCES gmail_accounts(id),
    status VARCHAR(20) DEFAULT 'idle',   -- idle, running, classifying, triage_complete, completed, error
    total_estimated INTEGER DEFAULT 0,
    fetched INTEGER DEFAULT 0,
    stored INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0,
    last_gmail_id VARCHAR(255),
    error TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Obsidian vault notes ingested for RAG retrieval (see migration 002).
CREATE TABLE IF NOT EXISTS obsidian_notes (
    id SERIAL PRIMARY KEY,
    file_path TEXT UNIQUE NOT NULL,
    title TEXT,
    content TEXT,
    wikilinks TEXT[],
    embedding vector(512),
    last_modified TIMESTAMP,
    is_vectorized BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_obsidian_vectorized ON obsidian_notes(is_vectorized);
