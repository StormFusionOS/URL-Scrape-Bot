# Safety Limits & Kill Switches

This guide explains how to use the safety mechanisms provided by `runner/safety.py` to prevent runaway scraping behavior.

## Overview

The safety module provides two main classes:

1. **SafetyLimits** - Enforces maximum pages and failure limits
2. **RateLimiter** - Adaptive rate limiting based on success/failure

Both are designed to be drop-in additions to existing scrapers with minimal code changes.

## SafetyLimits

### Purpose

Prevents runaway behavior by enforcing:
- Maximum pages per run
- Maximum consecutive failures
- Manual stop capability

### Configuration (via .env)

```bash
# Maximum pages to process (None = unlimited)
DEV_MAX_PAGES=50

# Maximum consecutive failures before abort
DEV_MAX_FAILURES=5

# Enable kill switch
DEV_ENABLE_KILL_SWITCH=true
```

### Basic Usage

```python
from runner.safety import SafetyLimits

# Create safety limits (reads from environment)
safety = SafetyLimits()

# In your scraping loop
for page in pages:
    # Check if should continue
    if not safety.check_should_continue():
        logger.warning("Safety limit reached, stopping")
        break

    try:
        # Scrape the page
        results = scrape_page(page)

        # Record success
        safety.record_success()
        safety.record_page_processed()

    except Exception as e:
        # Record failure
        safety.record_failure(str(e))
        safety.record_page_processed()

# Log summary at end
safety.log_summary()
```

### Advanced Usage

```python
# Override environment settings
safety = SafetyLimits(
    max_pages=100,           # Override DEV_MAX_PAGES
    max_failures=10,         # Override DEV_MAX_FAILURES
    enable_kill_switch=True  # Override DEV_ENABLE_KILL_SWITCH
)

# Manual stop
def signal_handler(sig, frame):
    safety.manual_stop("Received SIGINT")

# Get statistics
summary = safety.get_summary()
print(f"Processed {summary['pages_processed']} pages")
print(f"Successes: {summary['total_successes']}")
print(f"Failures: {summary['total_failures']}")
```

### Integration Example: YP Scraper

```python
# In scrape_yp/yp_crawl_city_first.py

from runner.safety import create_safety_limits_from_env

def crawl_targets(targets):
    # Initialize safety limits
    safety = create_safety_limits_from_env()

    for target in targets:
        # Check safety limits
        if not safety.check_should_continue():
            logger.warning("Safety limit reached")
            break

        try:
            # Existing scraping logic
            results = scrape_target(target)

            # Record success
            safety.record_success()

        except Exception as e:
            logger.error(f"Failed to scrape {target}: {e}")
            safety.record_failure(str(e))

        finally:
            # Always record page processed
            safety.record_page_processed()

    # Log final summary
    safety.log_summary()
```

## RateLimiter

### Purpose

Provides adaptive rate limiting that:
- Increases delays when failures occur (backs off)
- Decreases delays when operations succeed (recovers)
- Prevents overwhelming target servers

### Configuration (via .env)

```bash
# Minimum delay between requests
MIN_DELAY_SECONDS=2.0

# Maximum delay between requests
MAX_DELAY_SECONDS=30.0
```

### Basic Usage

```python
import time
from runner.safety import RateLimiter

# Create rate limiter (reads from environment)
limiter = RateLimiter()

# In your scraping loop
for item in items:
    try:
        # Wait before request
        time.sleep(limiter.get_delay())

        # Make request
        result = fetch_data(item)

        # Record success (may decrease delay)
        limiter.record_success()

    except Exception as e:
        # Record failure (will increase delay)
        limiter.record_failure()
        logger.warning(f"Request failed, backing off: {e}")
```

### Advanced Usage

```python
# Custom configuration
limiter = RateLimiter(
    base_delay=1.0,       # Start at 1 second
    max_delay=60.0,       # Cap at 1 minute
    backoff_factor=2.0,   # Double delay on failure
    recovery_factor=0.8   # Decrease by 20% on success
)

# Get current delay
current_delay = limiter.get_delay()
logger.debug(f"Current rate limit: {current_delay}s")

# Reset to base delay
limiter.reset()
```

### Integration Example: Google Scraper

```python
# In scrape_google/google_crawl_city_first.py

from runner.safety import create_rate_limiter_from_env
import time

def scrape_with_rate_limiting(targets):
    limiter = create_rate_limiter_from_env()

    for target in targets:
        # Apply rate limit
        delay = limiter.get_delay()
        logger.debug(f"Waiting {delay:.1f}s before next request")
        time.sleep(delay)

        try:
            # Scrape target
            results = scrape_target(target)

            # Success - may reduce delay
            limiter.record_success()

        except RateLimitError:
            # Rate limited - increase delay
            limiter.record_failure()
            logger.warning("Rate limited, backing off")

        except Exception as e:
            # Other error - also increase delay
            limiter.record_failure()
            logger.error(f"Error: {e}")
```

## Combined Usage

For maximum safety, use both SafetyLimits and RateLimiter together:

