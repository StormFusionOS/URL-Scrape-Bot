"""
Scrape page - configure and run bulk scraping with real-time progress.
"""

from nicegui import ui, run, app
from ..backend_facade import backend
from datetime import datetime
from collections import deque
import asyncio


# Global state for scraping
class ScrapeState:
    def __init__(self):
        self.running = False
        self.cancel_requested = False
        self.last_run_summary = None
        self.start_time = None
        self.error_log = deque(maxlen=20)  # Last 20 errors
        self.items_processed = 0

        # UI references (set when page is rendered)
        self.progress_bar = None
        self.rate_label = None
        self.stat_labels = {}
        self.error_table = None
        self.stats_card = None

    def cancel(self):
        self.cancel_requested = True

    def is_cancelled(self):
        return self.cancel_requested

    def reset(self):
        self.cancel_requested = False
        self.error_log.clear()
        self.items_processed = 0

    def add_error(self, error_msg: str, website: str = None):
        """Add an error to the error log."""
        self.error_log.append({
            'time': datetime.now().strftime('%H:%M:%S'),
            'website': website or 'N/A',
            'message': error_msg[:100]  # Truncate long messages
        })


scrape_state = ScrapeState()


def progress_callback(progress_data: dict):
    """
    Handle progress updates from the backend.
    This runs in the I/O thread, so we need to be careful with UI updates.
    """
    try:
        # Extract progress info
        current = progress_data.get("current", 0)
        total = progress_data.get("total", 1)
        processed = progress_data.get("processed", 0)
        updated = progress_data.get("updated", 0)
        skipped = progress_data.get("skipped", 0)
        errors = progress_data.get("errors", 0)
        last_result = progress_data.get("last_result", {})
        company_website = progress_data.get("company_website", "")

        # Update progress bar
        if scrape_state.progress_bar and total > 0:
            scrape_state.progress_bar.value = current / total

        # Calculate rate
        if scrape_state.start_time:
            elapsed = (datetime.now() - scrape_state.start_time).total_seconds()
            if elapsed > 0:
                rate = (processed / elapsed) * 60  # items per minute
                if scrape_state.rate_label:
                    scrape_state.rate_label.text = f'Rate: {rate:.1f} items/min (Elapsed: {elapsed:.0f}s)'

        # Update stat labels
        if scrape_state.stat_labels:
            if 'processed' in scrape_state.stat_labels:
                scrape_state.stat_labels['processed'].text = f'Processed: {processed} / {total}'
            if 'updated' in scrape_state.stat_labels:
                scrape_state.stat_labels['updated'].text = f'Updated: {updated}'
            if 'skipped' in scrape_state.stat_labels:
                scrape_state.stat_labels['skipped'].text = f'Skipped: {skipped}'
            if 'errors' in scrape_state.stat_labels:
                scrape_state.stat_labels['errors'].text = f'Errors: {errors}'

        # Log errors to error table
        if last_result.get("error"):
            scrape_state.add_error(last_result["error"], company_website)
            # Update error table
            if scrape_state.error_table:
                scrape_state.error_table.rows = list(scrape_state.error_log)
                scrape_state.error_table.update()

    except Exception as e:
        # Fail silently to avoid breaking the scraping process
        print(f"Progress callback error: {e}")


