-- ============================================================================
-- Migration 024: Create Company Conflicts Table
-- ============================================================================
-- Creates table for tracking potential duplicate companies and entity
-- resolution conflicts.
--
-- Conflict types:
-- - phone_match_name_mismatch: Same phone, different business names (shared number/call center)
-- - domain_match: Same domain but potentially different company records
-- - fuzzy_name_match: Very similar names at similar locations
-- - manual_review: Flagged for manual review
-- ============================================================================

-- Track this migration
INSERT INTO schema_migrations (version, name, applied_at)
VALUES ('024', 'create_company_conflicts_table', NOW())
ON CONFLICT (version) DO NOTHING;

-- ============================================================================
-- CREATE company_conflicts TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS company_conflicts (
    -- Primary Key
    conflict_id SERIAL PRIMARY KEY,

    -- Companies involved in conflict
    company_id_1 INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    company_id_2 INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,

    -- Conflict details
    conflict_type VARCHAR(50) NOT NULL,  -- phone_match_name_mismatch, domain_match, fuzzy_name_match, manual_review
    confidence_score FLOAT,  -- 0-1 confidence that these are actually different businesses
    match_score FLOAT,  -- 0-1 score for how similar they are

    -- Evidence
    matching_fields JSONB,  -- Which fields match (domain, phone, address, etc.)
    conflicting_fields JSONB,  -- Which fields differ
    evidence JSONB,  -- Detailed matching evidence

    -- Resolution
    resolution_status VARCHAR(50) DEFAULT 'pending',  -- pending, duplicate, not_duplicate, needs_review
    resolution_notes TEXT,
    resolved_by VARCHAR(100),
    resolved_at TIMESTAMP,

    -- Tracking
    detected_at TIMESTAMP DEFAULT NOW() NOT NULL,
    last_checked_at TIMESTAMP DEFAULT NOW(),

    -- Constraints
    CONSTRAINT chk_different_companies CHECK (company_id_1 != company_id_2),
    CONSTRAINT chk_ordered_ids CHECK (company_id_1 < company_id_2),  -- Prevent duplicate pairs
    CONSTRAINT chk_confidence_range CHECK (confidence_score >= 0 AND confidence_score <= 1),
    CONSTRAINT chk_match_range CHECK (match_score >= 0 AND match_score <= 1)
);

-- ============================================================================
-- INDEXES
-- ============================================================================

-- Foreign key indexes
CREATE INDEX IF NOT EXISTS idx_company_conflicts_company1
ON company_conflicts(company_id_1);

CREATE INDEX IF NOT EXISTS idx_company_conflicts_company2
ON company_conflicts(company_id_2);

-- Unique constraint to prevent duplicate conflict records
CREATE UNIQUE INDEX IF NOT EXISTS idx_company_conflicts_unique_pair
ON company_conflicts(company_id_1, company_id_2);

-- Conflict type index
CREATE INDEX IF NOT EXISTS idx_company_conflicts_type
ON company_conflicts(conflict_type);

-- Resolution status index
CREATE INDEX IF NOT EXISTS idx_company_conflicts_resolution
ON company_conflicts(resolution_status);

-- Composite index for unresolved conflicts
CREATE INDEX IF NOT EXISTS idx_company_conflicts_pending
ON company_conflicts(resolution_status, detected_at DESC)
WHERE resolution_status = 'pending';

-- Confidence score index for prioritization
CREATE INDEX IF NOT EXISTS idx_company_conflicts_confidence
ON company_conflicts(confidence_score DESC NULLS LAST);

-- JSONB indexes for evidence queries
CREATE INDEX IF NOT EXISTS idx_company_conflicts_matching_fields
ON company_conflicts USING GIN (matching_fields);

CREATE INDEX IF NOT EXISTS idx_company_conflicts_conflicting_fields
ON company_conflicts USING GIN (conflicting_fields);

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON TABLE company_conflicts IS
'Tracks potential duplicate companies and entity resolution conflicts for deduplication';

