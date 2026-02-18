-- Migration 047: Idempotent event dedup index for WEBHOOK push retries
-- Safe to rerun
CREATE UNIQUE INDEX IF NOT EXISTS idx_koi_net_events_source_event
    ON koi_net_events (source_node, event_id)
    WHERE event_id IS NOT NULL;
