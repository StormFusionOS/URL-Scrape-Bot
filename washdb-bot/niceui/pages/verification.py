"""
Verification Review page - Review and manually override company verification results.

Provides a GUI for:
- Viewing companies that need manual review
- Seeing verification details (score, tier, signals)
- Manually marking companies as Target or Non-target
- Collecting labels for ML training
- Real-time verification job monitoring
"""

from nicegui import ui, run
from datetime import datetime
from typing import Optional, List, Dict
import asyncio
import os
import sys
import json

from ..backend_facade import backend
from ..widgets.live_log_viewer import LiveLogViewer
from ..utils.subprocess_runner import SubprocessRunner
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()


# Global state for verification
class VerificationState:
    def __init__(self):
        self.running = False
        self.cancel_requested = False
        self.last_run_summary = None
        self.start_time = None
        self.subprocess_runner = None
        self.selected_company_id = None  # Currently selected company for detail view
        self.log_viewer = None  # LiveLogViewer instance
        self.worker_pool_running = False  # Worker pool status
        self.worker_pool_subprocess = None  # Worker pool subprocess

    def cancel(self):
        self.cancel_requested = True

    def is_cancelled(self):
        return self.cancel_requested

    def reset(self):
        self.cancel_requested = False


verification_state = VerificationState()


def get_db_session():
    """Get database session for querying companies."""
    engine = create_engine(os.getenv('DATABASE_URL'))
    Session = sessionmaker(bind=engine)
    return Session()


def get_companies_for_review(status_filter='needs_review', limit=50) -> List[Dict]:
    """
    Fetch companies that need review from database.

    Args:
        status_filter: 'all', 'needs_review', 'passed', 'failed', 'unknown', 'no_label'
        limit: Maximum companies to return

    Returns:
        List of company dicts with verification metadata
    """
    session = get_db_session()

    try:
        query = """
        SELECT
            id,
            name,
            website,
            domain,
            phone,
            email,
            services,
            service_area,
            source,
            rating_yp,
            rating_google,
            reviews_yp,
            reviews_google,
            active,
            parse_metadata,
            created_at,
            last_updated
        FROM companies
        WHERE 1=1
        """

        # Add filter conditions
        if status_filter == 'needs_review':
            query += " AND parse_metadata->'verification'->>'needs_review' = 'true'"
        elif status_filter in ['passed', 'failed', 'unknown']:
            query += f" AND parse_metadata->'verification'->>'status' = '{status_filter}'"
        elif status_filter == 'no_label':
            query += " AND parse_metadata->'verification'->>'label_human' IS NULL"

        query += f" ORDER BY last_updated DESC LIMIT {limit}"

        result = session.execute(text(query))
        companies = []

        for row in result:
            company = {
                'id': row.id,
                'name': row.name,
                'website': row.website,
                'domain': row.domain,
                'phone': row.phone,
                'email': row.email,
                'services': row.services,
                'service_area': row.service_area,
                'source': row.source,
                'rating_yp': row.rating_yp,
                'rating_google': row.rating_google,
                'reviews_yp': row.reviews_yp,
                'reviews_google': row.reviews_google,
                'active': row.active,
                'parse_metadata': row.parse_metadata or {},
                'created_at': row.created_at,
                'last_updated': row.last_updated
            }
            companies.append(company)

        return companies

    finally:
        session.close()


def get_verification_stats() -> Dict:
    """Get verification statistics for summary dashboard."""
    session = get_db_session()

    try:
        query = """
        SELECT
            COUNT(*) as total,
            COUNT(CASE WHEN parse_metadata->'verification'->>'status' = 'passed' THEN 1 END) as passed,
            COUNT(CASE WHEN parse_metadata->'verification'->>'status' = 'failed' THEN 1 END) as failed,
            COUNT(CASE WHEN parse_metadata->'verification'->>'status' = 'unknown' THEN 1 END) as unknown,
            COUNT(CASE WHEN parse_metadata->'verification'->>'needs_review' = 'true' THEN 1 END) as needs_review,
            COUNT(CASE WHEN parse_metadata->'verification'->>'label_human' = 'target' THEN 1 END) as labeled_target,
            COUNT(CASE WHEN parse_metadata->'verification'->>'label_human' = 'non_target' THEN 1 END) as labeled_non_target
        FROM companies
        WHERE parse_metadata->'verification' IS NOT NULL
        """

        result = session.execute(text(query))
        row = result.fetchone()

        return {
            'total': row.total,
            'passed': row.passed,
            'failed': row.failed,
            'unknown': row.unknown,
            'needs_review': row.needs_review,
            'labeled_target': row.labeled_target,
            'labeled_non_target': row.labeled_non_target
        }

    finally:
        session.close()


