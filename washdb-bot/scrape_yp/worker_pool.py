"""
Worker Pool for Parallel Yellow Pages Scraping.

This module provides:
- Multiprocessing worker pool
- Proxy-aware crawling
- Database locking for target acquisition
- Automatic error recovery
- Progress aggregation
"""

import os
import sys
import time
import random
import signal
import multiprocessing
from datetime import datetime, timedelta
from typing import Optional, List, Dict

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, Session
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from db.models import YPTarget
from scrape_yp.proxy_pool import ProxyPool, ProxyInfo
from scrape_yp.worker_config import WorkerConfig
from scrape_yp.yp_crawl_city_first import crawl_single_target
from runner.logging_setup import get_logger


# Global logger (will be worker-specific)
logger = None


def setup_worker_logging(worker_id: int):
    """Setup logging for a specific worker."""
    global logger
    logger = get_logger(f"worker_{worker_id}")
    return logger


def create_worker_session() -> Session:
    """
    Create a database session for a worker.

    Returns:
        SQLAlchemy Session
    """
    engine = create_engine(
        WorkerConfig.DATABASE_URL,
        pool_size=5,  # Each worker gets small pool
        max_overflow=10,
        pool_pre_ping=True,  # Verify connections before use
        echo=False
    )

    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


def calculate_cooldown_delay(attempt: int, base_delay: float = 30.0, max_delay: float = 300.0) -> float:
    """
    Calculate exponential backoff delay with jitter.

    Uses exponential backoff: delay = base * (2 ^ attempt) + jitter
    Caps at max_delay to prevent infinite waits.

    Args:
        attempt: Current attempt number (0-indexed)
        base_delay: Base delay in seconds (default: 30s)
        max_delay: Maximum delay in seconds (default: 300s = 5min)

    Returns:
        Delay in seconds with random jitter
    """
    # Exponential backoff: base * 2^attempt
    delay = base_delay * (2 ** attempt)

    # Cap at max_delay
    delay = min(delay, max_delay)

    # Add jitter (±25%)
    jitter = delay * 0.25 * (random.random() * 2 - 1)
    final_delay = delay + jitter

    # Ensure non-negative
    return max(0, final_delay)


def acquire_next_target(session: Session, state_ids: List[str], worker_id: str, max_per_state: int = 5) -> Optional[YPTarget]:
    """
    Acquire next target from database with row-level locking and per-state concurrency limits.

    Uses PostgreSQL SELECT FOR UPDATE SKIP LOCKED to prevent
    multiple workers from getting the same target.

    Enforces per-state concurrency limit to avoid overwhelming a single state.

    Sets claimed_by, claimed_at, and heartbeat_at for crash recovery.

    Args:
        session: Database session
        state_ids: List of state codes to filter by
        worker_id: Unique worker identifier (e.g., 'worker_0_pid_12345')
        max_per_state: Maximum concurrent targets per state (default: 5)

    Returns:
        YPTarget object or None if no targets available
    """
    try:
        # Check per-state concurrency limits
        # Count IN_PROGRESS targets for each state
        from sqlalchemy import func
        state_counts = (
            session.query(YPTarget.state_id, func.count(YPTarget.id))
            .filter(
                YPTarget.state_id.in_(state_ids),
                YPTarget.status == "IN_PROGRESS"
            )
            .group_by(YPTarget.state_id)
            .all()
        )

        # Build set of states at capacity
        states_at_capacity = {state_id for state_id, count in state_counts if count >= max_per_state}

        # Filter available states
        available_states = [s for s in state_ids if s not in states_at_capacity]

        if not available_states:
            if logger:
                logger.debug(f"All states at capacity (max {max_per_state} concurrent per state)")
            return None

        # Build query with locking and state capacity filtering
        query = (
            session.query(YPTarget)
            .filter(
                YPTarget.state_id.in_(available_states),
                YPTarget.status == "PLANNED"
            )
            .order_by(YPTarget.priority.asc(), YPTarget.id.asc())
            .with_for_update(skip_locked=True)  # PostgreSQL row-level lock
            .limit(1)
        )

        target = query.first()

        if target:
            now = datetime.now()

            # Mark as in progress with worker claim
            target.status = "IN_PROGRESS"
            target.last_attempt_ts = now
            target.attempts += 1
            target.claimed_by = worker_id
            target.claimed_at = now
            target.heartbeat_at = now  # Initial heartbeat
            target.page_target = target.max_pages  # Set target page count

            session.commit()

            if logger:
                logger.debug(f"Acquired target {target.id}: {target.city}, {target.state_id} - {target.category_label} (claimed by {worker_id})")

        return target

    except Exception as e:
        if logger:
            logger.error(f"Error acquiring target: {e}")
        session.rollback()
        return None