async def run_scrape(
    limit,
    stale_days,
    only_missing_email,
    run_button,
    stop_button,
):
    """Run scraping in background with progress updates."""
    scrape_state.running = True
    scrape_state.reset()
    scrape_state.start_time = datetime.now()

    # Disable run button, enable stop button
    run_button.disable()
    stop_button.enable()

    # Clear and setup stats display
    scrape_state.stats_card.clear()
    with scrape_state.stats_card:
        ui.label('Batch Scrape Running...').classes('text-lg font-bold text-blue-500')
        ui.separator().classes('my-2')
        scrape_state.stat_labels = {
            'processed': ui.label('Processed: 0 / 0').classes('text-base'),
            'updated': ui.label('Updated: 0').classes('text-base text-green-500'),
            'skipped': ui.label('Skipped: 0').classes('text-base text-blue-500'),
            'errors': ui.label('Errors: 0').classes('text-base text-red-500'),
        }

    # Reset progress bar and rate
    scrape_state.progress_bar.value = 0
    scrape_state.rate_label.text = 'Rate: 0.0 items/min (Elapsed: 0s)'

    # Clear error table
    scrape_state.error_table.rows = []
    scrape_state.error_table.update()

    start_time = datetime.now()

    try:
        # Run scraping in I/O bound thread with progress callback
        result = await run.io_bound(
            backend.scrape_batch,
            limit,
            stale_days,
            only_missing_email,
            lambda: scrape_state.is_cancelled(),
            progress_callback  # Pass the progress callback
        )

        # Calculate final elapsed time
        elapsed = (datetime.now() - start_time).total_seconds()
        items_per_min = (result["processed"] / elapsed * 60) if elapsed > 0 else 0

        # Update final stats
        scrape_state.stats_card.clear()
        with scrape_state.stats_card:
            if scrape_state.cancel_requested:
                ui.label('Batch Scrape Cancelled').classes('text-lg font-bold text-yellow-500')
            else:
                ui.label('Batch Scrape Complete!').classes('text-lg font-bold text-green-500')

            ui.label(f'Elapsed: {elapsed:.1f}s | Rate: {items_per_min:.1f} items/min').classes(
                'text-sm text-gray-400'
            )
            ui.separator().classes('my-2')

            with ui.grid(columns=2).classes('gap-2 w-full'):
                ui.label(f'Processed: {result["processed"]}').classes('text-base')
                ui.label(f'Updated: {result["updated"]}').classes('text-base text-green-500')
                ui.label(f'Skipped: {result["skipped"]}').classes('text-base text-blue-500')
                ui.label(f'Errors: {result["errors"]}').classes('text-base text-red-500')

        # Update progress bar to full
        scrape_state.progress_bar.value = 1.0

        # Update rate label
        scrape_state.rate_label.text = f'Rate: {items_per_min:.1f} items/min (Elapsed: {elapsed:.1f}s)'

        # Store summary
        scrape_state.last_run_summary = {
            'elapsed': elapsed,
            'rate': items_per_min,
            'result': result,
            'timestamp': start_time.isoformat()
        }

        # Show notification
        if scrape_state.cancel_requested:
            ui.notify('Scraping cancelled', type='warning')
        else:
            ui.notify(
                f'Scraping complete! Processed {result["processed"]}, Updated {result["updated"]}',
                type='positive',
                timeout=5000
            )

            # Emit event for database page to refresh
            app.storage.general['scrape_complete'] = datetime.now().isoformat()

    except Exception as e:
        scrape_state.stats_card.clear()
        with scrape_state.stats_card:
            ui.label('Scraping Failed').classes('text-lg font-bold text-red-500')
            ui.label(f'Error: {str(e)}').classes('text-sm text-red-400')

        ui.notify(f'Scraping failed: {str(e)}', type='negative')
        scrape_state.add_error(str(e))

        # Update error table
        scrape_state.error_table.rows = list(scrape_state.error_log)
        scrape_state.error_table.update()

    finally:
        # Re-enable run button, disable stop button
        scrape_state.running = False
        run_button.enable()
        stop_button.disable()


def stop_scrape():
    """Stop the running scrape."""
    if scrape_state.running:
        scrape_state.cancel()
        ui.notify('Cancelling scrape...', type='warning')


