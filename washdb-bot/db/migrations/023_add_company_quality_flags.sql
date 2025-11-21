-- ============================================================================
-- Migration 023: Add Company Quality Flags
-- ============================================================================
-- Adds quality and completeness tracking fields to the companies table.
-- Enables quick filtering and sorting by data quality, source coverage,
-- and NAP consistency.
--
-- New fields:
-- - nap_conflict: Boolean flag for NAP disagreement across sources
-- - source_count: Number of business_sources for this company
-- - has_website: Has company website
-- - has_google_profile: Has Google Business Profile
-- - has_yelp_profile: Has Yelp listing
-- - quality_score: Overall data quality score (0-100)
-- - last_validated_at: Most recent validation timestamp
-- - field_evidence: JSONB storing field-level evidence and conflicts
-- ============================================================================

-- Track this migration
INSERT INTO schema_migrations (version, name, applied_at)
VALUES ('023', 'add_company_quality_flags', NOW())
ON CONFLICT (version) DO NOTHING;

-- ============================================================================
-- ADD NEW COLUMNS TO companies TABLE
-- ============================================================================

-- NAP conflict flag
ALTER TABLE companies
ADD COLUMN IF NOT EXISTS nap_conflict BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN companies.nap_conflict IS
'TRUE if high-trust sources disagree on NAP (Name-Address-Phone) data';

-- Source count (number of business_sources records)
ALTER TABLE companies
ADD COLUMN IF NOT EXISTS source_count INTEGER DEFAULT 0;

COMMENT ON COLUMN companies.source_count IS
'Number of business_sources records for this company (computed periodically)';

-- Has website flag
ALTER TABLE companies
ADD COLUMN IF NOT EXISTS has_website BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN companies.has_website IS
'TRUE if company has a working website URL';

-- Has Google profile flag
ALTER TABLE companies
ADD COLUMN IF NOT EXISTS has_google_profile BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN companies.has_google_profile IS
'TRUE if company has a Google Business Profile in business_sources';

-- Has Yelp profile flag
ALTER TABLE companies
ADD COLUMN IF NOT EXISTS has_yelp_profile BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN companies.has_yelp_profile IS
'TRUE if company has a Yelp listing in business_sources';

-- Overall quality score
ALTER TABLE companies
ADD COLUMN IF NOT EXISTS quality_score INTEGER;

COMMENT ON COLUMN companies.quality_score IS
'Overall data quality score (0-100) computed from source coverage, NAP consistency, and completeness';

-- Last validation timestamp
ALTER TABLE companies
ADD COLUMN IF NOT EXISTS last_validated_at TIMESTAMP;

COMMENT ON COLUMN companies.last_validated_at IS
'When this company was last validated/scored (set by compute_evidence script)';

-- Field-level evidence and conflicts
ALTER TABLE companies
ADD COLUMN IF NOT EXISTS field_evidence JSONB;

COMMENT ON COLUMN companies.field_evidence IS
'Field-level evidence summary: canonical values, agreement ratios, disagreeing sources, best source IDs';

-- ============================================================================
-- CREATE INDEXES FOR NEW COLUMNS
-- ============================================================================

-- NAP conflict index for filtering
CREATE INDEX IF NOT EXISTS idx_companies_nap_conflict
ON companies(nap_conflict);

-- Source count index for sorting/filtering
CREATE INDEX IF NOT EXISTS idx_companies_source_count
ON companies(source_count DESC);

-- Quality score index for sorting
CREATE INDEX IF NOT EXISTS idx_companies_quality_score
ON companies(quality_score DESC NULLS LAST);

-- Profile presence composite index
CREATE INDEX IF NOT EXISTS idx_companies_profiles
ON companies(has_google_profile, has_yelp_profile, has_website);

-- Last validated index for stale detection
CREATE INDEX IF NOT EXISTS idx_companies_last_validated
ON companies(last_validated_at DESC NULLS LAST);

-- Field evidence GIN index for JSONB queries
CREATE INDEX IF NOT EXISTS idx_companies_field_evidence
ON companies USING GIN (field_evidence);

-- ============================================================================
-- UPDATE EXISTING RECORDS WITH COMPUTED VALUES
-- ============================================================================

-- Compute source_count for existing companies
UPDATE companies c
SET source_count = (
    SELECT COUNT(*)
    FROM business_sources bs
    WHERE bs.company_id = c.id
);

-- Set has_website based on website column
UPDATE companies
SET has_website = (website IS NOT NULL AND LENGTH(website) > 0);

-- Set has_google_profile based on business_sources
UPDATE companies c
SET has_google_profile = EXISTS (
    SELECT 1
    FROM business_sources bs
    WHERE bs.company_id = c.id
    AND bs.source_type IN ('google', 'google_business')
);

