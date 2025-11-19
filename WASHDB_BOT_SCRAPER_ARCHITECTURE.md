# Yellow Pages/Yelp Scraper Architecture - washdb-bot

Comprehensive analysis of the current scraper implementation for designing a Google Business scraper.

## PROJECT OVERVIEW

**Project**: washdb-bot (URL Scraping Bot)
**Current Scraper**: Yellow Pages (YP) + Website Enrichment
**Language**: Python 3.12
**Framework**: NiceGUI (web frontend) + Flask Backend + SQLAlchemy ORM
**Database**: PostgreSQL
**Key Libraries**: Playwright, BeautifulSoup4, SQLAlchemy, requests

---

## 1. FILE STRUCTURE AND KEY COMPONENTS

### Directory Organization
```
washdb-bot/
├── scrape_yp/                    # Yellow Pages scraping (discovery phase)
│   ├── yp_client.py             # YP API client with requests/Playwright
│   ├── yp_client_playwright.py  # Playwright-specific implementation
│   ├── yp_crawl.py              # Multi-page crawling orchestration
│   ├── fetch_categories.py      # Category discovery
│   └── test_categories.py       # Category testing
│
├── scrape_site/                  # Website scraping (enrichment phase)
│   ├── site_scraper.py          # Main website scraper
│   ├── site_parse.py            # Content extraction/parsing
│   └── __init__.py
│
├── runner/                       # Orchestration & CLI
│   ├── main.py                  # CLI entry point
│   ├── logging_setup.py         # Centralized logging
│   └── bootstrap.py             # Startup initialization
│
├── db/                          # Database layer
│   ├── models.py                # SQLAlchemy Company model
│   ├── save_discoveries.py      # Upsert discovered companies
│   ├── update_details.py        # Batch website scraping/enrichment
│   ├── init_db.py               # Database initialization
│   └── __pycache__/
│
├── niceui/                      # Web GUI (NiceGUI frontend)
│   ├── backend_facade.py        # API facade for scraper backend
│   ├── pages/
│   │   ├── discover.py          # Discovery UI page
│   │   ├── scrape.py            # Scraping UI page
│   │   ├── dashboard.py         # Dashboard/stats
│   │   ├── database.py          # Database viewer
│   │   ├── logs.py              # Log viewer
│   │   ├── status.py            # Status/monitoring
│   │   ├── settings.py          # Settings
│   │   └── single_url.py        # Single URL scraping
│   ├── layout.py                # Main layout
│   ├── main.py                  # NiceGUI app entry
│   ├── config_manager.py        # Configuration handling
│   └── widgets/                 # Reusable UI components
│
├── gui_backend/                 # Flask REST API (legacy backend)
│   ├── app.py                   # Flask app factory
│   ├── api/
│   │   ├── scraper_routes.py    # Scraper control endpoints
│   │   ├── data_routes.py       # Data access endpoints
│   │   └── stats_routes.py      # Statistics endpoints
│   ├── models/
│   │   └── db_manager.py        # Database access layer
│   └── config.py                # Configuration
│
├── logs/                        # Log files (rotated)
├── data/                        # CSV exports of discoveries
│
├── .env                         # Environment configuration
├── requirements.txt             # Python dependencies
└── ADVANCED_ANTI_BLOCKING.md   # Anti-blocking strategies doc
```

---

## 2. YEP SCRAPER END-TO-END WORKFLOW

### 2.1 Phase 1: Discovery (Yellow Pages)
**Purpose**: Find all businesses matching category/location criteria

#### Key Files
- `scrape_yp/yp_client.py` - Individual page fetching
- `scrape_yp/yp_crawl.py` - Multi-page crawling
- `runner/main.py` - CLI orchestration

