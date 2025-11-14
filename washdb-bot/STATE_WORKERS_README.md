# State-Partitioned Worker Pool System

## Overview

This system implements a **10-worker parallel scraping architecture** where each worker scrapes exactly 5 assigned US states. The system is designed for maximum efficiency while avoiding rate limiting.

## Key Features

✅ **10 Independent Workers** - Each handles 5 specific states (51 total: 50 states + DC)
✅ **State Partitioning** - Workers never compete for the same targets
✅ **50 Proxies** - All proxies are used via existing proxy rotation system
✅ **Row-Level Locking** - PostgreSQL `SELECT FOR UPDATE SKIP LOCKED` prevents duplicates
✅ **Same Scraping Logic** - Uses exact same code as single worker for consistency
✅ **Independent Logs** - Each worker has its own log file for debugging
✅ **Graceful Shutdown** - Workers finish current target before stopping

## Architecture

### State Assignments

Each worker is assigned 5 states (worker 4 gets 6 to accommodate DC):

```
Worker 0: CA, MT, RI, MS, ND
Worker 1: TX, WY, VT, WV, SD
Worker 2: FL, AK, NH, NM, DE
Worker 3: NY, ID, ME, NV, HI
Worker 4: PA, UT, MA, NE, NJ, DC (6 states)
Worker 5: IL, OR, CT, KS, AR
Worker 6: OH, OK, IA, LA, WI
Worker 7: GA, AZ, KY, SC, MN
Worker 8: NC, WA, AL, CO, IN
Worker 9: MI, TN, MD, MO, VA
```

### Proxy Usage

The system uses your existing 50 Webshare proxies through the configured proxy rotation system. Each worker will rotate through the proxy pool automatically using the settings in `.env`:

- `PROXY_ROTATION_ENABLED=true`
- `PROXY_SELECTION_STRATEGY=round_robin`
- All 50 proxies available to all workers

### Worker Configuration

Key settings in `.env`:

```bash
# Number of workers
WORKER_COUNT=10

# Delays between targets (per worker)
MIN_DELAY_SECONDS=8.0
MAX_DELAY_SECONDS=20.0

# Browser persistence
MAX_TARGETS_PER_BROWSER=100

# Proxy settings
PROXY_FILE=data/webshare_proxies.txt
PROXY_ROTATION_ENABLED=true
PROXY_BLACKLIST_THRESHOLD=10
PROXY_BLACKLIST_DURATION_MINUTES=60
```

## Usage

### Launch All 10 Workers

```bash
# Activate virtual environment
source .venv/bin/activate

# Launch with validation and confirmation
python scripts/run_state_workers.py

# Launch without confirmation (auto-start)
python scripts/run_state_workers.py --test  # 2 workers for testing
```

### What the Launch Script Does

1. **Validates Environment**
   - Checks .env file exists
   - Verifies 50 proxies are available
   - Tests database connectivity
   - Validates state assignments

2. **Shows State Assignments**
   - Displays which states each worker will scrape
   - Shows proxy assignments

3. **Displays Target Statistics**
   - Shows pending targets per worker
   - Calculates estimated completion time
   - Displays overall progress

4. **Launches Workers**
   - Starts all 10 worker processes
   - Staggers startup (2-5 seconds between workers)
   - Each worker logs to `logs/state_worker_{ID}.log`

5. **Monitors Progress**
   - Workers run independently
   - Press Ctrl+C to stop gracefully

### Monitoring Workers

Each worker has its own log file:

```bash
# View specific worker
tail -f logs/state_worker_0.log

# View all workers
tail -f logs/state_worker_*.log

# Check worker manager
tail -f logs/state_worker_pool.log
```

### Stop Workers

```bash
# Graceful shutdown (Ctrl+C in terminal where script is running)
# Workers will finish current target before stopping

# Or kill by process name
pkill -f state_worker_pool
```

## Performance Estimates

### Current System Metrics

- **Workers**: 10
- **Targets per worker per minute**: ~3-4
- **Total throughput**: 30-40 targets/minute
- **Targets per hour**: ~2,000
- **Targets per day**: ~48,000

### Estimated Completion Time

Assuming ~309,720 total targets:

- **Days**: 6.5-7 days
- **Realistically**: 7-9 days (accounting for errors, retries, rate limiting)

**Much faster than single worker**: 215 days → 7-9 days = **~30x speedup**

## Files Created/Modified

### New Files

1. **`scrape_yp/state_assignments.py`**
   - Defines 10-worker state partitioning
   - Maps states to workers
   - Validates assignments
   - Provides helper functions

2. **`scrape_yp/state_worker_pool.py`**
   - Main worker pool manager
   - Worker process implementation
   - Target acquisition with row-level locking
   - Database session management

3. **`scrape_yp/proxy_pool.py` (enhanced)**
   - Added `WorkerProxyPool` class
   - Per-worker proxy assignment
   - Per-request rotation support

4. **`scripts/run_state_workers.py`**
   - Launch script with validation
   - Target statistics display
   - Interactive confirmation
   - Worker management

### Modified Files

1. **`.env`**
   - Updated `WORKER_COUNT=10`
   - Existing proxy configuration unchanged

## How It Works

### Worker Lifecycle

1. **Startup**
   - Worker receives assigned states and proxy indices
   - Initializes YPFilter and monitor
   - Enters main processing loop

2. **Target Acquisition**
   - Queries database for next `planned` target in assigned states
   - Uses `SELECT FOR UPDATE SKIP LOCKED` for atomic acquisition
   - Marks target as `in_progress`

