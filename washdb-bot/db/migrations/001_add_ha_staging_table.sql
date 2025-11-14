-- Migration: Add ha_staging table for HomeAdvisor pipeline workflow
-- Description: Creates staging table for Phase 1 (discovery) before Phase 2 (URL finding)
-- Author: Claude
-- Date: 2025-01-14

-- Create ha_staging table
CREATE TABLE IF NOT EXISTS ha_staging (
    id SERIAL PRIMARY KEY,

    -- Business Information
    name TEXT,
    address TEXT,
    phone TEXT,
    profile_url TEXT UNIQUE NOT NULL,

    -- Ratings
    rating_ha REAL,
    reviews_ha INTEGER,

    -- Pipeline Status
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    processed BOOLEAN DEFAULT FALSE NOT NULL,
    retry_count INTEGER DEFAULT 0 NOT NULL,
    next_retry_at TIMESTAMP,
    last_error TEXT
);

-- Create indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_ha_staging_processed
    ON ha_staging(processed);

CREATE INDEX IF NOT EXISTS idx_ha_staging_next_retry
    ON ha_staging(next_retry_at);

CREATE INDEX IF NOT EXISTS idx_ha_staging_profile_url
    ON ha_staging(profile_url);

-- Add composite index for worker queries
CREATE INDEX IF NOT EXISTS idx_ha_staging_worker_query
    ON ha_staging(processed, next_retry_at)
    WHERE processed = FALSE;

-- Add comments
COMMENT ON TABLE ha_staging IS 'Staging table for HomeAdvisor businesses before URL finding';
COMMENT ON COLUMN ha_staging.profile_url IS 'HomeAdvisor profile URL (unique identifier)';
COMMENT ON COLUMN ha_staging.processed IS 'Whether URL finding has been completed';
COMMENT ON COLUMN ha_staging.retry_count IS 'Number of URL finding attempts';
COMMENT ON COLUMN ha_staging.next_retry_at IS 'When to retry URL finding (exponential backoff)';
COMMENT ON COLUMN ha_staging.last_error IS 'Error message from last URL finding attempt';
