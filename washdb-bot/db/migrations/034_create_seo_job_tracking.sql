-- Migration: 034_create_seo_job_tracking.sql
-- Description: Create SEO job tracking table for detailed job history and monitoring
-- Date: 2025-12-18

CREATE TABLE IF NOT EXISTS seo_job_tracking (
    tracking_id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    module_name VARCHAR(50) NOT NULL,  -- 'technical_audit', 'core_vitals', 'backlinks', etc.
    run_type VARCHAR(20) NOT NULL,     -- 'initial', 'quarterly', 'deep_refresh', 'retry'
    status VARCHAR(20) DEFAULT 'pending',  -- pending, running, completed, failed, skipped
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    duration_seconds FLOAT,
    records_created INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    error_message TEXT,
    error_traceback TEXT,
    retry_count INTEGER DEFAULT 0,
    metadata JSONB DEFAULT '{}',  -- Module-specific results summary
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_seo_tracking_company ON seo_job_tracking(company_id);
CREATE INDEX IF NOT EXISTS idx_seo_tracking_status ON seo_job_tracking(status);
CREATE INDEX IF NOT EXISTS idx_seo_tracking_module ON seo_job_tracking(module_name);
CREATE INDEX IF NOT EXISTS idx_seo_tracking_run_type ON seo_job_tracking(run_type);
CREATE INDEX IF NOT EXISTS idx_seo_tracking_created ON seo_job_tracking(created_at DESC);

-- Composite index for finding incomplete jobs
CREATE INDEX IF NOT EXISTS idx_seo_tracking_incomplete
ON seo_job_tracking(company_id, module_name)
WHERE status IN ('pending', 'running');

-- Composite index for finding failed jobs needing retry
CREATE INDEX IF NOT EXISTS idx_seo_tracking_failed_retry
ON seo_job_tracking(company_id, module_name, retry_count)
WHERE status = 'failed' AND retry_count < 3;

-- Table comments
COMMENT ON TABLE seo_job_tracking IS 'Detailed tracking of SEO module job executions for each company';
COMMENT ON COLUMN seo_job_tracking.module_name IS 'One of: technical_audit, core_vitals, backlinks, citations, competitors, serp, autocomplete, keyword_intel, competitive_analysis';
COMMENT ON COLUMN seo_job_tracking.run_type IS 'initial=first run, quarterly=scheduled refresh, deep_refresh=expanded scope, retry=error recovery';
COMMENT ON COLUMN seo_job_tracking.metadata IS 'JSON with module-specific stats like {score: 85, pages_crawled: 10, keywords_found: 25}';

-- Create trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_seo_job_tracking_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_seo_job_tracking_updated ON seo_job_tracking;
CREATE TRIGGER trigger_seo_job_tracking_updated
    BEFORE UPDATE ON seo_job_tracking
    FOR EACH ROW
    EXECUTE FUNCTION update_seo_job_tracking_timestamp();
