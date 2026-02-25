-- Migration 049: Peer aliases for human-friendly recipient resolution

CREATE TABLE IF NOT EXISTS koi_net_peer_aliases (
    alias TEXT PRIMARY KEY,
    node_rid TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_koi_peer_aliases_node
    ON koi_net_peer_aliases(node_rid);
