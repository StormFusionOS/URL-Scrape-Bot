#!/usr/bin/env python3
"""
Continuous Yellow Pages scraper with 5-worker system.

This script runs 5 parallel workers in an infinite loop with:
- Each worker handles 10 states
- 30-minute cooldown between cycles
- Auto-restart on completion/failure
- Graceful signal handling for clean shutdown

Usage:
    python scripts/yp_continuous_5workers.py
"""
import subprocess
import sys
import time
import os
import signal
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / '.env')

from runner.logging_setup import get_logger

logger = get_logger("YPContinuous5Workers")

# Configuration
COOLDOWN_SECONDS = 1800  # 30 minutes between cycles
CHECK_INTERVAL = 5  # Check worker status every 5 seconds
WORKER_STARTUP_DELAY = 2  # Seconds between starting each worker

# State partitioning for 5 workers (10 states each)
WORKER_STATES = {
    1: ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA"],
    2: ["HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD"],
    3: ["MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ"],
    4: ["NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC"],
    5: ["SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"],
}

# Graceful shutdown flag
shutdown_requested = False
worker_processes: Dict[int, subprocess.Popen] = {}


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    logger.info(f"Received signal {signum}, requesting graceful shutdown...")
    shutdown_requested = True


def start_worker(worker_id: int) -> Optional[subprocess.Popen]:
    """Start a single worker process."""
    states = WORKER_STATES[worker_id]
    log_file = PROJECT_ROOT / 'logs' / f'yp_worker_{worker_id}.log'

    # YP CLI uses comma-separated states
    states_str = ','.join(states)

    cmd = [
        sys.executable,
        '-u',
        str(PROJECT_ROOT / 'cli_crawl_yp.py'),
        '--states', states_str,
        '--worker-id', str(worker_id),
        '--log-file', str(log_file),
    ]

    logger.info(f"Starting Worker {worker_id}: {' '.join(states[:3])}...{' '.join(states[-2:])}")

    try:
        # Start process with output going to log file
        with open(log_file, 'a') as log_fd:
            log_fd.write(f"\n{'='*60}\n")
            log_fd.write(f"WORKER {worker_id} STARTED - {datetime.now().isoformat()}\n")
            log_fd.write(f"{'='*60}\n")
            log_fd.flush()

        process = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            stdout=open(log_file, 'a'),
            stderr=subprocess.STDOUT,
            env={**os.environ, 'PYTHONUNBUFFERED': '1'}
        )

        logger.info(f"Worker {worker_id} started (PID: {process.pid})")
        return process

    except Exception as e:
        logger.error(f"Failed to start Worker {worker_id}: {e}")
        return None


def start_all_workers() -> Dict[int, subprocess.Popen]:
    """Start all 5 workers with staggered startup."""
    processes = {}

    logger.info("=" * 60)
    logger.info("STARTING 5-WORKER SYSTEM")
    logger.info("=" * 60)

    for worker_id in range(1, 6):
        process = start_worker(worker_id)
        if process:
            processes[worker_id] = process

        # Stagger startup to avoid resource contention
        if worker_id < 5:
            time.sleep(WORKER_STARTUP_DELAY)

    # Write PIDs to file for GUI monitoring
    pid_file = PROJECT_ROOT / 'logs' / 'yp_workers.pid'
    with open(pid_file, 'w') as f:
        for worker_id, proc in processes.items():
            f.write(f"{proc.pid}\n")

    logger.info(f"All workers started. PIDs saved to {pid_file}")
    return processes


def stop_all_workers(processes: Dict[int, subprocess.Popen]):
    """Stop all worker processes gracefully."""
    logger.info("Stopping all workers...")

    for worker_id, proc in processes.items():
        if proc.poll() is None:  # Still running
            logger.info(f"Terminating Worker {worker_id} (PID: {proc.pid})")
            proc.terminate()

    # Wait for graceful shutdown
    time.sleep(5)

    # Force kill any remaining
    for worker_id, proc in processes.items():
        if proc.poll() is None:
            logger.warning(f"Force killing Worker {worker_id} (PID: {proc.pid})")
            proc.kill()

    # Clear PID file
    pid_file = PROJECT_ROOT / 'logs' / 'yp_workers.pid'
    if pid_file.exists():
        pid_file.unlink()


