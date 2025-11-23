# SEO Intelligence Database Schema

**Last Updated:** 2025-11-23
**Total Tables:** 13
**Total Views:** 6
**Total Functions:** 2

This document describes the canonical database schema for the SEO intelligence system. All scrapers and analyzers write to these tables, providing a single source of truth for SEO data.

---

## Table Categories

### 1. SERP Tracking (4 tables)
- `search_queries` - Monitored search queries
- `serp_snapshots` - Time-series SERP captures
- `serp_results` - Individual search results
- `serp_paa` - People Also Ask questions

### 2. Competitor Analysis (2 tables)
- `competitors` - Competitor directory
- `competitor_pages` - Competitor page snapshots

### 3. Backlinks & Authority (2 tables)
- `backlinks` - Inbound link tracking
- `referring_domains` - Domain authority metrics

### 4. Citations (1 table)
- `citations` - Business directory listings

### 5. Technical Audits (2 tables)
- `page_audits` - Technical/accessibility audits
- `audit_issues` - Individual audit findings

### 6. Governance (2 tables)
- `change_log` - Review-mode governance
- `task_logs` - Scraper execution tracking

---

## Table Schemas

### 1. SERP Tracking Tables

#### search_queries
Tracks monitored SERP queries with location targeting.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| query_id | SERIAL | PRIMARY KEY | Unique query identifier |
| query_text | VARCHAR(500) | NOT NULL | Search query text |
| location | VARCHAR(200) | | Location context (e.g., "Austin, TX") |
| search_engine | VARCHAR(50) | DEFAULT 'google' | Search engine (google, bing, duckduckgo) |
| is_active | BOOLEAN | DEFAULT TRUE | Whether query is actively monitored |
| created_at | TIMESTAMP | DEFAULT NOW() | Creation timestamp |
| updated_at | TIMESTAMP | DEFAULT NOW() | Last update timestamp |
| metadata | JSONB | | Extended metadata (device, language, etc.) |

**Unique Constraint:** (query_text, location, search_engine)

**Indexes:**
- `idx_search_queries_active` ON (is_active)
- `idx_search_queries_text` ON (query_text)
- `idx_search_queries_metadata` USING GIN (metadata)

---

#### serp_snapshots
Time-series SERP snapshot data with change detection.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| snapshot_id | SERIAL | PRIMARY KEY | Unique snapshot identifier |
| query_id | INTEGER | NOT NULL, FK → search_queries | Associated query |
| captured_at | TIMESTAMP | DEFAULT NOW() | Capture timestamp |
| result_count | INTEGER | | Total results found |
| snapshot_hash | VARCHAR(64) | | SHA-256 hash for change detection |
| raw_html | TEXT | | Optional: full HTML snapshot |
| metadata | JSONB | | SERP features, ads, knowledge panels |

**Foreign Keys:**
- `query_id` → search_queries(query_id) ON DELETE CASCADE

**Indexes:**
- `idx_serp_snapshots_query` ON (query_id)
- `idx_serp_snapshots_captured` ON (captured_at DESC)
- `idx_serp_snapshots_hash` ON (snapshot_hash)
- `idx_serp_snapshots_metadata` USING GIN (metadata)

---

#### serp_results
Individual SERP result entries with position tracking.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| result_id | SERIAL | PRIMARY KEY | Unique result identifier |
| snapshot_id | INTEGER | NOT NULL, FK → serp_snapshots | Associated snapshot |
| position | INTEGER | NOT NULL | 1-based ranking position |
| url | TEXT | NOT NULL | Result URL |
| title | TEXT | | Result title |
| description | TEXT | | Result description/snippet |
| domain | VARCHAR(500) | | Result domain |
| is_our_company | BOOLEAN | DEFAULT FALSE | Tracks our own rankings |
| is_competitor | BOOLEAN | DEFAULT FALSE | Flags competitor results |
| competitor_id | INTEGER | | FK to competitors table (nullable) |
| metadata | JSONB | | Rich snippets, features, schema markup |

**Foreign Keys:**
- `snapshot_id` → serp_snapshots(snapshot_id) ON DELETE CASCADE

**Indexes:**
- `idx_serp_results_snapshot` ON (snapshot_id)
- `idx_serp_results_position` ON (position)
- `idx_serp_results_domain` ON (domain)
- `idx_serp_results_competitor` ON (competitor_id) WHERE competitor_id IS NOT NULL
- `idx_serp_results_metadata` USING GIN (metadata)

