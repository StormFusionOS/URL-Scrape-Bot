"""
Status, History & Logs page - comprehensive dashboard for live activity, past runs, and application logs.
"""

import asyncio
from datetime import datetime, timedelta
from nicegui import ui, run
from ..router import event_bus
from ..utils import job_state, history_manager
from ..layout import layout
import tempfile
from pathlib import Path
from collections import deque
import logging


# Page state
class StatusPageState:
    """State for the status page."""
    def __init__(self):
        self.log_element = None
        self.auto_scroll = True
        self.status_badge = None
        self.job_name_label = None
        self.start_time_label = None
        self.elapsed_label = None
        self.items_label = None
        self.errors_label = None
        self.throughput_label = None
        self.progress_bar = None
        self.history_table = None
        self.stats_cards = {}
        self.update_timer = None


status_state = StatusPageState()


# Log viewing state (from logs.py)
class LogState:
    def __init__(self):
        self.tailing = False
        self.log_position = 0
        self.error_entries = deque(maxlen=100)
        self.timer = None
        self.log_element = None
        self.error_table = None
        self.current_log_file = 'backend_facade.log'
        self.search_text = ''
        self.level_filter = 'ALL'


log_state = LogState()


def get_status_color(exit_code, is_running, is_stalled):
    """Get badge color based on status."""
    if is_stalled:
        return 'red'
    if is_running:
        return 'blue'
    if exit_code is None:
        return 'grey'
    return 'positive' if exit_code == 0 else 'negative'


def get_status_text(exit_code, is_running, is_stalled):
    """Get status text."""
    if is_stalled:
        return 'STALLED'
    if is_running:
        return 'RUNNING'
    if exit_code is None:
        return 'IDLE'
    return 'FINISHED' if exit_code == 0 else 'FAILED'


