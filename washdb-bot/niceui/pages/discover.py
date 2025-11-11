"""
Discovery page - configure and run URL discovery from multiple sources with real-time progress.
"""

from nicegui import ui, run
from ..backend_facade import backend
from datetime import datetime
import asyncio


# Global state for discovery
class DiscoveryState:
    def __init__(self):
        self.running = False
        self.cancel_requested = False
        self.last_run_summary = None
        self.start_time = None
        self.log_element = None

    def cancel(self):
        self.cancel_requested = True

    def is_cancelled(self):
        return self.cancel_requested

    def reset(self):
        self.cancel_requested = False

    def add_log(self, message, level='info'):
        """Add a log message to the output window."""
        if not self.log_element:
            return

        # Color coding based on level
        color_map = {
            'info': 'text-blue-400',
            'success': 'text-green-400',
            'warning': 'text-yellow-400',
            'error': 'text-red-400',
            'debug': 'text-gray-400',
            'searching': 'text-cyan-400',
            'processing': 'text-purple-400',
            'scraping': 'text-yellow-300',
            'saved': 'text-green-300'
        }

        color = color_map.get(level, 'text-white')
        timestamp = datetime.now().strftime('%H:%M:%S')

        with self.log_element:
            ui.label(f'[{timestamp}] {message}').classes(f'{color} leading-tight')


discovery_state = DiscoveryState()


# Service categories
DEFAULT_CATEGORIES = [
    "pressure washing",
    "power washing",
    "soft washing",
    "window cleaning",
    "gutter cleaning",
    "roof cleaning",
    "deck cleaning",
    "concrete cleaning",
    "house cleaning exterior",
    "driveway cleaning",
]

# US States
ALL_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]


