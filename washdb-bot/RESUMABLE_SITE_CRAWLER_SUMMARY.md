# Resumable Site Crawler - Implementation Summary

**Date**: 2025-11-18
**Purpose**: Make site scraper resumable with cursor-based state management

---

## Overview

Added resumable crawling capability to the site scraper, allowing it to save state after each page and resume from the last completed URL if interrupted. Keeps it simple with a small `site_crawl_state` table and bounded queue (max 50 URLs).

---

## Changes Made

### 1. Database Table: `site_crawl_state` ✅

**File**: `db/models.py` (lines 709-800)

**Model**: `SiteCrawlState`

**Fields**:
```python
class SiteCrawlState(Base):
    id: int                          # Primary key
    domain: str                      # Domain being crawled (e.g., 'example.com')
    phase: str                       # 'parsing_home', 'crawling_internal', 'done', 'failed'
    last_completed_url: str          # Last URL successfully parsed (cursor)
    pending_queue: JSONB             # JSON array of pending URLs (max 50)
    discovered_targets: JSONB        # {contact: [...], about: [...], services: [...]}
    pages_crawled: int               # Total pages crawled so far
    targets_found: int               # Total target pages found
    errors_count: int                # Number of errors encountered
    last_error: str                  # Last error message (for debugging)
    started_at: datetime             # When crawl started
    last_updated: datetime           # Last cursor save timestamp
    completed_at: datetime           # When crawl completed (done or failed)
```

**Phases**:
1. **`parsing_home`**: Currently parsing homepage
2. **`crawling_internal`**: Crawling internal pages (contact, about, services)
3. **`done`**: All target pages discovered and parsed
4. **`failed`**: Crawl failed (too many errors, site unreachable, etc.)

**Indexes**:
- `domain` (unique) - For fast lookup
- `phase` - For querying incomplete crawls
- `last_updated` - For finding stale crawls
- GIN indexes on JSONB fields - For efficient JSON queries

---

### 2. Migration Script ✅

**File**: `db/migrations/add_site_crawl_state_table.sql` (NEW)

**Purpose**: Create `site_crawl_state` table in PostgreSQL

**To Apply**:
```bash
PGPASSWORD='Washdb123' psql -U washbot -d washbot_db -h localhost \
    -f db/migrations/add_site_crawl_state_table.sql
```

**Features**:
- Creates table with all fields
- Adds comments for documentation
- Creates indexes for performance
- Includes example queries

---

### 3. Resumable Crawler Module ✅

**File**: `scrape_site/resumable_crawler.py` (NEW - ~290 lines)

**Key Functions**:

#### `get_or_create_crawl_state(session, domain, website_url)`
- Get existing crawl state or create new one
- Returns `SiteCrawlState` object

#### `save_cursor(session, state, last_url, pending_urls, discovered)`
- Save crawl cursor (idempotent)
- Truncates queue to MAX_QUEUE_SIZE (50 URLs)
- Updates `last_completed_url`, `pending_queue`, `discovered_targets`
- Commits to database

#### `crawl_site_resumable(session, domain, website_url)`
**Main crawl function**:
- Gets or creates crawl state
- Rebuilds queue from saved state
- Crawls pending URLs with cursor saving after each page
- Phase 1: Parse homepage, discover internal links
- Phase 2: Crawl discovered target pages (contact/about/services)
- Marks as `done` when queue is empty
- Marks as `failed` if too many errors (threshold: 5)

**Configuration**:
```python
MAX_QUEUE_SIZE = 50               # Max URLs in pending queue
MAX_PAGES_PER_DOMAIN = 20         # Max pages to crawl per domain
MAX_ERRORS_BEFORE_FAIL = 5        # Error threshold
```

**Usage**:
```python
from scrape_site.resumable_crawler import crawl_site_resumable
from db.save_discoveries import create_session

session = create_session()
result = crawl_site_resumable(session, 'example.com', 'https://example.com')

# Result:
{
    'domain': 'example.com',
    'phase': 'done',              # or 'crawling_internal', 'failed'
    'pages_crawled': 8,
    'targets_found': 3,
    'discovered_data': {...},     # Parsed data from pages
    'completed': True             # True if done/failed
}
```

#### `reset_crawl_state(session, domain)`
- Delete crawl state for a domain (allows re-crawl)
- Returns `True` if reset successfully

#### `get_crawl_status(session, domain)`
- Get crawl status for a domain
- Returns dict with status info or `None` if not found

---

### 4. GUI Resume Toggle ✅

**File**: `niceui/pages/database.py` (lines 262-315, 449-453)

