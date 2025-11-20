# SEO Intelligence System

Comprehensive AI-powered SEO monitoring and competitive intelligence platform.

## Overview

The SEO Intelligence System is a complete solution for automated SEO monitoring, competitor analysis, and local authority tracking. Built with a write-only architecture, it collects data from multiple sources and stores it for analysis without directly mutating live systems.

## Architecture

### Core Principles

1. **Write-Only**: System never mutates live sites directly. All changes go to `change_log` table with `status='pending'` for manual review.
2. **Governance**: All operations logged to `task_logs` for accountability and debugging.
3. **Rate Limiting**: Conservative crawling with 3-6 second delays, robots.txt compliance, and 24-hour quarantine for CAPTCHA/403.
4. **Scalability**: Time-series partitioning support for high-volume tables.

### Database Schema

**12 Canonical Tables:**

- `search_queries` - Tracked keywords for SERP monitoring
- `serp_snapshots` - Daily SERP snapshots (one per query per day)
- `serp_results` - Individual organic results (top 10)
- `competitors` - Competitor domains with LAS scores
- `competitor_pages` - Crawled pages with hashes and snapshots
- `backlinks` - Link relationships (source → target)
- `referring_domains` - Aggregated domain-level backlink stats
- `citations` - Directory listings with NAP consistency
- `page_audits` - Technical SEO audit results
- `audit_issues` - Specific issues found during audits
- `task_logs` - Execution logs for all jobs
- `change_log` - Proposed changes awaiting approval

## Modules

### 1. SERP Scraper

Monitors search engine results pages for tracked keywords.

**Features:**
- Playwright-based rendering with anti-detection
- Extracts top 10 organic results
- Featured snippets (paragraph, list, table)
- People Also Ask (PAA) questions with expansion
- Automatic our_rank detection

**Usage:**
```bash
# Scrape all tracked queries
python -m seo_intelligence.serp.cli

# Limit to first 5 queries (for testing)
python -m seo_intelligence.serp.cli --limit 5

# Run with visible browser (debugging)
python -m seo_intelligence.serp.cli --no-headless

# With proxy
python -m seo_intelligence.serp.cli --proxy http://proxy:8080
```

**Cron Schedule:**
```cron
# Daily at 6 AM
0 6 * * * cd /path/to/washdb-bot && python -m seo_intelligence.serp.cli
```

### 2. Competitor Crawler

Crawls competitor websites for content analysis.

**Features:**
- URL discovery (sitemap.xml, RSS, homepage links)
- DOM hashing for change detection (SHA-256)
- On-page signal extraction:
  - Meta tags (title, description, Open Graph, Twitter Cards)
  - Header hierarchy (H1-H6)
  - Schema.org JSON-LD
  - Images and videos
  - Links with classification
- HTML snapshot storage (gzipped)
- Vector embeddings (sentence-transformers)
- Qdrant integration for semantic search

**Usage:**
```bash
# Crawl all tracked competitors
python -m seo_intelligence.competitor.cli

# Crawl specific competitor
python -m seo_intelligence.competitor.cli --competitor-id 123

# Limit pages per site
python -m seo_intelligence.competitor.cli --max-pages 50

# Disable embeddings (faster)
python -m seo_intelligence.competitor.cli --no-embeddings
```

**Cron Schedule:**
```cron
# Weekly on Sunday at 2 AM
0 2 * * 0 cd /path/to/washdb-bot && python -m seo_intelligence.competitor.cli
```

### 3. Backlinks Tracker & LAS Calculator

Tracks outbound links and computes Local Authority Scores.

**Features:**
- Link extraction from competitor snapshots
- Position classification (in-body, nav, footer, aside, sidebar)
- Deduplication by (source_url, target_url)
- Referring domains aggregation
- LAS calculation (0-100 scale):
  - Base score: log10(referring_domains) × 20
  - Quality bonus: (in_body_pct / 100) × 40

**Usage:**
```bash
# Extract backlinks and calculate LAS
python -m seo_intelligence.backlinks.cli

# Only extract backlinks
python -m seo_intelligence.backlinks.cli --mode backlinks

# Only calculate LAS
python -m seo_intelligence.backlinks.cli --mode las
```

