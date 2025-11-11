"""
Discovery page - configure and run URL discovery with real-time progress.
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
            'debug': 'text-gray-400'
        }

        color = color_map.get(level, 'text-white')
        timestamp = datetime.now().strftime('%H:%M:%S')

        with self.log_element:
            ui.label(f'[{timestamp}] {message}').classes(f'{color} leading-tight')


discovery_state = DiscoveryState()


# Service categories - using broader terms that return consistent results
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


async def run_discovery(
    categories,
    states,
    pages_per_pair,
    stats_card,
    progress_bar,
    run_button,
    stop_button
):
    """Run discovery in background with progress updates."""
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
    discovery_state.add_log('Starting Discovery Job', 'info')
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
                stats_card.clear()
                with stats_card:
                    ui.label('Running discovery...').classes('text-lg font-bold')
                    ui.label(f'Found: {progress.get("total_found", 0)}')
                    ui.label(f'New: {progress.get("total_new", 0)}')
                    ui.label(f'Updated: {progress.get("total_updated", 0)}')
                    ui.label(f'Errors: {progress.get("total_errors", 0)}')
                    ui.label(f'Progress: {progress.get("pairs_done", 0)}/{progress.get("pairs_total", 0)} pairs')

                # Update progress bar
                if progress.get('pairs_total', 0) > 0:
                    progress_bar.value = progress.get('pairs_done', 0) / progress.get('pairs_total', 1)

            elif progress_type == 'batch_empty':
                category = progress.get('category', '')
                state = progress.get('state', '')
                discovery_state.add_log(
                    f"○ {category} × {state}: No results",
                    'debug'
                )

            elif progress_type == 'batch_error':
                category = progress.get('category', '')
                state = progress.get('state', '')
                error = progress.get('error', 'Unknown error')
                discovery_state.add_log(
                    f"✗ {category} × {state}: Error - {error}",
                    'error'
                )

            elif progress_type == 'save_error':
                category = progress.get('category', '')
                state = progress.get('state', '')
                error = progress.get('error', 'Unknown error')
                discovery_state.add_log(
                    f"✗ {category} × {state}: Save error - {error}",
                    'error'
                )

            elif progress_type == 'cancelled':
                discovery_state.add_log('Discovery cancelled by user', 'warning')

        # Run discovery in I/O bound thread with progress callback
        result = await run.io_bound(
            backend.discover,
            categories,
            states,
            pages_per_pair,
            lambda: discovery_state.is_cancelled(),
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
    filename = f'discovery_run_{timestamp}.json'

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


def discover_page():
    """Render discovery page."""
    ui.label('URL Discovery').classes('text-3xl font-bold mb-4')

    # Configuration card
    with ui.card().classes('w-full mb-4'):
        ui.label('Discovery Configuration').classes('text-xl font-bold mb-4')

        # Category selection
        ui.label('Business Categories').classes('font-semibold mb-2')
        ui.label('Select categories to search (click to toggle):').classes('text-sm text-gray-400 mb-2')

        # Use a dictionary to track category chips and their selection state
        category_chips = {}

        def create_category_chip(category_name, selected=True):
            """Create a category chip with visual indicators."""
            chip_state = {'selected': selected}

            def toggle_chip():
                chip_state['selected'] = not chip_state['selected']
                # Update visual appearance
                if chip_state['selected']:
                    chip.props(f'color=positive icon=check_circle')
                    chip.classes(remove='bg-red-600 text-white')
                    chip.classes(add='bg-green-600 text-white')
                else:
                    chip.props(f'color=negative icon=cancel')
                    chip.classes(remove='bg-green-600')
                    chip.classes(add='bg-red-600 text-white')

            chip = ui.chip(
                category_name,
                icon='check_circle' if selected else 'cancel',
                on_click=toggle_chip
            ).props(f'clickable color={"positive" if selected else "negative"}')

            if selected:
                chip.classes('bg-green-600 text-white')
            else:
                chip.classes('bg-red-600 text-white')

            category_chips[category_name] = chip_state
            return chip

        with ui.row().classes('gap-2 flex-wrap mb-4'):
            for category in DEFAULT_CATEGORIES:  # Show all categories
                create_category_chip(category, selected=True)

        # State selection
        ui.label('States/Regions').classes('font-semibold mt-4 mb-2')

        with ui.row().classes('gap-2 items-center mb-2'):
            ui.button(
                'Select All',
                icon='check_circle',
                on_click=lambda: state_select.set_value(ALL_STATES),
                color='secondary'
            ).props('size=sm outline')

            ui.button(
                'Clear All',
                icon='cancel',
                on_click=lambda: state_select.set_value([]),
                color='warning'
            ).props('size=sm outline')

        state_select = ui.select(
            ALL_STATES,
            multiple=True,
            value=['TX', 'CA'],  # Default to 2 states for testing
            label='Select States',
            with_input=True
        ).classes('w-full')

        # Pages per pair slider
        ui.label('Pages per Category-State Pair').classes('font-semibold mt-4 mb-2')
        pages_slider = ui.slider(
            min=1,
            max=10,
            value=2,
            step=1
        ).classes('w-full').props('label-always')

        with ui.row().classes('w-full'):
            ui.label().bind_text_from(pages_slider, 'value', lambda v: f'{v} pages per pair')

    # Control buttons
    with ui.row().classes('gap-2 mb-4'):
        run_button = ui.button(
            'RUN',
            icon='play_arrow',
            color='positive',
            on_click=lambda: run_discovery(
                [cat for cat, state in category_chips.items() if state['selected']],
                state_select.value,
                int(pages_slider.value),
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
            on_click=lambda: stop_discovery()
        ).props('size=lg')
        stop_button.disable()

        ui.button(
            'EXPORT NEW URLs (7d)',
            icon='download',
            color='secondary',
            on_click=lambda: export_new_urls()
        ).props('outline')

    # Progress bar
    progress_bar = ui.linear_progress(value=0, show_value=False).classes('w-full mb-4')

    # Stats card
    stats_card = ui.card().classes('w-full mb-4')
    with stats_card:
        ui.label('Ready to run discovery').classes('text-lg text-gray-400 italic')

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
        log_container = ui.scroll_area().classes('w-full h-64 bg-gray-900 rounded p-2')

        with log_container:
            log_element = ui.column().classes('w-full gap-0 font-mono text-xs')

        # Store reference for access in run_discovery
        discovery_state.log_element = log_element

    # Instructions - Collapsible
    with ui.expansion('📖 Instructions', icon='help').classes('w-full mt-4'):
        with ui.card().classes('p-4'):
            ui.label('1. Select business categories and states').classes('text-sm mb-2')
            ui.label('2. Adjust pages per pair (more pages = more results but slower)').classes('text-sm mb-2')
            ui.label('3. Click RUN to start discovery').classes('text-sm mb-2')
            ui.label('4. Use STOP to cancel if needed').classes('text-sm mb-2')
            ui.label('5. Export new URLs to download discovered businesses').classes('text-sm')
