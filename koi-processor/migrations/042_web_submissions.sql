-- Migration 042: Web Submissions table
-- Tracks URL submissions from Telegram/Discord users through Octo
-- Stores preview, evaluation, and ingestion lifecycle

CREATE TABLE IF NOT EXISTS web_submissions (
    id SERIAL PRIMARY KEY,
    url TEXT NOT NULL,
    rid TEXT NOT NULL,
    domain TEXT NOT NULL,
    submitted_by TEXT,                            -- telegram/discord username
    submitted_via TEXT DEFAULT 'telegram',         -- telegram, discord, api
    submission_message TEXT,                       -- original user message
    status VARCHAR(20) DEFAULT 'pending',          -- pending/previewed/evaluated/ingested/rejected/error
    relevance_score FLOAT,
    relevance_reasoning TEXT,
    bioregional_tags TEXT[],
    title TEXT,
    description TEXT,
    content_hash TEXT,
    word_count INT,
    matching_entities JSONB DEFAULT '[]'::jsonb,
    ingested_entities JSONB DEFAULT '[]'::jsonb,   -- entities resolved during ingest
    vault_note_path TEXT,                          -- path to generated Sources/ vault note
    fetched_at TIMESTAMPTZ,
    evaluated_at TIMESTAMPTZ,
    ingested_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT valid_status CHECK (
        status IN ('pending', 'previewed', 'evaluated', 'ingested', 'rejected', 'error')
    )
);

-- Index for rate limiting queries
CREATE INDEX IF NOT EXISTS idx_web_submissions_created_at
    ON web_submissions(created_at);

-- Index for per-user rate limiting
CREATE INDEX IF NOT EXISTS idx_web_submissions_user_created
    ON web_submissions(submitted_by, created_at);

-- Index for URL lookups (check if already submitted)
CREATE INDEX IF NOT EXISTS idx_web_submissions_url
    ON web_submissions(url);

-- Index for status filtering
CREATE INDEX IF NOT EXISTS idx_web_submissions_status
    ON web_submissions(status);
