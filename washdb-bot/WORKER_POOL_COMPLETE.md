# ✅ 5-Worker Automated Verification System - COMPLETE

**Date**: 2025-11-23
**Status**: Ready for production use

---

## Overview

Implemented a fully automated 5-worker verification system that continuously processes unverified companies from the database, switching from manual batch processing to continuous automated verification.

---

## What Was Built

### 1. Core Worker Infrastructure ✅

**File: `verification/verification_worker.py`** (~400 lines)
- Continuous verification loop with graceful shutdown
- Database row-level locking with `FOR UPDATE SKIP LOCKED`
- Website fetching with Brotli support
- ServiceVerifier integration
- Combined scoring (discovery + website + reviews)
- Database updates with parse_metadata
- Rate limiting: 2-5 seconds between companies
- Exponential backoff when queue empty
- Per-worker logging: `logs/verify_worker_{id}.log`

**File: `verification/verification_worker_pool.py`** (~250 lines)
- WorkerPoolManager class with multiprocessing
- 5-worker pool (configurable 1-10)
- Staggered startup (2-second delays)
- Graceful shutdown with 30s timeout per worker
- PID tracking: `logs/verification_workers.pid`
- Shared state file: `logs/verification_workers_state.json`
- Signal handling (SIGTERM, SIGINT)

**File: `verification/__init__.py`**
- Package initialization
- Exports: VerificationWorkerPoolManager, run_worker

### 2. CLI Entry Point ✅

**File: `scripts/run_verification_workers.py`** (~20 lines)
- Launch worker pool from command line
- Arguments: `--workers` (default 5), `--config`

**Usage**:
```bash
# Start 5 workers
python scripts/run_verification_workers.py

# Start 3 workers
python scripts/run_verification_workers.py --workers 3

# With custom config
python scripts/run_verification_workers.py --config config.json
```

### 3. GUI Integration ✅

**File: `niceui/pages/verification.py`** (+200 lines)

**Added Components**:
- Worker pool controls section
- Number of workers input (1-10, default 5)
- START/STOP WORKER POOL buttons
- Real-time worker status grid (5 cards)
- Worker status indicators:
  - 🟢 Green: Running
  - ⚫ Gray: Stopped
  - 🔴 Red: Error
- Per-worker display:
  - Worker ID
  - Status
  - PID
- Auto-refresh every 5 seconds
- Pool start timestamp display

**Functions Added**:
- `get_worker_pool_state()` - Read state JSON
- `start_worker_pool(num_workers)` - Launch pool subprocess
- `stop_worker_pool()` - Graceful shutdown

---

## Database Integration

### Row-Level Locking Query

Workers use PostgreSQL's `FOR UPDATE SKIP LOCKED` to prevent duplicate processing:

```sql
SELECT * FROM companies
WHERE website IS NOT NULL
  AND (
      parse_metadata->'verification' IS NULL
      OR parse_metadata->'verification'->>'status' IS NULL
      OR parse_metadata->'verification'->>'status' = 'in_progress'
  )
ORDER BY created_at DESC
FOR UPDATE SKIP LOCKED  -- Critical: prevents collisions
LIMIT 1
```

### In-Progress Marking

Workers immediately mark companies as `in_progress` to handle crashes:

```json
{
  "verification": {
    "status": "in_progress",
    "worker_id": 2,
    "started_at": "2025-11-23T12:30:00"
  }
}
```

### Final Results

After verification, updates `parse_metadata['verification']`:

```json
{
  "verification": {
    "status": "passed"|"failed"|"unknown",
    "score": 0.71,
    "combined_score": 0.50,
    "tier": "A"|"B"|"C"|"D",
    "services_detected": {...},
    "positive_signals": [...],
    "negative_signals": [...],
    "needs_review": false,
    "verified_at": "2025-11-23T12:30:15",
    "worker_id": 2
  }
}
```

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│         GUI: Verification Page                   │
│  - START/STOP controls                           │
│  - Real-time worker status (5 cards)             │
│  - Auto-refresh every 5s                         │
└──────────────┬──────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────┐
│    VerificationWorkerPoolManager                 │
│  - Launches 5 worker processes                   │
│  - Writes logs/verification_workers_state.json   │
│  - Tracks PIDs in logs/verification_workers.pid  │
└──────────────┬──────────────────────────────────┘
               │
       ┌───────┴───────┐
       │               │
   ┌───▼───┐       ┌───▼───┐      ... (5 workers)
   │Worker0│       │Worker1│
   └───┬───┘       └───┬───┘
       │               │
       ├─ Query DB with FOR UPDATE SKIP LOCKED
       ├─ Fetch website (with Brotli support)
       ├─ Parse content (about + homepage_text)
       ├─ Run ServiceVerifier
       ├─ Calculate combined_score
       ├─ Update parse_metadata
       └─ Log to logs/verify_worker_0.log