async def run_yellow_pages_discovery(
    categories,
    states,
    pages_per_pair,
    stats_card,
    progress_bar,
    run_button,
    stop_button
):
    """Run Yellow Pages discovery in background with progress updates."""
    discovery_state.running = True
    discovery_state.reset()
    discovery_state.start_time = datetime.now()

    # Disable run button, enable stop button
    run_button.disable()
    stop_button.enable()

    # Clear log
    if discovery_state.log_element:
        discovery_state.log_element.clear()

    # Add initial log messages
    discovery_state.add_log('=' * 60, 'info')
    discovery_state.add_log('Starting Yellow Pages Discovery', 'info')
    discovery_state.add_log('=' * 60, 'info')
    discovery_state.add_log(f'Categories: {", ".join(categories)}', 'info')
    discovery_state.add_log(f'States: {", ".join(states)}', 'info')
    discovery_state.add_log(f'Pages per pair: {pages_per_pair}', 'info')
    discovery_state.add_log(f'Total pairs: {len(categories)} × {len(states)} = {len(categories) * len(states)}', 'info')
    discovery_state.add_log('-' * 60, 'info')

    # Clear stats
    stats_card.clear()
    with stats_card:
        ui.label('Running discovery...').classes('text-lg font-bold')
        stat_labels = {
            'found': ui.label('Found: 0'),
            'new': ui.label('New: 0'),
            'updated': ui.label('Updated: 0'),
            'errors': ui.label('Errors: 0'),
            'progress': ui.label('Progress: 0/0 pairs')
        }

    try:
        discovery_state.add_log('Starting Yellow Pages crawler...', 'info')

        # Progress callback to update UI in real-time
        def progress_callback(progress):
            """Handle progress updates from backend."""
            progress_type = progress.get('type')

            if progress_type == 'batch_start':
                category = progress.get('category', '')
                state = progress.get('state', '')
                pairs_done = progress.get('pairs_done', 0)
                pairs_total = progress.get('pairs_total', 0)
                discovery_state.add_log(
                    f"Processing pair {pairs_done}/{pairs_total}: {category} × {state}",
                    'info'
                )

            elif progress_type == 'batch_complete':
                category = progress.get('category', '')
                state = progress.get('state', '')
                found = progress.get('found', 0)
                new = progress.get('new', 0)
                updated = progress.get('updated', 0)
                discovery_state.add_log(
                    f"✓ {category} × {state}: Found {found}, New {new}, Updated {updated}",
                    'success'
                )

                # Update stats card with current totals
                totals = progress.get('totals', {})
                stat_labels['found'].set_text(f"Found: {totals.get('found', 0)}")
                stat_labels['new'].set_text(f"New: {totals.get('new', 0)}")
                stat_labels['updated'].set_text(f"Updated: {totals.get('updated', 0)}")
                stat_labels['errors'].set_text(f"Errors: {totals.get('errors', 0)}")

                # Update progress bar
                pairs_done = progress.get('pairs_done', 0)
                pairs_total = progress.get('pairs_total', 1)
                progress_bar.value = pairs_done / pairs_total
                stat_labels['progress'].set_text(f"Progress: {pairs_done}/{pairs_total} pairs")

            elif progress_type == 'error':
                error_msg = progress.get('error', 'Unknown error')
                discovery_state.add_log(f"✗ Error: {error_msg}", 'error')

            # Check if cancelled
            if discovery_state.is_cancelled():
                discovery_state.add_log('Cancellation requested, stopping...', 'warning')
                return True  # Signal to stop

            return False

        # Run discovery through backend
        result = await run.io_bound(
            backend.discover_yellow_pages,
            categories,
            states,
            pages_per_pair,
            progress_callback
        )

        discovery_state.add_log('Crawler completed!', 'success')

        # Update final stats
        elapsed = (datetime.now() - discovery_state.start_time).total_seconds()

        # Log final results
        discovery_state.add_log('-' * 60, 'info')
        discovery_state.add_log('Discovery Complete!', 'success')
        discovery_state.add_log(f'Elapsed time: {elapsed:.1f}s', 'info')
        discovery_state.add_log(f'Found: {result["found"]} businesses', 'success')
        discovery_state.add_log(f'New: {result["new"]} businesses added', 'success')
        discovery_state.add_log(f'Updated: {result["updated"]} businesses updated', 'info')
        discovery_state.add_log(f'Errors: {result["errors"]}', 'error' if result["errors"] > 0 else 'info')
        discovery_state.add_log(f'Pairs processed: {result["pairs_done"]}/{result["pairs_total"]}', 'info')
        discovery_state.add_log('=' * 60, 'info')

        stats_card.clear()
        with stats_card:
            ui.label('Discovery Complete!').classes('text-lg font-bold text-green-500')
            ui.label(f'Elapsed: {elapsed:.1f}s').classes('text-sm text-gray-400')
            ui.separator()
            ui.label(f'Found: {result["found"]}').classes('text-lg')
            ui.label(f'New: {result["new"]}').classes('text-lg text-green-500')
            ui.label(f'Updated: {result["updated"]}').classes('text-lg text-blue-500')
            ui.label(f'Errors: {result["errors"]}').classes('text-lg text-red-500')
            ui.label(f'Pairs: {result["pairs_done"]}/{result["pairs_total"]}').classes('text-sm')

        # Update progress bar
        if result["pairs_total"] > 0:
            progress_bar.value = result["pairs_done"] / result["pairs_total"]

        # Store summary
        discovery_state.last_run_summary = {
            'source': 'yellow_pages',
            'elapsed': elapsed,
            'result': result,
            'timestamp': discovery_state.start_time.isoformat()
        }

        # Show notification
        if discovery_state.cancel_requested:
            ui.notify('Discovery cancelled', type='warning')
        else:
            ui.notify(
                f'Discovery complete! Found {result["found"]}, New {result["new"]}',
                type='positive'
            )

    except Exception as e:
        discovery_state.add_log('-' * 60, 'error')
        discovery_state.add_log('Discovery Failed!', 'error')
        discovery_state.add_log(f'Error: {str(e)}', 'error')
        discovery_state.add_log('=' * 60, 'error')

        stats_card.clear()
        with stats_card:
            ui.label('Discovery Failed').classes('text-lg font-bold text-red-500')
            ui.label(f'Error: {str(e)}').classes('text-sm text-red-400')

        ui.notify(f'Discovery failed: {str(e)}', type='negative')

    finally:
        # Re-enable run button, disable stop button
        discovery_state.running = False
        run_button.enable()
        stop_button.disable()
        progress_bar.value = 0


