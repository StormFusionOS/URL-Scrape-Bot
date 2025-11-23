# Google Maps Business Scraper - Implementation Guide

## Overview

A complete Playwright-based Google Maps scraper with extreme caution settings (30-60s delays, no proxies) to avoid detection. Fully integrated with the NiceGUI dashboard.

## ✅ Completed Implementation

### Phase 1: Backend Infrastructure

#### 1. Database Schema (`db/migrations/003_add_google_fields.sql`)
- Added `place_id` field for Google Place ID (unique identifier)
- Added `google_business_url` for Google Maps URLs
- Added `data_completeness` (0.0-1.0 quality score)
- Added `confidence_score` for data reliability
- Added `scrape_method` (tracks "playwright" vs other methods)
- Added indexes for performance

#### 2. Core Scraper Modules (`scrape_google/`)

**google_logger.py**
- 4 separate log files: scrape.log, errors.log, metrics.log, operations.log
- Structured logging with context and metadata
- Performance metrics tracking
- Session summaries

**google_config.py**
- Rate limiting: 30-60 second delays (configurable)
- Browser settings: Chromium, not headless (for testing)
- Max results, timeouts, retry logic
- Environment variable support

**google_client.py**
- Async Playwright browser automation
- Google Maps search with scrolling
- Business detail extraction (15+ fields)
- Screenshot capture on errors
- Graceful error handling

**google_parse.py**
- HTML parsing with multiple fallback strategies
- Extracts: name, address, phone, website, rating, reviews, hours, etc.
- Data quality scoring (completeness)
- Robust error handling

**google_crawl.py**
- Orchestration layer with queue-based processing
- Database integration (companies + scrape_logs tables)
- Duplicate detection by place_id
- Progress tracking with callbacks
- Update existing businesses on re-scrape

### Phase 2: GUI Integration

#### 3. Backend Facade (`niceui/backend_facade.py`)
Added `discover_google()` method:
- Wraps GoogleCrawler for synchronous UI calls
- Progress callback support
- Cancel flag handling
- Error handling and logging

#### 4. Discovery Page (`niceui/pages/discover_google.py`)
Complete UI with:
- Search configuration (query, location, max results 1-50)
- Warning banner about slow speeds
- Real-time progress tracking
- Stats cards: Found, Saved, Duplicates, Errors
- Live log output with color coding
- Cancel functionality
- Time estimates (45s per business)
- Detailed instructions

#### 5. Navigation Integration
- Added to `pages/__init__.py`
- Registered in `main.py` router
- Added "Google Maps" nav item in `layout.py`
- Icon: "map"

## Architecture

```
User Interface (NiceGUI)
    ↓
backend_facade.discover_google()
    ↓
GoogleCrawler.search_and_save()
    ↓
GoogleBusinessClient
    ├─ search_google_maps() → Playwright automation
    ├─ scrape_business_details() → Detail extraction
    └─ parse HTML → google_parse.py
         ↓
    Database (PostgreSQL)
    ├─ companies table (businesses)
    └─ scrape_logs table (audit trail)
```

## Configuration

### Default Settings (google_config.py)
```python
Rate Limiting:
  - min_delay: 30 seconds
  - max_delay: 60 seconds
  - request_timeout: 30 seconds

Browser:
  - Type: Chromium
  - Headless: True (required for servers without display)
  - Viewport: 1920x1080

Scraping:
  - max_results_per_search: 20
  - scroll_pause_time: 2.0 seconds
  - max_retries: 3
```

### Environment Variables (optional)
```bash
# Database
DATABASE_URL=postgresql://user:pass@host:port/dbname

# Google Scraper
GOOGLE_MIN_DELAY=30
GOOGLE_MAX_DELAY=60
GOOGLE_HEADLESS=false
GOOGLE_MAX_RESULTS=20
```

## Usage

### 1. Via GUI Dashboard

1. Start dashboard: `python -m niceui.main`
2. Navigate to "Google Maps" page
3. Enter search query (e.g., "car wash")
4. Enter location (e.g., "Seattle, WA")
5. Set max results (1-50)
6. Click "START GOOGLE SCRAPING"
7. Monitor live progress and logs

### 2. Via Test Script

```bash
# Run test with reduced delays for testing
python test_google_scraper.py

# The script searches for "car wash" in "Seattle, WA"
# Returns 3 results (configurable)
# Shows detailed extraction
```

### 3. Via Python Code

```python
import asyncio
from scrape_google import GoogleCrawler

async def scrape():
    crawler = GoogleCrawler()

    # Set progress callback (optional)
    def progress(status, message, stats):
        print(f"[{status}] {message}")
        print(f"Stats: {stats}")

    crawler.set_progress_callback(progress)

    # Run search and save
    result = await crawler.search_and_save(
        query="car wash",
        location="Seattle, WA",
        max_results=10,
        scrape_details=True
    )

    print(result)

asyncio.run(scrape())
```

## Data Extracted