def mark_company_label(company_id: int, label: str):
    """
    Mark a company as 'target' or 'non_target' for ML training.

    Args:
        company_id: Company ID
        label: 'target' or 'non_target'
    """
    session = get_db_session()

    try:
        # Update parse_metadata with label
        query = text("""
        UPDATE companies
        SET
            parse_metadata = jsonb_set(
                COALESCE(parse_metadata, '{}'::jsonb),
                '{verification,label_human}',
                to_jsonb(:label::text)
            ),
            parse_metadata = jsonb_set(
                parse_metadata,
                '{verification,label_updated_at}',
                to_jsonb(:timestamp::text)
            ),
            active = CASE
                WHEN :label = 'target' THEN true
                WHEN :label = 'non_target' THEN false
                ELSE active
            END
        WHERE id = :company_id
        """)

        session.execute(query, {
            'company_id': company_id,
            'label': label,
            'timestamp': datetime.now().isoformat()
        })
        session.commit()

    finally:
        session.close()


async def run_batch_verification(
    max_companies: Optional[int],
    stats_card,
    progress_bar,
    run_button,
    stop_button,
    companies_table_container
):
    """Run batch verification job in background with progress updates."""
    verification_state.running = True
    verification_state.reset()
    verification_state.start_time = datetime.now()

    # Disable run button, enable stop button
    run_button.disable()
    stop_button.enable()

    # Clear stats
    stats_card.clear()
    with stats_card:
        ui.label('Running verification...').classes('text-lg font-bold')
        stat_labels = {
            'processed': ui.label('Processed: 0'),
            'passed': ui.label('Passed: 0'),
            'failed': ui.label('Failed: 0'),
            'unknown': ui.label('Unknown: 0')
        }

    try:
        ui.notify('Starting batch verification job...', type='info')

        # Build command for subprocess
        import sys
        cmd = [
            sys.executable,
            'db/verify_company_urls.py'
        ]

        if max_companies:
            cmd.extend(['--max-companies', str(max_companies)])

        # Create subprocess runner
        job_id = 'batch_verification'
        runner = SubprocessRunner(job_id, 'logs/batch_verification.log')
        verification_state.subprocess_runner = runner

        # Start subprocess
        pid = runner.start(cmd, cwd=os.getcwd())
        ui.notify(f'Verification job started (PID {pid})', type='positive')

        # Start tailing log file
        if verification_state.log_viewer:
            verification_state.log_viewer.load_last_n_lines(50)
            verification_state.log_viewer.start_tailing()

        # Wait for subprocess to complete (check every 2 seconds)
        while runner.is_running():
            await asyncio.sleep(2.0)

            # Update progress bar (rough estimate based on time)
            elapsed = (datetime.now() - verification_state.start_time).total_seconds()
            if max_companies:
                # Assume ~5 seconds per company
                estimated_done = min(int(elapsed / 5), max_companies)
                progress_bar.value = estimated_done / max_companies

            # Check for cancellation
            if verification_state.is_cancelled():
                ui.notify('Stopping verification job...', type='warning')
                runner.kill()
                break

        # Get final status
        status = runner.get_status()
        return_code = status['return_code']

        if return_code == 0:
            ui.notify('Verification job completed successfully!', type='positive')
        elif return_code == -9:
            ui.notify('Verification job was killed by user', type='warning')
        else:
            ui.notify(f'Verification job exited with code {return_code}', type='negative')

        # Get final stats
        final_stats = get_verification_stats()

        elapsed = (datetime.now() - verification_state.start_time).total_seconds()

        stats_card.clear()
        with stats_card:
            ui.label('Verification Complete!').classes('text-lg font-bold text-green-500')
            ui.label(f'Elapsed: {elapsed:.1f}s').classes('text-sm text-gray-400')
            ui.separator()
            ui.label(f'Passed: {final_stats["passed"]}').classes('text-lg text-green-500')
            ui.label(f'Failed: {final_stats["failed"]}').classes('text-lg text-red-500')
            ui.label(f'Unknown: {final_stats["unknown"]}').classes('text-lg text-yellow-500')
            ui.label(f'Needs Review: {final_stats["needs_review"]}').classes('text-lg text-orange-500')

        progress_bar.value = 1.0

        # Refresh companies table
        await refresh_companies_table(companies_table_container, 'needs_review')

    except Exception as e:
        stats_card.clear()
        with stats_card:
            ui.label('Verification Failed').classes('text-lg font-bold text-red-500')
            ui.label(f'Error: {str(e)}').classes('text-sm text-red-400')

        ui.notify(f'Verification failed: {str(e)}', type='negative')

    finally:
        # Stop tailing log file
        if verification_state.log_viewer:
            verification_state.log_viewer.stop_tailing()

        # Re-enable run button, disable stop button
        verification_state.running = False
        run_button.enable()
        stop_button.disable()
        progress_bar.value = 0


