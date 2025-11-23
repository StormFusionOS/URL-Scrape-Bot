# Parallel Yellow Pages Scraping Guide

## Overview

The parallel scraping system allows you to run 30-35 workers simultaneously using your 50 Webshare proxies, reducing scrape time from **215 days to ~10-11 days**.

## What Was Implemented

### Core Components

1. **Proxy Pool Management** (`scrape_yp/proxy_pool.py`)
   - Loads 50 Webshare proxies
   - Health tracking with success/failure rates
   - Automatic blacklisting of bad proxies (10 failures → 60 min blacklist)
   - Thread-safe proxy rotation

2. **Worker Configuration** (`scrape_yp/worker_config.py`)
   - Centralized configuration from `.env` file
   - 35 parallel workers (configurable)
   - Delays, retries, browser settings, etc.

3. **Worker Pool** (`scrape_yp/worker_pool.py`)
   - Multiprocessing worker pool (35 processes)
   - Database locking with `SELECT FOR UPDATE SKIP LOCKED` (PostgreSQL)
   - Automatic proxy rotation on failures
   - Per-worker persistent browsers
   - Graceful shutdown and error recovery

4. **Launch Script** (`scripts/run_parallel_scrape.py`)
   - Pre-flight checks (config validation, proxy testing)
   - Stops existing single-worker scrapers
   - Launches worker pool
   - Progress monitoring

## Quick Start

### 1. Your Proxies Are Already Loaded

Your 50 Webshare proxies have been copied to:
```
/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/data/webshare_proxies.txt
```

### 2. Configuration Is Ready

The `.env` file has been updated with:
- `WORKER_COUNT=35` (30-35 workers as recommended)
- `PROXY_FILE=data/webshare_proxies.txt`
- All other settings optimized for balanced speed/safety

### 3. Launch Parallel Scraping

```bash
cd /home/rivercityscrape/URL-Scrape-Bot/washdb-bot

# Activate virtual environment
source /opt/ai-seo/url-scrape-bot/.venv/bin/activate

# Run the launch script
python scripts/run_parallel_scrape.py
```

The script will:
1. Validate configuration
2. Test first 5 proxies
3. Stop any existing scrapers
4. Show target statistics and estimated completion time
5. Ask for confirmation
6. Launch 35 workers

## Monitoring Progress

### Option 1: GUI Dashboard (Recommended)
Visit http://127.0.0.1:8080 → Discover → Yellow Pages

### Option 2: Worker Logs
```bash
# Watch all workers
tail -f logs/worker_*.log

# Watch specific worker
tail -f logs/worker_0.log

# Watch pool manager
tail -f logs/worker_pool.log
```

### Option 3: Database Queries
```bash
# Check progress by status
PGPASSWORD="Washdb123" psql -h localhost -U washbot -d washbot_db -c \
  "SELECT status, COUNT(*) FROM yp_targets GROUP BY status ORDER BY status;"

# Check completion percentage
PGPASSWORD="Washdb123" psql -h localhost -U washbot -d washbot_db -c \
  "SELECT
    COUNT(*) FILTER (WHERE status = 'done') * 100.0 / COUNT(*) as pct_complete,
    COUNT(*) FILTER (WHERE status = 'planned') as remaining
  FROM yp_targets;"
```

## Performance Expectations

### Speed
- **35 workers** × **~1 target/minute** = **~2,100 targets/hour**
- **~50,400 targets/day**
- **309,720 total targets** ÷ 50,400/day = **~6-7 days** (accounting for delays/errors: **~10-11 days**)

### Resource Usage
- **RAM**: ~15-20GB (35 browsers)
- **CPU**: Moderate (mostly I/O bound)
- **Bandwidth**: ~5-10GB of your 5TB limit (plenty of headroom)
- **Proxies**: Round-robin usage across all 50 proxies

## Key Features

### 1. Database Locking (No Duplicates)
Workers use PostgreSQL `SELECT FOR UPDATE SKIP LOCKED` to atomically acquire targets. This guarantees:
- ✅ No two workers process the same target
- ✅ No race conditions
- ✅ Efficient parallelization

### 2. Automatic Proxy Rotation
- Worker tries proxy → fails → reports failure
- After 10 failures → proxy blacklisted for 60 minutes
- Worker automatically gets next healthy proxy
- Proxy stats tracked (success rate, last used, etc.)

### 3. Persistent Browsers
- Each worker launches one browser with assigned proxy
- Browser stays open for 100 targets (configurable)
- Then restarts to prevent memory leaks
- Much faster than launching browser per target

### 4. Error Recovery
- Target fails → marked back as 'planned' for retry
- After 3 attempts → marked as 'failed'
- Workers auto-restart on crashes (up to 5 times)
- Graceful shutdown on Ctrl+C

### 5. Anti-Detection
- All existing anti-detection features enabled:
  - User agent randomization
  - Viewport randomization
  - Hardware concurrency spoofing
  - WebDriver property masking
  - Human-like scrolling
  - Session breaks (30-90s every 50 requests)
  - Adaptive rate limiting

## Configuration Options

Edit `.env` to customize:

