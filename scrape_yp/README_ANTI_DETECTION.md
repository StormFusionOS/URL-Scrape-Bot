# Yellow Pages Anti-Detection Enhancements

## Overview

Enhanced Yellow Pages scraper with **dual anti-detection strategies** to bypass 403 Forbidden errors and bot protection without using proxies.

## Key Features

### 1. HTTP Client with Exponential Backoff (`yp_client.py:111-117`)
- **403 Forbidden Handling**: Aggressive 10×2^n backoff (10s, 20s, 40s)
- **429 Rate Limiting**: Standard exponential backoff
- **5xx Server Errors**: Retry with backoff
- **Automatic Fallback**: Falls back from browser to HTTP when Playwright fails

### 2. Persistent Browser with Stealth Mode (`yp_browser.py`)
- **playwright-stealth Integration**: Uses `stealth_sync()` for maximum anti-detection
- **Persistent Browser Instance**: Reuses browser across requests for efficiency
- **Consecutive 403 Tracking**: Adaptive backoff based on error patterns
- **Human Behavior Simulation**:
  - Smooth scrolling patterns
  - Random mouse movements
  - Realistic hover interactions
  - Variable delays (3-7s after page load)

### 3. Advanced Fingerprinting Evasion
- Randomized viewports (5 common resolutions)
- Rotating user agents (Chrome, Firefox, Safari)
- Geographic diversity (6 US timezone/location pairs)
- WebGL renderer spoofing
- Canvas fingerprint randomization
- Plugin enumeration mimicry

## Backoff Strategies

### HTTP Client (yp_client.py)
```
403 Errors:  10s → 20s → 40s  (aggressive)
429 Errors:   2s →  4s →  8s  (standard)
5xx Errors:   2s →  4s →  8s  (standard)
```

### Browser Client (yp_browser.py)
```
Per-Request:  5s → 10s → 20s → 40s → 80s
Consecutive:  10s × 2^n (resets on success)
Page Delays:  3-7s random (human-like)
```

## Configuration

```bash
# .env
USE_PLAYWRIGHT=true              # Enable browser mode (default)
CRAWL_DELAY_SECONDS=2            # Base delay between requests
```

## Usage

### Automatic (Recommended)
The scraper automatically uses the best method:

```python
from scrape_yp import crawl_category_location

results = crawl_category_location(
    category="pressure washing",
    location="TX",
    max_pages=50
)
```

### Manual Browser Control
```python
from scrape_yp.yp_browser import get_yp_browser, close_global_yp_browser

# Get persistent browser instance
browser = get_yp_browser()

# Fetch pages
html = browser.fetch_page(url, min_delay=3, max_delay=7)

# Close when done
close_global_yp_browser()
```

## Architecture

```
scrape_yp/
├── yp_client.py          # HTTP client + Playwright orchestration
├── yp_browser.py         # Persistent browser with stealth mode (NEW)
├── yp_crawl.py           # Multi-page/multi-state orchestration
└── README_ANTI_DETECTION.md  # This file
```

## Why This Works

1. **Persistent Browser**: Reusing the same browser instance looks more like a real user session
2. **playwright-stealth**: Industry-standard library for bypassing bot detection
3. **Human Behavior**: Random scrolling/mouse movements make traffic indistinguishable from real users
4. **Adaptive Backoff**: Automatically adjusts delays when hitting 403 errors
5. **Fingerprint Randomization**: Each session has unique but realistic browser characteristics

## Comparison to Proxies

| Feature | This Implementation | Residential Proxies |
|---------|-------------------|---------------------|
| Cost | Free | $50-200/month |
| Setup | Zero config | API keys, rotation logic |
| Reliability | High (reuses session) | Variable (proxy quality) |
| Speed | Fast (persistent browser) | Slower (connection overhead) |
| Detection Risk | Very Low | Low-Medium |

## Troubleshooting

### Still Getting 403 Errors?
1. **Check Consecutive 403 Counter**: Browser tracks this and increases backoff automatically
2. **Increase Base Delays**: Set `min_delay=5, max_delay=10` for more conservative crawling
3. **Reduce Request Rate**: Lower `max_pages` parameter or add cooldown periods

### Browser Not Starting?
```bash
# Install Playwright browsers
playwright install

# Check playwright-stealth is installed
pip install playwright-stealth
```

### Want to Switch Back to HTTP?
```bash
# .env
USE_PLAYWRIGHT=false
```

## Performance Tips

1. **Batch Processing**: Process multiple category/location pairs with cooldown periods
2. **Time of Day**: Scrape during off-peak hours (2AM-6AM ET) for lower detection risk
3. **Rate Limiting**: Keep `CRAWL_DELAY_SECONDS=2` minimum to avoid rate limiting

## Future Enhancements

- [ ] Browser pool (multiple instances for parallel scraping)
- [ ] Cookie persistence across sessions
- [ ] CAPTCHA detection and alerting
- [ ] Automatic backoff tuning based on success rate

## Credits

Built using:
- [Playwright](https://playwright.dev/) - Browser automation
- [playwright-stealth](https://github.com/AtuboDad/playwright_stealth) - Anti-detection
- Exponential backoff strategy inspired by AWS SDK retry logic
