# Log Management Guide

**Purpose**: Document log file locations, rotation policies, and tail commands for monitoring long-running scraper jobs.

---

## Log File Locations

All logs are stored in the `logs/` directory at the project root:

```bash
washdb-bot/
├── logs/
│   ├── yp_crawl_city_first.log      # YP city-first crawler (main)
│   ├── google_scrape.log            # Google Maps scraper
│   ├── url_finder.log               # URL finder (Phase 2 for HA)
│   ├── gui_backend.log              # Flask backend API logs
│   ├── nicegui_app.log              # NiceGUI dashboard logs (legacy)
│   ├── state_worker_pool.log        # Multi-worker manager logs
│   ├── state_worker_0.log           # Individual worker logs (0-9)
│   ├── state_worker_1.log
│   ├── ...
│   ├── state_worker_9.log
│   ├── generate_targets.log         # YP target generation logs
│   └── migration.log                # Database migration logs
```

**Environment Variable**: `LOG_DIR=logs` (configured in `.env`)

---

## Log Rotation Configuration

### Current Status: ✅ Built-in Python RotatingFileHandler

**Configuration** (in `runner/logging_setup.py`):
```python
from logging.handlers import RotatingFileHandler

# Rotating file handler
file_handler = RotatingFileHandler(
    log_file,
    maxBytes=10 * 1024 * 1024,  # 10 MB per file
    backupCount=5                # Keep 5 backup files
)
```

**Behavior**:
- **Max File Size**: 10 MB per log file
- **Backup Count**: 5 rotated files kept (e.g., `yp_crawl_city_first.log.1`, `.2`, etc.)
- **Total Storage**: ~60 MB max per log (10 MB × 6 files)
- **Automatic**: Rotation happens automatically when file reaches 10 MB
- **Thread-Safe**: Safe for multi-worker scenarios

**Example Rotation**:
```
logs/
├── yp_crawl_city_first.log       # Current (active)
├── yp_crawl_city_first.log.1     # Previous (most recent backup)
├── yp_crawl_city_first.log.2     # Older
├── yp_crawl_city_first.log.3     # Older
├── yp_crawl_city_first.log.4     # Older
└── yp_crawl_city_first.log.5     # Oldest (will be deleted on next rotation)
```

**Safety for Long Runs**:
- ✅ **No disk space issues**: Logs automatically cap at 60 MB per file
- ✅ **No manual intervention**: Rotation is automatic
- ✅ **Multi-worker safe**: Each worker has its own log file

---

## Log Levels

Configured via `LOG_LEVEL` environment variable (default: `INFO`).

**Available Levels**:
- `DEBUG`: Verbose output (request details, parsing steps)
- `INFO`: Normal operation (targets processed, results found) ← **Default**
- `WARNING`: Issues that don't stop execution (CAPTCHAs, rate limits)
- `ERROR`: Failures (network errors, parsing errors)
- `CRITICAL`: Fatal errors (database connection lost)

**Change Log Level**:
```bash
# Edit .env file
LOG_LEVEL=DEBUG  # For detailed debugging
LOG_LEVEL=WARNING  # For quieter logs
```

---

## Tailing Logs (Real-Time Monitoring)

### 1. Tail a Single Log File

```bash
# YP crawler (main scraper)
tail -f logs/yp_crawl_city_first.log

tail -f logs/ha_crawl.log

# Specific worker (e.g., worker 3)
tail -f logs/state_worker_3.log

# Multi-worker manager
tail -f logs/state_worker_pool.log
```

### 2. Tail Multiple Logs Simultaneously

```bash
# All worker logs at once
tail -f logs/state_worker_*.log

# All scrapers
tail -f logs/*_crawl*.log

# Everything (verbose!)
tail -f logs/*.log
```

### 3. Tail with Grep Filters

**Show only warnings and errors**:
```bash
tail -f logs/yp_crawl_city_first.log | grep -E "WARNING|ERROR|CRITICAL"
```

**Show only CAPTCHA detections**:
```bash
tail -f logs/yp_crawl_city_first.log | grep -i "captcha"
```

**Show only successful saves**:
```bash
tail -f logs/yp_crawl_city_first.log | grep "Upsert complete"
```

**Show rate limiting events**:
```bash
tail -f logs/yp_crawl_city_first.log | grep -i "rate limit\|delay\|backoff"
```

### 4. Tail Last N Lines

```bash
# Show last 100 lines
tail -n 100 logs/yp_crawl_city_first.log

# Show last 50 lines and continue tailing
tail -n 50 -f logs/yp_crawl_city_first.log
```

### 5. Tail with Timestamps Highlighted

```bash
# Highlight timestamps in output (requires ANSI colors)
tail -f logs/yp_crawl_city_first.log | grep --color=always -E "^\[.*?\]|$"
```

---

## Log Analysis Commands

### Count Errors in a Log File

```bash
# Count total errors
grep -c "ERROR" logs/yp_crawl_city_first.log

# Count by error type
grep "ERROR" logs/yp_crawl_city_first.log | cut -d'-' -f3 | sort | uniq -c | sort -rn
```

### Find Top Errors

```bash
# Top 10 most common errors
grep "ERROR" logs/yp_crawl_city_first.log | awk -F'ERROR' '{print $2}' | sort | uniq -c | sort -rn | head -10
```