-- Set has_yelp_profile based on business_sources
UPDATE companies c
SET has_yelp_profile = EXISTS (
    SELECT 1
    FROM business_sources bs
    WHERE bs.company_id = c.id
    AND bs.source_type = 'yelp'
);

-- ============================================================================
-- HELPER VIEW: Company Quality Dashboard
-- ============================================================================

CREATE OR REPLACE VIEW v_company_quality_dashboard AS
SELECT
    c.id as company_id,
    c.name,
    c.domain,
    c.phone,
    c.source_count,
    c.quality_score,
    c.nap_conflict,
    c.has_website,
    c.has_google_profile,
    c.has_yelp_profile,
    c.last_validated_at,
    CASE
        WHEN c.source_count = 0 THEN 'no_sources'
        WHEN c.source_count = 1 THEN 'single_source'
        WHEN c.source_count >= 2 AND c.source_count < 5 THEN 'multiple_sources'
        WHEN c.source_count >= 5 THEN 'well_sourced'
    END as source_coverage,
    CASE
        WHEN c.quality_score >= 80 THEN 'high'
        WHEN c.quality_score >= 60 THEN 'medium'
        WHEN c.quality_score >= 40 THEN 'low'
        ELSE 'very_low'
    END as quality_tier,
    CASE
        WHEN c.nap_conflict THEN 'conflict'
        WHEN c.source_count > 1 THEN 'consistent'
        ELSE 'unverified'
    END as nap_status,
    c.created_at,
    NOW() - c.last_validated_at as validation_age
FROM companies c
ORDER BY c.quality_score DESC NULLS LAST, c.source_count DESC;

COMMENT ON VIEW v_company_quality_dashboard IS
'Company quality overview with computed tiers and status categories';

-- ============================================================================
-- HELPER VIEW: Companies Needing Validation
-- ============================================================================

CREATE OR REPLACE VIEW v_companies_needing_validation AS
SELECT
    c.id as company_id,
    c.name,
    c.domain,
    c.source_count,
    c.quality_score,
    c.last_validated_at,
    NOW() - c.last_validated_at as days_since_validation,
    CASE
        WHEN c.last_validated_at IS NULL THEN 'never_validated'
        WHEN c.last_validated_at < NOW() - INTERVAL '30 days' THEN 'stale'
        WHEN c.last_validated_at < NOW() - INTERVAL '7 days' THEN 'aging'
        ELSE 'recent'
    END as validation_status
FROM companies c
WHERE
    c.last_validated_at IS NULL
    OR c.last_validated_at < NOW() - INTERVAL '30 days'
ORDER BY c.last_validated_at NULLS FIRST, c.source_count DESC;

COMMENT ON VIEW v_companies_needing_validation IS
'Companies that have never been validated or are stale (30+ days)';

-- ============================================================================
-- HELPER VIEW: NAP Conflict Summary
-- ============================================================================

CREATE OR REPLACE VIEW v_nap_conflict_summary AS
SELECT
    c.id as company_id,
    c.name,
    c.domain,
    c.phone as canonical_phone,
    c.address as canonical_address,
    c.source_count,
    c.field_evidence,
    bs_counts.source_types,
    bs_counts.disagreeing_count
FROM companies c
LEFT JOIN (
    SELECT
        company_id,
        ARRAY_AGG(DISTINCT source_type) as source_types,
        COUNT(DISTINCT name) as name_variations,
        COUNT(DISTINCT phone) as phone_variations,
        COUNT(DISTINCT street) as street_variations,
        GREATEST(
            COUNT(DISTINCT name),
            COUNT(DISTINCT phone),
            COUNT(DISTINCT street)
        ) - 1 as disagreeing_count
    FROM business_sources
    WHERE name IS NOT NULL OR phone IS NOT NULL OR street IS NOT NULL
    GROUP BY company_id
) bs_counts ON c.id = bs_counts.company_id
WHERE c.nap_conflict = TRUE
ORDER BY bs_counts.disagreeing_count DESC, c.source_count DESC;

COMMENT ON VIEW v_nap_conflict_summary IS
'Details of companies with NAP conflicts showing source types and variation counts';

-- ============================================================================
-- HELPER FUNCTION: Compute Quality Score for Company
-- ============================================================================

CREATE OR REPLACE FUNCTION compute_company_quality_score(
    p_company_id INT
)
RETURNS INT AS $$
DECLARE
    v_score INT := 0;
    v_source_count INT;
    v_has_website BOOLEAN;
    v_has_google BOOLEAN;
    v_has_yelp BOOLEAN;
    v_nap_conflict BOOLEAN;
    v_avg_source_quality FLOAT;