def get_worker_status(processes: Dict[int, subprocess.Popen]) -> Dict[int, str]:
    """Get status of all workers."""
    status = {}
    for worker_id, proc in processes.items():
        poll_result = proc.poll()
        if poll_result is None:
            status[worker_id] = "running"
        elif poll_result == 0:
            status[worker_id] = "completed"
        else:
            status[worker_id] = f"failed (exit={poll_result})"
    return status


def write_status_file(processes: Dict[int, subprocess.Popen], cycle: int):
    """Write status file for GUI monitoring."""
    status_file = PROJECT_ROOT / 'logs' / 'yp_workers_status.json'
    import json

    status = {
        "cycle": cycle,
        "timestamp": datetime.now().isoformat(),
        "workers": []
    }

    for worker_id in range(1, 6):
        worker_status = {
            "worker_id": worker_id,
            "states": WORKER_STATES[worker_id][:3] + ["..."] + WORKER_STATES[worker_id][-2:],
            "status": "stopped"
        }

        if worker_id in processes:
            proc = processes[worker_id]
            if proc.poll() is None:
                worker_status["status"] = "running"
                worker_status["pid"] = proc.pid
            elif proc.poll() == 0:
                worker_status["status"] = "completed"
            else:
                worker_status["status"] = "failed"

        status["workers"].append(worker_status)

    with open(status_file, 'w') as f:
        json.dump(status, f, indent=2)


def main():
    """Main entry point for continuous 5-worker YP scraper."""
    global shutdown_requested, worker_processes

    # Setup signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    total_cycles = 0

    logger.info("=" * 60)
    logger.info("YELLOW PAGES CONTINUOUS 5-WORKER SYSTEM")
    logger.info("=" * 60)
    logger.info(f"Workers: 5")
    logger.info(f"States per worker: 10")
    logger.info(f"Cooldown between cycles: {COOLDOWN_SECONDS}s ({COOLDOWN_SECONDS/3600:.1f} hours)")
    logger.info("=" * 60)

    while not shutdown_requested:
        total_cycles += 1
        cycle_start = datetime.now()

        logger.info("")
        logger.info("=" * 60)
        logger.info(f"CYCLE {total_cycles} - Started at {cycle_start.isoformat()}")
        logger.info("=" * 60)

        # Start all workers
        worker_processes = start_all_workers()

        if not worker_processes:
            logger.error("Failed to start any workers!")
            time.sleep(60)
            continue

        # Monitor workers until all complete or shutdown requested
        while not shutdown_requested:
            time.sleep(CHECK_INTERVAL)

            # Update status file for GUI
            write_status_file(worker_processes, total_cycles)

            # Check worker status
            status = get_worker_status(worker_processes)
            running_count = sum(1 for s in status.values() if s == "running")

            if running_count == 0:
                # All workers finished
                completed = sum(1 for s in status.values() if s == "completed")
                failed = sum(1 for s in status.values() if "failed" in s)
                logger.info(f"All workers finished: {completed} completed, {failed} failed")
                break

        # Cleanup finished processes
        for proc in worker_processes.values():
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass

        cycle_duration = (datetime.now() - cycle_start).total_seconds()
        logger.info(f"Cycle {total_cycles} completed in {cycle_duration/3600:.2f} hours")

        # Cooldown before next cycle
        if not shutdown_requested:
            logger.info(f"Cooldown: waiting {COOLDOWN_SECONDS}s ({COOLDOWN_SECONDS/3600:.1f} hours) before next cycle...")
            for _ in range(COOLDOWN_SECONDS):
                if shutdown_requested:
                    break
                time.sleep(1)

    # Shutdown
    logger.info("")
    logger.info("=" * 60)
    logger.info("SHUTTING DOWN")
    logger.info("=" * 60)

    stop_all_workers(worker_processes)

    # Clear status file
    status_file = PROJECT_ROOT / 'logs' / 'yp_workers_status.json'
    if status_file.exists():
        status_file.unlink()

    logger.info(f"Graceful shutdown complete. Total cycles: {total_cycles}")


if __name__ == '__main__':
    main()
