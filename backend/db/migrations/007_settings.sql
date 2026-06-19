-- User preferences persisted as simple key/value rows.
-- Run once: psql -U your_user -d meridian -f backend/db/migrations/007_settings.sql

CREATE TABLE IF NOT EXISTS user_settings (
    id SERIAL PRIMARY KEY,
    key VARCHAR(100) UNIQUE NOT NULL,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW()
);

INSERT INTO user_settings (key, value) VALUES
    ('response_tone', 'concise'),
    ('digest_schedule', '08:00'),
    ('voice_enabled', 'true'),
    ('agent_name', 'Meridian')
ON CONFLICT (key) DO NOTHING;
