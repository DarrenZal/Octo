-- Migration 039: KOI-net Protocol Tables
-- Date: 2026-02-08
-- Purpose: Event queue, edge profiles, and node registry for KOI-net federation

-- Event tracking for KOI-net protocol (database-backed queue)
CREATE TABLE IF NOT EXISTS koi_net_events (
    id SERIAL PRIMARY KEY,
    event_id UUID DEFAULT gen_random_uuid(),
    event_type VARCHAR(10) NOT NULL,  -- NEW, UPDATE, FORGET
    rid TEXT NOT NULL,
    manifest JSONB,
    contents JSONB,
    source_node TEXT,
    queued_at TIMESTAMPTZ DEFAULT NOW(),
    delivered_to TEXT[] DEFAULT '{}',
    confirmed_by TEXT[] DEFAULT '{}',
    expires_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '24 hours'
);

CREATE INDEX IF NOT EXISTS idx_koi_events_rid ON koi_net_events(rid);
CREATE INDEX IF NOT EXISTS idx_koi_events_type ON koi_net_events(event_type);
CREATE INDEX IF NOT EXISTS idx_koi_events_expires ON koi_net_events(expires_at);
CREATE INDEX IF NOT EXISTS idx_koi_events_queued ON koi_net_events(queued_at);

-- Edge profiles for node-to-node relationships
CREATE TABLE IF NOT EXISTS koi_net_edges (
    id SERIAL PRIMARY KEY,
    edge_rid TEXT UNIQUE NOT NULL,
    source_node TEXT NOT NULL,
    target_node TEXT NOT NULL,
    edge_type VARCHAR(10) NOT NULL,  -- WEBHOOK, POLL
    status VARCHAR(10) NOT NULL,     -- PROPOSED, APPROVED
    rid_types TEXT[] DEFAULT '{}',   -- Which RID types flow on this edge
    metadata JSONB DEFAULT '{}',     -- Per-edge config (e.g., {"event_ttl_hours": 72})
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Node registry (known peers)
CREATE TABLE IF NOT EXISTS koi_net_nodes (
    id SERIAL PRIMARY KEY,
    node_rid TEXT UNIQUE NOT NULL,
    node_name TEXT,
    node_type VARCHAR(10),    -- FULL, PARTIAL
    base_url TEXT,
    public_key TEXT,          -- DER-encoded, base64
    provides_event TEXT[] DEFAULT '{}',   -- RID types this node broadcasts
    provides_state TEXT[] DEFAULT '{}',   -- RID types this node serves
    last_seen TIMESTAMPTZ,
    status VARCHAR(10) DEFAULT 'active',
    metadata JSONB DEFAULT '{}'
);
