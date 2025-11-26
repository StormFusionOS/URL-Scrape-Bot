-- Migration 027: Add yelp_targets table for city-first Yelp discovery
-- Created: 2025-11-25
-- Purpose: Enable Yelp business discovery with city × category targets

BEGIN;

-- Create yelp_targets table
CREATE TABLE IF NOT EXISTS yelp_targets (
    -- Primary Key
    id SERIAL PRIMARY KEY,

    -- Provider & Location
    provider VARCHAR(10) NOT NULL DEFAULT 'Yelp',
    state_id VARCHAR(2) NOT NULL,  -- 2-letter state code
    city VARCHAR(255) NOT NULL,
    city_slug VARCHAR(255) NOT NULL,  -- e.g., 'providence-ri'
    lat FLOAT,  -- City latitude
    lng FLOAT,  -- City longitude

    -- Category
    category_label VARCHAR(255) NOT NULL,  -- Human-readable (e.g., 'Window Cleaning')
    category_keyword VARCHAR(255) NOT NULL,  -- Yelp search keyword (e.g., 'window cleaning')

    -- Search Configuration
    max_results INTEGER NOT NULL DEFAULT 20,  -- Maximum results to fetch (1-100)
    priority INTEGER NOT NULL DEFAULT 2,  -- 1=high, 2=medium, 3=low

    -- Status Tracking
    status VARCHAR(50) NOT NULL DEFAULT 'PLANNED',  -- PLANNED, IN_PROGRESS, DONE, FAILED, STUCK, PARKED
    last_attempt_ts TIMESTAMP,
    attempts INTEGER NOT NULL DEFAULT 0,
    note TEXT,  -- Optional note (e.g., 'no results', 'blocked')

    -- Worker Claim & Heartbeat (for crash recovery)
    claimed_by VARCHAR(100),  -- Worker ID that claimed this target
    claimed_at TIMESTAMP,  -- When target was claimed by worker
    heartbeat_at TIMESTAMP,  -- Last worker heartbeat (for orphan detection)

    -- Results Tracking
    results_found INTEGER NOT NULL DEFAULT 0,
    results_saved INTEGER NOT NULL DEFAULT 0,
    duplicates_skipped INTEGER NOT NULL DEFAULT 0,

    -- Error Tracking
    last_error TEXT,
    captcha_detected BOOLEAN NOT NULL DEFAULT FALSE,

    -- Completion Tracking
    finished_at TIMESTAMP,

    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);

-- Create indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_yelp_targets_state_id ON yelp_targets(state_id);
CREATE INDEX IF NOT EXISTS idx_yelp_targets_city ON yelp_targets(city);
CREATE INDEX IF NOT EXISTS idx_yelp_targets_city_slug ON yelp_targets(city_slug);
CREATE INDEX IF NOT EXISTS idx_yelp_targets_category_label ON yelp_targets(category_label);
CREATE INDEX IF NOT EXISTS idx_yelp_targets_priority ON yelp_targets(priority);
CREATE INDEX IF NOT EXISTS idx_yelp_targets_status ON yelp_targets(status);
CREATE INDEX IF NOT EXISTS idx_yelp_targets_provider ON yelp_targets(provider);
CREATE INDEX IF NOT EXISTS idx_yelp_targets_claimed_by ON yelp_targets(claimed_by);
CREATE INDEX IF NOT EXISTS idx_yelp_targets_claimed_at ON yelp_targets(claimed_at);
CREATE INDEX IF NOT EXISTS idx_yelp_targets_heartbeat_at ON yelp_targets(heartbeat_at);
CREATE INDEX IF NOT EXISTS idx_yelp_targets_last_attempt_ts ON yelp_targets(last_attempt_ts);
CREATE INDEX IF NOT EXISTS idx_yelp_targets_finished_at ON yelp_targets(finished_at);

-- Compound index for worker queries (status + priority for efficient target claiming)
CREATE INDEX IF NOT EXISTS idx_yelp_targets_status_priority ON yelp_targets(status, priority);

-- Add comments for documentation
COMMENT ON TABLE yelp_targets IS 'Yelp city-first scraping targets (city × category combinations)';
COMMENT ON COLUMN yelp_targets.provider IS 'Source provider (always ''Yelp'')';
COMMENT ON COLUMN yelp_targets.state_id IS '2-letter state code';
COMMENT ON COLUMN yelp_targets.city_slug IS 'City-state slug (e.g., ''providence-ri'')';
COMMENT ON COLUMN yelp_targets.category_label IS 'Human-readable category name (e.g., ''Window Cleaning'')';
COMMENT ON COLUMN yelp_targets.category_keyword IS 'Yelp search keyword (e.g., ''window cleaning'')';
COMMENT ON COLUMN yelp_targets.max_results IS 'Maximum results to fetch (1-100)';
COMMENT ON COLUMN yelp_targets.priority IS 'Priority (1=high, 2=medium, 3=low)';
COMMENT ON COLUMN yelp_targets.status IS 'PLANNED, IN_PROGRESS, DONE, FAILED, STUCK, PARKED';
COMMENT ON COLUMN yelp_targets.attempts IS 'Number of scraping attempts';
COMMENT ON COLUMN yelp_targets.claimed_by IS 'Worker ID that claimed this target';
COMMENT ON COLUMN yelp_targets.claimed_at IS 'When target was claimed by worker';
COMMENT ON COLUMN yelp_targets.heartbeat_at IS 'Last worker heartbeat (for orphan detection)';
COMMENT ON COLUMN yelp_targets.results_found IS 'Number of businesses found';
COMMENT ON COLUMN yelp_targets.results_saved IS 'Number of businesses saved to DB';
COMMENT ON COLUMN yelp_targets.duplicates_skipped IS 'Number of duplicates skipped';
COMMENT ON COLUMN yelp_targets.captcha_detected IS 'Whether CAPTCHA was encountered';
COMMENT ON COLUMN yelp_targets.finished_at IS 'When target was completed (status=DONE)';

COMMIT;
