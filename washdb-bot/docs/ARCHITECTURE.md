# URL Scrape Bot - System Architecture

> **Last Updated**: 2025-11-23
> **Status**: Local Development Phase (no production deployment yet)

## Overview

The URL Scrape Bot is a multi-phase web scraping system designed to discover and enrich pressure washing company data across multiple sources. It uses a modular architecture with separate discovery and enrichment phases, robust crash recovery, and comprehensive monitoring.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      User Interface Layer                    │
│  ┌──────────────────────┐       ┌──────────────────────┐   │
│  │   NiceGUI Dashboard  │       │   CLI Entry Points   │   │
│  │  (niceui/main.py)    │       │  (cli_crawl_*.py)    │   │
│  │   Port: 8080         │       │                      │   │
│  └──────────────────────┘       └──────────────────────┘   │
└───────────────────────┬──────────────────┬──────────────────┘
                        │                  │
┌───────────────────────┴──────────────────┴──────────────────┐
│                   Orchestration Layer                        │
│  ┌──────────────────────┐       ┌──────────────────────┐   │
│  │   Backend Facade     │       │   Job Scheduler      │   │
│  │  (backend_facade.py) │       │  (cron_service.py)   │   │
│  └──────────────────────┘       └──────────────────────┘   │
└───────────────────────┬──────────────────┬──────────────────┘
                        │                  │
┌───────────────────────┴──────────────────┴──────────────────┐
│                    Scraping Layer                            │
│  ┌────────────┐  ┌─────────────┐  ┌──────────────────┐     │
│  │ Phase 1: Discovery          │  │ Phase 2: Enrich  │     │
│  ├────────────┤  ├─────────────┤  ├──────────────────┤     │
│  │ YP Scraper │  │Google Scraper│ │  Site Scraper    │     │
│  │ (scrape_yp)│  │(scrape_google)│ │  (scrape_site)   │     │
│  │            │  │             │  │                  │     │
│  │ Bing Scraper                │  │  SEO Intelligence│     │
│  │ (scrape_bing)                │  │(seo_intelligence)│     │
│  └────────────┴──┴─────────────┴──┴──────────────────┘     │
└───────────────────────┬──────────────────┬──────────────────┘
                        │                  │
┌───────────────────────┴──────────────────┴──────────────────┐
│                     Data Layer                               │
│  ┌──────────────────────┐       ┌──────────────────────┐   │
│  │   PostgreSQL DB      │       │   Qdrant Vector DB   │   │
│  │  (washbot_db)        │       │   (embeddings)       │   │
│  └──────────────────────┘       └──────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

## Module Structure

### Core Directories

