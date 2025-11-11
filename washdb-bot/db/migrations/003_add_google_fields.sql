-- Migration: Add Google Business Scraper Fields
-- Date: 2025-11-10
-- Description: Add columns to support Google Maps/Business scraping

-- Add Google-specific fields to companies table
ALTER TABLE companies
ADD COLUMN IF NOT EXISTS place_id VARCHAR(255) UNIQUE,
ADD COLUMN IF NOT EXISTS google_business_url TEXT,
ADD COLUMN IF NOT EXISTS scrape_method VARCHAR(50) DEFAULT 'manual',
ADD COLUMN IF NOT EXISTS scrape_timestamp TIMESTAMP,
ADD COLUMN IF NOT EXISTS data_completeness FLOAT,
ADD COLUMN IF NOT EXISTS confidence_score FLOAT,
ADD COLUMN IF NOT EXISTS last_scrape_attempt TIMESTAMP,
ADD COLUMN IF NOT EXISTS scrape_error_count INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS scrape_error_message TEXT;

-- Create index on place_id for fast lookups
CREATE INDEX IF NOT EXISTS idx_companies_place_id ON companies(place_id);

-- Create index on scrape_method for filtering
CREATE INDEX IF NOT EXISTS idx_companies_scrape_method ON companies(scrape_method);

-- Create index on source for filtering (if not already exists)
CREATE INDEX IF NOT EXISTS idx_companies_source ON companies(source);

-- Add comment to table
COMMENT ON COLUMN companies.place_id IS 'Google Place ID (unique identifier from Google Maps)';
COMMENT ON COLUMN companies.google_business_url IS 'Google Business/Maps URL';
COMMENT ON COLUMN companies.scrape_method IS 'Method used to scrape: manual, playwright, api';
COMMENT ON COLUMN companies.data_completeness IS 'Data completeness score (0.0 - 1.0)';
COMMENT ON COLUMN companies.confidence_score IS 'Confidence in data accuracy (0.0 - 1.0)';
COMMENT ON COLUMN companies.scrape_timestamp IS 'When this business was last scraped';
COMMENT ON COLUMN companies.last_scrape_attempt IS 'Last attempt to scrape (even if failed)';
COMMENT ON COLUMN companies.scrape_error_count IS 'Number of consecutive scrape errors';
COMMENT ON COLUMN companies.scrape_error_message IS 'Last error message from scraping';

-- Update existing Google records (if any) to set scrape_method
UPDATE companies
SET scrape_method = 'manual'
WHERE source = 'Google' AND scrape_method IS NULL;

-- Create scrape_logs table for detailed logging
CREATE TABLE IF NOT EXISTS scrape_logs (
    id SERIAL PRIMARY KEY,
    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    scrape_method VARCHAR(50) NOT NULL,
    status VARCHAR(50) NOT NULL,  -- 'success', 'partial', 'failed'
    fields_updated TEXT[],  -- Array of field names that were updated
    error_message TEXT,
    scrape_duration_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create index on scrape_logs for company lookups
CREATE INDEX IF NOT EXISTS idx_scrape_logs_company_id ON scrape_logs(company_id);
CREATE INDEX IF NOT EXISTS idx_scrape_logs_status ON scrape_logs(status);
CREATE INDEX IF NOT EXISTS idx_scrape_logs_created_at ON scrape_logs(created_at DESC);

COMMENT ON TABLE scrape_logs IS 'Detailed logging for each scrape attempt';
COMMENT ON COLUMN scrape_logs.fields_updated IS 'Array of field names that were successfully updated';
COMMENT ON COLUMN scrape_logs.scrape_duration_ms IS 'Time taken to scrape in milliseconds';
