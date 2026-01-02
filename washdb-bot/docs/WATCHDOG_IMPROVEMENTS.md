# Watchdog System Improvements for Long-Term Deployment

## Current Status (2026-01-02)

### What's Working
- 5 services sending heartbeats to `job_heartbeats` table
- Watchdog detecting resource warnings (47 in last 24h)
- Standardization service now reporting job success/failure (18 ok, 10 fail)
- All workers have < 1 minute heartbeat lag

### Identified Gaps

## Priority 1: Critical Improvements

### 1.1 Add Failure Rate Monitoring
**Problem:** Watchdog only checks for stale heartbeats, not high failure rates. A service can fail 98% of jobs without triggering healing.

**Solution:** Add `_check_failure_rates()` method to UnifiedWatchdog:
```python
def _check_failure_rates(self):
    """Check for workers with high failure rates."""
    with self.db_manager.get_session() as session:
        result = session.execute(text("""
            SELECT worker_name, worker_type, service_unit,
                   jobs_completed, jobs_failed,
                   CASE WHEN (jobs_completed + jobs_failed) > 0
                        THEN jobs_failed::float / (jobs_completed + jobs_failed)
                        ELSE 0 END as failure_rate
            FROM job_heartbeats
            WHERE status = 'running'
              AND (jobs_completed + jobs_failed) > 10  -- Minimum sample size
              AND jobs_failed::float / NULLIF(jobs_completed + jobs_failed, 0) > 0.5
        """))
        # Trigger healing for workers with >50% failure rate
```

### 1.2 Lower Chrome Critical Threshold
**Problem:** CHROME_CRITICAL_THRESHOLD = 720 is too high. System runs 300-400 normally.

**Solution:**
- Change CHROME_WARNING_THRESHOLD from 300 to 400
- Change CHROME_CRITICAL_THRESHOLD from 720 to 500
- Add incremental cleanup at warning level

### 1.3 Add Disk Space Monitoring
**Problem:** Disk at 85% usage with no monitoring.

**Solution:** Add to `_check_resources()`:
```python
def _check_disk_usage(self):
    import shutil
    usage = shutil.disk_usage('/')
    percent_used = (usage.used / usage.total) * 100
    if percent_used > 90:
        # Trigger log rotation and cleanup
```

## Priority 2: Reliability Improvements

### 2.1 Browser Session Health Check
**Problem:** Browser sessions can stall while heartbeat continues (saw "Max retries exceeded" pattern).

**Solution:** Check error patterns in heartbeat `last_error` field:
```python
STALE_SESSION_PATTERNS = [
    "Max retries exceeded",
    "ERR_TUNNEL_CONNECTION_FAILED",
    "session not found"
]
```

### 2.2 Accumulated Warning Healing
**Problem:** 47 resource warnings with no action taken.

**Solution:** If >10 warnings in 30 minutes, trigger Chrome cleanup:
```python
if self._count_recent_warnings() > 10:
    self._trigger_chrome_cleanup()
```

### 2.3 Enable Watchdog Auto-Start
**Problem:** `unified-watchdog.service` is disabled (won't start on boot).

**Solution:**
```bash
sudo systemctl enable unified-watchdog.service
```

## Priority 3: Operational Improvements

### 3.1 Log Rotation Enforcement
- Implement daily log rotation for all services
- Add log compression for files > 100MB
- Auto-delete logs older than 30 days

### 3.2 Heartbeat Dashboard Integration
- Add NiceGUI page showing all worker heartbeats
- Show failure rate trends
- Alert on stale or failing workers

### 3.3 Email Alerts
- Send email on critical events
- Daily summary of healing actions
- Weekly health report

## Implementation Roadmap

1. **Immediate (Today):**
   - [x] Add job tracking to standardization service
   - [x] Restart YP/Google workers with heartbeat
   - [ ] Enable watchdog auto-start
   - [ ] Lower Chrome thresholds

2. **This Week:**
   - [ ] Add failure rate monitoring
   - [ ] Add disk space monitoring
   - [ ] Add browser session health check

3. **This Month:**
   - [ ] Add log rotation
   - [ ] Add NiceGUI dashboard
   - [ ] Add email alerts

## Metrics to Monitor

| Metric | Warning | Critical | Current |
|--------|---------|----------|---------|
| Chrome processes | 400 | 500 | 358 |
| Memory % | 85% | 95% | 25% |
| Disk % | 85% | 95% | 85% |
| Heartbeat lag | 3 min | 5 min | <1 min |
| Failure rate | 30% | 50% | ~36% (std) |

## Files Modified

- `services/unified_watchdog.py` - Add failure rate checks
- `services/heartbeat_manager.py` - Already complete
- `scripts/standardization_service_browser.py` - Job tracking added
- `scrape_yp/state_worker_pool.py` - Heartbeat added
- `scrape_google/state_worker_pool.py` - Heartbeat added
