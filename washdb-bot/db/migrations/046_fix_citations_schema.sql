-- Migration: Fix citations table schema for LAS calculator
-- Date: 2026-01-01
-- Description: Add missing columns required by LAS calculator

-- Add is_present column (indicates if citation is currently active/present)
ALTER TABLE citations ADD COLUMN IF NOT EXISTS is_present BOOLEAN DEFAULT TRUE;

-- Add individual NAP match columns for detailed scoring
ALTER TABLE citations ADD COLUMN IF NOT EXISTS name_match BOOLEAN DEFAULT NULL;
ALTER TABLE citations ADD COLUMN IF NOT EXISTS address_match BOOLEAN DEFAULT NULL;
ALTER TABLE citations ADD COLUMN IF NOT EXISTS phone_match BOOLEAN DEFAULT NULL;

-- Add company_id foreign key for linking to companies table
ALTER TABLE citations ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES companies(id);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_citations_is_present ON citations(is_present);
CREATE INDEX IF NOT EXISTS idx_citations_company_id ON citations(company_id);
CREATE INDEX IF NOT EXISTS idx_citations_business_name ON citations(business_name);

-- Update existing records: set is_present=TRUE for all existing citations
UPDATE citations SET is_present = TRUE WHERE is_present IS NULL;

-- Set NAP match columns based on nap_match_score if available
-- Score >= 0.9 means all three match
-- Score >= 0.66 means at least 2 match
-- Score >= 0.33 means at least 1 matches
UPDATE citations
SET
    name_match = CASE WHEN nap_match_score >= 0.33 THEN TRUE ELSE FALSE END,
    address_match = CASE WHEN nap_match_score >= 0.66 THEN TRUE ELSE FALSE END,
    phone_match = CASE WHEN nap_match_score >= 0.90 THEN TRUE ELSE FALSE END
WHERE nap_match_score IS NOT NULL
  AND (name_match IS NULL OR address_match IS NULL OR phone_match IS NULL);

-- Add comment explaining the columns
COMMENT ON COLUMN citations.is_present IS 'Whether the citation is currently active/present on the directory';
COMMENT ON COLUMN citations.name_match IS 'Whether the business name matches the canonical name';
COMMENT ON COLUMN citations.address_match IS 'Whether the address matches the canonical address';
COMMENT ON COLUMN citations.phone_match IS 'Whether the phone number matches the canonical phone';
COMMENT ON COLUMN citations.company_id IS 'Foreign key linking to the companies table';
