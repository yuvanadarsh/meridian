-- Migration 002 — Obsidian vault as a long-term memory layer.
-- Stores every ingested .md note plus its embedding for RAG retrieval.
--   psql -U your_user -d meridian -f backend/db/migrations/002_obsidian_notes.sql

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS obsidian_notes (
    id SERIAL PRIMARY KEY,
    file_path TEXT UNIQUE NOT NULL,
    title TEXT,
    content TEXT,
    wikilinks TEXT[],            -- extracted [[links]]
    embedding vector(1024),
    last_modified TIMESTAMP,
    is_vectorized BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_obsidian_vectorized ON obsidian_notes(is_vectorized);