### Check Crawler Progress

```bash
# Count targets processed
grep "Target complete" logs/yp_crawl_city_first.log | wc -l

# Show acceptance rate
grep "acceptance_rate" logs/yp_crawl_city_first.log | tail -20
```

### Monitor CAPTCHA Rate

```bash
# Count CAPTCHA detections
grep -i "captcha" logs/yp_crawl_city_first.log | wc -l

# Show CAPTCHA events with context
grep -i "captcha" logs/yp_crawl_city_first.log
```

---

## GUI Log Viewer

The NiceGUI dashboard includes a built-in **Live Log Viewer** with:

- ✅ **Auto-refresh**: Updates every 2 seconds
- ✅ **Filters**: Show only warnings, errors, or specific keywords
- ✅ **Auto-scroll**: Automatically scrolls to newest entries
- ✅ **Max lines**: Configurable (default: 300-500 lines)

**Access**: Navigate to the **Discover** page → Scroll to "Live Crawler Output"

**Features**:
- Tail last N lines on page load
- Start/stop tailing
- Color-coded log levels (info, warning, error)
- Per-worker log tabs (multi-worker view)

---

## Log File Size Management

### Check Total Log Directory Size

```bash
du -sh logs/
```

### Find Largest Log Files

```bash
du -h logs/*.log | sort -hr | head -10
```

### Clean Old Rotated Logs (Manual)

If you need to free up space:

```bash
# Remove all .1, .2, .3, .4, .5 backup files
rm logs/*.log.[1-5]

# Remove logs older than 7 days
find logs/ -name "*.log*" -mtime +7 -delete
```

**Note**: Automated rotation already limits size, so manual cleanup is rarely needed.

---

## Log Format

**Standard Format**:
```
YYYY-MM-DD HH:MM:SS - logger_name - LEVEL - message
```

**Example**:
```
2025-11-18 14:32:15 - yp_crawl_city_first - INFO - Target complete: Los Angeles, CA - Window Cleaning | pages=3, parsed=45, accepted=12 (26.7%)
2025-11-18 14:32:16 - yp_crawl_city_first - WARNING - CAPTCHA detected on page 2
2025-11-18 14:32:17 - yp_crawl_city_first - ERROR - Failed to fetch page: Timeout after 30s
```

**Fields**:
1. **Timestamp**: ISO format with timezone
2. **Logger Name**: Module that generated the log
3. **Level**: INFO, WARNING, ERROR, etc.
4. **Message**: Human-readable message

---

## Troubleshooting

### Issue: Log File Not Found

**Symptom**: `tail: cannot open 'logs/yp_crawl_city_first.log' for reading: No such file or directory`

**Solution**:
```bash
# Create logs directory if missing
mkdir -p logs

# Run the crawler to generate log file
python -m scrape_yp.worker_pool --states RI --max-targets 1
```

### Issue: Permission Denied

**Symptom**: `tail: logs/yp_crawl_city_first.log: Permission denied`

**Solution**:
```bash
# Fix permissions
chmod 644 logs/*.log
```

### Issue: Log File Too Large to Open

**Symptom**: Text editor hangs when opening large log file

**Solution**:
```bash
# View last 1000 lines instead of entire file
tail -n 1000 logs/yp_crawl_city_first.log

# Or use less with search
less +G logs/yp_crawl_city_first.log  # Jump to end
```

### Issue: Logs Growing Too Fast

**Symptom**: Log files fill up despite rotation

**Solution**:
```bash
# Reduce log level to WARNING or ERROR
# Edit .env:
LOG_LEVEL=WARNING

# Or reduce backup count in runner/logging_setup.py:
backupCount=3  # Instead of 5
```

---

## Best Practices

### For Development
- Use `LOG_LEVEL=DEBUG` for detailed output
- Tail logs in separate terminal: `tail -f logs/yp_crawl_city_first.log`
- Use grep filters to focus on specific events

### For Production
- Use `LOG_LEVEL=INFO` (default)
- Monitor logs via NiceGUI dashboard (no SSH needed)
- Check disk space periodically: `df -h` and `du -sh logs/`
- Archive old logs if needed: `tar -czf logs_backup_$(date +%F).tar.gz logs/*.log.[1-5]`

### For Long-Running Jobs
- ✅ **Rotation is automatic** - no manual intervention needed
- Monitor via GUI instead of SSH
- Use health checks to detect issues early
- Review logs after completion for errors

---

## Quick Reference

| Task | Command |
|------|---------|
| Tail main YP crawler | `tail -f logs/yp_crawl_city_first.log` |
| Tail with errors only | `tail -f logs/*.log \| grep ERROR` |
| Show last 100 lines | `tail -n 100 logs/yp_crawl_city_first.log` |
| Count errors | `grep -c ERROR logs/yp_crawl_city_first.log` |
| Check log size | `du -sh logs/` |
| View in GUI | Dashboard → Discover → Live Crawler Output |

---

**Log Rotation**: ✅ **Automatic** (Python RotatingFileHandler, 10 MB × 6 files)
**Long Run Safety**: ✅ **Protected** (capped at ~60 MB per log)
**Real-Time Monitoring**: ✅ **GUI + CLI** (NiceGUI dashboard and tail -f)

**For more help**: See `runner/logging_setup.py` for configuration details.
