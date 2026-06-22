-- Phase 5B: dynamic task scheduling.
-- The scheduler reads this table once a minute instead of using hardcoded times,
-- so any task can be enabled/disabled and rescheduled from Settings.

CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id SERIAL PRIMARY KEY,
    task_key VARCHAR(100) NOT NULL,             -- matches a key in services.tasks.TASK_REGISTRY
    display_name VARCHAR(200),
    schedule_time VARCHAR(5) NOT NULL,          -- HH:MM
    schedule_days VARCHAR(20) DEFAULT 'daily',  -- 'daily', 'weekdays', 'weekends'
    enabled BOOLEAN DEFAULT TRUE,
    last_run_at TIMESTAMP,
    last_run_status VARCHAR(20),                -- 'success', 'error', 'running'
    last_run_summary TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Default schedule. email_poll runs on its own 15-minute interval regardless of
-- schedule_time, so its time is a placeholder.
INSERT INTO scheduled_tasks (task_key, display_name, schedule_time, schedule_days) VALUES
    ('morning_brief', 'Morning Brief', '08:00', 'daily'),
    ('email_poll', 'Email Sync', '00:00', 'daily'),
    ('afternoon_review', 'Afternoon Email Review', '17:00', 'daily'),
    ('calendar_sync', 'Calendar Sync', '07:00', 'daily')
ON CONFLICT DO NOTHING;