async def stop_verification():
    """Stop the running verification job immediately."""
    if verification_state.running:
        verification_state.cancel()

        if verification_state.subprocess_runner:
            killed = verification_state.subprocess_runner.kill()
            if killed:
                ui.notify('Verification job stopped immediately', type='warning')


async def refresh_companies_table(container, status_filter):
    """Refresh the companies table with current data."""
    companies = await run.io_bound(get_companies_for_review, status_filter, limit=100)

    container.clear()
    with container:
        if not companies:
            ui.label('No companies found matching filter').classes('text-gray-400 italic')
            return

        # Create table
        columns = [
            {'name': 'id', 'label': 'ID', 'field': 'id', 'sortable': True, 'align': 'left'},
            {'name': 'name', 'label': 'Name', 'field': 'name', 'sortable': True, 'align': 'left'},
            {'name': 'domain', 'label': 'Domain', 'field': 'domain', 'sortable': True, 'align': 'left'},
            {'name': 'tier', 'label': 'Tier', 'field': 'tier', 'sortable': True, 'align': 'center'},
            {'name': 'score', 'label': 'Score', 'field': 'score', 'sortable': True, 'align': 'center'},
            {'name': 'status', 'label': 'Status', 'field': 'status', 'sortable': True, 'align': 'center'},
            {'name': 'label', 'label': 'Label', 'field': 'label', 'sortable': True, 'align': 'center'},
            {'name': 'actions', 'label': 'Actions', 'field': 'actions', 'sortable': False, 'align': 'center'}
        ]

        # Transform companies for table
        rows = []
        for company in companies:
            verification = company.get('parse_metadata', {}).get('verification', {})
            rows.append({
                'id': company['id'],
                'name': company['name'] or 'N/A',
                'domain': company['domain'],
                'tier': verification.get('tier', 'N/A'),
                'score': f"{verification.get('score', 0.0):.2f}",
                'status': verification.get('status', 'N/A'),
                'label': verification.get('label_human', 'None'),
                'company_data': company  # Store full data for detail view
            })

        table = ui.table(
            columns=columns,
            rows=rows,
            row_key='id',
            selection='single',
            pagination={'rowsPerPage': 20, 'sortBy': 'score', 'descending': True}
        ).classes('w-full')

        # Add row click handler to show detail view
        def on_row_click(e):
            company_data = e.args[1]['company_data']
            show_company_detail(company_data)

        table.on('row-click', on_row_click)