```
washdb-bot/
├── niceui/                    # Web dashboard (NiceGUI)
│   ├── main.py               # Dashboard entry point (port 8080)
│   ├── pages/                # Dashboard pages
│   │   ├── discover.py       # YP/Google discovery UI
│   │   ├── scrape.py         # Website enrichment UI
│   │   ├── dashboard.py      # Stats and metrics
│   │   ├── logs.py           # Log viewer
│   │   ├── scheduler.py      # Job scheduling
│   │   └── ...
│   ├── backend_facade.py     # API bridge to scrapers
│   └── widgets/              # Reusable UI components
│
├── scrape_yp/                # Yellow Pages scraper
│   ├── yp_crawl_city_first.py  # Main crawler
│   ├── yp_parser_enhanced.py   # HTML parsing
│   ├── yp_stealth.py           # Anti-detection
│   ├── yp_filter.py            # Result filtering
│   ├── yp_checkpoint.py        # Crash recovery
│   └── generate_city_targets.py # Target generation
│
├── scrape_google/            # Google Maps scraper
│   ├── google_crawl_city_first.py  # Main crawler
│   ├── google_client.py            # Google API/scraping
│   ├── google_stealth.py           # Anti-blocking
│   └── generate_city_targets.py    # Target generation
│
├── scrape_bing/              # Bing Local Search scraper
│   ├── bing_crawl_city_first.py   # Main crawler
│   └── generate_city_targets.py   # Target generation
│
├── scrape_site/              # Website enrichment
│   ├── site_scraper.py       # Multi-page website scraper
│   ├── site_parse.py         # Content extraction
│   └── resumable_crawler.py  # Crash-resumable crawler
│
├── seo_intelligence/         # SEO analysis module
│   ├── scrapers/             # SERP, citation, backlink scrapers
│   ├── services/             # Analysis and scoring
│   └── tests/                # SEO-specific tests
│
├── db/                       # Database layer
│   ├── models.py             # SQLAlchemy ORM models
│   ├── migrations/           # SQL migration files
│   ├── save_discoveries.py   # Upsert logic
│   └── init_db.py            # Database initialization
│
├── runner/                   # CLI orchestration
│   ├── main.py               # Legacy CLI entry point
│   ├── logging_setup.py      # Centralized logging
│   └── bootstrap.py          # Startup validation
│
├── scheduler/                # Job scheduling
│   └── cron_service.py       # APScheduler-based scheduler
│
├── scripts/                  # Utility scripts
│   ├── dev/                  # Development scripts
│   ├── run_state_workers.py  # Parallel worker scripts
│   └── cleanup_duplicates.py # Database cleanup
│
├── tests/                    # Test suite
│   ├── unit/                 # Unit tests
│   ├── integration/          # Integration tests
│   └── acceptance/           # End-to-end tests
│
├── data/                     # Data and artifacts
│   ├── backups/              # Database backups
│   ├── browser_profile/      # Playwright profiles
│   └── snapshots/            # HTML snapshots
│
└── logs/                     # Log files
    ├── yp_crawl_city_first.log
    ├── google_crawl.log
    ├── site_scraper.log
    └── yp_wal/               # Write-ahead logs
```

### Legacy/Deprecated Modules

```
legacy/
└── gui_backend/              # Old Flask backend (DEPRECATED)
    └── README.md             # Explains deprecation
```

## Configuration

### Environment Variables (.env)

Configuration is managed through environment variables loaded from `.env` (or `.env.dev` for development):

**Database**:
- `DATABASE_URL` - PostgreSQL connection string
- `WASHDB_PASSWORD` - Database password

**GUI**:
- `NICEGUI_PORT` - Dashboard port (default: 8080)
- `GUI_HOST` - Bind address (default: 127.0.0.1)

**Scraper Settings**:
- `WORKER_COUNT` - Number of parallel workers (default: 5)
- `CRAWL_DELAY_SECONDS` - Delay between requests (default: 10)
- `MAX_CONCURRENT_SITE_SCRAPES` - Max parallel site scrapes (default: 5)
- `USE_PLAYWRIGHT` - Use headless browser (default: true)
- `BROWSER_HEADLESS` - Run browser in headless mode (default: true)

**Anti-Detection**:
- `ANTI_DETECTION_ENABLED` - Enable stealth features (default: true)
- `RANDOMIZE_USER_AGENT` - Rotate user agents (default: true)
- `RANDOMIZE_VIEWPORT` - Randomize viewport sizes (default: true)
- `ADAPTIVE_RATE_LIMITING` - Adaptive delays (default: true)

**Proxy Settings**:
- `PROXY_FILE` - Path to proxy list
- `PROXY_ROTATION_ENABLED` - Enable proxy rotation (default: true)
- `PROXY_SELECTION_STRATEGY` - Selection method (round_robin, random, etc.)

**Vector Database**:
- `QDRANT_HOST` - Qdrant host (default: 127.0.0.1)
- `QDRANT_PORT` - Qdrant port (default: 6333)
- `EMBEDDING_MODEL` - Sentence transformer model (default: all-MiniLM-L6-v2)

**Logging**:
- `LOG_LEVEL` - Logging level (default: INFO)
- `LOG_DIR` - Log directory (default: logs)

See `.env.example` for full configuration template.

## Data Flow

### Phase 1: Discovery

