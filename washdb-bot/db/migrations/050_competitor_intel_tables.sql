-- Migration 050: Competitor Intelligence Tables
-- Creates tables and schema extensions for the competitor_intel module

-- ============================================================================
-- 1. Link companies to their competitors (many-to-many relationship)
-- ============================================================================
CREATE TABLE IF NOT EXISTS company_competitors (
    id SERIAL PRIMARY KEY,
    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    competitor_id INTEGER REFERENCES competitors(competitor_id) ON DELETE CASCADE,
    relationship_type VARCHAR(50) DEFAULT 'direct',  -- direct, adjacent, regional
    threat_level INTEGER DEFAULT 3 CHECK (threat_level BETWEEN 1 AND 5),
    market_overlap DECIMAL(5,2) CHECK (market_overlap BETWEEN 0 AND 100),
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(company_id, competitor_id)
);

CREATE INDEX IF NOT EXISTS idx_company_competitors_company ON company_competitors(company_id);
CREATE INDEX IF NOT EXISTS idx_company_competitors_competitor ON company_competitors(competitor_id);
CREATE INDEX IF NOT EXISTS idx_company_competitors_threat ON company_competitors(threat_level DESC);

COMMENT ON TABLE company_competitors IS 'Links companies to their competitors for tracking';
COMMENT ON COLUMN company_competitors.relationship_type IS 'direct=same services, adjacent=related services, regional=same area different services';
COMMENT ON COLUMN company_competitors.threat_level IS '1=low threat, 5=high threat';


-- ============================================================================
-- 2. Competitor services tracking
-- ============================================================================
CREATE TABLE IF NOT EXISTS competitor_services (
    id SERIAL PRIMARY KEY,
    competitor_id INTEGER REFERENCES competitors(competitor_id) ON DELETE CASCADE,
    service_name VARCHAR(255) NOT NULL,
    service_category VARCHAR(100),        -- pressure_washing, window_cleaning, etc.
    pricing_model VARCHAR(50),            -- flat, hourly, sqft, custom, quote
    price_min DECIMAL(10,2),
    price_max DECIMAL(10,2),
    price_unit VARCHAR(50),               -- per_hour, per_sqft, per_job, etc.
    description TEXT,
    source_url TEXT,
    confidence_score DECIMAL(3,2) DEFAULT 0.5 CHECK (confidence_score BETWEEN 0 AND 1),
    discovered_at TIMESTAMP DEFAULT NOW(),
    last_seen_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE,
    metadata JSONB DEFAULT '{}',
    UNIQUE(competitor_id, service_name)
);

CREATE INDEX IF NOT EXISTS idx_competitor_services_competitor ON competitor_services(competitor_id);
CREATE INDEX IF NOT EXISTS idx_competitor_services_category ON competitor_services(service_category);
CREATE INDEX IF NOT EXISTS idx_competitor_services_active ON competitor_services(competitor_id) WHERE is_active = true;

COMMENT ON TABLE competitor_services IS 'Tracks services offered by competitors with pricing info';


-- ============================================================================
-- 3. Competitor review aggregation (daily snapshots)
-- ============================================================================
CREATE TABLE IF NOT EXISTS competitor_reviews_aggregate (
    id SERIAL PRIMARY KEY,
    competitor_id INTEGER REFERENCES competitors(competitor_id) ON DELETE CASCADE,
    source VARCHAR(50) NOT NULL,          -- google, yelp, facebook, bbb, angi, etc.
    rating_avg DECIMAL(3,2) CHECK (rating_avg BETWEEN 0 AND 5),
    review_count INTEGER DEFAULT 0,
    review_count_7d INTEGER DEFAULT 0,    -- New reviews last 7 days
    review_count_30d INTEGER DEFAULT 0,   -- New reviews last 30 days
    sentiment_score DECIMAL(5,2) CHECK (sentiment_score BETWEEN 0 AND 100),
    response_rate DECIMAL(5,2) CHECK (response_rate BETWEEN 0 AND 100),
    avg_response_time_hours INTEGER,
    top_complaints JSONB DEFAULT '[]',    -- Common issues mentioned
    top_praise JSONB DEFAULT '[]',        -- Common positives mentioned
    captured_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(competitor_id, source, DATE(captured_at))
);

CREATE INDEX IF NOT EXISTS idx_competitor_reviews_competitor ON competitor_reviews_aggregate(competitor_id);
CREATE INDEX IF NOT EXISTS idx_competitor_reviews_source ON competitor_reviews_aggregate(source);
CREATE INDEX IF NOT EXISTS idx_competitor_reviews_date ON competitor_reviews_aggregate(captured_at DESC);