def show_company_detail(company: Dict):
    """Show detailed verification information for a company in a dialog."""
    verification = company.get('parse_metadata', {}).get('verification', {})

    with ui.dialog() as dialog, ui.card().classes('w-full max-w-4xl'):
        # Header
        with ui.row().classes('w-full items-center justify-between mb-4'):
            ui.label(f'{company["name"]}').classes('text-2xl font-bold')
            ui.badge(verification.get('tier', 'D'), color='primary').classes('text-lg')

        ui.separator()

        # Company info
        with ui.card().classes('w-full bg-gray-800 mb-4'):
            ui.label('Company Information').classes('text-lg font-bold mb-2')
            ui.label(f'Website: {company["website"]}').classes('text-sm')
            ui.label(f'Domain: {company["domain"]}').classes('text-sm')
            if company['phone']:
                ui.label(f'Phone: {company["phone"]}').classes('text-sm')
            if company['email']:
                ui.label(f'Email: {company["email"]}').classes('text-sm')
            if company['service_area']:
                ui.label(f'Service Area: {company["service_area"]}').classes('text-sm')

        # Verification details
        with ui.row().classes('w-full gap-4 mb-4'):
            # Score card
            with ui.card().classes('bg-blue-900 p-4'):
                ui.label('Verification Score').classes('text-sm text-gray-300')
                ui.label(f'{verification.get("score", 0.0):.2%}').classes('text-3xl font-bold text-blue-200')

            # Status card
            status = verification.get('status', 'unknown')
            status_colors = {'passed': 'green', 'failed': 'red', 'unknown': 'yellow'}
            with ui.card().classes(f'bg-{status_colors.get(status, "gray")}-900 p-4'):
                ui.label('Status').classes('text-sm text-gray-300')
                ui.label(status.upper()).classes('text-2xl font-bold')

        # Services detected
        with ui.card().classes('w-full bg-gray-800 mb-4'):
            ui.label('Services Detected').classes('text-lg font-bold mb-2')
            services_detected = verification.get('services_detected', {})

            if services_detected:
                with ui.grid(columns=3).classes('w-full gap-2'):
                    for service_name, flags in services_detected.items():
                        with ui.card().classes('p-3'):
                            ui.label(service_name.title()).classes('text-md font-bold mb-1')
                            ui.label(f"✓ Any" if flags.get('any') else "✗ Any").classes(
                                'text-xs text-green-400' if flags.get('any') else 'text-xs text-gray-500'
                            )
                            ui.label(f"✓ Residential" if flags.get('residential') else "✗ Residential").classes(
                                'text-xs text-green-400' if flags.get('residential') else 'text-xs text-gray-500'
                            )
                            ui.label(f"✓ Commercial" if flags.get('commercial') else "✗ Commercial").classes(
                                'text-xs text-green-400' if flags.get('commercial') else 'text-xs text-gray-500'
                            )
            else:
                ui.label('No services detected').classes('text-gray-400 italic')

        # Positive signals
        with ui.card().classes('w-full bg-gray-800 mb-4'):
            ui.label('Positive Signals').classes('text-lg font-bold mb-2 text-green-400')
            positive_signals = verification.get('positive_signals', [])
            if positive_signals:
                for signal in positive_signals:
                    ui.label(f'✓ {signal}').classes('text-sm text-green-300')
            else:
                ui.label('None').classes('text-gray-400 italic')

        # Negative signals
        with ui.card().classes('w-full bg-gray-800 mb-4'):
            ui.label('Negative Signals').classes('text-lg font-bold mb-2 text-red-400')
            negative_signals = verification.get('negative_signals', [])
            if negative_signals:
                for signal in negative_signals:
                    ui.label(f'✗ {signal}').classes('text-sm text-red-300')
            else:
                ui.label('None').classes('text-gray-400 italic')

        # Manual labeling actions
        ui.separator().classes('my-4')
        ui.label('Manual Override').classes('text-lg font-bold mb-2')

        current_label = verification.get('label_human', None)
        if current_label:
            ui.label(f'Current label: {current_label}').classes('text-sm text-blue-400 mb-2')

        with ui.row().classes('gap-2'):
            async def mark_target():
                mark_company_label(company['id'], 'target')
                ui.notify(f'Marked as TARGET: {company["name"]}', type='positive')
                dialog.close()

            async def mark_non_target():
                mark_company_label(company['id'], 'non_target')
                ui.notify(f'Marked as NON-TARGET: {company["name"]}', type='warning')
                dialog.close()

            ui.button('Mark as TARGET', on_click=mark_target, color='positive', icon='check_circle')
            ui.button('Mark as NON-TARGET', on_click=mark_non_target, color='negative', icon='cancel')
            ui.button('Close', on_click=dialog.close, color='secondary').props('flat')

    dialog.open()


# ==================== Worker Pool Management ====================

def get_worker_pool_state() -> Dict:
    """Read worker pool state from shared state file."""
    state_file = 'logs/verification_workers_state.json'

    if not os.path.exists(state_file):
        return {
            'pool_started_at': None,
            'num_workers': 0,
            'workers': []
        }

    try:
        with open(state_file, 'r') as f:
            return json.load(f)
    except Exception:
        return {
            'pool_started_at': None,
            'num_workers': 0,
            'workers': []
        }


