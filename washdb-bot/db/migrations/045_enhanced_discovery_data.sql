-- Migration: Enhanced Discovery Data for SEO Modules
-- Created: 2026-01-01
-- Purpose: Add columns to preserve Google data that was being extracted but discarded,
--          and create discovery_citations table for no-website listings

-- ============================================================================
-- Phase 1: Add Google-specific columns to companies table
-- ============================================================================

-- Google Place ID (unique identifier for deduplication and future updates)
ALTER TABLE companies ADD COLUMN IF NOT EXISTS google_place_id VARCHAR(255);

-- Google price range (e.g., "$", "$$", "$$$")
ALTER TABLE companies ADD COLUMN IF NOT EXISTS google_price_range VARCHAR(10);

-- Google Business Profile URL (direct link to GMB)
ALTER TABLE companies ADD COLUMN IF NOT EXISTS google_business_url TEXT;

-- Google hours as structured JSON (day-by-day breakdown)
ALTER TABLE companies ADD COLUMN IF NOT EXISTS google_hours JSONB;

-- Google category from search results
ALTER TABLE companies ADD COLUMN IF NOT EXISTS google_category VARCHAR(255);

-- Index for place_id deduplication lookups
CREATE INDEX IF NOT EXISTS idx_companies_google_place_id ON companies(google_place_id) WHERE google_place_id IS NOT NULL;

-- ============================================================================
-- Phase 2: Create discovery_citations table for no-website listings
-- ============================================================================

CREATE TABLE IF NOT EXISTS discovery_citations (
    id SERIAL PRIMARY KEY,

    -- Source tracking
    source VARCHAR(50) NOT NULL,  -- 'google_maps', 'yellowpages', 'yelp'

    -- Business information
    business_name VARCHAR(500) NOT NULL,
    phone VARCHAR(50),
    address TEXT,
    city VARCHAR(100),
    state VARCHAR(50),
    zip VARCHAR(20),

    -- Source-specific identifiers
    place_id VARCHAR(255),  -- Google place_id
    profile_url TEXT,       -- Link back to directory listing

    -- Business details
    category VARCHAR(200),
    rating DECIMAL(2,1),
    reviews_count INTEGER,
    hours JSONB,
    price_range VARCHAR(10),

    -- Timestamps
    discovered_at TIMESTAMP DEFAULT NOW(),

    -- Matching to companies
    matched_company_id INTEGER REFERENCES companies(id),
    matched_at TIMESTAMP,
    match_confidence DECIMAL(3,2),
    match_method VARCHAR(50)  -- 'phone', 'name_fuzzy', 'address'
);

-- Indexes for discovery_citations
CREATE INDEX IF NOT EXISTS idx_discovery_citations_phone ON discovery_citations(phone) WHERE phone IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_discovery_citations_place_id ON discovery_citations(place_id) WHERE place_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_discovery_citations_source ON discovery_citations(source);
CREATE INDEX IF NOT EXISTS idx_discovery_citations_unmatched ON discovery_citations(matched_company_id) WHERE matched_company_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_discovery_citations_state ON discovery_citations(state);

-- Unique constraints to prevent duplicates
CREATE UNIQUE INDEX IF NOT EXISTS idx_discovery_citations_source_place_id
    ON discovery_citations(source, place_id) WHERE place_id IS NOT NULL;

-- ============================================================================
-- Phase 3: Add YP-specific enhancement columns (for future use)
-- ============================================================================

-- Years in business (from YP badge)
ALTER TABLE companies ADD COLUMN IF NOT EXISTS years_in_business INTEGER;

-- Certifications/accreditations as JSON array
ALTER TABLE companies ADD COLUMN IF NOT EXISTS certifications JSONB;

-- Social media links as JSON object
ALTER TABLE companies ADD COLUMN IF NOT EXISTS social_links JSONB;

-- YP photo count
ALTER TABLE companies ADD COLUMN IF NOT EXISTS yp_photo_count INTEGER;

-- ============================================================================
-- Comments
-- ============================================================================
COMMENT ON COLUMN companies.google_place_id IS 'Google Maps Place ID for deduplication and future updates';
COMMENT ON COLUMN companies.google_price_range IS 'Google price range indicator ($, $$, $$$, $$$$)';
COMMENT ON COLUMN companies.google_business_url IS 'Direct URL to Google Business Profile';
COMMENT ON COLUMN companies.google_hours IS 'Business hours from Google as structured JSON';
COMMENT ON COLUMN companies.google_category IS 'Primary business category from Google Maps';
COMMENT ON COLUMN companies.years_in_business IS 'Years in business from YP badge';
COMMENT ON COLUMN companies.certifications IS 'Certifications/accreditations (BBB, licensed, insured, etc.)';
COMMENT ON COLUMN companies.social_links IS 'Social media links (facebook, instagram, etc.)';
COMMENT ON TABLE discovery_citations IS 'Citations from directories for businesses without websites (for NAP validation)';