#### Discovery Workflow
```
User inputs:
  - Categories: ["pressure washing", "window cleaning", ...]
  - States: ["TX", "CA", "FL", ...]
  - Pages per pair: 3

↓

crawl_all_states() generator
  For each state × category combination:
    crawl_category_location()
      For page 1 to max_pages:
        1. fetch_yp_search_page()
           - Rate limit with delay (±20% jitter)
           - Retry on 429/500+ with exponential backoff
           - Use Playwright if USE_PLAYWRIGHT=true
           - Add human behavior simulation
        
        2. parse_yp_results()
           - Extract business name
           - Extract phone number
           - Extract address
           - Extract website/URL
           - Extract YP rating & review count
           
        3. De-duplicate by domain
        4. Normalize URLs and domains
        5. Check for last page
        
      Aggregate results across pages

↓

upsert_discovered() in database
  - Check if website already exists (unique constraint)
  - INSERT if new
  - UPDATE if exists (merge non-null fields)
  - Return counts: (inserted, updated, skipped)

↓

Output to database + CSV export
```

#### Key Functions

**`fetch_yp_search_page(category, location, page, delay)`**
```python
# Builds URL: https://www.yellowpages.com/search?search_terms=...&geo_location_terms=...&page=...
# Returns HTML content
# Handles both requests library and Playwright
# Retries with exponential backoff on errors
```

**`parse_yp_results(html)`**
```python
# Returns list of dicts:
[
  {
    'name': str,
    'phone': str or None,
    'address': str or None,
    'website': str or None,
    'rating_yp': float or None,
    'reviews_yp': int or None,
    'source': 'YP'
  },
  ...
]
```

**`crawl_category_location(category, location, max_pages=50)`**
```python
# Returns de-duplicated list of businesses
# Stops early if no new results or detected last page
# Respects rate limiting between pages
```

**`crawl_all_states(categories, states, limit_per_state)`**
```python
# Generator that yields batches:
# {
#   'category': str,
#   'state': str,
#   'results': list[dict],
#   'count': int,
#   'error': str or None  # If batch failed
# }
#
# Includes 15-25s cooldown between states
```

### 2.2 Phase 2: Website Enrichment (Details Scraping)
**Purpose**: Extract detailed information from discovered website URLs

#### Key Files
- `scrape_site/site_scraper.py` - Website fetching & multi-page discovery
- `scrape_site/site_parse.py` - Content parsing & extraction
- `db/update_details.py` - Batch update orchestration

#### Enrichment Workflow
```
Companies in database with URLs
  (either from YP discovery or manual entry)

↓

update_batch(limit=100, stale_days=30, only_missing_email=False)
  Query for companies that need updating:
    - Never updated (last_updated IS NULL), OR
    - Last updated > 30 days ago, OR
    - Missing email (if only_missing_email=True)

  For each company (up to limit):
    update_company_details(website)
      1. Fetch homepage
         - Rate limit with CRAWL_DELAY_SECONDS (2 seconds default)
         - Standard browser headers
         
      2. Parse homepage content via parse_site_content()
         - Extract: name, phones, emails, services, service_area, address
         - Use JSON-LD if available
         - Regex patterns for contact info
         
      3. Discover internal pages (Contact, About, Services)
         - Keyword matching on href and link text
         - Return URLs for up to 3 pages
         
      4. Fetch additional pages if needed
         - Only fetch if homepage missing key info
         - Merge results with preference logic:
           * Emails: prefer business domain emails
           * Phones: merge all unique values
           * Services/address: use first non-null
           
      5. Update database
         - Only update fields with new non-null data
         - Set last_updated timestamp
         
      Track: updated count, field updates, errors

↓

Return summary: {
  'total_processed': int,
  'updated': int,
  'skipped': int,
  'errors': int,
  'fields_updated': {'email': 25, 'phone': 30, ...}
}
```

#### Key Functions

**`scrape_website(url)`**
```python
# Process:
# 1. Fetch homepage (delay=0 for first)
# 2. parse_site_content() → extract info
# 3. If missing contact/services, discover internal pages
# 4. Fetch up to 3 additional pages
# 5. Merge results with conflict resolution
#
# Returns: {
#   'name': str or None,
#   'phones': list[str],
#   'emails': list[str],
#   'services': str or None,
#   'service_area': str or None,
#   'address': str or None,
#   'reviews': dict or None
# }
```

