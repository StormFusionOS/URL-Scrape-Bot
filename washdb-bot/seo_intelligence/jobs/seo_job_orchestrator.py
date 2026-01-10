"""
SEO Job Orchestrator.

Main coordinator for SEO background job processing.
Handles:
- Querying eligible companies (verified + standardized)
- Dispatching to appropriate module jobs
- Managing GoogleCoordinator lifecycle
- Rate limiting between jobs
- Heartbeat monitoring for health checks
"""

# CRITICAL: Apply nest_asyncio BEFORE any other imports
# This fixes "Playwright Sync API inside asyncio loop" errors
# that occur when using Camoufox/Playwright sync API
import nest_asyncio
nest_asyncio.apply()

import argparse
import json
import logging
import os
import signal
import socket
import sys
import threading
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from sqlalchemy import text

from db.database_manager import get_db_manager
from seo_intelligence.jobs.keyword_assigner import KeywordAssigner
from seo_intelligence.jobs.seo_module_jobs import (
    get_all_job_classes,
    INITIAL_SCRAPE_ORDER,
    MODULE_SERP,
    MODULE_AUTOCOMPLETE,
    MODULE_KEYWORD_INTEL,
    MODULE_COMPETITIVE_ANALYSIS,
)

# System monitor for centralized error logging
try:
    from services.system_monitor import get_system_monitor, ErrorSeverity, ServiceName
    SYSTEM_MONITOR_AVAILABLE = True
except ImportError:
    SYSTEM_MONITOR_AVAILABLE = False
    logger.warning("System monitor not available - errors won't be logged to central table")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def sd_notify(state: str):
    """
    Send notification to systemd.

    Common states:
    - READY=1: Service is ready
    - WATCHDOG=1: Watchdog keepalive ping
    - STOPPING=1: Service is stopping
    - STATUS=<text>: Status text
    """
    notify_socket = os.environ.get('NOTIFY_SOCKET')
    if not notify_socket:
        return  # Not running under systemd

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        if notify_socket.startswith('@'):
            # Abstract socket
            notify_socket = '\0' + notify_socket[1:]
        sock.connect(notify_socket)
        sock.sendall(state.encode('utf-8'))
        sock.close()
    except Exception as e:
        logger.debug(f"sd_notify failed: {e}")

# Google-based modules need longer delays
GOOGLE_MODULES = {MODULE_SERP, MODULE_AUTOCOMPLETE, MODULE_KEYWORD_INTEL, MODULE_COMPETITIVE_ANALYSIS}

# Delay between modules
DELAY_TECHNICAL_MODULE = 5  # 5 seconds between technical modules
DELAY_GOOGLE_MODULE = 30  # 30 seconds between Google-based modules
DELAY_BETWEEN_COMPANIES = 60  # 60 seconds between companies
DELAY_NO_WORK = 300  # 5 minutes when no work available

# Heartbeat settings
HEARTBEAT_INTERVAL = 30  # Update heartbeat every 30 seconds
STALE_THRESHOLD_MINUTES = 5  # Consider worker stale after 5 minutes without heartbeat


