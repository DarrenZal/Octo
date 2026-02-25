-- Migration 051: Commons intake metadata for shared documents

ALTER TABLE koi_shared_documents
    ADD COLUMN IF NOT EXISTS recipient_type VARCHAR(20) DEFAULT 'peer';

ALTER TABLE koi_shared_documents
    ADD COLUMN IF NOT EXISTS intake_status VARCHAR(20) DEFAULT 'none';

ALTER TABLE koi_shared_documents
    ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;

ALTER TABLE koi_shared_documents
    ADD COLUMN IF NOT EXISTS reviewed_by TEXT;

ALTER TABLE koi_shared_documents
    ADD COLUMN IF NOT EXISTS review_notes TEXT;

CREATE INDEX IF NOT EXISTS idx_shared_docs_recipient_type
    ON koi_shared_documents(recipient_type);

CREATE INDEX IF NOT EXISTS idx_shared_docs_intake_status
    ON koi_shared_documents(intake_status)
    WHERE recipient_type = 'commons';

UPDATE koi_shared_documents
SET recipient_type = 'peer'
WHERE recipient_type IS NULL;

UPDATE koi_shared_documents
SET intake_status = CASE
    WHEN status = 'staged' THEN 'staged'
    ELSE 'none'
END
WHERE intake_status IS NULL;