**Cron Schedule:**
```cron
# Nightly at 3 AM (after competitor crawl)
0 3 * * * cd /path/to/washdb-bot && python -m seo_intelligence.backlinks.cli
```

### 4. Citations Scraper

Monitors business citations across directories.

**Features:**
- NAP (Name, Address, Phone) extraction
- Schema.org microdata parsing
- Phone/address normalization
- Consistency checking against canonical values
- Review signals (rating, count)

**Usage:**
```bash
# Scrape citations from JSON file
python -m seo_intelligence.citations.cli --citations-file citations.json \
  --canonical-name "My Business" \
  --canonical-address "123 Main St, City, ST 12345" \
  --canonical-phone "(555) 123-4567"
```

**Example citations.json:**
```json
[
  {
    "directory_name": "Google Business",
    "profile_url": "https://www.google.com/maps/place/..."
  },
  {
    "directory_name": "Yelp",
    "profile_url": "https://www.yelp.com/biz/..."
  },
  {
    "directory_name": "Yellow Pages",
    "profile_url": "https://www.yellowpages.com/..."
  }
]
```

**Cron Schedule:**
```cron
# Weekly on Monday at 4 AM
0 4 * * 1 cd /path/to/washdb-bot && python -m seo_intelligence.citations.cli --citations-file /path/to/citations.json
```

### 5. Technical Auditor

Performs technical SEO audits on pages.

**Features:**
- Indexability checks:
  - robots meta tag
  - X-Robots-Tag header
  - Canonical link presence
- Accessibility checks:
  - Alt text on images
  - H1 structure (exactly one)
  - HTML lang attribute
- Severity classification (error/warning)

**Usage:**
```bash
# Audit all tracked competitors
python -m seo_intelligence.audits.cli

# Audit specific competitor
python -m seo_intelligence.audits.cli --competitor-id 123
```

**Cron Schedule:**
```cron
# Monthly on 1st at 5 AM
0 5 1 * * cd /path/to/washdb-bot && python -m seo_intelligence.audits.cli
```

## Installation

### Prerequisites

- Python 3.8+
- PostgreSQL 12+
- Qdrant vector database (optional, for embeddings)

### Python Dependencies

```bash
pip install -r requirements.txt
```

**Core dependencies:**
- `sqlalchemy` - Database ORM
- `playwright` - Browser automation
- `beautifulsoup4` - HTML parsing
- `requests` - HTTP client
- `feedparser` - RSS/Atom parsing
- `sentence-transformers` - Embeddings
- `qdrant-client` - Vector database
- `python-dotenv` - Environment variables

### Playwright Setup

```bash
# Install Playwright browsers
playwright install chromium
```

### Database Setup

1. Set DATABASE_URL environment variable:
```bash
export DATABASE_URL="postgresql://user:password@localhost:5432/database"
```

2. Run migration:
```bash
python washdb-bot/seo_intelligence/scripts/run_migration.py
```

### Qdrant Setup (Optional)

For vector embeddings and semantic search:

```bash
# Run Qdrant via Docker
docker run -p 6333:6333 qdrant/qdrant

# Or set QDRANT_URL
export QDRANT_URL="http://localhost:6333"
```

## Configuration

### Environment Variables

```bash
# Required
DATABASE_URL="postgresql://user:password@localhost:5432/database"

# Optional
OUR_DOMAIN="yourdomain.com"  # For our_rank detection in SERP
QDRANT_URL="http://localhost:6333"  # For embeddings
QDRANT_API_KEY="your_api_key"  # If using Qdrant Cloud
```

### Rate Limiting

Configure in `infrastructure/rate_limiter.py`:

```python
rate_limiter = RateLimiter(
    base_delay=3.0,      # Minimum 3 seconds between requests
    max_delay=6.0,       # Maximum 6 seconds
    jitter=1.0,          # Add 0-1 second random jitter
    quarantine_hours=24  # 24-hour quarantine for CAPTCHA/403
)
```

