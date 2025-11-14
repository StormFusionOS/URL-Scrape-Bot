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
        if self.manager_subprocess and self.manager_subprocess.is_running():
            self.manager_subprocess.kill()
        for worker in self.workers.values():
            if worker.subprocess_runner and worker.subprocess_runner.is_running():
                worker.subprocess_runner.kill()
            worker.status = 'stopped'
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


async def run_homeadvisor_discovery(
    categories,
    states,
    pages_per_pair,
    stats_card,
    progress_bar,
    run_button,
    stop_button
):
    """Run HomeAdvisor discovery in background with progress updates."""
    discovery_state.running = True
    discovery_state.reset()
    discovery_state.start_time = datetime.now()

    # Register job in process manager
    job_id = 'discovery_ha'
    process_manager.register(job_id, 'HA Discovery', log_file='logs/ha_crawl.log')

    # Disable run button, enable stop button
    run_button.disable()
    stop_button.enable()

    # Start tailing log file
    if discovery_state.log_viewer:
        discovery_state.log_viewer.load_last_n_lines(50)
        discovery_state.log_viewer.start_tailing()

    # Add initial log messages
    discovery_state.add_log('=' * 60, 'info')
    discovery_state.add_log('Starting HomeAdvisor Discovery', 'info')
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
        ui.notify('Starting HomeAdvisor crawler as subprocess...', type='info')

        # Build command for subprocess
        categories_str = ','.join(categories)
        states_str = ','.join(states)

        cmd = [
            sys.executable,
            'cli_crawl_ha.py',
            '--categories', categories_str,
            '--states', states_str,
            '--pages', str(pages_per_pair)
        ]

        # Create subprocess runner
        runner = SubprocessRunner(job_id, 'logs/ha_crawl.log')
        discovery_state.subprocess_runner = runner

        # Start subprocess
        pid = runner.start(cmd, cwd=os.getcwd())
        ui.notify(f'Crawler started with PID {pid}', type='positive')

        # Update process manager with actual PID
        process_manager.update_pid(job_id, pid)

        # Wait for subprocess to complete (check every second)
        total_pairs = len(categories) * len(states)
        while runner.is_running():
            await asyncio.sleep(1.0)

            # Update progress bar based on time elapsed (rough estimate)
            elapsed = (datetime.now() - discovery_state.start_time).total_seconds()
            # Rough estimate: 20 seconds per pair
            estimated_pairs_done = min(int(elapsed / 20), total_pairs)
            progress_bar.value = estimated_pairs_done / total_pairs if total_pairs > 0 else 0
            stat_labels['progress'].set_text(f"Progress: ~{estimated_pairs_done}/{total_pairs} pairs (estimated)")

            # Check for cancellation
            if discovery_state.is_cancelled():
                ui.notify('Killing crawler process...', type='warning')
                runner.kill()
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
        result = {
            'found': result.get('total_companies', 0),
            'new': result.get('new_7d', 0),
            'updated': 0,
            'errors': 0,
            'pairs_done': total_pairs if return_code == 0 else estimated_pairs_done,
            'pairs_total': total_pairs
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
            'source': 'homeadvisor',
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
        process_manager.mark_completed('discovery_ha', success=not discovery_state.cancel_requested)

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
    process_manager.register(job_id, 'Google Discovery', log_file='logs/google_scrape.log')

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
        ui.notify('Starting Google Maps scraper as subprocess...', type='info')

        # Build command for subprocess
        cmd = [
            sys.executable,
            'cli_crawl_google.py',
            '--query', query,
            '--location', location,
            '--max-results', str(max_results)
        ]

        if scrape_details:
            cmd.append('--scrape-details')

        # Create subprocess runner
        runner = SubprocessRunner(job_id, 'logs/google_scrape.log')
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


def build_google_maps_ui(container):
    """Build Google Maps discovery UI in the given container."""
    with container:
        # Configuration card
        with ui.card().classes('w-full mb-4'):
            ui.label('Google Maps Configuration').classes('text-xl font-bold mb-4')

            # Warning banner
            with ui.card().classes('w-full bg-yellow-900 border-l-4 border-yellow-500 mb-4'):
                ui.label('⚠ Important: Google Maps Scraping Notes').classes('text-lg font-bold text-yellow-200')
                ui.label('• VERY SLOW: 45-90 seconds per business (conservative anti-detection delays)').classes('text-sm text-yellow-100')
                ui.label('• May trigger CAPTCHA: If detected, wait 2-4 hours before retrying').classes('text-sm text-yellow-100')
                ui.label('• Start small: Test with 1-2 businesses first').classes('text-sm text-yellow-100')
                ui.label('• Use specific locations for best results (e.g., "Seattle, WA" not just "WA")').classes('text-sm text-yellow-100')

            # Search configuration
            ui.label('Search Query').classes('font-semibold mb-2')
            query_input = ui.input(
                label='What to search for',
                placeholder='e.g., pressure washing, car wash, plumber',
                value='pressure washing'
            ).classes('w-full mb-4')

            ui.label('Location').classes('font-semibold mb-2')
            location_input = ui.input(
                label='Where to search',
                placeholder='e.g., Seattle, WA or Chicago, IL',
                value='Seattle, WA'
            ).classes('w-full mb-4')

            ui.label('Max Results').classes('font-semibold mb-2')
            max_results_input = ui.number(
                label='Maximum businesses to find',
                value=10,
                min=1,
                max=50,
                step=1
            ).classes('w-64 mb-4')
            ui.label('⚠ More results = longer time (10 businesses ≈ 7-15 minutes)').classes('text-xs text-yellow-400 mb-4')

            # Scrape details checkbox
            scrape_details_checkbox = ui.checkbox(
                'Scrape full business details (phone, website, hours, etc.)',
                value=True
            ).classes('mb-2')
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

                # Set initial button states based on global discovery state
                if discovery_state.running:
                    run_button.disable()
                    stop_button.enable()
                else:
                    run_button.enable()
                    stop_button.disable()

        # Live output with real-time log tailing
        log_viewer = LiveLogViewer('logs/google_scrape.log', max_lines=500, auto_scroll=True)
        log_viewer.create()

        # Store references (log_element set to None - add_log will skip)
        discovery_state.log_viewer = log_viewer
        discovery_state.log_element = None  # Disable old logging, use log viewer instead

        # Run button click handler
        async def start_discovery():
            # Validate Google Maps inputs
            if not query_input.value or not query_input.value.strip():
                ui.notify('Please enter a search query', type='warning')
                return
            if not location_input.value or not location_input.value.strip():
                ui.notify('Please enter a location', type='warning')
                return

            # Run Google Maps discovery
            await run_google_maps_discovery(
                query_input.value.strip(),
                location_input.value.strip(),
                int(max_results_input.value),
                scrape_details_checkbox.value,
                stats_card,
                progress_bar,
                run_button,
                stop_button
            )

        run_button.on('click', start_discovery)
        stop_button.on('click', stop_discovery)


def build_bing_ui(container):
    """Build Bing discovery UI in the given container."""
    with container:
        # Configuration card
        with ui.card().classes('w-full mb-4'):
            ui.label('Bing Discovery Configuration').classes('text-xl font-bold mb-4')

            # Coming soon banner
            with ui.card().classes('w-full bg-blue-900 border-l-4 border-blue-500 mb-4'):
                ui.label('🚧 Bing Discovery - Coming Soon').classes('text-lg font-bold text-blue-200')
                ui.label('• Search businesses on Bing Maps and Bing Local').classes('text-sm text-blue-100')
                ui.label('• Similar functionality to Google Maps discovery').classes('text-sm text-blue-100')
                ui.label('• Will support query and location-based searches').classes('text-sm text-blue-100')

            # Placeholder configuration
            ui.label('Search Query').classes('font-semibold mb-2')
            query_input = ui.input(
                label='What to search for',
                placeholder='e.g., pressure washing, car wash, plumber',
                value='pressure washing'
            ).props('disable').classes('w-full mb-4')

            ui.label('Location').classes('font-semibold mb-2')
            location_input = ui.input(
                label='Where to search',
                placeholder='e.g., Seattle, WA or Chicago, IL',
                value='Seattle, WA'
            ).props('disable').classes('w-full mb-4')

        # Status message
        with ui.card().classes('w-full'):
            ui.label('Status').classes('text-xl font-bold mb-4')
            ui.label('Bing scraper implementation is planned. This will allow discovery of businesses from Bing search results.').classes('text-gray-400')


def build_yelp_ui(container):
    """Build Yelp discovery UI in the given container."""
    with container:
        # Configuration card
        with ui.card().classes('w-full mb-4'):
            ui.label('Yelp Discovery Configuration').classes('text-xl font-bold mb-4')

            # Coming soon banner
            with ui.card().classes('w-full bg-orange-900 border-l-4 border-orange-500 mb-4'):
                ui.label('🚧 Yelp Discovery - Coming Soon').classes('text-lg font-bold text-orange-200')
                ui.label('• Search businesses on Yelp with rich review data').classes('text-sm text-orange-100')
                ui.label('• Includes ratings, reviews, and business hours').classes('text-sm text-orange-100')
                ui.label('• Category and location-based searches').classes('text-sm text-orange-100')

            # Placeholder configuration
            ui.label('Business Category').classes('font-semibold mb-2')
            category_input = ui.input(
                label='Category to search for',
                placeholder='e.g., pressure washing, restaurants, plumbers',
                value='pressure washing'
            ).props('disable').classes('w-full mb-4')

            ui.label('Location').classes('font-semibold mb-2')
            location_input = ui.input(
                label='City and state',
                placeholder='e.g., Seattle, WA',
                value='Seattle, WA'
            ).props('disable').classes('w-full mb-4')

        # Status message
        with ui.card().classes('w-full'):
            ui.label('Status').classes('text-xl font-bold mb-4')
            ui.label('Yelp scraper implementation is planned. This will allow discovery of businesses with Yelp reviews and ratings.').classes('text-gray-400')


def build_bbb_ui(container):
    """Build BBB (Better Business Bureau) discovery UI in the given container."""
    with container:
        # Configuration card
        with ui.card().classes('w-full mb-4'):
            ui.label('BBB Discovery Configuration').classes('text-xl font-bold mb-4')

            # Coming soon banner
            with ui.card().classes('w-full bg-green-900 border-l-4 border-green-500 mb-4'):
                ui.label('🚧 BBB Discovery - Coming Soon').classes('text-lg font-bold text-green-200')
                ui.label('• Search accredited businesses on Better Business Bureau').classes('text-sm text-green-100')
                ui.label('• Includes BBB ratings and complaint history').classes('text-sm text-green-100')
                ui.label('• Useful for finding reputable, established businesses').classes('text-sm text-green-100')

            # Placeholder configuration
            ui.label('Business Type').classes('font-semibold mb-2')
            category_input = ui.input(
                label='Type of business',
                placeholder='e.g., cleaning services, contractors',
                value='cleaning services'
            ).props('disable').classes('w-full mb-4')

            ui.label('Location').classes('font-semibold mb-2')
            location_input = ui.input(
                label='City and state',
                placeholder='e.g., Seattle, WA',
                value='Seattle, WA'
            ).props('disable').classes('w-full mb-4')

        # Status message
        with ui.card().classes('w-full'):
            ui.label('Status').classes('text-xl font-bold mb-4')
            ui.label('BBB scraper implementation is planned. This will allow discovery of accredited businesses with BBB ratings.').classes('text-gray-400')


def build_facebook_ui(container):
    """Build Facebook discovery UI in the given container."""
    with container:
        # Configuration card
        with ui.card().classes('w-full mb-4'):
            ui.label('Facebook Discovery Configuration').classes('text-xl font-bold mb-4')

            # Coming soon banner
            with ui.card().classes('w-full bg-indigo-900 border-l-4 border-indigo-500 mb-4'):
                ui.label('🚧 Facebook Discovery - Coming Soon').classes('text-lg font-bold text-indigo-200')
                ui.label('• Search business pages on Facebook').classes('text-sm text-indigo-100')
                ui.label('• Extract contact info, hours, and page data').classes('text-sm text-indigo-100')
                ui.label('• Note: Facebook scraping has anti-bot protections').classes('text-sm text-indigo-100')

            # Placeholder configuration
            ui.label('Search Query').classes('font-semibold mb-2')
            query_input = ui.input(
                label='Business or service to search',
                placeholder='e.g., pressure washing companies',
                value='pressure washing'
            ).props('disable').classes('w-full mb-4')

            ui.label('Location').classes('font-semibold mb-2')
            location_input = ui.input(
                label='City or region',
                placeholder='e.g., Seattle, WA',
                value='Seattle, WA'
            ).props('disable').classes('w-full mb-4')

        # Status message
        with ui.card().classes('w-full'):
            ui.label('Status').classes('text-xl font-bold mb-4')
            ui.label('Facebook scraper implementation is planned. This will allow discovery of business pages and contact information.').classes('text-gray-400')


def build_homeadvisor_ui(container):
    """Build HomeAdvisor discovery UI in the given container."""
    with container:
        # Configuration card
        with ui.card().classes('w-full mb-4'):
            ui.label('HomeAdvisor Discovery Configuration').classes('text-xl font-bold mb-4')

            # Info banner
            with ui.card().classes('w-full bg-teal-900 border-l-4 border-teal-500 mb-4'):
                ui.label('✨ HomeAdvisor Discovery - Now Available!').classes('text-lg font-bold text-teal-200')
                ui.label('• Search home service professionals on HomeAdvisor').classes('text-sm text-teal-100')
                ui.label('• Extract ratings, reviews, and verified contractor information').classes('text-sm text-teal-100')
                ui.label('• Great source for home improvement and maintenance services').classes('text-sm text-teal-100')

            # Category selection
            ui.label('Service Categories').classes('font-semibold mb-2')
            ui.label('Select categories to search (click to toggle):').classes('text-sm text-gray-400 mb-2')

            # HomeAdvisor categories (from ha_crawl.py)
            HA_CATEGORIES = [
                "power washing",
                "window cleaning services",
                "deck staining or painting",
                "fence painting or staining",
            ]

            category_checkboxes = {}
            with ui.grid(columns=2).classes('w-full gap-2 mb-4'):
                for cat in HA_CATEGORIES:
                    category_checkboxes[cat] = ui.checkbox(cat, value=True).classes('text-sm')

            # Quick select buttons
            with ui.row().classes('gap-2 mb-4'):
                def select_all_categories():
                    for cb in category_checkboxes.values():
                        cb.value = True

                def deselect_all_categories():
                    for cb in category_checkboxes.values():
                        cb.value = False

                ui.button('Select All', icon='check_box', on_click=select_all_categories).props('flat dense')
                ui.button('Deselect All', icon='check_box_outline_blank', on_click=deselect_all_categories).props('flat dense')

            ui.separator()

            # State selection
            ui.label('US States').classes('font-semibold mb-2 mt-4')
            ui.label('Select states to search (click to toggle):').classes('text-sm text-gray-400 mb-2')

            state_checkboxes = {}
            with ui.grid(columns=10).classes('w-full gap-1 mb-4'):
                for state in ALL_STATES:
                    state_checkboxes[state] = ui.checkbox(state, value=False).classes('text-xs')

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

            # Pages per pair
            ui.label('Crawl Settings').classes('font-semibold mb-2 mt-4')
            pages_input = ui.number(
                label='Search Depth',
                value=1,
                min=1,
                max=50,
                step=1
            ).classes('w-64')
            ui.label('⚠ Higher depth = more URLs but slower crawling').classes('text-xs text-yellow-400')

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

                # Set initial button states based on global discovery state
                if discovery_state.running:
                    run_button.disable()
                    stop_button.enable()
                else:
                    run_button.enable()
                    stop_button.disable()

        # Live output with real-time log tailing
        log_viewer = LiveLogViewer('logs/ha_crawl.log', max_lines=500, auto_scroll=True)
        log_viewer.create()

        # Store references (log_element set to None - add_log will skip)
        discovery_state.log_viewer = log_viewer
        discovery_state.log_element = None  # Disable old logging, use log viewer instead

        # Run button click handler
        async def start_discovery():
            # Get selected categories and states
            selected_categories = [cat for cat, cb in category_checkboxes.items() if cb.value]
            selected_states = [state for state, cb in state_checkboxes.items() if cb.value]

            # Validate
            if not selected_categories:
                ui.notify('Please select at least one category', type='warning')
                return
            if not selected_states:
                ui.notify('Please select at least one state', type='warning')
                return

            # Run HomeAdvisor discovery
            await run_homeadvisor_discovery(
                selected_categories,
                selected_states,
                int(pages_input.value),
                stats_card,
                progress_bar,
                run_button,
                stop_button
            )

        run_button.on('click', start_discovery)
        stop_button.on('click', stop_discovery)


def discover_page():
    """Render unified discovery page with source selection."""
    # Version badge to verify code updates
    with ui.row().classes('gap-2 mb-2'):
        ui.label('URL Discovery').classes('text-3xl font-bold')
        ui.badge('v2.0-CITY-FIRST', color='purple').classes('mt-2')

    # Source selection (stays at top)
    with ui.card().classes('w-full mb-4'):
        ui.label('Discovery Source').classes('text-xl font-bold mb-4')

        source_select = ui.select(
            options=['Yellow Pages', 'Multi-Worker YP (10x)', 'Google Maps', 'HomeAdvisor', 'Bing', 'Yelp', 'BBB', 'Facebook'],
            value='Yellow Pages',
            label='Choose discovery source'
        ).classes('w-64')

    # Main content container (will be rebuilt on source change)
    main_content = ui.column().classes('w-full')

    # Build initial content (Yellow Pages by default)
    build_yellow_pages_ui(main_content)

    # Handle source changes - completely rebuild the UI
    def on_source_change(e):
        main_content.clear()
        source = source_select.value

        if source == 'Yellow Pages':
            build_yellow_pages_ui(main_content)
        elif source == 'Multi-Worker YP (10x)':
            build_multiworker_yp_ui(main_content)
        elif source == 'Google Maps':
            build_google_maps_ui(main_content)
        elif source == 'HomeAdvisor':
            build_homeadvisor_ui(main_content)
        elif source == 'Bing':
            build_bing_ui(main_content)
        elif source == 'Yelp':
            build_yelp_ui(main_content)
        elif source == 'BBB':
            build_bbb_ui(main_content)
        elif source == 'Facebook':
            build_facebook_ui(main_content)

    source_select.on('update:model-value', on_source_change)
