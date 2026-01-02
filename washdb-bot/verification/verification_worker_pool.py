#!/usr/bin/env python3
"""
Verification worker pool manager.

Manages a pool of verification worker processes that continuously
verify companies from the database.
"""

import os
import sys
import time
import signal
import json
import multiprocessing as mp
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from runner.logging_setup import get_logger
from verification.verification_worker import run_worker

# Import HeartbeatManager for watchdog integration
try:
    from services.heartbeat_manager import HeartbeatManager
    from db.database_manager import get_db_manager
    HEARTBEAT_MANAGER_AVAILABLE = True
except ImportError as e:
    HEARTBEAT_MANAGER_AVAILABLE = False
    print(f"HeartbeatManager not available: {e}")

# Configuration
DEFAULT_NUM_WORKERS = 5
PID_FILE = 'logs/verification_workers.pid'
STATE_FILE = 'logs/verification_workers_state.json'
STARTUP_STAGGER_SECONDS = 2


class VerificationWorkerPoolManager:
    """
    Manages a pool of verification worker processes.

    Features:
    - Staggered startup to avoid database contention
    - Graceful shutdown with timeout
    - PID tracking for process management
    - Shared state file for GUI monitoring
    """

    def __init__(self, num_workers: int = DEFAULT_NUM_WORKERS, config: Optional[Dict] = None):
        """
        Initialize worker pool manager.

        Args:
            num_workers: Number of worker processes (default: 5)
            config: Optional configuration dict
        """
        self.num_workers = num_workers
        self.config = config or {}
        self.workers: List[mp.Process] = []
        self.worker_pids: Dict[int, int] = {}  # worker_id -> PID
        self.logger = get_logger("verification_pool_manager")
        self.shutdown_requested = False
        self.heartbeat_manager = None

        # Ensure logs directory exists
        Path('logs').mkdir(exist_ok=True)

        # Register signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        # Initialize HeartbeatManager for watchdog integration
        if HEARTBEAT_MANAGER_AVAILABLE:
            try:
                import socket
                self.heartbeat_manager = HeartbeatManager(
                    db_manager=get_db_manager(),
                    worker_name=f"verification_pool_{socket.gethostname()}",
                    worker_type='verification',
                    service_unit='washdb-verification'
                )
                self.logger.info("HeartbeatManager initialized for watchdog integration")
            except Exception as e:
                self.logger.warning(f"Failed to initialize HeartbeatManager: {e}")
                self.heartbeat_manager = None

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        self.logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.shutdown_requested = True

    def _write_pid_file(self):
        """Write worker PIDs to file for external management."""
        try:
            with open(PID_FILE, 'w') as f:
                json.dump(self.worker_pids, f, indent=2)
            self.logger.info(f"Wrote PID file: {PID_FILE}")
        except Exception as e:
            self.logger.error(f"Failed to write PID file: {e}")

    def _remove_pid_file(self):
        """Remove PID file on shutdown."""
        try:
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
                self.logger.info(f"Removed PID file: {PID_FILE}")
        except Exception as e:
            self.logger.error(f"Failed to remove PID file: {e}")

    def _update_state_file(self):
        """Update shared state file for GUI monitoring."""
        try:
            state = {
                'pool_started_at': getattr(self, 'pool_started_at', None),
                'num_workers': self.num_workers,
                'workers': []
            }

            for worker_id, process in enumerate(self.workers):
                worker_state = {
                    'worker_id': worker_id,
                    'pid': process.pid if process and process.is_alive() else None,
                    'status': 'running' if process and process.is_alive() else 'stopped',
                    'started_at': getattr(self, 'pool_started_at', None)
                }
                state['workers'].append(worker_state)

            with open(STATE_FILE, 'w') as f:
                json.dump(state, f, indent=2)

        except Exception as e:
            self.logger.error(f"Failed to update state file: {e}")

    def start(self):
        """
        Start all worker processes with staggered startup.

        Workers are started with a delay to avoid database contention
        during initialization.
        """
        self.logger.info("=" * 70)
        self.logger.info("VERIFICATION WORKER POOL MANAGER STARTING")
        self.logger.info("=" * 70)
        self.logger.info(f"Number of workers: {self.num_workers}")
        self.logger.info(f"Startup stagger: {STARTUP_STAGGER_SECONDS}s per worker")
        self.logger.info("-" * 70)

        self.pool_started_at = datetime.now().isoformat()

        # Start HeartbeatManager
        if self.heartbeat_manager:
            try:
                self.heartbeat_manager.start(config={
                    'num_workers': self.num_workers,
                    'startup_stagger': STARTUP_STAGGER_SECONDS,
                })
                self.logger.info("HeartbeatManager started - watchdog integration enabled")
            except Exception as e:
                self.logger.warning(f"Failed to start HeartbeatManager: {e}")

        for worker_id in range(self.num_workers):
            if self.shutdown_requested:
                self.logger.warning("Shutdown requested during startup, aborting...")
                break

            self.logger.info(f"Starting worker {worker_id}...")

            # Create worker process
            process = mp.Process(
                target=run_worker,
                args=(worker_id, self.config),
                name=f'verify_worker_{worker_id}'
            )
            process.start()

            self.workers.append(process)
            self.worker_pids[worker_id] = process.pid

            self.logger.info(f"Worker {worker_id} started with PID {process.pid}")

            # Update state and PID files
            self._write_pid_file()
            self._update_state_file()

            # Staggered startup (except for last worker)
            if worker_id < self.num_workers - 1:
                self.logger.info(f"Waiting {STARTUP_STAGGER_SECONDS}s before starting next worker...")
                time.sleep(STARTUP_STAGGER_SECONDS)

        self.logger.info("=" * 70)
        self.logger.info(f"All {len(self.workers)} workers started successfully")
        self.logger.info("=" * 70)

    def monitor(self):
        """
        Monitor worker processes and update state file.

        Runs continuously until shutdown is requested.
        """
        self.logger.info("Entering monitoring loop...")

        try:
            while not self.shutdown_requested:
                # Count alive workers
                alive_workers = sum(1 for p in self.workers if p.is_alive())
                dead_workers = len(self.workers) - alive_workers

                # Check worker health
                for worker_id, process in enumerate(self.workers):
                    if not process.is_alive():
                        self.logger.warning(f"Worker {worker_id} (PID {process.pid}) has died!")
                        # Record failure in heartbeat
                        if self.heartbeat_manager:
                            self.heartbeat_manager.record_job_failed(
                                f"Worker {worker_id} died",
                                module_name='worker_monitor'
                            )

                # Update heartbeat with current status
                if self.heartbeat_manager:
                    self.heartbeat_manager.set_current_work(
                        module=f"monitoring_{alive_workers}_workers"
                    )

                # Update state file
                self._update_state_file()

                # Sleep before next check
                time.sleep(5)

        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt received")
            self.shutdown_requested = True

    def stop(self, timeout: int = 30):
        """
        Stop all worker processes gracefully.

        Sends SIGTERM to all workers and waits for them to finish.
        If they don't finish within timeout, sends SIGKILL.

        Args:
            timeout: Maximum seconds to wait per worker
        """
        self.logger.info("=" * 70)
        self.logger.info("STOPPING VERIFICATION WORKER POOL")
        self.logger.info("=" * 70)

        for worker_id, process in enumerate(self.workers):
            if not process.is_alive():
                self.logger.info(f"Worker {worker_id} already stopped")
                continue

            self.logger.info(f"Sending SIGTERM to worker {worker_id} (PID {process.pid})...")

            try:
                process.terminate()  # Send SIGTERM

                # Wait for graceful shutdown
                self.logger.info(f"Waiting up to {timeout}s for worker {worker_id} to finish...")
                process.join(timeout=timeout)

                if process.is_alive():
                    self.logger.warning(
                        f"Worker {worker_id} did not stop gracefully, killing..."
                    )
                    process.kill()  # Send SIGKILL
                    process.join(timeout=5)

                if not process.is_alive():
                    self.logger.info(f"Worker {worker_id} stopped successfully")
                else:
                    self.logger.error(f"Worker {worker_id} could not be stopped!")

            except Exception as e:
                self.logger.error(f"Error stopping worker {worker_id}: {e}")

        self.logger.info("=" * 70)
        self.logger.info("All workers stopped")
        self.logger.info("=" * 70)

        # Stop HeartbeatManager
        if self.heartbeat_manager:
            try:
                self.heartbeat_manager.stop('stopped')
                self.logger.info("HeartbeatManager stopped")
            except Exception as e:
                self.logger.warning(f"Failed to stop HeartbeatManager: {e}")

        # Clean up
        self._remove_pid_file()
        self._update_state_file()

    def run(self):
        """
        Start worker pool and run until shutdown.

        This is the main entry point for the pool manager.
        """
        try:
            self.start()
            self.monitor()
        finally:
            self.stop()


def main():
    """Main entry point for pool manager."""
    import argparse

    parser = argparse.ArgumentParser(description='Verification worker pool manager')
    parser.add_argument(
        '--workers',
        type=int,
        default=DEFAULT_NUM_WORKERS,
        help=f'Number of worker processes (default: {DEFAULT_NUM_WORKERS})'
    )
    parser.add_argument(
        '--config',
        type=str,
        help='Path to configuration file (optional)'
    )

    args = parser.parse_args()

    # Load config if provided
    config = {}
    if args.config and os.path.exists(args.config):
        with open(args.config, 'r') as f:
            config = json.load(f)

    # Create and run pool manager
    manager = VerificationWorkerPoolManager(num_workers=args.workers, config=config)
    manager.run()


if __name__ == '__main__':
    main()
