-- Migration: 035_create_keyword_company_tracking.sql
-- Description: Create keyword-company tracking table for per-company keyword assignments
-- Date: 2025-12-18

CREATE TABLE IF NOT EXISTS keyword_company_tracking (
    tracking_id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    keyword_text VARCHAR(500) NOT NULL,
    source VARCHAR(50) NOT NULL,  -- 'service_seed', 'location_variant', 'competitor_gap', 'autocomplete'
    assignment_tier INTEGER CHECK (assignment_tier BETWEEN 1 AND 4),
    status VARCHAR(50) DEFAULT 'tracking',  -- tracking, paused, archived, not_ranking

    -- Position tracking
    initial_position INTEGER,      -- First position we found
    current_position INTEGER,      -- Latest position
    best_position INTEGER,         -- Best position ever achieved
    worst_position INTEGER,        -- Worst position recorded
    position_trend VARCHAR(20),    -- 'rising', 'falling', 'stable', 'new', 'lost'

    -- Timestamps
    first_ranked_at TIMESTAMP,     -- When we first found this keyword ranking
    last_checked_at TIMESTAMP,     -- Last SERP check
    last_position_change TIMESTAMP, -- When position last changed

    -- Analysis data
    analysis_count INTEGER DEFAULT 0,
    opportunity_score FLOAT,       -- From KeywordIntelligence
    difficulty_score FLOAT,        -- From KeywordIntelligence
    volume_tier VARCHAR(20),       -- 'very_low', 'low', 'medium', 'high', 'very_high'
    search_intent VARCHAR(30),     -- 'informational', 'transactional', 'navigational', 'local'

    -- Metadata
    assigned_at TIMESTAMP DEFAULT NOW(),
    reason TEXT,                   -- Why this keyword was added
    metadata JSONB DEFAULT '{}',   -- Additional data (related questions, competitors ranking, etc)

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT unique_company_keyword UNIQUE (company_id, keyword_text)
);

-- Primary lookup indexes
CREATE INDEX IF NOT EXISTS idx_kct_company ON keyword_company_tracking(company_id);
CREATE INDEX IF NOT EXISTS idx_kct_keyword ON keyword_company_tracking(keyword_text);
CREATE INDEX IF NOT EXISTS idx_kct_status ON keyword_company_tracking(status);
CREATE INDEX IF NOT EXISTS idx_kct_tier ON keyword_company_tracking(assignment_tier);
CREATE INDEX IF NOT EXISTS idx_kct_source ON keyword_company_tracking(source);

-- Query optimization indexes
CREATE INDEX IF NOT EXISTS idx_kct_last_checked ON keyword_company_tracking(last_checked_at);
CREATE INDEX IF NOT EXISTS idx_kct_trend ON keyword_company_tracking(position_trend);
CREATE INDEX IF NOT EXISTS idx_kct_opportunity ON keyword_company_tracking(opportunity_score DESC);

-- Composite index for finding stale keywords that need checking
CREATE INDEX IF NOT EXISTS idx_kct_stale_check
ON keyword_company_tracking(company_id, last_checked_at)
WHERE status = 'tracking';

-- Composite index for finding high-opportunity keywords
CREATE INDEX IF NOT EXISTS idx_kct_high_opportunity
ON keyword_company_tracking(company_id, opportunity_score DESC)
WHERE status = 'tracking' AND current_position IS NULL;

-- Table comments
COMMENT ON TABLE keyword_company_tracking IS 'Tracks which keywords are assigned to which companies for SEO monitoring';
COMMENT ON COLUMN keyword_company_tracking.source IS 'How keyword was discovered: service_seed (from verification_services.json), location_variant (seed + city), competitor_gap (competitors rank for it), autocomplete (Google suggestions)';
COMMENT ON COLUMN keyword_company_tracking.assignment_tier IS '1=service seeds, 2=location variants, 3=competitor gaps, 4=long-tail/autocomplete';
COMMENT ON COLUMN keyword_company_tracking.position_trend IS 'Calculated from last 3 position changes: rising (improved 2+), falling (declined 2+), stable, new (first ranking), lost (dropped from ranking)';

-- Create trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_keyword_company_tracking_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_keyword_company_tracking_updated ON keyword_company_tracking;
CREATE TRIGGER trigger_keyword_company_tracking_updated
    BEFORE UPDATE ON keyword_company_tracking
    FOR EACH ROW
    EXECUTE FUNCTION update_keyword_company_tracking_timestamp();