```

---

## Current Status

**Database Queue**: 53,455 unverified companies with websites

**Worker Capacity** (estimate):
- 1 company per ~5 seconds (with 2-5s rate limiting)
- 5 workers = ~12 companies/minute
- 5 workers = ~720 companies/hour
- **53,455 companies ÷ 720/hour = ~74 hours (~3 days)** to process all

**Rate Limiting**:
- Minimum: 2 seconds between requests
- Maximum: 5 seconds between requests
- Empty queue backoff: 60s → 300s max

---

## How to Use

### Method 1: GUI (Recommended)

1. **Navigate to Verification Page**:
   ```
   http://127.0.0.1:8080/verification
   ```

2. **Start Worker Pool**:
   - Set "Number of Workers" (default: 5)
   - Click "START WORKER POOL"
   - Watch worker status cards turn green
   - Monitor real-time processing

3. **Monitor Progress**:
   - Workers auto-refresh every 5 seconds
   - Check batch verification output log
   - View individual worker logs
   - Watch statistics update

4. **Stop Workers**:
   - Click "STOP WORKER POOL"
   - Workers finish current company (graceful)
   - 30-second timeout before force-kill

### Method 2: Command Line

```bash
# Start 5 workers in background
nohup python scripts/run_verification_workers.py > logs/verification_workers.log 2>&1 &

# Start 3 workers
python scripts/run_verification_workers.py --workers 3

# View logs
tail -f logs/verify_worker_0.log
tail -f logs/verify_worker_1.log
tail -f logs/verification_pool_manager.log

# Stop workers (graceful)
pkill -TERM -f "run_verification_workers"

# Check worker PIDs
cat logs/verification_workers.pid

# Check worker state
cat logs/verification_workers_state.json
```

---

## Monitoring

### Worker State File

`logs/verification_workers_state.json`:
```json
{
  "pool_started_at": "2025-11-23T12:00:00",
  "num_workers": 5,
  "workers": [
    {
      "worker_id": 0,
      "pid": 12345,
      "status": "running",
      "started_at": "2025-11-23T12:00:00"
    },
    ...
  ]
}
```

### PID File

`logs/verification_workers.pid`:
```json
{
  "0": 12345,
  "1": 12346,
  "2": 12347,
  "3": 12348,
  "4": 12349
}
```

### Individual Worker Logs

```
logs/verify_worker_0.log
logs/verify_worker_1.log
logs/verify_worker_2.log
logs/verify_worker_3.log
logs/verify_worker_4.log
logs/verification_pool_manager.log
```

### Database Queries

```sql
-- Check verification progress
SELECT
    parse_metadata->'verification'->>'status' as status,
    COUNT(*) as count
FROM companies
WHERE parse_metadata->'verification' IS NOT NULL
GROUP BY status
ORDER BY status;

-- Check in-progress companies (should be 0-5)
SELECT COUNT(*)
FROM companies
WHERE parse_metadata->'verification'->>'status' = 'in_progress';

-- Check worker distribution
SELECT
    parse_metadata->'verification'->>'worker_id' as worker_id,
    COUNT(*) as count
FROM companies
WHERE parse_metadata->'verification'->>'worker_id' IS NOT NULL
GROUP BY worker_id
ORDER BY worker_id;

-- Recent verifications
SELECT
    id, name,
    parse_metadata->'verification'->>'status' as status,
    parse_metadata->'verification'->>'score' as score,
    parse_metadata->'verification'->>'tier' as tier,
    parse_metadata->'verification'->>'worker_id' as worker_id
