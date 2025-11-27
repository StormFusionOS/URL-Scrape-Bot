"""
Yellow Pages Discovery page - configure and run YP discovery with 5-worker system and real-time progress.
"""

from nicegui import ui, run
from ..backend_facade import backend
from ..widgets.live_log_viewer import LiveLogViewer
from ..utils.process_manager import process_manager
from ..utils.subprocess_runner import SubprocessRunner
from datetime import datetime
import asyncio
import sys
import os
from scrape_yp.state_assignments_5worker import get_states_for_worker, get_proxy_assignments
from typing import Dict, Optional


# Global state for discovery
class DiscoveryState:
    def __init__(self):
        self.running = False
        self.cancel_requested = False
        self.last_run_summary = None
        self.start_time = None
        self.log_element = None
        self.log_viewer = None  # LiveLogViewer instance
        self.subprocess_runner = None  # SubprocessRunner instance for instant kill

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


# Multi-Worker State Management
class WorkerState:
    """State for a single worker in the multi-worker system."""
    def __init__(self, worker_id: int):
        self.worker_id = worker_id
        self.status = 'idle'  # idle, running, stopped, error
        self.assigned_states = get_states_for_worker(worker_id)
        self.current_target = None
        self.targets_processed = 0
        self.items_found = 0
        self.start_time = None
        self.subprocess_runner = None
        self.log_file = f'logs/state_worker_{worker_id}.log'
        self.status_badge = None
        self.target_label = None
        self.found_label = None
        self.progress_bar = None

    def get_display_states(self) -> str:
        return ', '.join(self.assigned_states)

    def get_status_color(self) -> str:
        color_map = {'idle': 'grey', 'running': 'positive', 'stopped': 'warning', 'error': 'negative'}
        return color_map.get(self.status, 'grey')


class MultiWorkerState:
    """Global state for multi-worker system."""
    def __init__(self, num_workers: int = 5):
        self.num_workers = num_workers
        self.workers: Dict[int, WorkerState] = {}
        self.running = False
        self.manager_subprocess = None
        for i in range(num_workers):
            self.workers[i] = WorkerState(i)

    def get_active_count(self) -> int:
        return sum(1 for w in self.workers.values() if w.status == 'running')

    def get_total_processed(self) -> int:
        return sum(w.targets_processed for w in self.workers.values())

    def get_total_found(self) -> int:
        return sum(w.items_found for w in self.workers.values())

    def stop_all(self):
        """Stop all workers - both GUI-tracked and external processes."""
        import subprocess as sp

        # First, kill GUI-tracked processes
        if self.manager_subprocess and self.manager_subprocess.is_running():
            self.manager_subprocess.kill()
        for worker in self.workers.values():
            if worker.subprocess_runner and worker.subprocess_runner.is_running():
                worker.subprocess_runner.kill()
            worker.status = 'stopped'

        # Second, find and kill ALL worker processes on the system
        # (including those started externally, not from GUI)
        try:
            from niceui.utils.process_manager import find_and_kill_processes_by_name

            # Kill all worker processes using cross-platform process manager
            patterns = ['run_state_workers', 'worker_pool', 'state_worker_']
            killed_count = find_and_kill_processes_by_name(patterns)

            if killed_count > 0:
                print(f"Killed {killed_count} worker processes")

        except Exception as e:
            print(f"Error finding/killing external workers: {e}")

        self.running = False


multi_worker_state = MultiWorkerState()


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


def generate_yp_targets_detached(states, clear_existing=True):
    """Launch Yellow Pages target generation as a detached background process."""
    import subprocess

    cmd = [
        sys.executable,
        '-m', 'scrape_yp.generate_city_targets',
        '--states', ','.join(states)
    ]

    if clear_existing:
        cmd.append('--clear')

    try:
        # Launch as completely detached background process
        # Redirect output to log file
        log_file = 'logs/generate_targets.log'
        with open(log_file, 'w') as f:
            proc = subprocess.Popen(
                cmd,
                cwd=os.getcwd(),
                stdout=f,
                stderr=subprocess.STDOUT,
                start_new_session=True  # Detach from parent process
            )

        return True, f"Target generation started (PID: {proc.pid}). Check {log_file} for progress."
    except Exception as e:
        return False, str(e)


