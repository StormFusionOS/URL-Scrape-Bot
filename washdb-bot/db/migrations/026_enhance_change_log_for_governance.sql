-- ============================================================================
-- Migration 026: Enhance change_log for SEO Governance Workflow
-- ============================================================================
-- Adds missing columns to change_log table to support the SEO governance system:
-- - change_type: Category of change (citations, technical_seo, backlinks, etc.)
-- - source: Which scraper/system proposed the change
-- - applied_at: Timestamp when change was applied to target table
--
-- These columns enable better filtering, tracking, and audit trails.
-- ============================================================================

-- Track this migration
INSERT INTO schema_migrations (version, name, applied_at)
VALUES ('026', 'enhance_change_log_for_governance', NOW())
ON CONFLICT (version) DO NOTHING;

-- Add change_type column
ALTER TABLE change_log
ADD COLUMN IF NOT EXISTS change_type VARCHAR(100);

-- Add source column (which scraper/system proposed the change)
ALTER TABLE change_log
ADD COLUMN IF NOT EXISTS source VARCHAR(200);

-- Add applied_at column (when the approved change was actually applied)
ALTER TABLE change_log
ADD COLUMN IF NOT EXISTS applied_at TIMESTAMP;

-- Add index on change_type for filtering
CREATE INDEX IF NOT EXISTS idx_change_log_change_type ON change_log(change_type);

-- Add index on source for auditing
CREATE INDEX IF NOT EXISTS idx_change_log_source ON change_log(source);

-- Add composite index for common query pattern (status + change_type)
CREATE INDEX IF NOT EXISTS idx_change_log_status_type ON change_log(status, change_type);

-- Add comments for documentation
COMMENT ON COLUMN change_log.change_type IS 'Category of change: citations, technical_seo, onpage, backlinks, serp_tracking, competitor_analysis, reviews, unlinked_mentions';
COMMENT ON COLUMN change_log.source IS 'Source system that proposed the change: review_detail_scraper, unlinked_mentions_finder, citation_crawler, etc.';
COMMENT ON COLUMN change_log.applied_at IS 'Timestamp when approved change was applied to target table';

-- Update existing records to have a default source if needed
UPDATE change_log
SET source = 'legacy_system'
WHERE source IS NULL;

COMMENT ON TABLE change_log IS 'Governance table tracking all proposed changes to SEO data. All scrapers must propose changes here for review before they are applied.';
