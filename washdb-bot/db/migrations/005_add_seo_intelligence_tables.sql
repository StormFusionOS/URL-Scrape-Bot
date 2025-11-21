-- Migration: Add SEO Intelligence System Tables
-- This migration creates 12 tables for AI-powered SEO intelligence tracking
--
-- Table Groups:
-- 1. SERP Tracking: search_queries, serp_snapshots, serp_results
-- 2. Competitor Analysis: competitors, competitor_pages
-- 3. Backlinks & Authority: backlinks, referring_domains
-- 4. Citations: citations
-- 5. Technical Audits: page_audits, audit_issues
-- 6. Governance: change_log, task_logs

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

CREATE INDEX idx_search_queries_active ON search_queries(is_active);
CREATE INDEX idx_search_queries_text ON search_queries(query_text);
CREATE INDEX idx_search_queries_metadata ON search_queries USING GIN(metadata);

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

CREATE INDEX idx_serp_snapshots_query ON serp_snapshots(query_id);
CREATE INDEX idx_serp_snapshots_captured ON serp_snapshots(captured_at DESC);
CREATE INDEX idx_serp_snapshots_hash ON serp_snapshots(snapshot_hash);
CREATE INDEX idx_serp_snapshots_metadata ON serp_snapshots USING GIN(metadata);

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

CREATE INDEX idx_serp_results_snapshot ON serp_results(snapshot_id);
CREATE INDEX idx_serp_results_position ON serp_results(position);
CREATE INDEX idx_serp_results_domain ON serp_results(domain);
CREATE INDEX idx_serp_results_competitor ON serp_results(competitor_id) WHERE competitor_id IS NOT NULL;
CREATE INDEX idx_serp_results_metadata ON serp_results USING GIN(metadata);

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

CREATE INDEX idx_competitors_domain ON competitors(domain);
CREATE INDEX idx_competitors_active ON competitors(is_active);
CREATE INDEX idx_competitors_location ON competitors(location);
CREATE INDEX idx_competitors_metadata ON competitors USING GIN(metadata);

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

CREATE INDEX idx_competitor_pages_competitor ON competitor_pages(competitor_id);
CREATE INDEX idx_competitor_pages_url ON competitor_pages(url);
CREATE INDEX idx_competitor_pages_type ON competitor_pages(page_type);
CREATE INDEX idx_competitor_pages_crawled ON competitor_pages(crawled_at DESC);
CREATE INDEX idx_competitor_pages_hash ON competitor_pages(content_hash);
CREATE INDEX idx_competitor_pages_schema ON competitor_pages USING GIN(schema_markup);

-- ============================================================================
-- 3. BACKLINKS & AUTHORITY TABLES
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

CREATE INDEX idx_backlinks_target_domain ON backlinks(target_domain);
CREATE INDEX idx_backlinks_source_domain ON backlinks(source_domain);
CREATE INDEX idx_backlinks_active ON backlinks(is_active);
CREATE INDEX idx_backlinks_discovered ON backlinks(discovered_at DESC);
CREATE INDEX idx_backlinks_metadata ON backlinks USING GIN(metadata);

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

CREATE INDEX idx_referring_domains_domain ON referring_domains(domain);
CREATE INDEX idx_referring_domains_las ON referring_domains(local_authority_score DESC);
CREATE INDEX idx_referring_domains_backlinks ON referring_domains(total_backlinks DESC);
CREATE INDEX idx_referring_domains_metadata ON referring_domains USING GIN(metadata);

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

CREATE INDEX idx_citations_directory ON citations(directory_name);
CREATE INDEX idx_citations_nap_score ON citations(nap_match_score DESC);
CREATE INDEX idx_citations_claimed ON citations(is_claimed);
CREATE INDEX idx_citations_discovered ON citations(discovered_at DESC);
CREATE INDEX idx_citations_metadata ON citations USING GIN(metadata);

-- ============================================================================
-- 5. TECHNICAL AUDIT TABLES
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

CREATE INDEX idx_page_audits_url ON page_audits(url);
CREATE INDEX idx_page_audits_type ON page_audits(audit_type);
CREATE INDEX idx_page_audits_score ON page_audits(overall_score DESC);
CREATE INDEX idx_page_audits_audited ON page_audits(audited_at DESC);
CREATE INDEX idx_page_audits_metadata ON page_audits USING GIN(metadata);

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

CREATE INDEX idx_audit_issues_audit ON audit_issues(audit_id);
CREATE INDEX idx_audit_issues_severity ON audit_issues(severity);
CREATE INDEX idx_audit_issues_category ON audit_issues(category);
CREATE INDEX idx_audit_issues_type ON audit_issues(issue_type);
CREATE INDEX idx_audit_issues_metadata ON audit_issues USING GIN(metadata);

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

CREATE INDEX idx_change_log_table ON change_log(table_name);
CREATE INDEX idx_change_log_status ON change_log(status);
CREATE INDEX idx_change_log_proposed ON change_log(proposed_at DESC);
CREATE INDEX idx_change_log_reviewed ON change_log(reviewed_at DESC);
CREATE INDEX idx_change_log_metadata ON change_log USING GIN(metadata);

-- Task logs (execution tracking for all scraper tasks)
-- Supports partitioning by started_at for performance
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

CREATE INDEX idx_task_logs_name ON task_logs(task_name);
CREATE INDEX idx_task_logs_status ON task_logs(status);
CREATE INDEX idx_task_logs_started ON task_logs(started_at DESC);
CREATE INDEX idx_task_logs_completed ON task_logs(completed_at DESC);
CREATE INDEX idx_task_logs_metadata ON task_logs USING GIN(metadata);

-- ============================================================================
-- TABLE COMMENTS
-- ============================================================================

COMMENT ON TABLE search_queries IS 'SERP monitoring queries with location targeting';
COMMENT ON TABLE serp_snapshots IS 'Time-series SERP snapshot data with change detection';
COMMENT ON TABLE serp_results IS 'Individual SERP result entries with position tracking';
COMMENT ON TABLE competitors IS 'Competitor business directory with domain tracking';
COMMENT ON TABLE competitor_pages IS 'Competitor page snapshots with content hashing';
COMMENT ON TABLE backlinks IS 'Inbound link tracking with anchor text analysis';
COMMENT ON TABLE referring_domains IS 'Domain-level authority metrics and LAS scores';
COMMENT ON TABLE citations IS 'Business directory citations with NAP matching';
COMMENT ON TABLE page_audits IS 'Technical/accessibility audit results';
COMMENT ON TABLE audit_issues IS 'Individual audit findings and recommendations';
COMMENT ON TABLE change_log IS 'Review-mode governance for all data changes';
COMMENT ON TABLE task_logs IS 'Execution tracking for all scraper tasks';

-- ============================================================================
-- NOTES ON FUTURE ENHANCEMENTS
-- ============================================================================

-- Time-series partitioning for serp_snapshots:
-- CREATE TABLE serp_snapshots_2025_01 PARTITION OF serp_snapshots
--     FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');

-- Time-series partitioning for task_logs:
-- CREATE TABLE task_logs_2025_01 PARTITION OF task_logs
--     FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');

-- Full-text search on competitor pages:
-- CREATE INDEX idx_competitor_pages_fulltext ON competitor_pages
--     USING gin(to_tsvector('english', title || ' ' || meta_description));
