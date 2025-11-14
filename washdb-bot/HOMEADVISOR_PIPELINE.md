# HomeAdvisor Discovery Pipeline

## Overview

A two-phase continuous pipeline for discovering businesses from HomeAdvisor and finding their external websites.

```
Phase 1 (Discovery)          Phase 2 (URL Finder)
-------------------          --------------------
Scrape HA lists    →  ha_staging table  ←  Poll every 30s
Save to staging                             Find URLs (DuckDuckGo)
                                            Dedup by domain
                                            Save to companies table
                                            Delete from staging
```

## Architecture

### Phase 1: Discovery
- **Purpose**: Discover businesses from HomeAdvisor list pages
- **Output**: Saves to `ha_staging` table
- **Data**: name, address, phone, profile_url, rating_ha, reviews_ha
- **No website URLs yet** - just basic business info from list pages

### Phase 2: URL Finder Worker
- **Purpose**: Find external websites for businesses in staging queue
- **Input**: Polls `ha_staging` table every 30 seconds
- **Processing**:
  1. Waits for minimum 10 businesses before starting
  2. Processes one business at a time
  3. Searches DuckDuckGo: "[Business Name] [City] [State]"
  4. Scores results using heuristics (business name in domain, etc.)
  5. On success: Upserts to `companies` table (dedup by domain), deletes from staging
  6. On failure: Exponential backoff retry (1h, 4h, 16h)
  7. After 3 failed attempts: Deletes from staging

### Database Schema

#### `ha_staging` Table (Queue)
```sql
CREATE TABLE ha_staging (
    id SERIAL PRIMARY KEY,
    name TEXT,
    address TEXT,
    phone TEXT,
    profile_url TEXT UNIQUE NOT NULL,
    rating_ha REAL,
    reviews_ha INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    processed BOOLEAN DEFAULT FALSE,
    retry_count INTEGER DEFAULT 0,
    next_retry_at TIMESTAMP,
    last_error TEXT
);
```

#### `companies` Table (Production)
Existing table - Phase 2 inserts/updates records here.

### Deduplication Strategy

**Staging Table**: Deduplicates by `profile_url` (HomeAdvisor URL)
- Prevents same HA business from entering queue twice

**Companies Table**: Deduplicates by `domain` (external website domain)
- If domain exists: Updates existing record with new HA data
- If domain doesn't exist: Inserts new record

### Retry Logic

Exponential backoff for failed URL finding:
- **Retry 1**: 1 hour later
- **Retry 2**: 4 hours later
- **Retry 3**: 16 hours later
- **After 3 retries**: Gives up, deletes from staging

## Files Created

### Core Pipeline
1. **db/models.py** (modified)
   - Added `HAStaging` model class

2. **db/migrations/001_add_ha_staging_table.sql** (new)
   - SQL migration to create staging table

3. **db/save_to_staging.py** (new)
   - `save_to_staging()`: Save businesses to staging
   - `get_staging_stats()`: Get queue statistics

4. **scrape_ha/ha_crawl.py** (modified)
   - Changed to save to staging table instead of yielding results
   - Returns summary dict instead of generator

5. **scrape_ha/url_finder_worker.py** (new)
   - Continuous background worker
   - Polls staging table, finds URLs, upserts to companies
   - Implements retry logic and exponential backoff

### Launchers & Tools
6. **cli_crawl_ha_pipeline.py** (new)
   - Unified CLI launcher for both phases
   - Runs them concurrently
   - Supports --phase1-only, --phase2-only, --watch

7. **scrape_ha/pipeline_stats.py** (new)
   - Real-time monitoring and statistics
   - Shows staging queue size, pending, retries, failures
   - `--watch` mode for live monitoring

## Usage

### Run Full Pipeline
```bash
# Default: all categories, all states, 3 pages per state
source .venv/bin/activate
python cli_crawl_ha_pipeline.py

# Custom categories and states
python cli_crawl_ha_pipeline.py --categories "power washing,window cleaning" --states "TX,CA,NY"

# More pages per state
python cli_crawl_ha_pipeline.py --pages 5
```

### Run Individual Phases
```bash
# Phase 1 only (discovery)
python cli_crawl_ha_pipeline.py --phase1-only

# Phase 2 only (URL finder worker)
python cli_crawl_ha_pipeline.py --phase2-only
```

### Monitor Pipeline
```bash
# Show current stats
python scrape_ha/pipeline_stats.py

# Watch in real-time (refreshes every 10s)
python scrape_ha/pipeline_stats.py --watch

# Detailed breakdown
python scrape_ha/pipeline_stats.py --detailed
```

### Direct Module Usage
```bash
# Run Phase 1 discovery
python -m scrape_ha.ha_crawl

# Run Phase 2 worker
python -m scrape_ha.url_finder_worker

# View stats
python -m scrape_ha.pipeline_stats
```

## Database Setup

### Run Migration
```bash
# Option 1: Using psql (recommended)
PGPASSWORD="Washdb123" psql -h localhost -U washbot -d washbot_db -f db/migrations/001_add_ha_staging_table.sql

# Option 2: Using Python
python db/run_migration.py
```

### Verify Tables
```bash
PGPASSWORD="Washdb123" psql -h localhost -U washbot -d washbot_db -c "\d ha_staging"
```

## Configuration