class HeartbeatManager:
    """Manages heartbeat updates in a background thread."""

    def __init__(self, db_manager, worker_name: str, worker_type: str = 'seo_orchestrator'):
        self.db_manager = db_manager
        self.worker_name = worker_name
        self.worker_type = worker_type
        self.running = False
        self._thread = None
        self._lock = threading.Lock()

        # Stats
        self.companies_processed = 0
        self.jobs_completed = 0
        self.jobs_failed = 0
        self.current_company_id = None
        self.current_module = None
        self.last_error = None
        self.last_error_at = None
        self.started_at = None
        self._job_durations = []

    def start(self, config: dict = None):
        """Start the heartbeat thread."""
        self.running = True
        self.started_at = datetime.now()

        # Register worker in database
        self._register_worker(config or {})

        # Start background thread
        self._thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._thread.start()
        logger.info(f"Heartbeat started for worker: {self.worker_name}")

    def stop(self, status: str = 'stopped'):
        """Stop the heartbeat thread and update final status."""
        self.running = False
        self._update_status(status)
        if self._thread:
            self._thread.join(timeout=5)
        logger.info(f"Heartbeat stopped for worker: {self.worker_name}")

    def set_current_work(self, company_id: int = None, module: str = None):
        """Update current work being done."""
        with self._lock:
            self.current_company_id = company_id
            self.current_module = module

    def record_job_complete(self, duration_seconds: float = None):
        """Record a completed job."""
        with self._lock:
            self.jobs_completed += 1
            if duration_seconds:
                self._job_durations.append(duration_seconds)
                # Keep only last 100 durations for average
                if len(self._job_durations) > 100:
                    self._job_durations = self._job_durations[-100:]

    def record_job_failed(self, error: str, module_name: str = None, company_id: int = None):
        """Record a failed job and log to centralized error tracking."""
        with self._lock:
            self.jobs_failed += 1
            self.last_error = error[:500] if error else None  # Truncate long errors
            self.last_error_at = datetime.now()

        # Log to centralized system monitor
        if SYSTEM_MONITOR_AVAILABLE:
            try:
                monitor = get_system_monitor()
                monitor.log_error(
                    service=ServiceName.SEO_WORKER,
                    message=error[:500] if error else "Unknown error",
                    severity=ErrorSeverity.ERROR,
                    error_code="JOB_FAILED",
                    component=module_name or self.current_module,
                    context={
                        'company_id': company_id or self.current_company_id,
                        'module': module_name or self.current_module,
                        'worker_name': self.worker_name,
                        'jobs_failed': self.jobs_failed,
                    }
                )
            except Exception as e:
                logger.debug(f"Failed to log error to system monitor: {e}")

    def record_company_complete(self):
        """Record a company fully processed."""
        with self._lock:
            self.companies_processed += 1

    def _register_worker(self, config: dict):
        """Register this worker in the database."""
        try:
            with self.db_manager.get_session() as session:
                query = text("""
                    INSERT INTO job_heartbeats
                        (worker_name, worker_type, status, pid, hostname, config, started_at, last_heartbeat)
                    VALUES
                        (:worker_name, :worker_type, 'running', :pid, :hostname, :config, NOW(), NOW())
                    ON CONFLICT (worker_name)
                    DO UPDATE SET
                        status = 'running',
                        pid = :pid,
                        hostname = :hostname,
                        config = :config,
                        started_at = NOW(),
                        last_heartbeat = NOW(),
                        companies_processed = 0,
                        jobs_completed = 0,
                        jobs_failed = 0,
                        current_company_id = NULL,
                        current_module = NULL,
                        last_error = NULL,
                        last_error_at = NULL
                """)
                session.execute(query, {
                    'worker_name': self.worker_name,
                    'worker_type': self.worker_type,
                    'pid': os.getpid(),
                    'hostname': socket.gethostname(),
                    'config': json.dumps(config)
                })
                session.commit()
        except Exception as e:
            logger.error(f"Failed to register worker: {e}")

    def _heartbeat_loop(self):
        """Background loop that updates heartbeat every HEARTBEAT_INTERVAL seconds."""
        while self.running:
            try:
                self._send_heartbeat()
                # Also notify systemd watchdog
                sd_notify("WATCHDOG=1")
            except Exception as e:
                logger.warning(f"Heartbeat update failed: {e}")

            # Sleep in small increments to allow quick shutdown
            for _ in range(HEARTBEAT_INTERVAL):
                if not self.running:
                    break
                time.sleep(1)

    def _send_heartbeat(self):
        """Send a heartbeat update to the database."""
        with self._lock:
            avg_duration = None
            if self._job_durations:
                avg_duration = sum(self._job_durations) / len(self._job_durations)

            with self.db_manager.get_session() as session:
                query = text("""
                    UPDATE job_heartbeats
                    SET last_heartbeat = NOW(),
                        status = 'running',
                        companies_processed = :companies_processed,
                        jobs_completed = :jobs_completed,
                        jobs_failed = :jobs_failed,
                        current_company_id = :current_company_id,
                        current_module = :current_module,
                        avg_job_duration_seconds = :avg_duration,
                        last_error = :last_error,
                        last_error_at = :last_error_at
                    WHERE worker_name = :worker_name
                """)
                session.execute(query, {
                    'worker_name': self.worker_name,
                    'companies_processed': self.companies_processed,
                    'jobs_completed': self.jobs_completed,
                    'jobs_failed': self.jobs_failed,
                    'current_company_id': self.current_company_id,
                    'current_module': self.current_module,
                    'avg_duration': avg_duration,
                    'last_error': self.last_error,
                    'last_error_at': self.last_error_at
                })
                session.commit()

    def _update_status(self, status: str):
        """Update worker status in database."""
        try:
            with self.db_manager.get_session() as session:
                query = text("""
                    UPDATE job_heartbeats
                    SET status = :status,
                        last_heartbeat = NOW(),
                        current_company_id = NULL,
                        current_module = NULL
                    WHERE worker_name = :worker_name
                """)
                session.execute(query, {
                    'worker_name': self.worker_name,
                    'status': status
                })
                session.commit()
        except Exception as e:
            logger.error(f"Failed to update status: {e}")


