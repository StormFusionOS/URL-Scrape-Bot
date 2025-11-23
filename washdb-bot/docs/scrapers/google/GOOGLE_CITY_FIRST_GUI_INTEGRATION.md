# Google Maps City-First GUI Integration Guide

**Date**: 2025-11-18
**Status**: Backend Ready, UI Integration Pending

---

## Overview

The Google Maps city-first crawler is fully implemented and tested. The backend integration is complete with two new methods in `backend_facade.py`. This guide provides step-by-step instructions for integrating the city-first crawler into the NiceGUI dashboard.

---

## Completed Components

### 1. Backend Integration (DONE)

**File**: `niceui/backend_facade.py`

**New Methods Added**:

#### `discover_google_city_first(state_ids, max_targets, scrape_details, save_to_db, cancel_flag, progress_callback)`
- **Purpose**: Run city-first Google Maps discovery
- **Parameters**:
  - `state_ids`: List of 2-letter state codes (e.g., `['RI', 'MA']`)
  - `max_targets`: Maximum targets to process (None = all)
  - `scrape_details`: Whether to scrape full business details
  - `save_to_db`: Whether to save results to database
  - `cancel_flag`: Callable that returns True to cancel
  - `progress_callback`: Callable to receive progress updates

- **Returns**:
```python
{
    "success": True,
    "targets_processed": 10,
    "total_businesses": 85,
    "saved": 80,
    "duplicates": 5,
    "captchas": 0,
    "errors": 0
}
```

- **Progress Callback Format**:
```python
{
    'type': 'progress',
    'message': 'Completed: Providence, RI - Window Cleaning',
    'target': 'Providence - Window Cleaning',
    'found': 12,
    'saved': 12,
    'duplicates': 0,
    'captcha': False,
    'total_targets': 1,
    'total_businesses': 12,
    'total_saved': 12,
    'total_duplicates': 0,
    'total_captchas': 0
}
```

#### `get_google_target_stats(state_ids=None)`
- **Purpose**: Get statistics about city-first targets
- **Parameters**:
  - `state_ids`: Optional state filter

- **Returns**:
```python
{
    "total": 775,
    "by_status": {
        "DONE": 3,
        "PLANNED": 772
    },
    "by_priority": {
        1: 200,  # High
        2: 400,  # Medium
        3: 175   # Low
    },
    "states": ['RI']
}
```

---

## UI Integration Steps

### Step 1: Add UI Controls to `discover.py`

**Location**: Around line 500-700 (Google Maps section)

**Required UI Elements**:

1. **Mode Toggle** (Radio buttons or dropdown):
   ```python
   ui.label('Google Maps Search Mode').classes('text-lg font-semibold')
   mode = ui.radio(
       ['Keyword Search', 'City-First Crawl'],
       value='Keyword Search'
   ).props('inline')
   ```

2. **City-First Controls** (visible when City-First mode selected):
   ```python
   with ui.column().bind_visibility_from(mode, 'value', value='City-First Crawl'):
       # State selector
       ui.label('States to Crawl')
       states_select = ui.select(
           ['RI', 'MA', 'CT', 'NH', 'VT', 'ME'],  # New England states
           multiple=True,
           value=['RI']
       )

       # Max targets limiter
       ui.label('Max Targets (leave empty for all)')
       max_targets_input = ui.number(
           'Max targets',
           value=None,
           min=1,
           max=10000
       )

       # Scrape details toggle
       scrape_details_switch = ui.switch(
           'Scrape detailed business info',
           value=True
       )

       # Save to DB toggle
       save_to_db_switch = ui.switch(
           'Save results to database',
           value=True
       )
   ```

3. **Target Statistics Display**:
   ```python
   with ui.card():
       ui.label('Current Target Status').classes('text-md font-semibold')
       stats_container = ui.column()

       def refresh_stats():
           stats = backend.get_google_target_stats(states_select.value)
           stats_container.clear()
           with stats_container:
               ui.label(f"Total targets: {stats['total']}")
               ui.label(f"Planned: {stats['by_status'].get('PLANNED', 0)}")
               ui.label(f"Done: {stats['by_status'].get('DONE', 0)}")
               ui.label(f"In Progress: {stats['by_status'].get('IN_PROGRESS', 0)}")

       ui.button('Refresh Stats', on_click=refresh_stats)
       refresh_stats()  # Initial load
   ```

