-- Migration 044: KOI Memories + Chunks for RAG
-- Purpose: Create document storage with embeddings for semantic search
-- Enables GitHub sensor (and future sensors) to store content for RAG retrieval

-- 1. Document-level storage
CREATE TABLE IF NOT EXISTS koi_memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rid VARCHAR(500) NOT NULL,
    version INTEGER DEFAULT 1,
    event_type VARCHAR(20) NOT NULL DEFAULT 'NEW',
    source_sensor VARCHAR(200) NOT NULL,
    content JSONB NOT NULL,
    metadata JSONB DEFAULT '{}',
    superseded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(rid, version)
);

CREATE INDEX IF NOT EXISTS idx_koi_memories_rid ON koi_memories(rid);
CREATE INDEX IF NOT EXISTS idx_koi_memories_source_sensor ON koi_memories(source_sensor);
CREATE INDEX IF NOT EXISTS idx_koi_memories_created_at ON koi_memories(created_at DESC);

-- Unique constraint on rid for foreign keys
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'koi_memories'::regclass
        AND contype = 'u'
        AND conname = 'koi_memories_rid_key'
    ) THEN
        ALTER TABLE koi_memories ADD CONSTRAINT koi_memories_rid_key UNIQUE (rid);
    END IF;
END$$;

-- 2. Document-level embeddings (multi-dimension support)
CREATE TABLE IF NOT EXISTS koi_embeddings (
    id SERIAL PRIMARY KEY,
    memory_id UUID NOT NULL REFERENCES koi_memories(id) ON DELETE CASCADE,
    dim_1536 vector(1536),   -- OpenAI text-embedding-3-small (Octo's model)
    dim_1024 vector(1024),   -- BGE (future / RegenAI compat)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(memory_id)
);

-- IVFFlat index for fast cosine similarity search
-- Note: IVFFlat requires at least 100 rows to be effective; HNSW is better for small datasets
-- but we use IVFFlat for RegenAI compatibility. Will auto-build on first query.
CREATE INDEX IF NOT EXISTS idx_koi_embeddings_dim_1536
    ON koi_embeddings USING ivfflat (dim_1536 vector_cosine_ops) WITH (lists = 10);

-- 3. Chunk-level storage with embeddings
CREATE TABLE IF NOT EXISTS koi_memory_chunks (
    id SERIAL PRIMARY KEY,
    chunk_rid VARCHAR UNIQUE NOT NULL,
    document_rid VARCHAR NOT NULL REFERENCES koi_memories(rid) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    total_chunks INTEGER NOT NULL,
    content JSONB NOT NULL,
    embedding vector(1536),   -- Same dimension as doc-level
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunks_document ON koi_memory_chunks(document_rid);
CREATE INDEX IF NOT EXISTS idx_chunks_created ON koi_memory_chunks(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON koi_memory_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);

-- 4. Entity-to-chunk bridge for hybrid RAG
CREATE TABLE IF NOT EXISTS koi_entity_chunk_links (
    id SERIAL PRIMARY KEY,
    entity_name TEXT NOT NULL,
    entity_type TEXT,
    entity_uri TEXT,
    chunk_rid VARCHAR REFERENCES koi_memory_chunks(chunk_rid) ON DELETE CASCADE,
    document_rid VARCHAR,
    confidence FLOAT DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(entity_uri, chunk_rid)
);

CREATE INDEX IF NOT EXISTS idx_entity_chunk_entity ON koi_entity_chunk_links(entity_uri);
CREATE INDEX IF NOT EXISTS idx_entity_chunk_doc ON koi_entity_chunk_links(document_rid);
