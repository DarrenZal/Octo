-- 045: Add entity descriptions and store full web content
-- Enables LLM extraction layer to persist rich descriptions and source content

-- Entity descriptions (from LLM extraction)
ALTER TABLE entity_registry ADD COLUMN IF NOT EXISTS description TEXT;

-- Store full source content in web_submissions (for re-processing, no TTL)
ALTER TABLE web_submissions ADD COLUMN IF NOT EXISTS content_text TEXT;
