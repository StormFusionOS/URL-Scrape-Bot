"""
Job runner integration for Status page.
Runs CLI commands with live streaming to the Status page.
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from .cli_stream import CLIStreamer, job_state
from .history_manager import history_manager


# Add project root to path for runner imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


async def run_discover_job(
    categories: List[str],
    states: List[str],
    pages_per_pair: int,
    on_line_callback: Optional[callable] = None,
    on_complete_callback: Optional[callable] = None
) -> Dict:
    """
    Run discovery job with CLI streaming.

    Args:
        categories: List of category strings
        states: List of state codes
        pages_per_pair: Pages to crawl per category-state pair
        on_line_callback: Called for each output line (line_type, line)
        on_complete_callback: Called when job completes (exit_code, duration, result)

    Returns:
        Result dict with success, message, counts
    """
    # Reset job state
    job_state.reset()
    job_state.active_job = {
        'name': 'Discovery Job',
        'type': 'Discover',
        'args': {
            'categories': categories,
            'states': states,
            'pages_per_pair': pages_per_pair
        },
        'start_time': datetime.now()
    }

    # Build command
    cmd = [
        'python', 'runner/main.py',
        '--discover-only',
        '--categories', ','.join(categories),
        '--states', ','.join(states),
        '--pages-per-pair', str(pages_per_pair)
    ]

    # Create streamer
    streamer = CLIStreamer()
    job_state.streamer = streamer

    # Set up callbacks
    def handle_line(line_type, line):
        if on_line_callback:
            on_line_callback(line_type, line)
        # Parse metrics
        job_state.parse_metrics(line)

    def handle_complete(exit_code, duration):
        # Record in history
        history_manager.add_run(
            job_type='Discover',
            args=job_state.active_job['args'],
            duration_sec=duration,
            exit_code=exit_code,
            counts={
                'found': job_state.metrics.get('items_done', 0),
                'errors': job_state.metrics.get('errors', 0)
            },
            log_path='logs/yp_crawl.log',
            notes=f"Discovered {len(categories)} categories × {len(states)} states"
        )

        result = {
            'success': exit_code == 0,
            'message': f'Discovery completed in {duration:.1f}s' if exit_code == 0 else f'Discovery failed with code {exit_code}',
            'found': job_state.metrics.get('items_done', 0),
            'errors': job_state.metrics.get('errors', 0),
            'exit_code': exit_code,
            'duration': duration
        }

        if on_complete_callback:
            on_complete_callback(exit_code, duration, result)

    # Run command
    await streamer.run_command(
        cmd,
        on_line=handle_line,
        on_complete=handle_complete
    )

    return {
        'success': streamer.exit_code == 0,
        'exit_code': streamer.exit_code,
        'duration': streamer.get_elapsed()
    }


async def run_scrape_job(
    limit: int,
    stale_days: int,
    only_missing_email: bool,
    on_line_callback: Optional[callable] = None,
    on_complete_callback: Optional[callable] = None
) -> Dict:
    """
    Run scraping job with CLI streaming.

    Args:
        limit: Number of companies to scrape
        stale_days: Only scrape companies not updated in N days
        only_missing_email: Only scrape companies missing email
        on_line_callback: Called for each output line (line_type, line)
        on_complete_callback: Called when job completes (exit_code, duration, result)

    Returns:
        Result dict with success, message, counts
    """
    # Reset job state
    job_state.reset()
    job_state.active_job = {
        'name': 'Scrape Job',
        'type': 'Scrape',
        'args': {
            'limit': limit,
            'stale_days': stale_days,
            'only_missing_email': only_missing_email
        },
        'start_time': datetime.now()
    }

    # Build command
    cmd = [
        'python', 'runner/main.py',
        '--scrape-only',
        '--update-limit', str(limit),
        '--stale-days', str(stale_days)
    ]

    if only_missing_email:
        cmd.append('--only-missing-email')

    # Create streamer
    streamer = CLIStreamer()
    job_state.streamer = streamer

    # Set up callbacks
    def handle_line(line_type, line):
        if on_line_callback:
            on_line_callback(line_type, line)
        # Parse metrics
        job_state.parse_metrics(line)

    def handle_complete(exit_code, duration):
        # Record in history
        history_manager.add_run(
            job_type='Scrape',
            args=job_state.active_job['args'],
            duration_sec=duration,
            exit_code=exit_code,
            counts={
                'found': job_state.metrics.get('items_done', 0),
                'updated': job_state.metrics.get('items_done', 0),
                'errors': job_state.metrics.get('errors', 0)
            },
            log_path='logs/update_details.log',
            notes=f"Scraped {limit} companies ({'missing email only' if only_missing_email else 'all stale'})"
        )

        result = {
            'success': exit_code == 0,
            'message': f'Scraping completed in {duration:.1f}s' if exit_code == 0 else f'Scraping failed with code {exit_code}',
            'updated': job_state.metrics.get('items_done', 0),
            'errors': job_state.metrics.get('errors', 0),
            'exit_code': exit_code,
            'duration': duration
        }

        if on_complete_callback:
            on_complete_callback(exit_code, duration, result)

    # Run command
    await streamer.run_command(
        cmd,
        on_line=handle_line,
        on_complete=handle_complete
    )

    return {
        'success': streamer.exit_code == 0,
        'exit_code': streamer.exit_code,
        'duration': streamer.get_elapsed()
    }


def is_job_running() -> bool:
    """Check if a job is currently running."""
    return job_state.active_job is not None and job_state.streamer is not None and job_state.streamer.running


def get_current_job_info() -> Optional[Dict]:
    """Get info about the currently running job."""
    if not job_state.active_job:
        return None

    return {
        'name': job_state.active_job.get('name', 'Unknown'),
        'type': job_state.active_job.get('type', 'Unknown'),
        'args': job_state.active_job.get('args', {}),
        'start_time': job_state.active_job.get('start_time'),
        'running': is_job_running(),
        'metrics': job_state.metrics.copy()
    }
