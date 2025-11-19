# Google Maps City-First GUI Integration - Implementation Guide

**Date**: 2025-11-18
**Status**: CLI Wrapper Created, UI Integration Pending

---

## ✅ Completed: CLI Wrapper

Created: `cli_crawl_google_city_first.py`

This script runs the city-first crawler as a subprocess (matching the existing Google Maps pattern).

**Test it**:
```bash
python cli_crawl_google_city_first.py --states RI --max-targets 3
```

---

## 📝 Step-by-Step UI Integration

### Step 1: Add City-First Handler Function

**Location**: `niceui/pages/discover.py` after line 826 (after `run_google_maps_discovery`)

**Code to Add**:
```python
async def run_google_maps_city_first_discovery(
    state_ids,
    max_targets,
    scrape_details,
    stats_card,
    progress_bar,
    run_button,
    stop_button
):
    """Run Google Maps city-first discovery in background with progress updates."""
    discovery_state.running = True
    discovery_state.reset()
    discovery_state.start_time = datetime.now()

    # Register job in process manager
    job_id = 'discovery_google_city_first'
    process_manager.register(job_id, 'Google City-First Discovery', log_file='logs/google_city_first.log')

    # Disable run button, enable stop button
    run_button.disable()
    stop_button.enable()

    # Start tailing log file
    if discovery_state.log_viewer:
        discovery_state.log_viewer.set_log_file('logs/google_city_first.log')
        discovery_state.log_viewer.load_last_n_lines(50)
        discovery_state.log_viewer.start_tailing()

    # Add initial log messages
    discovery_state.add_log('=' * 60, 'info')
    discovery_state.add_log('GOOGLE MAPS CITY-FIRST DISCOVERY STARTED', 'success')
    discovery_state.add_log('=' * 60, 'info')
    discovery_state.add_log(f'States: {", ".join(state_ids)}', 'info')
    discovery_state.add_log(f'Max Targets: {max_targets or "ALL"}', 'info')
    discovery_state.add_log(f'Scrape Details: {scrape_details}', 'info')
    discovery_state.add_log('-' * 60, 'info')

    # Clear stats
    stats_card.clear()
    with stats_card:
        ui.label('Running city-first discovery...').classes('text-lg font-bold')
        stat_labels = {
            'targets': ui.label('Targets: 0'),
            'businesses': ui.label('Businesses: 0'),
            'saved': ui.label('Saved: 0'),
            'captchas': ui.label('CAPTCHAs: 0')
        }

    try:
        ui.notify('Starting Google Maps city-first scraper as subprocess...', type='info')

        # Build command for subprocess
        cmd = [
            sys.executable,
            'cli_crawl_google_city_first.py',
            '--states'
        ] + state_ids

        if max_targets:
            cmd.extend(['--max-targets', str(max_targets)])

        if scrape_details:
            cmd.append('--scrape-details')
        else:
            cmd.append('--no-scrape-details')

        cmd.append('--save')

        # Create subprocess runner
        runner = SubprocessRunner(job_id, 'logs/google_city_first.log')
        discovery_state.subprocess_runner = runner

        # Start subprocess
        pid = runner.start(cmd, cwd=os.getcwd())
        ui.notify(f'City-first scraper started with PID {pid}', type='positive')

        # Update process manager with actual PID
        process_manager.update_pid(job_id, pid)

        # Wait for subprocess to complete
        while runner.is_running():
            await asyncio.sleep(1.0)

            # Update progress bar (rough estimate based on time)
            elapsed = (datetime.now() - discovery_state.start_time).total_seconds()
            # City-first: ~30 seconds per target average
            if max_targets:
                estimated_done = min(int(elapsed / 30), max_targets)
                progress_bar.value = estimated_done / max_targets
            else:
                # Indeterminate progress
                progress_bar.value = 0.5

            # Check for cancellation
            if discovery_state.is_cancelled():
                ui.notify('Killing city-first scraper process...', type='warning')
                runner.kill()
                break

        # Get final status
        status = runner.get_status()
        return_code = status['return_code']

        if return_code == 0:
            ui.notify('City-first scraper completed successfully!', type='positive')
        elif return_code == -9:
            ui.notify('City-first scraper was killed by user', type='warning')
        else:
            ui.notify(f'City-first scraper failed with code {return_code}', type='negative')

        # Parse final results from log (simplified - just show completion)
        result = {
            "targets_processed": max_targets or "all",
            "success": return_code == 0
        }

        # Calculate elapsed time
        elapsed = (datetime.now() - discovery_state.start_time).total_seconds()

        # Log final results
        discovery_state.add_log('-' * 60, 'info')
        discovery_state.add_log('CITY-FIRST DISCOVERY COMPLETED SUCCESSFULLY!', 'success')
        discovery_state.add_log(f'Duration: {elapsed:.1f}s', 'info')
        discovery_state.add_log('=' * 60, 'info')

        # Update final stats card
        stats_card.clear()
        with stats_card:
            ui.label('City-First Discovery Complete!').classes('text-lg font-bold text-green-500')
            ui.label(f'Elapsed: {elapsed:.1f}s').classes('text-sm text-gray-400')
            ui.label('Check logs for detailed results').classes('text-sm text-gray-400')

        # Progress bar to full
        progress_bar.value = 1.0

        # Show notification
        if discovery_state.cancel_requested:
            ui.notify('City-first discovery cancelled', type='warning')
        else:
            ui.notify('City-first discovery complete!', type='positive')

    except Exception as e:
        discovery_state.add_log('-' * 60, 'error')
        discovery_state.add_log('CITY-FIRST DISCOVERY FAILED!', 'error')
        discovery_state.add_log(f'Error: {str(e)}', 'error')
        discovery_state.add_log('=' * 60, 'error')

        stats_card.clear()
        with stats_card:
            ui.label('Discovery Failed').classes('text-lg font-bold text-red-500')
            ui.label(f'Error: {str(e)}').classes('text-sm text-red-400')

        ui.notify(f'City-first discovery failed: {str(e)}', type='negative')

    finally:
        # Stop tailing log file
        if discovery_state.log_viewer:
            discovery_state.log_viewer.stop_tailing()

        # Mark job as completed in process manager
        process_manager.mark_completed(job_id, success=not discovery_state.cancel_requested)

        # Re-enable run button, disable stop button
        discovery_state.running = False
        run_button.enable()
        stop_button.disable()
        progress_bar.value = 0
```

