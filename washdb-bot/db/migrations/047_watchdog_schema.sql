-- Migration: Watchdog Schema Extensions
-- Date: 2026-01-02
-- Description: Add columns and tables for enterprise watchdog service

-- ============================================================================
-- EXTEND job_heartbeats TABLE
-- ============================================================================

-- Add service_unit column for systemd restart actions
ALTER TABLE job_heartbeats ADD COLUMN IF NOT EXISTS service_unit VARCHAR(100);

-- Add browser/chrome process tracking for resource monitoring
ALTER TABLE job_heartbeats ADD COLUMN IF NOT EXISTS browser_session_count INTEGER DEFAULT 0;
ALTER TABLE job_heartbeats ADD COLUMN IF NOT EXISTS chrome_processes INTEGER DEFAULT 0;
ALTER TABLE job_heartbeats ADD COLUMN IF NOT EXISTS memory_mb INTEGER;

-- Index for watchdog stale detection queries
CREATE INDEX IF NOT EXISTS idx_heartbeat_active
ON job_heartbeats(worker_type, status, last_heartbeat)
WHERE status = 'running';

-- ============================================================================
-- CREATE watchdog_events TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS watchdog_events (
    event_id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT NOW(),

    -- Event classification
    event_type VARCHAR(50) NOT NULL,  -- 'stale_detected', 'resource_warning', 'resource_critical', 'healing_triggered', 'recovery_verified'
    severity VARCHAR(20) DEFAULT 'info',  -- 'info', 'warning', 'error', 'critical'

    -- Target information
    target_service VARCHAR(100),  -- systemd unit name or worker_name
    target_worker_type VARCHAR(50),

    -- Event details
    details JSONB,  -- { "chrome_count": 500, "threshold": 432, ... }

    -- Action taken (if any)
    action_taken VARCHAR(100),  -- HealingAction value
    action_success BOOLEAN,
    action_duration_seconds FLOAT,

    -- Related errors (for correlation)
    related_error_ids INTEGER[],

    -- Resolution tracking
    resolved BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMP,
    resolution_notes TEXT
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_watchdog_events_timestamp ON watchdog_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_watchdog_events_type ON watchdog_events(event_type);
CREATE INDEX IF NOT EXISTS idx_watchdog_events_target ON watchdog_events(target_service);
CREATE INDEX IF NOT EXISTS idx_watchdog_events_unresolved ON watchdog_events(resolved, timestamp) WHERE resolved = FALSE;

-- ============================================================================
-- ADD STANDARDIZATION to ServiceName enum if using system_errors table
-- ============================================================================

-- Add STANDARDIZATION to service name if not exists
-- (Using separate ALTER TYPE statements for safety)
DO $$
BEGIN
    -- Check if system_errors table exists and has service_name column
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'system_errors' AND column_name = 'service_name'
    ) THEN
        -- The column exists, it's likely VARCHAR so no ALTER TYPE needed
        NULL;
    END IF;
END $$;

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Function to get stale workers
CREATE OR REPLACE FUNCTION get_stale_workers(stale_threshold_minutes INTEGER DEFAULT 5)
RETURNS TABLE (
    worker_name VARCHAR,
    worker_type VARCHAR,
    service_unit VARCHAR,
    last_heartbeat TIMESTAMP,
    minutes_since_heartbeat FLOAT,
    current_company_id INTEGER,
    current_module VARCHAR
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        jh.worker_name,
        jh.worker_type,
        jh.service_unit,
        jh.last_heartbeat,
        EXTRACT(EPOCH FROM (NOW() - jh.last_heartbeat)) / 60.0 as minutes_since_heartbeat,
        jh.current_company_id,
        jh.current_module
    FROM job_heartbeats jh
    WHERE jh.status = 'running'
    AND jh.last_heartbeat < NOW() - (stale_threshold_minutes || ' minutes')::INTERVAL
    ORDER BY jh.last_heartbeat ASC;
END;
$$ LANGUAGE plpgsql;

-- Function to get watchdog summary (for dashboard)
CREATE OR REPLACE FUNCTION get_watchdog_summary(hours INTEGER DEFAULT 24)
RETURNS TABLE (
    total_events BIGINT,
    stale_detections BIGINT,
    healing_actions BIGINT,
    successful_heals BIGINT,
    failed_heals BIGINT,
    active_workers BIGINT,
    stale_workers BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        (SELECT COUNT(*) FROM watchdog_events
         WHERE timestamp > NOW() - (hours || ' hours')::INTERVAL) as total_events,

        (SELECT COUNT(*) FROM watchdog_events
         WHERE event_type = 'stale_detected'
         AND timestamp > NOW() - (hours || ' hours')::INTERVAL) as stale_detections,

        (SELECT COUNT(*) FROM watchdog_events
         WHERE event_type = 'healing_triggered'
         AND timestamp > NOW() - (hours || ' hours')::INTERVAL) as healing_actions,

        (SELECT COUNT(*) FROM watchdog_events
         WHERE event_type = 'healing_triggered'
         AND action_success = TRUE
         AND timestamp > NOW() - (hours || ' hours')::INTERVAL) as successful_heals,

        (SELECT COUNT(*) FROM watchdog_events
         WHERE event_type = 'healing_triggered'
         AND action_success = FALSE
         AND timestamp > NOW() - (hours || ' hours')::INTERVAL) as failed_heals,

        (SELECT COUNT(*) FROM job_heartbeats
         WHERE status = 'running'
         AND last_heartbeat > NOW() - INTERVAL '5 minutes') as active_workers,

        (SELECT COUNT(*) FROM job_heartbeats
         WHERE status = 'running'
         AND last_heartbeat < NOW() - INTERVAL '5 minutes') as stale_workers;
END;
$$ LANGUAGE plpgsql;

-- Add comment explaining the watchdog system
COMMENT ON TABLE watchdog_events IS 'Logs all watchdog events including stale detection, resource warnings, and healing actions';
COMMENT ON COLUMN job_heartbeats.service_unit IS 'systemd unit name for restart actions (e.g., washdb-standardization-browser)';
