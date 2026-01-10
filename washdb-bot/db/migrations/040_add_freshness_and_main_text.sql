-- Migration 040: Add freshness metadata and main_text storage
-- Per scraper-fixes.md items #8 and #9

-- Add freshness columns to competitor_pages
ALTER TABLE competitor_pages ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMP;
ALTER TABLE competitor_pages ADD COLUMN IF NOT EXISTS crawl_age_bucket VARCHAR(20) DEFAULT 'unknown';
ALTER TABLE competitor_pages ADD COLUMN IF NOT EXISTS data_confidence NUMERIC(3,2) DEFAULT 1.0;
ALTER TABLE competitor_pages ADD COLUMN IF NOT EXISTS main_text TEXT;

-- Add check constraint for crawl_age_bucket
ALTER TABLE competitor_pages DROP CONSTRAINT IF EXISTS check_crawl_age_bucket;
ALTER TABLE competitor_pages ADD CONSTRAINT check_crawl_age_bucket
    CHECK (crawl_age_bucket IN ('fresh', 'warm', 'stale', 'unknown'));

-- Add check constraint for data_confidence
ALTER TABLE competitor_pages DROP CONSTRAINT IF EXISTS check_data_confidence;
ALTER TABLE competitor_pages ADD CONSTRAINT check_data_confidence
    CHECK (data_confidence >= 0.0 AND data_confidence <= 1.0);

-- Add index for freshness queries
CREATE INDEX IF NOT EXISTS idx_competitor_pages_freshness
ON competitor_pages(crawl_age_bucket, last_verified_at DESC);

-- Add freshness columns to serp_snapshots
ALTER TABLE serp_snapshots ADD COLUMN IF NOT EXISTS data_confidence NUMERIC(3,2) DEFAULT 1.0;
ALTER TABLE serp_snapshots ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMP DEFAULT NOW();

-- Add freshness columns to companies
ALTER TABLE companies ADD COLUMN IF NOT EXISTS seo_data_freshness VARCHAR(20) DEFAULT 'unknown';
ALTER TABLE companies ADD COLUMN IF NOT EXISTS seo_last_full_analysis TIMESTAMP;

-- Comment on new columns
COMMENT ON COLUMN competitor_pages.last_verified_at IS 'When this data was last verified/re-crawled';
COMMENT ON COLUMN competitor_pages.crawl_age_bucket IS 'Freshness bucket: fresh (<7d), warm (7-30d), stale (>30d)';
COMMENT ON COLUMN competitor_pages.data_confidence IS 'Confidence score 0-1 based on data quality signals';
COMMENT ON COLUMN competitor_pages.main_text IS 'Extracted main text for re-embedding without re-crawling';
