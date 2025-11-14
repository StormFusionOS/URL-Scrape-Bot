# HomeAdvisor Two-Phase Discovery Workflow

## Overview

The HomeAdvisor discovery system has been updated to use a **two-phase workflow** that separates business discovery from URL finding. This approach is faster, more efficient, and uses free search methods.

## Why Two Phases?

**Old Approach (Slow):**
- Visit each HomeAdvisor profile page individually
- Extract external website from profile
- Required external website to save business
- Many profiles don't have external websites

**New Approach (Fast):**
- **Phase 1**: Extract business data from list pages only (no profile visits)
- **Phase 2**: Search DuckDuckGo to find real external websites

## Implementation Details

### Phase 1: Business Discovery

**File**: `scrape_ha/ha_crawl.py`

**What it does:**
- Scrapes HomeAdvisor list pages for category/state combinations
- Extracts from list page cards:
  - Business name
  - Address
  - Phone number
  - HomeAdvisor rating and review count
  - HomeAdvisor profile URL
- Uses HomeAdvisor profile URL as **temporary placeholder** website
- Saves to database with `domain=homeadvisor.com`

**Usage:**
```bash
# Via CLI
python cli_crawl_ha.py --categories "power washing" --states "RI" --pages 3

# Via GUI
# Navigate to Discover > HomeAdvisor > Phase 1
# Select categories and states
# Click "START PHASE 1"
```

**Categories (hardcoded):**
- power washing
- window cleaning services
- deck staining or painting
- fence painting or staining

### Phase 2: URL Finding

**File**: `scrape_ha/url_finder.py`

**What it does:**
- Queries database for companies with `domain=homeadvisor.com`
- For each company:
  - Builds search query: `[Business Name] [City] [State]`
  - Searches DuckDuckGo using Playwright
  - Scores results based on heuristics:
    - Business name keywords in domain
    - City/state in domain
    - Blacklist aggregator sites (yelp, yellowpages, etc.)
  - Selects best match
  - Updates database with real external website
  - Random delays (8-15s) between searches

**Usage:**
```bash
# Via CLI (process first 10 companies)
python cli_find_urls.py --limit 10

# Process all companies
python cli_find_urls.py

# Via GUI
# Navigate to Discover > HomeAdvisor > Phase 2
# Set max companies to process
# Click "START PHASE 2"
```

**Heuristics for URL Matching:**
- Business name keywords present in domain: +0.3 per keyword
- Multiple name words in domain: +0.4 bonus
- City in domain: +0.1
- State in domain: +0.1
- .com domain: +0.1
- Blacklisted aggregator sites: score = 0

**Blacklisted domains:**
- yellowpages.com
- yelp.com
- homeadvisor.com
- thumbtack.com
- angieslist.com
- facebook.com
- linkedin.com
- twitter.com
- instagram.com
- bbb.org
- google.com
- mapquest.com

## Database Schema

**Critical bug fixed**: The database requires `website` and `domain` to be NOT NULL. We now use HomeAdvisor profile URLs as temporary placeholders:

```python
# Phase 1 saves:
{
    "name": "ABC Pressure Washing",
    "website": "https://www.homeadvisor.com/rated.ABCPressureWashing.12345.html",  # Temporary
    "domain": "homeadvisor.com",
    "phone": "555-123-4567",
    "address": "123 Main St, Austin, TX 78701",
    "rating_ha": 4.5,
    "reviews_ha": 42,
    "source": "HA"
}

# Phase 2 updates:
{
    "website": "https://abcpressurewashing.com",  # Real external website
    "domain": "abcpressurewashing.com"
}
```

## GUI Changes

**File**: `niceui/pages/discover.py` (lines 1749-2004)

**New UI Structure:**
1. **Configuration Section**
   - Category checkboxes (4 hardcoded categories)
   - State checkboxes (all 50 US states)
   - Pages per state setting (default: 3)

2. **Phase 1: Discover Businesses**
   - Stats display
   - Progress bar
   - "START PHASE 1" button
   - Live log viewer (logs/ha_crawl.log)

3. **Phase 2: Find External URLs**
   - Max companies to process setting (default: 10)
   - Stats display
   - Progress bar
   - "START PHASE 2" button
   - Live log viewer (logs/url_finder.log)

## Workflow Example

```bash
# 1. Run Phase 1 (fast: ~20 seconds per category/state pair)
python cli_crawl_ha.py --categories "power washing" --states "RI,MA,CT" --pages 3

# Expected output: ~50-200 businesses saved with homeadvisor.com domain

# 2. Check database
PGPASSWORD="Washdb123" psql -h localhost -U scraper_user -d scraper \
  -c "SELECT COUNT(*) FROM companies WHERE domain = 'homeadvisor.com';"

# 3. Run Phase 2 on first 10 companies (slow: ~8-15 seconds per company)
python cli_find_urls.py --limit 10

# Expected output: 5-8 real external websites found

# 4. Check updated results
PGPASSWORD="Washdb123" psql -h localhost -U scraper_user -d scraper \
  -c "SELECT name, domain, website FROM companies WHERE source = 'HA' AND domain != 'homeadvisor.com' LIMIT 10;"
```

## Files Modified

1. **db/save_discoveries.py** (lines 226-232, 262-263)
   - Added `rating_ha` and `reviews_ha` handling in UPDATE and INSERT blocks

2. **scrape_ha/ha_crawl.py** (lines 11-13, 33-99)
   - Removed profile page fetching
   - Extract only from list pages
   - Use HomeAdvisor profile URL as temporary website

3. **scrape_ha/url_finder.py** (NEW FILE)
   - DuckDuckGo search with Playwright
   - URL scoring heuristics
   - Database update logic
   - Batch processing with random delays

4. **cli_find_urls.py** (NEW FILE)
   - CLI wrapper for URL finder
   - Argument parsing for --limit

5. **niceui/pages/discover.py** (lines 1749-2004)
   - Updated info banner
   - Separated Phase 1 and Phase 2 controls
   - Two separate log viewers
   - Two separate progress tracking systems

## Performance

**Phase 1 (Discovery):**
- Speed: ~20 seconds per category/state pair
- Example: 4 categories × 3 states × 3 pages = ~4 minutes
- Expected yield: 50-200 businesses

**Phase 2 (URL Finding):**
- Speed: ~8-15 seconds per company
- Example: 100 companies = 13-25 minutes
- Expected success rate: 50-80%
- Free (no API costs)

## Testing

```bash
# Test Phase 1 (single state, single category)
python cli_crawl_ha.py --categories "power washing" --states "RI" --pages 1

# Test Phase 2 (small batch)
python cli_find_urls.py --limit 5

# Check logs
tail -f logs/ha_crawl.log
tail -f logs/url_finder.log
```

## Future Improvements

1. **Parallel URL Finding**: Process multiple companies concurrently
2. **Better Scoring**: Use machine learning for URL matching
3. **Alternative Search Engines**: Try Bing if DuckDuckGo fails
4. **Caching**: Cache search results to avoid re-searching
5. **Manual Review**: Flag low-confidence matches for human review

## Notes

- URL finder includes 8-15 second delays to avoid rate limiting
- DuckDuckGo is free and doesn't require API keys
- HomeAdvisor profile URLs serve as permanent fallback if no external website found
- All businesses are saved even if Phase 2 fails (they keep homeadvisor.com domain)
