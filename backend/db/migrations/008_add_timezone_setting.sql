-- Add timezone preference to user_settings.
-- Run once: psql -U your_user -d meridian -f backend/db/migrations/008_add_timezone_setting.sql

INSERT INTO user_settings (key, value)
VALUES ('timezone', 'America/New_York')
ON CONFLICT (key) DO NOTHING;
