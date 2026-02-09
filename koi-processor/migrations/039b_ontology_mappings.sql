-- Migration 039b: Ontology Mapping Infrastructure
-- Date: 2026-02-08
-- Purpose: Schema registry and source-to-BKC ontology mappings
-- Supports the three-layer ingestion model (Source/Mapping/Commons)

-- Source schemas: records known external data schemas
CREATE TABLE IF NOT EXISTS source_schemas (
    id SERIAL PRIMARY KEY,
    schema_name TEXT UNIQUE NOT NULL,
    description TEXT,
    source_community TEXT,
    source_type TEXT,                           -- obsidian_yaml, csv, json_ld, rdf
    field_definitions JSONB NOT NULL DEFAULT '{}',
    mapping_status TEXT DEFAULT 'unmapped',     -- unmapped, partial, complete
    consent_status TEXT DEFAULT 'pending',      -- pending, verbal, written, formal, declined
    consent_details JSONB DEFAULT '{}',
    discovered_at TIMESTAMPTZ DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ,
    reviewed_by TEXT
);

-- Ontology mappings: explicit source -> BKC correspondences
CREATE TABLE IF NOT EXISTS ontology_mappings (
    id SERIAL PRIMARY KEY,
    source_schema_id INTEGER REFERENCES source_schemas(id),
    source_field TEXT NOT NULL,
    source_value_pattern TEXT,
    bkc_entity_type TEXT,
    bkc_predicate TEXT,
    bkc_property TEXT,
    mapping_type TEXT NOT NULL DEFAULT 'unmapped'
        CHECK (mapping_type IN ('equivalent', 'narrower', 'broader', 'related', 'unmapped', 'proposed_extension')),
    mapping_direction TEXT DEFAULT 'outgoing',
    confidence FLOAT DEFAULT 1.0,
    notes TEXT,
    reviewed_by TEXT,
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ontology_mappings_schema
    ON ontology_mappings(source_schema_id);

-- Entity registry additions for source preservation
ALTER TABLE entity_registry ADD COLUMN IF NOT EXISTS source_schema_id
    INTEGER REFERENCES source_schemas(id);
ALTER TABLE entity_registry ADD COLUMN IF NOT EXISTS source_metadata
    JSONB DEFAULT '{}';
ALTER TABLE entity_registry ADD COLUMN IF NOT EXISTS access_level
    TEXT DEFAULT 'public';
ALTER TABLE entity_registry ADD COLUMN IF NOT EXISTS contributed_by TEXT;
ALTER TABLE entity_registry ADD COLUMN IF NOT EXISTS source_community TEXT;
