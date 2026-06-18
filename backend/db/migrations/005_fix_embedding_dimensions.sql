-- Migration 005 — Switch embedding columns from vector(1024) to vector(512).
-- Switches the embedding model from voyage-large-2 (1024 dims) to
-- voyage-3-lite (512 dims) for cost ($0.02/1M vs $0.12/1M) and correctness.
-- Existing embeddings must be cleared and re-generated after this migration.
--   psql -U your_user -d meridian -f backend/db/migrations/005_fix_embedding_dimensions.sql

ALTER TABLE obsidian_notes ALTER COLUMN embedding TYPE vector(512);
ALTER TABLE emails ALTER COLUMN embedding TYPE vector(512);
ALTER TABLE contacts ALTER COLUMN embedding TYPE vector(512);

-- Clear stale embeddings so the vectorization loop re-embeds with the new model.
UPDATE obsidian_notes SET embedding = NULL, is_vectorized = FALSE;
UPDATE emails SET embedding = NULL, is_vectorized = FALSE WHERE is_vectorized = TRUE;