async def get_yp_target_stats(states):
    """Get statistics about Yellow Pages targets for the selected states."""
    try:
        from db.models import YPTarget
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from dotenv import load_dotenv
        load_dotenv()

        engine = create_engine(os.getenv('DATABASE_URL'))
        Session = sessionmaker(bind=engine)
        session = Session()

        try:
            total = session.query(YPTarget).filter(YPTarget.state_id.in_(states)).count()
            planned = session.query(YPTarget).filter(
                YPTarget.state_id.in_(states),
                YPTarget.status == 'planned'
            ).count()
            in_progress = session.query(YPTarget).filter(
                YPTarget.state_id.in_(states),
                YPTarget.status == 'in_progress'
            ).count()
            done = session.query(YPTarget).filter(
                YPTarget.state_id.in_(states),
                YPTarget.status == 'done'
            ).count()
            failed = session.query(YPTarget).filter(
                YPTarget.state_id.in_(states),
                YPTarget.status == 'failed'
            ).count()

            return {
                'total': total,
                'planned': planned,
                'in_progress': in_progress,
                'done': done,
                'failed': failed
            }
        finally:
            session.close()

    except Exception as e:
        return None


async def run_yellow_pages_discovery(
    states,
    max_targets,
    stats_card,
    progress_bar,
    run_button,
    stop_button,
    min_score=50.0,
    include_sponsored=False,
    enable_monitoring=True,
    enable_adaptive_rate_limiting=True,
    enable_session_breaks=True
):
    """Run Yellow Pages city-first discovery in background with progress updates."""
    discovery_state.running = True
    discovery_state.reset()
    discovery_state.start_time = datetime.now()

    # Register job in process manager
    job_id = 'discovery_yp'
    process_manager.register(job_id, 'YP Discovery', log_file='logs/yp_crawl_city_first.log')

    # Disable run button, enable stop button
    run_button.disable()
    stop_button.enable()

    # Start tailing log file
    if discovery_state.log_viewer:
        discovery_state.log_viewer.load_last_n_lines(50)  # Load last 50 lines first
        discovery_state.log_viewer.start_tailing()

    # Add initial log messages
    discovery_state.add_log('=' * 60, 'info')
    discovery_state.add_log('Starting Yellow Pages Discovery (City-First)', 'info')
    discovery_state.add_log('=' * 60, 'info')
    discovery_state.add_log(f'States: {", ".join(states)}', 'info')
    discovery_state.add_log(f'Max Targets: {max_targets or "All"}', 'info')
    discovery_state.add_log(f'Min Score: {min_score}', 'info')
    discovery_state.add_log(f'Include Sponsored: {include_sponsored}', 'info')
    discovery_state.add_log('-' * 60, 'info')
    discovery_state.add_log(f'Monitoring: {"Enabled" if enable_monitoring else "Disabled"}', 'info')
    discovery_state.add_log(f'Adaptive Rate Limiting: {"Enabled" if enable_adaptive_rate_limiting else "Disabled"}', 'info')
    discovery_state.add_log(f'Session Breaks: {"Enabled" if enable_session_breaks else "Disabled"}', 'info')
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
            'progress': ui.label('Progress: 0/0 targets')
        }

    try:
        ui.notify('Starting YP city-first crawler as subprocess...', type='info')

        # Build command for subprocess (NEW CLI arguments)
        states_str = ','.join(states)

        cmd = [
            sys.executable,  # Python interpreter from venv
            'cli_crawl_yp.py',
            '--states', states_str,
            '--min-score', str(min_score)
        ]

        # Add optional flags
        if include_sponsored:
            cmd.append('--include-sponsored')

        if max_targets:
            cmd.extend(['--max-targets', str(max_targets)])

        # Add monitoring flags
        if not enable_monitoring:
            cmd.append('--disable-monitoring')

        if not enable_adaptive_rate_limiting:
            cmd.append('--disable-adaptive-rate-limiting')

        if not enable_session_breaks:
            cmd.append('--no-session-breaks')

        # Create subprocess runner
        runner = SubprocessRunner(job_id, 'logs/yp_crawl_city_first.log')
        discovery_state.subprocess_runner = runner

        # Start subprocess
        pid = runner.start(cmd, cwd=os.getcwd())
        ui.notify(f'Crawler started with PID {pid}', type='positive')

        # Update process manager with actual PID
        process_manager.update_pid(job_id, pid)

        # Get initial target count
        target_stats = await get_yp_target_stats(states)
        total_targets = target_stats['planned'] if target_stats else max_targets or 0

        # Wait for subprocess to complete (check every second)
        while runner.is_running():
            await asyncio.sleep(1.0)

            # Update progress bar based on time elapsed (rough estimate)
            elapsed = (datetime.now() - discovery_state.start_time).total_seconds()
            # City-first: ~10 seconds per target
            estimated_done = min(int(elapsed / 10), total_targets) if total_targets > 0 else 0
            progress_bar.value = estimated_done / total_targets if total_targets > 0 else 0
            stat_labels['progress'].set_text(f"Progress: ~{estimated_done}/{total_targets} targets (estimated)")

            # Check for cancellation
            if discovery_state.is_cancelled():
                ui.notify('Killing crawler process...', type='warning')
                runner.kill()  # INSTANT KILL!
                break

        # Get final status
        status = runner.get_status()
        return_code = status['return_code']

        if return_code == 0:
            ui.notify('Crawler completed successfully!', type='positive')
        elif return_code == -9:
            ui.notify('Crawler was killed by user', type='warning')
        else:
            ui.notify(f'Crawler exited with code {return_code}', type='negative')

        # Parse results from database (crawler saves directly to DB)
        result = await run.io_bound(backend.kpis)
        final_target_stats = await get_yp_target_stats(states)

        result = {
            'found': result.get('total_companies', 0),
            'new': result.get('new_7d', 0),
            'updated': 0,  # Don't have this info from subprocess
            'errors': 0,  # Check log file for errors
            'targets_done': final_target_stats['done'] if final_target_stats else 0,
            'targets_total': final_target_stats['total'] if final_target_stats else total_targets
        }

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
        discovery_state.add_log(f'Targets processed: {result["targets_done"]}/{result["targets_total"]}', 'info')
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
            ui.label(f'Targets: {result["targets_done"]}/{result["targets_total"]}').classes('text-sm')

        # Update progress bar
        if result["targets_total"] > 0:
            progress_bar.value = result["targets_done"] / result["targets_total"]

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
        # Stop tailing log file
        if discovery_state.log_viewer:
            discovery_state.log_viewer.stop_tailing()

        # Mark job as completed in process manager
        process_manager.mark_completed('discovery_yp', success=not discovery_state.cancel_requested)

        # Re-enable run button, disable stop button
        discovery_state.running = False
        run_button.enable()
        stop_button.disable()
        progress_bar.value = 0