---

#### serp_paa
People Also Ask questions extracted from Google SERPs.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| paa_id | SERIAL | PRIMARY KEY | Unique PAA identifier |
| snapshot_id | INTEGER | NOT NULL, FK → serp_snapshots | Associated snapshot |
| query_id | INTEGER | NOT NULL, FK → search_queries | Associated query |
| question | TEXT | NOT NULL | PAA question text |
| answer_snippet | TEXT | | Answer text from PAA dropdown |
| source_url | TEXT | | URL of answer source |
| source_domain | VARCHAR(255) | | Domain of answer source |
| position | INTEGER | CHECK > 0 | Position in PAA list (1-based) |
| captured_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Capture timestamp |
| first_seen_at | TIMESTAMP | DEFAULT NOW() | First appearance |
| last_seen_at | TIMESTAMP | DEFAULT NOW() | Most recent appearance |
| metadata | JSONB | | Extended metadata |

**Foreign Keys:**
- `snapshot_id` → serp_snapshots(snapshot_id) ON DELETE CASCADE
- `query_id` → search_queries(query_id) ON DELETE CASCADE

**Indexes:**
- `idx_serp_paa_snapshot` ON (snapshot_id)
- `idx_serp_paa_query` ON (query_id)
- `idx_serp_paa_position` ON (snapshot_id, position)
- `idx_serp_paa_source_domain` ON (source_domain)
- `idx_serp_paa_captured` ON (captured_at DESC)
- `idx_serp_paa_first_seen` ON (query_id, first_seen_at)
- `idx_serp_paa_question_fulltext` USING GIN (to_tsvector('english', question))
- `idx_serp_paa_metadata` USING GIN (metadata)
- `idx_serp_paa_query_question` ON (query_id, question)

---

### 2. Competitor Analysis Tables

#### competitors
Competitor business directory with domain tracking.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| competitor_id | SERIAL | PRIMARY KEY | Unique competitor identifier |
| name | VARCHAR(500) | NOT NULL | Business name |
| domain | VARCHAR(500) | NOT NULL, UNIQUE | Primary domain |
| website_url | TEXT | | Full website URL |
| business_type | VARCHAR(200) | | Business category |
| location | VARCHAR(200) | | Geographic location |
| is_active | BOOLEAN | DEFAULT TRUE | Active monitoring flag |
| confidence_score | DECIMAL(5,2) | | Confidence score (0-100) |
| discovered_at | TIMESTAMP | DEFAULT NOW() | Discovery timestamp |
| last_crawled_at | TIMESTAMP | | Last crawl timestamp |
| metadata | JSONB | | Contact info, social links, etc. |

**Unique Constraint:** (domain)

**Indexes:**
- `idx_competitors_domain` ON (domain)
- `idx_competitors_active` ON (is_active)
- `idx_competitors_location` ON (location)
- `idx_competitors_metadata` USING GIN (metadata)

---

#### competitor_pages
Competitor page snapshots with content hashing.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| page_id | SERIAL | PRIMARY KEY | Unique page identifier |
| competitor_id | INTEGER | NOT NULL, FK → competitors | Associated competitor |
| url | TEXT | NOT NULL | Page URL |
| page_type | VARCHAR(100) | | Page type (homepage, services, etc.) |
| title | TEXT | | Page title |
| meta_description | TEXT | | Meta description |
| h1_tags | TEXT[] | | Array of H1 tags |
| content_hash | VARCHAR(64) | | SHA-256 content hash |
| word_count | INTEGER | | Page word count |
| crawled_at | TIMESTAMP | DEFAULT NOW() | Crawl timestamp |
| status_code | INTEGER | | HTTP status code |
| schema_markup | JSONB | | Extracted schema.org markup |
| links | JSONB | | Internal/external link analysis |
| metadata | JSONB | | Images, videos, CTAs, forms |

**Foreign Keys:**
- `competitor_id` → competitors(competitor_id) ON DELETE CASCADE

**Indexes:**
- `idx_competitor_pages_competitor` ON (competitor_id)
- `idx_competitor_pages_url` ON (url)
- `idx_competitor_pages_type` ON (page_type)
- `idx_competitor_pages_crawled` ON (crawled_at DESC)
- `idx_competitor_pages_hash` ON (content_hash)
- `idx_competitor_pages_schema` USING GIN (schema_markup)

