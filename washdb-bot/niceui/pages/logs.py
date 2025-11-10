"""
Logs page - real-time application logs with tailing and filtering.
"""

from nicegui import ui
import logging
from pathlib import Path
from collections import deque
from datetime import datetime


# Global state for log tailing
class LogState:
    def __init__(self):
        self.tailing = False
        self.log_position = 0
        self.error_entries = deque(maxlen=50)  # Last 50 errors
        self.timer = None
        self.log_element = None
        self.error_table = None


log_state = LogState()


def tail_log_file(log_file_path: str, log_element):
    """Read new lines from log file and append to UI log."""
    try:
        log_path = Path(log_file_path)

        if not log_path.exists():
            return

        with open(log_path, 'r', encoding='utf-8') as f:
            # Seek to last position
            f.seek(log_state.log_position)

            # Read new lines
            new_lines = f.readlines()

            # Update position
            log_state.log_position = f.tell()

            # Append new lines to log element
            for line in new_lines:
                line = line.rstrip()
                if line:
                    # Check if it's an error line
                    if 'ERROR' in line or 'Error' in line:
                        log_state.error_entries.append({
                            'time': datetime.now().strftime('%H:%M:%S'),
                            'message': line
                        })
                        # Update error table if it exists
                        if log_state.error_table:
                            update_error_table()

                    # Add to log display
                    log_element.push(line)

    except Exception as e:
        print(f"Error tailing log: {e}")


def update_error_table():
    """Update the error table with latest errors."""
    if log_state.error_table and log_state.error_entries:
        rows = [
            {'time': entry['time'], 'message': entry['message'][:100] + '...' if len(entry['message']) > 100 else entry['message']}
            for entry in reversed(log_state.error_entries)
        ]
        log_state.error_table.rows = rows
        log_state.error_table.update()


def toggle_tail():
    """Toggle log file tailing."""
    log_state.tailing = not log_state.tailing

    if log_state.tailing:
        # Start tailing
        log_file = 'logs/scraper.log'

        # Initialize position to end of file
        log_path = Path(log_file)
        if log_path.exists():
            with open(log_path, 'r') as f:
                f.seek(0, 2)  # Seek to end
                log_state.log_position = f.tell()

        # Start timer
        if log_state.timer:
            log_state.timer.active = True

        ui.notify('Started tailing log file', type='positive')
    else:
        # Stop tailing
        if log_state.timer:
            log_state.timer.active = False

        ui.notify('Stopped tailing log file', type='info')


def clear_logs():
    """Clear the log display."""
    if log_state.log_element:
        log_state.log_element.clear()
        ui.notify('Logs cleared', type='info')


def download_logs():
    """Download current logs."""
    log_file = Path('logs/scraper.log')

    if log_file.exists():
        ui.download(str(log_file))
        ui.notify('Downloading log file...', type='positive')
    else:
        ui.notify('Log file not found', type='warning')


def logs_page():
    """Render logs page with real-time tailing."""
    ui.label('Application Logs').classes('text-3xl font-bold mb-4')

    # Top control bar
    with ui.card().classes('w-full mb-4'):
        with ui.row().classes('w-full items-center gap-4'):
            # Log level filter
            ui.label('Level:').classes('font-semibold')
            level_select = ui.select(
                ['ALL', 'DEBUG', 'INFO', 'WARNING', 'ERROR'],
                value='ALL',
                label='Filter Level'
            ).classes('w-32')

            ui.space()

            # Control buttons
            tail_button = ui.button(
                'Tail File',
                icon='visibility',
                color='primary',
                on_click=lambda: toggle_tail()
            ).props('outline')

            ui.button(
                'Clear',
                icon='clear_all',
                color='warning',
                on_click=lambda: clear_logs()
            ).props('outline')

            ui.button(
                'Download',
                icon='download',
                color='secondary',
                on_click=lambda: download_logs()
            ).props('outline')

    # Main log viewer
    with ui.card().classes('w-full mb-4'):
        ui.label('Live Logs').classes('text-xl font-bold mb-2')

        # Log display - bind to Python logger
        log_element = ui.log(max_lines=500).classes('w-full h-96')

        # Bind to root logger
        try:
            root_logger = logging.getLogger()
            log_element.bind_logger(root_logger, level=logging.INFO)
        except Exception as e:
            print(f"Error binding logger: {e}")

        # Store reference
        log_state.log_element = log_element

        # Create timer for tailing (inactive by default)
        log_state.timer = ui.timer(
            1.0,  # Run every 1 second
            lambda: tail_log_file('logs/scraper.log', log_element),
            active=False
        )

    # Error entries table
    with ui.card().classes('w-full'):
        ui.label('Recent Errors (Last 50)').classes('text-xl font-bold mb-4')

        # Define columns
        columns = [
            {'name': 'time', 'label': 'Time', 'field': 'time', 'align': 'left'},
            {'name': 'message', 'label': 'Message', 'field': 'message', 'align': 'left'},
        ]

        # Create table
        error_table = ui.table(
            columns=columns,
            rows=[],
            row_key='time'
        ).classes('w-full')

        # Store reference
        log_state.error_table = error_table

        # Initialize with any existing errors
        if log_state.error_entries:
            update_error_table()
        else:
            with error_table:
                ui.label('No errors logged yet').classes('text-gray-400 italic p-4')

    # Add some test logs
    with ui.card().classes('w-full mt-4'):
        ui.label('Test Logging').classes('text-lg font-bold mb-2')
        ui.label('Click buttons below to test different log levels:').classes('text-sm text-gray-400 mb-2')

        with ui.row().classes('gap-2'):
            ui.button(
                'Test INFO',
                icon='info',
                color='info',
                on_click=lambda: logging.info('Test INFO message from logs page')
            ).props('size=sm')

            ui.button(
                'Test WARNING',
                icon='warning',
                color='warning',
                on_click=lambda: logging.warning('Test WARNING message from logs page')
            ).props('size=sm')

            ui.button(
                'Test ERROR',
                icon='error',
                color='negative',
                on_click=lambda: logging.error('Test ERROR message from logs page')
            ).props('size=sm')

            ui.button(
                'Test Backend Call',
                icon='code',
                color='primary',
                on_click=lambda: test_backend_call()
            ).props('size=sm')


def test_backend_call():
    """Test a backend call to see logs appear."""
    from ..backend_facade import backend

    ui.notify('Running backend test...', type='info')
    logging.info('Starting backend KPI test...')

    try:
        # Call backend to trigger some logging
        kpis = backend.kpis()
        logging.info(f'Backend KPIs retrieved: {kpis}')
        ui.notify(f'Backend test complete! Total companies: {kpis.get("total_companies", 0)}', type='positive')
    except Exception as e:
        logging.error(f'Backend test failed: {e}', exc_info=True)
        ui.notify(f'Backend test failed: {e}', type='negative')