# Google Maps functions removed - this is YP-specific page


async def stop_discovery():
    """Stop the running discovery immediately."""
    if discovery_state.running:
        # Set cancel flag (soft stop)
        discovery_state.cancel()

        # Try to kill subprocess directly (instant hard stop)
        killed = False
        if discovery_state.subprocess_runner:
            killed = discovery_state.subprocess_runner.kill()
            if killed:
                ui.notify('Discovery stopped immediately (subprocess killed)', type='warning')

        # Fallback: Try to kill via process manager if no subprocess runner
        if not killed:
            killed = process_manager.kill('discovery_yp', force=True)
            if killed:
                ui.notify('Discovery stopped immediately (force killed)', type='warning')
            else:
                ui.notify('Stop requested - waiting for current batch to finish', type='info')

        # Stop log tailing
        if discovery_state.log_viewer:
            discovery_state.log_viewer.stop_tailing()


def detect_running_yp_scraper():
    """Detect if a YP scraper is already running and reconnect to it."""
    import subprocess
    import os

    try:
        # Check for running cli_crawl_yp.py processes
        result = subprocess.run(
            ['ps', 'aux'],
            capture_output=True,
            text=True,
            timeout=5
        )

        for line in result.stdout.split('\n'):
            if 'cli_crawl_yp.py' in line and 'grep' not in line:
                # Extract PID
                parts = line.split()
                if len(parts) > 1:
                    pid = int(parts[1])

                    # Verify the process is actually still running
                    try:
                        os.kill(pid, 0)  # Signal 0 checks if process exists without killing it
                    except OSError:
                        # Process doesn't exist anymore
                        continue

                    # Register with process manager if not already registered
                    if not process_manager.get('discovery_yp'):
                        process_manager.register('discovery_yp', 'YP Discovery',
                                                pid=pid,
                                                log_file='logs/yp_crawl_city_first.log')
                        discovery_state.running = True
                        return True, pid
                    else:
                        # Already registered, update state
                        discovery_state.running = True
                        return True, pid
    except Exception as e:
        print(f"Error detecting running scraper: {e}")

    # If we get here, no running scraper found - ensure state is clean
    discovery_state.running = False
    return False, None