### Step 2: Modify Start Button Handler

**Current**: Calls `backend.discover_google(query, location, ...)`

**Updated**: Check mode and call appropriate method

```python
def on_start_google():
    if mode.value == 'Keyword Search':
        # Existing keyword search logic
        result = backend.discover_google(
            query=query_input.value,
            location=location_input.value,
            max_results=max_results_input.value,
            scrape_details=scrape_details_switch.value,
            cancel_flag=lambda: cancel_flag,
            progress_callback=update_progress
        )
    else:
        # New city-first logic
        result = backend.discover_google_city_first(
            state_ids=states_select.value,
            max_targets=max_targets_input.value,
            scrape_details=scrape_details_switch.value,
            save_to_db=save_to_db_switch.value,
            cancel_flag=lambda: cancel_flag,
            progress_callback=update_city_first_progress
        )

    # Update UI with results
    show_results(result)
```

### Step 3: Add Progress Display for City-First

**Progress callback** needs to handle city-first specific fields:

```python
def update_city_first_progress(progress_data):
    """Update progress display for city-first crawling."""
    # Update progress bar
    progress_bar.set_value(
        progress_data['total_targets'] / total_expected_targets
    )

    # Update status message
    status_label.set_text(progress_data['message'])

    # Update statistics
    stats_display.clear()
    with stats_display:
        ui.label(f"Targets processed: {progress_data['total_targets']}")
        ui.label(f"Total businesses: {progress_data['total_businesses']}")
        ui.label(f"Saved: {progress_data['total_saved']}")
        ui.label(f"Duplicates: {progress_data['total_duplicates']}")

        if progress_data['total_captchas'] > 0:
            ui.label(f"⚠️ CAPTCHAs: {progress_data['total_captchas']}")
            .classes('text-orange-600')
```

### Step 4: Add Results Display

**After completion**, show summary:

```python
def show_city_first_results(result):
    """Display city-first crawl results."""
    with ui.card():
        ui.label('City-First Crawl Complete').classes('text-xl font-bold')

        ui.label(f"✓ Targets processed: {result['targets_processed']}")
        ui.label(f"✓ Businesses found: {result['total_businesses']}")
        ui.label(f"✓ Saved to database: {result['saved']}")
        ui.label(f"✓ Duplicates skipped: {result['duplicates']}")

        if result['captchas'] > 0:
            ui.label(f"⚠️ CAPTCHAs detected: {result['captchas']}")
            .classes('text-orange-600')

        if result['errors'] > 0:
            ui.label(f"❌ Errors: {result['errors']}")
            .classes('text-red-600')

        # Refresh target stats
        refresh_stats()
```

---

## Testing the Integration

### 1. Unit Test

```python
# Test backend method directly
from niceui.backend_facade import BackendFacade

backend = BackendFacade()

# Get stats
stats = backend.get_google_target_stats(['RI'])
print(f"Total RI targets: {stats['total']}")

# Run small test
result = backend.discover_google_city_first(
    state_ids=['RI'],
    max_targets=3,
    scrape_details=True,
    save_to_db=False
)
print(f"Result: {result}")
```

### 2. GUI Test

1. Start the dashboard: `python -m niceui.main`
2. Navigate to Discover page
3. Select "City-First Crawl" mode
4. Select "RI" state
5. Set max targets to 3
6. Click "Start"
7. Verify progress updates appear
8. Verify final results display correctly
9. Verify target stats update

### 3. End-to-End Test

1. Generate targets for a new state:
   ```bash
   python -m scrape_google.generate_city_targets --states CT
   ```

2. Run city-first crawl from GUI for CT

3. Verify:
   - Progress updates in real-time
   - Businesses saved to database
   - Target statuses updated
   - No CAPTCHAs detected
   - Stats refresh correctly