## Development

### Project Structure

```
seo_intelligence/
├── infrastructure/          # Shared utilities
│   ├── http_client.py      # Unified HTTP client
│   ├── rate_limiter.py     # Per-domain rate limiting
│   ├── robots_parser.py    # Robots.txt compliance
│   └── task_logger.py      # Governance logging
├── serp/                   # SERP scraper
│   ├── scraper.py          # Main scraper
│   ├── extractor.py        # Data extraction
│   └── cli.py              # CLI entrypoint
├── competitor/             # Competitor crawler
│   ├── crawler.py          # Main crawler
│   ├── url_seeder.py       # URL discovery
│   ├── hasher.py           # DOM hashing
│   ├── parser.py           # On-page signal extraction
│   ├── snapshot.py         # HTML storage
│   ├── embeddings.py       # Vector embeddings
│   └── cli.py              # CLI entrypoint
├── backlinks/              # Backlinks & LAS
│   ├── tracker.py          # Link extraction & storage
│   ├── las_calculator.py   # Authority score computation
│   └── cli.py              # CLI entrypoint
├── citations/              # Citations scraper
│   ├── scraper.py          # NAP extraction
│   └── cli.py              # CLI entrypoint
├── audits/                 # Technical audits
│   ├── auditor.py          # Audit engine
│   └── cli.py              # CLI entrypoint
└── scripts/
    └── run_migration.py    # Database migration runner
```

### Testing

```bash
# Test SERP scraper with limit
python -m seo_intelligence.serp.cli --limit 1

# Test competitor crawler with limit
python -m seo_intelligence.competitor.cli --max-pages 5

# Check database logs
python -c "from db.models import TaskLog; from sqlalchemy import create_engine; from sqlalchemy.orm import sessionmaker; engine = create_engine('$DATABASE_URL'); Session = sessionmaker(bind=engine); session = Session(); logs = session.query(TaskLog).order_by(TaskLog.started_at.desc()).limit(5).all(); print('\\n'.join([f'{log.task_name}: {log.status}' for log in logs]))"
```

## Monitoring

### Task Logs

All jobs write to `task_logs` table:

```sql
SELECT
    task_name,
    module,
    status,
    items_processed,
    items_new,
    items_failed,
    started_at,
    completed_at,
    message
FROM task_logs
WHERE started_at > NOW() - INTERVAL '7 days'
ORDER BY started_at DESC;
```

### Failed Jobs

```sql
SELECT task_name, module, message, started_at
FROM task_logs
WHERE status = 'failed'
ORDER BY started_at DESC
LIMIT 10;
```

### Competitor LAS Rankings

```sql
SELECT name, domain, las
FROM competitors
WHERE track = true AND las IS NOT NULL
ORDER BY las DESC
LIMIT 10;
```

## Troubleshooting

### CAPTCHA/403 Quarantine

Check quarantined domains:

```python
from seo_intelligence.infrastructure.rate_limiter import rate_limiter
# Domains are quarantined for 24 hours after CAPTCHA/403
# To manually reset:
rate_limiter.reset_domain("https://example.com")
```

### Database Connection Issues

```bash
# Test connection
python -c "from sqlalchemy import create_engine; engine = create_engine('$DATABASE_URL'); print('Connected!' if engine.connect() else 'Failed')"
```

### Playwright Issues

```bash
# Reinstall browsers
playwright install --force chromium
```

## Roadmap

### Completed
- ✅ SERP scraper with Playwright
- ✅ Competitor crawler with embeddings
- ✅ Backlinks tracker & LAS calculator
- ✅ Citations scraper with NAP normalization
- ✅ Technical audits (indexability, accessibility)
- ✅ Infrastructure (rate limiting, robots, task logging)

### Future Enhancements
- [ ] Advanced accessibility checks (color contrast, ARIA)
- [ ] Mobile vs desktop rendering comparison
- [ ] Structured data validation
- [ ] Automated change proposals (ML-driven)
- [ ] Dashboard UI for visualization
- [ ] API endpoints for third-party integrations

## License

Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
