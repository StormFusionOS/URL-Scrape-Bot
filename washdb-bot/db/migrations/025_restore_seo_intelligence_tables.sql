-- ============================================================================
-- Migration 025: Restore SEO Intelligence Tables
-- ============================================================================
-- Restores the 12 SEO intelligence tables that were removed in migration 006.
-- These tables are required for Phase 2 scraper improvements:
--
-- - task_logs: Required for Task 12 (Telemetry & Health Monitoring)
-- - backlinks, referring_domains: Required for Task 8 (Link Graph Extraction)
-- - page_audits, audit_issues: Required for Task 10 (Render Parity Detection)
-- - search_queries, serp_snapshots, serp_results: Required for Task 13 (SERP enrichment)
-- - competitors, competitor_pages: Required for competitor analysis
-- - citations: Required for citation tracking
-- - change_log: Required for governance
--
-- Based on original migration 005 with minor enhancements for Phase 2.
-- ============================================================================

-- Track this migration
INSERT INTO schema_migrations (version, name, applied_at)
VALUES ('025', 'restore_seo_intelligence_tables', NOW())
ON CONFLICT (version) DO NOTHING;

-- ============================================================================
-- 1. SERP TRACKING TABLES
-- ============================================================================

-- Search queries table (tracks what we're monitoring)
CREATE TABLE IF NOT EXISTS search_queries (
    query_id SERIAL PRIMARY KEY,
    query_text VARCHAR(500) NOT NULL,
    location VARCHAR(200),  -- e.g., "Austin, TX" or "78701"
    search_engine VARCHAR(50) DEFAULT 'google',  -- google, bing, duckduckgo
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    metadata JSONB,  -- Extended metadata (device, language, etc.)

    CONSTRAINT unique_query_location UNIQUE (query_text, location, search_engine)
);

CREATE INDEX IF NOT EXISTS idx_search_queries_active ON search_queries(is_active);
CREATE INDEX IF NOT EXISTS idx_search_queries_text ON search_queries(query_text);
CREATE INDEX IF NOT EXISTS idx_search_queries_metadata ON search_queries USING GIN(metadata);

COMMENT ON TABLE search_queries IS 'SERP monitoring queries with location targeting';

-- SERP snapshots (time-series data)
-- Supports partitioning by captured_at for performance
CREATE TABLE IF NOT EXISTS serp_snapshots (
    snapshot_id SERIAL PRIMARY KEY,
    query_id INTEGER NOT NULL REFERENCES search_queries(query_id) ON DELETE CASCADE,
    captured_at TIMESTAMP DEFAULT NOW(),
    result_count INTEGER,  -- Total results found
    snapshot_hash VARCHAR(64),  -- SHA-256 hash for change detection
    raw_html TEXT,  -- Optional: full HTML snapshot
    metadata JSONB,  -- SERP features, ads, knowledge panels, etc.

    CONSTRAINT fk_serp_query FOREIGN KEY (query_id) REFERENCES search_queries(query_id)
);

CREATE INDEX IF NOT EXISTS idx_serp_snapshots_query ON serp_snapshots(query_id);
CREATE INDEX IF NOT EXISTS idx_serp_snapshots_captured ON serp_snapshots(captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_serp_snapshots_hash ON serp_snapshots(snapshot_hash);
CREATE INDEX IF NOT EXISTS idx_serp_snapshots_metadata ON serp_snapshots USING GIN(metadata);

COMMENT ON TABLE serp_snapshots IS 'Time-series SERP snapshot data with change detection';

-- SERP results (individual result entries)
CREATE TABLE IF NOT EXISTS serp_results (
    result_id SERIAL PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES serp_snapshots(snapshot_id) ON DELETE CASCADE,
    position INTEGER NOT NULL,  -- 1-based ranking position
    url TEXT NOT NULL,
    title TEXT,
    description TEXT,
    domain VARCHAR(500),
    is_our_company BOOLEAN DEFAULT FALSE,  -- Track our own rankings
    is_competitor BOOLEAN DEFAULT FALSE,
    competitor_id INTEGER,  -- FK to competitors table (nullable)
    metadata JSONB,  -- Rich snippets, features, schema markup

    CONSTRAINT fk_serp_snapshot FOREIGN KEY (snapshot_id) REFERENCES serp_snapshots(snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_serp_results_snapshot ON serp_results(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_serp_results_position ON serp_results(position);
CREATE INDEX IF NOT EXISTS idx_serp_results_domain ON serp_results(domain);
CREATE INDEX IF NOT EXISTS idx_serp_results_competitor ON serp_results(competitor_id) WHERE competitor_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_serp_results_metadata ON serp_results USING GIN(metadata);

COMMENT ON TABLE serp_results IS 'Individual SERP result entries with position tracking';

-- ============================================================================
-- 2. COMPETITOR ANALYSIS TABLES
-- ============================================================================

-- Competitors table (track competing businesses)
CREATE TABLE IF NOT EXISTS competitors (
    competitor_id SERIAL PRIMARY KEY,
    name VARCHAR(500) NOT NULL,
    domain VARCHAR(500) NOT NULL UNIQUE,
    website_url TEXT,
    business_type VARCHAR(200),  -- e.g., "pressure washing", "window cleaning"
    location VARCHAR(200),
    is_active BOOLEAN DEFAULT TRUE,
    confidence_score DECIMAL(5,2),  -- 0-100 confidence this is a real competitor
    discovered_at TIMESTAMP DEFAULT NOW(),
    last_crawled_at TIMESTAMP,
    metadata JSONB,  -- Contact info, social links, etc.

    CONSTRAINT unique_competitor_domain UNIQUE (domain)
);

CREATE INDEX IF NOT EXISTS idx_competitors_domain ON competitors(domain);
CREATE INDEX IF NOT EXISTS idx_competitors_active ON competitors(is_active);
CREATE INDEX IF NOT EXISTS idx_competitors_location ON competitors(location);
CREATE INDEX IF NOT EXISTS idx_competitors_metadata ON competitors USING GIN(metadata);

COMMENT ON TABLE competitors IS 'Competitor business directory with domain tracking';

-- Competitor pages (snapshots of competitor pages with change detection)
CREATE TABLE IF NOT EXISTS competitor_pages (
    page_id SERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(competitor_id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    page_type VARCHAR(100),  -- 'homepage', 'services', 'pricing', 'blog', etc.
    title TEXT,
    meta_description TEXT,
    h1_tags TEXT[],  -- Array of H1 tags
    content_hash VARCHAR(64),  -- SHA-256 hash for change detection
    word_count INTEGER,
    crawled_at TIMESTAMP DEFAULT NOW(),
    status_code INTEGER,
    schema_markup JSONB,  -- Extracted schema.org markup
    links JSONB,  -- Internal/external link analysis
    metadata JSONB,  -- Images, videos, CTAs, forms, etc.

    CONSTRAINT fk_competitor FOREIGN KEY (competitor_id) REFERENCES competitors(competitor_id)
);

CREATE INDEX IF NOT EXISTS idx_competitor_pages_competitor ON competitor_pages(competitor_id);
CREATE INDEX IF NOT EXISTS idx_competitor_pages_url ON competitor_pages(url);
CREATE INDEX IF NOT EXISTS idx_competitor_pages_type ON competitor_pages(page_type);
CREATE INDEX IF NOT EXISTS idx_competitor_pages_crawled ON competitor_pages(crawled_at DESC);
CREATE INDEX IF NOT EXISTS idx_competitor_pages_hash ON competitor_pages(content_hash);
CREATE INDEX IF NOT EXISTS idx_competitor_pages_schema ON competitor_pages USING GIN(schema_markup);

COMMENT ON TABLE competitor_pages IS 'Competitor page snapshots with content hashing';

-- ============================================================================
-- 3. BACKLINKS & AUTHORITY TABLES (Required for Task 8)
-- ============================================================================

-- Backlinks table (track inbound links)
CREATE TABLE IF NOT EXISTS backlinks (
    backlink_id SERIAL PRIMARY KEY,
    target_domain VARCHAR(500) NOT NULL,  -- Domain being linked to
    target_url TEXT NOT NULL,  -- Specific page being linked to
    source_domain VARCHAR(500) NOT NULL,  -- Domain of the linking page
    source_url TEXT NOT NULL,  -- Page containing the link
    anchor_text TEXT,
    link_type VARCHAR(50),  -- 'dofollow', 'nofollow', 'sponsored', 'ugc'
    discovered_at TIMESTAMP DEFAULT NOW(),
    last_seen_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE,
    metadata JSONB,  -- Context, position, surrounding text

    CONSTRAINT unique_backlink UNIQUE (target_url, source_url)
);

CREATE INDEX IF NOT EXISTS idx_backlinks_target_domain ON backlinks(target_domain);
CREATE INDEX IF NOT EXISTS idx_backlinks_source_domain ON backlinks(source_domain);
CREATE INDEX IF NOT EXISTS idx_backlinks_active ON backlinks(is_active);
CREATE INDEX IF NOT EXISTS idx_backlinks_discovered ON backlinks(discovered_at DESC);
CREATE INDEX IF NOT EXISTS idx_backlinks_metadata ON backlinks USING GIN(metadata);

COMMENT ON TABLE backlinks IS 'Inbound link tracking with anchor text analysis';

-- Referring domains (aggregate authority metrics)
CREATE TABLE IF NOT EXISTS referring_domains (
    domain_id SERIAL PRIMARY KEY,
    domain VARCHAR(500) NOT NULL UNIQUE,
    total_backlinks INTEGER DEFAULT 0,
    dofollow_count INTEGER DEFAULT 0,
    nofollow_count INTEGER DEFAULT 0,
    local_authority_score DECIMAL(5,2),  -- LAS: 0-100 custom authority metric
    first_seen_at TIMESTAMP DEFAULT NOW(),
    last_updated_at TIMESTAMP DEFAULT NOW(),
    metadata JSONB,  -- Domain age, TLD, industry relevance, etc.

    CONSTRAINT unique_referring_domain UNIQUE (domain)
);

CREATE INDEX IF NOT EXISTS idx_referring_domains_domain ON referring_domains(domain);
CREATE INDEX IF NOT EXISTS idx_referring_domains_las ON referring_domains(local_authority_score DESC);
CREATE INDEX IF NOT EXISTS idx_referring_domains_backlinks ON referring_domains(total_backlinks DESC);
CREATE INDEX IF NOT EXISTS idx_referring_domains_metadata ON referring_domains USING GIN(metadata);

COMMENT ON TABLE referring_domains IS 'Domain-level authority metrics and LAS scores';

-- ============================================================================
-- 4. CITATIONS TABLE
-- ============================================================================

-- Citations (business directory listings)
CREATE TABLE IF NOT EXISTS citations (
    citation_id SERIAL PRIMARY KEY,
    directory_name VARCHAR(500) NOT NULL,  -- e.g., "Yelp", "Yellow Pages", "BBB"
    directory_url TEXT,
    listing_url TEXT,
    business_name VARCHAR(500),
    address TEXT,
    phone VARCHAR(50),
    nap_match_score DECIMAL(5,2),  -- 0-100 consistency score (Name, Address, Phone)
    has_website_link BOOLEAN DEFAULT FALSE,
    is_claimed BOOLEAN DEFAULT FALSE,
    rating DECIMAL(3,2),
    review_count INTEGER,
    discovered_at TIMESTAMP DEFAULT NOW(),
    last_verified_at TIMESTAMP,
    metadata JSONB,  -- Hours, categories, photos, etc.

    CONSTRAINT unique_citation UNIQUE (directory_name, listing_url)
);

CREATE INDEX IF NOT EXISTS idx_citations_directory ON citations(directory_name);
CREATE INDEX IF NOT EXISTS idx_citations_nap_score ON citations(nap_match_score DESC);
CREATE INDEX IF NOT EXISTS idx_citations_claimed ON citations(is_claimed);
CREATE INDEX IF NOT EXISTS idx_citations_discovered ON citations(discovered_at DESC);
CREATE INDEX IF NOT EXISTS idx_citations_metadata ON citations USING GIN(metadata);

COMMENT ON TABLE citations IS 'Business directory citations with NAP matching';

-- ============================================================================
-- 5. TECHNICAL AUDIT TABLES (Required for Task 10)
-- ============================================================================

-- Page audits (technical/accessibility audits of our pages)
CREATE TABLE IF NOT EXISTS page_audits (
    audit_id SERIAL PRIMARY KEY,
    url TEXT NOT NULL,
    audit_type VARCHAR(100),  -- 'technical', 'accessibility', 'performance', 'seo'
    overall_score DECIMAL(5,2),  -- 0-100 aggregate score
    audited_at TIMESTAMP DEFAULT NOW(),
    page_load_time_ms INTEGER,
    page_size_kb INTEGER,
    total_requests INTEGER,
    metadata JSONB  -- Lighthouse scores, Core Web Vitals, etc.
);

CREATE INDEX IF NOT EXISTS idx_page_audits_url ON page_audits(url);
CREATE INDEX IF NOT EXISTS idx_page_audits_type ON page_audits(audit_type);
CREATE INDEX IF NOT EXISTS idx_page_audits_score ON page_audits(overall_score DESC);
CREATE INDEX IF NOT EXISTS idx_page_audits_audited ON page_audits(audited_at DESC);
CREATE INDEX IF NOT EXISTS idx_page_audits_metadata ON page_audits USING GIN(metadata);

COMMENT ON TABLE page_audits IS 'Technical/accessibility audit results';

-- Audit issues (individual findings from audits)
CREATE TABLE IF NOT EXISTS audit_issues (
    issue_id SERIAL PRIMARY KEY,
    audit_id INTEGER NOT NULL REFERENCES page_audits(audit_id) ON DELETE CASCADE,
    severity VARCHAR(50),  -- 'critical', 'warning', 'info'
    category VARCHAR(100),  -- 'meta', 'images', 'links', 'performance', 'accessibility'
    issue_type VARCHAR(200),  -- Specific issue (e.g., "missing_alt_text", "broken_link")
    description TEXT,
    element TEXT,  -- CSS selector or element identifier
    recommendation TEXT,
    metadata JSONB,  -- Additional context, code snippets, etc.

    CONSTRAINT fk_issue_audit FOREIGN KEY (audit_id) REFERENCES page_audits(audit_id)
);

CREATE INDEX IF NOT EXISTS idx_audit_issues_audit ON audit_issues(audit_id);
CREATE INDEX IF NOT EXISTS idx_audit_issues_severity ON audit_issues(severity);
CREATE INDEX IF NOT EXISTS idx_audit_issues_category ON audit_issues(category);
CREATE INDEX IF NOT EXISTS idx_audit_issues_type ON audit_issues(issue_type);
CREATE INDEX IF NOT EXISTS idx_audit_issues_metadata ON audit_issues USING GIN(metadata);

COMMENT ON TABLE audit_issues IS 'Individual audit findings and recommendations';

-- ============================================================================
-- 6. GOVERNANCE TABLES
-- ============================================================================

-- Change log (review-mode governance - all changes go here first)
CREATE TABLE IF NOT EXISTS change_log (
    change_id SERIAL PRIMARY KEY,
    table_name VARCHAR(100) NOT NULL,  -- Which table the change is for
    record_id INTEGER,  -- ID of the record being changed/created
    operation VARCHAR(50) NOT NULL,  -- 'insert', 'update', 'delete'
    proposed_data JSONB NOT NULL,  -- The proposed change data
    status VARCHAR(50) DEFAULT 'pending',  -- 'pending', 'approved', 'rejected'
    reason TEXT,  -- Approval/rejection reason
    proposed_at TIMESTAMP DEFAULT NOW(),
    reviewed_at TIMESTAMP,
    reviewed_by VARCHAR(200),  -- User/system that reviewed
    metadata JSONB,  -- Change context, diff, justification

    CONSTRAINT valid_operation CHECK (operation IN ('insert', 'update', 'delete')),
    CONSTRAINT valid_status CHECK (status IN ('pending', 'approved', 'rejected'))
);

CREATE INDEX IF NOT EXISTS idx_change_log_table ON change_log(table_name);
CREATE INDEX IF NOT EXISTS idx_change_log_status ON change_log(status);
CREATE INDEX IF NOT EXISTS idx_change_log_proposed ON change_log(proposed_at DESC);
CREATE INDEX IF NOT EXISTS idx_change_log_reviewed ON change_log(reviewed_at DESC);
CREATE INDEX IF NOT EXISTS idx_change_log_metadata ON change_log USING GIN(metadata);

COMMENT ON TABLE change_log IS 'Review-mode governance for all data changes';

-- Task logs (execution tracking for all scraper tasks)
-- Supports partitioning by started_at for performance
-- CRITICAL for Task 12: Logging, Telemetry & Health Monitoring
CREATE TABLE IF NOT EXISTS task_logs (
    task_id SERIAL PRIMARY KEY,
    task_name VARCHAR(200) NOT NULL,  -- e.g., "serp_scraper", "competitor_crawler"
    task_type VARCHAR(100),  -- 'scraper', 'analyzer', 'audit'
    status VARCHAR(50) DEFAULT 'running',  -- 'running', 'success', 'failed', 'cancelled'
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    duration_seconds INTEGER,
    records_processed INTEGER DEFAULT 0,
    records_created INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    error_message TEXT,
    metadata JSONB,  -- Parameters, configuration, results summary

    CONSTRAINT valid_task_status CHECK (status IN ('running', 'success', 'failed', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_task_logs_name ON task_logs(task_name);
CREATE INDEX IF NOT EXISTS idx_task_logs_status ON task_logs(status);
CREATE INDEX IF NOT EXISTS idx_task_logs_started ON task_logs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_task_logs_completed ON task_logs(completed_at DESC);
CREATE INDEX IF NOT EXISTS idx_task_logs_metadata ON task_logs USING GIN(metadata);

COMMENT ON TABLE task_logs IS 'Execution tracking for all scraper tasks';

-- ============================================================================
-- HELPER VIEWS FOR TASK 12: Telemetry & Health Monitoring
-- ============================================================================

-- View: Task execution statistics by task name
CREATE OR REPLACE VIEW v_task_stats_by_name AS
SELECT
    task_name,
    COUNT(*) as total_runs,
    COUNT(*) FILTER (WHERE status = 'success') as success_count,
    COUNT(*) FILTER (WHERE status = 'failed') as failed_count,
    COUNT(*) FILTER (WHERE status = 'running') as running_count,
    AVG(duration_seconds) FILTER (WHERE status = 'success') as avg_duration_seconds,
    MAX(started_at) as last_run_at,
    SUM(records_processed) as total_records_processed
FROM task_logs
GROUP BY task_name
ORDER BY last_run_at DESC NULLS LAST;

COMMENT ON VIEW v_task_stats_by_name IS 'Aggregated task execution statistics by task name';

-- View: Recent task failures for alerting
CREATE OR REPLACE VIEW v_recent_task_failures AS
SELECT
    task_id,
    task_name,
    task_type,
    started_at,
    completed_at,
    duration_seconds,
    error_message,
    metadata
FROM task_logs
WHERE
    status = 'failed'
    AND started_at > NOW() - INTERVAL '7 days'
ORDER BY started_at DESC;

COMMENT ON VIEW v_recent_task_failures IS 'Recent task failures for alerting and monitoring';

-- View: Task health summary (last 24 hours)
CREATE OR REPLACE VIEW v_task_health_24h AS
SELECT
    task_name,
    COUNT(*) as runs_24h,
    COUNT(*) FILTER (WHERE status = 'success') as success_24h,
    COUNT(*) FILTER (WHERE status = 'failed') as failed_24h,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE status = 'success') / NULLIF(COUNT(*), 0),
        2
    ) as success_rate_pct,
    AVG(duration_seconds) FILTER (WHERE status = 'success') as avg_duration_seconds,
    MAX(started_at) as last_run_at
FROM task_logs
WHERE started_at > NOW() - INTERVAL '24 hours'
GROUP BY task_name
ORDER BY failed_24h DESC, task_name;

COMMENT ON VIEW v_task_health_24h IS 'Task health summary for last 24 hours with success rates';

-- ============================================================================
-- HELPER FUNCTIONS FOR TASK 12: Health Monitoring
-- ============================================================================

-- Function: Detect error spikes (more than 3 failures in last hour for any task)
CREATE OR REPLACE FUNCTION detect_error_spikes()
RETURNS TABLE (
    task_name VARCHAR(200),
    error_count BIGINT,
    first_error TIMESTAMP,
    last_error TIMESTAMP,
    recent_error_messages TEXT[]
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        tl.task_name,
        COUNT(*) as error_count,
        MIN(tl.started_at) as first_error,
        MAX(tl.started_at) as last_error,
        ARRAY_AGG(tl.error_message ORDER BY tl.started_at DESC) as recent_error_messages
    FROM task_logs tl
    WHERE
        tl.status = 'failed'
        AND tl.started_at > NOW() - INTERVAL '1 hour'
    GROUP BY tl.task_name
    HAVING COUNT(*) >= 3
    ORDER BY error_count DESC;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION detect_error_spikes IS 'Detects tasks with 3+ failures in the last hour';

-- Function: Detect missing runs (tasks that should have run but didn't)
CREATE OR REPLACE FUNCTION detect_missing_runs(
    p_task_name VARCHAR(200),
    p_expected_interval_hours INTEGER DEFAULT 24
)
RETURNS TABLE (
    task_name VARCHAR(200),
    last_run_at TIMESTAMP,
    hours_since_run NUMERIC,
    expected_interval_hours INTEGER,
    is_overdue BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        p_task_name as task_name,
        MAX(tl.started_at) as last_run_at,
        ROUND(
            EXTRACT(EPOCH FROM (NOW() - MAX(tl.started_at))) / 3600,
            2
        ) as hours_since_run,
        p_expected_interval_hours as expected_interval_hours,
        (EXTRACT(EPOCH FROM (NOW() - MAX(tl.started_at))) / 3600) > p_expected_interval_hours as is_overdue
    FROM task_logs tl
    WHERE tl.task_name = p_task_name
    GROUP BY tl.task_name;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION detect_missing_runs IS 'Detects when a task has not run within expected interval';

-- ============================================================================
-- VERIFICATION
-- ============================================================================

DO $$
DECLARE
    table_count INTEGER;
    index_count INTEGER;
    view_count INTEGER;
    function_count INTEGER;
BEGIN
    -- Count tables created
    SELECT COUNT(*) INTO table_count
    FROM information_schema.tables
    WHERE table_name IN (
        'search_queries', 'serp_snapshots', 'serp_results',
        'competitors', 'competitor_pages',
        'backlinks', 'referring_domains',
        'citations',
        'page_audits', 'audit_issues',
        'change_log', 'task_logs'
    );

    -- Count indexes
    SELECT COUNT(*) INTO index_count
    FROM pg_indexes
    WHERE tablename IN (
        'search_queries', 'serp_snapshots', 'serp_results',
        'competitors', 'competitor_pages',
        'backlinks', 'referring_domains',
        'citations',
        'page_audits', 'audit_issues',
        'change_log', 'task_logs'
    );

    -- Count views
    SELECT COUNT(*) INTO view_count
    FROM information_schema.views
    WHERE table_name LIKE 'v_task%';

    -- Count functions
    SELECT COUNT(*) INTO function_count
    FROM information_schema.routines
    WHERE routine_name LIKE 'detect_%';

    RAISE NOTICE 'Migration 025 completed successfully.';
    RAISE NOTICE '  - % SEO intelligence tables restored', table_count;
    RAISE NOTICE '  - % indexes created', index_count;
    RAISE NOTICE '  - % views created', view_count;
    RAISE NOTICE '  - % functions created', function_count;
    RAISE NOTICE '';
    RAISE NOTICE 'Tables restored for Phase 2:';
    RAISE NOTICE '  - task_logs (Task 12: Telemetry)';
    RAISE NOTICE '  - backlinks, referring_domains (Task 8: Link Graph)';
    RAISE NOTICE '  - page_audits, audit_issues (Task 10: Render Parity)';
    RAISE NOTICE '  - search_queries, serp_snapshots, serp_results (Task 13: SERP)';
    RAISE NOTICE '  - competitors, competitor_pages (Competitor Analysis)';
    RAISE NOTICE '  - citations (Citation Tracking)';
    RAISE NOTICE '  - change_log (Governance)';
END $$;
