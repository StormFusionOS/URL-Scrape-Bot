-- Rollback Migration: Remove Claude Auto-Tuning System Tables
-- Created: 2025-12-05
-- Purpose: Safely remove Claude tables if needed (reverses 029_add_claude_tables.sql)

-- ==============================================================================
-- WARNING
-- ==============================================================================
-- This will DELETE ALL Claude review data including:
-- - Review queue
-- - Audit trail
-- - Prompt versions
-- - Rate limit tracking
--
-- Make sure to backup data before running this rollback!

-- ==============================================================================
-- BACKUP COMMANDS (run before rollback if you want to preserve data)
-- ==============================================================================
/*
-- Export queue data
COPY claude_review_queue TO '/tmp/claude_review_queue_backup.csv' WITH CSV HEADER;

-- Export audit data
COPY claude_review_audit TO '/tmp/claude_review_audit_backup.csv' WITH CSV HEADER;

-- Export prompt versions
COPY claude_prompt_versions TO '/tmp/claude_prompt_versions_backup.csv' WITH CSV HEADER;

-- Export rate limits
COPY claude_rate_limits TO '/tmp/claude_rate_limits_backup.csv' WITH CSV HEADER;
*/


-- ==============================================================================
-- DROP TABLES (in reverse dependency order)
-- ==============================================================================

-- Drop rate limits table (no dependencies)
DROP TABLE IF EXISTS claude_rate_limits CASCADE;

-- Drop prompt versions table (referenced by audit)
DROP TABLE IF EXISTS claude_prompt_versions CASCADE;

-- Drop audit table (no dependencies)
DROP TABLE IF EXISTS claude_review_audit CASCADE;

-- Drop queue table (no dependencies)
DROP TABLE IF EXISTS claude_review_queue CASCADE;


-- ==============================================================================
-- VERIFICATION QUERIES
-- ==============================================================================

-- Verify tables were dropped
SELECT
    tablename,
    schemaname
FROM pg_tables
WHERE tablename IN ('claude_review_queue', 'claude_review_audit', 'claude_prompt_versions', 'claude_rate_limits');

-- Should return 0 rows

-- Verify indexes were dropped
SELECT
    tablename,
    indexname
FROM pg_indexes
WHERE tablename IN ('claude_review_queue', 'claude_review_audit', 'claude_prompt_versions', 'claude_rate_limits');

-- Should return 0 rows


-- ==============================================================================
-- CLEANUP COMPANY METADATA (Optional)
-- ==============================================================================
-- If you want to also remove Claude review metadata from companies table:
/*
UPDATE companies
SET parse_metadata = parse_metadata - 'claude_review'
WHERE parse_metadata ? 'claude_review';

-- Verify cleanup
SELECT
    COUNT(*) as total_companies,
    COUNT(*) FILTER (WHERE parse_metadata ? 'claude_review') as with_claude_metadata
FROM companies;
*/