class SEOJobOrchestrator:
    """
    Orchestrates SEO background jobs for all eligible companies.
    """

    def __init__(self, db_manager=None, test_mode: bool = False, limit: int = 0,
                 worker_name: str = None):
        """
        Initialize the orchestrator.

        Args:
            db_manager: Database manager (optional)
            test_mode: If True, run in test mode (process one company then exit)
            limit: Maximum companies to process (0 = unlimited)
            worker_name: Unique name for this worker instance
        """
        self.db_manager = db_manager or get_db_manager()
        self.test_mode = test_mode
        self.limit = limit
        self.running = True
        self.job_classes = get_all_job_classes()
        self.keyword_assigner = KeywordAssigner(db_manager=self.db_manager)
        self.companies_processed = 0

        # Generate unique worker name if not provided
        if worker_name is None:
            worker_name = f"seo_orchestrator_{socket.gethostname()}_{os.getpid()}"
        self.worker_name = worker_name

        # Initialize heartbeat manager
        self.heartbeat = HeartbeatManager(
            db_manager=self.db_manager,
            worker_name=self.worker_name,
            worker_type='seo_orchestrator'
        )

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False

    def run(self):
        """
        Main run loop for the orchestrator.
        """
        logger.info("=" * 60)
        logger.info("SEO Job Orchestrator starting...")
        logger.info(f"Worker name: {self.worker_name}")
        logger.info(f"Test mode: {self.test_mode}, Limit: {self.limit or 'unlimited'}")
        logger.info("=" * 60)

        # Start heartbeat
        self.heartbeat.start(config={
            'test_mode': self.test_mode,
            'limit': self.limit,
            'pid': os.getpid()
        })

        # Initialize GoogleCoordinator if available
        self._init_google_coordinator()

        # Notify systemd we're ready
        sd_notify("READY=1")
        logger.info("Service ready, notified systemd")

        try:
            while self.running:
                # Check if limit reached
                if self.limit > 0 and self.companies_processed >= self.limit:
                    logger.info(f"Limit of {self.limit} companies reached, stopping...")
                    break

                # Clean up stale jobs (stuck in running state)
                self._cleanup_stale_jobs()

                # Check browser pool health - pause if draining or recovering
                if not self._check_pool_health():
                    logger.info("Pool not healthy, waiting 30s before retry...")
                    self.heartbeat.set_current_work(None, 'waiting_pool')
                    self._sleep_with_interrupt(30)
                    continue

                # Update heartbeat state
                self.heartbeat.set_current_work(None, 'idle')

                # Process initial scrapes
                initial_processed = self._process_initial_scrapes(batch_size=5)

                # Process quarterly refreshes
                refresh_processed = self._process_quarterly_refreshes(batch_size=2)

                total_processed = initial_processed + refresh_processed
                self.companies_processed += total_processed

                if total_processed == 0:
                    if self.test_mode:
                        logger.info("No work available in test mode, exiting...")
                        break
                    logger.info(f"No work available, sleeping {DELAY_NO_WORK}s...")
                    self.heartbeat.set_current_work(None, 'waiting')
                    self._sleep_with_interrupt(DELAY_NO_WORK)
                else:
                    logger.info(f"Processed {total_processed} companies, total: {self.companies_processed}")
                    self._sleep_with_interrupt(DELAY_BETWEEN_COMPANIES)

        except Exception as e:
            logger.error(f"Orchestrator error: {e}", exc_info=True)
            self.heartbeat.record_job_failed(str(e))
            self.heartbeat.stop('failed')
            raise
        finally:
            # Notify systemd we're stopping
            sd_notify("STOPPING=1")
            self._cleanup()
            self.heartbeat.stop('stopped')
            logger.info("=" * 60)
            logger.info(f"SEO Job Orchestrator stopped.")
            logger.info(f"Total companies processed: {self.companies_processed}")
            logger.info(f"Total jobs completed: {self.heartbeat.jobs_completed}")
            logger.info(f"Total jobs failed: {self.heartbeat.jobs_failed}")
            logger.info("=" * 60)

    def _sleep_with_interrupt(self, seconds: int):
        """Sleep that can be interrupted by shutdown signal."""
        for _ in range(seconds):
            if not self.running:
                break
            time.sleep(1)

    def _check_pool_health(self) -> bool:
        """
        Check if browser pool is healthy and ready for work.

        Returns:
            True if pool is healthy, False if draining or in critical state
        """
        try:
            from seo_intelligence.drivers.browser_pool import get_browser_pool

            pool = get_browser_pool()
            status = pool.get_pool_health_status()

            # Don't process during drain mode
            if status.get('drain_mode'):
                logger.warning("Browser pool is in drain mode - pausing work")
                return False

            # Allow processing during recovery mode (pool handles extended warmup)
            # but log it for monitoring
            if status.get('recovery_mode'):
                logger.info(f"Pool in recovery mode (progress: {status.get('recovery_progress')})")
                # Allow work to continue - this helps the pool recover

            return True

        except ImportError:
            # Pool not available - continue anyway
            return True
        except Exception as e:
            logger.warning(f"Failed to check pool health: {e}")
            # On error, continue processing
            return True

    def _init_google_coordinator(self):
        """Initialize GoogleCoordinator and infrastructure watchdogs."""
        # Start Xvfb watchdog first (other components depend on display)
        try:
            from seo_intelligence.drivers.xvfb_watchdog import get_xvfb_watchdog
            watchdog = get_xvfb_watchdog()
            watchdog.start(recovery_callback=self._on_xvfb_recovery)
            logger.info("Xvfb watchdog started")
        except Exception as e:
            logger.warning(f"Could not start Xvfb watchdog: {e}")

        # Start self-healing coordinator for infrastructure resilience
        try:
            from seo_intelligence.orchestrator.self_healing import get_self_healing_coordinator
            self._self_healing = get_self_healing_coordinator()
            self._self_healing.start()
            logger.info("Self-healing coordinator started")
        except Exception as e:
            logger.warning(f"Could not start self-healing coordinator: {e}")

        # Initialize GoogleCoordinator for shared browser sessions
        try:
            from seo_intelligence.services.google_coordinator import get_google_coordinator
            coordinator = get_google_coordinator(headless=False, use_proxy=True)
            logger.info("GoogleCoordinator initialized")
        except Exception as e:
            logger.warning(f"Could not initialize GoogleCoordinator: {e}")

    def _on_xvfb_recovery(self):
        """Callback when Xvfb display is recovered."""
        logger.warning("Xvfb recovered - browser sessions may need reinitialization")
        # The browser pool handles session invalidation via its own callback

    def _cleanup(self):
        """
        Cleanup resources during graceful shutdown.

        Order of cleanup:
        1. GoogleCoordinator (stop any Google requests)
        2. Browser Pool (drain and close all sessions)
        3. Chrome Process Manager (cleanup orphans)
        4. Xvfb Watchdog (stop monitoring)
        """
        logger.info("Starting graceful cleanup...")

        # 1. Cleanup GoogleCoordinator
        try:
            from seo_intelligence.services.google_coordinator import get_google_coordinator
            coordinator = get_google_coordinator()
            coordinator.close()
            logger.info("GoogleCoordinator cleaned up")
        except Exception as e:
            logger.debug(f"GoogleCoordinator cleanup error: {e}")

        # 2. Drain browser pool - wait for active leases to complete
        try:
            from seo_intelligence.drivers.browser_pool import get_browser_pool
            pool = get_browser_pool()
            if pool.is_enabled():
                logger.info("Draining browser pool (waiting for active leases)...")
                pool.enter_drain_mode(timeout=60)
                pool.shutdown()
                logger.info("Browser pool drained and shut down")
        except Exception as e:
            logger.debug(f"Browser pool cleanup error: {e}")

        # 3. Clean up orphaned Chrome processes
        try:
            from seo_intelligence.drivers.chrome_process_manager import get_chrome_process_manager
            pm = get_chrome_process_manager()
            cleaned = pm.cleanup_orphaned_processes()
            if cleaned:
                logger.info(f"Cleaned {cleaned} orphaned Chrome processes")
        except Exception as e:
            logger.debug(f"Chrome process cleanup error: {e}")

        # 4. Stop self-healing coordinator
        try:
            if hasattr(self, '_self_healing') and self._self_healing:
                self._self_healing.stop()
                logger.info("Self-healing coordinator stopped")
        except Exception as e:
            logger.debug(f"Self-healing cleanup error: {e}")

        # 5. Stop Xvfb watchdog
        try:
            from seo_intelligence.drivers.xvfb_watchdog import get_xvfb_watchdog
            watchdog = get_xvfb_watchdog()
            watchdog.stop()
            logger.info("Xvfb watchdog stopped")
        except Exception as e:
            logger.debug(f"Xvfb watchdog cleanup error: {e}")

        logger.info("Graceful cleanup complete")

    def _cleanup_stale_jobs(self):
        """
        Clean up jobs stuck in 'running' state for too long.

        This handles cases where:
        - Browser hangs and timeout is never reached
        - Process crashes/restarts leaving orphaned job records
        - Google modules bypass ThreadPoolExecutor and hang forever

        Jobs are marked failed if stuck for >2x their configured timeout.
        """
        try:
            from seo_intelligence.jobs.seo_module_jobs import MODULE_TIMEOUTS, DEFAULT_MODULE_TIMEOUT

            with self.db_manager.get_session() as session:
                # Get stuck jobs with their configured timeouts
                query = text("""
                    SELECT tracking_id, module_name, company_id, started_at,
                           EXTRACT(EPOCH FROM (NOW() - started_at))::int as elapsed_seconds
                    FROM seo_job_tracking
                    WHERE status = 'running'
                      AND started_at < NOW() - INTERVAL '10 minutes'
                    ORDER BY started_at ASC
                """)
                result = session.execute(query)
                stuck_jobs = result.fetchall()

                if not stuck_jobs:
                    return

                cleaned = 0
                for tracking_id, module_name, company_id, started_at, elapsed in stuck_jobs:
                    # Get module timeout (2x for grace period)
                    timeout = MODULE_TIMEOUTS.get(module_name, DEFAULT_MODULE_TIMEOUT)
                    max_allowed = timeout * 2

                    if elapsed > max_allowed:
                        update_query = text("""
                            UPDATE seo_job_tracking
                            SET status = 'failed',
                                completed_at = NOW(),
                                error_message = :error_msg,
                                retry_count = retry_count + 1
                            WHERE tracking_id = :tracking_id
                        """)
                        session.execute(update_query, {
                            'tracking_id': tracking_id,
                            'error_msg': f'Job abandoned: stuck for {elapsed}s (timeout: {timeout}s)'
                        })
                        cleaned += 1
                        logger.warning(
                            f"Cleaned stale job {tracking_id}: {module_name} for company {company_id} "
                            f"(stuck {elapsed}s, timeout {timeout}s)"
                        )

                if cleaned > 0:
                    session.commit()
                    logger.info(f"Cleaned {cleaned} stale jobs")

        except Exception as e:
            logger.error(f"Error cleaning stale jobs: {e}")

    def _process_initial_scrapes(self, batch_size: int = 5) -> int:
        """
        Process companies that need initial SEO scrape.

        Returns number of companies processed.
        """
        # Get eligible companies
        companies = self._get_initial_scrape_candidates(limit=batch_size)
        if not companies:
            return 0

        logger.info(f"Found {len(companies)} companies needing initial scrape")

        processed = 0
        for company in companies:
            if not self.running:
                break

            company_id = company['company_id']
            self.heartbeat.set_current_work(company_id, 'initial_scrape')
            logger.info(f"Processing initial scrape for company {company_id}: {company.get('domain')}")

            try:
                start_time = time.time()

                # Step 1: Assign keywords
                keywords_assigned, tier_counts = self.keyword_assigner.assign_keywords_for_company(company_id)
                logger.info(f"  Assigned {keywords_assigned} keywords")

                # Step 2: Run all modules in order
                for module_name in INITIAL_SCRAPE_ORDER:
                    if not self.running:
                        break

                    self.heartbeat.set_current_work(company_id, module_name)

                    job_class = self.job_classes.get(module_name)
                    if not job_class:
                        continue

                    module_start = time.time()
                    job = job_class(db_manager=self.db_manager)
                    result = job.run_for_company(company_id, run_type='initial')
                    module_duration = time.time() - module_start

                    if result.get('success'):
                        self.heartbeat.record_job_complete(module_duration)
                    else:
                        logger.warning(f"  Module {module_name} failed: {result.get('error')}")
                        self.heartbeat.record_job_failed(f"{module_name}: {result.get('error')}")

                    # Rate limit
                    delay = DELAY_GOOGLE_MODULE if module_name in GOOGLE_MODULES else DELAY_TECHNICAL_MODULE
                    self._sleep_with_interrupt(delay)

                # Step 3: Mark initial complete
                self._mark_initial_complete(company_id)
                processed += 1
                self.heartbeat.record_company_complete()

                total_duration = time.time() - start_time
                logger.info(f"  Initial scrape complete for company {company_id} ({total_duration:.1f}s)")

            except Exception as e:
                logger.error(f"  Failed to process company {company_id}: {e}")
                self.heartbeat.record_job_failed(str(e))

            # Rate limit between companies
            if self.running and processed < len(companies):
                self._sleep_with_interrupt(DELAY_BETWEEN_COMPANIES)

        return processed

    def _process_quarterly_refreshes(self, batch_size: int = 2) -> int:
        """
        Process companies due for quarterly refresh.

        Returns number of companies processed.
        """
        # Get companies due for refresh
        companies = self._get_refresh_candidates(limit=batch_size)
        if not companies:
            return 0

        logger.info(f"Found {len(companies)} companies needing quarterly refresh")

        processed = 0
        for company in companies:
            if not self.running:
                break

            company_id = company['company_id']
            self.heartbeat.set_current_work(company_id, 'quarterly_refresh')
            logger.info(f"Processing quarterly refresh for company {company_id}: {company.get('domain')}")

            try:
                start_time = time.time()

                # Step 1: Expand keywords
                new_keywords = self.keyword_assigner.expand_keywords_for_company(company_id)
                logger.info(f"  Added {new_keywords} new keywords")

                # Step 2: Run all modules in deep refresh mode
                for module_name in INITIAL_SCRAPE_ORDER:
                    if not self.running:
                        break

                    self.heartbeat.set_current_work(company_id, module_name)

                    job_class = self.job_classes.get(module_name)
                    if not job_class:
                        continue

                    module_start = time.time()
                    job = job_class(db_manager=self.db_manager)
                    result = job.run_for_company(company_id, run_type='quarterly')
                    module_duration = time.time() - module_start

                    if result.get('success'):
                        self.heartbeat.record_job_complete(module_duration)
                    else:
                        logger.warning(f"  Module {module_name} failed: {result.get('error')}")
                        self.heartbeat.record_job_failed(f"{module_name}: {result.get('error')}")

                    # Rate limit
                    delay = DELAY_GOOGLE_MODULE if module_name in GOOGLE_MODULES else DELAY_TECHNICAL_MODULE
                    self._sleep_with_interrupt(delay)

                # Step 3: Update refresh timestamp
                self._mark_refresh_complete(company_id)
                processed += 1
                self.heartbeat.record_company_complete()

                total_duration = time.time() - start_time
                logger.info(f"  Quarterly refresh complete for company {company_id} ({total_duration:.1f}s)")

            except Exception as e:
                logger.error(f"  Failed to refresh company {company_id}: {e}")
                self.heartbeat.record_job_failed(str(e))

            # Rate limit between companies
            if self.running and processed < len(companies):
                self._sleep_with_interrupt(DELAY_BETWEEN_COMPANIES)

        return processed

    def _get_initial_scrape_candidates(self, limit: int = 10) -> List[Dict]:
        """Get companies eligible for initial SEO scrape."""
        with self.db_manager.get_session() as session:
            query = text("""
                SELECT id, domain, standardized_name, service_area, city, state
                FROM companies
                WHERE verified = true
                  AND standardized_name IS NOT NULL
                  AND seo_initial_complete = false
                ORDER BY created_at ASC
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
            """)
            result = session.execute(query, {"limit": limit})
            rows = result.fetchall()
            return [{
                'company_id': row[0],
                'domain': row[1],
                'standardized_name': row[2],
                'service_area': row[3],
                'city': row[4],
                'state': row[5]
            } for row in rows]

    def _get_refresh_candidates(self, limit: int = 5) -> List[Dict]:
        """Get companies due for quarterly refresh."""
        with self.db_manager.get_session() as session:
            query = text("""
                SELECT id, domain, standardized_name, service_area, city, state
                FROM companies
                WHERE verified = true
                  AND standardized_name IS NOT NULL
                  AND seo_initial_complete = true
                  AND seo_next_refresh_due <= NOW()
                ORDER BY seo_next_refresh_due ASC
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
            """)
            result = session.execute(query, {"limit": limit})
            rows = result.fetchall()
            return [{
                'company_id': row[0],
                'domain': row[1],
                'standardized_name': row[2],
                'service_area': row[3],
                'city': row[4],
                'state': row[5]
            } for row in rows]

    def _mark_initial_complete(self, company_id: int):
        """Mark company's initial SEO scrape as complete."""
        with self.db_manager.get_session() as session:
            query = text("""
                UPDATE companies
                SET seo_initial_complete = true,
                    seo_last_full_scrape = NOW(),
                    seo_next_refresh_due = NOW() + INTERVAL '90 days'
                WHERE id = :company_id
            """)
            session.execute(query, {"company_id": company_id})
            session.commit()

    def _mark_refresh_complete(self, company_id: int):
        """Mark company's quarterly refresh as complete."""
        with self.db_manager.get_session() as session:
            query = text("""
                UPDATE companies
                SET seo_last_full_scrape = NOW(),
                    seo_next_refresh_due = NOW() + INTERVAL '90 days'
                WHERE id = :company_id
            """)
            session.execute(query, {"company_id": company_id})
            session.commit()

    def process_single_company(self, company_id: int, run_type: str = 'initial') -> Dict:
        """
        Process a single company (for testing or manual runs).

        Args:
            company_id: Company ID to process
            run_type: 'initial' or 'quarterly'

        Returns:
            Dict with results for each module
        """
        results = {}

        # Get company
        with self.db_manager.get_session() as session:
            query = text("""
                SELECT id, domain, standardized_name, verified
                FROM companies
                WHERE id = :company_id
            """)
            result = session.execute(query, {"company_id": company_id})
            row = result.fetchone()
            if not row:
                return {'error': f'Company {company_id} not found'}
            if not row[3]:  # verified
                return {'error': f'Company {company_id} not verified'}

        logger.info(f"Processing company {company_id} ({run_type})")

        # Assign keywords if initial
        if run_type == 'initial':
            keywords_assigned, tier_counts = self.keyword_assigner.assign_keywords_for_company(company_id)
            results['keywords'] = {'assigned': keywords_assigned, 'tiers': tier_counts}

        # Run all modules
        for module_name in INITIAL_SCRAPE_ORDER:
            job_class = self.job_classes.get(module_name)
            if not job_class:
                continue

            job = job_class(db_manager=self.db_manager)
            result = job.run_for_company(company_id, run_type=run_type)
            results[module_name] = result

            # Rate limit
            delay = DELAY_GOOGLE_MODULE if module_name in GOOGLE_MODULES else DELAY_TECHNICAL_MODULE
            time.sleep(delay)

        # Mark complete
        if run_type == 'initial':
            self._mark_initial_complete(company_id)
        else:
            self._mark_refresh_complete(company_id)

        return results


