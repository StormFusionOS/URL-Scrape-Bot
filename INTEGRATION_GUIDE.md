# Status Page Integration Guide

The Status & History page is now ready and can be integrated with your Discover and Scrape operations.

## Quick Integration

### In Discover Page (`niceui/pages/discover.py`):

Replace the `run_discovery()` function with:

```python
from ..utils import run_discover_job
from ..pages.status import add_log_line
from ..layout import layout

async def run_discovery(categories, states, pages_per_pair, ...):
    """Run discovery with CLI streaming to Status page."""

    # Show busy overlay
    layout.show_busy()

    # Callback for each line of output
    def on_line(line_type, line):
        add_log_line(line_type, line)

    # Callback when complete
    def on_complete(exit_code, duration, result):
        layout.hide_busy()
        ui.notify(result['message'],
                  type='positive' if exit_code == 0 else 'negative')
        # Update your stats_card here with result counts

    # Run the job
    await run_discover_job(
        categories=categories,
        states=states,
        pages_per_pair=pages_per_pair,
        on_line_callback=on_line,
        on_complete_callback=on_complete
    )
```

### In Scrape Page (`niceui/pages/scrape.py`):

Replace the scraping logic with:

```python
from ..utils import run_scrape_job
from ..pages.status import add_log_line
from ..layout import layout

async def start_scrape(limit, stale_days, only_missing_email, ...):
    """Run scraping with CLI streaming to Status page."""

    # Show busy overlay
    layout.show_busy()

    # Callback for each line
    def on_line(line_type, line):
        add_log_line(line_type, line)

    # Callback when complete
    def on_complete(exit_code, duration, result):
        layout.hide_busy()
        ui.notify(result['message'],
                  type='positive' if exit_code == 0 else 'negative')
        # Update your UI with result counts

    # Run the job
    await run_scrape_job(
        limit=limit,
        stale_days=stale_days,
        only_missing_email=only_missing_email,
        on_line_callback=on_line,
        on_complete_callback=on_complete
    )
```

## What This Gives You

### Live Features:
1. **Real-time output** appears in Status page as job runs
2. **Color-coded logs** (red=errors, yellow=warnings, blue=info)
3. **Auto-parsing metrics** from log lines
4. **Live throughput** calculation (items/min)
5. **Stall detection** (flags if no output for 30s)
6. **Cancel button** to terminate jobs
7. **Progress updates** in Status page

### History Features:
1. **Automatic recording** of every run in `data/history.jsonl`
2. **Searchable history** table with all past runs
3. **CSV export** with timestamps
4. **Statistics** (total runs, success/fail counts, avg duration)
5. **Persistent storage** survives app restarts

## CLI Commands Used

Discovery:
```bash
python runner/main.py --discover-only \
    --categories "pressure washing,window cleaning" \
    --states "WA,OR" \
    --pages-per-pair 2
```

Scraping:
```bash
python runner/main.py --scrape-only \
    --update-limit 100 \
    --stale-days 30 \
    --only-missing-email
```

## Testing

1. Navigate to http://127.0.0.1:8080/status
2. Click "Start Test Job" to see demo streaming
3. Go to Discover page and run a small job
4. Watch live output appear in Status page
5. Check History table after completion
6. Try Cancel button mid-run

## Event Bus Integration (Optional)

For cross-page communication:

```python
from ..router import event_bus

# When job starts
event_bus.publish('job_started', {'type': 'Discover', 'name': 'Discovery Job'})

# When job completes
event_bus.publish('job_completed', {'type': 'Discover', 'success': True})

# Other pages can subscribe
event_bus.subscribe('job_started', lambda data: ui.notify(f"Job started: {data['name']}"))
```

## Files Created

- `niceui/utils/cli_stream.py` - CLI output streaming
- `niceui/utils/history_manager.py` - Run history persistence
- `niceui/utils/job_runner.py` - Integration helpers
- `niceui/pages/status.py` - Status & History page
- `data/history.jsonl` - Auto-created history file

All set! The Status page is live and ready to receive jobs.
