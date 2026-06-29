-- 022_notes_table.sql
-- Rename the Obsidian-era `obsidian_notes` table to `notes` and make PostgreSQL
-- the direct memory layer. Existing rows (and their embeddings) are preserved —
-- the table is renamed, not dropped. New columns categorize each note and link
-- it back to the record it was generated from.

ALTER TABLE obsidian_notes RENAME TO notes;

-- note_type categorizes the source of a note.
-- Values: 'email', 'contact', 'chat', 'persistent_chat', 'sent', 'daily', 'general'
ALTER TABLE notes ADD COLUMN IF NOT EXISTS note_type VARCHAR(50) DEFAULT 'general';

-- source_id links back to the originating record:
--   note_type='email'   -> email_threads.id
--   note_type='contact' -> contacts.id
ALTER TABLE notes ADD COLUMN IF NOT EXISTS source_id INTEGER;

-- wikilinks already exists on the legacy table, but add defensively for fresh DBs.
ALTER TABLE notes ADD COLUMN IF NOT EXISTS wikilinks TEXT[] DEFAULT '{}';

-- updated_at tracks the last append/edit so memory_service can stamp writes.
ALTER TABLE notes ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();

-- Backfill note_type for existing rows using their legacy file_path prefix.
UPDATE notes SET note_type = 'email'   WHERE file_path LIKE '%/Emails/%';
UPDATE notes SET note_type = 'contact' WHERE file_path LIKE '%/Contacts/%';
UPDATE notes SET note_type = 'chat'    WHERE file_path LIKE '%/Chats/%';
UPDATE notes SET note_type = 'daily'   WHERE file_path LIKE '%/Daily/%';
UPDATE notes SET note_type = 'sent'    WHERE file_path LIKE '%/Sent/%';

-- file_path is retained for migration reference but is no longer written after
-- this change (memory_service writes synthetic pg:// paths only for uniqueness).

-- Swap the legacy index names for the new table name.
DROP INDEX IF EXISTS idx_obsidian_notes_embedding;
DROP INDEX IF EXISTS idx_obsidian_vectorized;

CREATE INDEX IF NOT EXISTS idx_notes_embedding ON notes
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_notes_vectorized ON notes(is_vectorized);
CREATE INDEX IF NOT EXISTS idx_notes_type ON notes(note_type);
CREATE INDEX IF NOT EXISTS idx_notes_source ON notes(source_id);
