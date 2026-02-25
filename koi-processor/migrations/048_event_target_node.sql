-- Migration 048: Recipient-scoped event delivery
--
-- Adds target_node so events can be unicast to a specific recipient.
-- NULL target_node remains broadcast behavior for backward compatibility.

ALTER TABLE koi_net_events
    ADD COLUMN IF NOT EXISTS target_node TEXT;

CREATE INDEX IF NOT EXISTS idx_koi_events_target
    ON koi_net_events(target_node);

CREATE INDEX IF NOT EXISTS idx_koi_events_target_poll
    ON koi_net_events(target_node, expires_at, queued_at)
    WHERE target_node IS NOT NULL;
