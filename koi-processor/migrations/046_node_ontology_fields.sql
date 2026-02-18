-- Migration 046: Add ontology fields to koi_net_nodes
-- Idempotent: safe to rerun
ALTER TABLE koi_net_nodes ADD COLUMN IF NOT EXISTS ontology_uri TEXT;
ALTER TABLE koi_net_nodes ADD COLUMN IF NOT EXISTS ontology_version TEXT;
