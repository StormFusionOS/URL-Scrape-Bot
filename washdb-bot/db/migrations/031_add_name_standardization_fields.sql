-- Migration: Add name standardization fields for citation lookup improvement
-- Date: 2025-12-08
-- Purpose: Enable better business name matching for citation scraper
--
-- Problem: Companies with short/generic names like "Hydro" fail to match in citation searches.
-- Solution: Add standardized_name, parsed location fields, and quality scoring.

-- ============================================================================
-- Add Name Standardization Fields to companies table
-- ============================================================================

-- Standardized name (e.g., "Hydro Soft Wash NE" instead of "Hydro")
ALTER TABLE companies ADD COLUMN IF NOT EXISTS standardized_name TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS standardized_name_source VARCHAR(50);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS standardized_name_confidence NUMERIC(3,2);

-- Parsed location fields (extracted from address or inferred)
ALTER TABLE companies ADD COLUMN IF NOT EXISTS city VARCHAR(100);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS state VARCHAR(50);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS zip_code VARCHAR(20);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS location_source VARCHAR(50);

-- Name quality tracking
ALTER TABLE companies ADD COLUMN IF NOT EXISTS name_length_flag BOOLEAN DEFAULT FALSE;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS name_quality_score INTEGER DEFAULT 50;

-- Add comments for documentation
COMMENT ON COLUMN companies.standardized_name IS 'Full business name for citation searches (e.g., "Hydro Soft Wash NE")';
COMMENT ON COLUMN companies.standardized_name_source IS 'How name was standardized: llm, website, domain, original';
COMMENT ON COLUMN companies.standardized_name_confidence IS 'Confidence score 0.00-1.00 for standardized name';
COMMENT ON COLUMN companies.city IS 'City parsed from address or inferred from service area';
COMMENT ON COLUMN companies.state IS 'State parsed from address or inferred';
COMMENT ON COLUMN companies.zip_code IS 'ZIP code parsed from address';
COMMENT ON COLUMN companies.location_source IS 'How location was determined: address_parse, llm, directory';
COMMENT ON COLUMN companies.name_length_flag IS 'TRUE if original name < 10 chars (needs standardization)';
COMMENT ON COLUMN companies.name_quality_score IS 'Quality score 0-100 based on length, specificity, location';

-- ============================================================================
-- Create Indexes for efficient queries
-- ============================================================================

-- Index for citation crawler lookups using standardized name
CREATE INDEX IF NOT EXISTS idx_companies_standardized_name ON companies(standardized_name);

-- Composite index for location-based searches
CREATE INDEX IF NOT EXISTS idx_companies_city_state ON companies(city, state);

-- Index for finding companies that need standardization
CREATE INDEX IF NOT EXISTS idx_companies_name_length_flag ON companies(name_length_flag) WHERE name_length_flag = TRUE;

-- Index for quality-based filtering
CREATE INDEX IF NOT EXISTS idx_companies_name_quality_score ON companies(name_quality_score);

-- ============================================================================
-- Backfill name_length_flag for existing data
-- ============================================================================

-- Mark companies with short names for processing
UPDATE companies
SET name_length_flag = TRUE
WHERE name IS NOT NULL AND LENGTH(name) < 10;

-- Set default quality score of 50 for all (will be recalculated by backfill script)
UPDATE companies
SET name_quality_score = 50
WHERE name_quality_score IS NULL;

-- ============================================================================
-- Record migration in schema_migrations
-- ============================================================================

INSERT INTO schema_migrations (version, description, applied_at)
VALUES (
    31,
    'Add name standardization fields (standardized_name, city, state, zip_code, quality_score)',
    NOW()
)
ON CONFLICT (version) DO NOTHING;