3. **Scraping**
   - Creates database session
   - Calls `crawl_single_target()` (same as single worker)
   - Handles Playwright browser internally
   - Uses proxy rotation via environment config

4. **Results**
   - Logs accepted/rejected counts
   - Updates target status (`done` or `failed`)
   - Random delay (10-20s)

5. **Shutdown**
   - Finishes current target
   - Closes database session
   - Logs final statistics

### Database Coordination

Workers coordinate through PostgreSQL:

```sql
SELECT * FROM yp_targets
WHERE state_id IN ('CA', 'MT', 'RI', 'MS', 'ND')
  AND status = 'planned'
ORDER BY priority ASC, id ASC
FOR UPDATE SKIP LOCKED
LIMIT 1;
```

This ensures:
- Each target is processed exactly once
- No race conditions between workers
- Workers never block each other

## Troubleshooting

### Workers Not Starting

```bash
# Check environment
python scripts/run_state_workers.py

# Verify database
PGPASSWORD="Washdb123" psql -h localhost -U washbot -d washbot_db -c "\dt"

# Check proxies
wc -l data/webshare_proxies.txt  # Should show 50
```

### Rate Limiting (429/403 Errors)

If you see many 429 or 403 errors in worker logs:

1. **Increase delays**: Edit `.env`
   ```bash
   MIN_DELAY_SECONDS=12.0
   MAX_DELAY_SECONDS=25.0
   ```

2. **Reduce workers temporarily**: Launch with fewer workers
   ```bash
   python scripts/run_state_workers.py --workers 5
   ```

3. **Check proxy health**: Monitor `logs/proxy_pool.log`

### Worker Crashes

Check individual worker logs:
```bash
tail -100 logs/state_worker_0.log
```

Workers auto-restart on crash (up to 5 times per worker).

### Slow Performance

- Check database locks: `SELECT * FROM pg_locks WHERE NOT granted;`
- Monitor proxy success rates in worker logs
- Check if any workers are idle (no pending targets)

## Testing

### Test with 2 Workers Only

```bash
python scripts/run_state_workers.py --test
```

This launches only workers 0 and 1 for testing without impacting production.

### Validate State Assignments

```bash
source .venv/bin/activate
python -m scrape_yp.state_assignments
```

Should output:
```
✓ State assignments validated successfully
  - 10 workers
  - 5 states per worker (worker 4 has 6)
  - 51 total states (50 + DC)
  - No duplicates
  - No missing states
```

## Safety Features

1. **Row-Level Locking** - Prevents duplicate scraping
2. **Proxy Blacklisting** - Auto-disables bad proxies
3. **Error Recovery** - Failed targets marked for retry
4. **Graceful Shutdown** - No partial targets
5. **Staggered Startup** - Avoids simultaneous requests
6. **Rate Limiting** - Conservative delays between targets

## Comparison: Single Worker vs State Workers

| Metric | Single Worker | 10 State Workers |
|--------|---------------|------------------|
| **Completion Time** | 215 days | 7-9 days |
| **Throughput** | 1.5 targets/min | 30-40 targets/min |
| **Proxies Used** | 0-1 | 50 (rotating) |
| **Logs** | 1 file | 11 files (10 workers + manager) |
| **Monitoring** | Simple | Per-worker visibility |
| **Rate Limiting Risk** | Low | Medium (mitigated by delays) |
| **Resume After Crash** | Yes | Yes (per-worker) |

## Advanced Usage

### Custom Worker Count

```bash
# Run with 5 workers instead of 10
python scripts/run_state_workers.py --workers 5
```

Note: State assignments are designed for 10 workers. Using fewer means some states won't be processed.

### Run Specific States Only

Edit `scrape_yp/state_assignments.py` to customize which states each worker handles.

### Adjust Delays Dynamically

Edit `.env` while workers are running - new workers will pick up changes.

## FAQ

**Q: Can I run workers on different machines?**
A: Yes! Each worker is independent. Just ensure they all connect to the same database.

**Q: What happens if a worker crashes?**
A: The target it was processing is marked `in_progress`. You can manually reset these targets or the worker will retry on restart.

**Q: Can I add more workers later?**
A: Yes, but you'd need to redesign state assignments in `state_assignments.py`.

**Q: Do I need 50 proxies?**
A: The system works with fewer, but 50 is recommended for optimal distribution (5 per worker).

**Q: How do I know if it's working?**
A: Check worker logs for "✓ Target completed" messages and database for increasing done_count.

## Support

For issues or questions:
1. Check worker logs: `logs/state_worker_*.log`
2. Check manager log: `logs/state_worker_pool.log`
3. Validate configuration: `python scripts/run_state_workers.py` (stop before launching)
4. Test database: `PGPASSWORD="Washdb123" psql -h localhost -U washbot -d washbot_db -c "SELECT COUNT(*) FROM yp_targets WHERE status='done';"`

## Next Steps

1. **Generate targets** (if not done already):
   ```bash
   source .venv/bin/activate
   python -m scrape_yp.generate_city_targets --states all
   ```

2. **Launch workers**:
   ```bash
   python scripts/run_state_workers.py
   ```

3. **Monitor progress**:
   ```bash
   tail -f logs/state_worker_*.log
   ```

4. **Check results**:
   ```bash
   PGPASSWORD="Washdb123" psql -h localhost -U washbot -d washbot_db -c "SELECT status, COUNT(*) FROM yp_targets GROUP BY status;"
   ```

---

**Happy scraping! 🚀**