```bash
# Number of workers (30-50 recommended)
WORKER_COUNT=35

# Delay between targets (per worker)
MIN_DELAY_SECONDS=5.0
MAX_DELAY_SECONDS=15.0

# Proxy settings
PROXY_BLACKLIST_THRESHOLD=10          # Failures before blacklist
PROXY_BLACKLIST_DURATION_MINUTES=60   # How long to blacklist
PROXY_SELECTION_STRATEGY=round_robin  # or 'health_based'

# Browser settings
MAX_TARGETS_PER_BROWSER=100           # Restart browser after N targets
BROWSER_HEADLESS=true                 # Use headless mode

# Retry settings
MAX_TARGET_RETRY_ATTEMPTS=3           # Retries per target
TARGET_TIMEOUT_MINUTES=30             # Reset stuck targets after 30 min

# Target limits (for testing)
TARGET_STATES=ALL                     # Or 'RI,MA,CT' for specific states
# MAX_TOTAL_TARGETS=1000              # Uncomment to limit total targets
```

## Stopping the Scrape

### Graceful Stop (Recommended)
Press `Ctrl+C` in the terminal running the workers. This will:
1. Signal all workers to stop
2. Workers finish current target
3. Clean shutdown (30s timeout per worker)

### Force Stop
```bash
ps aux | grep worker_pool | awk '{print $2}' | xargs kill -9
```

## Resuming After Stop

Just run the launch script again:
```bash
python scripts/run_parallel_scrape.py
```

Workers will automatically pick up where they left off (only 'planned' targets are processed).

## Troubleshooting

### "No healthy proxies available!"
**Cause:** All proxies blacklisted or failed pre-test

**Solutions:**
1. Check proxy file format: `cat data/webshare_proxies.txt | head -5`
2. Test proxies manually: `python -m scrape_yp.proxy_pool`
3. Contact Webshare support for replacement IPs
4. Temporarily reduce `PROXY_BLACKLIST_THRESHOLD` in `.env`

### "No planned targets found"
**Cause:** Targets not generated or all completed

**Solutions:**
1. Generate targets: `python -m scrape_yp.generate_city_targets --states AL,AK,AZ,... --clear`
2. Or check status: `psql -c "SELECT status, COUNT(*) FROM yp_targets GROUP BY status;"`

### Workers crash immediately
**Cause:** Usually proxy or database connection issues

**Solutions:**
1. Check logs: `cat logs/worker_0.log`
2. Test database: `python -m db.save_discoveries`
3. Test proxies: `python -m scrape_yp.proxy_pool`
4. Reduce worker count: `WORKER_COUNT=5` in `.env`

### High memory usage
**Cause:** Too many browsers open

**Solutions:**
1. Reduce `WORKER_COUNT` (e.g., to 20)
2. Reduce `MAX_TARGETS_PER_BROWSER` (restart browsers more often)
3. Monitor with: `ps aux | grep chromium | wc -l`

### Slow progress
**Cause:** Proxies failing or delays too high

**Solutions:**
1. Check proxy health: `python -m scrape_yp.proxy_pool` → stats
2. Reduce delays: `MIN_DELAY_SECONDS=3.0` and `MAX_DELAY_SECONDS=8.0`
3. Increase workers: `WORKER_COUNT=50`

## After Initial Scrape Completes

### Switch to Maintenance Mode

1. **Stop parallel workers:**
   ```bash
   # Ctrl+C or kill workers
   ```

2. **Remove proxies from `.env`:**
   ```bash
   # Comment out or remove proxy settings
   # PROXY_FILE=...
   # WORKER_COUNT=...
   ```

3. **Run single-worker maintenance:**
   ```bash
   # Weekly re-scrape of stale records (30+ days old)
   python cli_crawl_yp.py --states AL,AK,... --max-targets 5000
   ```

This saves $40-60/month on proxies while keeping data fresh.

## Files Created

```
washdb-bot/
├── scrape_yp/
│   ├── proxy_pool.py          # Proxy management
│   ├── worker_pool.py         # Worker orchestration
│   └── worker_config.py       # Configuration
├── scripts/
│   └── run_parallel_scrape.py # Launch script
├── data/
│   ├── proxies.txt            # Template
│   └── webshare_proxies.txt   # Your 50 proxies
├── logs/
│   ├── worker_0.log           # Worker logs (0-34)
│   ├── worker_1.log
│   └── worker_pool.log        # Pool manager log
└── .env                       # Updated config

Original files (unchanged):
├── cli_crawl_yp.py            # Single-worker (still works)
├── scrape_yp/
│   ├── yp_crawl_city_first.py # Core crawl logic (reused)
│   ├── yp_parser_enhanced.py  # Parser (reused)
│   ├── yp_filter.py           # Filter (reused)
│   └── yp_stealth.py          # Anti-detection (reused)
```

## Summary

You now have a production-ready parallel scraping system that will complete your initial database build in **~10-11 days** instead of 215 days. The system is:

- ✅ **Fast**: 35 workers = 50,400 targets/day
- ✅ **Reliable**: Database locking prevents duplicates
- ✅ **Resilient**: Automatic proxy rotation and error recovery
- ✅ **Safe**: All anti-detection features enabled
- ✅ **Monitored**: Logs, GUI dashboard, database queries

Ready to launch when you are!

```bash
cd /home/rivercityscrape/URL-Scrape-Bot/washdb-bot
source /opt/ai-seo/url-scrape-bot/.venv/bin/activate
python scripts/run_parallel_scrape.py
```
