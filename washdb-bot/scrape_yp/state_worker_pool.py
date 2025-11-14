"""
State-Partitioned Worker Pool for Yellow Pages Scraping.

This module implements a 10-worker system where each worker:
- Scrapes exactly 5 assigned US states
- Uses 5 dedicated proxies with per-request rotation
- Runs independently in its own process
- Uses the same scraping logic as the single worker

Architecture:
- 10 worker processes
- State assignments from state_assignments.py
- Per-worker proxy pool (5 proxies each, 50 total)
- PostgreSQL row-level locking for target coordination
- Individual worker logs for debugging
"""

import multiprocessing
import os
import random
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from runner.logging_setup import setup_logging
from scrape_yp.proxy_pool import WorkerProxyPool
from scrape_yp.state_assignments import get_states_for_worker, get_proxy_assignments
from scrape_yp.yp_crawl_city_first import crawl_single_target
from scrape_yp.yp_filter import YPFilter
from scrape_yp.yp_monitor import ScraperMonitor
from db.models import YPTarget, Company
from db import create_session

# Setup logger for pool manager
logger = setup_logging("state_worker_pool")


def worker_main(
    worker_id: int,
    state_ids: List[str],
    proxy_indices: List[int],
    shutdown_event: multiprocessing.Event,
    config: dict
):
    """
    Main function for a single state worker process.

    This worker:
    1. Initializes its own proxy pool with assigned proxies
    2. Creates a persistent Playwright browser
    3. Acquires targets from assigned states using row-level locking
    4. Rotates proxy on every request (not just browser restart)
    5. Processes targets using the same logic as single worker
    6. Random delay between targets (10-20 seconds)

    Args:
        worker_id: Worker number (0-9)
        state_ids: List of assigned state codes (e.g., ["CA", "MT", "RI", "MS", "ND"])
        proxy_indices: List of assigned proxy indices (e.g., [0, 1, 2, 3, 4])
        shutdown_event: Multiprocessing event to signal shutdown
        config: Configuration dictionary
    """
    # Set up worker-specific logger
    worker_logger = setup_logging(f"worker_{worker_id}", log_file=f"logs/state_worker_{worker_id}.log")

    worker_logger.info("="*70)
    worker_logger.info(f"WORKER {worker_id} STARTING")
    worker_logger.info("="*70)
    worker_logger.info(f"Assigned states: {state_ids}")
    worker_logger.info(f"Assigned proxy indices: {proxy_indices}")
    worker_logger.info(f"Configuration: {config}")
    worker_logger.info("="*70)

    try:
        # Initialize YPFilter for this worker
        worker_logger.info("Initializing YP filter...")
        yp_filter = YPFilter()

        # Initialize monitor (optional)
        monitor = ScraperMonitor() if config.get("enable_monitor", False) else None

        # Main processing loop
        targets_processed = 0
        delay_min = config.get("min_delay_seconds", 10.0)
        delay_max = config.get("max_delay_seconds", 20.0)

        worker_logger.info("Starting main processing loop...")

        while not shutdown_event.is_set():
            try:
                # Acquire next target ID from assigned states
                target_id = acquire_target_for_worker(state_ids, worker_logger)

                if not target_id:
                    worker_logger.info("No pending targets found. Sleeping 30s...")
                    time.sleep(30)
                    continue

                # Create a new database session for this target
                session = create_session()

                try:
                    # Query the target object in this session
                    target = session.query(YPTarget).filter(YPTarget.id == target_id).first()

                    if not target:
                        worker_logger.error(f"Target {target_id} not found in database")
                        continue

                    worker_logger.info(
                        f"Processing target {target.id}: {target.city}, {target.state_id} - {target.category_label}"
                    )

                    # Scrape the target using existing logic
                    # This will handle its own Playwright browser internally
                    accepted_results, stats = crawl_single_target(
                        target=target,
                        session=session,
                        yp_filter=yp_filter,
                        min_score=config.get("min_confidence_score", 40.0),
                        include_sponsored=config.get("include_sponsored", False),
                        use_fallback_on_404=True,
                        monitor=monitor
                    )

                    # Save results to database
                    if accepted_results:
                        new_count, updated_count = save_companies_to_db(accepted_results, session, worker_logger)
                        worker_logger.info(
                            f"✓ Target {target.id} completed: "
                            f"{len(accepted_results)} accepted, "
                            f"{stats.get('total_filtered_out', 0)} filtered out | "
                            f"DB: {new_count} new, {updated_count} updated"
                        )
                    else:
                        worker_logger.info(
                            f"✓ Target {target.id} completed: "
                            f"0 accepted, "
                            f"{stats.get('total_filtered_out', 0)} filtered out"
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
                time.sleep(delay)

            except KeyboardInterrupt:
                worker_logger.info("Keyboard interrupt received, shutting down...")
                break
            except Exception as e:
                worker_logger.error(f"Error in worker loop: {e}", exc_info=True)
                time.sleep(10)
                continue

    except Exception as e:
        worker_logger.error(f"Fatal error in worker {worker_id}: {e}", exc_info=True)
    finally:
        # Print final stats
        worker_logger.info("="*70)
        worker_logger.info(f"WORKER {worker_id} FINAL STATS")
        worker_logger.info("="*70)
        worker_logger.info(f"Targets processed: {targets_processed}")
        worker_logger.info("="*70)

        worker_logger.info(f"Worker {worker_id} stopped")


def acquire_target_for_worker(state_ids: List[str], logger) -> Optional[int]:
    """
    Acquire next pending target for worker's assigned states.

    Uses PostgreSQL row-level locking to prevent duplicate work.

    Args:
        state_ids: List of state codes this worker handles
        logger: Logger instance

    Returns:
        Target ID (int) or None if no targets available
    """
    session = None
    try:
        session = create_session()

        # Atomic target acquisition with row-level lock
        target = (
            session.query(YPTarget)
            .filter(
                YPTarget.state_id.in_(state_ids),
                YPTarget.status == "planned"
            )
            .order_by(YPTarget.priority.asc(), YPTarget.id.asc())
            .with_for_update(skip_locked=True)  # PostgreSQL row-level lock
            .first()
        )

        if target:
            target_id = target.id  # Get ID before closing session
            # Mark as in_progress
            target.status = "in_progress"
            target.last_attempt_ts = datetime.now()
            target.attempts = (target.attempts or 0) + 1
            session.commit()

            return target_id

        return None

    except Exception as e:
        logger.error(f"Error acquiring target: {e}", exc_info=True)
        if session:
            session.rollback()
        return None
    finally:
        if session:
            session.close()


def mark_target_failed(target_id: int, error_msg: str, logger) -> None:
    """Mark a target as failed."""
    session = None
    try:
        session = create_session()
        target = session.query(YPTarget).filter(YPTarget.id == target_id).first()
        if target:
            target.status = "failed"
            target.note = error_msg
            session.commit()
            logger.info(f"Marked target {target_id} as failed: {error_msg}")
    except Exception as e:
        logger.error(f"Error marking target as failed: {e}")
        if session:
            session.rollback()
    finally:
        if session:
            session.close()


def save_companies_to_db(results: list, session, logger) -> tuple[int, int]:
    """
    Save scraped companies to database.

    Args:
        results: List of company dictionaries
        session: SQLAlchemy session
        logger: Logger instance

    Returns:
        Tuple of (new_count, updated_count)
    """
    new_count = 0
    updated_count = 0

    for result in results:
        try:
            # Check if company already exists by website
            website = result.get("website")
            if not website:
                logger.warning(f"Skipping company without website: {result.get('name')}")
                continue

            # Check for existing company
            existing = session.query(Company).filter(Company.website == website).first()

            if existing:
                # Update existing company
                if result.get("name"):
                    existing.name = result["name"]
                if result.get("phone"):
                    existing.phone = result["phone"]
                if result.get("email"):
                    existing.email = result["email"]
                if result.get("address"):
                    existing.address = result["address"]
                if result.get("services"):
                    existing.services = result["services"]
                if result.get("rating_yp"):
                    existing.rating_yp = result["rating_yp"]
                if result.get("reviews_yp"):
                    existing.reviews_yp = result["reviews_yp"]

                existing.last_updated = datetime.now()
                updated_count += 1
                logger.debug(f"Updated company: {existing.name}")
            else:
                # Create new company
                company = Company(
                    name=result.get("name"),
                    website=website,
                    domain=result.get("domain"),
                    phone=result.get("phone"),
                    email=result.get("email"),
                    address=result.get("address"),
                    services=result.get("services"),
                    source=result.get("source", "YP"),
                    rating_yp=result.get("rating_yp"),
                    reviews_yp=result.get("reviews_yp"),
                    active=True,
                )
                session.add(company)
                new_count += 1
                logger.debug(f"Added new company: {company.name}")

        except Exception as e:
            logger.error(f"Error saving company {result.get('name')}: {e}")
            continue

    try:
        session.commit()
        logger.info(f"Saved to database: {new_count} new, {updated_count} updated")
    except Exception as e:
        logger.error(f"Error committing companies: {e}")
        session.rollback()
        new_count = 0
        updated_count = 0

    return new_count, updated_count


class StateWorkerPoolManager:
    """
    Manager for 10-worker state-partitioned scraping system.

    Features:
    - Launches 10 independent worker processes
    - Each worker handles 5 assigned states
    - Each worker uses 5 dedicated proxies
    - Graceful shutdown handling
    - Per-worker monitoring
    """

    def __init__(self, config: dict):
        """
        Initialize worker pool manager.

        Args:
            config: Configuration dictionary with keys:
                - proxy_file: Path to proxy file
                - num_workers: Number of workers (default 10)
                - min_delay_seconds: Min delay between targets
                - max_delay_seconds: Max delay between targets
                - max_targets_per_browser: Targets before browser restart
                - blacklist_threshold: Proxy failures before blacklist
                - blacklist_duration_minutes: How long to blacklist
                - headless: Run browsers headless
                - min_confidence_score: Minimum filter score
                - include_sponsored: Include sponsored results
        """
        self.config = config
        self.num_workers = config.get("num_workers", 10)
        self.workers: List[multiprocessing.Process] = []
        self.shutdown_event = multiprocessing.Event()

        # Validate configuration
        self._validate_config()

    def _validate_config(self):
        """Validate configuration."""
        required_keys = ["proxy_file"]
        for key in required_keys:
            if key not in self.config:
                raise ValueError(f"Missing required config key: {key}")

        # Check proxy file exists
        proxy_path = Path(self.config["proxy_file"])
        if not proxy_path.exists():
            raise FileNotFoundError(f"Proxy file not found: {self.config['proxy_file']}")

        # Check we have enough proxies (need 50 for 10 workers × 5 proxies each)
        with open(proxy_path, 'r') as f:
            proxy_count = sum(1 for line in f if line.strip() and not line.startswith('#'))

        proxies_needed = self.num_workers * 5
        if proxy_count < proxies_needed:
            raise ValueError(
                f"Not enough proxies! Need {proxies_needed} for {self.num_workers} workers, "
                f"but only found {proxy_count} in {self.config['proxy_file']}"
            )

        logger.info(f"Configuration validated: {proxy_count} proxies available for {self.num_workers} workers")

    def start(self):
        """Start all worker processes with staggered startup."""
        logger.info("="*70)
        logger.info(f"STARTING {self.num_workers}-WORKER STATE-PARTITIONED POOL")
        logger.info("="*70)

        for worker_id in range(self.num_workers):
            # Get state and proxy assignments
            state_ids = get_states_for_worker(worker_id)
            proxy_indices = get_proxy_assignments(worker_id)

            logger.info(f"Worker {worker_id}: States {state_ids}, Proxies {proxy_indices}")

            # Create worker process
            worker = multiprocessing.Process(
                target=worker_main,
                args=(worker_id, state_ids, proxy_indices, self.shutdown_event, self.config),
                name=f"StateWorker-{worker_id}"
            )

            worker.start()
            self.workers.append(worker)

            logger.info(f"Worker {worker_id} started (PID: {worker.pid})")

            # Stagger startup to avoid simultaneous requests
            if worker_id < self.num_workers - 1:
                stagger_delay = random.uniform(2, 5)
                logger.info(f"Staggering startup: waiting {stagger_delay:.1f}s before next worker...")
                time.sleep(stagger_delay)

        logger.info("="*70)
        logger.info(f"All {self.num_workers} workers started successfully")
        logger.info("="*70)

    def stop(self):
        """Stop all worker processes gracefully."""
        logger.info("Stopping all workers...")

        # Signal shutdown
        self.shutdown_event.set()

        # Wait for workers to finish (max 30 seconds each)
        for idx, worker in enumerate(self.workers):
            logger.info(f"Waiting for worker {idx} (PID: {worker.pid}) to stop...")
            worker.join(timeout=30)

            if worker.is_alive():
                logger.warning(f"Worker {idx} did not stop gracefully, terminating...")
                worker.terminate()
                worker.join(timeout=5)

            if worker.is_alive():
                logger.error(f"Worker {idx} did not terminate, killing...")
                worker.kill()

        logger.info("All workers stopped")

    def wait(self):
        """Wait for all workers to complete."""
        logger.info("Waiting for workers to complete...")

        try:
            for worker in self.workers:
                worker.join()
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
            self.stop()

        logger.info("All workers completed")


def main():
    """Main entry point for state worker pool."""
    # Load configuration from environment
    from dotenv import load_dotenv
    load_dotenv()

    config = {
        "proxy_file": os.getenv("PROXY_FILE", "data/webshare_proxies.txt"),
        "num_workers": int(os.getenv("WORKER_COUNT", "10")),
        "min_delay_seconds": float(os.getenv("MIN_DELAY_SECONDS", "10.0")),
        "max_delay_seconds": float(os.getenv("MAX_DELAY_SECONDS", "20.0")),
        "max_targets_per_browser": int(os.getenv("MAX_TARGETS_PER_BROWSER", "100")),
        "blacklist_threshold": int(os.getenv("PROXY_BLACKLIST_THRESHOLD", "10")),
        "blacklist_duration_minutes": int(os.getenv("PROXY_BLACKLIST_DURATION_MINUTES", "60")),
        "headless": os.getenv("BROWSER_HEADLESS", "true").lower() == "true",
        "min_confidence_score": float(os.getenv("MIN_CONFIDENCE_SCORE", "50.0")),
        "include_sponsored": os.getenv("INCLUDE_SPONSORED", "false").lower() == "true",
    }

    # Create and start pool
    pool = StateWorkerPoolManager(config)

    # Handle shutdown signals
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        pool.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start workers
    pool.start()

    # Wait for completion
    pool.wait()


if __name__ == "__main__":
    main()
