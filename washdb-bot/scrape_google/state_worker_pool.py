"""
State-Partitioned Worker Pool for Google Maps Scraping.

This module implements a 5-worker system where each worker:
- Scrapes exactly 10 assigned US states
- Uses persistent browsers with browser pooling
- Uses HTML caching for parsed results
- Runs independently in its own process
- Uses async/await for Playwright operations

Architecture:
- 5 worker processes
- State assignments (10 states per worker)
- PostgreSQL row-level locking for target coordination
- Individual worker logs for debugging
- Browser pool integration for persistent browsers
- HTML cache for eliminating redundant parsing
- HeartbeatManager integration for watchdog monitoring
"""

import asyncio
import multiprocessing
import os
import random
import signal
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict

from runner.logging_setup import setup_logging

# Import HeartbeatManager for watchdog integration
try:
    from services.heartbeat_manager import HeartbeatManager
    from db.database_manager import get_db_manager
    HEARTBEAT_MANAGER_AVAILABLE = True
except ImportError as e:
    HEARTBEAT_MANAGER_AVAILABLE = False
    print(f"HeartbeatManager not available: {e}")
from scrape_google.google_crawl_city_first import crawl_single_target
from scrape_google.google_filter import GoogleFilter
from db.models import GoogleTarget, Company
from db import create_session

# Setup logger for pool manager
logger = setup_logging("google_worker_pool")

# State assignments for 5 workers (10 states each)
WORKER_STATES = {
    0: ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA"],
    1: ["HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD"],
    2: ["MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ"],
    3: ["NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC"],
    4: ["SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"],
}


