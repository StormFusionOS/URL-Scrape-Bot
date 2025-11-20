# SEO Intelligence System - Installation Guide

Quick start guide for setting up the SEO Intelligence system.

## Prerequisites

- Python 3.8 or higher
- PostgreSQL 12 or higher
- Git (for cloning repository)

## Step 1: Clone Repository

```bash
git clone https://github.com/StormFusionOS/URL-Scrape-Bot.git
cd URL-Scrape-Bot/washdb-bot
```

## Step 2: Install Python Dependencies

```bash
cd seo_intelligence
pip install -r requirements.txt
```

**Core dependencies installed:**
- SQLAlchemy (database ORM)
- Requests (HTTP client)
- BeautifulSoup4 (HTML parsing)
- Playwright (browser automation)
- Python-dotenv (environment variables)

**Optional dependencies (install separately if needed):**
```bash
# For RSS feed parsing (competitor URL discovery)
pip install feedparser

# For vector embeddings and semantic search
pip install sentence-transformers qdrant-client
```

## Step 3: Install Playwright Browsers

```bash
playwright install chromium
```

This downloads the Chromium browser needed for SERP scraping.

## Step 4: Validate Installation

Run the validation script to check everything is set up correctly:

```bash
python scripts/validate_installation.py
```

**Expected output:**
```
✓ All required components validated successfully!
```

If you see errors, install missing packages and try again.

## Step 5: Configure Environment

Create a `.env` file in the `washdb-bot` directory:

```bash
# Required
DATABASE_URL=postgresql://username:password@localhost:5432/database_name

# Optional (for our_rank detection in SERP results)
OUR_DOMAIN=yourdomain.com

# Optional (for vector embeddings)
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=your_api_key  # If using Qdrant Cloud
```

**Or set environment variables directly:**

```bash
export DATABASE_URL="postgresql://username:password@localhost:5432/database_name"
export OUR_DOMAIN="yourdomain.com"
```

## Step 6: Set Up PostgreSQL Database

### Create Database

```sql
CREATE DATABASE seo_intelligence;
CREATE USER seo_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE seo_intelligence TO seo_user;
```

### Run Migration

Apply the database schema:

```bash
cd seo_intelligence
python scripts/run_migration.py --database-url "postgresql://seo_user:your_password@localhost:5432/seo_intelligence"
```

**This creates 12 tables:**
- search_queries, serp_snapshots, serp_results
- competitors, competitor_pages
- backlinks, referring_domains
- citations
- page_audits, audit_issues
- task_logs, change_log

## Step 7: Verify Database Setup

Check that tables were created:

```bash
psql -U seo_user -d seo_intelligence -c "\dt"
```

You should see all 12 tables listed.

## Step 8: Set Up Qdrant (Optional)

For vector embeddings and semantic search:

### Using Docker:

```bash
docker run -d -p 6333:6333 qdrant/qdrant
```

### Or download binary:

Visit: https://qdrant.tech/documentation/quick-start/

## Step 9: Populate Initial Data

### Add Search Queries

```sql
INSERT INTO search_queries (query_text, search_engine, locale, track) VALUES
('your main keyword', 'Google', 'en-US', true),
('another keyword', 'Google', 'en-US', true);
```

### Add Competitors

```sql
INSERT INTO competitors (name, domain, track) VALUES
('Competitor 1', 'competitor1.com', true),
('Competitor 2', 'competitor2.com', true);
```

## Step 10: Test Individual Modules

### Test SERP Scraper

```bash
# Test with limit to scrape just 1 query
python -m seo_intelligence.serp.cli --limit 1
```

### Test Competitor Crawler

```bash
# Test with page limit
python -m seo_intelligence.competitor.cli --max-pages 5 --no-embeddings
```

### Test Backlinks Tracker

```bash
# Extract backlinks only (fast)
python -m seo_intelligence.backlinks.cli --mode backlinks
```

## Step 11: Set Up Cron Jobs

Create `/etc/cron.d/seo-intelligence` or add to your crontab:

```bash
# Set environment variables
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin
DATABASE_URL=postgresql://seo_user:password@localhost:5432/seo_intelligence
OUR_DOMAIN=yourdomain.com

# Change to project directory
WORKDIR=/home/user/URL-Scrape-Bot/washdb-bot

# Daily SERP monitoring (6 AM)
0 6 * * * cd $WORKDIR && python -m seo_intelligence.serp.cli

# Weekly competitor crawl (Sunday 2 AM)
0 2 * * 0 cd $WORKDIR && python -m seo_intelligence.competitor.cli

# Nightly backlinks & LAS (3 AM)
0 3 * * * cd $WORKDIR && python -m seo_intelligence.backlinks.cli

# Weekly citations check (Monday 4 AM)
0 4 * * 1 cd $WORKDIR && python -m seo_intelligence.citations.cli --citations-file /path/to/citations.json

# Monthly technical audit (1st of month, 5 AM)
0 5 1 * * cd $WORKDIR && python -m seo_intelligence.audits.cli
```

## Step 12: Monitor Jobs

Check task logs:

```sql
SELECT
    task_name,
    module,
    status,
    items_processed,
    items_new,
    started_at,
    completed_at
FROM task_logs
ORDER BY started_at DESC
LIMIT 10;
```

Check for failures:

```sql
SELECT task_name, message, started_at
FROM task_logs
WHERE status = 'failed'
ORDER BY started_at DESC;
```

## Troubleshooting

### Issue: "No module named 'seo_intelligence'"

**Solution:** Ensure you're running commands from the `washdb-bot` directory:

```bash
cd /path/to/URL-Scrape-Bot/washdb-bot
python -m seo_intelligence.serp.cli
```

### Issue: "DATABASE_URL not set"

**Solution:** Set environment variable or use `--database-url` flag:

```bash
export DATABASE_URL="postgresql://user:pass@localhost/db"
# Or
python -m seo_intelligence.serp.cli --database-url "postgresql://..."
```

### Issue: CAPTCHA detected / Domain quarantined

**Solution:** Domain will be auto-unquarantined after 24 hours. To manually reset:

```python
from seo_intelligence.infrastructure.rate_limiter import rate_limiter
rate_limiter.reset_domain("https://example.com")
```

### Issue: Playwright browser not found

**Solution:** Install browsers:

```bash
playwright install chromium
```

### Issue: feedparser or qdrant_client not found

**Solution:** These are optional. Install if needed:

```bash
pip install feedparser sentence-transformers qdrant-client
```

## Next Steps

1. **Configure Rate Limiting:** Adjust delays in `infrastructure/rate_limiter.py`
2. **Add More Queries:** Insert keywords into `search_queries` table
3. **Add More Competitors:** Insert domains into `competitors` table
4. **Set Up Monitoring:** Create alerts for failed tasks
5. **Review Data:** Query `serp_snapshots`, `competitor_pages`, `backlinks` tables

## Support

For issues or questions:
- GitHub Issues: https://github.com/StormFusionOS/URL-Scrape-Bot/issues
- Documentation: See `README.md` for detailed module documentation

## Quick Reference

**Validate installation:**
```bash
python scripts/validate_installation.py
```

**Run migration:**
```bash
python scripts/run_migration.py
```

**Test SERP scraper:**
```bash
python -m seo_intelligence.serp.cli --limit 1
```

**View logs:**
```bash
tail -f serp_scraper.log
tail -f competitor_crawler.log
tail -f backlinks.log
```

**Check database:**
```sql
SELECT COUNT(*) FROM serp_results;
SELECT COUNT(*) FROM competitor_pages;
SELECT COUNT(*) FROM backlinks;
```

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