```
User Trigger (GUI or CLI)
    ↓
Target Generation
    → Generate city × category combinations
    → Insert into {yp,google,bing}_targets tables
    ↓
Worker Pool
    → Claim targets (set claimed_by, claimed_at)
    → Scrape business listings
    → Apply filters (85%+ precision)
    → Extract: name, phone, address, website, category
    ↓
Database Save
    → Upsert to companies table
    → Deduplicate by phone/email
    → Store parse_metadata for traceability
    ↓
Progress Tracking
    → Update target status: IN_PROGRESS → DONE
    → Write to job_execution_logs
    → Checkpoint for crash recovery
```

### Phase 2: Enrichment

```
Companies with websites (from Phase 1)
    ↓
Site Scraper Queue
    → Multi-page website crawling
    → Extract: emails, phones, services, service areas
    ↓
Content Parsing
    → Parse contact pages, about pages, service pages
    → Normalize phone numbers and emails
    → Extract service descriptions
    ↓
Database Update
    → Update companies table with enriched data
    → Store in business_sources for multi-source tracking
    ↓
Quality Scoring
    → Compute data_quality_score (0-100)
    → Assign confidence_level (high/medium/low)
```

### SEO Intelligence (Optional)

```
Target URLs (competitors, citations, etc.)
    ↓
SERP Scraper
    → Google/Bing search results
    → Save to serp_snapshots
    ↓
Citation Scraper
    → Directory listings (Yelp, BBB, etc.)
    → NAP validation
    ↓
Backlink Scraper
    → Link analysis
    → Local Authority Score (LAS)
    ↓
Analysis Services
    → Competitor tracking
    → Citation consistency
    → SEO recommendations
```

## Data Model

### Core Tables

**companies** - Main business data
- Primary fields: id, name, website, domain, phone, email
- Details: services, service_area, address (parsed + raw)
- Source tracking: source, data_source, parse_metadata (JSON)
- Timestamps: created_at, last_updated

**yp_targets / google_targets / bing_targets** - Scraping targets
- Target definition: city, state, category, search_query
- Worker management: claimed_by, claimed_at, heartbeat_at
- Progress cursor: page_current, last_listing_id, next_page_url
- Status: PLANNED → IN_PROGRESS → DONE/FAILED
- Crash recovery: attempts, last_error, finished_at

**business_sources** - Multi-source NAP tracking
- Links to companies table
- Per-source NAP data: name, phone, address
- Quality: is_verified, data_quality_score, confidence_level
- Enables cross-source validation

**site_crawl_state** - Resumable website crawler
- Domain-level tracking
- Phase: parsing_home → crawling_internal → done
- Cursor: last_completed_url, pending_queue (JSON)
- Statistics: pages_crawled, targets_found, errors_count

### Governance Tables

**scheduled_jobs** - Cron job definitions
- Config: job_type, schedule_cron, parameters
- Control: enabled, priority, timeout_minutes, max_retries
- Statistics: total_runs, success_runs, failed_runs

**job_execution_logs** - Execution history
- Timing: started_at, completed_at, duration_seconds
- Results: status, items_found, items_new, items_updated
- Logs: output_log, error_log
- Trigger: scheduled vs manual vs retry

**Future Integration:**
These tables are **read-only inputs** for the AI SEO system. In the future, discoveries could feed into a `change_log` table with review-mode workflows for governance. See detailed governance integration below.

See [SCHEMA_REFERENCE.md](SCHEMA_REFERENCE.md) for complete schema documentation.

## Governance & AI SEO Integration

The URL Scrape Bot is designed to integrate with a larger AI SEO intelligence system. While the scraper is currently standalone, the data model and architecture support future governance workflows.

### Current State: Read-Only Data Collection

**What We Do Now:**
- Scrape business data from multiple sources (YP, Google, Bing)
- Store discoveries in `companies` and `business_sources` tables
- Log all operations in `job_execution_logs`
- Track data quality and confidence scores
- No automated changes to external systems

