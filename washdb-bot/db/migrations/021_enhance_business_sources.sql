-- ============================================================================
-- Migration 021: Enhance Business Sources for Source Evidence System
-- ============================================================================
-- Adds comprehensive tracking fields to business_sources table for full
-- provenance, status tracking, and raw data preservation.
--
-- New fields:
-- - source_module: Which scraper created this record
-- - status: Current status (ok, captcha, error, etc.)
-- - status_reason: Detailed reason code for status
-- - first_seen_at: When first discovered
-- - last_seen_at: Most recent verification
-- - raw_payload: Full structured data extracted (JSONB)
-- - snapshot_path: Path to saved HTML snapshot
-- ============================================================================

-- Track this migration
INSERT INTO schema_migrations (version, name, applied_at)
VALUES ('021', 'enhance_business_sources', NOW())
ON CONFLICT (version) DO NOTHING;

-- ============================================================================
-- ADD NEW COLUMNS TO business_sources
-- ============================================================================

-- Source module tracking (which scraper created this)
ALTER TABLE business_sources
ADD COLUMN IF NOT EXISTS source_module VARCHAR(50);

COMMENT ON COLUMN business_sources.source_module IS
'Which scraper module created this record (scrape_yp, citation_crawler, competitor_crawler, serp_scraper)';

-- Status tracking
ALTER TABLE business_sources
ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'ok';

COMMENT ON COLUMN business_sources.status IS
'Current status: ok, captcha, robots_disallowed, gone, error, redirect, blocked';

-- Detailed reason code
ALTER TABLE business_sources
ADD COLUMN IF NOT EXISTS status_reason TEXT;

COMMENT ON COLUMN business_sources.status_reason IS
'Detailed reason code for status (e.g., "name_mismatch", "phone_mismatch", "captcha_detected")';

-- First seen timestamp
ALTER TABLE business_sources
ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMP DEFAULT NOW();

COMMENT ON COLUMN business_sources.first_seen_at IS
'When this source was first discovered/scraped';

-- Last seen timestamp (different from updated_at - this is last verification)
ALTER TABLE business_sources
ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP DEFAULT NOW();

COMMENT ON COLUMN business_sources.last_seen_at IS
'Most recent successful check/verification of this source';

-- Raw payload for full structured data
ALTER TABLE business_sources
ADD COLUMN IF NOT EXISTS raw_payload JSONB;

COMMENT ON COLUMN business_sources.raw_payload IS
'Full structured data extracted from source (for provenance and re-analysis)';

-- Snapshot path for HTML archiving
ALTER TABLE business_sources
ADD COLUMN IF NOT EXISTS snapshot_path TEXT;

COMMENT ON COLUMN business_sources.snapshot_path IS
'Path to saved HTML snapshot file (optional, for audit trail)';

-- ============================================================================
-- CREATE INDEXES FOR NEW COLUMNS
-- ============================================================================

-- Status index for filtering by status
CREATE INDEX IF NOT EXISTS idx_business_sources_status
ON business_sources(status);

-- Source module index for filtering by scraper
CREATE INDEX IF NOT EXISTS idx_business_sources_source_module
ON business_sources(source_module);

-- First seen index for time-based queries
CREATE INDEX IF NOT EXISTS idx_business_sources_first_seen
ON business_sources(first_seen_at DESC);

-- Last seen index for stale detection
CREATE INDEX IF NOT EXISTS idx_business_sources_last_seen
ON business_sources(last_seen_at DESC);

-- Raw payload GIN index for JSONB queries
CREATE INDEX IF NOT EXISTS idx_business_sources_raw_payload
ON business_sources USING GIN (raw_payload);

-- Composite index for status + module queries
CREATE INDEX IF NOT EXISTS idx_business_sources_status_module
ON business_sources(status, source_module);

-- ============================================================================
-- UPDATE EXISTING RECORDS
-- ============================================================================

-- Set default source_module based on source_type for existing records
UPDATE business_sources
SET source_module = CASE
    WHEN source_type = 'yp' THEN 'scrape_yp'
    WHEN source_type IN ('google', 'google_business') THEN 'citation_crawler'
    WHEN source_type IN ('yelp', 'bbb', 'facebook', 'angi', 'thumbtack', 'homeadvisor', 'mapquest', 'manta') THEN 'citation_crawler'
    ELSE 'unknown'
END
WHERE source_module IS NULL;