COMMENT ON TABLE competitor_reviews_aggregate IS 'Daily review metrics aggregation per competitor per source';


-- ============================================================================
-- 4. Share of Voice (SOV) tracking
-- ============================================================================
CREATE TABLE IF NOT EXISTS competitor_sov (
    id SERIAL PRIMARY KEY,
    market_segment VARCHAR(255) NOT NULL, -- e.g., "pressure_washing_peoria_il"
    captured_date DATE DEFAULT CURRENT_DATE,
    company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
    competitor_data JSONB DEFAULT '{}',   -- {competitor_id: {sov: %, rank: n, keywords_top10: n}, ...}
    our_sov DECIMAL(5,2) CHECK (our_sov BETWEEN 0 AND 100),
    our_rank INTEGER,
    keywords_tracked INTEGER DEFAULT 0,
    keywords_top_3 INTEGER DEFAULT 0,
    keywords_top_10 INTEGER DEFAULT 0,
    keywords_page_1 INTEGER DEFAULT 0,
    visibility_score DECIMAL(5,2) CHECK (visibility_score BETWEEN 0 AND 100),
    trend_7d DECIMAL(5,2),                -- Change vs 7 days ago
    trend_30d DECIMAL(5,2),               -- Change vs 30 days ago
    metadata JSONB DEFAULT '{}',
    UNIQUE(market_segment, captured_date, company_id)
);

CREATE INDEX IF NOT EXISTS idx_competitor_sov_market ON competitor_sov(market_segment);
CREATE INDEX IF NOT EXISTS idx_competitor_sov_company ON competitor_sov(company_id);
CREATE INDEX IF NOT EXISTS idx_competitor_sov_date ON competitor_sov(captured_date DESC);

COMMENT ON TABLE competitor_sov IS 'Share of Voice tracking - our visibility vs competitors per market segment';


