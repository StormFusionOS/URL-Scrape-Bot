-- Migration: Add google_targets table for city-first Google Maps scraping
-- Date: 2025-11-18
-- Description: Creates google_targets table to support systematic city × category crawling

CREATE TABLE IF NOT EXISTS google_targets (
    -- Primary Key
    id SERIAL PRIMARY KEY,

    -- Provider & Location
    provider VARCHAR(10) NOT NULL DEFAULT 'Google',
    state_id VARCHAR(2) NOT NULL,
    city VARCHAR(255) NOT NULL,
    city_slug VARCHAR(255) NOT NULL,
    lat FLOAT,
    lng FLOAT,

    -- Category
    category_label VARCHAR(255) NOT NULL,
    category_keyword VARCHAR(255) NOT NULL,

    -- Search Configuration
    search_query TEXT NOT NULL,
    max_results INT NOT NULL DEFAULT 20,
    priority INT NOT NULL DEFAULT 2,

    -- Status Tracking
    status VARCHAR(50) NOT NULL DEFAULT 'PLANNED',
    last_attempt_ts TIMESTAMP,
    attempts INT NOT NULL DEFAULT 0,
    note TEXT,

    -- Worker Claim & Heartbeat (for crash recovery)
    claimed_by VARCHAR(100),
    claimed_at TIMESTAMP,
    heartbeat_at TIMESTAMP,

    -- Results Tracking
    results_found INT NOT NULL DEFAULT 0,
    results_saved INT NOT NULL DEFAULT 0,
    duplicates_skipped INT NOT NULL DEFAULT 0,

    -- Error Tracking
    last_error TEXT,
    captcha_detected BOOLEAN DEFAULT FALSE,

    -- Timestamps
    finished_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_google_targets_status ON google_targets(status);
CREATE INDEX IF NOT EXISTS idx_google_targets_priority ON google_targets(priority);
CREATE INDEX IF NOT EXISTS idx_google_targets_state ON google_targets(state_id);
CREATE INDEX IF NOT EXISTS idx_google_targets_city ON google_targets(city);
CREATE INDEX IF NOT EXISTS idx_google_targets_category ON google_targets(category_label);
CREATE INDEX IF NOT EXISTS idx_google_targets_claimed_by ON google_targets(claimed_by);
CREATE INDEX IF NOT EXISTS idx_google_targets_claimed_at ON google_targets(claimed_at);
CREATE INDEX IF NOT EXISTS idx_google_targets_heartbeat_at ON google_targets(heartbeat_at);
CREATE INDEX IF NOT EXISTS idx_google_targets_last_attempt ON google_targets(last_attempt_ts);

-- Composite index for worker queries
CREATE INDEX IF NOT EXISTS idx_google_targets_status_priority ON google_targets(status, priority);

-- Unique constraint to prevent duplicate city × category combinations
CREATE UNIQUE INDEX IF NOT EXISTS idx_google_targets_unique_city_category
ON google_targets(state_id, city_slug, category_keyword);

-- Updated_at trigger
CREATE OR REPLACE FUNCTION update_google_targets_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_google_targets_updated_at
    BEFORE UPDATE ON google_targets
    FOR EACH ROW
    EXECUTE FUNCTION update_google_targets_updated_at();

-- Comments
COMMENT ON TABLE google_targets IS 'Google Maps scraping targets (city × category combinations)';
COMMENT ON COLUMN google_targets.provider IS 'Source provider (always Google)';
COMMENT ON COLUMN google_targets.state_id IS '2-letter state code';
COMMENT ON COLUMN google_targets.city IS 'City name';
COMMENT ON COLUMN google_targets.city_slug IS 'City-state slug (e.g., providence-ri)';
COMMENT ON COLUMN google_targets.lat IS 'City latitude';
COMMENT ON COLUMN google_targets.lng IS 'City longitude';
COMMENT ON COLUMN google_targets.category_label IS 'Human-readable category name';
COMMENT ON COLUMN google_targets.category_keyword IS 'Google search keyword for category';
COMMENT ON COLUMN google_targets.search_query IS 'Full search query (e.g., "car wash near Providence, RI")';
COMMENT ON COLUMN google_targets.max_results IS 'Maximum results to fetch (1-100)';
COMMENT ON COLUMN google_targets.priority IS 'Scraping priority (1=high, 2=medium, 3=low)';
COMMENT ON COLUMN google_targets.status IS 'PLANNED, IN_PROGRESS, DONE, FAILED, STUCK, PARKED';
COMMENT ON COLUMN google_targets.last_attempt_ts IS 'Last attempt timestamp';
COMMENT ON COLUMN google_targets.attempts IS 'Number of scraping attempts';
COMMENT ON COLUMN google_targets.note IS 'Optional note (e.g., reason for failure)';
COMMENT ON COLUMN google_targets.claimed_by IS 'Worker ID that claimed this target';
COMMENT ON COLUMN google_targets.claimed_at IS 'When target was claimed by worker';
COMMENT ON COLUMN google_targets.heartbeat_at IS 'Last worker heartbeat (for orphan detection)';
COMMENT ON COLUMN google_targets.results_found IS 'Number of businesses found';
COMMENT ON COLUMN google_targets.results_saved IS 'Number of businesses saved to DB';
COMMENT ON COLUMN google_targets.duplicates_skipped IS 'Number of duplicates skipped';
COMMENT ON COLUMN google_targets.last_error IS 'Last error message';
COMMENT ON COLUMN google_targets.captcha_detected IS 'Whether CAPTCHA was encountered';
COMMENT ON COLUMN google_targets.finished_at IS 'When target was completed';