**`parse_site_content(html, base_url)`**
```python
# 1. Extract JSON-LD structured data
# 2. Use regex patterns to find:
#    - Phones: \d{3}[-.]?\d{3}[-.]?\d{4}
#    - Emails: \b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b
# 3. Keyword-based content extraction:
#    - Services text (look for 'services', 'pressure', 'washing', etc.)
#    - Service area (look for 'service area', 'serving', etc.)
#    - Address (look for address in text/HTML)
# 4. Parse company name from tags
#
# Returns: structured dict with extracted fields
```

**`discover_internal_links(html, base_url)`**
```python
# Scan all links, match against keywords:
# - Contact: ['contact', 'contact-us', 'get-in-touch', 'reach-us']
# - About: ['about', 'about-us', 'who-we-are', 'our-story']
# - Services: ['services', 'what-we-do', 'our-services', 'solutions']
#
# Returns: {'contact': url or None, 'about': url or None, 'services': url or None}
```

---

## 3. DATABASE SCHEMA

### Company Model (SQLAlchemy)
```python
class Company(Base):
    __tablename__ = "companies"
    
    # Primary Key
    id: int (autoincrement)
    
    # Core Information
    name: str or None
    website: str (unique, indexed)     # Canonical URL
    domain: str (indexed)              # example.com
    
    # Contact Information
    phone: str or None
    email: str or None
    
    # Business Details
    services: str or None              # Text description
    service_area: str or None          # Geographic area
    address: str or None               # Physical address
    
    # Source & Ratings
    source: str or None                # 'YP', 'Google', 'Manual', etc.
    rating_yp: float or None           # Yellow Pages rating (0-5)
    rating_google: float or None       # Google rating (0-5)
    reviews_google: int or None        # Google review count
    reviews_yp: int or None            # YP review count
    
    # Status & Timestamps
    active: bool (default=True)
    created_at: datetime (server default)
    last_updated: datetime or None
```

### Key Constraints & Indexes
- `website` is UNIQUE - prevents duplicate entries
- `domain` is INDEXED - for efficient lookups
- `created_at` and `last_updated` track data freshness

### Helper Functions (models.py)

**`canonicalize_url(raw_url)`**
```python
# Normalizes URLs to canonical form:
# 1. Ensure https:// scheme (default if missing)
# 2. Remove fragment (#section)
# 3. Remove trailing slash (unless root)
# 4. Remove www. subdomain
# 5. Convert to lowercase
#
# Example: "http://www.example.com/" → "https://example.com"
```

**`domain_from_url(url)`**
```python
# Extract registered domain using tldextract:
# https://www.example.com/path → example.com
# https://subdomain.example.co.uk → example.co.uk
```

---

## 4. GUI INTEGRATION POINTS

### 4.1 NiceGUI Frontend Architecture

**Entry Point**: `niceui/main.py` → starts HTTP server at http://localhost:8000

**Pages**: (all in `niceui/pages/`)

1. **discover.py** - URL Discovery
   - Configure categories, states, pages per pair
   - Real-time progress tracking
   - Live log output
   - Export new URLs

2. **scrape.py** - Website Enrichment
   - Configure update limits, stale days
   - Option to only update missing email
   - Real-time progress
   - Summary statistics

3. **single_url.py** - Single URL Preview
   - Scrape one URL without saving
   - Show extracted data
   - Option to save to database

4. **dashboard.py** - Statistics
   - Total companies
   - Companies by source
   - Completeness metrics

5. **database.py** - Company Browser
   - Search/filter companies
   - View details
   - Manage active status

6. **logs.py** - Log Viewer
   - Follow real-time logs
   - Filter by level
   - Download logs

### 4.2 Backend Facade (niceui/backend_facade.py)

**Purpose**: Bridge between NiceGUI frontend and scraper backend

**Key Methods**:

```python
class BackendFacade:
    def discover(
        categories: List[str],
        states: List[str],
        pages_per_pair: int,
        cancel_flag: Callable[[], bool],      # Check this to cancel
        progress_callback: Callable[[dict], None]  # Send progress updates
    ) → Dict[str, int]
    # Returns: {found, new, updated, errors, pairs_done, pairs_total}
    
    # Progress callback receives:
    # - 'batch_start': Starting new category-state pair
    # - 'batch_complete': Finished pair with counts
    # - 'batch_empty': No results found
    # - 'batch_error': Error during crawl
    # - 'save_error': Error saving to database
    # - 'cancelled': User cancelled operation

    def scrape_batch(
        limit: int,
        stale_days: int,
        only_missing_email: bool,
        cancel_flag: Callable[[], bool],
        progress_callback: Callable[[dict], None]
    ) → Dict[str, int]
    # Returns: {processed, updated, skipped, errors}

    def scrape_one_preview(url: str) → Dict[str, Any]
    # Preview scrape (no database save)

    def upsert_from_scrape(scrape_result: Dict) → Dict[str, Any]
    # Save preview result to database
```

### 4.3 Communication Pattern

```
NiceGUI Frontend (async)
    ↓ calls
BackendFacade (sync wrapper)
    ↓ calls
Scraper modules (actual work)
    ↓ sends via
progress_callback()
    ↓ updates
NiceGUI Frontend (real-time UI)
```

---

## 5. LOGGING IMPLEMENTATION

### Setup (runner/logging_setup.py)

```python
def setup_logging(
    name: str = "washdb-bot",
    log_level: str = None,
    log_file: str = None
) → logging.Logger

# Configuration:
# - Level: from LOG_LEVEL env var (default: INFO)
# - Console: formatted as "LEVEL - MESSAGE"
# - File: formatted as "TIMESTAMP - NAME - LEVEL - MESSAGE"
# - Rotation: 10 MB max, keeps 5 backups
# - Location: logs/{name}.log
```

### Logger Usage Pattern
```python
from runner.logging_setup import get_logger

logger = get_logger("module_name")
logger.info("Discovery started")
logger.warning("Rate limited, retrying...")
logger.error("Failed to scrape", exc_info=True)
```

### Log Files
```
logs/
├── main.log              # CLI runner
├── yp_crawl.log          # Discovery
├── site_scraper.log      # Website scraping
├── save_discoveries.log  # Database operations
├── update_details.log    # Detail enrichment
└── backend_facade.log    # Frontend API calls
```

### Log Rotation
- Max size: 10 MB
- Backups: 5 files kept
- Automatic rotation when limit reached
- Can use logrotate systemd service for external rotation

---

## 6. ANTI-BLOCKING STRATEGIES

### 6.1 Currently Implemented (Free)

#### Rate Limiting
```python
CRAWL_DELAY_SECONDS = 10  # Base delay between requests
# Actual delay: CRAWL_DELAY_SECONDS ± 20% jitter
# Example: 10s base → 8-12s actual delay
# State cooldown: 15-25s between states
```

#### Browser Fingerprint Randomization (Playwright)
```python
# Randomized per request:
- Viewport: 1920x1080, 1366x768, 1536x864, 1440x900
- User Agent: Chrome, Firefox, Safari
- Timezone: EST, CST, MST, PST
- Locale: en-US, en-GB, en-CA
- Device scale factor: 1, 1.5, 2

# Browser args:
--disable-blink-features=AutomationControlled  # Hide webdriver
--disable-dev-shm-usage                         # Reduce memory
--no-sandbox                                    # Sandbox mode
```

#### Human Behavior Simulation
```python
# Per page load:
- Random page wait: 1-3 seconds
- Random scrolling: 2-4 scroll actions
- Random mouse movements: 2-4 random positions
- Scroll delays: 50-200ms between moves
```

#### Request Headers
```python
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)...',
    'Accept': 'text/html,application/xhtml+xml,...',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}
# Accept-Language rotated: en-US,en-US,es
```