**New Function**: `resume_site_crawl()`
- Resumes site crawl for selected company
- Runs in I/O-bound thread to avoid blocking UI
- Shows progress notification
- Handles errors gracefully

**UI Button**:
```python
ui.button(
    'Resume Site Crawl',
    icon='play_arrow',
    on_click=lambda: resume_site_crawl()
).props('outline size=sm color=positive').tooltip('Resume/start site crawl for selected domain')
```

**Location**: Database page → Row Actions toolbar

**Behavior**:
1. User selects a company from the table
2. Clicks "Resume Site Crawl" button
3. System checks for existing crawl state:
   - **If found**: Resumes from last completed URL
   - **If not found**: Starts new crawl from homepage
4. Crawls up to MAX_PAGES_PER_DOMAIN (20 pages)
5. Saves cursor after each page
6. Shows completion notification

**Notifications**:
- Start: `Resuming site crawl for example.com...`
- Success: `✓ Crawl done for example.com: 8 pages, 3 targets`
- Paused: `⏸ Crawl paused for example.com: 5 pages so far`
- Error: `Error resuming crawl: <message>`

---

## How It Works

### 1. First Run (New Crawl)

```
1. User clicks "Resume Site Crawl" for example.com
2. System creates new SiteCrawlState:
   - domain: 'example.com'
   - phase: 'parsing_home'
   - pending_queue: ['https://example.com']
   - pages_crawled: 0

3. Crawl homepage:
   - Fetch https://example.com
   - Parse content (email, phone, address, etc.)
   - Discover internal links (contact, about, services)
   - Add discovered links to pending_queue
   - Save cursor: last_completed_url = 'https://example.com'
   - Move to phase: 'crawling_internal'

4. Crawl discovered pages:
   - Fetch https://example.com/contact
   - Parse content, merge data
   - Save cursor: last_completed_url = 'https://example.com/contact'
   - Repeat for other pages

5. Complete:
   - Queue is empty
   - Mark phase: 'done'
   - Set completed_at timestamp
```

### 2. Resume After Interruption

```
1. System crashes after parsing homepage and 2 target pages

2. Database has saved state:
   - domain: 'example.com'
   - phase: 'crawling_internal'
   - last_completed_url: 'https://example.com/about'
   - pending_queue: ['https://example.com/services']
   - pages_crawled: 3

3. User clicks "Resume Site Crawl" again

4. System loads saved state:
   - Rebuilds queue from pending_queue
   - Skips already completed URLs
   - Continues from where it left off

5. Crawl remaining pages:
   - Fetch https://example.com/services
   - Parse content, merge data
   - Save cursor
   - Mark as 'done'
```

### 3. Idempotent Cursor Saving

**After each page**:
```python
# Update state
state.last_completed_url = current_url
state.pending_queue = {'urls': remaining_urls}
state.pages_crawled += 1

# Commit to database (idempotent)
session.commit()
```

**Benefits**:
- ✅ **Safe to call multiple times**: No duplicates or data loss
- ✅ **Atomic**: Commit ensures consistency
- ✅ **Resumable**: Can restart from any saved state

---

## Key Features

### ✅ Small and Simple
- Single table with ~10 fields
- Bounded queue (max 50 URLs)
- No heavy queue system (Redis, Celery, etc.)
- Simple phase tracking (4 states)

### ✅ Resumable
- Saves state after each page
- Can resume from any interruption (crash, shutdown, error)
- Rebuilds queue from saved state
- Skips already completed URLs

### ✅ Idempotent
- Safe to call crawl function multiple times
- Cursor saving is atomic (transaction commit)
- No duplicate pages crawled

### ✅ Bounded
- Queue limited to 50 URLs (prevents memory issues)
- Max 20 pages per domain (prevents infinite crawls)
- Max 5 errors before failure (prevents infinite retries)

### ✅ GUI Integrated
- One-click resume from database page
- Select any company and click "Resume Site Crawl"
- Shows progress notifications
- Works for both new and existing crawls

---

## Example Queries

### Find Incomplete Crawls
```sql
SELECT domain, phase, pages_crawled, last_updated
FROM site_crawl_state
WHERE phase NOT IN ('done', 'failed')
ORDER BY last_updated DESC;
```

### Get Crawl Status for Domain
```sql
SELECT * FROM site_crawl_state WHERE domain = 'example.com';
```

### Find Failed Crawls
```sql
SELECT domain, last_error, errors_count, completed_at
FROM site_crawl_state
WHERE phase = 'failed'
ORDER BY completed_at DESC;
```

### Count Crawls by Phase
```sql
SELECT phase, COUNT(*) as count
FROM site_crawl_state
GROUP BY phase;
```

