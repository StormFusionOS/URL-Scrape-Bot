-- ============================================================================
-- Migration 020: Add Business Sources Table for Multi-Source NAP Tracking
-- ============================================================================
-- Creates business_sources table to track NAP data from multiple sources
-- (YP, Google, Yelp, BBB, Facebook, citations, etc.) for consistency validation.
-- ============================================================================

-- Track this migration
INSERT INTO schema_migrations (version, name, applied_at)
VALUES ('020', 'add_business_sources_table', NOW())
ON CONFLICT (version) DO NOTHING;

-- ============================================================================
-- BUSINESS_SOURCES TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS business_sources (
    -- Primary Key
    source_id SERIAL PRIMARY KEY,

    -- Foreign Key to Company
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,

    -- Source Metadata
    source_type VARCHAR(50) NOT NULL,  -- 'yp', 'google', 'yelp', 'bbb', 'facebook', 'citation'
    source_name VARCHAR(255),           -- 'Yellow Pages', 'Google Business Profile'
    source_url TEXT,                    -- Base URL of source platform
    profile_url TEXT,                   -- Direct link to business profile

    -- NAP Data from this source
    name VARCHAR(500),                  -- Business name from this source
    phone VARCHAR(50),                  -- Raw phone number
    phone_e164 VARCHAR(20),             -- Normalized phone in E.164 format
    address_raw TEXT,                   -- Raw address string
    street VARCHAR(500),                -- Parsed street address
    city VARCHAR(200),                  -- Parsed city
    state VARCHAR(100),                 -- Parsed state/province
    zip_code VARCHAR(20),               -- Parsed ZIP/postal code

    -- Additional Data
    website TEXT,                       -- Website URL from this source
    categories TEXT[],                  -- Business categories/tags (PostgreSQL array)
    rating_value NUMERIC(3, 2),        -- Rating value (e.g., 4.5)
    rating_count INTEGER,               -- Number of reviews
    description TEXT,                   -- Business description

    -- Quality Indicators
    is_verified BOOLEAN DEFAULT FALSE NOT NULL,  -- Owner-verified listing
    listing_status VARCHAR(50),         -- 'claimed', 'unclaimed', 'found', 'needs_manual'
    data_quality_score INTEGER,         -- 0-100 quality score
    confidence_level VARCHAR(20),       -- 'high', 'medium', 'low'

    -- Timestamps
    scraped_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP,

    -- Extended Metadata (JSONB for flexibility)
    metadata JSONB
);

-- ============================================================================
-- INDEXES
-- ============================================================================

-- Foreign key index
CREATE INDEX IF NOT EXISTS idx_business_sources_company_id
ON business_sources(company_id);

-- Source type index for filtering
CREATE INDEX IF NOT EXISTS idx_business_sources_source_type
ON business_sources(source_type);

-- Profile URL for lookups
CREATE INDEX IF NOT EXISTS idx_business_sources_profile_url
ON business_sources(profile_url);

-- Phone index for NAP matching
CREATE INDEX IF NOT EXISTS idx_business_sources_phone_e164
ON business_sources(phone_e164);

-- Location indexes for geographic queries
CREATE INDEX IF NOT EXISTS idx_business_sources_city
ON business_sources(city);

CREATE INDEX IF NOT EXISTS idx_business_sources_state
ON business_sources(state);

CREATE INDEX IF NOT EXISTS idx_business_sources_zip_code
ON business_sources(zip_code);

-- Metadata JSONB index for extended queries
CREATE INDEX IF NOT EXISTS idx_business_sources_metadata
ON business_sources USING GIN (metadata);

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON TABLE business_sources IS
'Tracks business NAP data from multiple sources for consistency validation. One company can have many sources (YP, Google, Yelp, etc.)';

COMMENT ON COLUMN business_sources.source_id IS 'Primary key';
COMMENT ON COLUMN business_sources.company_id IS 'Links to companies table';
COMMENT ON COLUMN business_sources.source_type IS 'Source type: yp, google, yelp, bbb, facebook, citation, etc.';
COMMENT ON COLUMN business_sources.source_name IS 'Human-readable source name';
COMMENT ON COLUMN business_sources.profile_url IS 'Direct link to business profile on this source';
COMMENT ON COLUMN business_sources.phone_e164 IS 'Normalized phone in E.164 format for matching';
COMMENT ON COLUMN business_sources.is_verified IS 'Whether this is an owner-verified listing (higher trust)';
COMMENT ON COLUMN business_sources.data_quality_score IS 'Computed quality score 0-100 based on completeness and verification';
COMMENT ON COLUMN business_sources.metadata IS 'Extended fields, raw data, parsing metadata (JSONB)';