**Data Flow:**
```
Scrapers → Database → Manual Review/Export
```

### Future State: Governance-Integrated System

**What's Coming:**
- AI SEO system reads from scraper tables
- Discoveries generate "change proposals"
- Changes go through review workflow
- Approved changes applied to client sites/listings

**Data Flow:**
```
Scrapers → Database (Read-Only) → AI SEO System → change_log (Pending) → Review → Approved Changes
```

### Integration Architecture

#### Phase 1: Data Source (Current)

The scraper provides **authoritative source data**:

**Tables as Read-Only Inputs:**
- `companies` - Discovered businesses
- `business_sources` - Multi-source NAP data
- `serp_snapshots` - Search result tracking
- `citations` - Directory listings
- `backlinks` - Link profiles

**Traceability Fields:**
- `parse_metadata` (JSON) - Full scraping context
- `source`, `data_source` - Origin tracking
- `created_at`, `last_updated` - Temporal tracking
- `data_quality_score`, `confidence_level` - Quality metrics

#### Phase 2: Change Proposal Generation (Future)

AI SEO system analyzes scraper data and generates proposals:

**Example Scenarios:**

**New Competitor Discovered:**
```sql
-- Scraper finds new competitor
INSERT INTO companies (name, website, ...) VALUES ('New Competitor', ...);

-- AI SEO system detects and proposes tracking
INSERT INTO change_log (
    change_type = 'add_competitor',
    proposed_data = '{"competitor_id": 123, "action": "track"}',
    status = 'pending',
    source_table = 'companies',
    source_id = 123
);
```

**Citation Inconsistency Detected:**
```sql
-- Scraper finds NAP mismatch across sources
-- (Same business, different phone numbers)

-- AI SEO proposes correction
INSERT INTO change_log (
    change_type = 'update_citation',
    proposed_data = '{"correct_phone": "555-1234", "sources": [...]}',
    status = 'pending',
    evidence = 'Multi-source validation favors 555-1234 (3/4 sources)'
);
```

#### Phase 3: Review Workflow (Future)

Changes require human approval before execution:

**Review Modes:**

**1. Manual Review Mode** (Default):
- All changes go to `change_log` with `status='pending'`
- Human reviews proposals in dashboard
- Approval required before any action
- Audit trail maintained

**2. Auto-Approve Mode** (Opt-In):
- Low-risk changes auto-approved
- Based on confidence thresholds
- High-risk changes still require review
- Override available

**Review Dashboard:**
- View pending changes
- See supporting evidence
- Approve/reject/modify
- Add review notes

#### Phase 4: Change Execution (Future)

Approved changes are executed and tracked:

**Execution Flow:**
1. Change status: `pending` → `approved` → `in_progress` → `completed`
2. Execute change (update website, citation, etc.)
3. Log result in `change_log.execution_result`
4. Update `change_log.executed_at`, `executed_by`
5. Notify stakeholders if configured

### Data Model for Governance

**change_log Table** (Future):
```sql
CREATE TABLE change_log (
    id SERIAL PRIMARY KEY,
    change_type VARCHAR(50),  -- add_competitor, update_citation, etc.
    source_table VARCHAR(100),  -- companies, citations, etc.
    source_id INTEGER,  -- ID in source table
    proposed_data JSONB,  -- Proposed change
    current_data JSONB,  -- Current state
    evidence TEXT,  -- Supporting evidence
    status VARCHAR(20),  -- pending, approved, rejected, completed
    review_mode VARCHAR(20),  -- manual, auto
    confidence_score FLOAT,  -- 0-100
    created_at TIMESTAMP,
    reviewed_at TIMESTAMP,
    reviewed_by VARCHAR(100),
    executed_at TIMESTAMP,
    executed_by VARCHAR(100),
    execution_result JSONB,  -- Success/failure details
    notes TEXT  -- Review notes
);
```

### Integration Points

