# Live Output & Instant Kill - Implementation Guide

## Overview
This guide provides step-by-step instructions for integrating the LiveLogViewer and ProcessManager infrastructure into the discovery pages.

## Phase 1: Discovery Page (YP/HA) - Highest Priority

### Files to Modify:
- `niceui/pages/discover.py`
- `niceui/backend_facade.py`

### Step 1.1: Add LiveLogViewer to Discovery Page

**Location:** `niceui/pages/discover.py` - In the `discover_page()` function

**Find this section** (around line 300-350):
```python
# Live output log
with ui.card().classes('w-full'):
    ui.label('Live Output').classes('text-xl font-bold mb-4')

    with ui.scroll_area().classes('w-full h-96 bg-gray-900 rounded'):
        discovery_state.log_element = ui.column().classes('w-full p-4')
```

**Replace with:**
```python
# Live output log with real-time tailing
from ..widgets.live_log_viewer import LiveLogViewer

log_viewer = LiveLogViewer('logs/yp_crawl.log', max_lines=500, auto_scroll=True)
log_viewer.create()

# Store reference
discovery_state.log_viewer = log_viewer
```

### Step 1.2: Start Tailing When Job Starts

**Location:** `niceui/pages/discover.py` - In `run_yellow_pages_discovery()` function

**Find this section** (around line 95-100):
```python
discovery_state.running = True
discovery_state.reset()
discovery_state.start_time = datetime.now()

# Disable run button, enable stop button
run_button.disable()
stop_button.enable()
```

**Add after:**
```python
# Start tailing log file
if hasattr(discovery_state, 'log_viewer') and discovery_state.log_viewer:
    discovery_state.log_viewer.load_last_n_lines(50)  # Load last 50 lines first
    discovery_state.log_viewer.start_tailing()
```

### Step 1.3: Stop Tailing When Job Ends

**Location:** `niceui/pages/discover.py` - In `run_yellow_pages_discovery()` function

**Find the finally block** (around line 250):
```python
finally:
    discovery_state.running = False

    # Re-enable run button
    run_button.enable()
    stop_button.disable()
```

**Add before re-enabling buttons:**
```python
# Stop tailing log file
if hasattr(discovery_state, 'log_viewer') and discovery_state.log_viewer:
    discovery_state.log_viewer.stop_tailing()
```

### Step 1.4: Add Process Tracking

**Location:** `niceui/pages/discover.py` - At the top with imports

**Add:**
```python
from ..utils.process_manager import process_manager
```

**In `run_yellow_pages_discovery()`** - After discovery_state.running = True:
```python
# Register job in process manager
job_id = 'discovery_yp'
process_manager.register(job_id, 'YP Discovery', log_file='logs/yp_crawl.log')
```

**Before calling backend.discover** - Wrap the call to capture any process info:
```python
# Note: backend.discover runs synchronously, so we can't capture PID easily
# For now, we'll use the cancel flag mechanism
```

### Step 1.5: Strengthen Stop Button - INSTANT KILL

**Location:** `niceui/pages/discover.py` - Find the stop button click handler

**Find:**
```python
ui.button(
    'Stop',
    icon='stop',
    color='negative',
    on_click=lambda: discovery_state.cancel()
).props('outline')
```

**Replace with:**
```python
async def force_stop_discovery():
    """Force stop the discovery job immediately."""
    # Set cancel flag (soft stop)
    discovery_state.cancel()

    # Try to kill via process manager (hard stop)
    killed = process_manager.kill('discovery_yp', force=True)

    if killed:
        ui.notify('Discovery stopped immediately (force killed)', type='warning')
    else:
        ui.notify('Stop requested - waiting for current batch to finish', type='info')

    # Stop log tailing
    if hasattr(discovery_state, 'log_viewer') and discovery_state.log_viewer:
        discovery_state.log_viewer.stop_tailing()

ui.button(
    'Stop',
    icon='stop',
    color='negative',
    on_click=force_stop_discovery
).props('outline')
```

---

## Phase 2: Backend Process Tracking (For True Instant Kill)

### Problem:
Currently, `backend.discover()` runs in `run.io_bound()` which doesn't expose the actual subprocess PID.

### Solution:
Run discovery as an actual subprocess that we can track.

**Location:** `niceui/backend_facade.py`

**Add method:**
```python
def discover_with_pid(self, categories, states, pages_per_pair, cancel_flag, progress_callback, providers):
    """
    Run discovery and return the subprocess so caller can track PID.

    This is a wrapper that spawns the actual crawler as a subprocess.
    """
    import subprocess
    import json

    # Build command
    cmd = [
        'python', '-m', 'scrape_yp.yp_crawl',
        '--categories', ','.join(categories),
        '--states', ','.join(states),
        '--limit-per-state', str(pages_per_pair)
    ]

    # Start subprocess
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,  # Create process group
        bufsize=1,
        universal_newlines=True
    )

    return process
```