-- ============================================================================
-- 5. Competitor alerts
-- ============================================================================
CREATE TABLE IF NOT EXISTS competitor_alerts (
    id SERIAL PRIMARY KEY,
    competitor_id INTEGER REFERENCES competitors(competitor_id) ON DELETE CASCADE,
    company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
    alert_type VARCHAR(50) NOT NULL,      -- ranking_change, new_service, price_change, review_spike, etc.
    severity VARCHAR(20) DEFAULT 'medium' CHECK (severity IN ('critical', 'high', 'medium', 'low', 'info')),
    title VARCHAR(255) NOT NULL,
    description TEXT,
    old_value TEXT,
    new_value TEXT,
    change_magnitude DECIMAL(10,2),       -- Numeric change amount if applicable
    triggered_at TIMESTAMP DEFAULT NOW(),
    acknowledged_at TIMESTAMP,
    acknowledged_by VARCHAR(100),
    resolved_at TIMESTAMP,
    action_taken TEXT,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_competitor_alerts_competitor ON competitor_alerts(competitor_id);
CREATE INDEX IF NOT EXISTS idx_competitor_alerts_type ON competitor_alerts(alert_type);
CREATE INDEX IF NOT EXISTS idx_competitor_alerts_severity ON competitor_alerts(severity);
CREATE INDEX IF NOT EXISTS idx_competitor_alerts_unacked ON competitor_alerts(competitor_id)
    WHERE acknowledged_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_competitor_alerts_recent ON competitor_alerts(triggered_at DESC);

COMMENT ON TABLE competitor_alerts IS 'Alerts triggered by competitor changes requiring attention';


-- ============================================================================
-- 6. Competitor job tracking (separate from seo_job_tracking)
-- ============================================================================
CREATE TABLE IF NOT EXISTS competitor_job_tracking (
    id SERIAL PRIMARY KEY,
    competitor_id INTEGER REFERENCES competitors(competitor_id) ON DELETE CASCADE,
    module_name VARCHAR(50) NOT NULL,     -- site_crawl, serp_track, citations, reviews, technical, services, synthesis
    run_type VARCHAR(20) DEFAULT 'scheduled' CHECK (run_type IN ('scheduled', 'manual', 'retry', 'initial')),
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed', 'skipped')),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    duration_seconds INTEGER,
    records_created INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    error_message TEXT,
    error_traceback TEXT,
    retry_count INTEGER DEFAULT 0,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_competitor_job_competitor ON competitor_job_tracking(competitor_id);
CREATE INDEX IF NOT EXISTS idx_competitor_job_module ON competitor_job_tracking(module_name);
CREATE INDEX IF NOT EXISTS idx_competitor_job_status ON competitor_job_tracking(status);
CREATE INDEX IF NOT EXISTS idx_competitor_job_incomplete ON competitor_job_tracking(competitor_id, module_name)
    WHERE status IN ('pending', 'running');
CREATE INDEX IF NOT EXISTS idx_competitor_job_failed ON competitor_job_tracking(competitor_id)
    WHERE status = 'failed';

COMMENT ON TABLE competitor_job_tracking IS 'Tracks execution of competitor intelligence jobs';


-- ============================================================================
-- 7. Competitor heartbeats (for worker health monitoring)
-- ============================================================================
CREATE TABLE IF NOT EXISTS competitor_heartbeats (
    id SERIAL PRIMARY KEY,
    worker_name VARCHAR(100) NOT NULL UNIQUE,
    worker_type VARCHAR(50) DEFAULT 'competitor_intel',
    status VARCHAR(20) DEFAULT 'running' CHECK (status IN ('running', 'idle', 'stale', 'stopped')),
    last_heartbeat TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP DEFAULT NOW(),
    pid INTEGER,
    hostname VARCHAR(255),
    competitors_processed INTEGER DEFAULT 0,
    jobs_completed INTEGER DEFAULT 0,
    jobs_failed INTEGER DEFAULT 0,
    current_competitor_id INTEGER,
    current_module VARCHAR(50),
    avg_job_duration DECIMAL(10,2),
    last_error TEXT,
    last_error_at TIMESTAMP,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_competitor_heartbeats_status ON competitor_heartbeats(status);

COMMENT ON TABLE competitor_heartbeats IS 'Worker health monitoring for competitor intel workers';


-- ============================================================================
-- 8. Extend competitors table with intel tracking columns
-- ============================================================================
DO $$
BEGIN
    -- Add intel tracking columns if they don't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_initial_complete') THEN
        ALTER TABLE competitors ADD COLUMN intel_initial_complete BOOLEAN DEFAULT FALSE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_last_full_crawl') THEN
        ALTER TABLE competitors ADD COLUMN intel_last_full_crawl TIMESTAMP;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_next_refresh_due') THEN
        ALTER TABLE competitors ADD COLUMN intel_next_refresh_due TIMESTAMP;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'priority_tier') THEN
        ALTER TABLE competitors ADD COLUMN priority_tier INTEGER DEFAULT 2;
    END IF;

    -- Module completion flags
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_site_crawl_done') THEN
        ALTER TABLE competitors ADD COLUMN intel_site_crawl_done BOOLEAN DEFAULT FALSE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_serp_done') THEN
        ALTER TABLE competitors ADD COLUMN intel_serp_done BOOLEAN DEFAULT FALSE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_citations_done') THEN
        ALTER TABLE competitors ADD COLUMN intel_citations_done BOOLEAN DEFAULT FALSE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_reviews_done') THEN
        ALTER TABLE competitors ADD COLUMN intel_reviews_done BOOLEAN DEFAULT FALSE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_technical_done') THEN
        ALTER TABLE competitors ADD COLUMN intel_technical_done BOOLEAN DEFAULT FALSE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_services_done') THEN
        ALTER TABLE competitors ADD COLUMN intel_services_done BOOLEAN DEFAULT FALSE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_synthesis_done') THEN
        ALTER TABLE competitors ADD COLUMN intel_synthesis_done BOOLEAN DEFAULT FALSE;
    END IF;
END $$;

-- Index for finding competitors due for refresh
CREATE INDEX IF NOT EXISTS idx_competitors_intel_refresh ON competitors(intel_next_refresh_due)
    WHERE is_active = true AND intel_initial_complete = true;

-- Index for finding competitors needing initial intel
CREATE INDEX IF NOT EXISTS idx_competitors_intel_initial ON competitors(competitor_id)
    WHERE is_active = true AND intel_initial_complete = false;

-- Index for priority-based processing
CREATE INDEX IF NOT EXISTS idx_competitors_priority ON competitors(priority_tier, intel_next_refresh_due)
    WHERE is_active = true;


-- ============================================================================
-- 9. Record migration
-- ============================================================================
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('050', 'Competitor Intelligence Tables', NOW())
ON CONFLICT (version) DO NOTHING;
