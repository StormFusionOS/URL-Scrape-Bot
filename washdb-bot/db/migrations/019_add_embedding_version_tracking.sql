-- ============================================================================
-- Migration 019: Add Embedding Version Tracking
-- ============================================================================
-- Adds columns to track embedding generation and enable quarterly re-embedding
-- Per SCRAPER BOT.pdf: Track model version and support quarterly re-embed
-- ============================================================================

-- Track this migration
INSERT INTO schema_migrations (version, name, applied_at)
VALUES ('019', 'add_embedding_version_tracking', NOW())
ON CONFLICT (version) DO NOTHING;

-- ============================================================================
-- COMPETITOR_PAGES: Add embedding tracking
-- ============================================================================

ALTER TABLE competitor_pages
ADD COLUMN IF NOT EXISTS embedding_version VARCHAR(50),
ADD COLUMN IF NOT EXISTS embedded_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS embedding_chunk_count INTEGER DEFAULT 0;

COMMENT ON COLUMN competitor_pages.embedding_version IS 'Version of embedding model used (e.g., v1.0). NULL if not yet embedded.';
COMMENT ON COLUMN competitor_pages.embedded_at IS 'When embeddings were last generated for this page';
COMMENT ON COLUMN competitor_pages.embedding_chunk_count IS 'Number of chunks/embeddings stored in Qdrant for this page';

-- Index for finding pages that need re-embedding
CREATE INDEX IF NOT EXISTS idx_competitor_pages_embedding_version
ON competitor_pages(embedding_version)
WHERE embedding_version IS NOT NULL;

-- ============================================================================
-- SERP_RESULTS: Add embedding tracking
-- ============================================================================

ALTER TABLE serp_results
ADD COLUMN IF NOT EXISTS embedding_version VARCHAR(50),
ADD COLUMN IF NOT EXISTS embedded_at TIMESTAMP;

COMMENT ON COLUMN serp_results.embedding_version IS 'Version of embedding model used for snippet. NULL if not embedded.';
COMMENT ON COLUMN serp_results.embedded_at IS 'When snippet embedding was generated';

-- Index for finding results that need re-embedding
CREATE INDEX IF NOT EXISTS idx_serp_results_embedding_version
ON serp_results(embedding_version)
WHERE embedding_version IS NOT NULL;

-- ============================================================================
-- HELPER FUNCTION: Find pages needing re-embedding
-- ============================================================================

CREATE OR REPLACE FUNCTION get_pages_needing_reembedding(
    current_version VARCHAR(50) DEFAULT 'v1.0',
    limit_count INTEGER DEFAULT 100
)
RETURNS TABLE (
    page_id INTEGER,
    url TEXT,
    page_type VARCHAR(100),
    last_embedded embedding_version,
    crawled_at TIMESTAMP
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        cp.page_id,
        cp.url,
        cp.page_type,
        cp.embedding_version,
        cp.crawled_at
    FROM competitor_pages cp
    WHERE
        -- Not embedded yet OR using old version
        (cp.embedding_version IS NULL OR cp.embedding_version != current_version)
        -- Only pages that have been crawled
        AND cp.crawled_at IS NOT NULL
        -- Has content
        AND cp.content_hash IS NOT NULL
    ORDER BY
        -- Prioritize: never embedded, then oldest embeddings
        cp.embedded_at NULLS FIRST,
        cp.crawled_at DESC
    LIMIT limit_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_pages_needing_reembedding IS 'Find competitor pages that need (re)embedding. Used for quarterly re-embedding jobs.';

-- ============================================================================
-- HELPER FUNCTION: Find SERP snippets needing re-embedding
-- ============================================================================

CREATE OR REPLACE FUNCTION get_snippets_needing_reembedding(
    current_version VARCHAR(50) DEFAULT 'v1.0',
    limit_count INTEGER DEFAULT 100
)
RETURNS TABLE (
    result_id INTEGER,
    snapshot_id INTEGER,
    url TEXT,
    snippet TEXT,
    last_embedded embedding_version
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        sr.result_id,
        sr.snapshot_id,
        sr.url,
        sr.snippet,
        sr.embedding_version
    FROM serp_results sr
    WHERE
        -- Not embedded yet OR using old version
        (sr.embedding_version IS NULL OR sr.embedding_version != current_version)
        -- Has snippet text
        AND sr.snippet IS NOT NULL
        AND LENGTH(sr.snippet) > 0
    ORDER BY
        sr.embedded_at NULLS FIRST
    LIMIT limit_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_snippets_needing_reembedding IS 'Find SERP snippets that need (re)embedding for semantic search.';

-- ============================================================================
-- VERIFICATION
-- ============================================================================

DO $$
DECLARE
    cp_cols INTEGER;
    sr_cols INTEGER;
BEGIN
    -- Count new columns in competitor_pages
    SELECT COUNT(*) INTO cp_cols
    FROM information_schema.columns
    WHERE table_name = 'competitor_pages'
    AND column_name IN ('embedding_version', 'embedded_at', 'embedding_chunk_count');

    -- Count new columns in serp_results
    SELECT COUNT(*) INTO sr_cols
    FROM information_schema.columns
    WHERE table_name = 'serp_results'
    AND column_name IN ('embedding_version', 'embedded_at');

    IF cp_cols = 3 AND sr_cols = 2 THEN
        RAISE NOTICE 'Migration 019 completed successfully. Embedding tracking columns added.';
    ELSE
        RAISE WARNING 'Migration 019: Some columns may not have been added. Check schema.';
    END IF;
END $$;