def format_duration(seconds):
    """Format duration in seconds to human readable."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


async def update_live_stats():
    """Update live statistics (called by timer)."""
    if not job_state.active_job or not job_state.streamer:
        return

    try:
        # Update status badge
        is_stalled = job_state.streamer.is_stalled(30)
        is_running = job_state.streamer.running
        exit_code = job_state.streamer.exit_code

        # Update elapsed time ONLY if job is still running
        if is_running:
            elapsed = job_state.streamer.get_elapsed()
            if status_state.elapsed_label:
                status_state.elapsed_label.set_text(format_duration(elapsed))

        if status_state.status_badge:
            color = get_status_color(exit_code, is_running, is_stalled)
            text = get_status_text(exit_code, is_running, is_stalled)
            status_state.status_badge.props(f'color={color}')
            status_state.status_badge.set_text(text)

        # Update metrics
        metrics = job_state.metrics
        if status_state.items_label:
            if metrics['items_total'] > 0:
                status_state.items_label.set_text(
                    f"{metrics['items_done']} / {metrics['items_total']}"
                )
            else:
                status_state.items_label.set_text(f"{metrics['items_done']}")

        if status_state.errors_label:
            status_state.errors_label.set_text(str(metrics['errors']))

        if status_state.throughput_label:
            status_state.throughput_label.set_text(f"{metrics['throughput']:.1f} items/min")

        # Update progress bar
        if status_state.progress_bar and metrics['items_total'] > 0:
            progress = metrics['items_done'] / metrics['items_total']
            status_state.progress_bar.value = progress

    except Exception as e:
        print(f"Error updating live stats: {e}")


def add_log_line(line_type: str, line: str):
    """Add a line to the log viewer."""
    if not status_state.log_element:
        return

    # Determine color based on content
    line_lower = line.lower()
    if 'error' in line_lower or line_type == 'stderr':
        color = 'red'
    elif 'warning' in line_lower or 'warn' in line_lower:
        color = 'yellow'
    elif 'info' in line_lower:
        color = 'lightblue'
    else:
        color = 'white'

    # Add timestamp
    timestamp = datetime.now().strftime('%H:%M:%S')
    formatted = f"[{timestamp}] {line}"

    # Store in job state first
    job_state.logs.append((datetime.now(), line_type, line))

    # Parse for metrics
    job_state.parse_metrics(line)

    # Add to log element
    try:
        # Escape HTML entities in the line
        import html
        escaped_line = html.escape(formatted)

        with status_state.log_element:
            ui.html(f'<div style="color: {color}; font-family: monospace; font-size: 12px; white-space: pre-wrap;">{escaped_line}</div>')

        # Auto-scroll if enabled
        if status_state.auto_scroll:
            ui.run_javascript('''
                const logContainer = document.querySelector('#log-container');
                if (logContainer) {
                    logContainer.scrollTop = logContainer.scrollHeight;
                }
            ''')

    except Exception as e:
        print(f"Error adding log line: {e}")


async def start_test_job():
    """Start a test job (simulated)."""
    if job_state.active_job:
        ui.notify('A job is already running', type='warning')
        return

    layout.show_busy()

    # Capture the current client context for UI updates
    from nicegui import context
    client = context.get_client()

    try:
        # Reset state
        job_state.reset()
        job_state.active_job = {
            'name': 'Test Job',
            'type': 'Test',
            'args': {'mode': 'test'},
            'start_time': datetime.now()
        }

        # Update UI
        if status_state.job_name_label:
            status_state.job_name_label.set_text('Test Job')
        if status_state.start_time_label:
            status_state.start_time_label.set_text(
                job_state.active_job['start_time'].strftime('%Y-%m-%d %H:%M:%S')
            )

        # Create streamer
        from ..utils.cli_stream import CLIStreamer
        job_state.streamer = CLIStreamer()

        # Simulate job with echo commands
        def on_line(line_type, line):
            # Push UI update to the correct client
            with client:
                add_log_line(line_type, line)

        def on_complete(exit_code, duration):
            # Push UI updates to the correct client
            with client:
                # Add to history
                history_manager.add_run(
                    job_type='Test',
                    args={'mode': 'test'},
                    duration_sec=duration,
                    exit_code=exit_code,
                    counts={
                        'found': job_state.metrics['items_done'],
                        'errors': job_state.metrics['errors']
                    },
                    notes='Test run'
                )

                # Refresh history table
                load_history_table()

                ui.notify(f'Job completed in {format_duration(duration)}',
                          type='positive' if exit_code == 0 else 'negative')

                layout.hide_busy()

        # Run test command
        await job_state.streamer.run_command(
            ['bash', '-c', 'for i in {1..10}; do echo "Processing item $i"; sleep 0.5; done; echo "Done"'],
            on_line=on_line,
            on_complete=on_complete
        )

    except Exception as e:
        ui.notify(f'Error starting job: {e}', type='negative')
        job_state.reset()
        layout.hide_busy()


async def cancel_job():
    """Cancel the running job."""
    if not job_state.active_job or not job_state.streamer:
        ui.notify('No job to cancel', type='warning')
        return

    try:
        await job_state.streamer.terminate()
        ui.notify('Job cancelled', type='warning')
        layout.hide_busy()
    except Exception as e:
        ui.notify(f'Error cancelling job: {e}', type='negative')


def clear_log():
    """Clear the log viewer."""
    if status_state.log_element:
        status_state.log_element.clear()
        job_state.logs = []
        ui.notify('Log cleared', type='info')


def clear_discovery_log():
    """Clear the discovery log viewer."""
    from .discover import discovery_state
    if discovery_state.log_element:
        discovery_state.log_element.clear()
        ui.notify('Discovery log cleared', type='info')


def copy_log():
    """Copy log to clipboard."""
    if not job_state.logs:
        ui.notify('No logs to copy', type='warning')
        return

    log_text = '\n'.join(f"[{ts.strftime('%H:%M:%S')}] {line}" for ts, _, line in job_state.logs)

    ui.run_javascript(f'''
        navigator.clipboard.writeText(`{log_text}`);
    ''')
    ui.notify('Log copied to clipboard', type='positive')


def load_history_table(job_filter=None, search_text=None):
    """Load history into table."""
    if not status_state.history_table:
        return

    runs = history_manager.filter_runs(job_type=job_filter, search=search_text, limit=100)

    # Convert to table rows
    rows = []
    for run in runs:
        counts = run.get('counts', {})
        timestamp = run.get('timestamp', '')
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp)
                timestamp = dt.strftime('%Y-%m-%d %H:%M:%S')
            except (ValueError, TypeError) as e:
                logging.debug(f"Failed to parse timestamp '{timestamp}': {e}")
                # Keep original timestamp string

        rows.append({
            'timestamp': timestamp,
            'job_type': run.get('job_type', ''),
            'duration': format_duration(run.get('duration_sec', 0)),
            'exit_code': run.get('exit_code', -1),
            'found': counts.get('found', 0),
            'updated': counts.get('updated', 0),
            'errors': counts.get('errors', 0),
            'args': str(run.get('args', {}))[:50],
            'log_path': run.get('log_path', ''),
        })

    status_state.history_table.options['rowData'] = rows
    status_state.history_table.update()


def export_history_csv():
    """Export history to CSV."""
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            temp_path = f.name

        history_manager.export_csv(temp_path)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'history_{timestamp}.csv'

        ui.download(temp_path, filename)
        ui.notify('History exported', type='positive')

    except Exception as e:
        ui.notify(f'Error exporting: {e}', type='negative')


def clear_history():
    """Clear all history."""
    history_manager.clear_history()
    load_history_table()
    ui.notify('History cleared', type='warning')


# ============================================================================
# LOG VIEWING FUNCTIONS (from logs.py)
# ============================================================================

def get_log_files():
    """Get list of available log files with metadata."""
    log_dir = Path('logs')
    if not log_dir.exists():
        return []

    log_files = []
    for log_file in log_dir.glob('*.log'):
        size = log_file.stat().st_size
        size_str = f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / (1024 * 1024):.1f} MB"
        log_files.append({
            'name': log_file.name,
            'size': size,
            'size_str': size_str,
            'modified': datetime.fromtimestamp(log_file.stat().st_mtime)
        })

    return sorted(log_files, key=lambda x: x['size'], reverse=True)


def load_log_content(log_file, max_lines=500, filter_level='ALL', search=''):
    """Load log file content with filtering."""
    try:
        log_path = Path(f'logs/{log_file}')
        if not log_path.exists():
            return [f"Log file not found: {log_file}"]

        with open(log_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Get last N lines
        lines = lines[-max_lines:]

        # Apply filters
        filtered_lines = []
        for line in lines:
            line = line.rstrip()
            if not line:
                continue

            # Level filter
            if filter_level != 'ALL' and filter_level not in line:
                continue

            # Search filter
            if search and search.lower() not in line.lower():
                continue

            filtered_lines.append(line)

        return filtered_lines
    except Exception as e:
        return [f"Error loading log: {str(e)}"]


def switch_log_file(new_file):
    """Switch to a different log file."""
    log_state.current_log_file = new_file
    log_state.log_position = 0
    refresh_logs()
    ui.notify(f'Switched to {new_file}', type='info')


def refresh_logs():
    """Refresh the log display."""
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


def apply_filters():
    """Apply current filters to log display."""
    refresh_logs()
    ui.notify('Filters applied', type='positive')


def toggle_tail():
    """Toggle log tailing on/off."""
    if log_state.timer:
        log_state.tailing = not log_state.tailing
        log_state.timer.active = log_state.tailing
        ui.notify(f'Tailing {"enabled" if log_state.tailing else "disabled"}',
                  type='positive' if log_state.tailing else 'warning')


def clear_logs():
    """Clear the log display."""
    if log_state.log_element:
        log_state.log_element.clear()
        ui.notify('Log view cleared', type='info')


def tail_log_file(log_file_path, log_element):
    """Read new lines from log file."""
    try:
        log_path = Path(log_file_path)
        if not log_path.exists():
            return

        with open(log_path, 'r', encoding='utf-8') as f:
            f.seek(log_state.log_position)
            new_lines = f.readlines()
            log_state.log_position = f.tell()

            for line in new_lines:
                line = line.rstrip()
                if line:
                    if 'ERROR' in line:
                        log_state.error_entries.append({
                            'time': datetime.now().strftime('%H:%M:%S'),
                            'message': line[:100] + '...' if len(line) > 100 else line
                        })
                    log_element.push(line)
    except Exception as e:
        pass


def status_page():
    """Render combined status, history & logs page."""
    ui.label('Status, History & Logs').classes('text-3xl font-bold mb-4')

    # Create tabs
    with ui.tabs().classes('w-full') as tabs:
        tab_status = ui.tab('Status & History', icon='dashboard')
        tab_logs = ui.tab('Application Logs', icon='description')

    with ui.tab_panels(tabs, value=tab_status).classes('w-full'):
        # ======================
        # TAB 1: STATUS & HISTORY
        # ======================
        with ui.tab_panel(tab_status):
            # ======================
            # LIVE ACTIVITY SECTION
            # ======================
            ui.label('Live Activity').classes('text-2xl font-bold mb-2')

    with ui.card().classes('w-full mb-4'):
        # Log viewer - displays discovery logs
        ui.label('Live Output (Discovery Runs)').classes('text-lg font-bold mb-2')

        with ui.row().classes('w-full gap-2 mb-2'):
            ui.button('Clear Log', icon='delete', on_click=lambda: clear_discovery_log()).props('flat dense')

        # Display discovery logs
        log_container = ui.scroll_area().classes('w-full h-96 bg-gray-900 rounded p-2')

        with log_container:
            # Import discovery state to show discovery logs
            from .discover import discovery_state
            if discovery_state.log_element:
                # Reference the same log element from discovery
                status_state.log_element = discovery_state.log_element
            else:
                # Create a placeholder
                status_state.log_element = ui.column().classes('w-full gap-0 font-mono text-xs')
                ui.label('No discovery runs yet. Start a discovery run from the Discover page.').classes('text-gray-400 italic text-sm')

    # ======================
    # HISTORY SECTION
    # ======================
    ui.label('Run History').classes('text-2xl font-bold mb-2 mt-6')

    with ui.card().classes('w-full mb-4'):
        # Summary stats
        stats = history_manager.get_stats()

        with ui.row().classes('w-full gap-4 mb-4'):
            with ui.card().classes('flex-1 bg-blue-900'):
                ui.label('Total Runs').classes('text-sm text-gray-300')
                ui.label(str(stats['total_runs'])).classes('text-2xl font-bold')

            with ui.card().classes('flex-1 bg-green-900'):
                ui.label('Successful').classes('text-sm text-gray-300')
                ui.label(str(stats['success_count'])).classes('text-2xl font-bold')

            with ui.card().classes('flex-1 bg-red-900'):
                ui.label('Failed').classes('text-sm text-gray-300')
                ui.label(str(stats['error_count'])).classes('text-2xl font-bold')

            with ui.card().classes('flex-1 bg-purple-900'):
                ui.label('Avg Duration').classes('text-sm text-gray-300')
                ui.label(format_duration(stats['avg_duration'])).classes('text-2xl font-bold')

        # Filters
        with ui.row().classes('w-full gap-4 mb-4'):
            job_filter = ui.select(
                ['All', 'Discover', 'Scrape', 'Single URL'],
                value='All',
                label='Job Type'
            ).classes('w-48')

            search_input = ui.input('Search', placeholder='Search args/notes...').classes('flex-1')

            ui.button('Filter', icon='filter_list',
                      on_click=lambda: load_history_table(
                          None if job_filter.value == 'All' else job_filter.value,
                          search_input.value if search_input.value else None
                      )).props('outline')

            ui.button('Export CSV', icon='download', color='primary',
                      on_click=export_history_csv).props('outline')

            ui.button('Clear History', icon='delete_forever', color='negative',
                      on_click=clear_history).props('outline')

        # History table
        status_state.history_table = ui.aggrid({
            'columnDefs': [
                {'field': 'timestamp', 'headerName': 'Timestamp', 'sortable': True, 'width': 180},
                {'field': 'job_type', 'headerName': 'Job Type', 'sortable': True, 'width': 120},
                {'field': 'duration', 'headerName': 'Duration', 'sortable': True, 'width': 100},
                {'field': 'exit_code', 'headerName': 'Exit Code', 'sortable': True, 'width': 100},
                {'field': 'found', 'headerName': 'Found', 'sortable': True, 'width': 90},
                {'field': 'updated', 'headerName': 'Updated', 'sortable': True, 'width': 90},
                {'field': 'errors', 'headerName': 'Errors', 'sortable': True, 'width': 90},
                {'field': 'args', 'headerName': 'Args', 'flex': 1},
            ],
            'rowData': [],
            'rowSelection': 'single',
            'pagination': True,
            'paginationPageSize': 20,
        }).classes('w-full').style('height: 400px;')

        # Load initial data
        load_history_table()

        # ======================
        # TAB 2: APPLICATION LOGS
        # ======================
        with ui.tab_panel(tab_logs):
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
                        log_file_names if log_file_names else ['No logs'],
                        value=log_state.current_log_file if log_state.current_log_file in log_file_names else (log_file_names[0] if log_file_names else 'No logs'),
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

                    ui.button(
                        'Tail File',
                        icon='visibility',
                        color='primary',
                        on_click=toggle_tail
                    ).props('outline')

                    ui.button(
                        'Clear View',
                        icon='clear_all',
                        color='warning',
                        on_click=clear_logs
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

                # Create timer for tailing
                log_state.timer = ui.timer(
                    1.0,
                    lambda: tail_log_file(f'logs/{log_state.current_log_file}', log_element),
                    active=False
                )

            # Error entries table
            with ui.card().classes('w-full'):
                ui.label('Recent Errors').classes('text-xl font-bold mb-4')

                error_table = ui.table(
                    columns=[
                        {'name': 'time', 'label': 'Time', 'field': 'time', 'align': 'left'},
                        {'name': 'message', 'label': 'Message', 'field': 'message', 'align': 'left'},
                    ],
                    rows=[],
                    row_key='time'
                ).classes('w-full')

                # Store reference
                log_state.error_table = error_table

    # Start update timer for live stats (outside tabs)
    status_state.update_timer = ui.timer(1.0, lambda: update_live_stats())
