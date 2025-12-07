# Continuous SERP Scraper Setup Guide

## Overview

The continuous SERP scraper monitors your verified pressure washing companies' Google search rankings at a slow, undetectable rate (1-2 sites per hour).

## Features

- **Ultra-slow rate limiting**: 30-60 minutes between requests (1-2 sites/hour)
- **Cycle-based operation**: Scrapes all verified companies, then rests 60 minutes before restarting
- **CAPTCHA cooldown**: Pauses for 2 hours after 3 consecutive CAPTCHAs
- **Auto-resume**: Tracks progress and resumes from last position on restart
- **Systemd integration**: Automatically restarts on system reboot
- **Comprehensive anti-fingerprinting**: All the improvements made to base_scraper.py apply here

## Database Configuration

### Source Database (Input)
- **Database**: `washbot_db` (main database)
- **Table**: `companies`
- **Query**: Companies where `parse_metadata->'verification'->>'status' = 'passed'` AND `active = true` AND `website IS NOT NULL`
- **Purpose**: Gets list of verified companies to scrape

### Target Database (Output)
- **Database**: `washbot_db` (same database)
- **Tables**:
  - `search_queries`: Stores search queries and metadata
  - `serp_snapshots`: Stores SERP snapshots with HTML and hash
  - `serp_results`: Individual search results with position, URL, title, snippet
  - `serp_paa`: People Also Ask questions and answers
- **Purpose**: Stores all SERP ranking data for analysis

**NOTE**: Both input and output use the same `washbot_db` database. The SERP scraper reads from `companies` table and writes to `serp_*` tables.

## Files Created

1. **`scripts/continuous_serp_scraper.py`** - Main scraper script
2. **`/tmp/washbot-serp-scraper.service`** - Systemd service file
3. **`scripts/install_serp_service.sh`** - Installation helper script
4. **`.serp_scraper_progress.json`** - Progress tracking file (auto-created)

## Installation

### Option 1: Manual Installation

```bash
cd /home/rivercityscrape/URL-Scrape-Bot/washdb-bot

# Test dry run first (no actual scraping)
./venv/bin/python scripts/continuous_serp_scraper.py --dry-run

# Run manually (will run forever until Ctrl+C)
./venv/bin/python scripts/continuous_serp_scraper.py
```

### Option 2: Systemd Service (Recommended)

```bash
cd /home/rivercityscrape/URL-Scrape-Bot/washdb-bot

# Run installation script
./scripts/install_serp_service.sh

# The script will:
# 1. Install the service file to /etc/systemd/system/
# 2. Enable auto-start on boot
# 3. Ask if you want to start it now
```

## Service Management

### Start/Stop/Restart

```bash
# Start service
sudo systemctl start washbot-serp-scraper

# Stop service
sudo systemctl stop washbot-serp-scraper

# Restart service
sudo systemctl restart washbot-serp-scraper

# Check status
sudo systemctl status washbot-serp-scraper
```

### View Logs

```bash
# Follow live logs (systemd journal)
sudo journalctl -u washbot-serp-scraper -f

# View recent logs
sudo journalctl -u washbot-serp-scraper -n 100

# View log file directly
tail -f logs/serp_scraper_service.log
```

### Disable Auto-Start

```bash
# Disable service (won't start on boot)
sudo systemctl disable washbot-serp-scraper

# Stop and disable
sudo systemctl stop washbot-serp-scraper
sudo systemctl disable washbot-serp-scraper
```

## Configuration Options

Edit the systemd service file to change options:

```bash
sudo nano /etc/systemd/system/washbot-serp-scraper.service
```

Change this line to adjust CAPTCHA threshold:
```ini
ExecStart=/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/venv/bin/python \
    /home/rivercityscrape/URL-Scrape-Bot/washdb-bot/scripts/continuous_serp_scraper.py \
    --max-consecutive-captchas 3
```

