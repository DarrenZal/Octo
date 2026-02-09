-- Migration 040: Add KOI RID column to entity_registry
-- Date: 2026-02-08
-- Purpose: Enable federation by giving each entity a KOI-net compatible RID
-- Backfill happens via Python script (backfill_koi_rids.py) using rid-lib

ALTER TABLE entity_registry ADD COLUMN IF NOT EXISTS koi_rid TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_koi_rid
    ON entity_registry(koi_rid) WHERE koi_rid IS NOT NULL;