-- Set first_seen_at to scraped_at for existing records
UPDATE business_sources
SET first_seen_at = scraped_at
WHERE first_seen_at IS NULL AND scraped_at IS NOT NULL;

-- Set last_seen_at to updated_at or scraped_at for existing records
UPDATE business_sources
SET last_seen_at = COALESCE(updated_at, scraped_at, NOW())
WHERE last_seen_at IS NULL;

-- ============================================================================
-- HELPER VIEW: Source Status Summary
-- ============================================================================

CREATE OR REPLACE VIEW v_source_status_summary AS
SELECT
    source_module,
    source_type,
    status,
    COUNT(*) as count,
    COUNT(DISTINCT company_id) as unique_companies,
    AVG(data_quality_score) as avg_quality,
    MIN(first_seen_at) as earliest_seen,
    MAX(last_seen_at) as most_recent_seen
FROM business_sources
GROUP BY source_module, source_type, status
ORDER BY source_module, source_type, status;

COMMENT ON VIEW v_source_status_summary IS
'Summary of source records by module, type, and status with quality metrics';

-- ============================================================================
-- HELPER VIEW: Stale Sources (not verified recently)
-- ============================================================================

CREATE OR REPLACE VIEW v_stale_sources AS
SELECT
    bs.source_id,
    bs.company_id,
    c.name as company_name,
    bs.source_type,
    bs.source_module,
    bs.status,
    bs.first_seen_at,
    bs.last_seen_at,
    NOW() - bs.last_seen_at as age,
    EXTRACT(DAY FROM NOW() - bs.last_seen_at) as days_since_check
FROM business_sources bs
JOIN companies c ON bs.company_id = c.id
WHERE bs.last_seen_at < NOW() - INTERVAL '90 days'
ORDER BY bs.last_seen_at ASC;

COMMENT ON VIEW v_stale_sources IS
'Business sources that have not been verified in 90+ days';

-- ============================================================================
-- HELPER FUNCTION: Update Last Seen Timestamp
-- ============================================================================

CREATE OR REPLACE FUNCTION update_source_last_seen(
    p_source_id INT
)
RETURNS VOID AS $$
BEGIN
    UPDATE business_sources
    SET last_seen_at = NOW()
    WHERE source_id = p_source_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_source_last_seen IS
'Update last_seen_at timestamp for a business source (call after successful verification)';

-- ============================================================================
-- HELPER FUNCTION: Set Source Status
-- ============================================================================

CREATE OR REPLACE FUNCTION set_source_status(
    p_source_id INT,
    p_status VARCHAR(50),
    p_reason TEXT DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
    UPDATE business_sources
    SET
        status = p_status,
        status_reason = p_reason,
        last_seen_at = NOW()
    WHERE source_id = p_source_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION set_source_status IS
'Set status and optional reason for a business source';

-- ============================================================================
-- VERIFICATION
-- ============================================================================

DO $$
DECLARE
    column_count INTEGER;
    index_count INTEGER;
    view_count INTEGER;
BEGIN
    -- Check columns were added
    SELECT COUNT(*) INTO column_count
    FROM information_schema.columns
    WHERE table_name = 'business_sources'
    AND column_name IN ('source_module', 'status', 'status_reason', 'first_seen_at', 'last_seen_at', 'raw_payload', 'snapshot_path');

    IF column_count < 7 THEN
        RAISE WARNING 'Migration 021: Not all columns were added (found %, expected 7)', column_count;
    END IF;

    -- Count new indexes
    SELECT COUNT(*) INTO index_count
    FROM pg_indexes
    WHERE tablename = 'business_sources'
    AND indexname LIKE 'idx_business_sources_%'
    AND indexname IN (
        'idx_business_sources_status',
        'idx_business_sources_source_module',
        'idx_business_sources_first_seen',
        'idx_business_sources_last_seen',
        'idx_business_sources_raw_payload',
        'idx_business_sources_status_module'
    );

    -- Count views
    SELECT COUNT(*) INTO view_count
    FROM information_schema.views
    WHERE table_name IN ('v_source_status_summary', 'v_stale_sources');

    RAISE NOTICE 'Migration 021 completed successfully.';
    RAISE NOTICE '  - % new columns added to business_sources', column_count;
    RAISE NOTICE '  - % indexes created', index_count;
    RAISE NOTICE '  - % views created', view_count;
    RAISE NOTICE '  - 2 helper functions created';
END $$;
