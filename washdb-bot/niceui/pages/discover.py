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

    def cancel(self):
        self.cancel_requested = True

    def is_cancelled(self):
        return self.cancel_requested

    def reset(self):
        self.cancel_requested = False


discovery_state = DiscoveryState()


# Service categories from our scraper
DEFAULT_CATEGORIES = [
    "pressure washing",
    "power washing",
    "soft washing",
    "window cleaning",
    "window washing",
    "deck restoration",
    "deck staining",
    "wood restoration",
    "fence staining",
    "log home restoration",
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
        # Run discovery in I/O bound thread
        result = await run.io_bound(
            backend.discover,
            categories,
            states,
            pages_per_pair,
            lambda: discovery_state.is_cancelled()
        )

        # Update final stats
        elapsed = (datetime.now() - discovery_state.start_time).total_seconds()

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

        with ui.row().classes('gap-2 flex-wrap mb-4'):
            for category in DEFAULT_CATEGORIES[:5]:  # Show first 5 for testing
                chip = ui.chip(
                    category,
                    icon='label',
                    selectable=True,
                    selected=True
                ).props('color=primary')
                category_chips[category] = chip

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
                [cat for cat, chip in category_chips.items() if chip.selected],
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

    # Last run card
    with ui.card().classes('w-full'):
        ui.label('Last Run Summary').classes('text-xl font-bold mb-4')

        if discovery_state.last_run_summary:
            summary = discovery_state.last_run_summary
            result = summary['result']

            with ui.row().classes('gap-4'):
                ui.label(f"Timestamp: {summary['timestamp'][:19]}").classes('text-sm')
                ui.label(f"Elapsed: {summary['elapsed']:.1f}s").classes('text-sm')

            ui.separator()

            with ui.grid(columns=4).classes('w-full gap-4 mt-2'):
                with ui.card().classes('p-3'):
                    ui.label('Found').classes('text-gray-400 text-sm')
                    ui.label(str(result['found'])).classes('text-2xl font-bold')

                with ui.card().classes('p-3'):
                    ui.label('New').classes('text-gray-400 text-sm')
                    ui.label(str(result['new'])).classes('text-2xl font-bold text-green-500')

                with ui.card().classes('p-3'):
                    ui.label('Updated').classes('text-gray-400 text-sm')
                    ui.label(str(result['updated'])).classes('text-2xl font-bold text-blue-500')

                with ui.card().classes('p-3'):
                    ui.label('Errors').classes('text-gray-400 text-sm')
                    ui.label(str(result['errors'])).classes('text-2xl font-bold text-red-500')
        else:
            ui.label('No previous runs').classes('text-gray-400 italic')

    # Instructions
    with ui.card().classes('w-full mt-4'):
        ui.label('Instructions').classes('text-lg font-bold mb-2')
        ui.label('1. Select business categories and states').classes('text-sm')
        ui.label('2. Adjust pages per pair (more pages = more results but slower)').classes('text-sm')
        ui.label('3. Click RUN to start discovery').classes('text-sm')
        ui.label('4. Use STOP to cancel if needed').classes('text-sm')
        ui.label('5. Export new URLs to download discovered businesses').classes('text-sm')
