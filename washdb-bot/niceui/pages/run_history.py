"""
Run History page - display job execution logs and scraper run statistics.

Shows comprehensive history of all scraper runs with:
- Run status and duration
- Items found and saved
- Error tracking
- Filtering by status, source, date range
- Detailed run information
"""

from nicegui import ui
from datetime import datetime, timedelta
import logging
from sqlalchemy import desc, and_, or_


class RunHistoryState:
    def __init__(self):
        self.table_ref = None
        self.status_filter = 'all'
        self.source_filter = 'all'
        self.date_range = 7  # Last 7 days
        self.search_text = ''


run_history_state = RunHistoryState()


def get_run_history(limit=100):
    """Fetch run history from job_execution_logs table."""
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        import os

        db_url = os.getenv('DATABASE_URL')
        if not db_url:
            return []

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        # Import the model
        from db.models import JobExecutionLog

        # Build query with filters
        query = session.query(JobExecutionLog)

        # Status filter
        if run_history_state.status_filter != 'all':
            query = query.filter(JobExecutionLog.status == run_history_state.status_filter)

        # Source filter
        if run_history_state.source_filter != 'all':
            query = query.filter(JobExecutionLog.job_name.like(f'%{run_history_state.source_filter}%'))

        # Date range filter
        if run_history_state.date_range > 0:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=run_history_state.date_range)
            query = query.filter(JobExecutionLog.start_time >= cutoff_date)

        # Search filter (in job_name or notes)
        if run_history_state.search_text:
            search_pattern = f'%{run_history_state.search_text}%'
            query = query.filter(
                or_(
                    JobExecutionLog.job_name.like(search_pattern),
                    JobExecutionLog.notes.like(search_pattern)
                )
            )

        # Order by most recent first
        query = query.order_by(desc(JobExecutionLog.start_time))

        # Limit results
        jobs = query.limit(limit).all()

        session.close()

        # Convert to dict for table
        rows = []
        for job in jobs:
            duration = None
            if job.end_time and job.start_time:
                delta = job.end_time - job.start_time
                duration = delta.total_seconds()

            rows.append({
                'id': job.id,
                'job_name': job.job_name,
                'status': job.status,
                'start_time': job.start_time.strftime('%Y-%m-%d %H:%M:%S') if job.start_time else 'N/A',
                'duration': f'{duration:.1f}s' if duration else 'N/A',
                'items_found': job.items_found or 0,
                'errors_count': job.errors_count or 0,
                'notes': (job.notes[:50] + '...') if job.notes and len(job.notes) > 50 else (job.notes or '')
            })

        return rows

    except Exception as e:
        logging.error(f'Failed to fetch run history: {e}')
        return []


def get_summary_stats():
    """Get summary statistics for all runs."""
    try:
        from sqlalchemy import create_engine, func
        from sqlalchemy.orm import sessionmaker
        import os

        db_url = os.getenv('DATABASE_URL')
        if not db_url:
            return {}

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        from db.models import JobExecutionLog

        # Total runs
        total_runs = session.query(func.count(JobExecutionLog.id)).scalar()

        # Completed runs
        completed = session.query(func.count(JobExecutionLog.id)).filter(
            JobExecutionLog.status == 'completed'
        ).scalar()

        # Failed runs
        failed = session.query(func.count(JobExecutionLog.id)).filter(
            JobExecutionLog.status == 'failed'
        ).scalar()

        # Total items found
        total_items = session.query(func.sum(JobExecutionLog.items_found)).scalar() or 0

        # Total errors
        total_errors = session.query(func.sum(JobExecutionLog.errors_count)).scalar() or 0

        # Runs in last 24 hours
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        recent_runs = session.query(func.count(JobExecutionLog.id)).filter(
            JobExecutionLog.start_time >= yesterday
        ).scalar()

        session.close()

        return {
            'total_runs': total_runs,
            'completed': completed,
            'failed': failed,
            'running': total_runs - completed - failed,  # Approximation
            'total_items': total_items,
            'total_errors': total_errors,
            'recent_runs': recent_runs,
            'success_rate': (completed / total_runs * 100) if total_runs > 0 else 0
        }

    except Exception as e:
        logging.error(f'Failed to fetch summary stats: {e}')
        return {
            'total_runs': 0,
            'completed': 0,
            'failed': 0,
            'running': 0,
            'total_items': 0,
            'total_errors': 0,
            'recent_runs': 0,
            'success_rate': 0
        }