---

### 3. Backlinks & Authority Tables

#### backlinks
Inbound link tracking with anchor text analysis.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| backlink_id | SERIAL | PRIMARY KEY | Unique backlink identifier |
| target_domain | VARCHAR(500) | NOT NULL | Domain being linked to |
| target_url | TEXT | NOT NULL | Specific page being linked to |
| source_domain | VARCHAR(500) | NOT NULL | Domain of linking page |
| source_url | TEXT | NOT NULL | Page containing the link |
| anchor_text | TEXT | | Link anchor text |
| link_type | VARCHAR(50) | | Link type (dofollow, nofollow, etc.) |
| discovered_at | TIMESTAMP | DEFAULT NOW() | Discovery timestamp |
| last_seen_at | TIMESTAMP | DEFAULT NOW() | Last verification timestamp |
| is_active | BOOLEAN | DEFAULT TRUE | Active link flag |
| metadata | JSONB | | Context, position, surrounding text |

**Unique Constraint:** (target_url, source_url)

**Indexes:**
- `idx_backlinks_target_domain` ON (target_domain)
- `idx_backlinks_source_domain` ON (source_domain)
- `idx_backlinks_active` ON (is_active)
- `idx_backlinks_discovered` ON (discovered_at DESC)
- `idx_backlinks_metadata` USING GIN (metadata)

---

#### referring_domains
Domain-level authority metrics and LAS scores.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| domain_id | SERIAL | PRIMARY KEY | Unique domain identifier |
| domain | VARCHAR(500) | NOT NULL, UNIQUE | Domain name |
| total_backlinks | INTEGER | DEFAULT 0 | Total backlink count |
| dofollow_count | INTEGER | DEFAULT 0 | Dofollow link count |
| nofollow_count | INTEGER | DEFAULT 0 | Nofollow link count |
| local_authority_score | DECIMAL(5,2) | | LAS: 0-100 custom authority metric |
| first_seen_at | TIMESTAMP | DEFAULT NOW() | First discovery |
| last_updated_at | TIMESTAMP | DEFAULT NOW() | Last update |
| metadata | JSONB | | Domain age, TLD, industry relevance |

**Unique Constraint:** (domain)

**Indexes:**
- `idx_referring_domains_domain` ON (domain)
- `idx_referring_domains_las` ON (local_authority_score DESC)
- `idx_referring_domains_backlinks` ON (total_backlinks DESC)
- `idx_referring_domains_metadata` USING GIN (metadata)

---

### 4. Citations Table

#### citations
Business directory citations with NAP matching.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| citation_id | SERIAL | PRIMARY KEY | Unique citation identifier |
| directory_name | VARCHAR(500) | NOT NULL | Directory name (Yelp, YP, BBB, etc.) |
| directory_url | TEXT | | Directory homepage URL |
| listing_url | TEXT | | Specific listing URL |
| business_name | VARCHAR(500) | | Business name from listing |
| address | TEXT | | Business address |
| phone | VARCHAR(50) | | Business phone |
| nap_match_score | DECIMAL(5,2) | | NAP consistency score (0-100) |
| has_website_link | BOOLEAN | DEFAULT FALSE | Has website link flag |
| is_claimed | BOOLEAN | DEFAULT FALSE | Claimed listing flag |
| rating | DECIMAL(3,2) | | Business rating |
| review_count | INTEGER | | Number of reviews |
| discovered_at | TIMESTAMP | DEFAULT NOW() | Discovery timestamp |
| last_verified_at | TIMESTAMP | | Last verification timestamp |
| metadata | JSONB | | Hours, categories, photos, etc. |

**Unique Constraint:** (directory_name, listing_url)

**Indexes:**
- `idx_citations_directory` ON (directory_name)
- `idx_citations_nap_score` ON (nap_match_score DESC)
- `idx_citations_claimed` ON (is_claimed)
- `idx_citations_discovered` ON (discovered_at DESC)
- `idx_citations_metadata` USING GIN (metadata)

---

### 5. Technical Audit Tables