def check_worker_health(db_manager=None) -> List[Dict]:
    """
    Check health of all registered workers.

    Returns list of worker status dictionaries.
    """
    db_manager = db_manager or get_db_manager()
    stale_threshold = datetime.now() - timedelta(minutes=STALE_THRESHOLD_MINUTES)

    with db_manager.get_session() as session:
        # First, mark stale workers
        mark_stale = text("""
            UPDATE job_heartbeats
            SET status = 'stale'
            WHERE status = 'running'
              AND last_heartbeat < :threshold
        """)
        session.execute(mark_stale, {'threshold': stale_threshold})
        session.commit()

        # Get all workers
        query = text("""
            SELECT worker_name, worker_type, status, last_heartbeat, started_at,
                   pid, hostname, companies_processed, jobs_completed, jobs_failed,
                   current_company_id, current_module, avg_job_duration_seconds,
                   last_error, last_error_at
            FROM job_heartbeats
            ORDER BY last_heartbeat DESC
        """)
        result = session.execute(query)
        rows = result.fetchall()

        workers = []
        for row in rows:
            last_heartbeat = row[3]
            uptime = None
            if row[4]:  # started_at
                uptime = (datetime.now() - row[4]).total_seconds()

            workers.append({
                'worker_name': row[0],
                'worker_type': row[1],
                'status': row[2],
                'last_heartbeat': last_heartbeat.isoformat() if last_heartbeat else None,
                'seconds_since_heartbeat': (datetime.now() - last_heartbeat).total_seconds() if last_heartbeat else None,
                'uptime_seconds': uptime,
                'pid': row[5],
                'hostname': row[6],
                'companies_processed': row[7],
                'jobs_completed': row[8],
                'jobs_failed': row[9],
                'current_company_id': row[10],
                'current_module': row[11],
                'avg_job_duration_seconds': row[12],
                'last_error': row[13],
                'last_error_at': row[14].isoformat() if row[14] else None
            })

        return workers


