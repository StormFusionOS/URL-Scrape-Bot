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


def acquire_next_target(session: Session, state_ids: List[str]) -> Optional[YPTarget]:
    """
    Acquire next target from database with row-level locking.

    Uses PostgreSQL SELECT FOR UPDATE SKIP LOCKED to prevent
    multiple workers from getting the same target.

    Args:
        session: Database session
        state_ids: List of state codes to filter by

    Returns:
        YPTarget object or None if no targets available
    """
    try:
        # Build query with locking
        query = (
            session.query(YPTarget)
            .filter(
                YPTarget.state_id.in_(state_ids),
                YPTarget.status == "planned"
            )
            .order_by(YPTarget.priority.asc(), YPTarget.id.asc())
            .with_for_update(skip_locked=True)  # PostgreSQL row-level lock
            .limit(1)
        )

        target = query.first()

        if target:
            # Mark as in progress
            target.status = "in_progress"
            target.last_attempt_ts = datetime.utcnow()
            target.attempts += 1
            session.commit()

            logger.debug(f"Acquired target {target.id}: {target.city}, {target.state_id} - {target.category_label}")

        return target

    except Exception as e:
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

    logger.info("=" * 60)
    logger.info(f"Worker {worker_id} starting...")
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

    # Initialize browser
    browser = None
    browser_context = None
    playwright_instance = None
    targets_processed_this_browser = 0

    try:
        # Main worker loop
        while not stop_event.is_set():
            # Acquire next target
            target = acquire_next_target(session, state_ids)

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
                    except:
                        pass

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
                # Pass browser context to crawl function
                results, stats = crawl_single_target_with_context(
                    target=target,
                    browser_context=browser_context,
                    session=session,
                    min_score=WorkerConfig.MIN_CONFIDENCE_SCORE,
                    include_sponsored=WorkerConfig.INCLUDE_SPONSORED
                )

                # Report success
                proxy_pool.report_success(current_proxy)
                targets_processed_this_browser += 1

                # Mark target as done
                target.status = "done"
                target.note = f"Completed: {stats.get('accepted', 0)} results"
                session.commit()

                logger.info(f"✓ Target {target.id} complete: {stats.get('accepted', 0)} results accepted")

            except PlaywrightTimeoutError as e:
                logger.warning(f"Timeout on target {target.id}: {e}")
                proxy_pool.report_failure(current_proxy, "timeout")

                # Mark target as failed or retry
                if target.attempts >= WorkerConfig.MAX_TARGET_RETRY_ATTEMPTS:
                    target.status = "failed"
                    target.note = f"Failed after {target.attempts} attempts: timeout"
                    logger.error(f"✗ Target {target.id} failed (max retries)")
                else:
                    target.status = "planned"  # Retry later
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
                    target.status = "failed"
                    target.note = f"Failed after {target.attempts} attempts: {str(e)[:200]}"
                    logger.error(f"✗ Target {target.id} failed (max retries)")
                else:
                    target.status = "planned"
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
            except:
                pass

        if playwright_instance:
            try:
                playwright_instance.stop()
            except:
                pass

        session.close()

        # Print proxy stats
        stats = proxy_pool.get_stats()
        logger.info(f"Final proxy stats: {stats['total_successes']} successes, {stats['total_failures']} failures, {stats['overall_success_rate']:.1%} success rate")

        logger.info(f"Worker {worker_id} stopped")


def crawl_single_target_with_context(target, browser_context, session, min_score, include_sponsored):
    """
    Crawl a single target using existing browser context.

    This is a wrapper around the existing crawl_single_target function
    but uses a pre-existing browser context instead of launching a new browser.

    Args:
        target: YPTarget object
        browser_context: Playwright BrowserContext (with proxy already configured)
        session: Database session
        min_score: Minimum confidence score
        include_sponsored: Include sponsored listings

    Returns:
        Tuple of (results, stats)
    """
    from scrape_yp.yp_parser_enhanced import parse_yp_results_enhanced
    from scrape_yp.yp_filter import filter_yp_listings
    from db.save_discoveries import upsert_discovered

    results_all = []
    stats = {
        "pages_crawled": 0,
        "raw_results": 0,
        "accepted": 0,
        "rejected": 0
    }

    try:
        # Create a new page in the context
        page = browser_context.new_page()

        # Crawl up to max_pages
        for page_num in range(1, target.max_pages + 1):
            # Construct URL (primary_url already contains full URL)
            if page_num == 1:
                url = target.primary_url
            else:
                url = f"{target.primary_url}?page={page_num}"

            logger.debug(f"  Fetching page {page_num}/{target.max_pages}: {url}")

            # Fetch page
            try:
                response = page.goto(url, timeout=WorkerConfig.BROWSER_TIMEOUT_MS, wait_until='domcontentloaded')

                if not response or response.status != 200:
                    logger.warning(f"  Page {page_num} returned status {response.status if response else 'None'}")
                    break

                # Get HTML
                html = page.content()

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

                # Early exit if no new results
                if len(new_results) == 0 and page_num > 1:
                    logger.info(f"  No new results on page {page_num}, stopping pagination")
                    break

            except PlaywrightTimeoutError:
                logger.warning(f"  Page {page_num} timed out")
                raise  # Re-raise to be handled by worker

            except Exception as e:
                logger.error(f"  Error fetching page {page_num}: {e}")
                break

        # Close page
        page.close()

        # Save results to database
        if results_all:
            logger.info(f"Upserting {len(results_all)} companies...")
            inserted, skipped, updated = upsert_discovered(results_all)
            logger.info(f"Upsert complete: {inserted} inserted, {updated} updated, {skipped} skipped")

            stats["inserted"] = inserted
            stats["updated"] = updated
            stats["skipped"] = skipped

        # Log summary
        logger.info(f"Target complete: {target.city}, {target.state_id} - {target.category_label} | pages={stats['pages_crawled']}, parsed={stats['raw_results']}, accepted={stats['accepted']} ({stats['accepted']/stats['raw_results']*100 if stats['raw_results'] > 0 else 0:.1f}%)")

        return results_all, stats

    except Exception as e:
        logger.error(f"Error in crawl_single_target_with_context: {e}")
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