def worker_main(worker_id: int, proxy_file: str, state_ids: List[str], stop_event: multiprocessing.Event):
    """
    Main worker function (runs in separate process).

    Args:
        worker_id: Unique worker ID (0-indexed)
        proxy_file: Path to proxy file
        state_ids: List of state codes to scrape
        stop_event: Event to signal worker shutdown
    """
    # Setup logging
    logger = setup_worker_logging(worker_id)

    # Create unique worker identifier with PID
    worker_identifier = f"worker_{worker_id}_pid_{os.getpid()}"

    logger.info("=" * 60)
    logger.info(f"Worker {worker_id} starting (ID: {worker_identifier})...")
    logger.info("=" * 60)

    # Load proxy pool
    try:
        proxy_pool = ProxyPool(
            proxy_file,
            blacklist_threshold=WorkerConfig.PROXY_BLACKLIST_THRESHOLD,
            blacklist_duration_minutes=WorkerConfig.PROXY_BLACKLIST_DURATION_MINUTES
        )
        logger.info(f"Loaded {len(proxy_pool.proxies)} proxies")
    except Exception as e:
        logger.error(f"Failed to load proxies: {e}")
        return

    # Get initial proxy
    current_proxy = proxy_pool.get_proxy(strategy=WorkerConfig.PROXY_SELECTION_STRATEGY)
    if not current_proxy:
        logger.error("No healthy proxies available!")
        return

    logger.info(f"Assigned proxy: {current_proxy.host}:{current_proxy.port}")

    # Stagger worker startup to avoid all hitting YP at once
    # Each worker waits 0-30 seconds before starting
    startup_delay = random.uniform(0, 30)
    logger.info(f"Staggering startup by {startup_delay:.1f}s to distribute load...")
    time.sleep(startup_delay)

    # Create database session
    session = create_worker_session()

    # Create WAL for this worker
    from scrape_yp.yp_wal import WorkerWAL
    wal = WorkerWAL(worker_identifier, log_dir="logs")
    logger.info(f"WAL log: {wal.log_file}")

    # Initialize browser
    browser = None
    browser_context = None
    playwright_instance = None
    targets_processed_this_browser = 0

    try:
        # Main worker loop
        while not stop_event.is_set():
            # Acquire next target
            target = acquire_next_target(session, state_ids, worker_identifier)

            if not target:
                logger.info("No targets available, waiting...")
                time.sleep(10)
                continue

            logger.info(f"Processing target {target.id}/{targets_processed_this_browser}: {target.city}, {target.state_id} - {target.category_label}")

            # Restart browser if needed
            if (browser is None or
                targets_processed_this_browser >= WorkerConfig.MAX_TARGETS_PER_BROWSER):

                # Close old browser
                if browser:
                    logger.info(f"Restarting browser after {targets_processed_this_browser} targets")
                    try:
                        if browser_context:
                            browser_context.close()
                        browser.close()
                    except Exception as e:
                        logger.debug(f"Worker {worker_id}: Browser close failed during restart: {e}", exc_info=True)

                # Launch new browser with proxy
                try:
                    if not playwright_instance:
                        playwright_instance = sync_playwright().start()

                    browser = playwright_instance.chromium.launch(
                        headless=WorkerConfig.BROWSER_HEADLESS,
                        args=[
                            '--disable-blink-features=AutomationControlled',
                            '--disable-web-security',
                            '--no-sandbox',
                        ]
                    )

                    # Create context with proxy
                    from scrape_yp.yp_stealth import get_playwright_context_params, get_enhanced_playwright_init_scripts

                    context_params = get_playwright_context_params()
                    context_params['proxy'] = current_proxy.to_playwright_format()

                    browser_context = browser.new_context(**context_params)

                    # Inject anti-detection scripts
                    for script in get_enhanced_playwright_init_scripts():
                        browser_context.add_init_script(script)

                    targets_processed_this_browser = 0
                    logger.info(f"Browser launched with proxy {current_proxy.host}:{current_proxy.port}")

                except Exception as e:
                    logger.error(f"Failed to launch browser: {e}")
                    # Try different proxy
                    proxy_pool.report_failure(current_proxy, "browser_launch_failure")
                    current_proxy = proxy_pool.get_proxy(strategy=WorkerConfig.PROXY_SELECTION_STRATEGY)
                    if not current_proxy:
                        logger.error("No healthy proxies available!")
                        break
                    continue

            # Crawl target
            try:
                # Pass browser context, WAL, stop_event, and proxy info to crawl function
                results, stats = crawl_single_target_with_context(
                    target=target,
                    browser_context=browser_context,
                    session=session,
                    min_score=WorkerConfig.MIN_CONFIDENCE_SCORE,
                    include_sponsored=WorkerConfig.INCLUDE_SPONSORED,
                    wal=wal,
                    stop_event=stop_event,
                    proxy=current_proxy,
                    proxy_pool=proxy_pool
                )

                # RESILIENCE: Check for blocking/CAPTCHA
                if stats.get('blocked') or stats.get('captcha_detected'):
                    block_reason = stats.get('block_reason', 'Unknown')
                    logger.warning(f"🚫 Target {target.id} blocked/CAPTCHA: {block_reason}")

                    # Calculate cool-down delay with exponential backoff
                    cooldown = calculate_cooldown_delay(target.attempts, base_delay=30.0, max_delay=300.0)
                    logger.warning(f"  Cooling down for {cooldown:.1f}s before proxy rotation...")

                    # Mark target with cooling-down note
                    target.status = "PLANNED"  # Return to queue
                    target.note = f"cooling_down_after_block_attempt={target.attempts}_reason={block_reason[:100]}"
                    target.last_error = f"Blocked: {block_reason}"
                    session.commit()

                    # Cool-down delay
                    time.sleep(cooldown)

                    # Rotate proxy (force browser restart)
                    logger.info(f"  Rotating proxy after block/CAPTCHA...")
                    current_proxy = proxy_pool.get_proxy(strategy=WorkerConfig.PROXY_SELECTION_STRATEGY)
                    if not current_proxy:
                        logger.error("No healthy proxies available after rotation!")
                        break

                    # Force browser restart with new proxy
                    targets_processed_this_browser = WorkerConfig.MAX_TARGETS_PER_BROWSER
                    continue  # Skip to next target

                # Report success if no blocking
                proxy_pool.report_success(current_proxy)
                targets_processed_this_browser += 1

                # Mark target as done
                target.status = "DONE"
                target.note = f"Completed: {stats.get('accepted', 0)} results"
                target.finished_at = datetime.utcnow()
                target.heartbeat_at = datetime.utcnow()  # Final heartbeat
                session.commit()

                logger.info(f"✓ Target {target.id} complete: {stats.get('accepted', 0)} results accepted")

            except PlaywrightTimeoutError as e:
                logger.warning(f"Timeout on target {target.id}: {e}")
                proxy_pool.report_failure(current_proxy, "timeout")

                # Mark target as failed or retry
                if target.attempts >= WorkerConfig.MAX_TARGET_RETRY_ATTEMPTS:
                    target.status = "FAILED"
                    target.note = f"Failed after {target.attempts} attempts: timeout"
                    target.last_error = str(e)[:500]
                    logger.error(f"✗ Target {target.id} failed (max retries)")
                else:
                    target.status = "PLANNED"  # Retry later
                    target.last_error = str(e)[:500]
                    logger.warning(f"Target {target.id} will be retried (attempt {target.attempts})")

                session.commit()

                # Rotate proxy
                if WorkerConfig.PROXY_ROTATION_ENABLED:
                    current_proxy = proxy_pool.get_proxy(strategy=WorkerConfig.PROXY_SELECTION_STRATEGY)
                    if not current_proxy:
                        logger.error("No healthy proxies available!")
                        break

                    # Force browser restart with new proxy
                    targets_processed_this_browser = WorkerConfig.MAX_TARGETS_PER_BROWSER

            except Exception as e:
                logger.error(f"Error crawling target {target.id}: {e}", exc_info=True)
                proxy_pool.report_failure(current_proxy, "crawl_error")

                # Mark target for retry
                if target.attempts >= WorkerConfig.MAX_TARGET_RETRY_ATTEMPTS:
                    target.status = "FAILED"
                    target.note = f"Failed after {target.attempts} attempts: {str(e)[:200]}"
                    target.last_error = str(e)[:500]
                    logger.error(f"✗ Target {target.id} failed (max retries)")
                else:
                    target.status = "PLANNED"
                    target.last_error = str(e)[:500]
                    logger.warning(f"Target {target.id} will be retried")

                session.commit()

            # Random delay between targets
            if WorkerConfig.DELAY_RANDOMIZATION:
                delay = random.uniform(WorkerConfig.MIN_DELAY_SECONDS, WorkerConfig.MAX_DELAY_SECONDS)
            else:
                delay = WorkerConfig.MIN_DELAY_SECONDS

            logger.debug(f"Waiting {delay:.1f}s before next target...")
            time.sleep(delay)

    except KeyboardInterrupt:
        logger.info("Worker interrupted by user")

    except Exception as e:
        logger.error(f"Worker crashed: {e}", exc_info=True)

    finally:
        # Cleanup
        logger.info("Worker shutting down...")

        if browser:
            try:
                if browser_context:
                    browser_context.close()
                browser.close()
            except Exception as e:
                logger.debug(f"Worker {worker_id}: Browser close failed during shutdown: {e}", exc_info=True)

        if playwright_instance:
            try:
                playwright_instance.stop()
            except Exception as e:
                logger.debug(f"Worker {worker_id}: Playwright stop failed during shutdown: {e}", exc_info=True)

        session.close()

        # Close WAL
        if wal:
            wal.close()
            logger.info(f"WAL closed: {wal.log_file}")

        # Print proxy stats
        stats = proxy_pool.get_stats()
        logger.info(f"Final proxy stats: {stats['total_successes']} successes, {stats['total_failures']} failures, {stats['overall_success_rate']:.1%} success rate")

        logger.info(f"Worker {worker_id} stopped")