### Worker Settings
Edit `scrape_ha/url_finder_worker.py`:
```python
POLL_INTERVAL_SECONDS = 30  # Poll staging table every 30 seconds
MIN_BATCH_SIZE = 10         # Wait for at least 10 businesses
MAX_RETRY_COUNT = 3         # Give up after 3 failed attempts
RETRY_DELAYS = [1, 4, 16]   # Exponential backoff in hours
```

### Search Settings
Edit `scrape_ha/url_finder.py`:
```python
MIN_SEARCH_DELAY = 8   # Minimum delay between searches (seconds)
MAX_SEARCH_DELAY = 15  # Maximum delay between searches (seconds)
```

### Discovery Settings
Edit `scrape_ha/ha_crawl.py`:
```python
CATEGORIES_HA = [
    "power washing",
    "window cleaning services",
    "deck staining or painting",
    "fence painting or staining",
]

STATES = ["AL", "AK", "AZ", ...]  # All 50 states
```

## Workflow Example

### Day 1: Initial Discovery
```bash
# Terminal 1: Run full pipeline
python cli_crawl_ha_pipeline.py --states "TX" --pages 3

# Terminal 2: Monitor in real-time
python scrape_ha/pipeline_stats.py --watch
```

**Expected Flow**:
1. Phase 1 starts scraping HomeAdvisor (TX, all categories, 3 pages each)
2. Businesses are saved to `ha_staging` table
3. Once 10+ businesses in queue, Phase 2 starts processing
4. Phase 2 searches DuckDuckGo for each business
5. Found URLs are saved to `companies` table (dedup by domain)
6. Processed businesses are deleted from `ha_staging`
7. Phase 1 completes, Phase 2 continues until queue is empty

### Day 2: Add More States
```bash
# Run discovery for new states (Phase 2 auto-processes existing queue)
python cli_crawl_ha_pipeline.py --states "CA,NY,FL" --pages 5
```

### Ongoing: Worker Only
```bash
# Just run Phase 2 worker to process any queued businesses
python cli_crawl_ha_pipeline.py --phase2-only
```

## Monitoring

### Stats Output Example
```
======================================================================
HomeAdvisor Pipeline Statistics - 2025-01-14 15:30:00
======================================================================

STAGING TABLE (Phase 1 → Phase 2 Queue)
----------------------------------------------------------------------
  Total Records:        142
  Ready to Process:     38  (can process now)
  Waiting for Retry:    12  (scheduled for later)
  Failed (max retries): 5   (gave up)
  Added (last hour):    87

COMPANIES TABLE (Production)
----------------------------------------------------------------------
  Total Companies:      1,247
  Active Companies:     1,247
  From HomeAdvisor:     285
  With HA Ratings:      285
  Added (last hour):    49
  From HA (last hour):  49

PIPELINE HEALTH
----------------------------------------------------------------------
  Status: ACTIVE - Phase 2 is processing
  Success Rate: 89.2%  (122/137 succeeded)
```

## Troubleshooting

### Queue Not Processing
**Symptom**: Businesses in staging, but Phase 2 not processing

**Check**:
```bash
python scrape_ha/pipeline_stats.py
```

**Solutions**:
- If "Ready to Process" < 10: Wait for more businesses (Phase 2 waits for batch)
- If "Waiting for Retry" > 0: Businesses scheduled for later retry
- If "Failed" high: Check logs for errors, may need to adjust search heuristics

### High Failure Rate
**Symptom**: Many businesses failing to find URLs

**Check**:
```bash
# View failed records
PGPASSWORD="Washdb123" psql -h localhost -U washbot -d washbot_db -c "SELECT name, last_error FROM ha_staging WHERE retry_count >= 3 LIMIT 10;"
```

**Solutions**:
- Adjust scoring heuristics in `scrape_ha/url_finder.py` (score_url_match function)
- Lower minimum score threshold
- Add more search result processing

### Worker Not Starting
**Symptom**: Phase 2 worker exits immediately

**Check**:
```bash
# Test worker directly
python -m scrape_ha.url_finder_worker
```

**Solutions**:
- Check DATABASE_URL in .env
- Verify Playwright is installed: `playwright install chromium`
- Check logs for error messages

## Performance

### Expected Throughput
- **Phase 1**: ~100-200 businesses/minute (depends on HomeAdvisor rate limits)
- **Phase 2**: ~4-6 businesses/minute (DuckDuckGo searches + 8-15s delay)

### Scaling Options
1. **Phase 1**: Can run multiple times for different state sets
2. **Phase 2**: Single worker recommended (DuckDuckGo rate limits)
3. **Database**: Indexes optimize for queue queries

### Resource Usage
- **Memory**: ~200-400 MB per worker
- **CPU**: Low (mostly network I/O bound)
- **Network**: Moderate (web scraping)

## Next Steps

### GUI Integration (TODO)
Update the existing GUI to:
- Show "START PIPELINE" instead of separate phase buttons
- Display Phase 1 and Phase 2 progress separately
- Show queue stats in real-time
- Add "STOP PIPELINE" button

### Future Enhancements
- [ ] Add worker pool for Phase 2 (multiple browsers)
- [ ] Implement rate limiting with exponential backoff
- [ ] Add metrics dashboard (success rate over time, etc.)
- [ ] Email notifications for failed batches
- [ ] Export failed businesses to CSV for manual review
- [ ] Add support for other directory sources (Yelp, BBB, etc.)