async def run_google_maps_discovery(
    query,
    location,
    max_results,
    scrape_details,
    stats_card,
    progress_bar,
    run_button,
    stop_button
):
    """Run Google Maps discovery in background with progress updates."""
    discovery_state.running = True
    discovery_state.reset()
    discovery_state.start_time = datetime.now()

    # Disable run button, enable stop button
    run_button.disable()
    stop_button.enable()

    # Clear log
    if discovery_state.log_element:
        discovery_state.log_element.clear()

    # Add initial log messages
    discovery_state.add_log('=' * 60, 'info')
    discovery_state.add_log('GOOGLE MAPS DISCOVERY STARTED', 'success')
    discovery_state.add_log('=' * 60, 'info')
    discovery_state.add_log(f'Query: {query}', 'info')
    discovery_state.add_log(f'Location: {location or "Not specified"}', 'info')
    discovery_state.add_log(f'Max Results: {max_results}', 'info')
    discovery_state.add_log(f'Scrape Details: {scrape_details}', 'info')
    discovery_state.add_log('-' * 60, 'info')

    # Progress callback
    def update_progress(progress_data):
        """Handle progress updates from backend."""
        msg_type = progress_data.get('type', 'info')
        message = progress_data.get('message', '')

        # Log the message
        discovery_state.add_log(message, msg_type)

        # Update stats card
        stats_card.clear()
        with stats_card:
            ui.label('Running Google Maps Discovery...').classes('text-lg font-bold')
            ui.separator()
            if 'found' in progress_data:
                ui.label(f"Found: {progress_data['found']}").classes('text-lg')
            if 'saved' in progress_data:
                ui.label(f"Saved: {progress_data['saved']}").classes('text-lg text-green-500')
            if 'duplicates' in progress_data:
                ui.label(f"Duplicates: {progress_data['duplicates']}").classes('text-lg text-yellow-500')
            if 'errors' in progress_data:
                ui.label(f"Errors: {progress_data['errors']}").classes('text-lg text-red-500')

        # Check if cancelled
        if discovery_state.is_cancelled():
            discovery_state.add_log('Cancellation requested, stopping...', 'warning')
            return True

        return False

    try:
        discovery_state.add_log('Starting Google Maps scraper...', 'info')
        discovery_state.add_log(f'Searching for \'{query}\' in \'{location}\'...', 'searching')

        # Clear stats
        stats_card.clear()
        with stats_card:
            ui.label('Initializing...').classes('text-lg font-bold')

        # Run discovery through backend
        result = await run.io_bound(
            backend.discover_google,
            query,
            location,
            max_results,
            scrape_details,
            update_progress
        )

        # Calculate elapsed time
        elapsed = (datetime.now() - discovery_state.start_time).total_seconds()

        # Log final results
        discovery_state.add_log('-' * 60, 'info')
        discovery_state.add_log('GOOGLE DISCOVERY COMPLETED SUCCESSFULLY!', 'success')
        discovery_state.add_log(f'Duration: {elapsed:.1f}s', 'info')
        discovery_state.add_log(f'Found: {result["found"]} businesses', 'success')
        discovery_state.add_log(f'Saved: {result["saved"]} new businesses', 'success')
        discovery_state.add_log(f'Duplicates: {result["duplicates"]} skipped', 'warning')
        discovery_state.add_log('=' * 60, 'info')

        # Update final stats card
        stats_card.clear()
        with stats_card:
            ui.label('Discovery Complete!').classes('text-lg font-bold text-green-500')
            ui.label(f'Elapsed: {elapsed:.1f}s').classes('text-sm text-gray-400')
            ui.separator()
            ui.label(f'Found: {result["found"]}').classes('text-lg')
            ui.label(f'Saved: {result["saved"]}').classes('text-lg text-green-500')
            ui.label(f'Duplicates: {result["duplicates"]}').classes('text-lg text-yellow-500')

        # Progress bar to full
        progress_bar.value = 1.0

        # Store summary
        discovery_state.last_run_summary = {
            'source': 'google_maps',
            'elapsed': elapsed,
            'result': result,
            'timestamp': discovery_state.start_time.isoformat()
        }

        # Show notification
        if discovery_state.cancel_requested:
            ui.notify('Google discovery cancelled', type='warning')
        else:
            ui.notify(
                f'Google discovery complete! Found {result["found"]}, Saved {result["saved"]}',
                type='positive'
            )

    except Exception as e:
        discovery_state.add_log('-' * 60, 'error')
        discovery_state.add_log('GOOGLE DISCOVERY FAILED!', 'error')
        discovery_state.add_log(f'Error: {str(e)}', 'error')
        discovery_state.add_log('=' * 60, 'error')

        stats_card.clear()
        with stats_card:
            ui.label('Discovery Failed').classes('text-lg font-bold text-red-500')
            ui.label(f'Error: {str(e)}').classes('text-sm text-red-400')

        ui.notify(f'Google discovery failed: {str(e)}', type='negative')

    finally:
        # Re-enable run button, disable stop button
        discovery_state.running = False
        run_button.enable()
        stop_button.disable()
        progress_bar.value = 0