def scrape_page():
    """Render scrape page."""
    ui.label('Bulk Scraping').classes('text-3xl font-bold mb-4')

    ui.label(
        'Scrape business websites to enrich company records with detailed information.'
    ).classes('text-gray-400 mb-6')

    # Configuration card
    with ui.card().classes('w-full mb-4'):
        ui.label('Scraping Configuration').classes('text-xl font-bold mb-4')

        # Limit input with "No limit" checkbox
        ui.label('Processing Limit').classes('font-semibold mb-2')

        with ui.row().classes('gap-4 items-center mb-4'):
            limit_input = ui.number(
                'Limit',
                value=10,
                min=1,
                max=10000,
                format='%.0f'
            ).classes('w-48')

            no_limit_checkbox = ui.checkbox(
                'No limit',
                value=False,
                on_change=lambda e: limit_input.set_enabled(not e.value)
            )

        ui.label(
            'Set a limit to process only N companies (or check "No limit" to process all eligible companies)'
        ).classes('text-sm text-gray-400 mb-4')

        # Stale days input
        ui.label('Stale Threshold (days)').classes('font-semibold mb-2')
        stale_days_input = ui.number(
            'Stale Days',
            value=30,
            min=1,
            max=365,
            format='%.0f'
        ).classes('w-48 mb-2')

        ui.label(
            'Companies not updated in N days will be re-scraped'
        ).classes('text-sm text-gray-400 mb-4')

        # Only missing email checkbox
        only_email_checkbox = ui.checkbox(
            'Only process companies missing email addresses',
            value=False
        ).classes('mb-2')

        ui.label(
            'When enabled, only companies without email addresses will be processed (ignores stale threshold)'
        ).classes('text-sm text-gray-400')

    # Control buttons
    with ui.row().classes('gap-2 mb-4'):
        run_button = ui.button(
            'RUN',
            icon='play_arrow',
            color='positive',
            on_click=lambda: run_scrape(
                None if no_limit_checkbox.value else int(limit_input.value),
                int(stale_days_input.value),
                only_email_checkbox.value,
                run_button,
                stop_button,
            )
        ).props('size=lg')

        stop_button = ui.button(
            'STOP',
            icon='stop',
            color='negative',
            on_click=lambda: stop_scrape()
        ).props('size=lg')
        stop_button.disable()

    # Progress card
    with ui.card().classes('w-full mb-4'):
        ui.label('Progress').classes('text-lg font-bold mb-2')
        scrape_state.progress_bar = ui.linear_progress(
            value=0,
            show_value=False
        ).classes('w-full')

        scrape_state.rate_label = ui.label('Rate: 0.0 items/min (Elapsed: 0s)').classes(
            'text-sm text-gray-400 mt-2'
        )

    # Stats card (will be populated during run)
    scrape_state.stats_card = ui.card().classes('w-full mb-4')
    with scrape_state.stats_card:
        ui.label('Ready to run batch scrape').classes('text-lg text-gray-400 italic')

    # Error grid
    with ui.card().classes('w-full mb-4'):
        ui.label('Recent Errors').classes('text-xl font-bold mb-4')

        # Define columns
        columns = [
            {'name': 'time', 'label': 'Time', 'field': 'time', 'align': 'left', 'sortable': False},
            {'name': 'website', 'label': 'Website', 'field': 'website', 'align': 'left', 'sortable': False},
            {'name': 'message', 'label': 'Error Message', 'field': 'message', 'align': 'left', 'sortable': False},
        ]

        # Create error table
        scrape_state.error_table = ui.table(
            columns=columns,
            rows=list(scrape_state.error_log),
            row_key='time'
        ).classes('w-full')

        if not scrape_state.error_log:
            ui.label('No errors logged yet').classes('text-gray-400 italic text-sm mt-2')

    # Last run summary
    with ui.card().classes('w-full'):
        ui.label('Last Run Summary').classes('text-xl font-bold mb-4')

        if scrape_state.last_run_summary:
            summary = scrape_state.last_run_summary
            result = summary['result']

            with ui.row().classes('gap-4 mb-2'):
                ui.label(f"Timestamp: {summary['timestamp'][:19]}").classes('text-sm')
                ui.label(f"Elapsed: {summary['elapsed']:.1f}s").classes('text-sm')
                ui.label(f"Rate: {summary['rate']:.1f} items/min").classes('text-sm')

            ui.separator()

            with ui.grid(columns=4).classes('w-full gap-4 mt-2'):
                with ui.card().classes('p-3'):
                    ui.label('Processed').classes('text-gray-400 text-sm')
                    ui.label(str(result['processed'])).classes('text-2xl font-bold')

                with ui.card().classes('p-3'):
                    ui.label('Updated').classes('text-gray-400 text-sm')
                    ui.label(str(result['updated'])).classes('text-2xl font-bold text-green-500')

                with ui.card().classes('p-3'):
                    ui.label('Skipped').classes('text-gray-400 text-sm')
                    ui.label(str(result['skipped'])).classes('text-2xl font-bold text-blue-500')

                with ui.card().classes('p-3'):
                    ui.label('Errors').classes('text-gray-400 text-sm')
                    ui.label(str(result['errors'])).classes('text-2xl font-bold text-red-500')
        else:
            ui.label('No previous runs').classes('text-gray-400 italic')

    # Instructions
    with ui.expansion('Instructions', icon='help_outline').classes('w-full mt-4'):
        with ui.card().classes('w-full'):
            ui.label('How to use the Bulk Scraping tool:').classes('font-semibold mb-2')

            with ui.column().classes('gap-1'):
                ui.label('1. Set processing limit or enable "No limit" to process all eligible companies')
                ui.label('2. Configure stale threshold (companies not updated in N days will be re-scraped)')
                ui.label('3. Optionally enable "Only missing email" to focus on companies without contact info')
                ui.label('4. Click RUN to start batch scraping')
                ui.label('5. Monitor live progress: progress bar, rate, and counters update in real-time')
                ui.label('6. Use STOP to cancel the operation if needed')
                ui.label('7. Check the error grid for any failed scrapes')
                ui.label('8. Review the summary after completion')

            ui.separator().classes('my-2')

            ui.label('💡 Tip: Start with a small limit (e.g., 3-5) to test before running larger batches').classes(
                'text-sm text-blue-400'
            )