After editing, reload and restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart washbot-serp-scraper
```

## Rate Limits

### Per-Site Delay
- **Min**: 30 minutes (1800 seconds)
- **Max**: 60 minutes (3600 seconds)
- **Rate**: ~1-2 sites per hour

### Cycle Rest
- **Duration**: 60 minutes (3600 seconds)
- **When**: After completing all verified companies

### CAPTCHA Cooldown
- **Threshold**: 3 consecutive CAPTCHAs
- **Duration**: 2 hours (7200 seconds)
- **Purpose**: Back off when detection occurs

## Progress Tracking

The scraper maintains state in `.serp_scraper_progress.json`:

```json
{
  "last_scraped_id": 12345,
  "last_updated": "2025-12-06T10:30:00",
  "cycle_num": 3,
  "total_scraped": 150,
  "total_captchas": 5
}
```

This allows the scraper to resume from where it left off if interrupted.

## Search Query Format

For each company, the scraper builds a Google search query:

```
"Company Name" City State
```

Example:
```
"ABC Pressure Washing" Austin TX
```

The quotes around the company name ensure exact match searching.

## Database Schema

### search_queries table
```sql
query_id        SERIAL PRIMARY KEY
query_text      TEXT
location        TEXT
search_engine   TEXT (default: 'google')
is_active       BOOLEAN
created_at      TIMESTAMP
```

### serp_snapshots table
```sql
snapshot_id     SERIAL PRIMARY KEY
query_id        INTEGER (FK)
result_count    INTEGER
snapshot_hash   TEXT
raw_html        TEXT (optional)
metadata        JSONB
created_at      TIMESTAMP
```

### serp_results table
```sql
result_id           SERIAL PRIMARY KEY
snapshot_id         INTEGER (FK)
position            INTEGER
url                 TEXT
title               TEXT
description         TEXT
domain              TEXT
is_our_company      BOOLEAN
is_competitor       BOOLEAN
competitor_id       INTEGER
metadata            JSONB
embedding_version   TEXT
embedded_at         TIMESTAMP
created_at          TIMESTAMP
```

### serp_paa table (People Also Ask)
```sql
paa_id              SERIAL PRIMARY KEY
snapshot_id         INTEGER (FK)
query_id            INTEGER (FK)
question            TEXT
answer_snippet      TEXT
source_url          TEXT
source_domain       TEXT
position            INTEGER
metadata            JSONB
first_seen          TIMESTAMP
last_seen           TIMESTAMP
seen_count          INTEGER
```

## Monitoring

### Check Current Status

```bash
# Service status
sudo systemctl status washbot-serp-scraper

# Recent activity
sudo journalctl -u washbot-serp-scraper -n 50

# Current progress
cat .serp_scraper_progress.json | python3 -m json.tool
```

### Database Query Examples

```sql
-- Check recent SERP snapshots
SELECT
    sq.query_text,
    sq.location,
    ss.result_count,
    ss.created_at
FROM serp_snapshots ss
JOIN search_queries sq ON ss.query_id = sq.query_id
ORDER BY ss.created_at DESC
LIMIT 10;

-- Find our company rankings
SELECT
    sq.query_text,
    sr.position,
    sr.url,
    sr.title,
    ss.created_at
FROM serp_results sr
JOIN serp_snapshots ss ON sr.snapshot_id = ss.snapshot_id
JOIN search_queries sq ON ss.query_id = sq.query_id
WHERE sr.is_our_company = true
ORDER BY ss.created_at DESC;

-- CAPTCHA detection rate
SELECT
    DATE(created_at) as date,
    COUNT(*) as total_snapshots,
    COUNT(*) FILTER (WHERE result_count < 3) as suspected_captchas
FROM serp_snapshots
GROUP BY DATE(created_at)
ORDER BY date DESC;
```

## Troubleshooting

### Service Won't Start

```bash
# Check logs
sudo journalctl -u washbot-serp-scraper -n 100

# Common issues:
# 1. Virtual environment path incorrect
# 2. .env file missing or DATABASE_URL not set
# 3. Permission issues with log directory
```

### Too Many CAPTCHAs

If you're getting excessive CAPTCHAs:

1. **Increase delays** (edit `continuous_serp_scraper.py`):
   ```python
   MIN_DELAY_SECONDS = 3600  # 1 hour
   MAX_DELAY_SECONDS = 7200  # 2 hours
   ```

2. **Add residential proxies** (requires paid proxy service)

3. **Reduce concurrent operations** (only run SERP scraper, pause other scrapers)

### Progress File Corrupted

```bash
# Delete and restart from beginning
rm .serp_scraper_progress.json
sudo systemctl restart washbot-serp-scraper
```

## Performance Expectations

- **Companies**: ~5,000-10,000 verified companies
- **Rate**: 1-2 sites/hour = 24-48 sites/day
- **Full cycle**: ~200-400 days for 10,000 companies
- **Cycle rest**: 60 minutes after each complete cycle
- **Memory**: ~500MB-1GB (browser headless)
- **CPU**: Low (<5% average)

## Security & Privacy

- Service runs as `rivercityscrape` user (not root)
- Limited filesystem access (systemd hardening)
- No new privileges allowed
- Private /tmp directory
- Read-only home directory
- Only logs/ directory is writable

## Next Steps

After installation:

1. **Monitor first few scrapes** to ensure working correctly
2. **Check database** to verify data being stored
3. **Review logs** for any errors or warnings
4. **Set up alerts** (optional) for service failures
5. **Plan data analysis** strategy for SERP ranking data
