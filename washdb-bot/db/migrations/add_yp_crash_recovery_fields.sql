-- Migration: Add crash recovery fields to yp_targets table
-- Purpose: Enable resumable, crash-proof Yellow Pages crawler
-- Date: 2025-11-18

-- Add worker claim fields
ALTER TABLE yp_targets ADD COLUMN IF NOT EXISTS claimed_by VARCHAR(100);
ALTER TABLE yp_targets ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE yp_targets ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMP WITH TIME ZONE;

-- Add page-level progress fields
ALTER TABLE yp_targets ADD COLUMN IF NOT EXISTS page_current INTEGER NOT NULL DEFAULT 0;
ALTER TABLE yp_targets ADD COLUMN IF NOT EXISTS page_target INTEGER NOT NULL DEFAULT 1;
ALTER TABLE yp_targets ADD COLUMN IF NOT EXISTS last_listing_id VARCHAR(255);
ALTER TABLE yp_targets ADD COLUMN IF NOT EXISTS next_page_url TEXT;

-- Add error tracking
ALTER TABLE yp_targets ADD COLUMN IF NOT EXISTS last_error TEXT;

-- Add completion tracking
ALTER TABLE yp_targets ADD COLUMN IF NOT EXISTS finished_at TIMESTAMP WITH TIME ZONE;

-- Add indexes for crash recovery queries
CREATE INDEX IF NOT EXISTS idx_yp_targets_claimed_by ON yp_targets(claimed_by);
CREATE INDEX IF NOT EXISTS idx_yp_targets_claimed_at ON yp_targets(claimed_at);
CREATE INDEX IF NOT EXISTS idx_yp_targets_heartbeat_at ON yp_targets(heartbeat_at);
CREATE INDEX IF NOT EXISTS idx_yp_targets_finished_at ON yp_targets(finished_at);

-- Add indexes for Company deduplication
CREATE INDEX IF NOT EXISTS idx_companies_phone ON companies(phone);
CREATE INDEX IF NOT EXISTS idx_companies_email ON companies(email);

-- Update status enum values (migrate lowercase to uppercase)
-- Note: This preserves existing data while standardizing status values
UPDATE yp_targets SET status = 'PLANNED' WHERE status = 'planned';
UPDATE yp_targets SET status = 'IN_PROGRESS' WHERE status = 'in_progress';
UPDATE yp_targets SET status = 'DONE' WHERE status = 'done';
UPDATE yp_targets SET status = 'FAILED' WHERE status = 'failed';
UPDATE yp_targets SET status = 'PARKED' WHERE status = 'parked';

-- Initialize page_target for existing records
UPDATE yp_targets SET page_target = max_pages WHERE page_target = 1 AND max_pages != 1;

-- Comments for new fields
COMMENT ON COLUMN yp_targets.claimed_by IS 'Worker ID that claimed this target (e.g., worker_0_pid_12345)';
COMMENT ON COLUMN yp_targets.claimed_at IS 'When target was claimed by worker';
COMMENT ON COLUMN yp_targets.heartbeat_at IS 'Last worker heartbeat timestamp (for orphan detection)';
COMMENT ON COLUMN yp_targets.page_current IS 'Current page being crawled (0=not started, 1=first page, etc.)';
COMMENT ON COLUMN yp_targets.page_target IS 'Target page count (same as max_pages)';
COMMENT ON COLUMN yp_targets.last_listing_id IS 'Last processed listing ID (stable cursor for resume)';
COMMENT ON COLUMN yp_targets.next_page_url IS 'URL of next page to crawl (for resume)';
COMMENT ON COLUMN yp_targets.last_error IS 'Last error message encountered';
COMMENT ON COLUMN yp_targets.finished_at IS 'When target was completed (status=DONE)';

-- Update status column comment
COMMENT ON COLUMN yp_targets.status IS 'PLANNED, IN_PROGRESS, DONE, FAILED, STUCK, PARKED';
