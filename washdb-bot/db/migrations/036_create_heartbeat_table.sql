-- Migration: 036_create_heartbeat_table.sql
-- Description: Create heartbeat table for background job health monitoring
-- Date: 2025-12-18

CREATE TABLE IF NOT EXISTS job_heartbeats (
    heartbeat_id SERIAL PRIMARY KEY,
    worker_name VARCHAR(100) NOT NULL UNIQUE,
    worker_type VARCHAR(50) NOT NULL,  -- 'seo_orchestrator', 'verification', etc.
    status VARCHAR(20) DEFAULT 'running',  -- running, stopped, failed, stale
    last_heartbeat TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP DEFAULT NOW(),
    pid INTEGER,
    hostname VARCHAR(255),

    -- Stats
    companies_processed INTEGER DEFAULT 0,
    jobs_completed INTEGER DEFAULT 0,
    jobs_failed INTEGER DEFAULT 0,
    current_company_id INTEGER,
    current_module VARCHAR(50),

    -- Performance metrics
    avg_job_duration_seconds FLOAT,
    last_error TEXT,
    last_error_at TIMESTAMP,

    -- Metadata
    config JSONB DEFAULT '{}',  -- Worker configuration snapshot
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Index for health checks
CREATE INDEX IF NOT EXISTS idx_heartbeat_worker ON job_heartbeats(worker_name);
CREATE INDEX IF NOT EXISTS idx_heartbeat_last ON job_heartbeats(last_heartbeat);
CREATE INDEX IF NOT EXISTS idx_heartbeat_status ON job_heartbeats(status);

-- Index for finding stale workers (no heartbeat in last 5 minutes)
CREATE INDEX IF NOT EXISTS idx_heartbeat_stale
ON job_heartbeats(last_heartbeat)
WHERE status = 'running';

-- Table comments
COMMENT ON TABLE job_heartbeats IS 'Health monitoring for background job workers';
COMMENT ON COLUMN job_heartbeats.worker_name IS 'Unique identifier for this worker instance';
COMMENT ON COLUMN job_heartbeats.last_heartbeat IS 'Updated every 30 seconds while worker is running';
COMMENT ON COLUMN job_heartbeats.status IS 'running=active, stopped=graceful shutdown, failed=crashed, stale=no heartbeat';

-- Create trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_job_heartbeats_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_job_heartbeats_updated ON job_heartbeats;
CREATE TRIGGER trigger_job_heartbeats_updated
    BEFORE UPDATE ON job_heartbeats
    FOR EACH ROW
    EXECUTE FUNCTION update_job_heartbeats_timestamp();
