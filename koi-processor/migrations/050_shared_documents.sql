-- Migration 050: Persistent inbound shared documents
--
-- Polled share events are transient in koi_net_events; this table persists
-- received shares for /koi-net/shared-with-me and intake workflows.

CREATE TABLE IF NOT EXISTS koi_shared_documents (
    id SERIAL PRIMARY KEY,
    event_id UUID,
    document_rid TEXT NOT NULL,
    sender_node TEXT NOT NULL,
    sender_name TEXT,
    event_type VARCHAR(10) NOT NULL,  -- NEW, UPDATE, FORGET
    manifest JSONB,
    contents JSONB,
    message TEXT,
    received_at TIMESTAMPTZ DEFAULT NOW(),
    status VARCHAR(20) DEFAULT 'received'  -- received, ingested, retracted, staged
);

CREATE INDEX IF NOT EXISTS idx_shared_docs_received
    ON koi_shared_documents(received_at DESC);

CREATE INDEX IF NOT EXISTS idx_shared_docs_sender
    ON koi_shared_documents(sender_node);

CREATE INDEX IF NOT EXISTS idx_shared_docs_rid
    ON koi_shared_documents(document_rid);

CREATE UNIQUE INDEX IF NOT EXISTS idx_shared_docs_event_id
    ON koi_shared_documents(event_id)
    WHERE event_id IS NOT NULL;