#### Retry Strategy
```python
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # Exponential: 2, 4, 8 seconds

Triggers:
- 429 (Too Many Requests) → backoff & retry
- 500+ (Server errors) → backoff & retry
- Timeout → backoff & retry
- Connection errors → backoff & retry
```

### 6.2 Advanced Options (Not Implemented, Documented)

See `ADVANCED_ANTI_BLOCKING.md` for:
- Residential proxy rotation ($75-500/month)
- Distributed scraping via VPS network ($20-50/month)
- CAPTCHA solving services (2Captcha, Anti-Captcha) ($2-3/1000)
- Scraping API services (ScraperAPI, Scrapingbee) ($29-249/month)

### 6.3 Environment Configuration
```python
# .env
DATABASE_URL=postgresql+psycopg://washbot:...@127.0.0.1:5432/washbot_db
LOG_LEVEL=INFO
YP_BASE=https://www.yellowpages.com/search
CRAWL_DELAY_SECONDS=10
MAX_CONCURRENT_SITE_SCRAPES=5
USE_PLAYWRIGHT=true
```

---

## 7. DATA FLOW DIAGRAM

```
┌─────────────────────────────────────────────────────────────────┐
│                         NiceGUI Frontend                         │
│  (Discover Page / Scrape Page / Single URL / Dashboard)         │
└────────────────────────────┬────────────────────────────────────┘
                             │ calls
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│                    BackendFacade (API)                           │
│  - discover(categories, states, pages_per_pair, callbacks)     │
│  - scrape_batch(limit, stale_days, callbacks)                  │
│  - scrape_one_preview(url)                                     │
└────┬──────────────────────────────────────────────────────┬────┘
     │ coordinates                                          │
     ↓                                                      ↓
┌──────────────────────────────────┐  ┌──────────────────────────────┐
│      YP Discovery Phase          │  │   Website Enrichment Phase   │
│                                  │  │                              │
│ yp_crawl.py                      │  │ update_details.py            │
│  ├─ crawl_all_states()           │  │  ├─ update_batch()           │
│  └─ crawl_category_location()    │  │  └─ update_company_details() │
│       ↓                          │  │       ↓                      │
│ yp_client.py                     │  │ site_scraper.py              │
│  ├─ fetch_yp_search_page()       │  │  ├─ scrape_website()         │
│  │   (requests or Playwright)    │  │  ├─ discover_internal_links()
│  └─ parse_yp_results()           │  │  └─ merge_results()          │
│       ↓                          │  │       ↓                      │
│ HTTP GET                         │  │ site_parse.py                │
│ https://yellowpages.com/search   │  │  ├─ parse_site_content()    │
│                                  │  │  └─ extract_json_ld()       │
│ Output: 50-1000 URLs/state-cat   │  │       ↓                      │
└──────────────────┬───────────────┘  │ HTTP GET (3+ pages)          │
                   │ saves to DB      │ Regex patterns for:          │
                   ↓                  │ - Phones: \d{3}-\d{3}-\d{4}  │
        ┌──────────────────────┐      │ - Emails: \w+@\w+.\w+       │
        │  Database            │      │ - Services/Area/Address     │
        │  (PostgreSQL)        │      └──────────────┬───────────────┘
        │                      │                     │ saves to DB
        │ save_discoveries.py  │                     ↓
        │  ├─ upsert_discovered()    ┌──────────────────────────────┐
        │  └─ canonicalize_url()     │  Database (updated fields)   │
        │  └─ domain_from_url()      │  - email, phone, services    │
        │                            │  - service_area, address     │
        └────────────────────────────┴──────────────────────────────┘
                                │
                                ↓
                    ┌─────────────────────┐
                    │   Company Records   │
                    │   (300K+ firms)     │
                    │                     │
                    │ Fields:             │
                    │ - id, name          │
                    │ - website (unique)  │
                    │ - domain            │
                    │ - phone, email      │
                    │ - services, address │
                    │ - ratings & reviews │
                    │ - source, dates     │
                    └─────────────────────┘
```

---

## 8. KEY EXECUTION FLOWS

