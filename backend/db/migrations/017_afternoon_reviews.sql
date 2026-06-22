-- Phase 5B: afternoon email review.
-- One row per day holds the reviewed emails (classification, summary, draft id,
-- calendar suggestion) as JSON for the Daily Review panel to render.

CREATE TABLE IF NOT EXISTS afternoon_reviews (
    id SERIAL PRIMARY KEY,
    review_date DATE UNIQUE NOT NULL DEFAULT CURRENT_DATE,
    emails_json JSONB NOT NULL DEFAULT '[]',
    status VARCHAR(20) DEFAULT 'pending',  -- 'pending', 'approved', 'dismissed'
    approved_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT NOW()
);