COMMENT ON COLUMN company_conflicts.conflict_id IS 'Primary key';
COMMENT ON COLUMN company_conflicts.company_id_1 IS 'First company in conflict pair (lower ID)';
COMMENT ON COLUMN company_conflicts.company_id_2 IS 'Second company in conflict pair (higher ID)';
COMMENT ON COLUMN company_conflicts.conflict_type IS 'Type: phone_match_name_mismatch, domain_match, fuzzy_name_match, manual_review';
COMMENT ON COLUMN company_conflicts.confidence_score IS 'Confidence (0-1) that these are actually different businesses';
COMMENT ON COLUMN company_conflicts.match_score IS 'Similarity score (0-1) indicating how similar the companies are';
COMMENT ON COLUMN company_conflicts.matching_fields IS 'JSONB: Which fields match between companies';
COMMENT ON COLUMN company_conflicts.conflicting_fields IS 'JSONB: Which fields differ between companies';
COMMENT ON COLUMN company_conflicts.evidence IS 'JSONB: Detailed matching evidence and reasoning';
COMMENT ON COLUMN company_conflicts.resolution_status IS 'Status: pending, duplicate, not_duplicate, needs_review';
COMMENT ON COLUMN company_conflicts.detected_at IS 'When conflict was first detected';

-- ============================================================================
-- HELPER VIEW: Unresolved Conflicts Summary
-- ============================================================================

CREATE OR REPLACE VIEW v_unresolved_conflicts AS
SELECT
    cc.conflict_id,
    cc.conflict_type,
    cc.confidence_score,
    cc.match_score,
    cc.detected_at,
    c1.id as company1_id,
    c1.name as company1_name,
    c1.domain as company1_domain,
    c1.phone as company1_phone,
    c2.id as company2_id,
    c2.name as company2_name,
    c2.domain as company2_domain,
    c2.phone as company2_phone,
    cc.matching_fields,
    cc.conflicting_fields
FROM company_conflicts cc
JOIN companies c1 ON cc.company_id_1 = c1.id
JOIN companies c2 ON cc.company_id_2 = c2.id
WHERE cc.resolution_status = 'pending'
ORDER BY cc.confidence_score DESC NULLS LAST, cc.detected_at DESC;

COMMENT ON VIEW v_unresolved_conflicts IS
'Shows pending conflict pairs with company details for manual review';

-- ============================================================================
-- HELPER VIEW: Conflict Statistics by Type
-- ============================================================================

CREATE OR REPLACE VIEW v_conflict_stats_by_type AS
SELECT
    conflict_type,
    COUNT(*) as total_conflicts,
    COUNT(*) FILTER (WHERE resolution_status = 'pending') as pending_count,
    COUNT(*) FILTER (WHERE resolution_status = 'duplicate') as duplicate_count,
    COUNT(*) FILTER (WHERE resolution_status = 'not_duplicate') as not_duplicate_count,
    COUNT(*) FILTER (WHERE resolution_status = 'needs_review') as needs_review_count,
    AVG(confidence_score) as avg_confidence,
    AVG(match_score) as avg_match_score
FROM company_conflicts
GROUP BY conflict_type
ORDER BY total_conflicts DESC;

COMMENT ON VIEW v_conflict_stats_by_type IS
'Conflict statistics grouped by type with resolution breakdown';

-- ============================================================================
-- HELPER FUNCTION: Mark Conflict as Duplicate
-- ============================================================================