---

## Integration Checklist

- [ ] Add mode toggle (Keyword Search vs City-First)
- [ ] Add state selector (multi-select dropdown)
- [ ] Add max targets input
- [ ] Add scrape details toggle
- [ ] Add save to DB toggle
- [ ] Add target statistics display with refresh button
- [ ] Modify start button to check mode
- [ ] Add city-first progress callback
- [ ] Add city-first results display
- [ ] Test backend methods directly
- [ ] Test GUI integration with 3 targets
- [ ] Test end-to-end with new state
- [ ] Document usage for end users

---

## Example Usage Workflows

### Workflow 1: Test Run (3 targets)
1. Mode: City-First Crawl
2. States: RI
3. Max targets: 3
4. Scrape details: ON
5. Save to DB: OFF (testing)
6. Click Start
7. Review results
8. If successful, rerun with Save to DB: ON

### Workflow 2: Full State Crawl
1. Mode: City-First Crawl
2. States: RI
3. Max targets: (empty = all 775)
4. Scrape details: ON
5. Save to DB: ON
6. Click Start
7. Monitor progress
8. Expected runtime: ~19 hours for 775 targets

### Workflow 3: Multi-State Crawl
1. Generate targets first:
   ```bash
   python -m scrape_google.generate_city_targets --states RI MA CT
   ```
2. Mode: City-First Crawl
3. States: RI, MA, CT
4. Max targets: (empty = all)
5. Scrape details: ON
6. Save to DB: ON
7. Click Start

---

## Production Deployment Notes

### Monitoring

- Watch CAPTCHA rate: If >5%, pause and increase delays
- Monitor success rate: Should be >95%
- Check database growth: ~10-15 businesses per target average

### Performance Tuning

- **Delays**: Currently 10-20s between targets (conservative)
- **Session breaks**: Every 50 requests (30-90s break)
- **Checkpoint interval**: Every 10 targets

### Scaling

- Single worker tested and validated
- Multi-worker support built-in (claimed_by, heartbeat fields)
- Can run multiple instances with different state_ids
- Orphan recovery handles crashes gracefully

---

## Files Modified

1. **niceui/backend_facade.py** (DONE)
   - Added `discover_google_city_first()` method
   - Added `get_google_target_stats()` method
   - Added imports for city-first crawler

2. **niceui/pages/discover.py** (PENDING)
   - Needs mode toggle
   - Needs city-first UI controls
   - Needs modified start handler
   - Needs progress/results display

---

## Support & Troubleshooting

### Common Issues

**Issue**: No targets found
- **Solution**: Run `python -m scrape_google.generate_city_targets --states <STATE>`

**Issue**: CAPTCHA detected
- **Solution**: Increase delays in google_stealth.py, add residential proxies

**Issue**: Targets stuck in IN_PROGRESS
- **Solution**: Orphan recovery runs automatically (60min timeout), or manually:
  ```sql
  UPDATE google_targets
  SET status='PLANNED', claimed_by=NULL
  WHERE status='IN_PROGRESS' AND heartbeat_at < NOW() - INTERVAL '60 minutes';
  ```

**Issue**: Duplicate businesses
- **Solution**: Working as designed - deduplication by place_id and domain

---

## Next Development Steps

After GUI integration:

1. **Monitoring System** (Phase 4):
   - Create `scrape_google/google_monitor.py`
   - Implement adaptive rate limiting
   - Add health checks and alerts

2. **Multi-State Expansion**:
   - Generate targets for all New England states
   - Run parallel crawls with different workers
   - Monitor aggregate performance

3. **Residential Proxy Integration**:
   - Add proxy rotation if CAPTCHA rate >5%
   - Integrate with proxy providers (Bright Data, Oxylabs, etc.)

4. **Advanced Features**:
   - Scheduled crawls (cron integration)
   - Email notifications on completion
   - Automatic retry of failed targets
   - Export results to CSV/JSON

---

**Last Updated**: 2025-11-18
**Status**: Ready for UI Integration