async def start_worker_pool(num_workers: int):
    """Start all verification services (LLM service + workers)."""
    import subprocess

    ui.notify('Starting verification services...', type='info')

    # First, check if LLM service is already running
    llm_running = False
    try:
        result = subprocess.run(
            ['pgrep', '-f', 'llm_service.py'],
            capture_output=True,
            timeout=5
        )
        llm_running = result.returncode == 0
    except Exception:
        pass

    # Start LLM service if not running
    if not llm_running:
        ui.notify('Starting LLM service...', type='info')
        try:
            llm_cmd = [
                sys.executable,
                'verification/llm_service.py'
            ]
            # Start LLM service in background
            subprocess.Popen(
                llm_cmd,
                cwd=os.getcwd(),
                stdout=open('logs/llm_service.log', 'a'),
                stderr=subprocess.STDOUT,
                start_new_session=True
            )
            # Wait for LLM service to initialize
            await asyncio.sleep(2)
            ui.notify('LLM service started', type='positive')
        except Exception as e:
            ui.notify(f'Failed to start LLM service: {e}', type='negative')
            return
    else:
        ui.notify('LLM service already running', type='info')

    # Now start verification workers
    ui.notify(f'Starting {num_workers} verification workers...', type='info')

    # Build command
    cmd = [
        sys.executable,
        'scripts/run_verification_workers.py',
        '--workers', str(num_workers)
    ]

    # Create subprocess runner
    job_id = 'verification_workers'
    runner = SubprocessRunner(job_id, 'logs/verification_workers.log')
    verification_state.worker_pool_subprocess = runner

    # Start subprocess
    try:
        pid = runner.start(cmd, cwd=os.getcwd())
        verification_state.worker_pool_running = True
        ui.notify(f'All verification services started ({num_workers} workers)', type='positive')
    except Exception as e:
        ui.notify(f'Failed to start worker pool: {e}', type='negative')
        verification_state.worker_pool_running = False


