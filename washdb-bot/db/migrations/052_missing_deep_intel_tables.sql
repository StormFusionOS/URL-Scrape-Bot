-- Migration 052: Missing Deep Intelligence Tables
-- Adds tables missed from 051 and fixes constraints

-- ============================================================================
-- PART 1: CRAWL PAGES CACHE
-- ============================================================================

CREATE TABLE IF NOT EXISTS competitor_crawl_pages (
    id SERIAL PRIMARY KEY,
    competitor_id INTEGER REFERENCES competitors(competitor_id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    page_type VARCHAR(50) DEFAULT 'home',  -- home, about, services, pricing, contact, blog

    -- Content
    html_content TEXT,
    text_content TEXT,
    content_hash VARCHAR(64),

    -- Metadata
    status_code INTEGER,
    response_time_ms INTEGER,
    crawled_at TIMESTAMP DEFAULT NOW(),

    metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_crawl_pages_competitor ON competitor_crawl_pages(competitor_id);
CREATE INDEX IF NOT EXISTS idx_crawl_pages_type ON competitor_crawl_pages(competitor_id, page_type);
CREATE INDEX IF NOT EXISTS idx_crawl_pages_date ON competitor_crawl_pages(crawled_at DESC);

-- ============================================================================
-- PART 2: SERP CACHE
-- ============================================================================

CREATE TABLE IF NOT EXISTS competitor_serp_cache (
    id SERIAL PRIMARY KEY,
    competitor_id INTEGER REFERENCES competitors(competitor_id) ON DELETE CASCADE,
    keyword VARCHAR(255) NOT NULL,
    location VARCHAR(100),

    -- SERP Content
    serp_html TEXT,
    serp_data JSONB,  -- Parsed results

    -- Competitor Position
    organic_position INTEGER,
    local_pack_position INTEGER,
    is_in_ads BOOLEAN DEFAULT FALSE,

    captured_at TIMESTAMP DEFAULT NOW(),

    metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_serp_cache_competitor ON competitor_serp_cache(competitor_id);
CREATE INDEX IF NOT EXISTS idx_serp_cache_keyword ON competitor_serp_cache(keyword);
CREATE INDEX IF NOT EXISTS idx_serp_cache_date ON competitor_serp_cache(captured_at DESC);

-- ============================================================================
-- PART 3: ADD MISSING COLUMNS TO COMPETITORS
-- ============================================================================

-- Module completion flags
DO $$
BEGIN
    -- Content modules
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_content_done') THEN
        ALTER TABLE competitors ADD COLUMN intel_content_done BOOLEAN DEFAULT FALSE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_blog_done') THEN
        ALTER TABLE competitors ADD COLUMN intel_blog_done BOOLEAN DEFAULT FALSE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_keywords_done') THEN
        ALTER TABLE competitors ADD COLUMN intel_keywords_done BOOLEAN DEFAULT FALSE;
    END IF;

    -- Social/Marketing modules
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_social_done') THEN
        ALTER TABLE competitors ADD COLUMN intel_social_done BOOLEAN DEFAULT FALSE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_ads_done') THEN
        ALTER TABLE competitors ADD COLUMN intel_ads_done BOOLEAN DEFAULT FALSE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_marketing_done') THEN
        ALTER TABLE competitors ADD COLUMN intel_marketing_done BOOLEAN DEFAULT FALSE;
    END IF;

    -- Review modules
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_review_deep_done') THEN
        ALTER TABLE competitors ADD COLUMN intel_review_deep_done BOOLEAN DEFAULT FALSE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_review_analysis_done') THEN
        ALTER TABLE competitors ADD COLUMN intel_review_analysis_done BOOLEAN DEFAULT FALSE;
    END IF;

    -- Pricing module
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_pricing_done') THEN
        ALTER TABLE competitors ADD COLUMN intel_pricing_done BOOLEAN DEFAULT FALSE;
    END IF;

END$$;

-- ============================================================================
-- PART 4: FIX UNIQUE CONSTRAINTS IN 051 (Convert to indexes)
-- ============================================================================

-- competitor_reviews: Use functional index for uniqueness
DROP INDEX IF EXISTS idx_competitor_reviews_unique;
CREATE UNIQUE INDEX IF NOT EXISTS idx_competitor_reviews_unique
    ON competitor_reviews(competitor_id, source, COALESCE(external_review_id, LEFT(review_text, 100)));

-- competitor_review_stats: One set per competitor/source per day
DROP INDEX IF EXISTS idx_competitor_review_stats_unique;
CREATE UNIQUE INDEX IF NOT EXISTS idx_competitor_review_stats_unique
    ON competitor_review_stats(competitor_id, source, DATE(computed_at));

-- competitor_content_archive: One archive per URL per day
DROP INDEX IF EXISTS idx_content_archive_unique;
CREATE UNIQUE INDEX IF NOT EXISTS idx_content_archive_unique
    ON competitor_content_archive(competitor_id, url, DATE(captured_at));

-- keyword_gap_analysis: One analysis per keyword per day
DROP INDEX IF EXISTS idx_keyword_gap_unique;
CREATE UNIQUE INDEX IF NOT EXISTS idx_keyword_gap_unique
    ON keyword_gap_analysis(company_id, competitor_id, keyword, DATE(captured_at));
