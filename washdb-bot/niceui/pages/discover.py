"""
Discovery page - configure and run URL discovery from multiple sources with real-time progress.
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
from pathlib import Path
from scrape_yp.state_assignments import get_states_for_worker, get_proxy_assignments
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
        self.run_button = None  # Reference to run button for state management
        self.stop_button = None  # Reference to stop button for state management
        self.progress_bar = None  # Reference to progress bar for state management

    def cancel(self):
        self.cancel_requested = True

    def is_cancelled(self):
        return self.cancel_requested

    def reset(self):
        self.cancel_requested = False

    def reset_ui_state(self):
        """Reset UI elements to stopped state."""
        self.running = False
        if self.run_button:
            self.run_button.enable()
        if self.stop_button:
            self.stop_button.disable()
        if self.progress_bar:
            self.progress_bar.value = 0

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
    def __init__(self, num_workers: int = 10):
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


def generate_yelp_targets_detached(states, clear_existing=True):
    """Launch Yelp target generation as a detached background process."""
    import subprocess

    cmd = [
        sys.executable,
        '-m', 'scrape_yelp.generate_city_targets',
        '--states', ','.join(states)
    ]

    if clear_existing:
        cmd.append('--clear')

    try:
        # Launch as completely detached background process
        # Redirect output to log file
        log_file = 'logs/generate_yelp_targets.log'
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


async def get_yelp_target_stats(states):
    """Get statistics about Yelp targets for the selected states."""
    try:
        from db.models import YelpTarget
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from dotenv import load_dotenv
        load_dotenv()

        engine = create_engine(os.getenv('DATABASE_URL'))
        Session = sessionmaker(bind=engine)
        session = Session()

        try:
            total = session.query(YelpTarget).filter(YelpTarget.state_id.in_(states)).count()
            planned = session.query(YelpTarget).filter(
                YelpTarget.state_id.in_(states),
                YelpTarget.status == 'PLANNED'
            ).count()
            in_progress = session.query(YelpTarget).filter(
                YelpTarget.state_id.in_(states),
                YelpTarget.status == 'IN_PROGRESS'
            ).count()
            done = session.query(YelpTarget).filter(
                YelpTarget.state_id.in_(states),
                YelpTarget.status == 'DONE'
            ).count()
            failed = session.query(YelpTarget).filter(
                YelpTarget.state_id.in_(states),
                YelpTarget.status == 'FAILED'
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
    process_manager.register(job_id, 'YP Discovery (5-Worker)', log_file='logs/YPContinuous5Workers.log')

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
        ui.notify('Starting YP 5-worker continuous scraper (all 50 states, auto-restart)...', type='info')

        # Build command for 5-worker continuous subprocess
        cmd = [
            sys.executable,  # Python interpreter from venv
            'scripts/yp_continuous_5workers.py'
        ]

        # Create subprocess runner
        runner = SubprocessRunner(job_id, 'logs/YPContinuous5Workers.log')
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



async def run_google_maps_discovery(
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
    discovery_state.running = True
    discovery_state.reset()
    discovery_state.start_time = datetime.now()

    # Register job in process manager
    job_id = 'discovery_google'
    process_manager.register(job_id, 'Google Discovery (Continuous)', log_file='logs/GoogleContinuous.log')

    # Disable run button, enable stop button
    run_button.disable()
    stop_button.enable()

    # Start tailing log file
    if discovery_state.log_viewer:
        discovery_state.log_viewer.load_last_n_lines(50)
        discovery_state.log_viewer.start_tailing()

    # Add initial log messages
    discovery_state.add_log('=' * 60, 'info')
    discovery_state.add_log('GOOGLE MAPS DISCOVERY STARTED', 'success')
    discovery_state.add_log('=' * 60, 'info')
    discovery_state.add_log(f'Query: {query}', 'info')
    discovery_state.add_log(f'Location: {location or "Not specified"}', 'info')
    discovery_state.add_log(f'Max Results: {max_results}', 'info')
    discovery_state.add_log(f'Scrape Details: {scrape_details}', 'info')
    discovery_state.add_log('-' * 60, 'info')

    # Clear stats
    stats_card.clear()
    with stats_card:
        ui.label('Running discovery...').classes('text-lg font-bold')
        stat_labels = {
            'found': ui.label('Found: 0'),
            'saved': ui.label('Saved: 0'),
            'duplicates': ui.label('Duplicates: 0')
        }

    try:
        ui.notify('Starting Google continuous scraper (all 50 states, auto-restart)...', type='info')

        # Build command for continuous subprocess (no args needed - all states hardcoded)
        cmd = [
            sys.executable,
            'scripts/google_continuous.py'
        ]

        # Create subprocess runner
        runner = SubprocessRunner(job_id, 'logs/GoogleContinuous.log')
        discovery_state.subprocess_runner = runner

        # Start subprocess
        pid = runner.start(cmd, cwd=os.getcwd())
        ui.notify(f'Google scraper started with PID {pid}', type='positive')

        # Update process manager with actual PID
        process_manager.update_pid(job_id, pid)

        # Wait for subprocess to complete (check every second)
        while runner.is_running():
            await asyncio.sleep(1.0)

            # Update progress bar (rough estimate based on time)
            elapsed = (datetime.now() - discovery_state.start_time).total_seconds()
            # Google is slow: ~60 seconds per result
            estimated_done = min(int(elapsed / 60), max_results)
            progress_bar.value = estimated_done / max_results if max_results > 0 else 0

            # Check for cancellation
            if discovery_state.is_cancelled():
                ui.notify('Killing scraper process...', type='warning')
                runner.kill()
                break

        # Get final status
        status = runner.get_status()
        return_code = status['return_code']

        if return_code == 0:
            ui.notify('Google scraper completed successfully!', type='positive')
        elif return_code == -9:
            ui.notify('Google scraper was killed by user', type='warning')
        else:
            ui.notify(f'Google scraper exited with code {return_code}', type='negative')

        # Parse results from database (scraper saves directly to DB)
        result = await run.io_bound(backend.kpis)
        result = {
            'found': result.get('total_companies', 0),
            'saved': result.get('new_7d', 0),
            'duplicates': 0  # Don't have this info from subprocess
        }

        # Calculate elapsed time
        elapsed = (datetime.now() - discovery_state.start_time).total_seconds()

        # Log final results
        discovery_state.add_log('-' * 60, 'info')
        discovery_state.add_log('GOOGLE DISCOVERY COMPLETED SUCCESSFULLY!', 'success')
        discovery_state.add_log(f'Duration: {elapsed:.1f}s', 'info')
        discovery_state.add_log(f'Found: {result["found"]} businesses', 'success')
        discovery_state.add_log(f'Saved: {result["saved"]} new businesses', 'success')
        discovery_state.add_log('=' * 60, 'info')

        # Update final stats card
        stats_card.clear()
        with stats_card:
            ui.label('Discovery Complete!').classes('text-lg font-bold text-green-500')
            ui.label(f'Elapsed: {elapsed:.1f}s').classes('text-sm text-gray-400')
            ui.separator()
            ui.label(f'Found: {result["found"]}').classes('text-lg')
            ui.label(f'Saved: {result["saved"]}').classes('text-lg text-green-500')

        # Progress bar to full
        progress_bar.value = 1.0

        # Store summary
        discovery_state.last_run_summary = {
            'source': 'google_maps',
            'elapsed': elapsed,
            'result': result,
            'timestamp': discovery_state.start_time.isoformat()
        }

        # Show notification
        if discovery_state.cancel_requested:
            ui.notify('Google discovery cancelled', type='warning')
        else:
            ui.notify(
                f'Google discovery complete! Found {result["found"]}, Saved {result["saved"]}',
                type='positive'
            )

    except Exception as e:
        discovery_state.add_log('-' * 60, 'error')
        discovery_state.add_log('GOOGLE DISCOVERY FAILED!', 'error')
        discovery_state.add_log(f'Error: {str(e)}', 'error')
        discovery_state.add_log('=' * 60, 'error')

        stats_card.clear()
        with stats_card:
            ui.label('Discovery Failed').classes('text-lg font-bold text-red-500')
            ui.label(f'Error: {str(e)}').classes('text-sm text-red-400')

        ui.notify(f'Google discovery failed: {str(e)}', type='negative')

    finally:
        # Stop tailing log file
        if discovery_state.log_viewer:
            discovery_state.log_viewer.stop_tailing()

        # Mark job as completed in process manager
        process_manager.mark_completed('discovery_google', success=not discovery_state.cancel_requested)

        # Re-enable run button, disable stop button
        discovery_state.running = False
        run_button.enable()
        stop_button.disable()
        progress_bar.value = 0


async def run_google_maps_city_first_discovery(
    stats_card,
    progress_bar,
    run_button,
    stop_button
):
    """Run Google Maps city-first discovery in background with progress updates.

    Note: The 5-worker system automatically handles all 50 states with partitioning.
    No configuration parameters needed - everything is handled by the worker script.
    """
    discovery_state.running = True
    discovery_state.reset()
    discovery_state.start_time = datetime.now()

    # Store button references for stop_discovery to use
    discovery_state.run_button = run_button
    discovery_state.stop_button = stop_button
    discovery_state.progress_bar = progress_bar

    # Register job in process manager
    job_id = 'discovery_google_city_first'
    process_manager.register(job_id, 'Google 5-Worker City-First System', log_file='logs/google_worker_1.log')

    # Disable run button, enable stop button
    run_button.disable()
    stop_button.enable()

    # Start tailing log file (monitor worker 1's log as primary)
    if discovery_state.log_viewer:
        discovery_state.log_viewer.set_log_file('logs/google_worker_1.log')
        discovery_state.log_viewer.load_last_n_lines(50)
        discovery_state.log_viewer.start_tailing()

    # Add initial log messages
    discovery_state.add_log('=' * 60, 'info')
    discovery_state.add_log('GOOGLE MAPS 5-WORKER CITY-FIRST SYSTEM STARTED', 'success')
    discovery_state.add_log('=' * 60, 'info')
    discovery_state.add_log('Workers: 5 parallel workers with state partitioning', 'info')
    discovery_state.add_log('Coverage: All 50 US states', 'info')
    discovery_state.add_log('Log shown: Worker 1 (see logs/google_worker_*.log for others)', 'info')
    discovery_state.add_log('-' * 60, 'info')

    # Clear stats
    stats_card.clear()
    with stats_card:
        ui.label('Running city-first discovery...').classes('text-lg font-bold')
        stat_labels = {
            'targets': ui.label('Targets: 0'),
            'businesses': ui.label('Businesses: 0'),
            'saved': ui.label('Saved: 0'),
            'captchas': ui.label('CAPTCHAs: 0')
        }

    try:
        ui.notify('Starting 5-worker Google Maps city-first scraper system...', type='info')

        # Call the 5-worker start script instead of single process
        cmd = [
            'bash',
            'scripts/google_workers/start_google_workers.sh'
        ]

        # Note: The 5-worker system automatically handles all 50 states with partitioning
        # Individual worker parameters (max_targets, scrape_details) are handled by the script

        # Start the 5-worker system (script launches workers and exits quickly)
        import subprocess
        result = subprocess.run(cmd, cwd=os.getcwd(), capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            ui.notify(f'Failed to start workers: {result.stderr}', type='negative')
            raise Exception(f'Start script failed: {result.stderr}')

        # Wait a moment for PID file to be created
        await asyncio.sleep(2)

        # Verify workers started by checking PID file
        pid_file = Path('logs/google_workers.pid')
        if not pid_file.exists():
            ui.notify('Workers failed to start - no PID file found', type='negative')
            raise Exception('Workers failed to start - no PID file found')

        # Read worker PIDs
        with open(pid_file, 'r') as f:
            worker_pids = [int(line.strip()) for line in f if line.strip()]

        if not worker_pids:
            ui.notify('Workers failed to start - empty PID file', type='negative')
            raise Exception('Workers failed to start - empty PID file')

        ui.notify(f'5-worker system started ({len(worker_pids)} workers)', type='positive')
        ui.notify('Workers deployed: 5 workers processing all 50 states', type='info')

        # Update process manager with first worker PID
        process_manager.update_pid(job_id, worker_pids[0])

        # Monitor workers until stopped or all finish
        # Workers are long-running continuous processes
        while True:
            await asyncio.sleep(2.0)

            # Check if workers are still running
            running_count = 0
            for pid in worker_pids:
                try:
                    result = subprocess.run(['ps', '-p', str(pid)], capture_output=True)
                    if result.returncode == 0:
                        running_count += 1
                except Exception:
                    pass

            # Update progress bar (indeterminate - workers run continuously)
            # Show a pulsing effect between 0.3 and 0.7
            elapsed = (datetime.now() - discovery_state.start_time).total_seconds()
            import math
            progress_bar.value = 0.5 + 0.2 * math.sin(elapsed / 5)

            # Check for cancellation
            if discovery_state.is_cancelled():
                ui.notify('Stopping 5-worker system...', type='warning')
                # Call stop script to gracefully stop all 5 workers
                subprocess.run(['bash', 'scripts/google_workers/stop_google_workers.sh'],
                             cwd=os.getcwd(), capture_output=True)
                break

            # Check if all workers finished
            if running_count == 0:
                ui.notify('All workers have completed!', type='positive')
                break

        # Determine final status
        was_cancelled = discovery_state.is_cancelled()

        if was_cancelled:
            ui.notify('City-first scraper was stopped by user', type='warning')
        else:
            ui.notify('City-first scraper completed successfully!', type='positive')

        # Parse final results from log (simplified - just show completion)
        result = {
            "targets_processed": "all (5-worker system)",
            "success": not was_cancelled
        }

        # Calculate elapsed time
        elapsed = (datetime.now() - discovery_state.start_time).total_seconds()

        # Log final results
        discovery_state.add_log('-' * 60, 'info')
        discovery_state.add_log('CITY-FIRST DISCOVERY COMPLETED SUCCESSFULLY!', 'success')
        discovery_state.add_log(f'Duration: {elapsed:.1f}s', 'info')
        discovery_state.add_log('=' * 60, 'info')

        # Update final stats card
        stats_card.clear()
        with stats_card:
            ui.label('City-First Discovery Complete!').classes('text-lg font-bold text-green-500')
            ui.label(f'Elapsed: {elapsed:.1f}s').classes('text-sm text-gray-400')
            ui.label('Check logs for detailed results').classes('text-sm text-gray-400')

        # Progress bar to full
        progress_bar.value = 1.0

        # Show notification
        if discovery_state.cancel_requested:
            ui.notify('City-first discovery cancelled', type='warning')
        else:
            ui.notify('City-first discovery complete!', type='positive')

    except Exception as e:
        discovery_state.add_log('-' * 60, 'error')
        discovery_state.add_log('CITY-FIRST DISCOVERY FAILED!', 'error')
        discovery_state.add_log(f'Error: {str(e)}', 'error')
        discovery_state.add_log('=' * 60, 'error')

        stats_card.clear()
        with stats_card:
            ui.label('Discovery Failed').classes('text-lg font-bold text-red-500')
            ui.label(f'Error: {str(e)}').classes('text-sm text-red-400')

        ui.notify(f'City-first discovery failed: {str(e)}', type='negative')

    finally:
        # Stop tailing log file
        if discovery_state.log_viewer:
            discovery_state.log_viewer.stop_tailing()

        # Mark job as completed in process manager
        process_manager.mark_completed(job_id, success=not discovery_state.cancel_requested)

        # Re-enable run button, disable stop button
        discovery_state.running = False
        run_button.enable()
        stop_button.disable()
        progress_bar.value = 0


async def stop_discovery():
    """Stop ALL running Google discovery immediately - both foreground and background."""
    import subprocess

    # Set cancel flag regardless of state
    discovery_state.cancel()

    killed_count = 0

    # Step 1: Stop the systemd service (this handles auto-restart)
    try:
        result = subprocess.run(
            ['sudo', 'systemctl', 'stop', 'google-state-workers.service'],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            killed_count += 1
    except Exception as e:
        print(f"Error stopping systemd service: {e}")

    # Step 2: Kill ALL Google-related processes with pkill (instant kill)
    patterns = [
        'cli_crawl_google_city_first',
        'google_continuous_5workers',
        'google_continuous.py'
    ]

    for pattern in patterns:
        try:
            # Use SIGKILL for instant termination
            subprocess.run(['pkill', '-9', '-f', pattern], capture_output=True)
            killed_count += 1
        except Exception:
            pass

    # Step 3: Double-check and force kill any remaining
    try:
        result = subprocess.run(
            ['pgrep', '-f', 'cli_crawl_google'],
            capture_output=True,
            text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                try:
                    subprocess.run(['kill', '-9', pid.strip()], capture_output=True)
                except Exception:
                    pass
    except Exception:
        pass

    # Step 4: Clear the PID file
    pid_file = Path('logs/google_workers.pid')
    if pid_file.exists():
        try:
            pid_file.unlink()
        except Exception:
            pass

    # Step 5: Clear the status file
    status_file = Path('logs/google_workers_status.json')
    if status_file.exists():
        try:
            status_file.unlink()
        except Exception:
            pass

    # Notify user
    ui.notify('All Google workers stopped immediately', type='warning')

    # Try to kill subprocess directly (for GUI-started processes)
    if discovery_state.subprocess_runner:
        try:
            discovery_state.subprocess_runner.kill()
        except Exception:
            pass

    # Stop log tailing
    if discovery_state.log_viewer:
        discovery_state.log_viewer.stop_tailing()

    # Reset UI state (buttons and progress bar) immediately
    discovery_state.running = False
    discovery_state.reset_ui_state()


async def stop_yp_discovery():
    """Stop ALL running YP discovery immediately - both foreground and background."""
    import subprocess

    # Set cancel flag regardless of state
    discovery_state.cancel()

    # Kill ALL YP-related processes with pkill (instant kill, no sudo needed)
    patterns = [
        'cli_crawl_yp',
        'yp_continuous_5workers',
        'yp_continuous.py'
    ]

    for pattern in patterns:
        try:
            # Use SIGKILL for instant termination
            subprocess.run(['pkill', '-9', '-f', pattern], capture_output=True)
            killed_count += 1
        except Exception:
            pass

    # Step 3: Double-check and force kill any remaining
    try:
        result = subprocess.run(
            ['pgrep', '-f', 'cli_crawl_yp'],
            capture_output=True,
            text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                try:
                    subprocess.run(['kill', '-9', pid.strip()], capture_output=True)
                except Exception:
                    pass
    except Exception:
        pass

    # Step 4: Clear the PID file
    pid_file = Path('logs/yp_workers.pid')
    if pid_file.exists():
        try:
            pid_file.unlink()
        except Exception:
            pass

    # Step 5: Clear the status file
    status_file = Path('logs/yp_workers_status.json')
    if status_file.exists():
        try:
            status_file.unlink()
        except Exception:
            pass

    # Notify user
    ui.notify('All YP workers stopped immediately', type='warning')

    # Try to kill subprocess directly (for GUI-started processes)
    if discovery_state.subprocess_runner:
        try:
            discovery_state.subprocess_runner.kill()
        except Exception:
            pass

    # Stop log tailing
    if discovery_state.log_viewer:
        discovery_state.log_viewer.stop_tailing()

    # Reset UI state (buttons and progress bar) immediately
    discovery_state.running = False
    discovery_state.reset_ui_state()


def detect_running_yp_workers():
    """Detect if YP workers are running (systemd service, GUI-started, or external)."""
    import subprocess
    import os

    pid_file = 'logs/yp_workers.pid'
    running_count = 0

    # Method 1: Check systemd service status
    try:
        result = subprocess.run(
            ['systemctl', 'is-active', 'yp-state-workers.service'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.stdout.strip() == 'active':
            # Service is running - count workers via pgrep
            worker_result = subprocess.run(
                ['pgrep', '-cf', 'cli_crawl_yp'],
                capture_output=True,
                text=True
            )
            if worker_result.returncode == 0:
                running_count = int(worker_result.stdout.strip())
            else:
                running_count = 5  # Assume 5 if service is active

            discovery_state.running = True
            return True, running_count
    except Exception as e:
        print(f"Error checking YP systemd service: {e}")

    # Method 2: Check PID file (GUI-started workers)
    try:
        if os.path.exists(pid_file):
            with open(pid_file, 'r') as f:
                pids = [int(line.strip()) for line in f if line.strip()]

            # Check if any PIDs are still running
            for pid in pids[:5]:
                try:
                    result = subprocess.run(['ps', '-p', str(pid)], capture_output=True)
                    if result.returncode == 0:
                        running_count += 1
                except Exception:
                    pass

            if running_count > 0:
                discovery_state.running = True
                return True, running_count

    except Exception as e:
        print(f"Error checking YP PID file: {e}")

    # Method 3: Fallback - Use pgrep to find external workers
    try:
        patterns = ['cli_crawl_yp', 'yp_continuous_5workers']
        for pattern in patterns:
            result = subprocess.run(
                ['pgrep', '-f', pattern],
                capture_output=True, text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                running_count = len(pids)
                discovery_state.running = True
                return True, running_count
    except Exception as e:
        print(f"Error in YP pgrep fallback: {e}")

    # No running workers found
    discovery_state.running = False
    return False, 0


def detect_running_google_workers():
    """Detect if Google workers are running (systemd service, GUI-started, or external)."""
    import subprocess
    import os

    pid_file = 'logs/google_workers.pid'
    running_count = 0

    # Method 1: Check systemd service status
    try:
        result = subprocess.run(
            ['systemctl', 'is-active', 'google-state-workers.service'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.stdout.strip() == 'active':
            # Service is running - count workers via pgrep
            worker_result = subprocess.run(
                ['pgrep', '-cf', 'cli_crawl_google_city_first'],
                capture_output=True,
                text=True
            )
            if worker_result.returncode == 0:
                running_count = int(worker_result.stdout.strip())
            else:
                running_count = 5  # Assume 5 if service is active

            discovery_state.running = True
            return True, running_count
    except Exception as e:
        print(f"Error checking systemd service: {e}")

    # Method 2: Check PID file (GUI-started workers)
    try:
        if os.path.exists(pid_file):
            with open(pid_file, 'r') as f:
                pids = [int(line.strip()) for line in f if line.strip()]

            # Check if any PIDs are still running
            for pid in pids[:5]:
                try:
                    result = subprocess.run(['ps', '-p', str(pid)], capture_output=True)
                    if result.returncode == 0:
                        running_count += 1
                except Exception:
                    pass

            if running_count > 0:
                discovery_state.running = True
                return True, running_count

    except Exception as e:
        print(f"Error checking PID file: {e}")

    # Method 3: Fallback - Use pgrep to find external workers
    try:
        patterns = ['cli_crawl_google_city_first', 'google_continuous_5workers']
        for pattern in patterns:
            result = subprocess.run(
                ['pgrep', '-f', pattern],
                capture_output=True, text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                running_count = len(pids)
                discovery_state.running = True
                return True, running_count
    except Exception as e:
        print(f"Error in pgrep fallback: {e}")

    # No running workers found
    discovery_state.running = False
    return False, 0


def build_yellow_pages_ui(container):
    """Build Yellow Pages discovery UI in the given container."""

    # Check if workers are already running on page load
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

                # Set initial button states based on detection
                if is_running or discovery_state.running:
                    run_button.disable()
                    stop_button.enable()
                else:
                    run_button.enable()
                    stop_button.disable()

        # ====================================================================
        # MULTI-WORKER STATUS DISPLAY (5 Workers)
        # ====================================================================

        # YP Worker State Assignments (matches yp_continuous_5workers.py)
        yp_worker_states = {
            0: ['AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA'],
            1: ['HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD'],
            2: ['MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ'],
            3: ['NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC'],
            4: ['SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY']
        }

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
                    log_viewer_all = LiveLogViewer('logs/yp_workers.log', max_lines=400, auto_scroll=True)
                    log_viewer_all.create()
                    log_viewer_all.load_last_n_lines(100)
                    log_viewer_all.start_tailing()

                # Individual worker logs
                yp_log_viewers = []
                for i in range(5):
                    with ui.tab_panel(yp_worker_tabs[i]):
                        states = yp_worker_states[i]
                        ui.label(f"🌎 States: {', '.join(states)}").classes('text-xs text-gray-400 mb-2')
                        log_viewer = LiveLogViewer(f'logs/state_worker_{i}.log', max_lines=300, auto_scroll=True)
                        log_viewer.create()
                        log_viewer.load_last_n_lines(100)
                        log_viewer.start_tailing()
                        yp_log_viewers.append(log_viewer)

        # Check worker status on page load
        def check_yp_workers_status():
            """Check if YP workers are running and update badges and buttons."""
            import subprocess
            running_count = 0

            try:
                # Method 1: Check systemd service status first
                try:
                    result = subprocess.run(
                        ['systemctl', 'is-active', 'yp-state-workers.service'],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.stdout.strip() == 'active':
                        # Service is active - count actual workers
                        worker_result = subprocess.run(
                            ['pgrep', '-cf', 'cli_crawl_yp'],
                            capture_output=True,
                            text=True
                        )
                        if worker_result.returncode == 0:
                            running_count = int(worker_result.stdout.strip())
                        else:
                            running_count = 5  # Assume 5 if service is active
                except Exception:
                    pass

                # Method 2: Check PID file if systemd not running
                if running_count == 0:
                    pid_file = 'logs/yp_workers.pid'
                    if os.path.exists(pid_file):
                        with open(pid_file, 'r') as f:
                            pids = [int(line.strip()) for line in f if line.strip()]

                        for worker_id, pid in enumerate(pids[:5]):
                            try:
                                result = subprocess.run(['ps', '-p', str(pid)], capture_output=True)
                                if result.returncode == 0:
                                    running_count += 1
                            except Exception:
                                pass

                # Method 3: Fallback - pgrep
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
                    # Workers are running - disable start, enable stop
                    run_button.disable()
                    stop_button.enable()
                    discovery_state.running = True

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
                    # No workers running - enable start, disable stop
                    run_button.enable()
                    stop_button.disable()
                    discovery_state.running = False

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

        # Store references
        discovery_state.log_viewer = log_viewer_all
        discovery_state.log_element = None

        # Run button click handler
        async def start_yp_discovery():
            # Check if workers are already running
            already_running, _ = detect_running_yp_workers()
            if already_running:
                ui.notify('Workers are already running! Stop them first.', type='warning')
                return

            # Start 5-worker system directly (no sudo required)
            import subprocess
            try:
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
                discovery_state.running = True
                await asyncio.sleep(3)
                check_yp_workers_status()
            except Exception as e:
                ui.notify(f'Error starting workers: {e}', type='negative')

        run_button.on('click', start_yp_discovery)
        stop_button.on('click', stop_yp_discovery)


def build_multiworker_yp_ui(container):
    """
    Build the multi-worker Yellow Pages UI.

    This creates a complete interface for launching and monitoring 10 workers.
    """

    with container:
        # Info banner
        with ui.card().classes('w-full bg-purple-900/20 border-l-4 border-purple-500 mb-4'):
            ui.label('🚀 Multi-Worker Discovery (10x Speed)').classes('text-xl font-bold mb-2')
            ui.label('Launch 10 independent workers, each scraping specific states in parallel.').classes('text-sm text-gray-300')

        # Configuration card
        with ui.card().classes('w-full mb-4'):
            ui.label('Configuration').classes('text-xl font-bold mb-4')

            # Worker count selector
            with ui.row().classes('items-center gap-4 mb-4'):
                ui.label('Number of Workers:').classes('font-semibold')
                worker_count_slider = ui.slider(min=1, max=10, value=10, step=1).props('label-always').classes('w-64')
                worker_count_label = ui.label('10 workers').classes('text-sm text-gray-400')

                def update_worker_count(e):
                    count = int(e.value)
                    worker_count_label.set_text(f'{count} worker{"s" if count != 1 else ""}')

                worker_count_slider.on('update:model-value', update_worker_count)

            ui.separator().classes('my-4')

            # Quick stats
            with ui.row().classes('gap-4'):
                with ui.card().classes('p-3 bg-gray-800'):
                    ui.label('States per Worker').classes('text-xs text-gray-400')
                    ui.label('5-6').classes('text-2xl font-bold text-purple-400')

                with ui.card().classes('p-3 bg-gray-800'):
                    ui.label('Total Proxies').classes('text-xs text-gray-400')
                    ui.label('50').classes('text-2xl font-bold text-blue-400')

                with ui.card().classes('p-3 bg-gray-800'):
                    ui.label('Expected Speed').classes('text-xs text-gray-400')
                    ui.label('30-40/min').classes('text-2xl font-bold text-green-400')

        # Worker Status Grid
        with ui.card().classes('w-full mb-4'):
            ui.label('Worker Status').classes('text-xl font-bold mb-4')

            with ui.grid(columns=5).classes('w-full gap-3'):
                for worker_id in range(10):
                    worker = multi_worker_state.workers[worker_id]

                    with ui.card().classes('p-3 hover:shadow-lg transition-shadow'):
                        # Header
                        with ui.row().classes('items-center justify-between w-full mb-2'):
                            ui.label(f'Worker {worker_id}').classes('font-bold text-sm')
                            worker.status_badge = ui.badge('IDLE', color='grey').classes('text-xs')

                        # Assigned states
                        ui.label(worker.get_display_states()).classes('text-xs text-gray-400 mb-2')

                        # Stats
                        worker.target_label = ui.label('-').classes('text-xs truncate w-full')
                        worker.found_label = ui.label('Processed: 0').classes('text-xs text-gray-300 mt-1')

                        # Progress bar
                        worker.progress_bar = ui.linear_progress(value=0).classes('w-full mt-2')

        # Aggregate Status Card
        with ui.card().classes('w-full mb-4'):
            ui.label('Aggregate Status').classes('text-xl font-bold mb-4')

            # Stats row
            with ui.row().classes('gap-6 mb-4'):
                with ui.column():
                    ui.label('Active Workers').classes('text-sm text-gray-400')
                    active_workers_label = ui.label('0/10').classes('text-2xl font-bold')

                with ui.column():
                    ui.label('Targets Processed').classes('text-sm text-gray-400')
                    total_processed_label = ui.label('0').classes('text-2xl font-bold')

                with ui.column():
                    ui.label('Items Found').classes('text-sm text-gray-400')
                    total_found_label = ui.label('0').classes('text-2xl font-bold')

            # Overall progress
            aggregate_progress = ui.linear_progress(value=0).classes('w-full mb-4')

            # Control buttons
            with ui.row().classes('gap-3'):
                start_button = ui.button('START ALL WORKERS', icon='play_arrow', color='positive').classes('px-6')
                stop_button = ui.button('STOP ALL', icon='stop', color='negative').classes('px-6')
                stop_button.disable()

        # Log Viewer with Tabs
        with ui.card().classes('w-full'):
            ui.label('Live Output').classes('text-xl font-bold mb-2')

            # Tab selector for workers
            with ui.tabs().classes('w-full') as tabs:
                tab_all = ui.tab('All Workers')
                worker_tabs = []
                for i in range(10):
                    worker_tabs.append(ui.tab(f'Worker {i}'))

            # Tab panels
            with ui.tab_panels(tabs, value=tab_all).classes('w-full'):
                # All workers merged view
                with ui.tab_panel(tab_all):
                    log_viewer_all = LiveLogViewer('logs/state_worker_pool.log', max_lines=300, auto_scroll=True)
                    log_viewer_all.create()

                # Individual worker logs
                worker_log_viewers = []
                for i in range(10):
                    with ui.tab_panel(worker_tabs[i]):
                        log_viewer = LiveLogViewer(f'logs/state_worker_{i}.log', max_lines=200, auto_scroll=True)
                        log_viewer.create()
                        worker_log_viewers.append(log_viewer)

        # ====================================================================
        # EVENT HANDLERS
        # ====================================================================

        def start_all_workers():
            """Start all workers using the state worker pool manager."""
            try:
                start_button.disable()
                ui.notify('Starting worker pool...', type='info')

                # Build command to launch state worker pool
                cmd = [
                    sys.executable,
                    'scripts/run_state_workers.py',
                    '--workers', str(int(worker_count_slider.value)),
                    '--yes'  # Skip interactive confirmation prompt
                ]

                # Create subprocess runner
                job_id = f'multiworker_yp_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
                runner = SubprocessRunner(job_id, 'logs/state_worker_pool.log')

                # Start the process
                pid = runner.start(cmd, cwd=os.getcwd())

                multi_worker_state.manager_subprocess = runner
                multi_worker_state.running = True

                # Update UI
                for worker in multi_worker_state.workers.values():
                    worker.status = 'running'
                    if worker.status_badge:
                        worker.status_badge.text = 'RUNNING'
                        worker.status_badge.props(f'color={worker.get_status_color()}')

                stop_button.enable()

                # Start monitoring
                log_viewer_all.start_tailing()
                for log_viewer in worker_log_viewers:
                    log_viewer.start_tailing()

                ui.notify(f'Worker pool started! (PID: {pid})', type='positive')

                # Start update timer
                def update_worker_stats():
                    """Update worker statistics from log files."""
                    if not multi_worker_state.running:
                        return

                    # Update active count
                    active_count = multi_worker_state.get_active_count()
                    active_workers_label.set_text(f'{active_count}/{multi_worker_state.num_workers}')

                    # Update totals (parse from logs in real implementation)
                    total_processed = multi_worker_state.get_total_processed()
                    total_found = multi_worker_state.get_total_found()

                    total_processed_label.set_text(str(total_processed))
                    total_found_label.set_text(str(total_found))

                    # Update progress (example: assume 10000 total targets)
                    if total_processed > 0:
                        progress = min(total_processed / 10000, 1.0)
                        aggregate_progress.value = progress

                ui.timer(2.0, update_worker_stats)

            except Exception as e:
                ui.notify(f'Error starting workers: {e}', type='negative')
                start_button.enable()

        def stop_all_workers():
            """Stop all workers."""
            try:
                ui.notify('Stopping all workers...', type='warning')

                multi_worker_state.stop_all()

                # Update UI
                for worker in multi_worker_state.workers.values():
                    if worker.status_badge:
                        worker.status_badge.text = 'STOPPED'
                        worker.status_badge.props('color=warning')

                start_button.enable()
                stop_button.disable()

                log_viewer_all.stop_tailing()
                for log_viewer in worker_log_viewers:
                    log_viewer.stop_tailing()

                ui.notify('All workers stopped', type='info')

            except Exception as e:
                ui.notify(f'Error stopping workers: {e}', type='negative')

        # Bind button handlers
        start_button.on('click', start_all_workers)
        stop_button.on('click', stop_all_workers)

        # ====================================================================
        # CHECK IF WORKERS ARE ALREADY RUNNING (on page load)
        # ====================================================================
        def check_workers_running():
            """Check if workers are already running and update UI accordingly."""
            import subprocess
            try:
                # Check for running state_worker processes
                result = subprocess.run(
                    ['ps', 'aux'],
                    capture_output=True,
                    text=True
                )

                # Count running worker processes
                running_count = 0
                for line in result.stdout.split('\n'):
                    if 'run_state_workers.py' in line and 'grep' not in line:
                        running_count += 1

                # If workers are running, update UI
                if running_count > 0:
                    multi_worker_state.running = True

                    # Update worker statuses
                    for worker in multi_worker_state.workers.values():
                        worker.status = 'running'
                        if worker.status_badge:
                            worker.status_badge.text = 'RUNNING'
                            worker.status_badge.props(f'color={worker.get_status_color()}')

                    # Update buttons
                    start_button.disable()
                    stop_button.enable()

                    # Start log tailing
                    log_viewer_all.start_tailing()
                    for log_viewer in worker_log_viewers:
                        log_viewer.start_tailing()

                    # Update stats
                    active_count = multi_worker_state.get_active_count()
                    active_workers_label.set_text(f'{active_count}/{multi_worker_state.num_workers}')

                    ui.notify(f'Detected {running_count} running worker processes', type='info')

                    # Start update timer
                    def update_worker_stats():
                        """Update worker statistics from log files."""
                        if not multi_worker_state.running:
                            return

                        # Update active count
                        active_count = multi_worker_state.get_active_count()
                        active_workers_label.set_text(f'{active_count}/{multi_worker_state.num_workers}')

                        # Update totals
                        total_processed = multi_worker_state.get_total_processed()
                        total_found = multi_worker_state.get_total_found()

                        total_processed_label.set_text(str(total_processed))
                        total_found_label.set_text(str(total_found))

                        # Update progress
                        if total_processed > 0:
                            progress = min(total_processed / 10000, 1.0)
                            aggregate_progress.value = progress

                    ui.timer(2.0, update_worker_stats)

            except Exception as e:
                # Silently fail - workers just aren't running
                pass

        # Check on page load
        check_workers_running()


def build_google_maps_ui(container):
    """Build Google Maps discovery UI in the given container."""

    # Check if workers are already running on page load
    is_running, running_count = detect_running_google_workers()

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

                # Set initial button states based on detection
                if is_running or discovery_state.running:
                    run_button.disable()
                    stop_button.enable()
                else:
                    run_button.enable()
                    stop_button.disable()

        # ====================================================================
        # MULTI-WORKER STATUS DISPLAY (5 Workers)
        # ====================================================================

        # Google Worker State Assignments (matches start_google_workers.sh)
        google_worker_states = {
            0: ['AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA'],
            1: ['HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD'],
            2: ['MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ'],
            3: ['NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC'],
            4: ['SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY']
        }

        # Worker Status Grid
        with ui.card().classes('w-full mb-4'):
            ui.label('5-Worker System Status').classes('text-xl font-bold mb-4')

            with ui.grid(columns=5).classes('w-full gap-3'):
                google_worker_badges = {}
                google_worker_labels = {}

                for worker_id in range(5):
                    states = google_worker_states[worker_id]

                    with ui.card().classes('p-3 hover:shadow-lg transition-shadow bg-gray-800'):
                        # Header
                        with ui.row().classes('items-center justify-between w-full mb-2'):
                            ui.label(f'Worker {worker_id + 1}').classes('font-bold text-sm text-blue-200')
                            google_worker_badges[worker_id] = ui.badge('CHECKING', color='grey').classes('text-xs')

                        # Assigned states
                        ui.label(f"{', '.join(states[:3])}...").classes('text-xs text-gray-400 mb-2')

                        # Stats placeholder
                        google_worker_labels[worker_id] = ui.label('Ready').classes('text-xs text-gray-300')

        # Live output with tabbed multi-worker log viewers
        with ui.card().classes('w-full'):
            ui.label('Live Worker Output').classes('text-xl font-bold mb-2')

            # Tab selector for workers
            with ui.tabs().classes('w-full') as google_tabs:
                google_tab_all = ui.tab('All Workers')
                google_worker_tabs = []
                for i in range(5):
                    google_worker_tabs.append(ui.tab(f'Worker {i + 1}'))

            # Tab panels
            with ui.tab_panels(google_tabs, value=google_tab_all).classes('w-full'):
                # All workers merged view - shows main activity log
                with ui.tab_panel(google_tab_all):
                    ui.label('📊 Live crawling activity from orchestrator').classes('text-xs text-gray-400 mb-2')
                    log_viewer_all = LiveLogViewer('logs/google_workers.log', max_lines=400, auto_scroll=True)
                    log_viewer_all.create()
                    log_viewer_all.load_last_n_lines(100)
                    log_viewer_all.start_tailing()

                # Individual worker logs
                google_log_viewers = []
                for i in range(5):
                    with ui.tab_panel(google_worker_tabs[i]):
                        states = google_worker_states[i]
                        ui.label(f"🌎 States: {', '.join(states)}").classes('text-xs text-gray-400 mb-2')
                        log_viewer = LiveLogViewer(f'logs/google_state_worker_{i}.log', max_lines=300, auto_scroll=True)
                        log_viewer.create()
                        log_viewer.load_last_n_lines(100)
                        log_viewer.start_tailing()
                        google_log_viewers.append(log_viewer)

        # Check worker status on page load
        def check_google_workers_status():
            """Check if Google workers are running and update badges and buttons."""
            import subprocess
            running_count = 0

            try:
                # Method 1: Check systemd service status first
                try:
                    result = subprocess.run(
                        ['systemctl', 'is-active', 'google-state-workers.service'],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.stdout.strip() == 'active':
                        # Service is active - count actual workers
                        worker_result = subprocess.run(
                            ['pgrep', '-cf', 'cli_crawl_google_city_first'],
                            capture_output=True,
                            text=True
                        )
                        if worker_result.returncode == 0:
                            running_count = int(worker_result.stdout.strip())
                        else:
                            running_count = 5  # Assume 5 if service is active
                except Exception:
                    pass

                # Method 2: Check PID file if systemd not running
                if running_count == 0:
                    pid_file = 'logs/google_workers.pid'
                    if os.path.exists(pid_file):
                        with open(pid_file, 'r') as f:
                            pids = [int(line.strip()) for line in f if line.strip()]

                        for worker_id, pid in enumerate(pids[:5]):
                            try:
                                result = subprocess.run(['ps', '-p', str(pid)], capture_output=True)
                                if result.returncode == 0:
                                    running_count += 1
                            except Exception:
                                pass

                # Method 3: Fallback - pgrep
                if running_count == 0:
                    try:
                        result = subprocess.run(
                            ['pgrep', '-f', 'cli_crawl_google_city_first'],
                            capture_output=True, text=True
                        )
                        if result.returncode == 0 and result.stdout.strip():
                            pids = result.stdout.strip().split('\n')
                            running_count = min(len(pids), 5)
                    except Exception:
                        pass

                # Update badges based on running count
                if running_count > 0:
                    # Workers are running - disable start, enable stop
                    run_button.disable()
                    stop_button.enable()
                    discovery_state.running = True

                    for worker_id in range(5):
                        if worker_id < running_count:
                            if worker_id in google_worker_badges:
                                google_worker_badges[worker_id].set_text('RUNNING')
                                google_worker_badges[worker_id].props('color=positive')
                            if worker_id in google_worker_labels:
                                google_worker_labels[worker_id].set_text('Processing targets...')
                        else:
                            if worker_id in google_worker_badges:
                                google_worker_badges[worker_id].set_text('IDLE')
                                google_worker_badges[worker_id].props('color=grey')
                            if worker_id in google_worker_labels:
                                google_worker_labels[worker_id].set_text('Ready')
                else:
                    # No workers running - enable start, disable stop
                    run_button.enable()
                    stop_button.disable()
                    discovery_state.running = False

                    for worker_id in range(5):
                        if worker_id in google_worker_badges:
                            google_worker_badges[worker_id].set_text('IDLE')
                            google_worker_badges[worker_id].props('color=grey')
                        if worker_id in google_worker_labels:
                            google_worker_labels[worker_id].set_text('Ready')
            except Exception as e:
                print(f"Error checking worker status: {e}")

        # Initial status check
        check_google_workers_status()

        # Periodic status updates
        ui.timer(5.0, check_google_workers_status)

        # Store references
        discovery_state.log_viewer = log_viewer_all
        discovery_state.log_element = None

        # Run button click handler - City-First Discovery
        async def start_discovery():
            # Check if workers are already running
            already_running, _ = detect_running_google_workers()
            if already_running:
                ui.notify('Workers are already running! Stop them first.', type='warning')
                return

            # Run city-first discovery (all 50 states handled by 5-worker system)
            await run_google_maps_city_first_discovery(
                stats_card,
                progress_bar,
                run_button,
                stop_button
            )

        run_button.on('click', start_discovery)
        stop_button.on('click', stop_discovery)


async def run_yelp_city_first_discovery(
    state_ids,
    max_targets,
    scrape_details,
    stats_card,
    progress_bar,
    run_button,
    stop_button
):
    """Run Yelp city-first discovery in background with progress updates."""
    discovery_state.running = True
    discovery_state.reset()
    discovery_state.start_time = datetime.now()

    # Register job in process manager
    job_id = 'discovery_yelp_city_first'
    process_manager.register(job_id, 'Yelp 5-Worker City-First System', log_file='logs/yelp_workers/worker_1.log')

    # Disable run button, enable stop button
    run_button.disable()
    stop_button.enable()

    # Start tailing log file (monitor worker 1's log as primary)
    if discovery_state.log_viewer:
        discovery_state.log_viewer.set_log_file('logs/yelp_workers/worker_1.log')
        discovery_state.log_viewer.load_last_n_lines(50)
        discovery_state.log_viewer.start_tailing()

    # Add initial log messages
    discovery_state.add_log('=' * 60, 'info')
    discovery_state.add_log('YELP 5-WORKER CITY-FIRST SYSTEM STARTED', 'success')
    discovery_state.add_log('=' * 60, 'info')
    discovery_state.add_log('Workers: 5 parallel workers with state partitioning', 'info')
    discovery_state.add_log('Coverage: All 50 US states', 'info')
    discovery_state.add_log(f'Scrape Details: {scrape_details}', 'info')
    discovery_state.add_log('Log shown: Worker 1 (see logs/yelp_workers/worker_*.log for others)', 'info')
    discovery_state.add_log('-' * 60, 'info')

    # Clear stats
    stats_card.clear()
    with stats_card:
        ui.label('Running city-first discovery...').classes('text-lg font-bold')
        stat_labels = {
            'targets': ui.label('Targets: 0'),
            'businesses': ui.label('Businesses: 0'),
            'saved': ui.label('Saved: 0'),
            'captchas': ui.label('CAPTCHAs: 0')
        }

    try:
        ui.notify('Starting 5-worker Yelp city-first scraper system...', type='info')

        # Call the 5-worker start script
        cmd = [
            'bash',
            'scripts/yelp_workers/start_yelp_workers.sh'
        ]

        # Create subprocess runner (uses worker 1's log as primary)
        runner = SubprocessRunner(job_id, 'logs/yelp_workers/worker_1.log')
        discovery_state.subprocess_runner = runner

        # Start the 5-worker system
        pid = runner.start(cmd, cwd=os.getcwd())
        ui.notify(f'5-worker system started (script PID: {pid})', type='positive')
        ui.notify('Workers deployed: 5 workers processing all 50 states', type='info')

        # Update process manager with script PID
        process_manager.update_pid(job_id, pid)

        # Wait for subprocess to complete
        while runner.is_running():
            await asyncio.sleep(1.0)

            # Update progress bar (rough estimate based on time)
            elapsed = (datetime.now() - discovery_state.start_time).total_seconds()
            # City-first: ~30 seconds per target average
            if max_targets:
                estimated_done = min(int(elapsed / 30), max_targets)
                progress_bar.value = estimated_done / max_targets
            else:
                # Indeterminate progress
                progress_bar.value = 0.5

            # Check for cancellation
            if discovery_state.is_cancelled():
                ui.notify('Stopping 5-worker system...', type='warning')
                # Call stop script to gracefully stop all 5 workers
                import subprocess
                subprocess.run(['bash', 'scripts/yelp_workers/stop_yelp_workers.sh'],
                             cwd=os.getcwd(), capture_output=True)
                runner.kill()  # Also kill the start script
                break

        # Get final status
        status = runner.get_status()

        if discovery_state.is_cancelled():
            discovery_state.add_log('=' * 60, 'info')
            discovery_state.add_log('YELP DISCOVERY CANCELLED BY USER', 'warning')
            discovery_state.add_log('=' * 60, 'info')

            stats_card.clear()
            with stats_card:
                ui.label('Discovery cancelled').classes('text-lg text-yellow-500')

            run_button.enable()
            stop_button.disable()
            progress_bar.value = 0

            ui.notify('Yelp discovery cancelled', type='warning')
        elif status['exit_code'] == 0:
            discovery_state.add_log('=' * 60, 'info')
            discovery_state.add_log('YELP DISCOVERY COMPLETED SUCCESSFULLY!', 'success')
            discovery_state.add_log('=' * 60, 'info')

            stats_card.clear()
            with stats_card:
                ui.label('Discovery complete!').classes('text-lg text-green-500 font-bold')
                ui.label('Check logs for detailed results').classes('text-sm')

            run_button.enable()
            stop_button.disable()
            progress_bar.value = 1.0

            ui.notify('Yelp discovery completed successfully!', type='positive')
        else:
            discovery_state.add_log('=' * 60, 'error')
            discovery_state.add_log('YELP DISCOVERY FAILED!', 'error')
            discovery_state.add_log(f'Exit code: {status["exit_code"]}', 'error')
            discovery_state.add_log('=' * 60, 'error')

            stats_card.clear()
            with stats_card:
                ui.label('Discovery failed').classes('text-lg text-red-500 font-bold')
                ui.label(f'Exit code: {status["exit_code"]}').classes('text-sm')

            run_button.enable()
            stop_button.disable()
            progress_bar.value = 0

            ui.notify(f'Yelp discovery failed with exit code {status["exit_code"]}', type='negative')

    except Exception as e:
        discovery_state.add_log('=' * 60, 'error')
        discovery_state.add_log(f'EXCEPTION: {str(e)}', 'error')
        discovery_state.add_log('=' * 60, 'error')

        stats_card.clear()
        with stats_card:
            ui.label('Discovery error').classes('text-lg text-red-500 font-bold')
            ui.label(str(e)).classes('text-sm')

        run_button.enable()
        stop_button.disable()
        progress_bar.value = 0

        ui.notify(f'Yelp discovery failed: {str(e)}', type='negative')

    finally:
        discovery_state.running = False
        discovery_state.subprocess_runner = None
        process_manager.mark_completed('discovery_yelp', success=not discovery_state.cancel_requested)


def build_yelp_ui(container):
    """Build Yelp discovery UI in the given container."""
    with container:
        # Configuration card
        with ui.card().classes('w-full mb-4'):
            ui.label('Yelp Configuration').classes('text-xl font-bold mb-4')

            # City-First Crawl Controls
            ui.label('States to Crawl').classes('font-semibold mb-2')

            # All 50 US states
            all_states = [
                'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
                'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
                'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
                'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
                'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY'
            ]

            # Store checkbox states in a dict
            state_checkboxes = {}

            with ui.card().classes('w-full bg-gray-800 p-4 mb-4'):
                with ui.row().classes('w-full items-center mb-2'):
                    ui.label('Select States').classes('text-sm font-bold text-blue-200')
                    ui.space()
                    select_all_btn = ui.button('Select All', icon='check_box', color='positive').props('size=sm outline')
                    deselect_all_btn = ui.button('Deselect All', icon='check_box_outline_blank', color='warning').props('size=sm outline')

                # Create checkbox grid (10 columns for 50 states = 5 rows)
                with ui.grid(columns=10).classes('w-full gap-2'):
                    for state in all_states:
                        state_checkboxes[state] = ui.checkbox(state, value=True).classes('text-xs')

                # Select/Deselect All functionality
                def select_all():
                    for checkbox in state_checkboxes.values():
                        checkbox.value = True

                def deselect_all():
                    for checkbox in state_checkboxes.values():
                        checkbox.value = False

                select_all_btn.on('click', select_all)
                deselect_all_btn.on('click', deselect_all)

            ui.label('✓ All 50 states selected by default - will process ALL available targets').classes('text-xs text-green-400 mb-4')

            ui.separator().classes('my-4')

            # Step 1: Generate Targets
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

            ui.separator().classes('my-4')

            # Step 2: Crawler Settings
            ui.label('Step 2: Crawler Settings').classes('font-semibold mb-2 mt-4')

            ui.label('Max Targets').classes('font-semibold mb-2')
            max_targets_input = ui.number(
                label='Maximum targets to process (leave empty for all)',
                value=None,
                min=1,
                max=10000,
                step=1
            ).classes('w-64 mb-2')
            ui.label('Limit number of targets to process (useful for testing)').classes('text-xs text-gray-400 mb-3')

            # Scrape details checkbox
            scrape_details_checkbox = ui.checkbox(
                'Scrape full business details',
                value=True
            ).classes('mb-1')
            ui.label('Unchecking will only get basic info (faster but less data)').classes('text-xs text-gray-400')

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
                run_button = ui.button('START DISCOVERY', icon='play_arrow', color='positive')
                stop_button = ui.button('STOP', icon='stop', color='negative')

                # Set initial button states
                if discovery_state.running:
                    run_button.disable()
                    stop_button.enable()
                else:
                    run_button.enable()
                    stop_button.disable()

        # ====================================================================
        # MULTI-WORKER STATUS DISPLAY (5 Workers)
        # ====================================================================

        # Yelp Worker State Assignments (matches start_yelp_workers.sh)
        yelp_worker_states = {
            0: ['AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA'],
            1: ['HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD'],
            2: ['MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ'],
            3: ['NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC'],
            4: ['SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY']
        }

        # Worker Status Grid
        with ui.card().classes('w-full mb-4'):
            ui.label('5-Worker System Status').classes('text-xl font-bold mb-4')

            with ui.grid(columns=5).classes('w-full gap-3'):
                yelp_worker_badges = {}
                yelp_worker_labels = {}

                for worker_id in range(5):
                    states = yelp_worker_states[worker_id]

                    with ui.card().classes('p-3 hover:shadow-lg transition-shadow bg-gray-800'):
                        # Header
                        with ui.row().classes('items-center justify-between w-full mb-2'):
                            ui.label(f'Worker {worker_id + 1}').classes('font-bold text-sm text-blue-200')
                            yelp_worker_badges[worker_id] = ui.badge('CHECKING', color='grey').classes('text-xs')

                        # Assigned states
                        ui.label(f"{', '.join(states[:3])}...").classes('text-xs text-gray-400 mb-2')

                        # Stats placeholder
                        yelp_worker_labels[worker_id] = ui.label('Ready').classes('text-xs text-gray-300')

        # Live output with tabbed multi-worker log viewers
        with ui.card().classes('w-full'):
            ui.label('Live Worker Output').classes('text-xl font-bold mb-2')

            # Tab selector for workers
            with ui.tabs().classes('w-full') as yelp_tabs:
                yelp_tab_all = ui.tab('All Workers')
                yelp_worker_tabs = []
                for i in range(5):
                    yelp_worker_tabs.append(ui.tab(f'Worker {i + 1}'))

            # Tab panels
            with ui.tab_panels(yelp_tabs, value=yelp_tab_all).classes('w-full'):
                # All workers merged view - shows Worker 1 as primary
                with ui.tab_panel(yelp_tab_all):
                    ui.label('📊 Aggregate view - showing Worker 1 log as primary').classes('text-xs text-gray-400 mb-2')
                    log_viewer_all = LiveLogViewer('logs/yelp_workers/worker_0.log', max_lines=400, auto_scroll=True)
                    log_viewer_all.create()
                    log_viewer_all.load_last_n_lines(100)
                    log_viewer_all.start_tailing()

                # Individual worker logs
                yelp_log_viewers = []
                for i in range(5):
                    with ui.tab_panel(yelp_worker_tabs[i]):
                        states = yelp_worker_states[i]
                        ui.label(f"🌎 States: {', '.join(states)}").classes('text-xs text-gray-400 mb-2')
                        log_viewer = LiveLogViewer(f'logs/yelp_workers/worker_{i}.log', max_lines=300, auto_scroll=True)
                        log_viewer.create()
                        log_viewer.load_last_n_lines(100)
                        log_viewer.start_tailing()
                        yelp_log_viewers.append(log_viewer)

        # Check worker status on page load
        def check_yelp_workers_status():
            """Check if Yelp workers are running and update badges."""
            import subprocess
            try:
                # Check for running cli_crawl_yelp.py processes
                result = subprocess.run(['pgrep', '-f', 'cli_crawl_yelp.py'], capture_output=True, text=True)

                if result.returncode == 0 and result.stdout.strip():
                    # Workers are running - count them
                    pids = result.stdout.strip().split('\n')
                    num_running = len(pids)

                    # Update badges for running workers (assume sequential worker IDs)
                    for worker_id in range(min(num_running, 5)):
                        if worker_id in yelp_worker_badges:
                            yelp_worker_badges[worker_id].set_text('RUNNING')
                            yelp_worker_badges[worker_id].props('color=positive')
                        if worker_id in yelp_worker_labels:
                            yelp_worker_labels[worker_id].set_text('Processing targets...')

                    # Mark remaining workers as idle
                    for worker_id in range(num_running, 5):
                        if worker_id in yelp_worker_badges:
                            yelp_worker_badges[worker_id].set_text('IDLE')
                            yelp_worker_badges[worker_id].props('color=grey')
                else:
                    # No workers running
                    for worker_id in range(5):
                        if worker_id in yelp_worker_badges:
                            yelp_worker_badges[worker_id].set_text('IDLE')
                            yelp_worker_badges[worker_id].props('color=grey')
            except Exception as e:
                print(f"Error checking Yelp worker status: {e}")

        # Initial status check
        check_yelp_workers_status()

        # Periodic status updates
        ui.timer(5.0, check_yelp_workers_status)

        # Store references
        discovery_state.log_viewer = log_viewer_all
        discovery_state.log_element = None

        # Helper function to get selected states
        def get_selected_states():
            """Helper function to get list of selected states from checkboxes."""
            return [state for state, checkbox in state_checkboxes.items() if checkbox.value]

        # Helper function to update target stats display
        async def update_target_stats():
            selected_states = get_selected_states()
            if not selected_states:
                target_stats_container.clear()
                with target_stats_container:
                    ui.label('No states selected').classes('text-gray-400 italic')
                return

            stats = await get_yelp_target_stats(selected_states)

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
            selected_states = get_selected_states()

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
                        success, message = generate_yelp_targets_detached(selected_states, clear_existing=True)

                        if success:
                            # Calculate estimated time
                            estimated_minutes = max(2, int(10 * len(selected_states) / 50))
                            ui.notify(
                                f'Target generation started for {len(selected_states)} state(s)! '
                                f'Check logs/generate_yelp_targets.log for progress. Refresh in ~{estimated_minutes} minutes.',
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

        # Run button click handler - City-First Discovery
        async def start_discovery():
            # Get selected states from checkboxes
            selected_states = get_selected_states()

            # Validate city-first inputs
            if not selected_states:
                ui.notify('Please select at least one state', type='warning')
                return

            # Run city-first discovery
            await run_yelp_city_first_discovery(
                selected_states,
                int(max_targets_input.value) if max_targets_input.value else None,
                scrape_details_checkbox.value,
                stats_card,
                progress_bar,
                run_button,
                stop_button
            )

        # Stop button click handler
        def stop_discovery():
            if discovery_state.running and discovery_state.subprocess_runner:
                ui.notify('Stopping Yelp discovery...', type='warning')
                discovery_state.cancel()
            else:
                ui.notify('No discovery is running', type='info')

        run_button.on('click', start_discovery)
        stop_button.on('click', stop_discovery)



def discover_page():
    """Render unified discovery page with source selection."""
    # Version badge to verify code updates
    with ui.row().classes('gap-2 mb-2'):
        ui.label('URL Discovery').classes('text-3xl font-bold')
        ui.badge('v3.0-MULTI-WORKER', color='purple').classes('mt-2')

    # Source selection
    with ui.card().classes('w-full mb-4'):
        ui.label('Discovery Source').classes('text-xl font-bold mb-4')

        source_select = ui.select(
            options=['Google Maps', 'Yellow Pages', 'Yelp'],
            value='Google Maps',
            label='Choose discovery source'
        ).classes('w-64')

    # Main content container (will be rebuilt on source change)
    main_content = ui.column().classes('w-full')

    # Build initial content (Google Maps by default)
    build_google_maps_ui(main_content)

    # Handle source changes - completely rebuild the UI
    def on_source_change(e):
        main_content.clear()
        source = source_select.value

        if source == 'Google Maps':
            build_google_maps_ui(main_content)
        elif source == 'Yellow Pages':
            # Import YP UI function
            from .yp_discover import build_multiworker_yp_ui
            build_multiworker_yp_ui(main_content)
        elif source == 'Yelp':
            build_yelp_ui(main_content)

    source_select.on('update:model-value', on_source_change)