**Note:** This requires refactoring how discovery works. For Phase 1, we'll use the cancel_flag mechanism which is good enough for testing.

---

## Phase 3: Google Discovery Page

### Files to Modify:
- `niceui/pages/discover_google.py`

**Follow same pattern as Phase 1, but:**
- Use `logs/google_scrape.log` as log file
- Job ID: `'discovery_google'`
- Job type: `'Google Discovery'`

---

## Phase 4: Logs Page Auto-Tailing

### Files to Modify:
- `niceui/pages/logs.py`

### Step 4.1: Detect Active Jobs

**Location:** `niceui/pages/logs.py` - In `logs_page()` function

**Add at the top:**
```python
from ..utils.process_manager import process_manager

# Check for active jobs
active_jobs = process_manager.get_running()
```

### Step 4.2: Auto-Tail Active Job Logs

**After log file grid:**
```python
# Active jobs section
if active_jobs:
    with ui.card().classes('w-full mb-4 border-2 border-green-500'):
        ui.label('🟢 Active Jobs').classes('text-xl font-bold mb-2 text-green-400')

        for job_id, proc_info in active_jobs.items():
            with ui.row().classes('w-full items-center gap-4'):
                ui.badge('LIVE', color='positive').classes('animate-pulse')
                ui.label(f"{proc_info.job_type} (PID: {proc_info.pid})").classes('font-semibold')
                ui.label(f"Log: {proc_info.log_file}").classes('text-sm text-gray-400')

                ui.button(
                    'View Live',
                    icon='visibility',
                    on_click=lambda f=proc_info.log_file: switch_log_file(f) or ui.notify('Auto-tailing started', type='positive') or toggle_tail()
                ).props('outline size=sm color=positive')

                ui.button(
                    'Kill Job',
                    icon='stop',
                    on_click=lambda j=job_id: process_manager.kill(j, force=True) and ui.notify(f'Killed {j}', type='warning')
                ).props('flat size=sm color=negative')
```

### Step 4.3: Auto-Start Tailing for Active Jobs

**After creating log_element:**
```python
# Auto-start tailing if there are active jobs
if active_jobs and log_state.current_log_file in [proc.log_file for proc in active_jobs.values()]:
    toggle_tail()  # Start tailing automatically
```

---

## Phase 5: Testing Checklist

### Test Discovery (YP):
1. ✅ Start discovery - verify log viewer shows real-time output
2. ✅ Click Stop during crawl - verify it stops IMMEDIATELY
3. ✅ Check logs page - verify active job appears with LIVE badge
4. ✅ Verify color coding works (errors=red, success=green, etc.)

### Test Google Discovery:
1. ✅ Start Google discovery - verify log viewer works
2. ✅ Click Stop - verify instant termination
3. ✅ Check logs page shows active Google job

### Test Logs Page:
1. ✅ Start a discovery job
2. ✅ Navigate to logs page - verify LIVE badge appears
3. ✅ Click "View Live" - verify auto-tailing starts
4. ✅ Click "Kill Job" - verify job stops immediately

---

## Quick Reference: Key Components

### LiveLogViewer Usage:
```python
from niceui.widgets.live_log_viewer import LiveLogViewer

viewer = LiveLogViewer('logs/yp_crawl.log', max_lines=500, auto_scroll=True)
viewer.create()  # Creates UI
viewer.load_last_n_lines(50)  # Load history
viewer.start_tailing()  # Start live updates
viewer.stop_tailing()  # Stop updates
```

### ProcessManager Usage:
```python
from niceui.utils.process_manager import process_manager

# Register job
process_manager.register('job_id', 'Job Type', pid=12345, log_file='logs/job.log')

# Kill job (instant)
process_manager.kill('job_id', force=True)

# Check if cancelled
if process_manager.is_cancelled('job_id'):
    # Stop processing

# Get all active jobs
active = process_manager.get_running()
```

---

## Benefits After Implementation:

1. **More CLI Output**: Every log line from crawlers visible in real-time
2. **Instant Stop**: Stop button kills process immediately via SIGKILL
3. **Stall Detection**: Can see if crawler is actually working or stuck
4. **Better Debugging**: Logs page shows live output from active jobs
5. **Standardized**: Same viewer across all discovery sources
6. **Testing-Friendly**: Can quickly stop and restart during development

---

## Priority Order:

1. **Phase 1** (Highest) - Discovery page with YP/HA
2. **Phase 4** (High) - Logs page auto-tailing
3. **Phase 3** (Medium) - Google discovery page
4. **Phase 2** (Low) - Backend subprocess tracking (optional enhancement)

Start with Phase 1 for immediate testing benefits!
