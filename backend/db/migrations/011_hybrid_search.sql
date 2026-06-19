-- Hybrid search: add Postgres full-text (BM25-style) search vectors alongside
-- the pgvector embeddings so email RAG can combine semantic + lexical matches.
-- Run once: psql -U your_user -d meridian -f backend/db/migrations/011_hybrid_search.sql

ALTER TABLE emails ADD COLUMN IF NOT EXISTS search_vector tsvector
    GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(subject, '') || ' ' || coalesce(body_text, ''))
    ) STORED;

CREATE INDEX IF NOT EXISTS idx_emails_fts ON emails USING GIN(search_vector);

ALTER TABLE email_threads ADD COLUMN IF NOT EXISTS search_vector tsvector
    GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(subject, '') || ' ' || array_to_string(coalesce(participants, '{}'), ' '))
    ) STORED;

CREATE INDEX IF NOT EXISTS idx_threads_fts ON email_threads USING GIN(search_vector);
