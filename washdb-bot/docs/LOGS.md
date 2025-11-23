# Log Reference Guide

This guide helps you find and understand logs when debugging the URL Scrape Bot.

## Log File Locations

All logs are stored in the `logs/` directory at the project root with rotating file handlers (10MB max, 5 backups).

### Main Scraper Logs

| Log File | Purpose | When to Check |
|----------|---------|---------------|
| `yp_crawl_city_first.log` | Yellow Pages city-first crawler | YP discovery issues, parsing errors, rate limiting |
| `google_crawl.log` | Google Maps crawler | Google scraping issues, CAPTCHA detection, location parsing |
| `site_scraper.log` | Website enrichment scraper | Site crawling errors, content extraction issues |
| `backend_facade.log` | NiceGUI dashboard backend | Dashboard errors, job orchestration issues |
| `main.log` | Legacy CLI runner | Issues with runner/main.py (deprecated) |

### Special Purpose Logs

| Directory/File | Purpose | Contents |
|----------------|---------|----------|
| `yp_wal/` | Write-ahead logging for crash recovery | Pre-write operations for YP scraper |
| `screenshots/` | Debug screenshots from Playwright | Visual snapshots when errors occur |
| `bing_debug/` | Bing scraper debugging | Bing-specific debug output |

## Log Format

### Standard Log Format

```
2025-11-23 14:32:15 - scrape_yp.yp_crawl_city_first - INFO - Starting discovery for Peoria, IL
```

Format: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`

### Log Levels

- **DEBUG**: Detailed diagnostic information (verbose)
- **INFO**: General operational messages (default)
- **WARNING**: Something unexpected happened, but the system continues
- **ERROR**: An error occurred, but the operation may continue
- **CRITICAL**: A severe error that may cause the system to stop

## Common Error Patterns & Solutions

### 1. Database Connection Errors

**Log Pattern**:
```
ERROR - Could not connect to database
psycopg.OperationalError: connection refused
```

**Possible Causes**:
- PostgreSQL is not running
- Incorrect DATABASE_URL in `.env`
- Wrong credentials

**Solutions**:
```bash
# Check if PostgreSQL is running
sudo systemctl status postgresql

# Test connection manually
psql -U washbot -d washbot_db

# Verify .env DATABASE_URL matches your database
cat .env | grep DATABASE_URL
```

### 2. Rate Limiting / Blocking

**Log Pattern**:
```
WARNING - Rate limited by yellowpages.com, retrying with longer delay...
WARNING - Received 429 status code
ERROR - Too many requests, backing off
```

**Possible Causes**:
- Scraping too fast
- IP address detected as bot
- Need to use proxies

**Solutions**:
1. Increase `CRAWL_DELAY_SECONDS` in `.env` (try 15-20)
2. Reduce `WORKER_COUNT` (try 2 for development)
3. Enable `ADAPTIVE_RATE_LIMITING=true`
4. Use proxies (`PROXY_ROTATION_ENABLED=true`)

**Check delays**:
```bash
grep -E "CRAWL_DELAY|WORKER_COUNT|MIN_DELAY|MAX_DELAY" .env
```

### 3. CAPTCHA Detection

**Log Pattern**:
```
WARNING - CAPTCHA detected on page
ERROR - Cannot proceed due to CAPTCHA challenge
```

**Possible Causes**:
- Anti-bot measures triggered
- Too many requests from same IP
- Stealth features not enabled

**Solutions**:
1. Enable stealth: `ANTI_DETECTION_ENABLED=true`
2. Use proxies to rotate IPs
3. Increase delays between requests
4. Randomize user agents: `RANDOMIZE_USER_AGENT=true`

### 4. Playwright/Browser Errors

**Log Pattern**:
```
ERROR - playwright._impl._errors.TimeoutError: Timeout 30000ms exceeded
ERROR - Executable doesn't exist at /path/to/browser
```

**Possible Causes**:
- Playwright browsers not installed
- Page load timeout
- Network connectivity issues

**Solutions**:
```bash
# Install Playwright browsers
playwright install

# Check browser installation
playwright install --help

