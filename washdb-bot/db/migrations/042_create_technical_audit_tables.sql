-- Migration: 042_create_technical_audit_tables.sql
-- Description: Create tables for storing technical SEO audit and Core Web Vitals results
-- Date: 2025-12-23

-- Technical audit results (main audit table)
CREATE TABLE IF NOT EXISTS technical_audits (
    audit_id SERIAL PRIMARY KEY,
    url TEXT NOT NULL,
    company_id INTEGER REFERENCES companies(id),

    -- Overall scores
    overall_score INTEGER,
    audit_type VARCHAR(50) DEFAULT 'technical',

    -- Core Web Vitals metrics
    lcp_ms INTEGER,      -- Largest Contentful Paint
    fid_ms INTEGER,      -- First Input Delay
    cls_value DECIMAL(6,4),  -- Cumulative Layout Shift
    fcp_ms INTEGER,      -- First Contentful Paint
    ttfb_ms INTEGER,     -- Time to First Byte
    tti_ms INTEGER,      -- Time to Interactive
    cwv_score INTEGER,   -- CWV composite score

    -- CWV ratings (good/needs_improvement/poor)
    lcp_rating VARCHAR(20),
    cls_rating VARCHAR(20),
    fid_rating VARCHAR(20),

    -- Page metrics
    page_load_time_ms INTEGER,
    page_size_kb INTEGER,
    total_requests INTEGER,

    -- Additional metadata
    metadata JSONB,
    audited_at TIMESTAMP DEFAULT NOW(),

    -- Constraints
    CONSTRAINT chk_score_range CHECK (overall_score >= 0 AND overall_score <= 100)
);

-- Audit issues (individual problems found during audit)
CREATE TABLE IF NOT EXISTS technical_audit_issues (
    issue_id SERIAL PRIMARY KEY,
    audit_id INTEGER NOT NULL REFERENCES technical_audits(audit_id) ON DELETE CASCADE,
    category VARCHAR(100),      -- 'technical', 'seo', 'performance', etc.
    issue_type VARCHAR(100),    -- Specific issue identifier
    severity VARCHAR(20),       -- 'critical', 'high', 'medium', 'low'
    description TEXT,           -- Human-readable description
    element TEXT,               -- DOM element or selector
    recommendation TEXT,        -- How to fix
    metadata JSONB
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_tech_audits_url ON technical_audits(url);
CREATE INDEX IF NOT EXISTS idx_tech_audits_company ON technical_audits(company_id);
CREATE INDEX IF NOT EXISTS idx_tech_audits_date ON technical_audits(audited_at DESC);
CREATE INDEX IF NOT EXISTS idx_tech_audits_score ON technical_audits(overall_score);
CREATE INDEX IF NOT EXISTS idx_tech_audit_issues_audit ON technical_audit_issues(audit_id);
CREATE INDEX IF NOT EXISTS idx_tech_audit_issues_severity ON technical_audit_issues(severity);
CREATE INDEX IF NOT EXISTS idx_tech_audit_issues_category ON technical_audit_issues(category);

-- Comments
COMMENT ON TABLE technical_audits IS 'Stores technical SEO audit and Core Web Vitals results';
COMMENT ON COLUMN technical_audits.cwv_score IS 'Composite Core Web Vitals score (0-100)';
COMMENT ON COLUMN technical_audits.lcp_rating IS 'LCP rating: good (<2.5s), needs_improvement (2.5-4s), poor (>4s)';
COMMENT ON COLUMN technical_audits.cls_rating IS 'CLS rating: good (<0.1), needs_improvement (0.1-0.25), poor (>0.25)';
COMMENT ON COLUMN technical_audits.fid_rating IS 'FID rating: good (<100ms), needs_improvement (100-300ms), poor (>300ms)';
