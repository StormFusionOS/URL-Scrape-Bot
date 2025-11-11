"""
Google Maps Discovery page - search and scrape businesses from Google Maps.
"""

from nicegui import ui, run
from ..backend_facade import backend
from datetime import datetime
import asyncio


# Global state for Google discovery
class GoogleDiscoveryState:
    def __init__(self):
        self.running = False
        self.cancel_requested = False
        self.last_result = None
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


google_state = GoogleDiscoveryState()


async def run_google_discovery(
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
    google_state.running = True
    google_state.reset()
    google_state.start_time = datetime.now()

    # Disable run button, enable stop button
    run_button.disable()
    stop_button.enable()

    # Clear log
    if google_state.log_element:
        google_state.log_element.clear()

    # Add initial log messages
    google_state.add_log('=' * 60, 'info')
    google_state.add_log('GOOGLE MAPS DISCOVERY STARTED', 'success')
    google_state.add_log('=' * 60, 'info')
    google_state.add_log(f'Query: {query}', 'info')
    google_state.add_log(f'Location: {location or "Not specified"}', 'info')
    google_state.add_log(f'Max Results: {max_results}', 'info')
    google_state.add_log(f'Scrape Details: {scrape_details}', 'info')
    google_state.add_log('-' * 60, 'info')

    # Progress callback
    def update_progress(progress_data):
        """Handle progress updates from backend."""
        msg_type = progress_data.get('type', 'info')
        message = progress_data.get('message', '')

        # Log the message
        google_state.add_log(message, msg_type)

        # Update stats card
        stats_card.clear()
        with stats_card:
            with ui.grid(columns=4).classes('w-full gap-4'):
                # Found
                with ui.card().classes('p-4'):
                    ui.label('Found').classes('text-sm text-gray-400')
                    ui.label(str(progress_data.get('found', 0))).classes('text-2xl font-bold text-blue-400')

                # Saved
                with ui.card().classes('p-4'):
                    ui.label('Saved').classes('text-sm text-gray-400')
                    ui.label(str(progress_data.get('saved', 0))).classes('text-2xl font-bold text-green-400')

                # Duplicates
                with ui.card().classes('p-4'):
                    ui.label('Duplicates').classes('text-sm text-gray-400')
                    ui.label(str(progress_data.get('duplicates', 0))).classes('text-2xl font-bold text-yellow-400')

                # Errors
                with ui.card().classes('p-4'):
                    ui.label('Errors').classes('text-sm text-gray-400')
                    ui.label(str(progress_data.get('errors', 0))).classes('text-2xl font-bold text-red-400')

        # Update progress bar (estimate based on max_results)
        if max_results > 0:
            processed = progress_data.get('saved', 0) + progress_data.get('duplicates', 0)
            progress_bar.value = min(processed / max_results, 1.0)

    try:
        # Run discovery
        google_state.add_log('Starting Google Maps scraper...', 'info')

        result = await run.io_bound(
            backend.discover_google,
            query=query,
            location=location,
            max_results=max_results,
            scrape_details=scrape_details,
            cancel_flag=google_state.is_cancelled,
            progress_callback=update_progress
        )

        # Store result
        google_state.last_result = result

        # Calculate duration
        duration = (datetime.now() - google_state.start_time).total_seconds()

        # Log completion
        google_state.add_log('-' * 60, 'info')
        if google_state.cancel_requested:
            google_state.add_log('GOOGLE DISCOVERY CANCELLED', 'warning')
        elif result.get('success'):
            google_state.add_log('GOOGLE DISCOVERY COMPLETED SUCCESSFULLY!', 'success')
            stats = result.get('stats', {})
            google_state.add_log(f'Duration: {duration:.1f}s', 'info')
            google_state.add_log(f'Found: {stats.get("businesses_found", 0)} businesses', 'success')
            google_state.add_log(f'Saved: {stats.get("businesses_saved", 0)} new businesses', 'success')
            google_state.add_log(f'Duplicates: {stats.get("duplicates_skipped", 0)} skipped', 'info')
            if stats.get('errors', 0) > 0:
                google_state.add_log(f'Errors: {stats.get("errors", 0)}', 'warning')
        else:
            google_state.add_log('GOOGLE DISCOVERY FAILED', 'error')
            google_state.add_log(f'Error: {result.get("error", "Unknown error")}', 'error')

        google_state.add_log('=' * 60, 'info')

        # Final stats card update
        stats_card.clear()
        with stats_card:
            if result.get('success'):
                stats = result.get('stats', {})
                ui.label('Discovery Complete!').classes('text-xl font-bold text-green-400 mb-4')

                with ui.grid(columns=4).classes('w-full gap-4'):
                    with ui.card().classes('p-4'):
                        ui.label('Found').classes('text-sm text-gray-400')
                        ui.label(str(stats.get('businesses_found', 0))).classes('text-2xl font-bold text-blue-400')

                    with ui.card().classes('p-4'):
                        ui.label('Saved').classes('text-sm text-gray-400')
                        ui.label(str(stats.get('businesses_saved', 0))).classes('text-2xl font-bold text-green-400')

                    with ui.card().classes('p-4'):
                        ui.label('Duplicates').classes('text-sm text-gray-400')
                        ui.label(str(stats.get('duplicates_skipped', 0))).classes('text-2xl font-bold text-yellow-400')

                    with ui.card().classes('p-4'):
                        ui.label('Errors').classes('text-sm text-gray-400')
                        ui.label(str(stats.get('errors', 0))).classes('text-2xl font-bold text-red-400')

                ui.label(f'Duration: {duration:.1f} seconds').classes('text-sm text-gray-400 mt-4')
            else:
                ui.label('Discovery Failed').classes('text-xl font-bold text-red-400 mb-2')
                ui.label(f'Error: {result.get("error", "Unknown error")}').classes('text-sm text-red-300')

        # Show notification
        if google_state.cancel_requested:
            ui.notify('Google discovery cancelled', type='warning')
        elif result.get('success'):
            stats = result.get('stats', {})
            ui.notify(
                f'Discovery complete! Saved {stats.get("businesses_saved", 0)} businesses',
                type='positive'
            )
        else:
            ui.notify(f'Discovery failed: {result.get("error", "Unknown error")}', type='negative')

    except Exception as e:
        google_state.add_log('-' * 60, 'error')
        google_state.add_log('DISCOVERY FAILED!', 'error')
        google_state.add_log(f'Error: {str(e)}', 'error')
        google_state.add_log('=' * 60, 'error')

        stats_card.clear()
        with stats_card:
            ui.label('Discovery Failed').classes('text-lg font-bold text-red-500')
            ui.label(f'Error: {str(e)}').classes('text-sm text-red-400')

        ui.notify(f'Google discovery failed: {str(e)}', type='negative')

    finally:
        # Re-enable run button, disable stop button
        google_state.running = False
        run_button.enable()
        stop_button.disable()
        progress_bar.value = 1.0 if not google_state.cancel_requested else 0


def stop_google_discovery():
    """Stop the running Google discovery."""
    if google_state.running:
        google_state.cancel()
        ui.notify('Cancelling Google discovery...', type='warning')


def discover_google_page():
    """Google Maps discovery page."""
    # Page header
    with ui.row().classes('w-full items-center mb-6'):
        ui.icon('map', size='xl').classes('text-purple-400')
        ui.label('Google Maps Discovery').classes('text-3xl font-bold')

    ui.label('Search and scrape businesses from Google Maps with Playwright automation').classes(
        'text-lg text-gray-400 mb-6'
    )

    # Warning banner
    with ui.card().classes('w-full mb-6 bg-yellow-900 border-l-4 border-yellow-500'):
        with ui.row().classes('items-center gap-2'):
            ui.icon('warning', size='md').classes('text-yellow-400')
            with ui.column().classes('gap-1'):
                ui.label('Extreme Caution Mode').classes('font-bold text-yellow-300')
                ui.label(
                    'This scraper uses 30-60 second delays between requests and NO proxies. '
                    'Speed is intentionally slow to avoid detection.'
                ).classes('text-sm text-yellow-200')

    # Configuration form
    with ui.card().classes('w-full mb-6'):
        ui.label('Search Configuration').classes('text-xl font-bold mb-4')

        with ui.grid(columns=2).classes('w-full gap-4'):
            # Query input
            query_input = ui.input(
                'Search Query',
                placeholder='e.g., car wash, restaurants, plumbers',
                value='car wash'
            ).classes('w-full').props('outlined')

            # Location input
            location_input = ui.input(
                'Location (Optional)',
                placeholder='e.g., Seattle, WA',
                value='Seattle, WA'
            ).classes('w-full').props('outlined')

        # Max results slider
        ui.label('Maximum Results').classes('font-semibold mt-4 mb-2')
        max_results_slider = ui.slider(
            min=1,
            max=50,
            value=10,
            step=1
        ).classes('w-full').props('label-always')

        with ui.row().classes('w-full items-center gap-4'):
            ui.label().bind_text_from(
                max_results_slider, 'value',
                lambda v: f'{v} results (Est. time: {v * 45 / 60:.1f} minutes at 45s per business)'
            ).classes('text-sm text-gray-400')

        # Scrape details checkbox
        scrape_details_check = ui.checkbox(
            'Scrape Detailed Info (slower but more complete)',
            value=True
        ).classes('mt-4')

    # Control buttons
    with ui.row().classes('gap-2 mb-4'):
        run_button = ui.button(
            'START GOOGLE SCRAPING',
            icon='play_arrow',
            color='positive',
            on_click=lambda: run_google_discovery(
                query_input.value,
                location_input.value if location_input.value else None,
                int(max_results_slider.value),
                scrape_details_check.value,
                stats_card,
                progress_bar,
                run_button,
                stop_button
            )
        ).props('size=lg')

        stop_button = ui.button(
            'STOP',
            icon='stop',
            color='negative',
            on_click=lambda: stop_google_discovery()
        ).props('size=lg')
        stop_button.disable()

    # Progress bar
    progress_bar = ui.linear_progress(value=0, show_value=False).classes('w-full mb-4')

    # Stats card
    stats_card = ui.card().classes('w-full mb-4')
    with stats_card:
        ui.label('Ready to scrape Google Maps').classes('text-lg text-gray-400 italic')

    # Live output log
    with ui.card().classes('w-full mb-4'):
        with ui.row().classes('w-full items-center mb-2'):
            ui.label('Live Output').classes('text-xl font-bold')
            ui.space()
            clear_log_btn = ui.button(
                'Clear',
                icon='clear',
                on_click=lambda: log_element.clear(),
                color='secondary'
            ).props('size=sm outline')

        # Create scrollable log container
        log_container = ui.scroll_area().classes('w-full h-96 bg-gray-900 rounded p-2')

        with log_container:
            log_element = ui.column().classes('w-full gap-0 font-mono text-xs')

        # Store reference for access in run_google_discovery
        google_state.log_element = log_element

    # Instructions - Collapsible
    with ui.expansion('📖 How to Use', icon='help').classes('w-full mt-4'):
        with ui.card().classes('p-4'):
            ui.label('What This Does:').classes('font-bold text-lg mb-2')
            ui.label('• Searches Google Maps using Playwright browser automation').classes('text-sm mb-1')
            ui.label('• Extracts business name, address, phone, website, rating, etc.').classes('text-sm mb-1')
            ui.label('• Saves results to database with duplicate detection (by place_id)').classes('text-sm mb-4')

            ui.label('Steps:').classes('font-bold text-lg mb-2')
            ui.label('1. Enter a search query (e.g., "car wash", "restaurants")').classes('text-sm mb-1')
            ui.label('2. Optionally specify a location (e.g., "Seattle, WA")').classes('text-sm mb-1')
            ui.label('3. Set max results (warning: this will be SLOW)').classes('text-sm mb-1')
            ui.label('4. Choose whether to scrape detailed info for each business').classes('text-sm mb-1')
            ui.label('5. Click START and wait (expect 30-60 seconds between each request)').classes('text-sm mb-4')

            ui.label('Important Notes:').classes('font-bold text-lg mb-2')
            ui.label('⚠ This uses NO proxies and extreme rate limiting to avoid detection').classes('text-sm text-yellow-300 mb-1')
            ui.label('⚠ Expect ~30-60 seconds PER business (10 businesses = 5-10 minutes)').classes('text-sm text-yellow-300 mb-1')
            ui.label('⚠ Browser window will appear (not headless by default for testing)').classes('text-sm text-yellow-300 mb-1')
            ui.label('⚠ If CAPTCHA appears, stop and wait before retrying').classes('text-sm text-red-300 mb-1')
            ui.label('✓ All data saved to database with Google source tag').classes('text-sm text-green-300 mb-1')
            ui.label('✓ Logs saved to logs/google_*.log for troubleshooting').classes('text-sm text-green-300')