async def async_worker_main(
    worker_id: int,
    state_ids: List[str],
    shutdown_event: multiprocessing.Event,
    config: dict
):
    """
    Async main function for a single state worker process.

    This worker:
    1. Uses browser pool for persistent browsers
    2. Uses HTML cache for parsed results
    3. Acquires targets from assigned states using row-level locking
    4. Processes targets using async Google crawl logic
    5. Random delay between targets (10-20 seconds)

    Args:
        worker_id: Worker number (0-4)
        state_ids: List of assigned state codes (e.g., ["CA", "MT", "RI", "MS", "ND"])
        shutdown_event: Multiprocessing event to signal shutdown
        config: Configuration dictionary
    """
    # Set up worker-specific logger
    worker_logger = setup_logging(f"google_worker_{worker_id}", log_file=f"logs/google_state_worker_{worker_id}.log")

    # Set WORKER_ID environment variable for browser pool isolation
    os.environ["WORKER_ID"] = str(worker_id)

    worker_logger.info("="*70)
    worker_logger.info(f"GOOGLE WORKER {worker_id} STARTING")
    worker_logger.info("="*70)
    worker_logger.info(f"Assigned states: {state_ids}")
    worker_logger.info(f"Configuration: {config}")
    worker_logger.info("="*70)

    try:
        # Initialize GoogleFilter for this worker
        worker_logger.info("Initializing Google filter...")
        google_filter = GoogleFilter()

        # Main processing loop
        targets_processed = 0
        delay_min = config.get("min_delay_seconds", 10.0)
        delay_max = config.get("max_delay_seconds", 20.0)

        # Exponential backoff for idle polling
        idle_sleep_time = 60  # Start with 60 seconds
        max_idle_sleep = 300  # Max 5 minutes

        worker_logger.info("Starting main processing loop...")

        while not shutdown_event.is_set():
            try:
                # Acquire next target ID from assigned states
                target_id = acquire_target_for_worker(state_ids, worker_logger)

                if not target_id:
                    worker_logger.info(f"No pending targets found. Sleeping {idle_sleep_time}s...")
                    await asyncio.sleep(idle_sleep_time)

                    # Exponential backoff: increase sleep time when idle
                    idle_sleep_time = min(idle_sleep_time * 1.5, max_idle_sleep)
                    continue

                # Reset idle sleep time when we find work
                idle_sleep_time = 60

                # Create a new database session for this target
                session = create_session()

                try:
                    # Query the target object in this session
                    target = session.query(GoogleTarget).filter(GoogleTarget.id == target_id).first()

                    if not target:
                        worker_logger.error(f"Target {target_id} not found in database")
                        continue

                    worker_logger.info(
                        f"Processing target {target.id}: {target.city}, {target.state_id} - {target.category_label}"
                    )

                    # Scrape the target using async Google crawl
                    # This will use browser pool internally
                    accepted_results, stats = await crawl_single_target(
                        target=target,
                        session=session,
                        scrape_details=config.get("scrape_details", True),
                        save_to_db=True,
                        worker_id=worker_id
                    )

                    # Log results
                    if accepted_results:
                        worker_logger.info(
                            f"✓ Target {target.id} completed: "
                            f"{len(accepted_results)} accepted, "
                            f"{stats.get('filtered_out', 0)} filtered out | "
                            f"DB: {stats.get('total_saved', 0)} saved"
                        )
                    else:
                        worker_logger.info(
                            f"✓ Target {target.id} completed: "
                            f"0 accepted, "
                            f"{stats.get('filtered_out', 0)} filtered out"
                        )

                    targets_processed += 1

                except Exception as e:
                    worker_logger.error(f"✗ Target {target_id} failed: {e}", exc_info=True)
                    mark_target_failed(target_id, str(e), worker_logger)

                finally:
                    session.close()

                # Random delay between targets
                delay = random.uniform(delay_min, delay_max)
                worker_logger.info(f"Sleeping {delay:.1f}s before next target...")
                await asyncio.sleep(delay)

            except KeyboardInterrupt:
                worker_logger.info("Keyboard interrupt received, shutting down...")
                break
            except Exception as e:
                worker_logger.error(f"Error in worker loop: {e}", exc_info=True)
                await asyncio.sleep(10)
                continue

    except Exception as e:
        worker_logger.error(f"Fatal error in worker {worker_id}: {e}", exc_info=True)
    finally:
        # Print final stats
        worker_logger.info("="*70)
        worker_logger.info(f"GOOGLE WORKER {worker_id} FINAL STATS")
        worker_logger.info("="*70)
        worker_logger.info(f"Targets processed: {targets_processed}")
        worker_logger.info("="*70)

        worker_logger.info(f"Google Worker {worker_id} stopped")


def worker_main(worker_id: int, state_ids: List[str], shutdown_event: multiprocessing.Event, config: dict):
    """
    Synchronous wrapper for async worker main.

    This allows us to run async code in a multiprocessing context.
    """
    # Run the async worker main
    asyncio.run(async_worker_main(worker_id, state_ids, shutdown_event, config))


def acquire_target_for_worker(state_ids: List[str], logger) -> Optional[int]:
    """
    Acquire next pending target for worker's assigned states.

    Uses PostgreSQL row-level locking to prevent duplicate work.

    Args:
        state_ids: List of state codes this worker handles
        logger: Worker logger

    Returns:
        Target ID if found, None if no pending targets
    """
    session = create_session()

    try:
        # Use row-level locking to atomically claim a target
        # SELECT FOR UPDATE SKIP LOCKED ensures no duplicate work
        target = (
            session.query(GoogleTarget)
            .filter(
                GoogleTarget.state_id.in_(state_ids),
                GoogleTarget.status == "PLANNED"
            )
            .order_by(
                GoogleTarget.priority.desc(),
                GoogleTarget.created_at.asc()
            )
            .with_for_update(skip_locked=True)
            .first()
        )

        if target:
            # Mark as IN_PROGRESS (will be updated by crawl_single_target)
            target.status = "IN_PROGRESS"
            target.claimed_at = datetime.now(timezone.utc)
            session.commit()

            logger.debug(f"Acquired target {target.id}: {target.city}, {target.state_id}")
            return target.id

        return None

    except Exception as e:
        logger.error(f"Error acquiring target: {e}", exc_info=True)
        session.rollback()
        return None
    finally:
        session.close()