### From Search Results:
- Business name
- Address
- Place ID (Google's unique ID)
- Google Maps URL
- Star rating (if visible)

### From Business Details (if scrape_details=True):
- Phone number
- Website
- Full address
- Rating (0.0-5.0)
- Review count
- Business category
- Hours of operation
- Plus button (Google link)
- Data completeness score (0.0-1.0)

## Database Schema

### companies table (key fields)
```sql
place_id VARCHAR(255) UNIQUE  -- Google Place ID
name VARCHAR(255)              -- Business name
address TEXT                   -- Full address
phone VARCHAR(50)              -- Phone number
website VARCHAR(500)           -- Website URL
rating DECIMAL(2,1)            -- Rating 0.0-5.0
category VARCHAR(255)          -- Business category
google_business_url TEXT       -- Google Maps URL
source VARCHAR(50)             -- "Google"
scrape_method VARCHAR(50)      -- "playwright"
data_completeness DECIMAL(3,2) -- 0.0-1.0
confidence_score DECIMAL(3,2)  -- 0.0-1.0
scrape_timestamp TIMESTAMP     -- Last scrape
last_scrape_attempt TIMESTAMP  -- Last attempt
```

### scrape_logs table
```sql
company_id INTEGER             -- FK to companies
scrape_method VARCHAR(50)      -- "playwright"
status VARCHAR(50)             -- success/partial/failed
fields_updated TEXT[]          -- Array of updated fields
error_message TEXT             -- Error details
scrape_duration_ms INTEGER     -- Performance metric
created_at TIMESTAMP           -- Log timestamp
```

## Logging

### Log Files (logs/ directory)
1. **google_scrape.log** - Main operations log
2. **google_errors.log** - Errors and exceptions only
3. **google_metrics.log** - Performance metrics
4. **google_operations.log** - Business operations

### Log Levels
- INFO: Normal operations
- WARNING: Recoverable issues
- ERROR: Failures and exceptions
- DEBUG: Detailed debugging (disabled by default)

## Important Notes

### ⚠️ Rate Limiting
- **Default: 30-60 seconds between requests**
- This is EXTREMELY SLOW by design
- 10 businesses = ~5-10 minutes
- DO NOT reduce delays in production (risk of detection)

### ⚠️ Detection Avoidance
- No proxies (single IP)
- Long delays between requests
- Human-like scrolling and interactions
- Browser fingerprint (real Chrome)
- NOT headless by default

### ⚠️ CAPTCHA Handling
- If CAPTCHA appears: STOP immediately
- Wait several hours before retrying
- Consider reducing max_results
- DO NOT attempt to bypass CAPTCHA

### ⚠️ Best Practices
1. Start with small batches (5-10 results)
2. Test with headless=False first
3. Monitor logs for errors
4. Respect rate limits
5. Don't scrape during peak hours
6. Use location-specific searches

## Testing

### Quick Validation Test
```bash
# Test 1: Verify imports
python -c "from scrape_google import GoogleCrawler; print('✓ Imports OK')"

# Test 2: Check Playwright
playwright --version

# Test 3: Run test script (3 results, faster delays)
python test_google_scraper.py
```

### Integration Test
```bash
# Start dashboard
python -m niceui.main

# Navigate to: http://127.0.0.1:8080
# Click "Google Maps" in navigation
# Run a test search with 3 results
# Verify logs appear in real-time
```

## Troubleshooting

### Playwright Issues
```bash
# Install browsers if missing
playwright install chromium

# Check installation
playwright install --dry-run
```

### Database Connection
```bash
# Test database connection
python -c "import psycopg; conn = psycopg.connect('your-db-url'); print('✓ DB OK')"

# Check .env file
cat .env | grep DATABASE_URL
```

### Import Errors
```bash
# Verify Python path
python -c "import sys; print('\n'.join(sys.path))"

# Reinstall dependencies
pip install -r requirements.txt
```

## Performance

### Expected Speeds
- **Search**: ~5-10 seconds
- **Detail scrape**: ~30-60 seconds per business
- **10 businesses**: ~5-10 minutes
- **50 businesses**: ~25-50 minutes

### Optimization (NOT RECOMMENDED)
- Reducing delays increases detection risk
- Headless mode slightly faster but less realistic
- Parallel scraping = instant ban

## Future Enhancements

### Potential Additions
1. Settings page configuration (rate limits, headless mode)
2. Database page filters for Google-sourced companies
3. Export Google results to CSV
4. Scheduling/automation
5. Proxy rotation (advanced)
6. CAPTCHA detection and pause

## Files Reference

```
washdb-bot/
├── db/migrations/
│   └── 003_add_google_fields.sql      # Database schema
├── scrape_google/
│   ├── __init__.py                     # Module exports
│   ├── google_logger.py                # Logging infrastructure
│   ├── google_config.py                # Configuration management
│   ├── google_client.py                # Playwright browser automation
│   ├── google_parse.py                 # HTML parsing utilities
│   └── google_crawl.py                 # Orchestration layer
├── niceui/
│   ├── backend_facade.py               # GUI-backend integration
│   ├── pages/
│   │   ├── __init__.py                 # Page exports
│   │   └── discover_google.py          # Google Maps UI page
│   ├── layout.py                       # Navigation menu
│   └── main.py                         # App entry point
├── test_google_scraper.py              # Test script
└── GOOGLE_SCRAPER_README.md           # This file
```

## License & Legal

This scraper is intended for:
- Educational purposes
- Personal research
- Lead generation with proper consent
- Market research

**DO NOT:**
- Violate Google's Terms of Service
- Scrape at high volume
- Use for spam or harassment
- Sell scraped data without permission

**User responsibility:**
- Comply with local laws
- Respect robots.txt and rate limits
- Obtain necessary permissions
- Use ethically and responsibly

---

**Created:** 2025-11-10
**Version:** 1.0.0
**Author:** washdb-bot (Claude Code)
