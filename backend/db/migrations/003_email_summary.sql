-- Migration 003 — per-email one-sentence summary produced during the sweep,
-- shown in the triage review UI.
--   psql -U your_user -d meridian -f backend/db/migrations/003_email_summary.sql

ALTER TABLE emails ADD COLUMN IF NOT EXISTS summary TEXT;