**1. Task Logging:**
Current `job_execution_logs` table:
- Already tracks all scraper runs
- Records items found, created, updated
- Provides audit trail
- Can trigger AI SEO analysis

**2. Data Quality Scoring:**
Current `business_sources` table:
- `data_quality_score` (0-100)
- `confidence_level` (high/medium/low)
- `is_verified` flag
- Informs change confidence

**3. Multi-Source Validation:**
Current `business_sources` table:
- Tracks same business across sources
- Enables consistency checks
- Identifies conflicts
- Supports evidence-based decisions

**4. Change Traceability:**
Current `parse_metadata` field:
- Full scraping context preserved
- Source URLs captured
- Scraping timestamp recorded
- Enables change verification

### Governance Principles

**1. Write-Only to change_log:**
- Scrapers never modify existing data directly
- All changes go through `change_log`
- Read-only access to scraper tables

**2. Explicit Approval:**
- No automated changes in manual mode
- Clear approval trail
- Rollback capability

**3. Evidence-Based:**
- Changes backed by data
- Confidence scores required
- Multi-source validation preferred

**4. Audit Trail:**
- Complete history in `change_log`
- Who, what, when, why recorded
- Execution results logged

**5. Fail-Safe:**
- Failed changes logged but don't break system
- Retry logic for transient failures
- Manual intervention option

### Future Enhancements

**Short Term** (Next 3-6 months):
- Implement `change_log` table
- Build review dashboard in NiceGUI
- Add manual approval workflow
- Integrate with existing scrapers

**Medium Term** (6-12 months):
- AI-powered change detection
- Confidence scoring algorithms
- Auto-approval for low-risk changes
- Email/Slack notifications

**Long Term** (12+ months):
- Machine learning for quality scoring
- Predictive competitor analysis
- Automated citation management
- Full AI SEO integration

### Current Best Practices

Until governance integration is complete:

**1. Review Scraper Output:**
- Regularly check `job_execution_logs`
- Monitor `data_quality_score` distribution
- Investigate low-confidence records

**2. Manual Change Process:**
- Export data for review
- Make changes manually
- Document changes externally
- Track outcomes

**3. Data Quality Monitoring:**
- Run quality reports
- Check for duplicates
- Validate NAP consistency
- Review parse errors

**4. Prepare for Integration:**
- Maintain data quality standards
- Keep parse_metadata complete
- Log all operations
- Document anomalies

See also:
- [SCHEMA_REFERENCE.md](SCHEMA_REFERENCE.md) - Database schema details
- [FIELD_MIGRATION_GUIDE.md](FIELD_MIGRATION_GUIDE.md) - Schema changes
- Future AI SEO system documentation (TBD)

## Key Components

### Anti-Detection & Stealth

**Features**:
- Playwright stealth plugins
- User agent randomization (Chrome, Firefox, Safari)
- Viewport randomization (desktop, tablet)
- Realistic mouse movements and delays
- Browser profile persistence
- Adaptive rate limiting (backs off on errors)
- Proxy rotation (if configured)

**Implementation**:
- `scrape_yp/yp_stealth.py`
- `scrape_google/google_stealth.py`
- See [YP_STEALTH_FEATURES.md](YP_STEALTH_FEATURES.md) for details

### Crash Recovery

**Write-Ahead Logging (WAL)**:
- `logs/yp_wal/` - Pre-writes scraping actions
- Enables replay after crashes

**Checkpoints**:
- Page-level progress tracking in targets tables
- `last_listing_id`, `next_page_url` for exact resume point
- Worker heartbeats detect stalled processes

**Worker Management**:
- Workers "claim" targets (set `claimed_by`, `claimed_at`)
- Heartbeat updates every 30s
- Stale claims (>5 min) can be reclaimed

**Implementation**:
- `scrape_yp/yp_checkpoint.py`
- `scrape_yp/yp_wal.py`
- See [architecture/CRASH_RECOVERY.md](architecture/CRASH_RECOVERY.md)

### Logging System