#### page_audits
Technical/accessibility audit results.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| audit_id | SERIAL | PRIMARY KEY | Unique audit identifier |
| url | TEXT | NOT NULL | Audited page URL |
| audit_type | VARCHAR(100) | | Audit type (technical, accessibility, etc.) |
| overall_score | DECIMAL(5,2) | | Aggregate score (0-100) |
| audited_at | TIMESTAMP | DEFAULT NOW() | Audit timestamp |
| page_load_time_ms | INTEGER | | Page load time (milliseconds) |
| page_size_kb | INTEGER | | Page size (kilobytes) |
| total_requests | INTEGER | | Total HTTP requests |
| metadata | JSONB | | Lighthouse scores, Core Web Vitals |

**Indexes:**
- `idx_page_audits_url` ON (url)
- `idx_page_audits_type` ON (audit_type)
- `idx_page_audits_score` ON (overall_score DESC)
- `idx_page_audits_audited` ON (audited_at DESC)
- `idx_page_audits_metadata` USING GIN (metadata)

---

#### audit_issues
Individual audit findings and recommendations.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| issue_id | SERIAL | PRIMARY KEY | Unique issue identifier |
| audit_id | INTEGER | NOT NULL, FK → page_audits | Associated audit |
| severity | VARCHAR(50) | | Severity (critical, warning, info) |
| category | VARCHAR(100) | | Category (meta, images, links, etc.) |
| issue_type | VARCHAR(200) | | Specific issue type |
| description | TEXT | | Issue description |
| element | TEXT | | CSS selector or element identifier |
| recommendation | TEXT | | Recommended fix |
| metadata | JSONB | | Additional context, code snippets |

**Foreign Keys:**
- `audit_id` → page_audits(audit_id) ON DELETE CASCADE

**Indexes:**
- `idx_audit_issues_audit` ON (audit_id)
- `idx_audit_issues_severity` ON (severity)
- `idx_audit_issues_category` ON (category)
- `idx_audit_issues_type` ON (issue_type)
- `idx_audit_issues_metadata` USING GIN (metadata)

---

### 6. Governance Tables

#### change_log
Review-mode governance for all data changes.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| change_id | SERIAL | PRIMARY KEY | Unique change identifier |
| table_name | VARCHAR(100) | NOT NULL | Target table name |
| record_id | INTEGER | | Target record ID |
| operation | VARCHAR(50) | NOT NULL, CHECK | Operation (insert, update, delete) |
| proposed_data | JSONB | NOT NULL | Proposed change data |
| status | VARCHAR(50) | DEFAULT 'pending', CHECK | Status (pending, approved, rejected) |
| reason | TEXT | | Approval/rejection reason |
| proposed_at | TIMESTAMP | DEFAULT NOW() | Proposal timestamp |
| reviewed_at | TIMESTAMP | | Review timestamp |
| reviewed_by | VARCHAR(200) | | Reviewer identifier |
| metadata | JSONB | | Change context, diff, justification |

**Constraints:**
- `operation` IN ('insert', 'update', 'delete')
- `status` IN ('pending', 'approved', 'rejected')

**Indexes:**
- `idx_change_log_table` ON (table_name)
- `idx_change_log_status` ON (status)
- `idx_change_log_proposed` ON (proposed_at DESC)
- `idx_change_log_reviewed` ON (reviewed_at DESC)
- `idx_change_log_metadata` USING GIN (metadata)

---

#### task_logs
Execution tracking for all scraper tasks.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| task_id | SERIAL | PRIMARY KEY | Unique task identifier |
| task_name | VARCHAR(200) | NOT NULL | Task name (serp_scraper, etc.) |
| task_type | VARCHAR(100) | | Task type (scraper, analyzer, audit) |
| status | VARCHAR(50) | DEFAULT 'running', CHECK | Status (running, success, failed, cancelled) |
| started_at | TIMESTAMP | DEFAULT NOW() | Start timestamp |
| completed_at | TIMESTAMP | | Completion timestamp |
| duration_seconds | INTEGER | | Execution duration |
| records_processed | INTEGER | DEFAULT 0 | Records processed count |
| records_created | INTEGER | DEFAULT 0 | Records created count |
| records_updated | INTEGER | DEFAULT 0 | Records updated count |
| error_message | TEXT | | Error message (if failed) |
| metadata | JSONB | | Parameters, config, results summary |

**Constraints:**
- `status` IN ('running', 'success', 'failed', 'cancelled')

**Indexes:**
- `idx_task_logs_name` ON (task_name)
- `idx_task_logs_status` ON (status)
- `idx_task_logs_started` ON (started_at DESC)
- `idx_task_logs_completed` ON (completed_at DESC)
- `idx_task_logs_metadata` USING GIN (metadata)

