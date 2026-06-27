-- PKCE state storage for OAuth flows and auth health tracking on accounts.
--
-- oauth_state holds a short-lived (state → code_verifier) mapping created
-- at the start of every OAuth flow and deleted immediately after the callback
-- exchanges the code. Storing it in the database (rather than a module-level
-- dict) makes the verifier survive container restarts and multi-worker setups.
--
-- auth_status on gmail_accounts tracks whether the stored token is valid.
-- The email-poll task sets it to 'expired' on invalid_grant errors;
-- a successful re-auth resets it to 'ok'.

CREATE TABLE IF NOT EXISTS oauth_state (
    state        VARCHAR(255) PRIMARY KEY,
    code_verifier VARCHAR(255) NOT NULL,
    label        VARCHAR(100),
    account_id   INTEGER REFERENCES gmail_accounts(id) ON DELETE CASCADE,
    created_at   TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oauth_state_created_at ON oauth_state(created_at);

ALTER TABLE gmail_accounts ADD COLUMN IF NOT EXISTS auth_status VARCHAR(20) DEFAULT 'ok';
