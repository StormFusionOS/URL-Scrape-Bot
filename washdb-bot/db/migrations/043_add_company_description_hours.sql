-- Migration: Add description and business_hours columns to companies table
-- These fields are extracted from YP but were not being saved

-- Add description column
ALTER TABLE companies ADD COLUMN IF NOT EXISTS description TEXT;
COMMENT ON COLUMN companies.description IS 'Business description from YP or other sources';

-- Add business_hours column
ALTER TABLE companies ADD COLUMN IF NOT EXISTS business_hours TEXT;
COMMENT ON COLUMN companies.business_hours IS 'Business hours (e.g., "Mon-Fri 8am-5pm")';

-- Add city, state, zip_code columns for better location data
ALTER TABLE companies ADD COLUMN IF NOT EXISTS city VARCHAR(100);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS state VARCHAR(2);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS zip_code VARCHAR(10);

-- Add indexes for location fields
CREATE INDEX IF NOT EXISTS idx_companies_city ON companies(city);
CREATE INDEX IF NOT EXISTS idx_companies_state ON companies(state);
CREATE INDEX IF NOT EXISTS idx_companies_zip_code ON companies(zip_code);
