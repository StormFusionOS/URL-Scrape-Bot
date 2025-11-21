-- Migration: Create city_registry table for ZIP code-based city searches
-- This table stores US cities with their ZIP codes from uscities.csv

CREATE TABLE IF NOT EXISTS city_registry (
    city_id SERIAL PRIMARY KEY,
    city VARCHAR(255) NOT NULL,
    city_ascii VARCHAR(255) NOT NULL,
    state_id VARCHAR(2) NOT NULL,
    state_name VARCHAR(100) NOT NULL,
    county_name VARCHAR(100),
    lat DECIMAL(10, 7),
    lng DECIMAL(10, 7),
    population INTEGER,
    density DECIMAL(10, 2),
    timezone VARCHAR(50),
    ranking INTEGER,

    -- ZIP code fields
    zips TEXT,  -- Space-separated list of all ZIP codes
    primary_zip VARCHAR(10),  -- Primary ZIP code (first one)

    -- Priority tier for crawling (based on population)
    tier CHAR(1) DEFAULT 'C',  -- A (high), B (medium), C (low)

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    -- Indexes for efficient queries
    CONSTRAINT unique_city_state UNIQUE (city_ascii, state_id)
);

-- Create indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_city_registry_state ON city_registry(state_id);
CREATE INDEX IF NOT EXISTS idx_city_registry_tier ON city_registry(tier);
CREATE INDEX IF NOT EXISTS idx_city_registry_population ON city_registry(population DESC);
CREATE INDEX IF NOT EXISTS idx_city_registry_primary_zip ON city_registry(primary_zip);

-- Add comment
COMMENT ON TABLE city_registry IS 'US cities with ZIP codes for city-based scraping (from uscities.csv)';
