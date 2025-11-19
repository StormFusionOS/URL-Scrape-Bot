-- Migration: Add parse_metadata JSONB field to companies table
-- Purpose: Store traceability and explainability data for accepted YP listings
-- Date: 2025-11-18

-- Add parse_metadata column
ALTER TABLE companies
ADD COLUMN IF NOT EXISTS parse_metadata JSONB;

-- Add comment explaining the field
COMMENT ON COLUMN companies.parse_metadata IS
'JSON with parsing/filtering signals: profile_url, category_tags, is_sponsored, filter_score, filter_reason, source_page_url';

-- Create GIN index for efficient JSONB queries
CREATE INDEX IF NOT EXISTS idx_companies_parse_metadata_gin
ON companies USING GIN (parse_metadata);

-- Add index on filter_reason for reject stats queries
CREATE INDEX IF NOT EXISTS idx_companies_parse_metadata_filter_reason
ON companies ((parse_metadata->>'filter_reason'));

-- Example queries after migration:
--
-- 1. Find all companies with high filter scores:
-- SELECT name, website, parse_metadata->>'filter_score' as score
-- FROM companies
-- WHERE parse_metadata->>'filter_reason' = 'accepted'
-- ORDER BY (parse_metadata->>'filter_score')::float DESC
-- LIMIT 100;
--
-- 2. Count by category tags:
-- SELECT jsonb_array_elements_text(parse_metadata->'category_tags') as tag, COUNT(*) as count
-- FROM companies
-- WHERE parse_metadata ? 'category_tags'
-- GROUP BY tag
-- ORDER BY count DESC;
--
-- 3. Find sponsored listings:
-- SELECT name, website, parse_metadata->>'source_page_url'
-- FROM companies
-- WHERE parse_metadata->>'is_sponsored' = 'true';
--
-- 4. Trace back to source page:
-- SELECT name, website, parse_metadata->>'profile_url' as yp_profile,
--        parse_metadata->>'source_page_url' as search_page
-- FROM companies
-- WHERE parse_metadata ? 'source_page_url'
-- LIMIT 100;