# Increase timeout in .env
BROWSER_TIMEOUT_MS=60000
```

### 5. Parsing Errors

**Log Pattern**:
```
ERROR - Failed to parse business data from HTML
WARNING - Missing required field: phone
ERROR - Invalid address format
```

**Possible Causes**:
- HTML structure changed on source website
- Incomplete or malformed HTML
- New page layout not yet supported

**Solutions**:
1. Check screenshot in `logs/screenshots/` to see the page
2. Update parser in `scrape_yp/yp_parser_enhanced.py`
3. Enable DEBUG logging: `LOG_LEVEL=DEBUG` in `.env`

### 6. Crash Recovery Issues

**Log Pattern**:
```
INFO - Found stale target, reclaiming (worker last seen 10 min ago)
WARNING - WAL file corrupt, cannot resume
ERROR - Checkpoint data inconsistent
```

**Possible Causes**:
- Worker process died unexpectedly
- Disk full during WAL write
- Concurrent access to same target

**Solutions**:
1. Check disk space: `df -h`
2. Review WAL logs: `ls -lh logs/yp_wal/`
3. Reset stale targets:
```sql
UPDATE yp_targets
SET status = 'PLANNED', claimed_by = NULL
WHERE status = 'IN_PROGRESS' AND heartbeat_at < NOW() - INTERVAL '10 minutes';
```

### 7. Memory/Resource Issues

**Log Pattern**:
```
ERROR - MemoryError: Unable to allocate memory
WARNING - Too many open files
```

**Possible Causes**:
- Too many concurrent workers
- Browser instances not closing
- Large result sets

**Solutions**:
1. Reduce `WORKER_COUNT` in `.env`
2. Reduce `MAX_CONCURRENT_SITE_SCRAPES`
3. Increase system limits:
```bash
ulimit -n 4096  # Increase file descriptor limit
```

### 8. Job Scheduling Errors

**Log Pattern**:
```
ERROR - APScheduler job failed to execute
WARNING - Job missed scheduled time
```

**Possible Causes**:
- System time changed
- Job timeout exceeded
- Database connection lost during job

**Solutions**:
1. Check system time: `date`
2. Review scheduled jobs in database:
```sql
SELECT * FROM scheduled_jobs WHERE enabled = true;
```
3. Check job execution logs:
```sql
SELECT * FROM job_execution_logs
WHERE status = 'failed'
ORDER BY started_at DESC
LIMIT 10;
```

## How to Use Logs for Debugging

### 1. Real-Time Monitoring

**Tail a log file**:
```bash
tail -f logs/yp_crawl_city_first.log
```

**Tail with grep for specific errors**:
```bash
tail -f logs/yp_crawl_city_first.log | grep ERROR
```

**Tail multiple logs**:
```bash
tail -f logs/*.log
```

### 2. Search Historical Logs

**Find all errors today**:
```bash
grep ERROR logs/yp_crawl_city_first.log | grep "2025-11-23"
```

**Count error types**:
```bash
grep ERROR logs/yp_crawl_city_first.log | cut -d'-' -f4 | sort | uniq -c | sort -rn
```

**Find specific error pattern**:
```bash
grep -i "rate limit" logs/*.log
```

### 3. Using the GUI Log Viewer

1. Open dashboard: http://localhost:8080
2. Go to **Logs** tab
3. Select log file from dropdown
4. Use filters:
   - Log level (INFO, WARNING, ERROR)
   - Date range
   - Search text

**Features**:
- Real-time updates
- Syntax highlighting
- Download log files
- Filter by severity

## Log Rotation

Logs automatically rotate when they reach 10MB. Rotation configuration:

- **Max Size**: 10MB per file
- **Backups**: 5 rotated files kept
- **Format**: `{logfile}.1`, `{logfile}.2`, etc.
- **Compression**: Optionally gzip old logs

**Manual rotation** (if needed):
```bash
# Using logrotate systemd service
sudo systemctl start washdb-bot-logrotate

# Or manually archive
cd logs
for log in *.log; do
    if [ -f "$log" ] && [ $(stat -f%z "$log" 2>/dev/null || stat -c%s "$log") -gt 10485760 ]; then
        gzip -c "$log" > "$log.$(date +%Y%m%d).gz"
        > "$log"  # Truncate
    fi
done
```

## Changing Log Levels

### Globally (via .env)

```bash
# Edit .env
LOG_LEVEL=DEBUG  # Options: DEBUG, INFO, WARNING, ERROR, CRITICAL

# Restart application
./scripts/dev/run-gui.sh
```

### Per Module (programmatically)

```python
# In your Python code
from runner.logging_setup import get_logger
import logging

logger = get_logger("my_module")
logger.setLevel(logging.DEBUG)  # Enable DEBUG for this module only
```

### Temporarily (command line)

```bash
# Set log level for single run
LOG_LEVEL=DEBUG python cli_crawl_yp.py --states RI
```

## Log Analysis Tips

### 1. Find Scraping Success Rate

```bash
grep -c "Successfully scraped" logs/yp_crawl_city_first.log
grep -c "Failed to scrape" logs/yp_crawl_city_first.log
```

### 2. Identify Slowest Operations

```bash
grep "duration_seconds" logs/backend_facade.log | sort -t':' -k4 -n | tail -20
```

### 3. Check for Memory Leaks

```bash
# Watch for repeated "allocat" errors over time
grep -i "memory\|allocat" logs/*.log | wc -l
```

### 4. Monitor Rate Limiting

```bash
# Count rate limit warnings per hour
grep "rate limit" logs/yp_crawl_city_first.log | cut -d' ' -f1-2 | uniq -c
```

## Best Practices

1. **Enable DEBUG logging** during development for detailed diagnostics
2. **Use INFO logging** in production for operational visibility
3. **Monitor logs regularly** via dashboard or `tail -f`
4. **Archive old logs** before they rotate out (keep for compliance)
5. **Search logs first** before asking for help (often faster)
6. **Include log snippets** when reporting issues (with timestamps)
7. **Check multiple log files** - errors may appear in related logs

## Troubleshooting Checklist

When something goes wrong:

- [ ] Check the relevant log file(s) for ERROR lines
- [ ] Look for WARNING messages preceding the error
- [ ] Verify configuration in `.env` or `.env.dev`
- [ ] Test database connection: `psql -U washbot -d washbot_db`
- [ ] Check system resources: `df -h`, `free -h`, `top`
- [ ] Review job execution history in database or GUI
- [ ] Look for screenshots in `logs/screenshots/` if Playwright involved
- [ ] Enable DEBUG logging and reproduce the issue
- [ ] Search existing GitHub issues for similar errors

---

**See Also**:
- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture overview
- [QUICKSTART-dev.md](QUICKSTART-dev.md) - Setup guide
- [index.md](index.md) - Documentation index
