"""
Logs page - comprehensive log viewing with multi-file support, filtering, and search.
"""

from nicegui import ui
import logging
import asyncio
from pathlib import Path
from collections import deque
from datetime import datetime
import os


# Global state for log tailing
class LogState:
    def __init__(self):
        self.tailing = False
        self.log_position = 0
        self.error_entries = deque(maxlen=100)  # Last 100 errors
        self.timer = None
        self.log_element = None
        self.error_table = None
        self.current_log_file = 'backend_facade.log'  # Default to biggest log
        self.search_text = ''
        self.level_filter = 'ALL'


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
    log_file = Path(f'logs/{log_state.current_log_file}')

    if log_file.exists():
        ui.download(str(log_file))
        ui.notify(f'Downloading {log_state.current_log_file}...', type='positive')
    else:
        ui.notify('Log file not found', type='warning')


def get_log_files():
    """Get list of all available log files with sizes."""
    log_dir = Path('logs')

    if not log_dir.exists():
        return []

    log_files = []
    for log_file in sorted(log_dir.glob('*.log')):
        try:
            size = log_file.stat().st_size
            # Convert size to human readable
            if size < 1024:
                size_str = f'{size}B'
            elif size < 1024 * 1024:
                size_str = f'{size/1024:.1f}KB'
            else:
                size_str = f'{size/(1024*1024):.1f}MB'

            log_files.append({
                'name': log_file.name,
                'size': size,
                'size_str': size_str,
                'modified': datetime.fromtimestamp(log_file.stat().st_mtime)
            })
        except Exception as e:
            logging.error(f'Error reading log file {log_file}: {e}')

    # Sort by size descending
    log_files.sort(key=lambda x: x['size'], reverse=True)
    return log_files


def load_log_content(log_file: str, max_lines: int = 1000, filter_level: str = 'ALL', search: str = ''):
    """Load log file content with filtering."""
    log_path = Path(f'logs/{log_file}')

    if not log_path.exists():
        return []

    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            # Read last N lines for large files
            lines = f.readlines()

            # Take last max_lines
            if len(lines) > max_lines:
                lines = lines[-max_lines:]

            # Apply filters
            filtered_lines = []
            for line in lines:
                line = line.rstrip()
                if not line:
                    continue

                # Level filter
                if filter_level != 'ALL':
                    if filter_level not in line:
                        continue

                # Search filter
                if search and search.lower() not in line.lower():
                    continue

                filtered_lines.append(line)

            return filtered_lines

    except Exception as e:
        logging.error(f'Error loading log file {log_file}: {e}')
        return [f'Error loading log: {str(e)}']


def switch_log_file(file_name: str):
    """Switch to a different log file."""
    log_state.current_log_file = file_name
    log_state.log_position = 0  # Reset position for tailing

    # Reload log content
    if log_state.log_element:
        log_state.log_element.clear()
        lines = load_log_content(
            file_name,
            max_lines=500,
            filter_level=log_state.level_filter,
            search=log_state.search_text
        )
        for line in lines:
            log_state.log_element.push(line)

    ui.notify(f'Switched to {file_name}', type='info')


def refresh_logs():
    """Manually refresh the current log view."""
    if log_state.log_element:
        log_state.log_element.clear()
        lines = load_log_content(
            log_state.current_log_file,
            max_lines=500,
            filter_level=log_state.level_filter,
            search=log_state.search_text
        )
        for line in lines:
            log_state.log_element.push(line)

    ui.notify('Logs refreshed', type='positive')


def apply_filters():
    """Apply search and level filters to current log."""
    refresh_logs()