def stop_discovery():
    """Stop the running discovery."""
    if discovery_state.running:
        discovery_state.cancel()
        ui.notify('Cancelling discovery...', type='warning')


async def export_last_run():
    """Export the results from the last discovery run."""
    if not discovery_state.last_run_summary:
        ui.notify('No discovery run to export', type='warning')
        return

    summary = discovery_state.last_run_summary
    timestamp = summary['timestamp'][:19].replace(':', '-').replace(' ', '_')
    source = summary.get('source', 'unknown')
    filename = f'discovery_{source}_{timestamp}.json'

    try:
        # Export summary as JSON
        import json
        import tempfile
        import os

        temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        json.dump(summary, temp_file, indent=2)
        temp_file.close()

        ui.download(temp_file.name, filename)
        ui.notify(f'Exported discovery results to {filename}', type='positive')

        # Clean up temp file after a delay
        await asyncio.sleep(5)
        try:
            os.unlink(temp_file.name)
        except:
            pass

    except Exception as e:
        ui.notify(f'Export failed: {str(e)}', type='negative')


async def export_new_urls():
    """Export new URLs from last 7 days."""
    ui.notify('Exporting new URLs...', type='info')

    try:
        result = await run.io_bound(
            backend.export_new_urls,
            days=7,
            out_csv='data/new_urls.csv',
            out_jsonl='data/new_urls.jsonl'
        )

        if result['count'] > 0:
            ui.notify(
                f'Exported {result["count"]} URLs to {result["csv"]}',
                type='positive'
            )
            # Download the file
            ui.download(result['csv'])
        else:
            ui.notify('No new URLs in last 7 days', type='warning')

    except Exception as e:
        ui.notify(f'Export failed: {str(e)}', type='negative')


