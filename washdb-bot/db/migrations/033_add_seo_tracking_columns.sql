-- Migration: 033_add_seo_tracking_columns.sql
-- Description: Add SEO module tracking flags to companies table for background job system
-- Date: 2025-12-18

-- Add overall SEO tracking columns
ALTER TABLE companies ADD COLUMN IF NOT EXISTS seo_initial_complete BOOLEAN DEFAULT FALSE;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS seo_last_full_scrape TIMESTAMP;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS seo_next_refresh_due TIMESTAMP;

-- Add individual module flags (for granular tracking)
ALTER TABLE companies ADD COLUMN IF NOT EXISTS seo_technical_audit_done BOOLEAN DEFAULT FALSE;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS seo_core_vitals_done BOOLEAN DEFAULT FALSE;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS seo_backlinks_done BOOLEAN DEFAULT FALSE;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS seo_citations_done BOOLEAN DEFAULT FALSE;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS seo_competitors_done BOOLEAN DEFAULT FALSE;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS seo_serp_done BOOLEAN DEFAULT FALSE;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS seo_autocomplete_done BOOLEAN DEFAULT FALSE;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS seo_keyword_intel_done BOOLEAN DEFAULT FALSE;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS seo_competitive_analysis_done BOOLEAN DEFAULT FALSE;

-- Create partial index for efficient job queries (only eligible companies)
CREATE INDEX IF NOT EXISTS idx_companies_seo_eligible
ON companies(verified, standardized_name)
WHERE verified = true AND standardized_name IS NOT NULL;

-- Create index for refresh scheduling queries
CREATE INDEX IF NOT EXISTS idx_companies_seo_refresh
ON companies(seo_next_refresh_due)
WHERE seo_initial_complete = true;

-- Create index for incomplete initial scrapes
CREATE INDEX IF NOT EXISTS idx_companies_seo_incomplete
ON companies(company_id)
WHERE verified = true
  AND standardized_name IS NOT NULL
  AND seo_initial_complete = false;

COMMENT ON COLUMN companies.seo_initial_complete IS 'True when all 9 SEO modules have run at least once';
COMMENT ON COLUMN companies.seo_last_full_scrape IS 'Timestamp of last complete SEO scrape';
COMMENT ON COLUMN companies.seo_next_refresh_due IS 'When quarterly refresh should run (90 days after last scrape)';
COMMENT ON COLUMN companies.seo_technical_audit_done IS 'TechnicalAuditor module completed';
COMMENT ON COLUMN companies.seo_core_vitals_done IS 'CoreWebVitals module completed';
COMMENT ON COLUMN companies.seo_backlinks_done IS 'BacklinkCrawler module completed';
COMMENT ON COLUMN companies.seo_citations_done IS 'CitationCrawler module completed';
COMMENT ON COLUMN companies.seo_competitors_done IS 'CompetitorCrawler module completed';
COMMENT ON COLUMN companies.seo_serp_done IS 'SerpScraper module completed';
COMMENT ON COLUMN companies.seo_autocomplete_done IS 'AutocompleteScraper module completed';
COMMENT ON COLUMN companies.seo_keyword_intel_done IS 'KeywordIntelligence module completed';
COMMENT ON COLUMN companies.seo_competitive_analysis_done IS 'CompetitiveAnalysis module completed';
