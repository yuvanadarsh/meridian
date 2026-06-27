-- Persistent chats: long-lived conversations that survive the daily chat reset.
-- Unlike chat_messages (wiped to "today only" each morning), these are kept
-- forever, listed on the /chat page, and mirrored into the Obsidian vault.

CREATE TABLE IF NOT EXISTS persistent_chats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255),
    auto_titled BOOLEAN DEFAULT FALSE,
    obsidian_note_path TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS persistent_chat_messages (
    id SERIAL PRIMARY KEY,
    chat_id UUID NOT NULL REFERENCES persistent_chats(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,  -- 'user' or 'assistant'
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pcm_chat_id ON persistent_chat_messages(chat_id);
CREATE INDEX IF NOT EXISTS idx_pc_updated ON persistent_chats(updated_at DESC);
