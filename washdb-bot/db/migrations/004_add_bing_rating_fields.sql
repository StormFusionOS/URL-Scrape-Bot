-- Migration: Add Bing Rating Fields
-- Date: 2025-11-18
-- Description: Add columns to support Bing Local Search rating data

-- Add Bing-specific rating fields to companies table
ALTER TABLE companies
ADD COLUMN IF NOT EXISTS rating_bing FLOAT,
ADD COLUMN IF NOT EXISTS reviews_bing INTEGER;

-- Create index on rating_bing for filtering/sorting
CREATE INDEX IF NOT EXISTS idx_companies_rating_bing ON companies(rating_bing);

-- Add comments
COMMENT ON COLUMN companies.rating_bing IS 'Bing Local Search rating (0.0-5.0)';
COMMENT ON COLUMN companies.reviews_bing IS 'Number of reviews on Bing';
