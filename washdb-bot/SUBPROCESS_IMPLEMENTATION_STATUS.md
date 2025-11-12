# Subprocess Runner Implementation - Status

## Goal
Replace thread-based `backend.discover()` with actual subprocess execution for:
- **True instant kill** via SIGKILL (no waiting for batch)
- **Real-time log streaming** from actual crawler process
- **PID tracking** for process management

## Completed ✅

### 1. Infrastructure Files Created

**`cli_crawl_yp.py`** - CLI wrapper for YP crawler
- Runs as standalone subprocess
- Takes `--categories`, `--states`, `--pages` arguments
- Writes all output to stdout (captured by log file)
- Uses actual YP crawler (`crawl_all_states`)
- Saves results to database via `upsert_discovered()`
- Can be killed instantly via SIGKILL

**`niceui/utils/subprocess_runner.py`** - Process management class
- `SubprocessRunner` class for managing subprocesses
- Tracks PID, start/end time, return code
- `start()` - Launch subprocess with log file redirection
- `kill()` - Instant SIGKILL of process group
- `is_running()` - Check if still alive
- `get_status()` - Get process info

**`niceui/widgets/live_log_viewer.py`** - Already complete ✅
- Tails log files in real-time
- Auto-scroll implemented
- Enhanced error detection (red text)
- Works great!

### 2. Process Manager Enhanced ✅
- `niceui/utils/process_manager.py` tracks jobs globally
- Can register jobs with PIDs
- Kill by job_id

## Remaining Work 🚧

### 3. Integrate Subprocess into Discovery Page

**File to modify:** `niceui/pages/discover.py`

**Changes needed:**

#### A. Add imports:
```python
from ..utils.subprocess_runner import SubprocessRunner
import os
```

#### B. Replace `run_yellow_pages_discovery()` function:

**Current approach:**
```python
result = await run.io_bound(
    backend.discover,
    categories,
    states,
    pages_per_pair,
    ...
)
```

**New subprocess approach:**
```python
# Build command
categories_str = ','.join(categories)
states_str = ','.join(states)

cmd = [
    sys.executable,  # Python interpreter
    'cli_crawl_yp.py',
    '--categories', categories_str,
    '--states', states_str,
    '--pages', str(pages_per_pair)
]

# Create subprocess runner
runner = SubprocessRunner('discovery_yp', 'logs/yp_crawl.log')

# Start subprocess
pid = runner.start(cmd, cwd=os.getcwd())

# Register PID with process manager
process_manager.register('discovery_yp', 'YP Discovery', pid=pid, log_file='logs/yp_crawl.log')

# Wait for completion (non-blocking)
while runner.is_running():
    await asyncio.sleep(1.0)

    # Check for cancellation
    if discovery_state.is_cancelled():
        runner.kill()  # INSTANT KILL!
        break

# Get final status
status = runner.get_status()
return_code = status['return_code']
```

#### C. Update stop button handler:

**Current (doesn't work):**
```python
killed = process_manager.kill('discovery_yp', force=True)
# Returns False because no PID registered
```

**New (instant kill):**
```python
# Process manager now has actual PID!
killed = process_manager.kill('discovery_yp', force=True)
# Returns True and kills immediately via SIGKILL
```

### 4. Testing Checklist

After integration:
- [ ] Start YP discovery
- [ ] Verify logs stream in real-time in LiveLogViewer
- [ ] Verify `ps aux | grep cli_crawl_yp` shows process
- [ ] Click STOP button during active crawl
- [ ] Verify process dies instantly (< 1 second)
- [ ] Verify "Discovery stopped immediately (force killed)" notification
- [ ] Check log file continues to have all output
- [ ] Verify auto-scroll works
- [ ] Verify errors show in red

### 5. Standardize All Sources

Once YP works, apply same pattern to:

**Google Discovery:**
- Create `cli_crawl_google.py`
- Update `run_google_maps_discovery()` to use subprocess
- Log file: `logs/google_scrape.log`

**HomeAdvisor Discovery:**
- Create `cli_crawl_ha.py`
- Update `run_homeadvisor_discovery()` to use subprocess
- Log file: `logs/ha_crawl.log`

## Benefits of This Approach

✅ **True instant kill** - SIGKILL process group, no waiting
✅ **Real-time logs** - All crawler output visible immediately
✅ **PID tracking** - Know exactly what's running
✅ **Clean separation** - Crawler runs independently
✅ **Easier debugging** - Can run `cli_crawl_yp.py` manually
✅ **Process isolation** - Crash won't affect dashboard

## Alternative: Keep Current Soft Cancel

If subprocess refactoring is too complex:
- Current soft cancel works (waits for batch ~20-30s)
- LiveLogViewer already shows live logs ✅
- Auto-scroll already works ✅
- Error detection already works ✅

Just need to accept ~30 second stop delay.

## Recommendation

**Complete subprocess integration** - It's 80% done:
- CLI wrapper: ✅ Done
- SubprocessRunner: ✅ Done
- LiveLogViewer: ✅ Done
- Process Manager: ✅ Done
- Integration: 🚧 20% of work remaining

The hardest parts are done. Just need to wire it up in `discover.py`.

## Next Steps

1. Modify `run_yellow_pages_discovery()` in `discover.py`
2. Test with real crawl
3. Verify instant kill works
4. Apply to Google and HA
5. Done!