-- ============================================================================
-- HELPER VIEW: NAP Conflict Detection
-- ============================================================================

CREATE OR REPLACE VIEW v_nap_conflicts AS
SELECT
    c.id as company_id,
    c.name as company_name,
    COUNT(DISTINCT bs.source_id) as source_count,
    COUNT(DISTINCT bs.name) as unique_names,
    COUNT(DISTINCT bs.phone_e164) as unique_phones,
    COUNT(DISTINCT bs.street) as unique_streets,
    COUNT(DISTINCT bs.city) as unique_cities,
    CASE
        WHEN COUNT(DISTINCT bs.name) > 1 OR
             COUNT(DISTINCT bs.phone_e164) > 1 OR
             COUNT(DISTINCT bs.street) > 1
        THEN TRUE
        ELSE FALSE
    END as has_conflict,
    ARRAY_AGG(DISTINCT bs.source_name) as sources
FROM companies c
LEFT JOIN business_sources bs ON c.id = bs.company_id
GROUP BY c.id, c.name
HAVING COUNT(DISTINCT bs.source_id) >= 1;

COMMENT ON VIEW v_nap_conflicts IS
'Quick view to identify companies with NAP inconsistencies across multiple sources';

-- ============================================================================
-- HELPER FUNCTION: Calculate Data Quality Score
-- ============================================================================

CREATE OR REPLACE FUNCTION calculate_source_quality_score(
    p_name TEXT,
    p_phone TEXT,
    p_street TEXT,
    p_city TEXT,
    p_state TEXT,
    p_zip TEXT,
    p_website TEXT,
    p_is_verified BOOLEAN,
    p_rating_count INTEGER
)
RETURNS INTEGER AS $$
DECLARE
    score INTEGER := 0;
BEGIN
    -- Base NAP completeness (60 points max)
    IF p_name IS NOT NULL AND LENGTH(p_name) > 0 THEN score := score + 15; END IF;
    IF p_phone IS NOT NULL AND LENGTH(p_phone) > 0 THEN score := score + 15; END IF;
    IF p_street IS NOT NULL AND LENGTH(p_street) > 0 THEN score := score + 10; END IF;
    IF p_city IS NOT NULL AND LENGTH(p_city) > 0 THEN score := score + 10; END IF;
    IF p_state IS NOT NULL AND LENGTH(p_state) > 0 THEN score := score + 5; END IF;
    IF p_zip IS NOT NULL AND LENGTH(p_zip) > 0 THEN score := score + 5; END IF;

    -- Additional data (20 points max)
    IF p_website IS NOT NULL AND LENGTH(p_website) > 0 THEN score := score + 10; END IF;
    IF p_rating_count IS NOT NULL AND p_rating_count > 0 THEN score := score + 10; END IF;

    -- Verification bonus (20 points)
    IF p_is_verified THEN score := score + 20; END IF;

    RETURN score;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION calculate_source_quality_score IS
'Calculates data quality score (0-100) based on completeness and verification status';

-- ============================================================================
-- VERIFICATION
-- ============================================================================

DO $$
DECLARE
    table_exists BOOLEAN;
    index_count INTEGER;
BEGIN
    -- Check table exists
    SELECT EXISTS (
        SELECT FROM information_schema.tables
        WHERE table_name = 'business_sources'
    ) INTO table_exists;

    IF NOT table_exists THEN
        RAISE WARNING 'Migration 020: business_sources table was not created';
        RETURN;
    END IF;

    -- Count indexes
    SELECT COUNT(*) INTO index_count
    FROM pg_indexes
    WHERE tablename = 'business_sources';

    RAISE NOTICE 'Migration 020 completed successfully.';
    RAISE NOTICE '  - business_sources table created';
    RAISE NOTICE '  - % indexes created', index_count;
    RAISE NOTICE '  - v_nap_conflicts view created';
    RAISE NOTICE '  - calculate_source_quality_score() function created';
END $$;
