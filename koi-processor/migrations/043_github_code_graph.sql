-- 043_github_code_graph.sql
-- GitHub sensor tables + code artifact tracking for Phase 5.7
-- Run: cat koi-processor/migrations/043_github_code_graph.sql | ssh root@45.132.245.30 "docker exec -i regen-koi-postgres psql -U postgres -d octo_koi"

-- Tracked repositories
CREATE TABLE IF NOT EXISTS github_repos (
    id SERIAL PRIMARY KEY,
    repo_url TEXT NOT NULL UNIQUE,
    repo_name TEXT NOT NULL,
    branch TEXT DEFAULT 'main',
    clone_path TEXT,
    last_commit_sha TEXT,
    last_scan_at TIMESTAMPTZ,
    file_count INT DEFAULT 0,
    code_entity_count INT DEFAULT 0,
    status VARCHAR(20) DEFAULT 'active',
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Per-file state (content hash change detection)
CREATE TABLE IF NOT EXISTS github_file_state (
    id SERIAL PRIMARY KEY,
    repo_id INT REFERENCES github_repos(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    rid TEXT NOT NULL,
    vault_note_path TEXT,
    line_count INT,
    byte_size INT,
    file_type TEXT,
    last_commit_sha TEXT,
    last_commit_author TEXT,
    last_commit_date TIMESTAMPTZ,
    last_commit_message TEXT,
    entity_count INT DEFAULT 0,
    code_entity_count INT DEFAULT 0,
    scanned_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(repo_id, file_path)
);

-- Code artifacts (relational mirror of AGE graph nodes)
CREATE TABLE IF NOT EXISTS koi_code_artifacts (
    id SERIAL PRIMARY KEY,
    code_uri TEXT UNIQUE NOT NULL,
    kind TEXT NOT NULL,                  -- Function, Class, Module, File, Import, Interface
    repo_key TEXT NOT NULL,
    file_path TEXT NOT NULL,
    symbol TEXT,                         -- Function/class name
    language TEXT,
    signature TEXT,
    docstring TEXT,
    line_start INT,
    line_end INT,
    commit_sha TEXT,
    extraction_run_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_code_artifacts_repo ON koi_code_artifacts(repo_key);
CREATE INDEX IF NOT EXISTS idx_code_artifacts_kind ON koi_code_artifacts(kind);
CREATE INDEX IF NOT EXISTS idx_code_artifacts_file ON koi_code_artifacts(file_path);
CREATE INDEX IF NOT EXISTS idx_code_artifacts_symbol ON koi_code_artifacts(symbol);
CREATE INDEX IF NOT EXISTS idx_code_artifacts_run ON koi_code_artifacts(extraction_run_id);

CREATE INDEX IF NOT EXISTS idx_github_file_state_repo ON github_file_state(repo_id);
CREATE INDEX IF NOT EXISTS idx_github_file_state_path ON github_file_state(file_path);
