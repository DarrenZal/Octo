-- Migration 041: Cross-references for federated entity resolution
-- Date: 2026-02-08
-- Purpose: Link local entities to remote entities via KOI RIDs

CREATE TABLE IF NOT EXISTS koi_net_cross_refs (
    id SERIAL PRIMARY KEY,
    local_uri TEXT NOT NULL,
    remote_rid TEXT NOT NULL,
    remote_node TEXT NOT NULL,
    relationship VARCHAR(20) DEFAULT 'related_to',
    confidence FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(local_uri, remote_rid)
);

CREATE INDEX IF NOT EXISTS idx_cross_refs_local ON koi_net_cross_refs(local_uri);
CREATE INDEX IF NOT EXISTS idx_cross_refs_remote ON koi_net_cross_refs(remote_rid);