```python
from runner.safety import create_safety_limits_from_env, create_rate_limiter_from_env
import time

def safe_scrape(targets):
    # Initialize both safety mechanisms
    safety = create_safety_limits_from_env()
    limiter = create_rate_limiter_from_env()

    for target in targets:
        # Check safety limits first
        if not safety.check_should_continue():
            logger.warning("Safety limit reached, stopping")
            break

        # Apply rate limiting
        time.sleep(limiter.get_delay())

        try:
            # Scrape target
            results = scrape_target(target)

            # Record success in both
            safety.record_success()
            limiter.record_success()

        except Exception as e:
            # Record failure in both
            safety.record_failure(str(e))
            limiter.record_failure()

        finally:
            # Always record page processed
            safety.record_page_processed()

    # Log summary
    safety.log_summary()
```

## Best Practices

### 1. Always Use in Development

Enable safety limits in `.env.dev`:
```bash
DEV_MAX_PAGES=50
DEV_MAX_FAILURES=5
DEV_ENABLE_KILL_SWITCH=true
```

### 2. Relax in Production

Use higher limits in `.env` (production):
```bash
DEV_MAX_PAGES=  # Empty = unlimited
DEV_MAX_FAILURES=20
DEV_ENABLE_KILL_SWITCH=true  # Always keep enabled
```

### 3. Log Progress

The safety module logs progress every 10 pages:
```
INFO - Progress: 10 pages processed (8 successes, 2 failures)
INFO - Progress: 20 pages processed (17 successes, 3 failures)
```

### 4. Handle Graceful Shutdown

```python
import signal

def signal_handler(sig, frame):
    safety.manual_stop("Received shutdown signal")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
```

### 5. Test Safety Limits

Test with small limits first:
```bash
DEV_MAX_PAGES=5 python cli_crawl_yp.py --states RI
```

Should stop after 5 pages with message:
```
WARNING - Reached maximum pages limit: 5
```

## Monitoring

### Check if Scraper Was Stopped

```python
summary = safety.get_summary()

if summary['stopped']:
    logger.error(f"Scraper stopped: {summary['stop_reason']}")
    # Send alert, log to monitoring system, etc.
```

### Integration with job_execution_logs

```python
# After scraping completes
summary = safety.get_summary()

# Log to database
log_job_execution(
    status='stopped' if summary['stopped'] else 'completed',
    items_found=summary['total_successes'],
    errors_count=summary['total_failures'],
    notes=summary.get('stop_reason')
)
```

## Troubleshooting

### Safety limits not working

**Check environment variables:**
```bash
echo $DEV_MAX_PAGES
echo $DEV_MAX_FAILURES
echo $DEV_ENABLE_KILL_SWITCH
```

**Check .env file is loaded:**
```python
import os
from dotenv import load_dotenv

load_dotenv()  # Make sure this is called
print(os.getenv('DEV_MAX_PAGES'))
```

### Rate limiter stuck at max delay

**Reset rate limiter:**
```python
limiter.reset()  # Back to base delay
```

**Or check for persistent failures:**
- Are you hitting rate limits?
- Is the target site blocking you?
- Check logs for error patterns

### False positives (stops too early)

**Increase limits:**
```bash
# In .env.dev
DEV_MAX_PAGES=100        # From 50
DEV_MAX_FAILURES=10      # From 5
```

**Or disable temporarily:**
```bash
DEV_ENABLE_KILL_SWITCH=false
```

## Examples

### Real Implementation: YP Scraper

The Yellow Pages scraper (`cli_crawl_yp.py`) uses safety limits:

```python
# Import safety modules
from runner.safety import create_safety_limits_from_env, create_rate_limiter_from_env

# Initialize at start of scrape
safety = create_safety_limits_from_env()
limiter = create_rate_limiter_from_env()

# In main processing loop
for batch in crawl_city_targets(...):
    # Check safety limits before processing
    if not safety.check_should_continue():
        logger.warning("Safety limit reached, stopping crawler")
        break

    # Apply rate limiting
    delay = limiter.get_delay()
    if delay > 0:
        time.sleep(delay)

    # Process target
    target = batch['target']
    results = batch['results']

    # Record page processed
    safety.record_page_processed()

    # Record success/failure
    if results:
        safety.record_success()
        limiter.record_success()
    else:
        safety.record_failure("No results found")
        limiter.record_failure()

# Log summary at end
safety.log_summary()
```

### Real Implementation: Google Scraper

The Google Maps scraper (`cli_crawl_google_city_first.py`) uses async/await:

```python
# Import safety modules
from runner.safety import create_safety_limits_from_env, create_rate_limiter_from_env

# Initialize safety limits
safety = create_safety_limits_from_env()
limiter = create_rate_limiter_from_env()

# In async processing loop
async for batch in crawl_city_targets(...):
    # Check safety limits
    if not safety.check_should_continue():
        logger.warning("Safety limit reached, stopping crawler")
        break

    # Apply rate limiting (async)
    delay = limiter.get_delay()
    if delay > 0:
        await asyncio.sleep(delay)

    # Process and record
    stats = batch['stats']
    safety.record_page_processed()

    if stats['total_found'] > 0:
        safety.record_success()
        limiter.record_success()
    else:
        safety.record_failure("No results found")
        limiter.record_failure()

# Log summary
safety.log_summary()
```

### Test Cases

See additional examples in:
- `tests/integration/test_scraper_safety.py` - Unit test cases
- `cli_crawl_yp.py:cli_crawl_yp.py:177-268` - Full YP integration
- `cli_crawl_google_city_first.py:150-238` - Full Google integration

## Related Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
- [LOGS.md](LOGS.md) - Troubleshooting guide
- [CONTRIBUTING.md](../CONTRIBUTING.md) - Development guidelines
