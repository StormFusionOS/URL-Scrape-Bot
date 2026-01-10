-- Migration: 041_create_serp_local_pack_table.sql
-- Description: Create table for storing local pack (Google Maps) results from SERP scraping
-- Date: 2025-12-23

-- Local pack results (Google Maps listings shown in SERP)
CREATE TABLE IF NOT EXISTS serp_local_pack (
    local_id SERIAL PRIMARY KEY,

    -- Foreign Keys
    snapshot_id INTEGER NOT NULL REFERENCES serp_snapshots(snapshot_id) ON DELETE CASCADE,
    query_id INTEGER NOT NULL REFERENCES search_queries(query_id) ON DELETE CASCADE,

    -- Business Data
    business_name TEXT NOT NULL,
    position INTEGER NOT NULL,  -- 1-based position in local pack

    -- Contact Information
    phone VARCHAR(30),
    website TEXT,

    -- Location Data
    street TEXT,
    city VARCHAR(100),
    state VARCHAR(10),
    zip_code VARCHAR(20),
    distance VARCHAR(20),  -- e.g., "2.3 mi"

    -- Ratings & Reviews
    rating DECIMAL(3,2),
    rating_text VARCHAR(50),
    review_count INTEGER,

    -- Business Info
    category VARCHAR(200),
    price_level INTEGER,  -- 0-4 for $ indicators
    hours TEXT,
    is_open BOOLEAN,

    -- Additional Data
    directions_url TEXT,
    services TEXT,

    -- Metadata
    metadata JSONB,

    -- Timestamps
    captured_at TIMESTAMP DEFAULT NOW(),

    -- Constraints
    CONSTRAINT chk_position_positive CHECK (position > 0)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_serp_local_pack_snapshot ON serp_local_pack(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_serp_local_pack_query ON serp_local_pack(query_id);
CREATE INDEX IF NOT EXISTS idx_serp_local_pack_position ON serp_local_pack(snapshot_id, position);
CREATE INDEX IF NOT EXISTS idx_serp_local_pack_city ON serp_local_pack(city);
CREATE INDEX IF NOT EXISTS idx_serp_local_pack_captured ON serp_local_pack(captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_serp_local_pack_business ON serp_local_pack(business_name);

-- Comment on table
COMMENT ON TABLE serp_local_pack IS 'Stores Google Maps local pack results from SERP snapshots';
COMMENT ON COLUMN serp_local_pack.position IS '1-based position in the local pack (usually 1-3)';
COMMENT ON COLUMN serp_local_pack.price_level IS 'Number of $ symbols (0-4) indicating price range';
