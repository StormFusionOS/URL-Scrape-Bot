-- Migration: 044_create_system_errors_table.sql
-- Description: Create system_errors table for centralized error tracking and AI troubleshooting
-- Date: 2025-12-27

-- Drop existing if needed (for development)
-- DROP TABLE IF EXISTS system_errors CASCADE;
-- DROP TABLE IF EXISTS healing_actions CASCADE;

-- =============================================================================
-- SYSTEM ERRORS TABLE
-- =============================================================================
-- Centralized error tracking for all washdb-bot services
-- Optimized for AI troubleshooting with structured context

CREATE TABLE IF NOT EXISTS system_errors (
    error_id SERIAL PRIMARY KEY,

    -- Identification
    timestamp TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    service_name VARCHAR(100) NOT NULL,      -- 'seo_worker', 'yp_scraper', 'google_scraper', 'verification', 'browser_pool', 'xvfb', 'system'
    component VARCHAR(100),                   -- Sub-component within service (e.g., 'backlink_crawler', 'warmup')
    error_code VARCHAR(50),                   -- Standardized error code (e.g., 'CHROME_CRASH', 'DB_TIMEOUT', 'CAPTCHA_DETECTED')

    -- Severity Classification
    severity VARCHAR(20) NOT NULL DEFAULT 'error',  -- 'critical', 'error', 'warning', 'info'

    -- Error Details (AI-Friendly)
    message TEXT NOT NULL,                    -- Human-readable error summary
    stack_trace TEXT,                         -- Full Python traceback
    error_type VARCHAR(200),                  -- Python exception class name (e.g., 'TimeoutError', 'ConnectionError')

    -- Context for Troubleshooting (JSONB for flexibility)
    context JSONB DEFAULT '{}',               -- Structured context: {company_id, module, url, retry_count, proxy, etc.}
    system_state JSONB DEFAULT '{}',          -- Snapshot: {chrome_count, memory_mb, cpu_percent, active_leases, xvfb_running}

    -- Resolution Tracking
    resolved BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMPTZ,
    resolution_action VARCHAR(100),           -- Action taken: 'auto_restart', 'chrome_cleanup', 'xvfb_restart', 'manual', etc.
    resolution_notes TEXT,                    -- Human notes about what fixed it
    auto_resolved BOOLEAN DEFAULT FALSE,      -- Was this resolved by self-healing?

    -- Deduplication & Correlation
    error_hash VARCHAR(64),                   -- SHA-256 of (service + error_code + message[:100]) for dedup
    first_occurrence_id INTEGER,              -- FK to first error in this group (for recurring errors)
    occurrence_count INTEGER DEFAULT 1,       -- How many times this exact error occurred (incremented on dedup)

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- HEALING ACTIONS TABLE
-- =============================================================================
-- Track all self-healing actions taken by the system

CREATE TABLE IF NOT EXISTS healing_actions (
    action_id SERIAL PRIMARY KEY,

    -- Action Details
    timestamp TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    action_type VARCHAR(50) NOT NULL,         -- 'chrome_cleanup', 'xvfb_restart', 'restart_service', etc.
    target_service VARCHAR(100),              -- Service that was targeted (if applicable)
    trigger_type VARCHAR(20) NOT NULL,        -- 'auto', 'manual', 'escalation'
    trigger_reason TEXT,                      -- Why this action was triggered

    -- Pattern that triggered (if auto)
    triggered_by_pattern VARCHAR(100),        -- Pattern ID that triggered this action
    triggered_by_error_id INTEGER,            -- FK to the error that triggered this (if applicable)

    -- Results
    success BOOLEAN,
    result_message TEXT,
    duration_seconds FLOAT,

    -- Escalation tracking
    escalated_from_action_id INTEGER,         -- FK to previous action if this is an escalation
    escalated_to_action_id INTEGER,           -- FK to next action if this escalated

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- INDEXES
-- =============================================================================

-- Primary query patterns for system_errors
CREATE INDEX IF NOT EXISTS idx_system_errors_timestamp ON system_errors(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_system_errors_service ON system_errors(service_name);
CREATE INDEX IF NOT EXISTS idx_system_errors_severity ON system_errors(severity);
CREATE INDEX IF NOT EXISTS idx_system_errors_resolved ON system_errors(resolved);
CREATE INDEX IF NOT EXISTS idx_system_errors_hash ON system_errors(error_hash);
CREATE INDEX IF NOT EXISTS idx_system_errors_code ON system_errors(error_code);

-- Composite index for unresolved errors by service (common dashboard query)
CREATE INDEX IF NOT EXISTS idx_system_errors_unresolved
ON system_errors(service_name, severity, timestamp DESC)
WHERE resolved = FALSE;

-- GIN index for JSONB context queries (e.g., find errors for specific company)
CREATE INDEX IF NOT EXISTS idx_system_errors_context ON system_errors USING GIN(context);

-- Partial index for critical errors needing attention
CREATE INDEX IF NOT EXISTS idx_system_errors_critical
ON system_errors(timestamp DESC)
WHERE severity = 'critical' AND resolved = FALSE;

-- Healing actions indexes
CREATE INDEX IF NOT EXISTS idx_healing_actions_timestamp ON healing_actions(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_healing_actions_type ON healing_actions(action_type);
CREATE INDEX IF NOT EXISTS idx_healing_actions_trigger ON healing_actions(trigger_type);

-- =============================================================================
-- FOREIGN KEYS
-- =============================================================================

-- Self-referential FK for error grouping (first occurrence)
ALTER TABLE system_errors
ADD CONSTRAINT fk_first_occurrence
FOREIGN KEY (first_occurrence_id) REFERENCES system_errors(error_id) ON DELETE SET NULL;

-- Healing action escalation chain
ALTER TABLE healing_actions
ADD CONSTRAINT fk_escalated_from
FOREIGN KEY (escalated_from_action_id) REFERENCES healing_actions(action_id) ON DELETE SET NULL;

ALTER TABLE healing_actions
ADD CONSTRAINT fk_triggered_by_error
FOREIGN KEY (triggered_by_error_id) REFERENCES system_errors(error_id) ON DELETE SET NULL;

-- =============================================================================
-- TRIGGERS
-- =============================================================================

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_system_errors_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_system_errors_updated ON system_errors;
CREATE TRIGGER trigger_system_errors_updated
    BEFORE UPDATE ON system_errors
    FOR EACH ROW
    EXECUTE FUNCTION update_system_errors_timestamp();

-- =============================================================================
-- VIEWS
-- =============================================================================

-- View for dashboard: recent unresolved errors
CREATE OR REPLACE VIEW v_recent_errors AS
SELECT
    error_id,
    timestamp,
    service_name,
    component,
    severity,
    error_code,
    message,
    error_type,
    context,
    occurrence_count,
    resolved,
    auto_resolved
FROM system_errors
WHERE timestamp > NOW() - INTERVAL '24 hours'
ORDER BY
    CASE severity
        WHEN 'critical' THEN 1
        WHEN 'error' THEN 2
        WHEN 'warning' THEN 3
        ELSE 4
    END,
    timestamp DESC;

-- View for AI export: formatted for easy copy/paste
CREATE OR REPLACE VIEW v_errors_for_ai AS
SELECT
    error_id,
    timestamp,
    service_name,
    severity,
    error_code,
    message,
    error_type,
    LEFT(stack_trace, 3000) as stack_trace_preview,
    context,
    system_state,
    resolved,
    resolution_action,
    resolution_notes,
    occurrence_count
FROM system_errors
ORDER BY timestamp DESC;

-- View for healing action history
CREATE OR REPLACE VIEW v_healing_history AS
SELECT
    h.action_id,
    h.timestamp,
    h.action_type,
    h.target_service,
    h.trigger_type,
    h.trigger_reason,
    h.success,
    h.result_message,
    h.duration_seconds,
    e.message as triggered_by_error
FROM healing_actions h
LEFT JOIN system_errors e ON h.triggered_by_error_id = e.error_id
ORDER BY h.timestamp DESC;

-- =============================================================================
-- FUNCTIONS
-- =============================================================================

-- Function to export recent errors in AI-friendly format
CREATE OR REPLACE FUNCTION export_errors_for_ai(hours_back INTEGER DEFAULT 24, max_errors INTEGER DEFAULT 50)
RETURNS TABLE(error_report TEXT) AS $$
BEGIN
    RETURN QUERY
    SELECT
        format(E'## Error #%s\n**Time:** %s\n**Service:** %s | **Severity:** %s | **Code:** %s\n**Message:** %s\n\n### Stack Trace\n```\n%s\n```\n\n### Context\n```json\n%s\n```\n\n### System State\n```json\n%s\n```\n\n---\n',
            se.error_id,
            se.timestamp::TEXT,
            se.service_name,
            UPPER(se.severity),
            COALESCE(se.error_code, 'N/A'),
            se.message,
            COALESCE(LEFT(se.stack_trace, 2000), 'No stack trace'),
            COALESCE(se.context::TEXT, '{}'),
            COALESCE(se.system_state::TEXT, '{}')
        )
    FROM system_errors se
    WHERE se.timestamp > NOW() - (hours_back || ' hours')::INTERVAL
    ORDER BY se.timestamp DESC
    LIMIT max_errors;
END;
$$ LANGUAGE plpgsql;

-- Function to get error stats by service (for dashboard)
CREATE OR REPLACE FUNCTION get_error_stats_by_service(hours_back INTEGER DEFAULT 24)
RETURNS TABLE(
    service_name VARCHAR,
    total_errors BIGINT,
    critical_count BIGINT,
    error_count BIGINT,
    warning_count BIGINT,
    unresolved_count BIGINT,
    auto_resolved_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        se.service_name,
        COUNT(*) as total_errors,
        COUNT(*) FILTER (WHERE se.severity = 'critical') as critical_count,
        COUNT(*) FILTER (WHERE se.severity = 'error') as error_count,
        COUNT(*) FILTER (WHERE se.severity = 'warning') as warning_count,
        COUNT(*) FILTER (WHERE se.resolved = FALSE) as unresolved_count,
        COUNT(*) FILTER (WHERE se.auto_resolved = TRUE) as auto_resolved_count
    FROM system_errors se
    WHERE se.timestamp > NOW() - (hours_back || ' hours')::INTERVAL
    GROUP BY se.service_name
    ORDER BY total_errors DESC;
END;
$$ LANGUAGE plpgsql;

-- Function to mark error as resolved
CREATE OR REPLACE FUNCTION resolve_error(
    p_error_id INTEGER,
    p_resolution_action VARCHAR DEFAULT 'manual',
    p_resolution_notes TEXT DEFAULT NULL,
    p_auto_resolved BOOLEAN DEFAULT FALSE
)
RETURNS BOOLEAN AS $$
BEGIN
    UPDATE system_errors
    SET resolved = TRUE,
        resolved_at = NOW(),
        resolution_action = p_resolution_action,
        resolution_notes = p_resolution_notes,
        auto_resolved = p_auto_resolved
    WHERE error_id = p_error_id;

    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- COMMENTS
-- =============================================================================

COMMENT ON TABLE system_errors IS 'Centralized error tracking for all washdb-bot services, optimized for AI troubleshooting';
COMMENT ON COLUMN system_errors.error_hash IS 'SHA-256 hash for deduplication: sha256(service + error_code + message[:100])';
COMMENT ON COLUMN system_errors.system_state IS 'Snapshot of system state at error time: chrome_count, memory, cpu, xvfb status';
COMMENT ON COLUMN system_errors.context IS 'Structured context: company_id, module, url, browser_type, proxy, retry_count, etc.';
COMMENT ON COLUMN system_errors.occurrence_count IS 'Incremented when duplicate error (same hash) occurs within dedup window';

COMMENT ON TABLE healing_actions IS 'Audit log of all self-healing actions taken by the system';
COMMENT ON COLUMN healing_actions.trigger_type IS 'How action was triggered: auto (pattern match), manual (GUI), escalation';

-- =============================================================================
-- SAMPLE DATA (for testing - comment out in production)
-- =============================================================================

-- INSERT INTO system_errors (service_name, component, error_code, severity, message, context, system_state)
-- VALUES
--     ('browser_pool', 'warmup', 'CHROME_CRASH', 'error', 'Chrome process died during warmup',
--      '{"session_id": "abc123", "url": "https://google.com"}',
--      '{"chrome_count": 45, "memory_mb": 8000, "xvfb_running": true}'),
--     ('seo_worker', 'backlink_crawler', 'TIMEOUT', 'warning', 'Request timeout after 30s',
--      '{"company_id": 12345, "domain": "example.com"}',
--      '{"chrome_count": 32, "memory_mb": 6500, "xvfb_running": true}');