def refresh_table():
    """Refresh the run history table."""
    if run_history_state.table_ref:
        rows = get_run_history()
        run_history_state.table_ref.rows = rows
        run_history_state.table_ref.update()
        ui.notify(f'Refreshed: {len(rows)} runs loaded', type='info')


def apply_filters():
    """Apply filters and refresh table."""
    refresh_table()


def show_run_details(run_id):
    """Show detailed information for a specific run."""
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        import os

        db_url = os.getenv('DATABASE_URL')
        if not db_url:
            ui.notify('Database not configured', type='warning')
            return

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        from db.models import JobExecutionLog

        job = session.query(JobExecutionLog).filter(JobExecutionLog.id == run_id).first()

        if not job:
            ui.notify('Run not found', type='warning')
            session.close()
            return

        # Create dialog with full details
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl'):
            with ui.row().classes('w-full items-center mb-4'):
                ui.label('Run Details').classes('text-2xl font-bold')
                ui.space()
                ui.button(icon='close', on_click=dialog.close).props('flat round')

            # Job info
            with ui.grid(columns=2).classes('w-full gap-4 mb-4'):
                ui.label('Job Name:').classes('font-semibold')
                ui.label(job.job_name)

                ui.label('Status:').classes('font-semibold')
                status_color = {'completed': 'positive', 'failed': 'negative', 'running': 'info'}.get(job.status, 'gray')
                ui.badge(job.status.upper(), color=status_color)

                ui.label('Start Time:').classes('font-semibold')
                ui.label(job.start_time.strftime('%Y-%m-%d %H:%M:%S') if job.start_time else 'N/A')

                ui.label('End Time:').classes('font-semibold')
                ui.label(job.end_time.strftime('%Y-%m-%d %H:%M:%S') if job.end_time else 'N/A')

                if job.end_time and job.start_time:
                    duration = (job.end_time - job.start_time).total_seconds()
                    ui.label('Duration:').classes('font-semibold')
                    ui.label(f'{duration:.1f} seconds ({duration/60:.1f} minutes)')

                ui.label('Items Found:').classes('font-semibold')
                ui.label(str(job.items_found or 0))

                ui.label('Errors:').classes('font-semibold')
                ui.label(str(job.errors_count or 0))

            # Notes
            if job.notes:
                ui.separator()
                ui.label('Notes:').classes('font-semibold mb-2 mt-4')
                ui.label(job.notes).classes('text-sm text-gray-300 whitespace-pre-wrap')

        dialog.open()
        session.close()

    except Exception as e:
        logging.error(f'Failed to show run details: {e}')
        ui.notify(f'Error: {e}', type='negative')