def logs_page():
    """Render comprehensive logs page with multi-file support."""
    ui.label('Application Logs').classes('text-3xl font-bold mb-4')

    # Get available log files
    log_files = get_log_files()
    log_file_names = [f['name'] for f in log_files]

    # File browser card
    with ui.card().classes('w-full mb-4'):
        with ui.row().classes('w-full items-center mb-2'):
            ui.label('Log Files').classes('text-xl font-bold')
            ui.space()
            ui.label(f'{len(log_files)} files found').classes('text-sm text-gray-400')

        # Log file grid
        with ui.grid(columns=4).classes('w-full gap-2'):
            for log_file in log_files[:12]:  # Show top 12
                with ui.card().classes('p-3 cursor-pointer hover:bg-gray-700').on('click', lambda f=log_file['name']: switch_log_file(f)):
                    ui.label(log_file['name']).classes('text-sm font-semibold truncate')
                    ui.label(log_file['size_str']).classes('text-xs text-gray-400')
                    if log_file['name'] == log_state.current_log_file:
                        ui.badge('ACTIVE', color='positive').classes('absolute top-2 right-2')

    # Control bar
    with ui.card().classes('w-full mb-4'):
        ui.label('Log Viewer Controls').classes('text-lg font-bold mb-3')

        # Row 1: File selector and filters
        with ui.row().classes('w-full items-center gap-4 mb-3'):
            # Current file selector
            ui.label('File:').classes('font-semibold')
            file_select = ui.select(
                log_file_names,
                value=log_state.current_log_file,
                label='Select Log File',
                on_change=lambda e: switch_log_file(e.value)
            ).classes('w-64')

            # Level filter
            ui.label('Level:').classes('font-semibold ml-4')
            level_select = ui.select(
                ['ALL', 'DEBUG', 'INFO', 'WARNING', 'ERROR'],
                value=log_state.level_filter,
                label='Filter Level',
                on_change=lambda e: setattr(log_state, 'level_filter', e.value) or apply_filters()
            ).classes('w-32')

            # Search box
            ui.label('Search:').classes('font-semibold ml-4')
            search_input = ui.input(
                'Search text...',
                value=log_state.search_text,
                on_change=lambda e: setattr(log_state, 'search_text', e.value)
            ).classes('w-64')

            ui.button(
                'Apply',
                icon='search',
                on_click=apply_filters,
                color='primary'
            ).props('flat')

        # Row 2: Action buttons
        with ui.row().classes('w-full gap-2'):
            ui.button(
                'Refresh',
                icon='refresh',
                color='primary',
                on_click=refresh_logs
            ).props('outline')

            tail_button = ui.button(
                'Tail File',
                icon='visibility',
                color='primary',
                on_click=lambda: toggle_tail()
            ).props('outline')

            ui.button(
                'Clear View',
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

            ui.space()

            # Stats
            ui.label(f'Viewing: {log_state.current_log_file}').classes('text-sm text-gray-400')

    # Main log viewer
    with ui.card().classes('w-full mb-4'):
        with ui.row().classes('w-full items-center mb-2'):
            ui.label('Live Logs').classes('text-xl font-bold')
            ui.space()
            ui.label('Last 500 lines').classes('text-sm text-gray-400')

        # Log display
        log_element = ui.log(max_lines=500).classes('w-full h-96')

        # Store reference
        log_state.log_element = log_element

        # Load initial content
        initial_lines = load_log_content(
            log_state.current_log_file,
            max_lines=500,
            filter_level=log_state.level_filter,
            search=log_state.search_text
        )
        for line in initial_lines:
            log_element.push(line)

        # Create timer for tailing (inactive by default)
        log_state.timer = ui.timer(
            1.0,  # Run every 1 second
            lambda: tail_log_file(f'logs/{log_state.current_log_file}', log_element),
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

    # Last Run Summary - Enhanced
    with ui.card().classes('w-full mt-4'):
        from .discover import discovery_state

        with ui.row().classes('w-full items-center mb-4'):
            ui.label('Last Discovery Run Summary').classes('text-xl font-bold')
            ui.space()
            if discovery_state.last_run_summary:
                ui.button(
                    'Export Results',
                    icon='download',
                    on_click=lambda: export_last_run(),
                    color='secondary'
                ).props('outline size=sm')

        if discovery_state.last_run_summary:
            summary = discovery_state.last_run_summary
            result = summary['result']

            # Header with timestamp and performance
            with ui.row().classes('w-full items-center mb-4'):
                with ui.column().classes('flex-1'):
                    ui.label(f"📅 {summary['timestamp'][:19]}").classes('text-sm font-semibold')
                    ui.label(f"⏱️ Duration: {summary['elapsed']:.1f}s ({summary['elapsed']/60:.1f} minutes)").classes('text-sm text-gray-400')

                # Calculate success rate
                total_pairs = result['pairs_total']
                completed_pairs = result['pairs_done']
                success_rate = (result['found'] / completed_pairs * 100) if completed_pairs > 0 else 0

                with ui.column().classes('items-end'):
                    ui.label(f"Progress: {completed_pairs}/{total_pairs} pairs").classes('text-sm')
                    if completed_pairs == total_pairs:
                        ui.badge('✓ COMPLETE', color='positive')
                    else:
                        ui.badge('⚠ PARTIAL', color='warning')

            ui.separator()

            # KPI Cards
            with ui.grid(columns=5).classes('w-full gap-4 mt-4 mb-4'):
                # Found
                with ui.card().classes('p-4 bg-gradient-to-br from-blue-900 to-blue-800'):
                    ui.label('Found').classes('text-gray-300 text-xs uppercase')
                    ui.label(str(result['found'])).classes('text-3xl font-bold text-white')
                    ui.label('Total businesses').classes('text-xs text-gray-400')

                # New
                with ui.card().classes('p-4 bg-gradient-to-br from-green-900 to-green-800'):
                    ui.label('New').classes('text-gray-300 text-xs uppercase')
                    ui.label(str(result['new'])).classes('text-3xl font-bold text-white')
                    ui.label('Added to database').classes('text-xs text-gray-400')

                # Updated
                with ui.card().classes('p-4 bg-gradient-to-br from-blue-900 to-blue-700'):
                    ui.label('Updated').classes('text-gray-300 text-xs uppercase')
                    ui.label(str(result['updated'])).classes('text-3xl font-bold text-white')
                    ui.label('Existing records').classes('text-xs text-gray-400')

                # Success Rate
                with ui.card().classes('p-4 bg-gradient-to-br from-purple-900 to-purple-800'):
                    ui.label('Success Rate').classes('text-gray-300 text-xs uppercase')
                    ui.label(f'{success_rate:.1f}%').classes('text-3xl font-bold text-white')
                    ui.label(f'{result["found"]}/{completed_pairs} pairs').classes('text-xs text-gray-400')

                # Errors
                error_color = 'red' if result['errors'] > 0 else 'gray'
                with ui.card().classes(f'p-4 bg-gradient-to-br from-{error_color}-900 to-{error_color}-800'):
                    ui.label('Errors').classes('text-gray-300 text-xs uppercase')
                    ui.label(str(result['errors'])).classes('text-3xl font-bold text-white')
                    error_rate = (result['errors'] / completed_pairs * 100) if completed_pairs > 0 else 0
                    ui.label(f'{error_rate:.1f}% error rate').classes('text-xs text-gray-400')

            # Performance Metrics
            with ui.expansion('📊 Performance Metrics', icon='analytics').classes('w-full mt-4'):
                with ui.grid(columns=3).classes('w-full gap-4 p-4'):
                    # Speed metrics
                    with ui.card().classes('p-4'):
                        ui.label('⚡ Speed').classes('font-semibold mb-2')
                        avg_time_per_pair = summary['elapsed'] / completed_pairs if completed_pairs > 0 else 0
                        ui.label(f'Avg per pair: {avg_time_per_pair:.1f}s').classes('text-sm')
                        businesses_per_min = (result['found'] / summary['elapsed'] * 60) if summary['elapsed'] > 0 else 0
                        ui.label(f'Rate: {businesses_per_min:.1f} businesses/min').classes('text-sm text-gray-400')

                    # Efficiency
                    with ui.card().classes('p-4'):
                        ui.label('📈 Efficiency').classes('font-semibold mb-2')
                        new_rate = (result['new'] / result['found'] * 100) if result['found'] > 0 else 0
                        ui.label(f'New rate: {new_rate:.1f}%').classes('text-sm')
                        ui.label(f'Duplicates filtered: {result["found"] - result["new"]}').classes('text-sm text-gray-400')

                    # Coverage
                    with ui.card().classes('p-4'):
                        ui.label('🗺️ Coverage').classes('font-semibold mb-2')
                        coverage = (completed_pairs / total_pairs * 100) if total_pairs > 0 else 0
                        ui.label(f'Completion: {coverage:.1f}%').classes('text-sm')
                        ui.label(f'{completed_pairs} of {total_pairs} pairs').classes('text-sm text-gray-400')

            # State & Category breakdown (if we have it)
            if summary.get('state_breakdown'):
                with ui.expansion('🗺️ State Breakdown', icon='map').classes('w-full mt-4'):
                    with ui.scroll_area().classes('h-64'):
                        # Show top performing states
                        state_data = summary['state_breakdown']
                        sorted_states = sorted(state_data.items(), key=lambda x: x[1], reverse=True)

                        for state, count in sorted_states[:20]:  # Top 20 states
                            with ui.row().classes('w-full items-center py-1'):
                                ui.label(f"{state}").classes('w-16 font-semibold')
                                ui.linear_progress(value=count/max(state_data.values()) if state_data.values() else 0).classes('flex-1')
                                ui.label(f"{count}").classes('w-12 text-right text-sm')

            # Action buttons
            with ui.row().classes('w-full gap-2 mt-4'):
                ui.button(
                    'View in Database',
                    icon='storage',
                    on_click=lambda: ui.navigate.to('/database'),
                    color='primary'
                ).props('outline')

                ui.button(
                    'Export to CSV',
                    icon='file_download',
                    on_click=lambda: export_last_run(),
                    color='secondary'
                ).props('outline')

                ui.button(
                    'Run Discovery',
                    icon='play_arrow',
                    on_click=lambda: ui.navigate.to('/discover'),
                    color='positive'
                ).props('outline')

        else:
            # No previous runs
            with ui.column().classes('items-center justify-center p-8'):
                ui.icon('search_off', size='64px').classes('text-gray-600 mb-4')
                ui.label('No Discovery Runs Yet').classes('text-xl text-gray-400 mb-2')
                ui.label('Run your first discovery to see detailed analytics here').classes('text-sm text-gray-500')
                ui.button(
                    'Go to Discovery',
                    icon='play_arrow',
                    on_click=lambda: ui.navigate.to('/discover'),
                    color='positive'
                ).classes('mt-4')

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


async def export_last_run():
    """Export the results from the last discovery run."""
    from .discover import discovery_state

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
        ui.notify(f'Export failed: {e}', type='negative')
        logging.error(f'Export failed: {e}', exc_info=True)