**Centralized Setup**: `runner/logging_setup.py`
- Function: `setup_logging(name)` or `get_logger(name)`
- Handlers: Console + Rotating file (10MB, 5 backups)
- Format: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`

**Log Locations**: `logs/{module_name}.log`
- `yp_crawl_city_first.log` - YP scraper
- `google_crawl.log` - Google scraper
- `site_scraper.log` - Site enrichment
- `backend_facade.log` - GUI backend
- See [LOGS.md](LOGS.md) for complete reference

### Parallel Processing

**Worker Pools**:
- `scripts/run_state_workers.py` (10 workers)
- `scripts/run_state_workers_5.py` (5 workers)
- Each worker: separate browser instance, DB connection

**Target Distribution**:
- `state_assignments.py` - Distributes states across workers
- Load balancing by city count

**Database Pool**:
- `DB_POOL_SIZE=20` - Connection pooling for concurrency

**Implementation**: See [architecture/PARALLEL_SCRAPING_GUIDE.md](architecture/PARALLEL_SCRAPING_GUIDE.md)

## Entry Points

### GUI (Recommended)

```bash
# Start NiceGUI dashboard
python niceui/main.py
# Or: python -m niceui
# Access at: http://localhost:8080
```

**Features**:
- Discover tab - Trigger YP/Google/Bing scrapers
- Scrape tab - Website enrichment
- Dashboard - Stats and KPIs
- Logs - Real-time log viewer
- Scheduler - Manage cron jobs
- Database - Browse companies
- Testing - Run test suite

### CLI

**Yellow Pages Discovery**:
```bash
python cli_crawl_yp.py --states RI --max-targets 500 --categories "pressure washing"
```

**Google Maps Discovery**:
```bash
python cli_crawl_google_city_first.py --states RI --max-workers 2
```

**Legacy Runner** (deprecated, use CLI above):
```bash
python runner/main.py --discover-only --categories "pressure washing" --states "TX"
```

## Development vs Production

**Current State**: **Local Development Only**

**What We're NOT Doing Yet**:
- ❌ Production deployment (remote servers)
- ❌ System-wide cron scheduling
- ❌ External access (VPN, TLS, authentication)
- ❌ Automated backups with remote storage
- ❌ Email/Slack alerting
- ❌ Auto-changes to external systems

**What We ARE Doing**:
- ✅ Local PostgreSQL database
- ✅ Manual scraper runs (GUI or CLI)
- ✅ Local log files
- ✅ Manual job scheduling via GUI
- ✅ Crash recovery (for local reliability)
- ✅ Code quality tooling (linting, formatting)

See [QUICKSTART-dev.md](QUICKSTART-dev.md) for local development setup.

## Technology Stack

**Languages & Frameworks**:
- Python 3.11+
- NiceGUI (web framework)
- SQLAlchemy 2.0+ (ORM)
- Playwright (headless browser automation)

**Databases**:
- PostgreSQL 14+ (main database)
- Qdrant (vector database for embeddings)

**Key Libraries**:
- `requests` - HTTP client
- `beautifulsoup4` + `lxml` - HTML parsing
- `APScheduler` - Job scheduling
- `psutil` - Process management
- `python-dotenv` - Environment management
- `sentence-transformers` - Local embeddings

**Testing**:
- `pytest` - Test framework
- `pytest-asyncio` - Async testing

**Code Quality**:
- `black` - Code formatter
- `ruff` - Fast Python linter

## Next Steps

For production deployment, we'll add:
1. System-wide cron scheduling (APScheduler in daemon mode)
2. Remote access hardening (auth, TLS, VPN)
3. Alerting (email/Slack for failures)
4. Automated backups with restore drills
5. Integration with AI SEO system (`change_log`, review mode)

See the project roadmap in the planning documents.

---

**For More Information**:
- Quick start: [QUICKSTART-dev.md](QUICKSTART-dev.md)
- Log reference: [LOGS.md](LOGS.md)
- Testing: [../tests/README.md](../tests/README.md)
- Full documentation index: [index.md](index.md)