def run_history_page():
    """Render run history page."""
    ui.label('Run History').classes('text-3xl font-bold mb-4')
    ui.label('Track all scraper execution logs').classes('text-gray-400 mb-6')

    # Summary stats
    stats = get_summary_stats()

    with ui.card().classes('w-full mb-4'):
        ui.label('Summary Statistics').classes('text-xl font-bold mb-4')

        with ui.grid(columns=4).classes('w-full gap-4'):
            # Total runs
            with ui.card().classes('p-4 bg-gradient-to-br from-blue-900 to-blue-800'):
                ui.label('Total Runs').classes('text-gray-300 text-xs uppercase')
                ui.label(str(stats['total_runs'])).classes('text-3xl font-bold text-white')

            # Completed
            with ui.card().classes('p-4 bg-gradient-to-br from-green-900 to-green-800'):
                ui.label('Completed').classes('text-gray-300 text-xs uppercase')
                ui.label(str(stats['completed'])).classes('text-3xl font-bold text-white')
                ui.label(f'{stats["success_rate"]:.1f}% success').classes('text-xs text-gray-400')

            # Failed
            with ui.card().classes('p-4 bg-gradient-to-br from-red-900 to-red-800'):
                ui.label('Failed').classes('text-gray-300 text-xs uppercase')
                ui.label(str(stats['failed'])).classes('text-3xl font-bold text-white')

            # Total items
            with ui.card().classes('p-4 bg-gradient-to-br from-purple-900 to-purple-800'):
                ui.label('Total Items').classes('text-gray-300 text-xs uppercase')
                ui.label(str(stats['total_items'])).classes('text-3xl font-bold text-white')
                ui.label(f'{stats["recent_runs"]} runs (24h)').classes('text-xs text-gray-400')

    # Filters
    with ui.card().classes('w-full mb-4'):
        ui.label('Filters').classes('text-lg font-bold mb-3')

        with ui.row().classes('w-full items-center gap-4'):
            # Status filter
            ui.label('Status:').classes('font-semibold')
            ui.select(
                ['all', 'completed', 'failed', 'running'],
                value=run_history_state.status_filter,
                label='Filter by status',
                on_change=lambda e: setattr(run_history_state, 'status_filter', e.value)
            ).classes('w-40')

            # Source filter
            ui.label('Source:').classes('font-semibold ml-4')
            ui.select(
                ['all', 'yp', 'google', 'bing'],
                value=run_history_state.source_filter,
                label='Filter by source',
                on_change=lambda e: setattr(run_history_state, 'source_filter', e.value)
            ).classes('w-40')

            # Date range
            ui.label('Period:').classes('font-semibold ml-4')
            ui.select(
                {7: 'Last 7 days', 30: 'Last 30 days', 90: 'Last 90 days', 0: 'All time'},
                value=run_history_state.date_range,
                label='Date range',
                on_change=lambda e: setattr(run_history_state, 'date_range', e.value)
            ).classes('w-40')

            # Search
            ui.label('Search:').classes('font-semibold ml-4')
            ui.input(
                'Search job name or notes...',
                value=run_history_state.search_text,
                on_change=lambda e: setattr(run_history_state, 'search_text', e.value)
            ).classes('w-64')

            ui.button(
                'Apply',
                icon='search',
                color='primary',
                on_click=apply_filters
            ).props('flat')

            ui.button(
                'Refresh',
                icon='refresh',
                color='primary',
                on_click=refresh_table
            ).props('flat')

    # Run history table
    with ui.card().classes('w-full'):
        ui.label('Recent Runs').classes('text-xl font-bold mb-4')

        columns = [
            {'name': 'id', 'label': 'ID', 'field': 'id', 'sortable': True, 'align': 'left'},
            {'name': 'job_name', 'label': 'Job Name', 'field': 'job_name', 'sortable': True, 'align': 'left'},
            {'name': 'status', 'label': 'Status', 'field': 'status', 'sortable': True, 'align': 'left'},
            {'name': 'start_time', 'label': 'Start Time', 'field': 'start_time', 'sortable': True, 'align': 'left'},
            {'name': 'duration', 'label': 'Duration', 'field': 'duration', 'sortable': True, 'align': 'left'},
            {'name': 'items_found', 'label': 'Items', 'field': 'items_found', 'sortable': True, 'align': 'right'},
            {'name': 'errors_count', 'label': 'Errors', 'field': 'errors_count', 'sortable': True, 'align': 'right'},
            {'name': 'notes', 'label': 'Notes', 'field': 'notes', 'sortable': False, 'align': 'left'},
        ]

        # Get initial data
        initial_rows = get_run_history()

        table = ui.table(
            columns=columns,
            rows=initial_rows,
            row_key='id',
            pagination={'rowsPerPage': 20, 'sortBy': 'start_time', 'descending': True}
        ).classes('w-full')

        # Store reference
        run_history_state.table_ref = table

        # Add click handler to show details
        table.on('row-click', lambda e: show_run_details(e.args[1]['id']))

        # Custom row styling
        table.add_slot('body-cell-status', '''
            <q-td :props="props">
                <q-badge
                    :color="props.value === 'completed' ? 'positive' : props.value === 'failed' ? 'negative' : 'info'"
                    :label="props.value.toUpperCase()"
                />
            </q-td>
        ''')

        table.add_slot('body-cell-errors_count', '''
            <q-td :props="props">
                <span :class="props.value > 0 ? 'text-red-400' : 'text-green-400'">
                    {{ props.value }}
                </span>
            </q-td>
        ''')

        if not initial_rows:
            with table:
                ui.label('No runs found. Run a scraper to see history here.').classes('text-gray-400 italic p-4')

    # Help card
    with ui.card().classes('w-full mt-6 bg-blue-900 bg-opacity-30'):
        ui.label('💡 Run History Tips').classes('text-lg font-bold mb-3')

        with ui.column().classes('gap-2'):
            ui.label('• Click on any row to see full run details').classes('text-sm')
            ui.label('• Green badges = completed, Red = failed, Blue = running').classes('text-sm')
            ui.label('• Use filters to narrow down specific runs').classes('text-sm')
            ui.label('• Search by job name or notes for quick lookups').classes('text-sm')
            ui.label('• Table is sortable - click column headers').classes('text-sm')