CREATE OR REPLACE FUNCTION resolve_conflict_as_duplicate(
    p_conflict_id INT,
    p_keep_company_id INT,
    p_merge_company_id INT,
    p_resolved_by VARCHAR(100) DEFAULT NULL,
    p_notes TEXT DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
    -- Update conflict record
    UPDATE company_conflicts
    SET
        resolution_status = 'duplicate',
        resolved_by = p_resolved_by,
        resolved_at = NOW(),
        resolution_notes = p_notes,
        evidence = jsonb_set(
            COALESCE(evidence, '{}'::jsonb),
            '{resolution}',
            jsonb_build_object(
                'keep_company_id', p_keep_company_id,
                'merge_company_id', p_merge_company_id,
                'resolved_at', NOW()
            )
        )
    WHERE conflict_id = p_conflict_id;

    -- Note: Actual company merging should be done separately
    -- This just marks the conflict as resolved
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION resolve_conflict_as_duplicate IS
'Mark a conflict as duplicate and record which company to keep (does not perform merge)';

-- ============================================================================
-- HELPER FUNCTION: Mark Conflict as Not Duplicate
-- ============================================================================

CREATE OR REPLACE FUNCTION resolve_conflict_as_distinct(
    p_conflict_id INT,
    p_resolved_by VARCHAR(100) DEFAULT NULL,
    p_notes TEXT DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
    UPDATE company_conflicts
    SET
        resolution_status = 'not_duplicate',
        resolved_by = p_resolved_by,
        resolved_at = NOW(),
        resolution_notes = p_notes
    WHERE conflict_id = p_conflict_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION resolve_conflict_as_distinct IS
'Mark a conflict as NOT duplicate (companies are legitimately different)';

-- ============================================================================
-- HELPER FUNCTION: Get Conflicts for Company
-- ============================================================================

CREATE OR REPLACE FUNCTION get_conflicts_for_company(
    p_company_id INT,
    p_resolution_status VARCHAR(50) DEFAULT NULL
)
RETURNS TABLE (
    conflict_id INT,
    other_company_id INT,
    other_company_name VARCHAR(255),
    conflict_type VARCHAR(50),
    confidence_score FLOAT,
    match_score FLOAT,
    resolution_status VARCHAR(50),
    detected_at TIMESTAMP
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        cc.conflict_id,
        CASE
            WHEN cc.company_id_1 = p_company_id THEN cc.company_id_2
            ELSE cc.company_id_1
        END as other_company_id,
        c.name as other_company_name,
        cc.conflict_type,
        cc.confidence_score,
        cc.match_score,
        cc.resolution_status,
        cc.detected_at
    FROM company_conflicts cc
    JOIN companies c ON (
        c.id = CASE
            WHEN cc.company_id_1 = p_company_id THEN cc.company_id_2
            ELSE cc.company_id_1
        END
    )
    WHERE
        (cc.company_id_1 = p_company_id OR cc.company_id_2 = p_company_id)
        AND (p_resolution_status IS NULL OR cc.resolution_status = p_resolution_status)
    ORDER BY cc.confidence_score DESC NULLS LAST, cc.detected_at DESC;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_conflicts_for_company IS
'Get all conflicts involving a specific company, optionally filtered by resolution status';

-- ============================================================================
-- VERIFICATION
-- ============================================================================

DO $$
DECLARE
    table_exists BOOLEAN;
    index_count INTEGER;
    view_count INTEGER;
    function_count INTEGER;
BEGIN
    -- Check table exists
    SELECT EXISTS (
        SELECT FROM information_schema.tables
        WHERE table_name = 'company_conflicts'
    ) INTO table_exists;

    IF NOT table_exists THEN
        RAISE WARNING 'Migration 024: company_conflicts table was not created';
        RETURN;
    END IF;

    -- Count indexes
    SELECT COUNT(*) INTO index_count
    FROM pg_indexes
    WHERE tablename = 'company_conflicts';

    -- Count views
    SELECT COUNT(*) INTO view_count
    FROM information_schema.views
    WHERE table_name LIKE 'v_%conflict%';

    -- Count functions
    SELECT COUNT(*) INTO function_count
    FROM information_schema.routines
    WHERE routine_name LIKE '%conflict%';

    RAISE NOTICE 'Migration 024 completed successfully.';
    RAISE NOTICE '  - company_conflicts table created';
    RAISE NOTICE '  - % indexes created', index_count;
    RAISE NOTICE '  - % views created', view_count;
    RAISE NOTICE '  - % functions created', function_count;
END $$;