---

## Files Changed

| File | Lines | Type | Purpose |
|------|-------|------|---------|
| `db/models.py` | +92 | Model | SiteCrawlState model definition |
| `db/migrations/add_site_crawl_state_table.sql` | +75 | Migration | Create site_crawl_state table |
| `scrape_site/resumable_crawler.py` | +290 (NEW) | Feature | Resumable crawl logic |
| `niceui/pages/database.py` | +60 | Feature | GUI resume button |

**Total**: ~517 lines added across 4 files

---

## Testing

### 1. Create Table
```bash
# Apply migration
PGPASSWORD='Washdb123' psql -U washbot -d washbot_db -h localhost \
    -f db/migrations/add_site_crawl_state_table.sql

# Verify table exists
PGPASSWORD='Washdb123' psql -U washbot -d washbot_db -h localhost \
    -c "\d site_crawl_state"
```

### 2. Test Crawl (Python Console)
```python
from scrape_site.resumable_crawler import crawl_site_resumable
from db.save_discoveries import create_session

session = create_session()

# Start crawl
result = crawl_site_resumable(session, 'example.com', 'https://example.com')
print(result)
# Output: {'domain': 'example.com', 'phase': 'done', 'pages_crawled': 8, ...}

# Check state
from scrape_site.resumable_crawler import get_crawl_status
status = get_crawl_status(session, 'example.com')
print(status)
# Output: {'domain': 'example.com', 'phase': 'done', 'can_resume': False, ...}
```

### 3. Test Resume (Simulate Interruption)
```python
# Interrupt crawl (Ctrl+C during crawl)

# Resume
result = crawl_site_resumable(session, 'example.com', 'https://example.com')
# Should continue from last saved state
```

### 4. Test GUI
1. Start NiceGUI: `python -m niceui.main`
2. Open http://127.0.0.1:8080
3. Navigate to Database page
4. Select a company
5. Click "Resume Site Crawl" button
6. Check notifications for progress

---

## Configuration

**Environment Variables** (`.env`):
```bash
CRAWL_DELAY_SECONDS=2.0           # Delay between requests
REQUEST_TIMEOUT=30                # HTTP timeout (seconds)
```

**Constants** (`resumable_crawler.py`):
```python
MAX_QUEUE_SIZE = 50               # Max URLs in queue
MAX_PAGES_PER_DOMAIN = 20         # Max pages per domain
MAX_ERRORS_BEFORE_FAIL = 5        # Error threshold
```

**Tuning**:
- Increase `MAX_PAGES_PER_DOMAIN` for deeper crawls
- Increase `MAX_QUEUE_SIZE` if discovering many links
- Decrease `CRAWL_DELAY_SECONDS` for faster (but less polite) crawling
- Increase `MAX_ERRORS_BEFORE_FAIL` for more retries

---

## Benefits

### For Operators
- ✅ **No data loss**: State saved after every page
- ✅ **Resume anytime**: Can restart crawler without losing progress
- ✅ **GUI control**: One-click resume from dashboard
- ✅ **Transparent**: Phase and progress visible in database

### For Developers
- ✅ **Simple**: No complex queue system
- ✅ **Maintainable**: Single table, clear states
- ✅ **Testable**: Easy to test resume logic
- ✅ **Documented**: Comprehensive docstrings

### For System
- ✅ **Bounded**: Queue and page limits prevent runaway crawls
- ✅ **Idempotent**: Safe to retry
- ✅ **Efficient**: Indexed lookups, atomic commits
- ✅ **Observable**: All state visible in database

---

## Future Enhancements (Optional)

1. **Batch Resume**: Resume multiple domains at once
2. **Scheduled Resume**: Auto-resume failed/incomplete crawls
3. **Priority Queue**: Crawl contact pages before about pages
4. **Parallel Crawling**: Multiple domains in parallel
5. **Health Checks**: Detect and mark unhealthy domains
6. **Crawl Budget**: Per-domain page limits from config

---

## Summary

Implemented resumable site crawler with:
- ✅ **Database table**: `site_crawl_state` with cursor and queue
- ✅ **Cursor saving**: After each page, idempotent
- ✅ **Resume logic**: Rebuilds queue from saved state
- ✅ **GUI toggle**: "Resume Site Crawl" button on database page
- ✅ **Bounded queue**: Max 50 URLs, max 20 pages per domain
- ✅ **Simple**: No heavy queue system needed

**Status**: ✅ **Ready to use**
**Migration**: Required (apply SQL migration)
**Behavior**: Non-breaking (only adds new feature)
