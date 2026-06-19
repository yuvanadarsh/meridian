-- Add regular tsvector column to email_threads (not generated, due to array_to_string immutability)
ALTER TABLE email_threads
ADD COLUMN IF NOT EXISTS search_vector tsvector;

-- Populate existing rows
UPDATE email_threads
SET search_vector = to_tsvector('english', coalesce(subject, ''));

-- Create trigger to keep it updated on insert/update
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

-- Create GIN index
CREATE INDEX IF NOT EXISTS idx_threads_fts ON email_threads USING GIN(search_vector);