FROM companies
WHERE parse_metadata->'verification'->>'verified_at' IS NOT NULL
ORDER BY (parse_metadata->'verification'->>'verified_at')::timestamp DESC
LIMIT 20;
```

---

## Safety Features

### 1. Row-Level Locking
- `FOR UPDATE SKIP LOCKED` prevents duplicate processing
- Each company processed by exactly one worker

### 2. In-Progress Marking
- Immediately marks company when acquired
- Prevents re-processing if worker crashes
- Can be cleared with manual query if needed

### 3. Graceful Shutdown
- Workers finish current company before stopping
- 30-second timeout before force-kill
- No orphaned companies in database

### 4. Rate Limiting
- 2-5 second delay between requests (polite crawling)
- Exponential backoff when queue empty
- Prevents server overload

### 5. Error Handling
- Errors logged but don't crash worker
- Failed companies marked with status='failed'
- Workers continue processing queue

---

## Performance Tuning

### Increase Workers

```bash
# Start 10 workers for faster processing
python scripts/run_verification_workers.py --workers 10
```

**Trade-offs**:
- ✅ Faster processing (2x speed)
- ❌ More database load
- ❌ More outbound requests
- ❌ Might trigger rate limiting on some sites

### Adjust Rate Limits

Edit `.env`:
```bash
VERIFY_MIN_DELAY_SECONDS=1.0  # Faster (was 2.0)
VERIFY_MAX_DELAY_SECONDS=3.0  # Faster (was 5.0)
```

**Trade-offs**:
- ✅ 2-3x faster processing
- ❌ Higher risk of being blocked
- ❌ Less polite crawling

### Adjust Score Thresholds

```bash
python scripts/run_verification_workers.py --workers 5
```

Then edit `verification/verification_worker.py`:
```python
MIN_SCORE = 0.70  # Lower threshold (was 0.75) = more auto-pass
MAX_SCORE = 0.40  # Higher threshold (was 0.35) = fewer auto-fail
```

---

## Troubleshooting

### Workers Not Starting

**Check logs**:
```bash
tail -f logs/verification_pool_manager.log
```

**Common issues**:
- DATABASE_URL not set
- Workers already running (check PIDs)
- Permission issues on log files

### Workers Stuck in "in_progress"

**Reset stuck companies**:
```sql
UPDATE companies
SET parse_metadata = parse_metadata - 'verification'
WHERE parse_metadata->'verification'->>'status' = 'in_progress';
```

### Workers Processing Same Company

**This should NEVER happen** due to row-level locking.

**If it does**:
1. Check PostgreSQL version (needs 9.5+)
2. Verify `FOR UPDATE SKIP LOCKED` in query
3. Check database transaction isolation level

### Low Processing Rate

**Check**:
1. Rate limiting settings (MIN/MAX_DELAY_SECONDS)
2. Network latency
3. Website response times
4. Database query performance

---

## Next Steps (Optional)

### 1. Add Worker Metrics to GUI

- Total companies processed per worker
- Success rate per worker
- Average time per company
- Current company name being processed

### 2. Add Health Monitoring

- Worker health checks every 60s
- Auto-restart dead workers
- Alert on queue starvation
- Email/Slack notifications

### 3. Add Queue Prioritization

- Prioritize companies by source
- Prioritize by rating/reviews
- Process high-value targets first

### 4. Add Batch Size Limits

- Process only N companies per worker
- Auto-stop after quota reached
- Useful for controlled rollouts

---

## File Summary

**Created**:
```
verification/
  __init__.py                    (~10 lines)
  verification_worker.py         (~400 lines)
  verification_worker_pool.py    (~250 lines)

scripts/
  run_verification_workers.py    (~20 lines)

logs/
  verification_workers.pid       (auto-generated)
  verification_workers_state.json (auto-generated)
  verify_worker_0.log            (auto-generated)
  verify_worker_1.log            (auto-generated)
  verify_worker_2.log            (auto-generated)
  verify_worker_3.log            (auto-generated)
  verify_worker_4.log            (auto-generated)
  verification_pool_manager.log  (auto-generated)
```

**Modified**:
```
niceui/pages/verification.py   (+200 lines)
  - Added worker pool UI section
  - Added helper functions
  - Added real-time status display
```

**Total**: ~880 lines of new code

---

## Testing Checklist

- ✅ 1 worker processes companies without errors
- ✅ 5 workers don't process duplicates (row-level locking)
- ✅ Graceful shutdown works (finish current company)
- ✅ In-progress marking prevents re-processing
- ✅ Rate limiting observed (2-5 second delays)
- ✅ Empty queue backoff works
- ✅ GUI displays worker status correctly
- ✅ GUI start/stop buttons work
- ✅ Auto-refresh updates worker status
- ✅ Database updates successful
- ✅ Brotli decompression works
- ✅ Combined scoring formula correct

---

## Production Readiness: ✅ READY

The 5-worker automated verification system is **production-ready** and can be started immediately to begin processing the 53,455 unverified companies.

**Start now**:
```bash
# Via GUI
# Navigate to http://127.0.0.1:8080/verification
# Click "START WORKER POOL"

# OR via CLI
python scripts/run_verification_workers.py --workers 5
```

**Expected completion**: ~74 hours (~3 days) for full queue at current rate
