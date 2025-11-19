-- Migration: Add site_crawl_state table for resumable site crawling
-- Purpose: Track crawl progress per domain for resumability
-- Date: 2025-11-18

-- Create site_crawl_state table
CREATE TABLE IF NOT EXISTS site_crawl_state (
    id SERIAL PRIMARY KEY,

    -- Domain being crawled
    domain VARCHAR(255) NOT NULL UNIQUE,

    -- Crawl phase
    phase VARCHAR(50) NOT NULL DEFAULT 'parsing_home',

    -- Cursor state
    last_completed_url TEXT,
    pending_queue JSONB,

    -- Discovered target URLs
    discovered_targets JSONB,

    -- Statistics
    pages_crawled INTEGER NOT NULL DEFAULT 0,
    targets_found INTEGER NOT NULL DEFAULT 0,
    errors_count INTEGER NOT NULL DEFAULT 0,

    -- Error tracking
    last_error TEXT,

    -- Timestamps
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- Add comments
COMMENT ON TABLE site_crawl_state IS 'Site crawler state for resumable crawling';
COMMENT ON COLUMN site_crawl_state.domain IS 'Domain being crawled (e.g., example.com)';
COMMENT ON COLUMN site_crawl_state.phase IS 'Current phase: parsing_home, crawling_internal, done, failed';
COMMENT ON COLUMN site_crawl_state.last_completed_url IS 'Last URL successfully parsed (for resume)';
COMMENT ON COLUMN site_crawl_state.pending_queue IS 'JSON array of pending URLs to crawl (max 50)';
COMMENT ON COLUMN site_crawl_state.discovered_targets IS 'JSON with discovered URLs: {contact: [...], about: [...], services: [...]}';
COMMENT ON COLUMN site_crawl_state.pages_crawled IS 'Total pages crawled so far';
COMMENT ON COLUMN site_crawl_state.targets_found IS 'Total target pages found (contact/about/services)';
COMMENT ON COLUMN site_crawl_state.errors_count IS 'Number of errors encountered';
COMMENT ON COLUMN site_crawl_state.last_error IS 'Last error message (for debugging)';
COMMENT ON COLUMN site_crawl_state.started_at IS 'When crawl started';
COMMENT ON COLUMN site_crawl_state.last_updated IS 'Last cursor save timestamp';
COMMENT ON COLUMN site_crawl_state.completed_at IS 'When crawl completed (done or failed)';

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_site_crawl_state_domain ON site_crawl_state(domain);
CREATE INDEX IF NOT EXISTS idx_site_crawl_state_phase ON site_crawl_state(phase);
CREATE INDEX IF NOT EXISTS idx_site_crawl_state_last_updated ON site_crawl_state(last_updated);

-- Create GIN index for JSONB columns
CREATE INDEX IF NOT EXISTS idx_site_crawl_state_pending_queue_gin ON site_crawl_state USING GIN (pending_queue);
CREATE INDEX IF NOT EXISTS idx_site_crawl_state_discovered_targets_gin ON site_crawl_state USING GIN (discovered_targets);

-- Example queries after migration:
--
-- 1. Find incomplete crawls (for resume):
-- SELECT domain, phase, pages_crawled, last_updated
-- FROM site_crawl_state
-- WHERE phase NOT IN ('done', 'failed')
-- ORDER BY last_updated DESC;
--
-- 2. Get crawl state for specific domain:
-- SELECT * FROM site_crawl_state WHERE domain = 'example.com';
--
-- 3. Find failed crawls:
-- SELECT domain, last_error, errors_count, completed_at
-- FROM site_crawl_state
-- WHERE phase = 'failed'
-- ORDER BY completed_at DESC;
--
-- 4. Count crawls by phase:
-- SELECT phase, COUNT(*) as count
-- FROM site_crawl_state
-- GROUP BY phase;