def main():
    """Main entry point for SEO job orchestrator."""
    parser = argparse.ArgumentParser(description='SEO Job Orchestrator')
    parser.add_argument('--test', action='store_true', help='Run in test mode (single batch then exit)')
    parser.add_argument('--limit', type=int, default=0, help='Maximum companies to process (0=unlimited)')
    parser.add_argument('--company-id', type=int, help='Process a specific company ID')
    parser.add_argument('--run-type', choices=['initial', 'quarterly'], default='initial',
                        help='Run type for single company processing')
    parser.add_argument('--status', action='store_true', help='Show worker status and exit')
    parser.add_argument('--worker-name', type=str, help='Custom worker name (default: auto-generated)')
    args = parser.parse_args()

    # Status check mode
    if args.status:
        workers = check_worker_health()
        if not workers:
            print("No workers registered.")
            return

        print(f"\n{'='*80}")
        print("SEO Job Worker Status")
        print(f"{'='*80}")

        for w in workers:
            status_icon = {
                'running': '🟢',
                'stopped': '⚪',
                'failed': '🔴',
                'stale': '🟡'
            }.get(w['status'], '❓')

            print(f"\n{status_icon} {w['worker_name']}")
            print(f"   Status: {w['status']}")
            print(f"   Host: {w['hostname']} (PID: {w['pid']})")
            if w['seconds_since_heartbeat']:
                print(f"   Last heartbeat: {w['seconds_since_heartbeat']:.0f}s ago")
            if w['uptime_seconds']:
                hours = w['uptime_seconds'] / 3600
                print(f"   Uptime: {hours:.1f} hours")
            print(f"   Companies: {w['companies_processed']} | Jobs: {w['jobs_completed']} ✓ / {w['jobs_failed']} ✗")
            if w['current_module']:
                print(f"   Current: Company {w['current_company_id']} → {w['current_module']}")
            if w['avg_job_duration_seconds']:
                print(f"   Avg job duration: {w['avg_job_duration_seconds']:.1f}s")
            if w['last_error']:
                print(f"   Last error: {w['last_error'][:60]}...")

        print(f"\n{'='*80}\n")
        return

    # Single company mode
    if args.company_id:
        orchestrator = SEOJobOrchestrator(test_mode=True, limit=1, worker_name=args.worker_name)
        results = orchestrator.process_single_company(args.company_id, args.run_type)
        print(f"\nResults for company {args.company_id}:")
        for module, result in results.items():
            if isinstance(result, dict):
                success = result.get('success', 'N/A')
                records = result.get('records_created', 0)
                print(f"  {module}: success={success}, records={records}")
            else:
                print(f"  {module}: {result}")
        return

    # Continuous mode
    orchestrator = SEOJobOrchestrator(
        test_mode=args.test,
        limit=args.limit,
        worker_name=args.worker_name
    )
    orchestrator.run()


if __name__ == '__main__':
    main()