async def stop_worker_pool():
    """Stop all verification processes including background workers."""
    import subprocess

    ui.notify('Stopping all verification services...', type='info')

    killed_count = 0

    # Try to kill via subprocess runner first (if available)
    if verification_state.worker_pool_subprocess:
        try:
            if verification_state.worker_pool_subprocess.kill():
                killed_count += 1
        except Exception:
            pass

    # Kill all verification workers and LLM service by pattern
    patterns = [
        'run_verification_workers.py',
        'verification_worker.py',
        'verification/llm_service.py',
        'llm_service.py'
    ]

    for pattern in patterns:
        try:
            # Use pkill to find and kill processes matching pattern
            result = subprocess.run(
                ['pkill', '-f', pattern],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                killed_count += 1
        except Exception:
            pass

    # Also try killing by process name patterns using pgrep + kill
    try:
        result = subprocess.run(
            ['pgrep', '-f', 'verif.*worker'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                try:
                    subprocess.run(['kill', pid], timeout=2)
                    killed_count += 1
                except Exception:
                    pass
    except Exception:
        pass

    verification_state.worker_pool_running = False
    verification_state.worker_pool_subprocess = None

    if killed_count > 0:
        ui.notify(f'Stopped {killed_count} verification service(s)', type='positive')
    else:
        ui.notify('No verification services were running', type='warning')


def verification_page():
    """Render verification review page."""
    ui.label('Verification Review').classes('text-3xl font-bold mb-4')

    # Stats dashboard
    with ui.card().classes('w-full mb-4'):
        ui.label('Verification Statistics').classes('text-xl font-bold mb-4')

        stats = get_verification_stats()

        with ui.grid(columns=4).classes('w-full gap-4'):
            with ui.card().classes('p-4 bg-gray-800'):
                ui.label('Total Verified').classes('text-xs text-gray-400')
                ui.label(str(stats['total'])).classes('text-2xl font-bold')

            with ui.card().classes('p-4 bg-green-900'):
                ui.label('Passed').classes('text-xs text-gray-300')
                ui.label(str(stats['passed'])).classes('text-2xl font-bold text-green-200')

            with ui.card().classes('p-4 bg-red-900'):
                ui.label('Failed').classes('text-xs text-gray-300')
                ui.label(str(stats['failed'])).classes('text-2xl font-bold text-red-200')

            with ui.card().classes('p-4 bg-yellow-900'):
                ui.label('Needs Review').classes('text-xs text-gray-300')
                ui.label(str(stats['needs_review'])).classes('text-2xl font-bold text-yellow-200')

        with ui.grid(columns=2).classes('w-full gap-4 mt-4'):
            with ui.card().classes('p-4 bg-blue-900'):
                ui.label('Labeled: Target').classes('text-xs text-gray-300')
                ui.label(str(stats['labeled_target'])).classes('text-2xl font-bold text-blue-200')

            with ui.card().classes('p-4 bg-purple-900'):
                ui.label('Labeled: Non-Target').classes('text-xs text-gray-300')
                ui.label(str(stats['labeled_non_target'])).classes('text-2xl font-bold text-purple-200')

    # Worker Pool Controls (integrated batch verification)
    with ui.card().classes('w-full mb-4'):
        ui.label('Automated Verification Worker Pool (5 Workers)').classes('text-xl font-bold mb-4')

        ui.label('Continuously process unverified companies from database using 5 parallel workers').classes('text-sm text-gray-400 mb-4')

        # Worker pool buttons
        with ui.row().classes('gap-2 mb-4'):
            start_pool_button = ui.button('START VERIFICATION', icon='play_circle', color='positive')
            stop_pool_button = ui.button('STOP VERIFICATION', icon='stop_circle', color='negative')

            if verification_state.worker_pool_running:
                start_pool_button.disable()
                stop_pool_button.enable()
            else:
                start_pool_button.enable()
                stop_pool_button.disable()


        # Track selected worker for log viewing (use dict instead of ui.state)
        selected_worker = {'id': 0}  # Default to worker 0

        # Debug label to verify rendering
        ui.label('═' * 60).classes('text-gray-600 mb-2')
        ui.label('WORKER STATUS (Always Visible)').classes('text-lg font-bold mb-2 text-yellow-400')

        # Worker status cards container
        worker_status_container = ui.column().classes('w-full')

        # Initial render - always show 5 worker cards
        def render_worker_statuses():
            worker_status_container.clear()

            state = get_worker_pool_state()

            with worker_status_container:
                # Show pool started time if running
                if state.get('pool_started_at'):
                    ui.label(f'Pool started: {state["pool_started_at"]}').classes('text-sm text-gray-400 mb-2')
                else:
                    ui.label('Worker pool stopped').classes('text-sm text-gray-400 mb-2')

                # Always show 5 worker status cards
                with ui.grid(columns=5).classes('w-full gap-4'):
                    # Create status dict for quick lookup
                    worker_status_dict = {w['worker_id']: w for w in state.get('workers', [])}

                    # Always show exactly 5 workers (0-4)
                    for worker_id in range(5):
                        worker_data = worker_status_dict.get(worker_id, {})
                        status = worker_data.get('status', 'stopped')
                        pid = worker_data.get('pid')

                        # Check if this worker is selected
                        is_selected = selected_worker['id'] == worker_id

                        # Color based on status and selection
                        if is_selected:
                            if status == 'running':
                                card_class = 'p-4 bg-green-700 border-4 border-green-400 cursor-pointer'
                                status_color = 'text-green-100'
                                icon = '✓'
                            elif status == 'stopped':
                                card_class = 'p-4 bg-gray-700 border-4 border-gray-400 cursor-pointer'
                                status_color = 'text-gray-300'
                                icon = '○'
                            else:
                                card_class = 'p-4 bg-red-700 border-4 border-red-400 cursor-pointer'
                                status_color = 'text-red-100'
                                icon = '✗'
                        else:
                            if status == 'running':
                                card_class = 'p-4 bg-green-900 cursor-pointer hover:bg-green-800'
                                status_color = 'text-green-200'
                                icon = '✓'
                            elif status == 'stopped':
                                card_class = 'p-4 bg-gray-800 cursor-pointer hover:bg-gray-700'
                                status_color = 'text-gray-400'
                                icon = '○'
                            else:
                                card_class = 'p-4 bg-red-900 cursor-pointer hover:bg-red-800'
                                status_color = 'text-red-200'
                                icon = '✗'

                        # Make card clickable to select worker
                        def make_click_handler(wid):
                            def handler():
                                selected_worker['id'] = wid
                                render_worker_statuses()
                                # Update log viewer to show selected worker's log
                                if verification_state.log_viewer:
                                    verification_state.log_viewer.set_log_file(f'logs/verify_worker_{wid}.log')
                                    verification_state.log_viewer.load_last_n_lines(50)
                            return handler

                        with ui.card().classes(card_class).on('click', make_click_handler(worker_id)):
                            if is_selected:
                                ui.label(f'▶ {icon} Worker {worker_id}').classes('text-sm font-bold mb-1')
                            else:
                                ui.label(f'{icon} Worker {worker_id}').classes('text-sm font-bold mb-1')
                            ui.label(status.upper()).classes(f'text-xs {status_color} font-bold')
                            if pid:
                                ui.label(f'PID: {pid}').classes('text-xs text-gray-400 mt-1')
                            else:
                                ui.label('Not running').classes('text-xs text-gray-500 mt-1')
                            if is_selected:
                                ui.label('(Viewing)').classes('text-xs text-blue-300 mt-1 font-bold')

        # Call render function with error handling
        try:
            render_worker_statuses()
            ui.label('✓ Worker status rendered successfully').classes('text-xs text-green-500')
        except Exception as e:
            ui.label(f'❌ ERROR rendering workers: {str(e)}').classes('text-xs text-red-500 font-bold p-2 bg-red-900')
            import traceback
            ui.label(traceback.format_exc()).classes('text-xs text-red-300 font-mono')

        # Auto-refresh worker status every 5 seconds
        ui.timer(5.0, render_worker_statuses)

        # Button handlers
        async def on_start_pool():
            await start_worker_pool(5)  # Always start 5 workers
            start_pool_button.disable()
            stop_pool_button.enable()
            await asyncio.sleep(3)  # Wait for workers to start
            render_worker_statuses()

            # Start live log tailing for real-time updates
            if verification_state.log_viewer:
                verification_state.log_viewer.load_last_n_lines(50)
                verification_state.log_viewer.start_tailing()

        async def on_stop_pool():
            await stop_worker_pool()
            start_pool_button.enable()
            stop_pool_button.disable()
            await asyncio.sleep(2)  # Wait for workers to stop
            render_worker_statuses()

            # Stop live log tailing
            if verification_state.log_viewer:
                verification_state.log_viewer.stop_tailing()

        start_pool_button.on('click', on_start_pool)
        stop_pool_button.on('click', on_stop_pool)

    # Live log viewer
    with ui.card().classes('w-full mb-4'):
        ui.label('═' * 60).classes('text-gray-600 mb-2')
        ui.label('Worker Log Output (Click worker card to switch)').classes('text-xl font-bold mb-2')

        # Create LiveLogViewer
        log_viewer = LiveLogViewer('logs/verify_worker_0.log', max_lines=500, auto_scroll=True)
        log_viewer.create()
        verification_state.log_viewer = log_viewer

        # Load last 50 lines on page load
        log_viewer.load_last_n_lines(50)

    # Companies review table
    with ui.card().classes('w-full'):
        ui.label('Companies for Review').classes('text-xl font-bold mb-4')

        # Filter selector
        filter_select = ui.select(
            options=['needs_review', 'all', 'passed', 'failed', 'unknown', 'no_label'],
            value='needs_review',
            label='Filter by status'
        ).classes('w-64 mb-4')

        # Refresh button
        refresh_button = ui.button('Refresh', icon='refresh', on_click=lambda: None).props('flat')

        # Companies table container
        companies_table_container = ui.column().classes('w-full')

        # Initial load
        async def initial_load():
            await refresh_companies_table(companies_table_container, 'needs_review')

        asyncio.create_task(initial_load())

        # Bind refresh action
        async def on_filter_change():
            await refresh_companies_table(companies_table_container, filter_select.value)

        filter_select.on('update:model-value', on_filter_change)
        refresh_button.on('click', on_filter_change)

        # Run button handler
        async def start_batch_verification():
            await run_batch_verification(
                int(max_companies_input.value) if max_companies_input.value else None,
                stats_card,
                progress_bar,
                run_button,
                stop_button,
                companies_table_container
            )

        run_button.on('click', start_batch_verification)
        stop_button.on('click', stop_verification)