def mark_target_failed(target_id: int, error_message: str, logger):
    """
    Mark target as FAILED with error message.

    Args:
        target_id: Target ID
        error_message: Error message to store
        logger: Worker logger
    """
    session = create_session()

    try:
        target = session.query(GoogleTarget).filter(GoogleTarget.id == target_id).first()

        if target:
            target.status = "FAILED"
            target.error_message = error_message[:500]  # Truncate if too long
            target.completed_at = datetime.now(timezone.utc)
            session.commit()

            logger.info(f"Marked target {target_id} as FAILED")

    except Exception as e:
        logger.error(f"Error marking target {target_id} as failed: {e}", exc_info=True)
        session.rollback()
    finally:
        session.close()


def start_workers(worker_count: int = 5, config: Optional[Dict] = None):
    """
    Start the worker pool with specified number of workers.

    Args:
        worker_count: Number of workers to start (default: 5)
        config: Configuration dictionary
    """
    if config is None:
        config = {
            "min_delay_seconds": 10.0,
            "max_delay_seconds": 20.0,
            "scrape_details": True,
        }

    logger.info("="*70)
    logger.info("GOOGLE MAPS STATE WORKER POOL")
    logger.info("="*70)
    logger.info(f"Workers: {worker_count}")
    logger.info(f"Configuration: {config}")
    logger.info("="*70)

    # Initialize HeartbeatManager for watchdog integration
    heartbeat_manager = None
    if HEARTBEAT_MANAGER_AVAILABLE:
        try:
            heartbeat_manager = HeartbeatManager(
                db_manager=get_db_manager(),
                worker_name=f"google_worker_pool_{socket.gethostname()}",
                worker_type='google_worker',
                service_unit='google-state-workers'
            )
            heartbeat_manager.start(config={
                'num_workers': worker_count,
            })
            logger.info("HeartbeatManager started - watchdog integration enabled")
        except Exception as e:
            logger.warning(f"Failed to initialize HeartbeatManager: {e}")
            heartbeat_manager = None

    # Create shutdown event
    shutdown_event = multiprocessing.Event()

    # Signal handler for graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"\nReceived signal {signum}, initiating graceful shutdown...")
        shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start workers
    processes = []

    for worker_id in range(worker_count):
        state_ids = WORKER_STATES[worker_id]

        logger.info(f"Starting worker {worker_id} with states: {state_ids}")

        process = multiprocessing.Process(
            target=worker_main,
            args=(worker_id, state_ids, shutdown_event, config),
            name=f"google_worker_{worker_id}"
        )

        process.start()
        processes.append(process)

        # Small delay between worker starts
        time.sleep(1)

    logger.info(f"All {worker_count} workers started")

    # Wait for all workers to complete
    try:
        for process in processes:
            process.join()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt in main process")
        shutdown_event.set()

        # Give workers time to shutdown gracefully
        logger.info("Waiting for workers to shutdown...")
        time.sleep(5)

        # Force terminate if still running
        for process in processes:
            if process.is_alive():
                logger.warning(f"Force terminating worker {process.name}")
                process.terminate()

    logger.info("All workers stopped")

    # Stop HeartbeatManager
    if heartbeat_manager:
        try:
            heartbeat_manager.stop('stopped')
            logger.info("HeartbeatManager stopped")
        except Exception as e:
            logger.warning(f"Failed to stop HeartbeatManager: {e}")


if __name__ == "__main__":
    # Default configuration
    config = {
        "min_delay_seconds": 10.0,
        "max_delay_seconds": 20.0,
        "scrape_details": True,
    }

    # Start 5 workers
    start_workers(worker_count=5, config=config)
