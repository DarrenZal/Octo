-- Migration 052: Durable outbound share ledger
--
-- Tracks what this node shared with which target so offboarding can emit
-- reliable FORGET events even after queue TTL expiry.

CREATE TABLE IF NOT EXISTS koi_outbound_shares (
    id SERIAL PRIMARY KEY,
    document_rid TEXT NOT NULL,
    target_node TEXT NOT NULL,
    shared_at TIMESTAMPTZ DEFAULT NOW(),
    retracted_at TIMESTAMPTZ,
    UNIQUE(document_rid, target_node)
);

CREATE INDEX IF NOT EXISTS idx_outbound_shares_target
    ON koi_outbound_shares(target_node);

CREATE INDEX IF NOT EXISTS idx_outbound_shares_active
    ON koi_outbound_shares(target_node)
    WHERE retracted_at IS NULL;