def build_yellow_pages_ui(container):
    """Build Yellow Pages discovery UI in the given container."""
    with container:
        # Configuration card
        with ui.card().classes('w-full mb-4'):
            ui.label('Yellow Pages Configuration').classes('text-xl font-bold mb-4')

            # Category selection
            ui.label('Business Categories').classes('font-semibold mb-2')
            ui.label('Select categories to search (click to toggle):').classes('text-sm text-gray-400 mb-2')

            category_checkboxes = {}
            with ui.grid(columns=3).classes('w-full gap-2 mb-4'):
                for cat in DEFAULT_CATEGORIES:
                    category_checkboxes[cat] = ui.checkbox(cat, value=True).classes('text-sm')

            # Quick select buttons
            with ui.row().classes('gap-2 mb-4'):
                def select_all_categories():
                    for cb in category_checkboxes.values():
                        cb.value = True

                def deselect_all_categories():
                    for cb in category_checkboxes.values():
                        cb.value = False

                ui.button('Select All', icon='check_box', on_click=select_all_categories).props('flat dense')
                ui.button('Deselect All', icon='check_box_outline_blank', on_click=deselect_all_categories).props('flat dense')

            ui.separator()

            # State selection
            ui.label('US States').classes('font-semibold mb-2 mt-4')
            ui.label('Select states to search (click to toggle):').classes('text-sm text-gray-400 mb-2')

            state_checkboxes = {}
            with ui.grid(columns=10).classes('w-full gap-1 mb-4'):
                for state in ALL_STATES:
                    state_checkboxes[state] = ui.checkbox(state, value=False).classes('text-xs')

            # Quick select buttons
            with ui.row().classes('gap-2 mb-4'):
                def select_all_states():
                    for cb in state_checkboxes.values():
                        cb.value = True

                def deselect_all_states():
                    for cb in state_checkboxes.values():
                        cb.value = False

                ui.button('Select All', icon='check_box', on_click=select_all_states).props('flat dense')
                ui.button('Deselect All', icon='check_box_outline_blank', on_click=deselect_all_states).props('flat dense')

            ui.separator()

            # Pages per pair
            ui.label('Crawl Settings').classes('font-semibold mb-2 mt-4')
            pages_input = ui.number(
                label='Pages per category/state pair',
                value=1,
                min=1,
                max=10,
                step=1
            ).classes('w-64')
            ui.label('⚠ More pages = more URLs but slower crawling').classes('text-xs text-yellow-400')

        # Stats and controls
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
                stop_button = ui.button('STOP', icon='stop', color='negative').props('disable')
                ui.button('Export Last Run', icon='download', on_click=export_last_run).classes('ml-auto')
                ui.button('Export New URLs', icon='file_download', on_click=export_new_urls)

        # Live output
        with ui.card().classes('w-full'):
            ui.label('Live Output').classes('text-xl font-bold mb-4')
            log_container = ui.column().classes('w-full h-96 overflow-y-auto bg-gray-900 p-4 rounded')
            discovery_state.log_element = log_container

        # Run button click handler
        async def start_discovery():
            # Get selected categories and states
            selected_categories = [cat for cat, cb in category_checkboxes.items() if cb.value]
            selected_states = [state for state, cb in state_checkboxes.items() if cb.value]

            # Validate
            if not selected_categories:
                ui.notify('Please select at least one category', type='warning')
                return
            if not selected_states:
                ui.notify('Please select at least one state', type='warning')
                return

            # Run Yellow Pages discovery
            await run_yellow_pages_discovery(
                selected_categories,
                selected_states,
                int(pages_input.value),
                stats_card,
                progress_bar,
                run_button,
                stop_button
            )

        run_button.on('click', start_discovery)
        stop_button.on('click', stop_discovery)


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
                ui.label('• Use specific locations for best results (e.g., "Seattle, WA" not just "WA")').classes('text-sm text-yellow-100')

            # Search configuration
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

        # Stats and controls
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
                stop_button = ui.button('STOP', icon='stop', color='negative').props('disable')
                ui.button('Export Last Run', icon='download', on_click=export_last_run).classes('ml-auto')
                ui.button('Export New URLs', icon='file_download', on_click=export_new_urls)

        # Live output
        with ui.card().classes('w-full'):
            ui.label('Live Output').classes('text-xl font-bold mb-4')
            log_container = ui.column().classes('w-full h-96 overflow-y-auto bg-gray-900 p-4 rounded')
            discovery_state.log_element = log_container

        # Run button click handler
        async def start_discovery():
            # Validate Google Maps inputs
            if not query_input.value or not query_input.value.strip():
                ui.notify('Please enter a search query', type='warning')
                return
            if not location_input.value or not location_input.value.strip():
                ui.notify('Please enter a location', type='warning')
                return

            # Run Google Maps discovery
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

        run_button.on('click', start_discovery)
        stop_button.on('click', stop_discovery)


