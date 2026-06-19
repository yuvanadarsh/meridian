-- Triage aggressiveness setting: aggressive / normal / safe.
-- Run once: psql -U your_user -d meridian -f backend/db/migrations/015_triage_mode.sql

INSERT INTO user_settings (key, value) VALUES ('triage_mode', 'normal')
ON CONFLICT (key) DO NOTHING;