---

## Helper Views

### 1. v_task_stats_by_name
Aggregated task execution statistics by task name.

**Purpose:** Monitor task success rates and performance

**Columns:**
- task_name
- total_runs
- success_count
- failed_count
- running_count
- avg_duration_seconds
- last_run_at
- total_records_processed

---

### 2. v_recent_task_failures
Recent task failures for alerting and monitoring (last 7 days).

**Purpose:** Alert on recent failures

**Columns:**
- task_id
- task_name
- task_type
- started_at
- completed_at
- duration_seconds
- error_message
- metadata

---

### 3. v_task_health_24h
Task health summary for last 24 hours with success rates.

**Purpose:** Daily health dashboard

**Columns:**
- task_name
- runs_24h
- success_24h
- failed_24h
- success_rate_pct
- avg_duration_seconds
- last_run_at

---

### 4. v_paa_question_frequency
Shows how often each PAA question appears for each query.

**Purpose:** Identify frequently appearing PAA questions

**Columns:**
- query_id
- query_text
- question
- appearance_count
- avg_position
- earliest_seen
- most_recent_seen
- source_domains

---

### 5. v_paa_delta_recent
Compares most recent 2 SERP snapshots to detect PAA changes.

**Purpose:** Track which PAA questions were added or removed

**Columns:**
- query_id
- query_text
- current_question
- previous_question
- change_type (added, removed, unchanged)

---

### 6. v_paa_top_sources
Shows which domains appear most frequently as PAA answer sources.

**Purpose:** Identify authoritative content sources

**Columns:**
- source_domain
- total_paa_answers
- queries_answered
- avg_position
- earliest_appearance
- most_recent_appearance

---

## Helper Functions

### 1. get_paa_for_query(p_query_id INT, p_limit INT)
Get PAA questions for a specific query, ordered by frequency and position.

**Returns:** TABLE (question, answer_snippet, source_url, paa_position, appearance_count)

---

### 2. upsert_paa_question(...)
Insert or update a PAA question. Updates last_seen_at if question already exists.

**Returns:** INT (paa_id)

---

## Migration Files

- **025_restore_seo_intelligence_tables.sql** - Core 12 tables + 3 views
- **022_create_serp_paa_table.sql** - PAA table + 3 views + 2 functions

---

## Schema Compliance Notes

### Field Naming Conventions
- Primary keys: `{table}_id` (e.g., query_id, snapshot_id)
- Foreign keys: Same name as referenced primary key
- Timestamps: `created_at`, `updated_at`, `captured_at`, `discovered_at`
- Flags: `is_{description}` (e.g., is_active, is_claimed)
- Counts: `{item}_count` (e.g., review_count, total_backlinks)
- Scores: `{metric}_score` (e.g., nap_match_score, overall_score)

### Data Types
- IDs: SERIAL (auto-incrementing integers)
- URLs: TEXT (unlimited length)
- Domains: VARCHAR(500)
- Names/Titles: VARCHAR(500) or TEXT
- Timestamps: TIMESTAMP (with DEFAULT NOW() where applicable)
- Scores: DECIMAL(5,2) for 0-100 scores
- Metadata: JSONB for flexible extension fields

### Index Strategy
- All foreign keys have indexes
- Timestamp columns have DESC indexes for recent-first queries
- JSONB columns use GIN indexes
- Composite indexes for common query patterns
- Partial indexes for filtered queries (e.g., WHERE is_active)

---

## Usage Guidelines

### For Scrapers
1. Always use prepared statements with parameterized queries
2. Store raw data in JSONB `metadata` fields when structure is uncertain
3. Use hash fields (content_hash, snapshot_hash) for change detection
4. Log all operations to `task_logs` for monitoring
5. Propose changes via `change_log` when governance is required

### For Analyzers
1. Query from views for pre-aggregated data
2. Use JSONB operators for metadata queries
3. Join on indexed foreign keys for performance
4. Filter on indexed columns (is_active, status, timestamps)

### For AI/LLM Integration
1. All field names and types are stable - safe to hardcode in prompts
2. JSONB fields allow flexible schema evolution
3. Helper views provide common aggregations
4. Change_log enables human-in-the-loop workflows

---

## Change History

| Date | Version | Changes |
|------|---------|---------|
| 2025-11-23 | 1.0 | Initial schema documentation after Step 1 inventory |