BEGIN
    -- Get company data
    SELECT
        source_count,
        has_website,
        has_google_profile,
        has_yelp_profile,
        nap_conflict
    INTO
        v_source_count,
        v_has_website,
        v_has_google,
        v_has_yelp,
        v_nap_conflict
    FROM companies
    WHERE id = p_company_id;

    -- Source coverage score (40 points max)
    IF v_source_count >= 5 THEN
        v_score := v_score + 40;
    ELSIF v_source_count >= 3 THEN
        v_score := v_score + 30;
    ELSIF v_source_count >= 2 THEN
        v_score := v_score + 20;
    ELSIF v_source_count >= 1 THEN
        v_score := v_score + 10;
    END IF;

    -- Profile presence score (30 points max)
    IF v_has_website THEN v_score := v_score + 10; END IF;
    IF v_has_google THEN v_score := v_score + 10; END IF;
    IF v_has_yelp THEN v_score := v_score + 10; END IF;

    -- Average source quality (20 points max)
    SELECT AVG(data_quality_score) INTO v_avg_source_quality
    FROM business_sources
    WHERE company_id = p_company_id
    AND data_quality_score IS NOT NULL;

    IF v_avg_source_quality IS NOT NULL THEN
        v_score := v_score + (v_avg_source_quality / 5)::INT;  -- Convert 0-100 to 0-20
    END IF;

    -- NAP consistency (10 points max, or -10 penalty for conflict)
    IF v_nap_conflict THEN
        v_score := v_score - 10;
    ELSIF v_source_count > 1 THEN
        v_score := v_score + 10;
    END IF;

    -- Clamp score to 0-100 range
    v_score := GREATEST(0, LEAST(100, v_score));

    RETURN v_score;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION compute_company_quality_score IS
'Compute overall quality score for a company (0-100) based on sources, profiles, and NAP consistency';

-- ============================================================================
-- HELPER FUNCTION: Refresh Company Quality Flags
-- ============================================================================

CREATE OR REPLACE FUNCTION refresh_company_quality_flags(
    p_company_id INT
)
RETURNS VOID AS $$
BEGIN
    UPDATE companies c
    SET
        source_count = (
            SELECT COUNT(*)
            FROM business_sources bs
            WHERE bs.company_id = p_company_id
        ),
        has_google_profile = EXISTS (
            SELECT 1
            FROM business_sources bs
            WHERE bs.company_id = p_company_id
            AND bs.source_type IN ('google', 'google_business')
        ),
        has_yelp_profile = EXISTS (
            SELECT 1
            FROM business_sources bs
            WHERE bs.company_id = p_company_id
            AND bs.source_type = 'yelp'
        ),
        quality_score = compute_company_quality_score(p_company_id),
        last_validated_at = NOW()
    WHERE c.id = p_company_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION refresh_company_quality_flags IS
'Refresh all quality flags for a specific company (call after updating business_sources)';

-- ============================================================================
-- VERIFICATION
-- ============================================================================

DO $$
DECLARE
    column_count INTEGER;
    index_count INTEGER;
    view_count INTEGER;
    function_count INTEGER;
BEGIN
    -- Check columns were added
    SELECT COUNT(*) INTO column_count
    FROM information_schema.columns
    WHERE table_name = 'companies'
    AND column_name IN (
        'nap_conflict', 'source_count', 'has_website', 'has_google_profile',
        'has_yelp_profile', 'quality_score', 'last_validated_at', 'field_evidence'
    );

    IF column_count < 8 THEN
        RAISE WARNING 'Migration 023: Not all columns were added (found %, expected 8)', column_count;
    END IF;

    -- Count new indexes
    SELECT COUNT(*) INTO index_count
    FROM pg_indexes
    WHERE tablename = 'companies'
    AND indexname LIKE 'idx_companies_%'
    AND indexname IN (
        'idx_companies_nap_conflict',
        'idx_companies_source_count',
        'idx_companies_quality_score',
        'idx_companies_profiles',
        'idx_companies_last_validated',
        'idx_companies_field_evidence'
    );

    -- Count views
    SELECT COUNT(*) INTO view_count
    FROM information_schema.views
    WHERE table_name LIKE 'v_company%' OR table_name LIKE 'v_nap%' OR table_name LIKE 'v_companies%';

    -- Count functions
    SELECT COUNT(*) INTO function_count
    FROM information_schema.routines
    WHERE routine_name IN ('compute_company_quality_score', 'refresh_company_quality_flags');

    RAISE NOTICE 'Migration 023 completed successfully.';
    RAISE NOTICE '  - % new columns added to companies table', column_count;
    RAISE NOTICE '  - % indexes created', index_count;
    RAISE NOTICE '  - % views created', view_count;
    RAISE NOTICE '  - % functions created', function_count;
    RAISE NOTICE '  - Quality flags computed for existing companies';
END $$;