def build_yellow_pages_ui(container):
    """Build Yellow Pages City-First discovery UI in the given container."""

    # Check if scraper is already running on page load
    is_running, pid = detect_running_yp_scraper()

    with container:
        # Show reconnection banner if scraper detected
        if is_running:
            with ui.card().classes('w-full bg-green-900 border-l-4 border-green-500 mb-4'):
                ui.label(f'✅ Reconnected to running scraper (PID: {pid})').classes('text-lg font-bold text-green-200')
                ui.label('Live output resumed below. You can stop the scraper at any time.').classes('text-sm text-green-100')

        # Info banner about city-first approach
        with ui.card().classes('w-full bg-purple-900 border-l-4 border-purple-500 mb-4'):
            ui.label('🎯 Yellow Pages City-First Scraper').classes('text-lg font-bold text-purple-200')
            ui.label('• Scrapes 31,254 US cities with population-based prioritization').classes('text-sm text-purple-100')
            ui.label('• Shallow pagination (1-3 pages per city) with early-exit optimization').classes('text-sm text-purple-100')
            ui.label('• 85%+ precision filtering with 10 predefined categories').classes('text-sm text-purple-100')
            ui.label('• Step 1: Generate targets → Step 2: Run crawler').classes('text-sm text-purple-100')

        # Configuration card
        with ui.card().classes('w-full mb-4'):
            ui.label('Yellow Pages Configuration').classes('text-xl font-bold mb-4')

            # State selection
            ui.label('US States').classes('font-semibold mb-2')
            ui.label('Select states to scrape (generates targets for all cities in selected states):').classes('text-sm text-gray-400 mb-2')

            state_checkboxes = {}
            with ui.grid(columns=10).classes('w-full gap-1 mb-4'):
                for state in ALL_STATES:
                    # Rhode Island selected by default for testing
                    state_checkboxes[state] = ui.checkbox(state, value=(state == 'RI')).classes('text-xs')

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

            # Target generation section
            ui.label('Step 1: Generate Targets').classes('font-semibold mb-2 mt-4')
            ui.label('Generate scraping targets (city × category combinations) before running the crawler').classes('text-sm text-gray-400 mb-2')

            # Target stats display (dynamic)
            target_stats_container = ui.column().classes('w-full mb-3')

            with ui.row().classes('gap-2 mb-4 items-center'):
                generate_button = ui.button(
                    'GENERATE TARGETS',
                    icon='add_circle',
                    color='secondary'
                ).props('size=md')

                refresh_stats_button = ui.button(
                    'Refresh Stats',
                    icon='refresh',
                    on_click=lambda: None  # Will be set below
                ).props('flat dense')

            ui.separator()

            # Crawler settings
            ui.label('Step 2: Crawler Settings').classes('font-semibold mb-2 mt-4')

            # Max targets
            max_targets_input = ui.number(
                label='Max Targets (leave empty for all)',
                value=None,
                min=1,
                max=100000,
                step=10
            ).classes('w-64 mb-2')
            ui.label('Limit number of targets to process (useful for testing)').classes('text-xs text-gray-400 mb-3')

            # Minimum score slider
            min_score_slider = ui.slider(
                min=0,
                max=100,
                value=50,
                step=5
            ).classes('w-full mb-1').props('label-always')
            ui.label('Minimum Confidence Score (lower = more results, higher = better precision)').classes('text-xs text-gray-400 mb-2')

            # Include sponsored checkbox
            include_sponsored_checkbox = ui.checkbox(
                'Include Sponsored/Ad Listings',
                value=False
            ).classes('mb-1')
            ui.label('Check to include paid ads (usually excluded for quality)').classes('text-xs text-gray-400')

            ui.separator().classes('my-4')

            # Monitoring & Anti-Detection Settings
            ui.label('Anti-Detection & Monitoring').classes('font-semibold mb-2 mt-2')
            ui.label('Enhanced monitoring and stealth features (recommended for production)').classes('text-xs text-gray-400 mb-2')

            with ui.column().classes('gap-2'):
                enable_monitoring_checkbox = ui.checkbox(
                    '✓ Enable Monitoring & Health Checks',
                    value=True
                ).classes('text-sm')
                ui.label('Real-time metrics, CAPTCHA detection, health monitoring').classes('text-xs text-gray-400 ml-6 -mt-2')

                enable_adaptive_rate_limiting_checkbox = ui.checkbox(
                    '✓ Enable Adaptive Rate Limiting',
                    value=True
                ).classes('text-sm')
                ui.label('Automatically slows down on errors, speeds up on success').classes('text-xs text-gray-400 ml-6 -mt-2')

                enable_session_breaks_checkbox = ui.checkbox(
                    '✓ Enable Session Breaks',
                    value=True
                ).classes('text-sm')
                ui.label('Takes 30-90s breaks every 50 requests for human-like behavior').classes('text-xs text-gray-400 ml-6 -mt-2')

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
                run_button = ui.button('START CRAWLER', icon='play_arrow', color='positive')
                stop_button = ui.button('STOP', icon='stop', color='negative')

                # Set initial button states based on detected or global discovery state
                if discovery_state.running or is_running:
                    run_button.disable()
                    stop_button.enable()
                else:
                    run_button.enable()
                    stop_button.disable()

        # Live output
        with ui.card().classes('w-full'):
            ui.label('Live Crawler Output').classes('text-lg font-bold mb-2')

            log_viewer = LiveLogViewer('logs/yp_crawl_city_first.log', max_lines=500, auto_scroll=True)
            log_viewer.create()

            # If scraper was detected as running, load last 100 lines and start tailing
            if is_running:
                log_viewer.load_last_n_lines(100)
                log_viewer.start_tailing()

            # Store references
            discovery_state.log_viewer = log_viewer
            discovery_state.log_element = None

        # Helper function to update target stats display
        async def update_target_stats():
            selected_states = [state for state, cb in state_checkboxes.items() if cb.value]
            if not selected_states:
                target_stats_container.clear()
                with target_stats_container:
                    ui.label('No states selected').classes('text-gray-400 italic')
                return

            stats = await get_yp_target_stats(selected_states)

            target_stats_container.clear()
            if stats and stats['total'] > 0:
                with target_stats_container:
                    with ui.card().classes('w-full bg-slate-800 p-3'):
                        ui.label('Target Statistics').classes('text-sm font-bold mb-2')
                        with ui.grid(columns=5).classes('gap-2'):
                            ui.label(f'Total: {stats["total"]}').classes('text-xs')
                            ui.label(f'Planned: {stats["planned"]}').classes('text-xs text-blue-400')
                            ui.label(f'In Progress: {stats["in_progress"]}').classes('text-xs text-yellow-400')
                            ui.label(f'Done: {stats["done"]}').classes('text-xs text-green-400')
                            ui.label(f'Failed: {stats["failed"]}').classes('text-xs text-red-400')
            else:
                with target_stats_container:
                    ui.label('No targets generated yet for selected states').classes('text-yellow-400 italic text-sm')

        # Generate targets button handler
        async def handle_generate_targets():
            selected_states = [state for state, cb in state_checkboxes.items() if cb.value]

            if not selected_states:
                ui.notify('Please select at least one state', type='warning')
                return

            # Confirm with user
            with ui.dialog() as dialog, ui.card():
                ui.label('Generate Targets?').classes('text-lg font-bold mb-2')
                ui.label(f'This will generate targets for {len(selected_states)} state(s):').classes('text-sm mb-1')
                ui.label(f'{", ".join(selected_states)}').classes('text-sm text-blue-400 mb-3')
                ui.label('Existing targets for these states will be cleared.').classes('text-xs text-yellow-400 mb-3')

                with ui.row().classes('gap-2'):
                    ui.button('Cancel', on_click=dialog.close).props('flat')
                    async def confirm_generate():
                        dialog.close()

                        # Launch target generation in detached background process
                        success, message = generate_yp_targets_detached(selected_states, clear_existing=True)

                        if success:
                            # Calculate estimated time
                            estimated_minutes = max(2, int(10 * len(selected_states) / 50))
                            ui.notify(
                                f'Target generation started for {len(selected_states)} state(s)! '
                                f'Check logs/generate_targets.log for progress. Refresh in ~{estimated_minutes} minutes.',
                                type='positive',
                                timeout=10000
                            )
                        else:
                            ui.notify(
                                f'Failed to start target generation: {message}',
                                type='negative',
                                timeout=5000
                            )

                    ui.button('Generate', on_click=confirm_generate, color='positive')

            dialog.open()

        generate_button.on('click', handle_generate_targets)
        refresh_stats_button.on('click', update_target_stats)

        # Initialize stats display
        asyncio.create_task(update_target_stats())

        # Run button click handler
        async def start_discovery():
            # Get selected states
            selected_states = [state for state, cb in state_checkboxes.items() if cb.value]

            # Validate
            if not selected_states:
                ui.notify('Please select at least one state', type='warning')
                return

            # Check if targets exist
            stats = await get_yp_target_stats(selected_states)
            if not stats or stats['planned'] == 0:
                ui.notify('No planned targets found. Please generate targets first!', type='warning')
                return

            # Run Yellow Pages city-first discovery
            await run_yellow_pages_discovery(
                selected_states,
                int(max_targets_input.value) if max_targets_input.value else None,
                stats_card,
                progress_bar,
                run_button,
                stop_button,
                min_score=min_score_slider.value,
                include_sponsored=include_sponsored_checkbox.value,
                enable_monitoring=enable_monitoring_checkbox.value,
                enable_adaptive_rate_limiting=enable_adaptive_rate_limiting_checkbox.value,
                enable_session_breaks=enable_session_breaks_checkbox.value
            )

            # Refresh stats after completion
            await update_target_stats()

        run_button.on('click', start_discovery)
        stop_button.on('click', stop_discovery)


