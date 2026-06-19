-- Email threading: group messages by Gmail thread_id so RAG retrieves whole
-- conversations instead of isolated messages.
-- Run once: psql -U your_user -d meridian -f backend/db/migrations/010_email_threads.sql

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
    created_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(account_id, thread_id)
);

CREATE INDEX IF NOT EXISTS idx_threads_account ON email_threads(account_id);
CREATE INDEX IF NOT EXISTS idx_threads_vectorized ON email_threads(is_vectorized);

-- Link each email back to its parent thread row.
ALTER TABLE emails ADD COLUMN IF NOT EXISTS thread_db_id INTEGER REFERENCES email_threads(id);
CREATE INDEX IF NOT EXISTS idx_emails_thread_db ON emails(thread_db_id);
