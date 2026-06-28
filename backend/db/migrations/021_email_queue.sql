-- Migration 021: Inbox redesign — persistent email queue + brief/review removal.
--
-- Replaces the daily afternoon-review batch with a continuous triage queue that
-- accumulates classified emails until the user approves them in the Inbox page.
-- Also retires the morning brief and afternoon review scheduled tasks.

-- Drop afternoon_reviews (replaced by email_queue).
DROP TABLE IF EXISTS afternoon_reviews;

-- Persistent email queue — accumulates until the user approves each entry.
-- One row per email; classification is one of trash/archive/keep/draft. Rows
-- with approved_at set have been acted on (Gmail mutated, or kept/drafted).
CREATE TABLE IF NOT EXISTS email_queue (
    id             SERIAL PRIMARY KEY,
    email_id       INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    account_id     INTEGER NOT NULL REFERENCES gmail_accounts(id),
    classification VARCHAR(20) NOT NULL,           -- 'trash', 'archive', 'keep', 'draft'
    ai_summary     TEXT,
    needs_draft    BOOLEAN DEFAULT FALSE,
    draft_id       INTEGER REFERENCES drafts(id),
    draft_status   VARCHAR(20),                    -- NULL, 'generating', 'ready', 'sent'
    approved_at    TIMESTAMP,
    created_at     TIMESTAMP DEFAULT NOW(),
    UNIQUE(email_id)                               -- one queue entry per email
);

CREATE INDEX IF NOT EXISTS idx_eq_account ON email_queue(account_id);
CREATE INDEX IF NOT EXISTS idx_eq_approved ON email_queue(approved_at);
CREATE INDEX IF NOT EXISTS idx_eq_classification ON email_queue(classification);

-- Retire the removed scheduled tasks. Continuous triage on the email poll
-- replaces the afternoon review; the morning brief pipeline is gone entirely.
DELETE FROM scheduled_tasks WHERE task_key = 'morning_brief';
DELETE FROM scheduled_tasks WHERE task_key = 'afternoon_review';
