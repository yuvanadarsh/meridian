-- Contact graph: aggregate per-person stats from email history for contact
-- intelligence in chat. The base contacts table may already exist (init.sql);
-- this migration ensures it exists and adds the richer Phase 4 columns.
-- Run once: psql -U your_user -d meridian -f backend/db/migrations/012_contacts_graph.sql

CREATE TABLE IF NOT EXISTS contacts (
    id              SERIAL PRIMARY KEY,
    email_address   VARCHAR(255) UNIQUE NOT NULL,
    display_name    VARCHAR(255),
    email_count     INTEGER DEFAULT 0,
    last_contacted  TIMESTAMP,
    embedding       vector(512),
    created_at      TIMESTAMP DEFAULT NOW()
);

ALTER TABLE contacts ADD COLUMN IF NOT EXISTS sent_count INTEGER DEFAULT 0;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS received_count INTEGER DEFAULT 0;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS first_contacted TIMESTAMP;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS topics TEXT[];

CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email_address);
