# Yellow Pages Blocking Issue

**Status:** Yellow Pages is blocking scraper requests with 403 Forbidden errors

## Problem

When running discovery, all requests to Yellow Pages return:
```
403 Client Error: Forbidden for url: https://www.yellowpages.com/search?...
```

This results in 0 results being found and saved.

## Root Cause

Yellow Pages has implemented anti-bot protection that detects and blocks automated scraping attempts.

## Current Configuration

The scraper currently uses:
- **User-Agent:** Chrome 120 (desktop browser)
- **Delay:** 2 seconds between requests
- **Headers:** Standard browser headers (Accept, Accept-Language, etc.)
- **Retries:** 3 attempts with exponential backoff

## Why It's Being Blocked

Despite proper headers and delays, Yellow Pages likely detects bots through:
1. **Request patterns** - Sequential, predictable requests
2. **Session behavior** - No cookies, no session persistence
3. **IP reputation** - Single IP making many requests
4. **Missing browser fingerprints** - No JavaScript execution
5. **Rate limiting** - Too many requests from same IP

## Solutions (In Order of Difficulty)

### Solution 1: Increase Delays (Easy)
Significantly increase crawl delay to appear more human-like.

**Edit `.env` file:**
```bash
CRAWL_DELAY_SECONDS=10  # Increase from 2 to 10 seconds
```

**Pros:** Simple, no code changes
**Cons:** Much slower scraping, may not fully solve the issue

### Solution 2: Use Scrapy with AutoThrottle (Medium)
Scrapy has built-in anti-blocking features and intelligent throttling.

**Pros:** Better rate limiting, automatic retries, more sophisticated
**Cons:** Requires refactoring scraper code

### Solution 3: Add Session Persistence (Medium)
Use `requests.Session()` to maintain cookies and session state.

**Implementation:** Modify `yp_client.py` to use sessions:
```python
import requests

# Create persistent session
session = requests.Session()
session.headers.update(HEADERS)

# Use session instead of requests
response = session.get(url, timeout=30)
```

**Pros:** More realistic browser behavior
**Cons:** Requires code changes

### Solution 4: Rotate User Agents (Medium)
Randomize user agent strings to appear as different browsers.

**Implementation:**
```python
import random

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) Firefox/121.0",
    # ... more user agents
]

# Pick random user agent per request
headers = HEADERS.copy()
headers["User-Agent"] = random.choice(USER_AGENTS)
```

**Pros:** Harder to detect as single bot
**Cons:** Still may not fully solve the issue

### Solution 5: Use Proxies (Hard)
Route requests through rotating proxies to avoid IP-based blocking.

**Options:**
- Free proxy lists (unreliable)
- Paid proxy services (Bright Data, Oxylabs, etc.)
- Residential proxies (most effective)

**Pros:** Most effective anti-blocking solution
**Cons:** Expensive, requires infrastructure

### Solution 6: Use Headless Browser (Hard)
Use Selenium or Playwright to scrape with a real browser.

**Pros:** Full JavaScript support, realistic browser fingerprint
**Cons:** Much slower, resource-intensive

### Solution 7: Use Third-Party APIs (Expensive)
Use commercial scraping APIs that handle anti-blocking.

**Options:**
- ScraperAPI (https://www.scraperapi.com/)
- Bright Data (https://brightdata.com/)
- Apify (https://apify.com/)

**Pros:** No blocking issues, handles everything
**Cons:** Expensive ($49-$200+/month)

## Recommended Short-Term Solution

**Increase delays significantly:**

1. Edit `.env` file:
```bash
CRAWL_DELAY_SECONDS=15
```

2. Reduce scope per discovery run:
   - Use 1-2 categories
   - Use 1-2 states
   - Use 1 page per pair

3. Run discoveries spread out over time (not all at once)

4. Monitor logs to see if 403 errors decrease

## Recommended Long-Term Solution

If you need to scrape Yellow Pages regularly at scale:

1. **Invest in residential proxies** ($50-200/month)
   - Services like Bright Data, Smartproxy, etc.
   - Rotate IPs per request

2. **Use Scrapy with rotating proxies + sessions**
   - Proper middleware for proxy rotation
   - Session persistence
   - Intelligent throttling

3. **Consider commercial APIs** if budget allows
   - Pay per request
   - No maintenance required

## Alternative Data Sources

Consider these alternatives to Yellow Pages:

1. **Google Places API** (official, reliable, $200 free credit/month)
2. **Yelp Fusion API** (official, free tier available)
3. **Outscraper** (third-party API for Google Maps/Places)
4. **Data vendors** (buy pre-scraped business databases)

## Testing the Current Setup

To test if increased delays help:

```bash
cd /home/rivercityscrape/URL-Scrape-Bot/washdb-bot

# Edit .env
nano .env  # Change CRAWL_DELAY_SECONDS=15

# Restart service
sudo systemctl restart washdb-bot

# Try a small discovery:
# Go to GUI -> Discovery
# Select: 1 category, 1 state, 1 page
# Monitor logs:
sudo journalctl -u washdb-bot -f
```

## Current Workaround

Until anti-blocking is improved:

1. **Manual data entry** - Use Single URL scraping for specific businesses
2. **Reduce frequency** - Run discovery once per day/week
3. **Use other sources** - Try Google Places API or buy data
4. **Increase delays** - Set to 15-30 seconds between requests

## Files to Modify for Fixes

- `scrape_yp/yp_client.py` - HTTP client and headers
- `.env` - CRAWL_DELAY_SECONDS configuration
- `requirements.txt` - Add proxy/session libraries if needed

---

**Last Updated:** 2025-11-10
**Issue Status:** Identified - Waiting for solution implementation