---

### Step 2: Modify `build_google_maps_ui` Function

**Location**: Line 1482 in `discover.py`

**Changes Needed**:

1. Add mode toggle after warning banner (around line 1496)
2. Add city-first controls
3. Modify start button handler

**Complete Modified Function**:
```python
def build_google_maps_ui(container):
    """Build Google Maps discovery UI in the given container."""
    with container:
        # Configuration card
        with ui.card().classes('w-full mb-4'):
            ui.label('Google Maps Configuration').classes('text-xl font-bold mb-4')

            # Warning banner
            with ui.card().classes('w-full bg-yellow-900 border-l-4 border-yellow-500 mb-4'):
                ui.label('⚠ Important: Google Maps Scraping Notes').classes('text-lg font-bold text-yellow-200')
                ui.label('• VERY SLOW: 45-90 seconds per business (conservative anti-detection delays)').classes('text-sm text-yellow-100')
                ui.label('• May trigger CAPTCHA: If detected, wait 2-4 hours before retrying').classes('text-sm text-yellow-100')
                ui.label('• Start small: Test with 1-2 businesses first').classes('text-sm text-yellow-100')
                ui.label('• Use specific locations for best results').classes('text-sm text-yellow-100')

            # MODE TOGGLE - NEW!
            ui.label('Search Mode').classes('font-semibold mb-2')
            mode_toggle = ui.toggle(
                ['Keyword Search', 'City-First Crawl'],
                value='Keyword Search'
            ).classes('mb-4')

            # Keyword Search Controls (existing)
            keyword_container = ui.column().classes('w-full')
            with keyword_container:
                ui.label('Search Query').classes('font-semibold mb-2')
                query_input = ui.input(
                    label='What to search for',
                    placeholder='e.g., pressure washing, car wash, plumber',
                    value='pressure washing'
                ).classes('w-full mb-4')

                ui.label('Location').classes('font-semibold mb-2')
                location_input = ui.input(
                    label='Where to search',
                    placeholder='e.g., Seattle, WA or Chicago, IL',
                    value='Seattle, WA'
                ).classes('w-full mb-4')

                ui.label('Max Results').classes('font-semibold mb-2')
                max_results_input = ui.number(
                    label='Maximum businesses to find',
                    value=10,
                    min=1,
                    max=50,
                    step=1
                ).classes('w-64 mb-4')
                ui.label('⚠ More results = longer time (10 businesses ≈ 7-15 minutes)').classes('text-xs text-yellow-400 mb-4')

                # Scrape details checkbox
                scrape_details_checkbox = ui.checkbox(
                    'Scrape full business details (phone, website, hours, etc.)',
                    value=True
                ).classes('mb-2')
                ui.label('Unchecking will only get basic info (faster but less data)').classes('text-xs text-gray-400')

            # City-First Controls - NEW!
            city_first_container = ui.column().classes('w-full')
            with city_first_container:
                ui.label('States to Crawl').classes('font-semibold mb-2')
                states_select = ui.select(
                    options=['RI', 'MA', 'CT', 'NH', 'VT', 'ME', 'NY', 'NJ', 'PA'],
                    multiple=True,
                    value=['RI']
                ).classes('w-full mb-4')
                ui.label('💡 Tip: Start with one small state (RI has 775 targets)').classes('text-xs text-blue-400 mb-4')

                ui.label('Max Targets').classes('font-semibold mb-2')
                max_targets_input = ui.number(
                    label='Maximum targets to process (leave empty for all)',
                    value=10,
                    min=1,
                    max=10000,
                    step=1
                ).classes('w-64 mb-4')
                ui.label('⚠ Leave empty to process ALL targets in selected states').classes('text-xs text-yellow-400 mb-4')

                # Scrape details checkbox (city-first)
                city_first_scrape_details = ui.checkbox(
                    'Scrape full business details',
                    value=True
                ).classes('mb-2')
                ui.label('Unchecking will only get basic info (faster but less data)').classes('text-xs text-gray-400')

                # Target stats display - NEW!
                with ui.card().classes('w-full bg-gray-800 border-l-4 border-blue-500 mt-4'):
                    ui.label('Target Statistics').classes('text-md font-bold text-blue-200 mb-2')
                    stats_display = ui.column().classes('w-full')

                    def refresh_target_stats():
                        """Refresh target statistics display."""
                        from niceui.backend_facade import BackendFacade
                        backend = BackendFacade()
                        stats = backend.get_google_target_stats(states_select.value)

                        stats_display.clear()
                        with stats_display:
                            ui.label(f"Total targets: {stats['total']}").classes('text-sm text-gray-300')
                            if stats['by_status']:
                                for status, count in stats['by_status'].items():
                                    color = 'text-green-400' if status == 'DONE' else 'text-blue-400' if status == 'PLANNED' else 'text-yellow-400'
                                    ui.label(f"  {status}: {count}").classes(f'text-xs {color}')

                    ui.button('Refresh Stats', on_click=refresh_target_stats, icon='refresh').classes('mt-2')
                    refresh_target_stats()  # Initial load

            # Show/hide containers based on mode
            def update_mode_visibility():
                keyword_container.set_visibility(mode_toggle.value == 'Keyword Search')
                city_first_container.set_visibility(mode_toggle.value == 'City-First Crawl')

            mode_toggle.on('update:model-value', update_mode_visibility)
            update_mode_visibility()  # Initial state

        # Stats and controls (same as before)
        with ui.card().classes('w-full mb-4'):
            ui.label('Discovery Status').classes('text-xl font-bold mb-4')

            # Stats card
            stats_card = ui.column().classes('w-full mb-4')
            with stats_card:
                ui.label('Ready to start').classes('text-lg')

            # Progress bar
            progress_bar = ui.linear_progress(value=0).classes('w-full mb-4')

            # Control buttons
            with ui.row().classes('gap-2'):
                run_button = ui.button('START DISCOVERY', icon='play_arrow', color='positive')
                stop_button = ui.button('STOP', icon='stop', color='negative')

                # Set initial button states
                if discovery_state.running:
                    run_button.disable()
                    stop_button.enable()
                else:
                    run_button.enable()
                    stop_button.disable()

        # Live output with real-time log tailing
        log_viewer = LiveLogViewer('logs/google_scrape.log', max_lines=500, auto_scroll=True)
        log_viewer.create()

        # Store references
        discovery_state.log_viewer = log_viewer
        discovery_state.log_element = None

        # Modified Run button click handler - NEW!
        async def start_discovery():
            if mode_toggle.value == 'Keyword Search':
                # Validate keyword search inputs
                if not query_input.value or not query_input.value.strip():
                    ui.notify('Please enter a search query', type='warning')
                    return
                if not location_input.value or not location_input.value.strip():
                    ui.notify('Please enter a location', type='warning')
                    return

                # Run keyword search (existing)
                await run_google_maps_discovery(
                    query_input.value.strip(),
                    location_input.value.strip(),
                    int(max_results_input.value),
                    scrape_details_checkbox.value,
                    stats_card,
                    progress_bar,
                    run_button,
                    stop_button
                )
            else:
                # Validate city-first inputs
                if not states_select.value:
                    ui.notify('Please select at least one state', type='warning')
                    return

                # Run city-first discovery (NEW!)
                await run_google_maps_city_first_discovery(
                    states_select.value,
                    int(max_targets_input.value) if max_targets_input.value else None,
                    city_first_scrape_details.value,
                    stats_card,
                    progress_bar,
                    run_button,
                    stop_button
                )

        run_button.on('click', start_discovery)
        stop_button.on('click', stop_discovery)
```

