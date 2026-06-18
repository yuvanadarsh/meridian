-- Records when triage classification completed so the review UI can be
-- reopened after the user navigates away.
ALTER TABLE sweep_progress ADD COLUMN IF NOT EXISTS sweep_completed_at TIMESTAMP;
