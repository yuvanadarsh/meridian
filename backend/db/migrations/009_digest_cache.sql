-- One row per calendar day; upserted each time the digest is rebuilt.
-- Run once: psql -U your_user -d meridian -f backend/db/migrations/009_digest_cache.sql

CREATE TABLE IF NOT EXISTS digest_cache (
    id          SERIAL PRIMARY KEY,
    cache_date  DATE UNIQUE NOT NULL DEFAULT CURRENT_DATE,
    calendar    TEXT,
    emails      TEXT,
    news        TEXT,
    stocks      TEXT,
    full_text   TEXT,
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);
