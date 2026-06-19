-- Supercharge import: track uploads of AI chat-export JSON (Claude, ChatGPT,
-- Gemini) that get parsed into the Obsidian vault and vectorized.
-- Run once: psql -U your_user -d meridian -f backend/db/migrations/014_supercharge.sql

CREATE TABLE IF NOT EXISTS supercharge_imports (
    id                      SERIAL PRIMARY KEY,
    provider                VARCHAR(50) NOT NULL,    -- claude, chatgpt, gemini
    filename                VARCHAR(255),
    total_conversations     INTEGER DEFAULT 0,
    processed_conversations INTEGER DEFAULT 0,
    status                  VARCHAR(20) DEFAULT 'pending',  -- pending, processing, complete, error
    created_at              TIMESTAMP DEFAULT NOW()
);