---

## 🚀 Quick Implementation Steps

1. **Add the new async function** (Step 1 code) after line 826
2. **Replace the `build_google_maps_ui` function** (Step 2 code) starting at line 1482
3. **Save the file**
4. **Restart the GUI**:
   ```bash
   lsof -ti:8080 | xargs kill -9
   source venv/bin/activate && python3 -m niceui.main
   ```

---

## ✅ Testing the Integration

1. **Open GUI**: http://127.0.0.1:8080
2. **Navigate to**: Discover tab → Google Maps
3. **Toggle to**: City-First Crawl
4. **Configure**:
   - States: RI
   - Max targets: 3
   - Scrape details: ON
5. **Click**: Refresh Stats (should show 772 PLANNED, 3 DONE)
6. **Click**: START DISCOVERY
7. **Monitor**: Live log viewer should show progress
8. **Wait**: 3 targets ≈ 2-3 minutes
9. **Verify**: Check stats again (should show 6 DONE)

---

## 📊 Expected Behavior

**Mode Toggle**:
- Keyword Search: Shows query, location, max results inputs
- City-First Crawl: Shows states selector, max targets, target stats

**Discovery Process**:
- Subprocess spawns `cli_crawl_google_city_first.py`
- Live log tail shows real-time progress
- Progress bar updates every second
- Stop button can kill subprocess
- Final stats shown on completion

**Target Stats**:
- Refreshes on button click
- Shows breakdown by status (PLANNED, DONE, etc.)
- Updates based on selected states

---

## 🎯 Next Steps After Integration

1. **Test with 10 targets**: Validate stability
2. **Monitor CAPTCHA rate**: Should remain 0%
3. **Run full RI crawl**: Process all 772 remaining targets
4. **Expand states**: Add MA, CT for broader coverage
5. **Monitor performance**: Track speed, success rate, errors

---

## 📝 Notes

- The GUI uses subprocess pattern (not direct backend_facade calls)
- CLI wrapper handles all the async/await complexity
- Log files separate: `logs/google_scrape.log` vs `logs/google_city_first.log`
- Process manager tracks both job types separately
- Mode toggle preserves existing keyword search functionality

---

**Last Updated**: 2025-11-18
**Status**: Ready to Implement