### Flow 1: Command-Line Discovery
```bash
python runner/main.py --discover-only \
  --categories "pressure washing,window cleaning" \
  --states "TX,CA" \
  --pages-per-state 3
```

**Process**:
1. Parse arguments
2. Initialize logger
3. Call crawl_all_states() generator
4. For each batch: upsert_discovered() → database
5. Export CSV to data/new_urls_TIMESTAMP.csv
6. Print summary statistics

### Flow 2: NiceGUI Discovery
```
1. User configures in Discover page
2. Click "RUN" button
3. Calls backend.discover() in I/O thread
4. Progress updates flow back via callback
5. UI updates in real-time (logs, stats, progress bar)
6. Final summary on completion/cancellation
```

### Flow 3: Website Enrichment
```
1. Query database for stale/missing companies
2. For each company:
   a. Check if needs enrichment (missing email, stale, never updated)
   b. Scrape website (homepage + up to 3 pages)
   c. Parse extracted data
   d. Merge with existing record
   e. Update database (last_updated timestamp)
3. Track field updates (email: 25, phone: 30, etc.)
4. Return summary statistics
```

---

## 9. INTEGRATION CONSIDERATIONS FOR GOOGLE SCRAPER

### What to Reuse
1. **Database schema** - Company model is generic
2. **URL normalization** - canonicalize_url(), domain_from_url()
3. **Website enrichment** - site_scraper.py, site_parse.py work for any site
4. **Batch processing framework** - update_batch() pattern scales
5. **Logging infrastructure** - logging_setup.py
6. **GUI framework** - NiceGUI + BackendFacade architecture
7. **Anti-blocking strategies** - Rate limiting, Playwright, retries

### What to Create
1. **Google Business Scraper** (equivalent to yp_client.py)
   - Google Maps API integration
   - Google Search Business Profile scraping
   - Handling Google-specific HTML structures

2. **Google Crawl Orchestration** (equivalent to yp_crawl.py)
   - Location-based searches (coordinates/radius)
   - Category search on Google
   - Pagination handling

3. **Google-specific parsing**
   - Rating/review extraction from Google
   - Business hours parsing
   - Photo/image handling

### Integration Points
- Add google_source to Company.source field
- rating_google / reviews_google already in schema
- Create scrape_google/ directory parallel to scrape_yp/
- Extend BackendFacade with google_discover() method
- Add Google config to .env (API keys, etc.)

---

## 10. CONFIGURATION & DEPLOYMENT

### Environment Variables (.env)
```
DATABASE_URL=postgresql+psycopg://user:pass@host:5432/db
LOG_LEVEL=INFO
YP_BASE=https://www.yellowpages.com/search
CRAWL_DELAY_SECONDS=10
MAX_CONCURRENT_SITE_SCRAPES=5
USE_PLAYWRIGHT=true

# Optional proxy config
PROXY_SERVER=http://proxy.server:port
PROXY_USERNAME=user
PROXY_PASSWORD=pass
USE_PROXY=false
```

### System Service Setup
- `washdb-bot.service` - systemd service file
- `install_service.sh` - installs service
- `restart_service.sh` - restart command
- `washdb-bot-logrotate` - log rotation config
- `install_logrotate.sh` - installs rotation

### Database Setup
- `db/init_db.py` - creates tables and schema
- PostgreSQL 12+ required
- Connection via SQLAlchemy

---

## SUMMARY

The washdb-bot is a **two-phase scraper architecture**:

1. **Discovery Phase** (Yellow Pages)
   - Category + location search
   - Multi-page pagination
   - Basic extraction (name, phone, address, website)
   - Rate limiting + retry logic
   - Database upsert

2. **Enrichment Phase** (Website Scraping)
   - Visit discovered company websites
   - Extract detailed info (email, phone, services, area)
   - Intelligent multi-page discovery
   - Database updates

**For Google Business Scraper**: Create scrape_google/ with equivalent structure, extend BackendFacade, and leverage existing infrastructure for deployment, logging, GUI, and database.