def build_bing_ui(container):
    """Build Bing discovery UI in the given container."""
    with container:
        # Configuration card
        with ui.card().classes('w-full mb-4'):
            ui.label('Bing Discovery Configuration').classes('text-xl font-bold mb-4')

            # Coming soon banner
            with ui.card().classes('w-full bg-blue-900 border-l-4 border-blue-500 mb-4'):
                ui.label('🚧 Bing Discovery - Coming Soon').classes('text-lg font-bold text-blue-200')
                ui.label('• Search businesses on Bing Maps and Bing Local').classes('text-sm text-blue-100')
                ui.label('• Similar functionality to Google Maps discovery').classes('text-sm text-blue-100')
                ui.label('• Will support query and location-based searches').classes('text-sm text-blue-100')

            # Placeholder configuration
            ui.label('Search Query').classes('font-semibold mb-2')
            query_input = ui.input(
                label='What to search for',
                placeholder='e.g., pressure washing, car wash, plumber',
                value='pressure washing'
            ).props('disable').classes('w-full mb-4')

            ui.label('Location').classes('font-semibold mb-2')
            location_input = ui.input(
                label='Where to search',
                placeholder='e.g., Seattle, WA or Chicago, IL',
                value='Seattle, WA'
            ).props('disable').classes('w-full mb-4')

        # Status message
        with ui.card().classes('w-full'):
            ui.label('Status').classes('text-xl font-bold mb-4')
            ui.label('Bing scraper implementation is planned. This will allow discovery of businesses from Bing search results.').classes('text-gray-400')


def build_yelp_ui(container):
    """Build Yelp discovery UI in the given container."""
    with container:
        # Configuration card
        with ui.card().classes('w-full mb-4'):
            ui.label('Yelp Discovery Configuration').classes('text-xl font-bold mb-4')

            # Coming soon banner
            with ui.card().classes('w-full bg-orange-900 border-l-4 border-orange-500 mb-4'):
                ui.label('🚧 Yelp Discovery - Coming Soon').classes('text-lg font-bold text-orange-200')
                ui.label('• Search businesses on Yelp with rich review data').classes('text-sm text-orange-100')
                ui.label('• Includes ratings, reviews, and business hours').classes('text-sm text-orange-100')
                ui.label('• Category and location-based searches').classes('text-sm text-orange-100')

            # Placeholder configuration
            ui.label('Business Category').classes('font-semibold mb-2')
            category_input = ui.input(
                label='Category to search for',
                placeholder='e.g., pressure washing, restaurants, plumbers',
                value='pressure washing'
            ).props('disable').classes('w-full mb-4')

            ui.label('Location').classes('font-semibold mb-2')
            location_input = ui.input(
                label='City and state',
                placeholder='e.g., Seattle, WA',
                value='Seattle, WA'
            ).props('disable').classes('w-full mb-4')

        # Status message
        with ui.card().classes('w-full'):
            ui.label('Status').classes('text-xl font-bold mb-4')
            ui.label('Yelp scraper implementation is planned. This will allow discovery of businesses with Yelp reviews and ratings.').classes('text-gray-400')