def crawl_single_target_with_context(target, browser_context, session, min_score, include_sponsored, wal=None, stop_event=None, proxy=None, proxy_pool=None):
    """
    Crawl a single target using existing browser context with per-page checkpoints.

    This is a wrapper around the existing crawl_single_target function
    but uses a pre-existing browser context instead of launching a new browser.

    Implements crash recovery and resilience:
    - Updates page_current after each page
    - Saves listings atomically with page checkpoint
    - Logs to WAL for operator visibility
    - Checks stop_event before each page
    - Detects CAPTCHA/blocking and signals proxy rotation
    - Returns block/CAPTCHA detection status

    Args:
        target: YPTarget object
        browser_context: Playwright BrowserContext (with proxy already configured)
        session: Database session
        min_score: Minimum confidence score
        include_sponsored: Include sponsored listings
        wal: WorkerWAL instance for logging (optional)
        stop_event: Event to check for graceful stop (optional)
        proxy: Current ProxyInfo being used (optional, for block detection)
        proxy_pool: ProxyPool instance (optional, for reporting failures)

    Returns:
        Tuple of (results, stats) where stats includes 'blocked' and 'captcha_detected' keys
    """
    from scrape_yp.yp_parser_enhanced import parse_yp_results_enhanced
    from scrape_yp.yp_filter import filter_yp_listings
    from db.save_discoveries import upsert_discovered
    from scrape_yp.yp_monitor import detect_captcha, detect_blocking

    results_all = []
    stats = {
        "pages_crawled": 0,
        "raw_results": 0,
        "accepted": 0,
        "rejected": 0,
        "blocked": False,
        "captcha_detected": False,
        "block_reason": None
    }

    # Log target start to WAL
    if wal:
        wal.log_target_start(
            target.id, target.city, target.state_id,
            target.category_label, target.max_pages
        )

    try:
        # Create a new page in the context
        page = browser_context.new_page()

        # Resume from page_current + 1 (or start from 1 if page_current == 0)
        start_page = max(1, target.page_current + 1)

        # Crawl from start_page to max_pages
        for page_num in range(start_page, target.max_pages + 1):
            # Check for graceful stop before each page
            if stop_event and stop_event.is_set():
                logger.info(f"  Stop requested, exiting after page {page_num - 1}")
                break
            # Construct URL (primary_url already contains full URL)
            if page_num == 1:
                url = target.primary_url
            else:
                url = f"{target.primary_url}?page={page_num}"

            logger.debug(f"  Fetching page {page_num}/{target.max_pages}: {url}")

            # Fetch page
            try:
                response = page.goto(url, timeout=WorkerConfig.BROWSER_TIMEOUT_MS, wait_until='domcontentloaded')

                status_code = response.status if response else None

                if not response or response.status != 200:
                    logger.warning(f"  Page {page_num} returned status {response.status if response else 'None'}")
                    break

                # Get HTML
                html = page.content()

                # RESILIENCE: Detect CAPTCHA/blocking
                is_captcha, captcha_type = detect_captcha(html)
                is_blocked, block_reason = detect_blocking(html, status_code)

                if is_captcha:
                    logger.warning(f"  CAPTCHA detected on page {page_num}: {captcha_type}")
                    stats['captcha_detected'] = True
                    stats['block_reason'] = f"CAPTCHA: {captcha_type}"

                    # Report to proxy pool
                    if proxy and proxy_pool:
                        proxy_pool.report_failure(proxy, "captcha")

                    # Break out - will trigger proxy rotation in worker loop
                    break

                if is_blocked:
                    logger.warning(f"  Blocking detected on page {page_num}: {block_reason}")
                    stats['blocked'] = True
                    stats['block_reason'] = block_reason

                    # Report to proxy pool
                    if proxy and proxy_pool:
                        proxy_pool.report_failure(proxy, "blocked")

                    # Break out - will trigger proxy rotation in worker loop
                    break

                # Parse results
                parsed_results = parse_yp_results_enhanced(html)

                if not parsed_results:
                    logger.info(f"  Page {page_num} has no results (early exit)")
                    break

                logger.info(f"  Parsed {len(parsed_results)} results from page {page_num}")

                # Filter results
                accepted, filter_stats = filter_yp_listings(parsed_results, min_score=min_score, include_sponsored=include_sponsored)

                logger.info(f"  Filter: {len(accepted)} accepted, {filter_stats.get('rejected', 0)} rejected")

                # Add unique results
                existing_websites = {r['website'] for r in results_all}
                new_results = [r for r in accepted if r['website'] not in existing_websites]

                results_all.extend(new_results)

                logger.info(f"  Added {len(new_results)} new unique results from page {page_num}")

                stats["pages_crawled"] += 1
                stats["raw_results"] += len(parsed_results)
                stats["accepted"] += len(accepted)
                stats["rejected"] += filter_stats.get('rejected', 0)

                # ATOMIC CHECKPOINT: Update page progress and save accepted listings together
                # This ensures we can resume from exactly where we left off
                try:
                    # Save accepted listings from this page
                    if accepted:
                        inserted, skipped, updated = upsert_discovered(accepted)
                        logger.debug(f"  Page {page_num}: {inserted} inserted, {updated} updated, {skipped} skipped")

                    # Update page checkpoint (atomic with listing saves)
                    target.page_current = page_num
                    target.heartbeat_at = datetime.utcnow()  # Heartbeat on each page

                    # Calculate next page URL
                    if page_num < target.max_pages:
                        target.next_page_url = f"{target.primary_url}?page={page_num + 1}"
                    else:
                        target.next_page_url = None

                    session.commit()

                    # Log to WAL for visibility
                    if wal:
                        wal.log_page_complete(
                            target.id, page_num, len(accepted),
                            target.city, target.state_id, target.category_label,
                            raw_count=len(parsed_results)
                        )

                except Exception as e:
                    logger.error(f"  Failed to save page {page_num} checkpoint: {e}")
                    session.rollback()
                    raise

                # Early exit if no new results
                if len(new_results) == 0 and page_num > 1:
                    logger.info(f"  No new results on page {page_num}, stopping pagination")
                    break

            except PlaywrightTimeoutError:
                logger.warning(f"  Page {page_num} timed out")
                # Log error to WAL
                if wal:
                    wal.log_target_error(target.id, "Timeout", page_number=page_num)
                raise  # Re-raise to be handled by worker

            except Exception as e:
                logger.error(f"  Error fetching page {page_num}: {e}")
                # Log error to WAL
                if wal:
                    wal.log_target_error(target.id, str(e), page_number=page_num)
                break

        # Close page
        page.close()

        # Note: Results are saved per-page atomically with checkpoints
        # No need to save again here - this prevents duplicates on resume

        # Log target completion to WAL
        if wal:
            wal.log_target_complete(target.id, stats['pages_crawled'], stats['accepted'])

        # Log summary
        logger.info(f"Target complete: {target.city}, {target.state_id} - {target.category_label} | pages={stats['pages_crawled']}, parsed={stats['raw_results']}, accepted={stats['accepted']} ({stats['accepted']/stats['raw_results']*100 if stats['raw_results'] > 0 else 0:.1f}%)")

        return results_all, stats

    except Exception as e:
        logger.error(f"Error in crawl_single_target_with_context: {e}")
        # Log error to WAL
        if wal:
            wal.log_target_error(target.id, str(e))
        raise


