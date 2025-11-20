-- Migration: Add SEO Intelligence Tables for Canonical AI SEO System
-- Created: 2025-11-20
-- Description: Adds 12 canonical tables for SERP monitoring, competitor tracking,
--              backlinks, citations, technical audits, and governance logging

-- ============================================================================
-- 1. Search Queries - Tracked keywords for SERP monitoring
-- ============================================================================
CREATE TABLE IF NOT EXISTS search_queries (
    id SERIAL PRIMARY KEY,
    query_text TEXT NOT NULL,
    search_engine VARCHAR(50) NOT NULL DEFAULT 'Google',
    locale VARCHAR(10) NOT NULL DEFAULT 'en-US',
    location VARCHAR(255),
    track BOOLEAN NOT NULL DEFAULT TRUE,
    priority INTEGER NOT NULL DEFAULT 2,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_checked TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_search_queries_query_text ON search_queries(query_text);
CREATE INDEX IF NOT EXISTS ix_search_queries_track ON search_queries(track);
CREATE UNIQUE INDEX IF NOT EXISTS ix_query_engine_locale ON search_queries(query_text, search_engine, locale);

COMMENT ON TABLE search_queries IS 'Tracked keywords for SERP monitoring';
COMMENT ON COLUMN search_queries.query_text IS 'Search keyword or phrase';
COMMENT ON COLUMN search_queries.search_engine IS 'Search engine (Google, Bing, etc.)';
COMMENT ON COLUMN search_queries.locale IS 'Locale for search results';
COMMENT ON COLUMN search_queries.location IS 'Geographic location for localized results';
COMMENT ON COLUMN search_queries.track IS 'Whether to actively track this query';
COMMENT ON COLUMN search_queries.priority IS '1=high, 2=medium, 3=low';
COMMENT ON COLUMN search_queries.last_checked IS 'Last SERP capture timestamp';


-- ============================================================================
-- 2. SERP Snapshots - Daily SERP captures per query
-- ============================================================================
CREATE TABLE IF NOT EXISTS serp_snapshots (
    id SERIAL PRIMARY KEY,
    query_id INTEGER NOT NULL REFERENCES search_queries(id) ON DELETE CASCADE,
    snapshot_date TIMESTAMP NOT NULL,
    search_engine VARCHAR(50) NOT NULL DEFAULT 'Google',
    our_rank INTEGER,
    featured_snippet BOOLEAN NOT NULL DEFAULT FALSE,
    featured_snippet_data JSONB,
    paa_questions JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_serp_snapshots_query_id ON serp_snapshots(query_id);
CREATE INDEX IF NOT EXISTS ix_serp_snapshots_snapshot_date ON serp_snapshots(snapshot_date);
CREATE UNIQUE INDEX IF NOT EXISTS ix_serp_query_date ON serp_snapshots(query_id, snapshot_date);

COMMENT ON TABLE serp_snapshots IS 'Daily SERP snapshot for tracked queries';
COMMENT ON COLUMN serp_snapshots.snapshot_date IS 'Date of snapshot (for daily tracking and partitioning)';
COMMENT ON COLUMN serp_snapshots.our_rank IS 'Our ranking position if found in top results';
COMMENT ON COLUMN serp_snapshots.featured_snippet IS 'Whether a featured snippet was present';
COMMENT ON COLUMN serp_snapshots.featured_snippet_data IS 'JSON with featured snippet text, URL, type';
COMMENT ON COLUMN serp_snapshots.paa_questions IS 'JSON array of People Also Ask questions with answers';


-- ============================================================================
-- 3. SERP Results - Individual organic results per snapshot
-- ============================================================================
CREATE TABLE IF NOT EXISTS serp_results (
    id SERIAL PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES serp_snapshots(id) ON DELETE CASCADE,
    rank INTEGER NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    snippet TEXT,
    domain VARCHAR(255) NOT NULL,
    is_ours BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_serp_results_snapshot_id ON serp_results(snapshot_id);
CREATE INDEX IF NOT EXISTS ix_serp_results_domain ON serp_results(domain);
CREATE INDEX IF NOT EXISTS ix_serp_results_is_ours ON serp_results(is_ours);

COMMENT ON TABLE serp_results IS 'Individual SERP result (top 10 organic results per snapshot)';
COMMENT ON COLUMN serp_results.rank IS 'Position in SERP (1-10)';
COMMENT ON COLUMN serp_results.domain IS 'Domain extracted from URL';
COMMENT ON COLUMN serp_results.is_ours IS 'Whether this result belongs to our domain';


-- ============================================================================
-- 4. Competitors - Competitor domain tracking
-- ============================================================================
CREATE TABLE IF NOT EXISTS competitors (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255),
    category VARCHAR(100),
    priority INTEGER NOT NULL DEFAULT 2,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_crawled TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_competitors_domain ON competitors(domain);
CREATE INDEX IF NOT EXISTS ix_competitors_active ON competitors(active);

COMMENT ON TABLE competitors IS 'Competitor domain tracking';
COMMENT ON COLUMN competitors.domain IS 'Competitor domain (e.g., example.com)';
COMMENT ON COLUMN competitors.name IS 'Business/site name';
COMMENT ON COLUMN competitors.category IS 'Business category';
COMMENT ON COLUMN competitors.priority IS '1=high, 2=medium, 3=low';
COMMENT ON COLUMN competitors.active IS 'Whether actively tracking this competitor';
COMMENT ON COLUMN competitors.last_crawled IS 'Last crawl timestamp';


-- ============================================================================
-- 5. Competitor Pages - Page-level data with hashing and snapshots
-- ============================================================================
CREATE TABLE IF NOT EXISTS competitor_pages (
    id SERIAL PRIMARY KEY,
    site_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    page_type VARCHAR(50) NOT NULL DEFAULT 'other',
    meta_title TEXT,
    meta_description TEXT,
    h1_text TEXT,
    h2_text JSONB,
    canonical_url TEXT,
    robots_meta VARCHAR(255),
    last_hash VARCHAR(64),
    last_scraped TIMESTAMP,
    status_code INTEGER,
    data JSONB,
    html_snapshot_path TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_competitor_pages_site_id ON competitor_pages(site_id);
CREATE INDEX IF NOT EXISTS ix_competitor_pages_url ON competitor_pages(url);
CREATE INDEX IF NOT EXISTS ix_competitor_pages_page_type ON competitor_pages(page_type);
CREATE INDEX IF NOT EXISTS ix_competitor_pages_last_hash ON competitor_pages(last_hash);
CREATE INDEX IF NOT EXISTS ix_competitor_pages_last_scraped ON competitor_pages(last_scraped);
CREATE UNIQUE INDEX IF NOT EXISTS ix_competitor_pages_site_url ON competitor_pages(site_id, url);

COMMENT ON TABLE competitor_pages IS 'Competitor page data with hashing, snapshots, and structured data';
COMMENT ON COLUMN competitor_pages.url IS 'Page URL';
COMMENT ON COLUMN competitor_pages.page_type IS 'homepage, service, blog, contact, listing, other';
COMMENT ON COLUMN competitor_pages.h1_text IS 'H1 heading text';
COMMENT ON COLUMN competitor_pages.h2_text IS 'JSON array of H2 headings';
COMMENT ON COLUMN competitor_pages.robots_meta IS 'Robots meta directives (e.g., noindex, nofollow)';
COMMENT ON COLUMN competitor_pages.last_hash IS 'SHA-256 hash of normalized DOM for change detection';
COMMENT ON COLUMN competitor_pages.status_code IS 'HTTP status code from last fetch';
COMMENT ON COLUMN competitor_pages.data IS 'JSONB with structured signals: schema.ld_json[], links.internal[], links.external[], images.alt_coverage, video.embeds[], etc.';
COMMENT ON COLUMN competitor_pages.html_snapshot_path IS 'Path to archived HTML snapshot file';


-- ============================================================================
-- 6. Backlinks - Link tracking (source → target)
-- ============================================================================
CREATE TABLE IF NOT EXISTS backlinks (
    id SERIAL PRIMARY KEY,
    source_url TEXT NOT NULL,
    target_url TEXT NOT NULL,
    source_domain VARCHAR(255) NOT NULL,
    target_domain VARCHAR(255) NOT NULL,
    anchor_text TEXT,
    rel_attr VARCHAR(100),
    position VARCHAR(50) NOT NULL DEFAULT 'unknown',
    first_seen TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_checked TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    alive BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_backlinks_source_url ON backlinks(source_url);
CREATE INDEX IF NOT EXISTS ix_backlinks_target_url ON backlinks(target_url);
CREATE INDEX IF NOT EXISTS ix_backlinks_source_domain ON backlinks(source_domain);
CREATE INDEX IF NOT EXISTS ix_backlinks_target_domain ON backlinks(target_domain);
CREATE INDEX IF NOT EXISTS ix_backlinks_alive ON backlinks(alive);
CREATE UNIQUE INDEX IF NOT EXISTS ix_backlinks_source_target ON backlinks(source_url, target_url);

COMMENT ON TABLE backlinks IS 'Backlink tracking (source → target)';
COMMENT ON COLUMN backlinks.source_url IS 'URL where the link was found';
COMMENT ON COLUMN backlinks.target_url IS 'URL being linked to';
COMMENT ON COLUMN backlinks.source_domain IS 'Source domain for aggregation';
COMMENT ON COLUMN backlinks.target_domain IS 'Target domain';
COMMENT ON COLUMN backlinks.rel_attr IS 'Rel attribute: nofollow, sponsored, ugc, etc.';
COMMENT ON COLUMN backlinks.position IS 'in-body, nav, footer, aside';
COMMENT ON COLUMN backlinks.first_seen IS 'First discovery timestamp';
COMMENT ON COLUMN backlinks.last_checked IS 'Last verification timestamp';
COMMENT ON COLUMN backlinks.alive IS 'Whether link is still present';


-- ============================================================================
-- 7. Referring Domains - Domain-level aggregates for LAS
-- ============================================================================
CREATE TABLE IF NOT EXISTS referring_domains (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(255) UNIQUE NOT NULL,
    backlink_count INTEGER NOT NULL DEFAULT 0,
    inbody_link_count INTEGER NOT NULL DEFAULT 0,
    authority_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    last_updated TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_referring_domains_domain ON referring_domains(domain);
CREATE INDEX IF NOT EXISTS ix_referring_domains_authority_score ON referring_domains(authority_score);

COMMENT ON TABLE referring_domains IS 'Domain-level backlink aggregates for Local Authority Score (LAS)';
COMMENT ON COLUMN referring_domains.domain IS 'Domain being aggregated';
COMMENT ON COLUMN referring_domains.backlink_count IS 'Total backlinks to this domain';
COMMENT ON COLUMN referring_domains.inbody_link_count IS 'Count of in-body links (weighted higher)';
COMMENT ON COLUMN referring_domains.authority_score IS 'Local Authority Score (0-100, normalized)';
COMMENT ON COLUMN referring_domains.last_updated IS 'Last aggregation timestamp';


-- ============================================================================
-- 8. Citations - Directory presence, NAP matching, reviews
-- ============================================================================
CREATE TABLE IF NOT EXISTS citations (
    id SERIAL PRIMARY KEY,
    site_name VARCHAR(100) UNIQUE NOT NULL,
    profile_url TEXT,
    listed BOOLEAN NOT NULL DEFAULT FALSE,
    nap_match BOOLEAN NOT NULL DEFAULT FALSE,
    business_name VARCHAR(255),
    phone VARCHAR(50),
    address TEXT,
    rating DOUBLE PRECISION,
    review_count INTEGER,
    last_audited TIMESTAMP,
    first_seen TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    issues TEXT,
    data JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_citations_site_name ON citations(site_name);
CREATE INDEX IF NOT EXISTS ix_citations_listed ON citations(listed);
CREATE INDEX IF NOT EXISTS ix_citations_last_audited ON citations(last_audited);

COMMENT ON TABLE citations IS 'Citations tracking (directory presence, NAP matching, reviews)';
COMMENT ON COLUMN citations.site_name IS 'Directory name (e.g., Yelp, BBB, Angi)';
COMMENT ON COLUMN citations.profile_url IS 'URL to business profile on directory';
COMMENT ON COLUMN citations.listed IS 'Whether business is listed on this directory';
COMMENT ON COLUMN citations.nap_match IS 'Whether NAP (Name, Address, Phone) matches canonical data';
COMMENT ON COLUMN citations.rating IS 'Average rating (if available)';
COMMENT ON COLUMN citations.review_count IS 'Number of reviews';
COMMENT ON COLUMN citations.last_audited IS 'Last audit timestamp';
COMMENT ON COLUMN citations.first_seen IS 'First discovery timestamp';
COMMENT ON COLUMN citations.issues IS 'Text description of issues (e.g., NAP mismatch details)';
COMMENT ON COLUMN citations.data IS 'JSONB with extended fields (review samples, hours, etc.)';


-- ============================================================================
-- 9. Page Audits - Technical/accessibility audit summaries
-- ============================================================================
CREATE TABLE IF NOT EXISTS page_audits (
    id SERIAL PRIMARY KEY,
    page_url TEXT NOT NULL,
    audit_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status_code INTEGER NOT NULL,
    indexable BOOLEAN NOT NULL DEFAULT TRUE,
    render_differs BOOLEAN NOT NULL DEFAULT FALSE,
    performance_proxy DOUBLE PRECISION,
    issues_found INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_page_audits_page_url ON page_audits(page_url);
CREATE INDEX IF NOT EXISTS ix_page_audits_audit_date ON page_audits(audit_date);

COMMENT ON TABLE page_audits IS 'Page-level technical/accessibility audit summary';
COMMENT ON COLUMN page_audits.page_url IS 'URL audited';
COMMENT ON COLUMN page_audits.audit_date IS 'Audit timestamp';
COMMENT ON COLUMN page_audits.status_code IS 'HTTP status code';
COMMENT ON COLUMN page_audits.indexable IS 'Whether page is indexable (no robots blocks)';
COMMENT ON COLUMN page_audits.render_differs IS 'Whether rendered DOM differs from raw HTML';
COMMENT ON COLUMN page_audits.performance_proxy IS 'Estimated performance score (0-100)';
COMMENT ON COLUMN page_audits.issues_found IS 'Count of issues detected';
COMMENT ON COLUMN page_audits.notes IS 'Optional notes about the audit';


-- ============================================================================
-- 10. Audit Issues - Individual technical/accessibility issues
-- ============================================================================
CREATE TABLE IF NOT EXISTS audit_issues (
    id SERIAL PRIMARY KEY,
    audit_id INTEGER NOT NULL REFERENCES page_audits(id) ON DELETE CASCADE,
    issue_type VARCHAR(100) NOT NULL,
    description TEXT NOT NULL,
    severity VARCHAR(20) NOT NULL DEFAULT 'medium',
    fixed BOOLEAN NOT NULL DEFAULT FALSE,
    fixed_date TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_audit_issues_audit_id ON audit_issues(audit_id);
CREATE INDEX IF NOT EXISTS ix_audit_issues_issue_type ON audit_issues(issue_type);
CREATE INDEX IF NOT EXISTS ix_audit_issues_fixed ON audit_issues(fixed);

COMMENT ON TABLE audit_issues IS 'Individual technical/accessibility audit issue';
COMMENT ON COLUMN audit_issues.issue_type IS 'Type: render_js_only_text, no_canonical, a11y_alt_missing, html_error, etc.';
COMMENT ON COLUMN audit_issues.description IS 'Detailed description of the issue';
COMMENT ON COLUMN audit_issues.severity IS 'high, medium, low';
COMMENT ON COLUMN audit_issues.fixed IS 'Whether issue has been fixed';
COMMENT ON COLUMN audit_issues.fixed_date IS 'When issue was fixed';


-- ============================================================================
-- 11. Task Logs - Job execution logging for governance
-- ============================================================================
CREATE TABLE IF NOT EXISTS task_logs (
    id SERIAL PRIMARY KEY,
    task_name VARCHAR(255) NOT NULL,
    module VARCHAR(100) NOT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    status VARCHAR(50) NOT NULL,
    message TEXT,
    items_processed INTEGER NOT NULL DEFAULT 0,
    items_new INTEGER NOT NULL DEFAULT 0,
    items_updated INTEGER NOT NULL DEFAULT 0,
    items_failed INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_task_logs_task_name ON task_logs(task_name);
CREATE INDEX IF NOT EXISTS ix_task_logs_module ON task_logs(module);
CREATE INDEX IF NOT EXISTS ix_task_logs_started_at ON task_logs(started_at);
CREATE INDEX IF NOT EXISTS ix_task_logs_status ON task_logs(status);

COMMENT ON TABLE task_logs IS 'Task execution logging for governance and accountability';
COMMENT ON COLUMN task_logs.task_name IS 'Name of the task (e.g., serp_scraper, competitor_crawler)';
COMMENT ON COLUMN task_logs.module IS 'Module name (e.g., serp, competitor, backlinks)';
COMMENT ON COLUMN task_logs.started_at IS 'Task start timestamp';
COMMENT ON COLUMN task_logs.completed_at IS 'Task completion timestamp';
COMMENT ON COLUMN task_logs.status IS 'success, failed, partial, timeout';
COMMENT ON COLUMN task_logs.message IS 'Summary message or error details';
COMMENT ON COLUMN task_logs.items_processed IS 'Number of items processed';
COMMENT ON COLUMN task_logs.items_new IS 'Number of new items created';
COMMENT ON COLUMN task_logs.items_updated IS 'Number of items updated';
COMMENT ON COLUMN task_logs.items_failed IS 'Number of items that failed';


-- ============================================================================
-- 12. Change Log - SEO change proposals for review-mode governance
-- ============================================================================
CREATE TABLE IF NOT EXISTS change_log (
    id SERIAL PRIMARY KEY,
    module VARCHAR(100) NOT NULL,
    change_type VARCHAR(100) NOT NULL,
    target_url TEXT NOT NULL,
    proposed_change JSONB NOT NULL,
    rationale TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    priority INTEGER NOT NULL DEFAULT 2,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMP,
    reviewed_by VARCHAR(100),
    executed_at TIMESTAMP,
    reverted_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_change_log_module ON change_log(module);
CREATE INDEX IF NOT EXISTS ix_change_log_change_type ON change_log(change_type);
CREATE INDEX IF NOT EXISTS ix_change_log_target_url ON change_log(target_url);
CREATE INDEX IF NOT EXISTS ix_change_log_status ON change_log(status);
CREATE INDEX IF NOT EXISTS ix_change_log_created_at ON change_log(created_at);

COMMENT ON TABLE change_log IS 'SEO change proposals for review-mode governance';
COMMENT ON COLUMN change_log.module IS 'Module that proposed the change';
COMMENT ON COLUMN change_log.change_type IS 'Type: title_update, schema_add, internal_link, meta_update, etc.';
COMMENT ON COLUMN change_log.target_url IS 'URL to be modified';
COMMENT ON COLUMN change_log.proposed_change IS 'JSON with change details (before/after, anchor text, etc.)';
COMMENT ON COLUMN change_log.rationale IS 'Explanation of why this change is recommended';
COMMENT ON COLUMN change_log.status IS 'pending, approved, rejected, executed, reverted';
COMMENT ON COLUMN change_log.priority IS '1=high, 2=medium, 3=low';
COMMENT ON COLUMN change_log.created_at IS 'Proposal creation timestamp';
COMMENT ON COLUMN change_log.reviewed_at IS 'When change was reviewed';
COMMENT ON COLUMN change_log.reviewed_by IS 'Who reviewed the change';
COMMENT ON COLUMN change_log.executed_at IS 'When change was applied';
COMMENT ON COLUMN change_log.reverted_at IS 'When change was reverted';


-- ============================================================================
-- Migration Complete
-- ============================================================================