def build_bbb_ui(container):
    """Build BBB (Better Business Bureau) discovery UI in the given container."""
    with container:
        # Configuration card
        with ui.card().classes('w-full mb-4'):
            ui.label('BBB Discovery Configuration').classes('text-xl font-bold mb-4')

            # Coming soon banner
            with ui.card().classes('w-full bg-green-900 border-l-4 border-green-500 mb-4'):
                ui.label('🚧 BBB Discovery - Coming Soon').classes('text-lg font-bold text-green-200')
                ui.label('• Search accredited businesses on Better Business Bureau').classes('text-sm text-green-100')
                ui.label('• Includes BBB ratings and complaint history').classes('text-sm text-green-100')
                ui.label('• Useful for finding reputable, established businesses').classes('text-sm text-green-100')

            # Placeholder configuration
            ui.label('Business Type').classes('font-semibold mb-2')
            category_input = ui.input(
                label='Type of business',
                placeholder='e.g., cleaning services, contractors',
                value='cleaning services'
            ).props('disable').classes('w-full mb-4')

            ui.label('Location').classes('font-semibold mb-2')
            location_input = ui.input(
                label='City and state',
                placeholder='e.g., Seattle, WA',
                value='Seattle, WA'
            ).props('disable').classes('w-full mb-4')

        # Status message
        with ui.card().classes('w-full'):
            ui.label('Status').classes('text-xl font-bold mb-4')
            ui.label('BBB scraper implementation is planned. This will allow discovery of accredited businesses with BBB ratings.').classes('text-gray-400')


def build_facebook_ui(container):
    """Build Facebook discovery UI in the given container."""
    with container:
        # Configuration card
        with ui.card().classes('w-full mb-4'):
            ui.label('Facebook Discovery Configuration').classes('text-xl font-bold mb-4')

            # Coming soon banner
            with ui.card().classes('w-full bg-indigo-900 border-l-4 border-indigo-500 mb-4'):
                ui.label('🚧 Facebook Discovery - Coming Soon').classes('text-lg font-bold text-indigo-200')
                ui.label('• Search business pages on Facebook').classes('text-sm text-indigo-100')
                ui.label('• Extract contact info, hours, and page data').classes('text-sm text-indigo-100')
                ui.label('• Note: Facebook scraping has anti-bot protections').classes('text-sm text-indigo-100')

            # Placeholder configuration
            ui.label('Search Query').classes('font-semibold mb-2')
            query_input = ui.input(
                label='Business or service to search',
                placeholder='e.g., pressure washing companies',
                value='pressure washing'
            ).props('disable').classes('w-full mb-4')

            ui.label('Location').classes('font-semibold mb-2')
            location_input = ui.input(
                label='City or region',
                placeholder='e.g., Seattle, WA',
                value='Seattle, WA'
            ).props('disable').classes('w-full mb-4')

        # Status message
        with ui.card().classes('w-full'):
            ui.label('Status').classes('text-xl font-bold mb-4')
            ui.label('Facebook scraper implementation is planned. This will allow discovery of business pages and contact information.').classes('text-gray-400')


def discover_page():
    """Render unified discovery page with source selection."""
    ui.label('URL Discovery').classes('text-3xl font-bold mb-4')

    # Source selection (stays at top)
    with ui.card().classes('w-full mb-4'):
        ui.label('Discovery Source').classes('text-xl font-bold mb-4')

        source_select = ui.select(
            options=['Yellow Pages', 'Google Maps', 'Bing', 'Yelp', 'BBB', 'Facebook'],
            value='Yellow Pages',
            label='Choose discovery source'
        ).classes('w-64')

    # Main content container (will be rebuilt on source change)
    main_content = ui.column().classes('w-full')

    # Build initial content (Yellow Pages by default)
    build_yellow_pages_ui(main_content)

    # Handle source changes - completely rebuild the UI
    def on_source_change(e):
        main_content.clear()
        source = source_select.value

        if source == 'Yellow Pages':
            build_yellow_pages_ui(main_content)
        elif source == 'Google Maps':
            build_google_maps_ui(main_content)
        elif source == 'Bing':
            build_bing_ui(main_content)
        elif source == 'Yelp':
            build_yelp_ui(main_content)
        elif source == 'BBB':
            build_bbb_ui(main_content)
        elif source == 'Facebook':
            build_facebook_ui(main_content)

    source_select.on('update:model-value', on_source_change)