class WorkerPoolManager:
    """
    Manages a pool of worker processes for parallel scraping.

    Features:
    - Spawns N worker processes
    - Distributes proxies to workers
    - Monitors worker health
    - Handles graceful shutdown
    - Aggregates progress
    """

    def __init__(self, num_workers: int, proxy_file: str, state_ids: List[str]):
        """
        Initialize worker pool manager.

        Args:
            num_workers: Number of worker processes
            proxy_file: Path to proxy file
            state_ids: List of state codes to scrape
        """
        self.num_workers = num_workers
        self.proxy_file = proxy_file
        self.state_ids = state_ids

        self.workers: List[multiprocessing.Process] = []
        self.stop_event = multiprocessing.Event()

        self.logger = get_logger("worker_pool")

    def start(self):
        """Start all worker processes."""
        self.logger.info("=" * 60)
        self.logger.info(f"Starting {self.num_workers} workers...")
        self.logger.info(f"States: {', '.join(self.state_ids)}")
        self.logger.info("=" * 60)

        for worker_id in range(self.num_workers):
            worker = multiprocessing.Process(
                target=worker_main,
                args=(worker_id, self.proxy_file, self.state_ids, self.stop_event),
                name=f"Worker-{worker_id}"
            )
            worker.start()
            self.workers.append(worker)

            self.logger.info(f"Started worker {worker_id} (PID: {worker.pid})")

        self.logger.info(f"All {self.num_workers} workers started")

    def stop(self):
        """Stop all worker processes gracefully."""
        self.logger.info("Stopping workers...")
        self.stop_event.set()

        # Wait for workers to finish
        for idx, worker in enumerate(self.workers):
            worker.join(timeout=30)

            if worker.is_alive():
                self.logger.warning(f"Worker {idx} did not stop gracefully, terminating...")
                worker.terminate()
                worker.join(timeout=5)

            self.logger.info(f"Worker {idx} stopped")

        self.logger.info("All workers stopped")

    def wait(self):
        """Wait for all workers to complete."""
        try:
            for worker in self.workers:
                worker.join()
        except KeyboardInterrupt:
            self.logger.info("Interrupted, stopping workers...")
            self.stop()