# Multi-worker, Google Maps, and Yelp UI functions removed - this is YP-specific single-page


def build_multiworker_yp_ui(container):
    """
    Build the simplified multi-worker Yellow Pages UI.
    Matches the Google Maps UI pattern with systemd service integration.
    """
    import subprocess
    from pathlib import Path

    # YP Worker State Assignments (matches yp_continuous_5workers.py)
    yp_worker_states = {
        0: ['AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA'],
        1: ['HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD'],
        2: ['MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ'],
        3: ['NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC'],
        4: ['SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY']
    }

    def detect_running_yp_workers():
        """Detect if YP workers are running."""
        running_count = 0
        try:
            # Check systemd service status first
            result = subprocess.run(
                ['systemctl', 'is-active', 'yp-5workers.service'],
                capture_output=True, text=True, timeout=5
            )
            if result.stdout.strip() == 'active':
                worker_result = subprocess.run(
                    ['pgrep', '-cf', 'cli_crawl_yp'],
                    capture_output=True, text=True
                )
                if worker_result.returncode == 0:
                    running_count = int(worker_result.stdout.strip())
                else:
                    running_count = 5
                return True, running_count
        except Exception:
            pass

        # Fallback - pgrep
        try:
            result = subprocess.run(
                ['pgrep', '-f', 'cli_crawl_yp'],
                capture_output=True, text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                running_count = min(len(pids), 5)
                return True, running_count
        except Exception:
            pass

        return False, 0

    # Check initial state
    is_running, running_count = detect_running_yp_workers()

    with container:
        # Show reconnection banner if workers detected
        if is_running:
            with ui.card().classes('w-full bg-green-900 border-l-4 border-green-500 mb-4'):
                ui.label(f'Reconnected to running workers ({running_count}/5 active)').classes('text-lg font-bold text-green-200')
                ui.label('Live output resumed below. You can stop the workers at any time.').classes('text-sm text-green-100')

        # Stats and controls
        with ui.card().classes('w-full mb-4'):
            ui.label('Discovery Status').classes('text-xl font-bold mb-4')

            # Stats card
            stats_card = ui.column().classes('w-full mb-4')
            with stats_card:
                if is_running:
                    ui.label(f'Workers running ({running_count}/5 active)').classes('text-lg text-green-400')
                else:
                    ui.label('Ready to start').classes('text-lg')

            # Progress bar
            progress_bar = ui.linear_progress(value=0).classes('w-full mb-4')

            # Control buttons
            with ui.row().classes('gap-2'):
                run_button = ui.button('START DISCOVERY', icon='play_arrow', color='positive')
                stop_button = ui.button('STOP', icon='stop', color='negative')

                # Set initial button states
                if is_running:
                    run_button.disable()
                    stop_button.enable()
                else:
                    run_button.enable()
                    stop_button.disable()

        # Worker Status Grid
        with ui.card().classes('w-full mb-4'):
            ui.label('5-Worker System Status').classes('text-xl font-bold mb-4')

            with ui.grid(columns=5).classes('w-full gap-3'):
                yp_worker_badges = {}
                yp_worker_labels = {}

                for worker_id in range(5):
                    states = yp_worker_states[worker_id]

                    with ui.card().classes('p-3 hover:shadow-lg transition-shadow bg-gray-800'):
                        # Header
                        with ui.row().classes('items-center justify-between w-full mb-2'):
                            ui.label(f'Worker {worker_id + 1}').classes('font-bold text-sm text-purple-200')
                            yp_worker_badges[worker_id] = ui.badge('CHECKING', color='grey').classes('text-xs')

                        # Assigned states
                        ui.label(f"{', '.join(states[:3])}...").classes('text-xs text-gray-400 mb-2')

                        # Stats placeholder
                        yp_worker_labels[worker_id] = ui.label('Ready').classes('text-xs text-gray-300')

        # Live output with tabbed multi-worker log viewers
        with ui.card().classes('w-full'):
            ui.label('Live Worker Output').classes('text-xl font-bold mb-2')

            # Tab selector for workers
            with ui.tabs().classes('w-full') as yp_tabs:
                yp_tab_all = ui.tab('All Workers')
                yp_worker_tabs = []
                for i in range(5):
                    yp_worker_tabs.append(ui.tab(f'Worker {i + 1}'))

            # Tab panels
            with ui.tab_panels(yp_tabs, value=yp_tab_all).classes('w-full'):
                # All workers merged view - shows main orchestrator log
                with ui.tab_panel(yp_tab_all):
                    ui.label('📊 Live crawling activity from orchestrator').classes('text-xs text-gray-400 mb-2')
                    log_viewer_all = LiveLogViewer('logs/YPContinuous5Workers.log', max_lines=400, auto_scroll=True)
                    log_viewer_all.create()
                    log_viewer_all.load_last_n_lines(100)
                    log_viewer_all.start_tailing()

                # Individual worker logs
                yp_log_viewers = []
                for i in range(5):
                    with ui.tab_panel(yp_worker_tabs[i]):
                        states = yp_worker_states[i]
                        ui.label(f"🌎 States: {', '.join(states)}").classes('text-xs text-gray-400 mb-2')
                        log_viewer = LiveLogViewer(f'logs/yp_worker_{i + 1}.log', max_lines=300, auto_scroll=True)
                        log_viewer.create()
                        log_viewer.load_last_n_lines(100)
                        log_viewer.start_tailing()
                        yp_log_viewers.append(log_viewer)

        # Check worker status and update UI
        def check_yp_workers_status():
            """Check if YP workers are running and update badges and buttons."""
            running_count = 0

            try:
                # Check systemd service status first
                try:
                    result = subprocess.run(
                        ['systemctl', 'is-active', 'yp-5workers.service'],
                        capture_output=True, text=True, timeout=5
                    )
                    if result.stdout.strip() == 'active':
                        worker_result = subprocess.run(
                            ['pgrep', '-cf', 'cli_crawl_yp'],
                            capture_output=True, text=True
                        )
                        if worker_result.returncode == 0:
                            running_count = int(worker_result.stdout.strip())
                        else:
                            running_count = 5
                except Exception:
                    pass

                # Fallback - pgrep
                if running_count == 0:
                    try:
                        result = subprocess.run(
                            ['pgrep', '-f', 'cli_crawl_yp'],
                            capture_output=True, text=True
                        )
                        if result.returncode == 0 and result.stdout.strip():
                            pids = result.stdout.strip().split('\n')
                            running_count = min(len(pids), 5)
                    except Exception:
                        pass

                # Update badges based on running count
                if running_count > 0:
                    run_button.disable()
                    stop_button.enable()

                    for worker_id in range(5):
                        if worker_id < running_count:
                            if worker_id in yp_worker_badges:
                                yp_worker_badges[worker_id].set_text('RUNNING')
                                yp_worker_badges[worker_id].props('color=positive')
                            if worker_id in yp_worker_labels:
                                yp_worker_labels[worker_id].set_text('Processing targets...')
                        else:
                            if worker_id in yp_worker_badges:
                                yp_worker_badges[worker_id].set_text('IDLE')
                                yp_worker_badges[worker_id].props('color=grey')
                            if worker_id in yp_worker_labels:
                                yp_worker_labels[worker_id].set_text('Ready')
                else:
                    run_button.enable()
                    stop_button.disable()

                    for worker_id in range(5):
                        if worker_id in yp_worker_badges:
                            yp_worker_badges[worker_id].set_text('IDLE')
                            yp_worker_badges[worker_id].props('color=grey')
                        if worker_id in yp_worker_labels:
                            yp_worker_labels[worker_id].set_text('Ready')
            except Exception as e:
                print(f"Error checking YP worker status: {e}")

        # Initial status check
        check_yp_workers_status()

        # Periodic status updates
        ui.timer(5.0, check_yp_workers_status)

        # Start button handler
        async def start_yp_discovery():
            """Start YP 5-worker system directly (no sudo required)."""
            # Check if already running
            is_running, _ = detect_running_yp_workers()
            if is_running:
                ui.notify('Workers are already running! Stop them first.', type='warning')
                return

            try:
                # Start the 5-worker script directly as a background process
                import sys
                cmd = [
                    sys.executable,
                    'scripts/yp_continuous_5workers.py'
                ]

                # Launch as detached background process
                process = subprocess.Popen(
                    cmd,
                    cwd='/home/rivercityscrape/URL-Scrape-Bot/washdb-bot',
                    stdout=open('logs/YPContinuous5Workers.log', 'a'),
                    stderr=subprocess.STDOUT,
                    start_new_session=True  # Detach from parent
                )

                ui.notify(f'YP 5-worker system started! (PID: {process.pid})', type='positive')
                run_button.disable()
                stop_button.enable()
                await asyncio.sleep(3)
                check_yp_workers_status()
            except Exception as e:
                ui.notify(f'Error starting workers: {e}', type='negative')

        # Stop button handler
        async def stop_yp_discovery():
            """Stop ALL running YP discovery immediately (no sudo required)."""
            ui.notify('Stopping all YP workers...', type='warning')

            # Kill all YP processes (pkill works without sudo for same-user processes)
            patterns = ['cli_crawl_yp', 'yp_continuous_5workers', 'yp_continuous.py']
            for pattern in patterns:
                try:
                    subprocess.run(['pkill', '-9', '-f', pattern], capture_output=True)
                except Exception:
                    pass

            # Clear PID and status files
            for f in ['logs/yp_workers.pid', 'logs/yp_workers_status.json']:
                try:
                    Path(f).unlink()
                except Exception:
                    pass

            ui.notify('All YP workers stopped', type='info')
            run_button.enable()
            stop_button.disable()
            await asyncio.sleep(1)
            check_yp_workers_status()

        # Bind button handlers
        run_button.on('click', start_yp_discovery)
        stop_button.on('click', stop_yp_discovery)


def yp_discover_page():
    """Render Yellow Pages Discovery page with 5-worker city-first approach."""
    # Page header
    with ui.row().classes('gap-2 mb-2'):
        ui.label('Yellow Pages Discovery').classes('text-3xl font-bold')
        ui.badge('v2.0-5-WORKER', color='purple').classes('mt-2')

    # Build multi-worker YP UI directly (no tabs)
    build_multiworker_yp_ui(ui.column().classes('w-full'))