def main():
    """Demo: Run worker pool with configuration."""
    # Validate config
    try:
        WorkerConfig.validate()
        WorkerConfig.print_summary()
    except ValueError as e:
        print(f"✗ Configuration error:\n{e}")
        return

    # Parse states
    if WorkerConfig.TARGET_STATES == "ALL":
        # Get all states from database
        session = create_worker_session()
        from db.models import YPTarget
        state_ids = session.query(YPTarget.state_id).distinct().all()
        state_ids = [s[0] for s in state_ids]
        session.close()
    else:
        state_ids = [s.strip() for s in WorkerConfig.TARGET_STATES.split(',')]

    print(f"\nScraping {len(state_ids)} states: {', '.join(state_ids)}")

    # Create and start worker pool
    pool = WorkerPoolManager(
        num_workers=WorkerConfig.WORKER_COUNT,
        proxy_file=WorkerConfig.PROXY_FILE,
        state_ids=state_ids
    )

    # Setup signal handlers
    def signal_handler(sig, frame):
        print("\nReceived interrupt signal, stopping workers...")
        pool.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start and wait
    pool.start()
    print(f"\nWorker pool running with {pool.num_workers} workers...")
    print("Press Ctrl+C to stop\n")

    pool.wait()

    print("\nWorker pool finished")


if __name__ == "__main__":
    main()
