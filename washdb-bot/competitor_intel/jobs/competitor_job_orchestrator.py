"""
Competitor Intelligence Job Orchestrator.

Main coordinator for competitor tracking job processing.
Handles:
- Querying eligible competitors (active + due for refresh)
- Dispatching to module jobs (site_crawl, serp_track, etc.)
- Managing browser sessions
- Priority-based scheduling (daily, every-other-day, weekly)
- Heartbeat monitoring for health checks
"""

# CRITICAL: Apply nest_asyncio BEFORE any other imports
import nest_asyncio
nest_asyncio.apply()

import argparse
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
from competitor_intel.config import (
    MODULE_ORDER,
    MODULE_TIMEOUTS,
    DAILY_MODULES,
    WEEKLY_MODULES,
    REFRESH_INTERVALS,
    DEFAULT_PRIORITY_TIER,
    DELAY_BETWEEN_MODULES,
    DELAY_GOOGLE_MODULE,
    DELAY_BETWEEN_COMPETITORS,
    DELAY_NO_WORK,
    HEARTBEAT_INTERVAL,
    HEARTBEAT_TIMEOUT,
    JOB_TRACKING_TABLE,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def sd_notify(state: str):
    """Send notification to systemd."""
    notify_socket = os.environ.get('NOTIFY_SOCKET')
    if not notify_socket:
        return

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        if notify_socket.startswith('@'):
            notify_socket = '\0' + notify_socket[1:]
        sock.connect(notify_socket)
        sock.sendall(state.encode('utf-8'))
        sock.close()
    except Exception as e:
        logger.debug(f"sd_notify failed: {e}")


# Modules that need longer delays (Google-based or heavy scraping)
GOOGLE_MODULES = {'serp_track', 'review_deep_scrape', 'ad_detect'}


class HeartbeatManager:
    """Manages heartbeat updates in a background thread."""

    def __init__(self, db_manager, worker_name: str):
        self.db_manager = db_manager
        self.worker_name = worker_name
        self.running = False
        self._thread = None
        self._lock = threading.Lock()

        # Stats
        self.competitors_processed = 0
        self.jobs_completed = 0
        self.jobs_failed = 0
        self.current_competitor_id = None
        self.current_module = None
        self.last_error = None
        self.last_error_at = None
        self.started_at = None
        self._job_durations = []

    def start(self):
        """Start the heartbeat thread."""
        self.running = True
        self.started_at = datetime.now()
        self._register_worker()
        self._thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._thread.start()
        logger.info(f"Heartbeat started for worker: {self.worker_name}")

    def stop(self, status: str = 'stopped'):
        """Stop the heartbeat thread."""
        self.running = False
        self._update_status(status)
        if self._thread:
            self._thread.join(timeout=5)
        logger.info(f"Heartbeat stopped for worker: {self.worker_name}")

    def set_current_work(self, competitor_id: int = None, module: str = None):
        """Update current work being done."""
        with self._lock:
            self.current_competitor_id = competitor_id
            self.current_module = module

    def record_job_complete(self, duration_seconds: float = None):
        """Record a completed job."""
        with self._lock:
            self.jobs_completed += 1
            if duration_seconds:
                self._job_durations.append(duration_seconds)
                if len(self._job_durations) > 100:
                    self._job_durations = self._job_durations[-100:]

    def record_job_failed(self, error: str):
        """Record a failed job."""
        with self._lock:
            self.jobs_failed += 1
            self.last_error = error[:500] if error else None
            self.last_error_at = datetime.now()

    def record_competitor_complete(self):
        """Record a competitor fully processed."""
        with self._lock:
            self.competitors_processed += 1

    def _register_worker(self):
        """Register this worker in the database."""
        try:
            with self.db_manager.get_session() as session:
                query = text("""
                    INSERT INTO competitor_heartbeats
                        (worker_name, worker_type, status, pid, hostname, started_at, last_heartbeat)
                    VALUES
                        (:worker_name, 'competitor_intel', 'running', :pid, :hostname, NOW(), NOW())
                    ON CONFLICT (worker_name)
                    DO UPDATE SET
                        status = 'running',
                        pid = EXCLUDED.pid,
                        hostname = EXCLUDED.hostname,
                        started_at = NOW(),
                        last_heartbeat = NOW(),
                        competitors_processed = 0,
                        jobs_completed = 0,
                        jobs_failed = 0
                """)
                session.execute(query, {
                    'worker_name': self.worker_name,
                    'pid': os.getpid(),
                    'hostname': socket.gethostname(),
                })
                session.commit()
        except Exception as e:
            logger.error(f"Failed to register worker: {e}")

    def _heartbeat_loop(self):
        """Background thread that sends heartbeats."""
        while self.running:
            try:
                self._send_heartbeat()
                sd_notify("WATCHDOG=1")
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")

            time.sleep(HEARTBEAT_INTERVAL)

    def _send_heartbeat(self):
        """Send a heartbeat update to the database."""
        with self._lock:
            avg_duration = (
                sum(self._job_durations) / len(self._job_durations)
                if self._job_durations else None
            )

        try:
            with self.db_manager.get_session() as session:
                query = text("""
                    UPDATE competitor_heartbeats SET
                        last_heartbeat = NOW(),
                        competitors_processed = :competitors_processed,
                        jobs_completed = :jobs_completed,
                        jobs_failed = :jobs_failed,
                        current_competitor_id = :current_competitor_id,
                        current_module = :current_module,
                        avg_job_duration = :avg_duration,
                        last_error = :last_error,
                        last_error_at = :last_error_at
                    WHERE worker_name = :worker_name
                """)
                session.execute(query, {
                    'worker_name': self.worker_name,
                    'competitors_processed': self.competitors_processed,
                    'jobs_completed': self.jobs_completed,
                    'jobs_failed': self.jobs_failed,
                    'current_competitor_id': self.current_competitor_id,
                    'current_module': self.current_module,
                    'avg_duration': avg_duration,
                    'last_error': self.last_error,
                    'last_error_at': self.last_error_at,
                })
                session.commit()
        except Exception as e:
            logger.debug(f"Failed to send heartbeat: {e}")

    def _update_status(self, status: str):
        """Update worker status in database."""
        try:
            with self.db_manager.get_session() as session:
                query = text("""
                    UPDATE competitor_heartbeats
                    SET status = :status, last_heartbeat = NOW()
                    WHERE worker_name = :worker_name
                """)
                session.execute(query, {
                    'worker_name': self.worker_name,
                    'status': status,
                })
                session.commit()
        except Exception as e:
            logger.debug(f"Failed to update status: {e}")


class CompetitorJobOrchestrator:
    """
    Main orchestrator for competitor intelligence jobs.

    Processes competitors based on priority tier:
    - Priority 1: Daily refresh
    - Priority 2: Every other day
    - Priority 3: Weekly refresh
    """

    def __init__(self, worker_name: str = 'competitor_worker_1'):
        self.worker_name = worker_name
        self.db_manager = get_db_manager()
        self.running = False
        self.competitors_processed = 0
        self.heartbeat = HeartbeatManager(self.db_manager, worker_name)

        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.running = False

    def run(self, test_mode: bool = False):
        """
        Main run loop.

        Args:
            test_mode: If True, process one batch then exit
        """
        logger.info("=" * 60)
        logger.info(f"Competitor Intelligence Orchestrator starting")
        logger.info(f"Worker: {self.worker_name}")
        logger.info(f"Mode: {'test' if test_mode else 'continuous'}")
        logger.info("=" * 60)

        self.running = True
        self.heartbeat.start()

        # Notify systemd we're ready
        sd_notify("READY=1")

        try:
            while self.running:
                # Check browser pool health
                if not self._check_pool_health():
                    logger.info("Browser pool not ready, waiting 30s...")
                    self._sleep_with_interrupt(30)
                    continue

                # Process competitors due for refresh
                total_processed = self._process_refresh_batch()

                if test_mode:
                    logger.info("Test mode: exiting after one batch")
                    break

                if total_processed == 0:
                    logger.info(f"No work available, sleeping {DELAY_NO_WORK}s...")
                    self.heartbeat.set_current_work(None, 'waiting')
                    self._sleep_with_interrupt(DELAY_NO_WORK)
                else:
                    logger.info(f"Processed {total_processed} competitors")
                    self._sleep_with_interrupt(DELAY_BETWEEN_COMPETITORS)

        except Exception as e:
            logger.error(f"Orchestrator error: {e}", exc_info=True)
            self.heartbeat.record_job_failed(str(e))
            raise
        finally:
            sd_notify("STOPPING=1")
            self._cleanup()
            self.heartbeat.stop('stopped')
            logger.info("=" * 60)
            logger.info(f"Competitor Intel Orchestrator stopped")
            logger.info(f"Total competitors processed: {self.competitors_processed}")
            logger.info(f"Total jobs completed: {self.heartbeat.jobs_completed}")
            logger.info(f"Total jobs failed: {self.heartbeat.jobs_failed}")
            logger.info("=" * 60)

    def run_single_competitor(self, competitor_id: int):
        """Process a single competitor then exit."""
        logger.info(f"Processing single competitor: {competitor_id}")

        self.running = True
        self.heartbeat.start()

        try:
            self._process_competitor(competitor_id, run_type='manual')
            logger.info(f"Single competitor {competitor_id} processed successfully")
        except Exception as e:
            logger.error(f"Failed to process competitor {competitor_id}: {e}")
            self.heartbeat.record_job_failed(str(e))
        finally:
            self.heartbeat.stop()

    def _sleep_with_interrupt(self, seconds: int):
        """Sleep that can be interrupted by shutdown signal."""
        for _ in range(seconds):
            if not self.running:
                break
            time.sleep(1)

    def _check_pool_health(self) -> bool:
        """Check if browser pool is healthy."""
        try:
            from seo_intelligence.drivers.browser_pool import get_browser_pool
            pool = get_browser_pool()
            status = pool.get_pool_health_status()

            if status.get('drain_mode'):
                logger.warning("Browser pool is in drain mode")
                return False

            return True
        except ImportError:
            return True
        except Exception as e:
            logger.warning(f"Failed to check pool health: {e}")
            return True

    def _cleanup(self):
        """Cleanup resources during shutdown."""
        logger.info("Starting graceful cleanup...")

        try:
            from seo_intelligence.drivers.browser_pool import get_browser_pool
            pool = get_browser_pool()
            if pool.is_enabled():
                pool.enter_drain_mode(timeout=30)
                pool.shutdown()
        except Exception as e:
            logger.debug(f"Browser pool cleanup error: {e}")

        logger.info("Graceful cleanup complete")

    def _process_refresh_batch(self) -> int:
        """
        Process competitors due for refresh.

        Returns:
            Number of competitors processed
        """
        # Get competitors needing initial processing OR due for refresh
        candidates = self._get_candidates(limit=10)

        if not candidates:
            return 0

        processed = 0
        for competitor_id, is_initial in candidates:
            if not self.running:
                break

            run_type = 'initial' if is_initial else 'scheduled'

            try:
                self._process_competitor(competitor_id, run_type)
                processed += 1
                self.competitors_processed += 1
                self.heartbeat.record_competitor_complete()
            except Exception as e:
                logger.error(f"Failed to process competitor {competitor_id}: {e}")
                self.heartbeat.record_job_failed(str(e))

            if self.running and processed < len(candidates):
                self._sleep_with_interrupt(DELAY_BETWEEN_COMPETITORS)

        return processed

    def _get_candidates(self, limit: int = 10) -> List[tuple]:
        """
        Get competitors that need processing.

        Returns list of (competitor_id, is_initial) tuples.
        """
        try:
            with self.db_manager.get_session() as session:
                # First, get any needing initial processing
                initial_query = text("""
                    SELECT competitor_id, TRUE as is_initial
                    FROM competitors
                    WHERE is_active = true
                      AND intel_initial_complete = false
                    ORDER BY priority_tier ASC, competitor_id ASC
                    LIMIT :limit
                """)
                result = session.execute(initial_query, {'limit': limit})
                initial = [(r[0], r[1]) for r in result.fetchall()]

                if initial:
                    return initial

                # Then, get those due for refresh
                refresh_query = text("""
                    SELECT competitor_id, FALSE as is_initial
                    FROM competitors
                    WHERE is_active = true
                      AND intel_initial_complete = true
                      AND (intel_next_refresh_due IS NULL OR intel_next_refresh_due <= NOW())
                    ORDER BY priority_tier ASC, intel_next_refresh_due ASC NULLS FIRST
                    LIMIT :limit
                """)
                result = session.execute(refresh_query, {'limit': limit})
                return [(r[0], r[1]) for r in result.fetchall()]

        except Exception as e:
            logger.error(f"Failed to get candidates: {e}")
            return []

    def _process_competitor(self, competitor_id: int, run_type: str = 'scheduled'):
        """
        Process all modules for a single competitor.

        Args:
            competitor_id: The competitor to process
            run_type: 'initial', 'scheduled', or 'manual'
        """
        logger.info(f"Processing competitor {competitor_id} ({run_type})")

        # Get competitor info
        with self.db_manager.get_session() as session:
            result = session.execute(
                text("SELECT name, domain, website_url FROM competitors WHERE competitor_id = :id"),
                {'id': competitor_id}
            ).fetchone()

            if not result:
                logger.error(f"Competitor {competitor_id} not found")
                return

            name, domain, website_url = result

        logger.info(f"  Competitor: {name} ({domain})")

        # Determine which modules to run based on run_type
        if run_type == 'initial':
            modules_to_run = MODULE_ORDER
        else:
            # For refresh, check what's due
            modules_to_run = self._get_due_modules(competitor_id)

        # Run each module - track critical failures
        critical_modules = {'site_crawl'}  # Modules that must succeed
        critical_failure = False

        for module in modules_to_run:
            if not self.running:
                break

            self.heartbeat.set_current_work(competitor_id, module)

            try:
                success = self._run_module(competitor_id, module, domain, website_url, run_type)
                if success:
                    self.heartbeat.record_job_complete()
                else:
                    self.heartbeat.record_job_failed(f"Module {module} returned failure")
                    if module in critical_modules:
                        critical_failure = True
                        logger.warning(f"Critical module {module} failed for competitor {competitor_id}")
            except Exception as e:
                logger.error(f"Module {module} failed for competitor {competitor_id}: {e}")
                self.heartbeat.record_job_failed(str(e))
                self._log_job_failure(competitor_id, module, run_type, str(e))
                if module in critical_modules:
                    critical_failure = True

            # Delay between modules
            if self.running:
                delay = DELAY_GOOGLE_MODULE if module in GOOGLE_MODULES else DELAY_BETWEEN_MODULES
                self._sleep_with_interrupt(delay)

        # Only mark complete if no critical failures occurred
        if critical_failure:
            logger.warning(f"Competitor {competitor_id} NOT marked complete due to critical module failure")
        else:
            self._mark_competitor_complete(competitor_id, run_type)
        self.heartbeat.set_current_work(None, None)

    def _get_due_modules(self, competitor_id: int) -> List[str]:
        """Determine which modules are due to run for this competitor."""
        # For now, run all modules
        # TODO: Add per-module scheduling (daily vs weekly)
        return MODULE_ORDER

    def _run_module(self, competitor_id: int, module: str, domain: str,
                    website_url: str, run_type: str) -> bool:
        """
        Run a single module for a competitor.

        Returns:
            True if successful, False otherwise
        """
        start_time = datetime.now()
        logger.info(f"  [{module}] Starting...")

        # Log job start
        job_id = self._log_job_start(competitor_id, module, run_type)

        try:
            # Dispatch to appropriate module
            if module == 'site_crawl':
                result = self._run_site_crawl(competitor_id, domain, website_url)
            elif module == 'content_archive':
                result = self._run_content_archive(competitor_id, website_url)
            elif module == 'blog_track':
                result = self._run_blog_track(competitor_id, website_url)
            elif module == 'serp_track':
                result = self._run_serp_track(competitor_id, domain)
            elif module == 'keyword_gaps':
                result = self._run_keyword_gaps(competitor_id, domain)
            elif module == 'social_track':
                result = self._run_social_track(competitor_id, website_url)
            elif module == 'ad_detect':
                result = self._run_ad_detect(competitor_id, domain)
            elif module == 'citation_check':
                result = self._run_citation_check(competitor_id, domain)
            elif module == 'review_aggregate':
                result = self._run_review_aggregate(competitor_id, domain)
            elif module == 'review_deep_scrape':
                result = self._run_review_deep_scrape(competitor_id, domain)
            elif module == 'review_analysis':
                result = self._run_review_analysis(competitor_id)
            elif module == 'technical_audit':
                result = self._run_technical_audit(competitor_id, website_url)
            elif module == 'service_extract':
                result = self._run_service_extract(competitor_id, website_url)
            elif module == 'pricing_intel':
                result = self._run_pricing_intel(competitor_id, website_url)
            elif module == 'marketing_monitor':
                result = self._run_marketing_monitor(competitor_id)
            elif module == 'intel_synthesis':
                result = self._run_intel_synthesis(competitor_id)
            else:
                logger.warning(f"Unknown module: {module}")
                result = {'success': False, 'error': 'Unknown module'}

            duration = (datetime.now() - start_time).total_seconds()

            if result.get('success', False):
                self._log_job_complete(job_id, duration, result)
                self._update_module_flag(competitor_id, module, True)
                logger.info(f"  [{module}] Completed in {duration:.1f}s")
                return True
            else:
                error = result.get('error', 'Unknown error')
                self._log_job_failure(competitor_id, module, run_type, error, job_id)
                logger.warning(f"  [{module}] Failed: {error}")
                return False

        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            self._log_job_failure(competitor_id, module, run_type, str(e), job_id)
            logger.error(f"  [{module}] Exception after {duration:.1f}s: {e}")
            return False

    def _run_site_crawl(self, competitor_id: int, domain: str, website_url: str) -> dict:
        """Run site crawl module with pre-flight checks."""
        import requests

        # Pre-flight check: verify website is reachable before using browser resources
        try:
            response = requests.head(
                website_url,
                timeout=15,
                allow_redirects=True,
                headers={'User-Agent': 'Mozilla/5.0 (compatible; WashBot/1.0)'}
            )
            if response.status_code >= 400:
                # Check failure history and potentially deactivate
                self._check_and_deactivate_if_dead(competitor_id, domain)
                return {'success': False, 'error': f'Website returned HTTP {response.status_code}'}
        except requests.exceptions.Timeout:
            self._check_and_deactivate_if_dead(competitor_id, domain)
            return {'success': False, 'error': f'Website timeout - {domain} may be down'}
        except requests.exceptions.ConnectionError:
            self._check_and_deactivate_if_dead(competitor_id, domain)
            return {'success': False, 'error': f'Connection failed - {domain} may be down'}
        except Exception as e:
            logger.warning(f"Pre-flight check failed for {domain}: {e}")
            # Continue anyway - might work with browser

        try:
            from seo_intelligence.scrapers.competitor_crawler_selenium import CompetitorCrawlerSelenium

            crawler = CompetitorCrawlerSelenium()
            result = crawler.crawl_competitor(
                domain=domain,
                website_url=website_url,
            )

            if result is None:
                self._check_and_deactivate_if_dead(competitor_id, domain)
                return {'success': False, 'error': f'Crawl returned None - {domain} may be unreachable'}

            return {
                'success': True,
                'pages_crawled': result.get('pages_crawled', 0) if isinstance(result, dict) else 0,
                'links_found': result.get('links_found', 0) if isinstance(result, dict) else 0,
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _check_and_deactivate_if_dead(self, competitor_id: int, domain: str):
        """Check if competitor has too many failures and deactivate if so."""
        try:
            with self.db_manager.get_session() as session:
                # Count recent site_crawl failures
                result = session.execute(text("""
                    SELECT COUNT(*) FROM competitor_job_tracking
                    WHERE competitor_id = :cid
                    AND module_name = 'site_crawl'
                    AND status = 'failed'
                    AND started_at > NOW() - INTERVAL '7 days'
                """), {'cid': competitor_id})
                failure_count = result.scalar() or 0

                if failure_count >= 5:
                    # Deactivate competitor after 5 failures in a week
                    session.execute(text("""
                        UPDATE competitors SET is_active = false
                        WHERE competitor_id = :cid
                    """), {'cid': competitor_id})
                    session.commit()
                    logger.warning(f"Deactivated competitor {domain} after {failure_count} site_crawl failures")
        except Exception as e:
            logger.error(f"Error checking/deactivating competitor {domain}: {e}")

    def _run_serp_track(self, competitor_id: int, domain: str) -> dict:
        """Run SERP tracking module."""
        try:
            # Get keywords to track
            with self.db_manager.get_session() as session:
                result = session.execute(text("""
                    SELECT DISTINCT kct.keyword_text
                    FROM keyword_company_tracking kct
                    JOIN company_competitors cc ON kct.company_id = cc.company_id
                    WHERE cc.competitor_id = :cid
                    LIMIT 50
                """), {'cid': competitor_id})
                keywords = [r[0] for r in result.fetchall()]

            if not keywords:
                return {'success': True, 'message': 'No keywords to track', 'positions': 0}

            from seo_intelligence.scrapers.serp_scraper_selenium import SerpScraperSelenium
            scraper = SerpScraperSelenium()

            positions_found = 0
            for keyword in keywords[:20]:  # Limit per run
                try:
                    result = scraper.run(keyword)
                    for r in result.get('organic_results', []):
                        if domain in r.get('url', ''):
                            positions_found += 1
                            # TODO: Save position to database
                            break
                except Exception as e:
                    logger.debug(f"SERP error for {keyword}: {e}")

            return {'success': True, 'keywords_checked': len(keywords), 'positions_found': positions_found}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _run_citation_check(self, competitor_id: int, domain: str) -> dict:
        """Run citation checking module."""
        try:
            from seo_intelligence.scrapers.citation_crawler_selenium import CitationCrawlerSelenium, BusinessInfo

            # Get competitor's business name and location for citation search
            with self.db_manager.get_session() as session:
                result = session.execute(
                    text("SELECT name, location, website_url FROM competitors WHERE competitor_id = :id"),
                    {'id': competitor_id}
                ).fetchone()

                if not result:
                    return {'success': False, 'error': 'Competitor not found'}

                business_name = result[0]
                location = result[1] or ''
                website_url = result[2] or f'https://{domain}'

                # Parse location into city/state if possible
                city, state = '', ''
                if location:
                    parts = [p.strip() for p in location.split(',')]
                    if len(parts) >= 2:
                        city = parts[0]
                        state = parts[1] if len(parts[1]) <= 2 else ''
                    elif len(parts) == 1:
                        city = parts[0]

            # Create BusinessInfo object
            business = BusinessInfo(
                name=business_name,
                address='',
                city=city,
                state=state,
                zip_code='',
                phone='',
                website=website_url,
            )

            crawler = CitationCrawlerSelenium()
            result = crawler.check_all_directories(business=business)

            if result is None:
                return {'success': True, 'directories_checked': 0, 'citations_found': 0}

            # Result is Dict[str, CitationResult] - count directories checked and found
            directories_checked = len(result) if isinstance(result, dict) else 0
            citations_found = sum(1 for v in result.values() if v and getattr(v, 'found', False)) if isinstance(result, dict) else 0

            return {
                'success': True,
                'directories_checked': directories_checked,
                'citations_found': citations_found,
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _run_review_aggregate(self, competitor_id: int, domain: str) -> dict:
        """Run review aggregation module."""
        try:
            from competitor_intel.services.review_aggregator import aggregate_reviews_for_competitor

            result = aggregate_reviews_for_competitor(competitor_id, domain)

            return {
                'success': result.get('success', False),
                'sources_found': result.get('sources_found', 0),
                'total_reviews': result.get('total_reviews', 0),
                'records_created': result.get('records_saved', 0),
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _run_technical_audit(self, competitor_id: int, website_url: str) -> dict:
        """Run technical audit module."""
        try:
            from seo_intelligence.scrapers.technical_auditor_selenium import TechnicalAuditorSelenium

            auditor = TechnicalAuditorSelenium()
            result = auditor.audit_page(website_url)

            if result is None:
                return {'success': False, 'error': 'Audit returned None'}

            # Handle both dict and AuditResult object
            if isinstance(result, dict):
                overall_score = result.get('overall_score')
                issues_count = result.get('issues_count', 0)
            else:
                # Assume it's an AuditResult dataclass/object
                overall_score = getattr(result, 'overall_score', None)
                issues_count = getattr(result, 'issues_count', 0)
                # Convert issues list to count if needed
                if issues_count == 0 and hasattr(result, 'issues'):
                    issues_count = len(result.issues) if result.issues else 0

            return {
                'success': True,
                'overall_score': overall_score,
                'issues_count': issues_count,
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _run_service_extract(self, competitor_id: int, website_url: str) -> dict:
        """Run service extraction module."""
        try:
            from competitor_intel.services.service_extractor import extract_services_for_competitor

            result = extract_services_for_competitor(competitor_id, website_url)

            return {
                'success': result.get('success', False),
                'services_found': result.get('services_found', 0),
                'pricing_found': result.get('pricing_found', 0),
                'records_created': result.get('records_saved', 0),
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _run_content_archive(self, competitor_id: int, website_url: str) -> dict:
        """Run content archiving module."""
        try:
            from competitor_intel.services.content_analyzer import ContentAnalyzer

            # Get cached HTML from site_crawl
            with self.db_manager.get_session() as session:
                result = session.execute(text("""
                    SELECT html_content, url FROM competitor_crawl_pages
                    WHERE competitor_id = :cid AND page_type IN ('homepage', 'home')
                    ORDER BY crawled_at DESC LIMIT 1
                """), {'cid': competitor_id}).fetchone()

            if not result or not result[0]:
                return {'success': True, 'message': 'No cached HTML available', 'archived': 0}

            html_content, url = result

            analyzer = ContentAnalyzer()
            analysis = analyzer.analyze(url, html_content, competitor_id)

            if analysis:
                analyzer.save_archive(competitor_id, analysis, page_type='home')

            return {
                'success': True,
                'archived': 1,
                'word_count': analysis.word_count if analysis else 0,
                'change_detected': analysis.change_detected if analysis else False,
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _run_blog_track(self, competitor_id: int, website_url: str) -> dict:
        """Run blog tracking module."""
        try:
            from competitor_intel.services.blog_tracker import BlogTracker

            # Get cached HTML from site_crawl
            with self.db_manager.get_session() as session:
                result = session.execute(text("""
                    SELECT html_content FROM competitor_crawl_pages
                    WHERE competitor_id = :cid AND page_type IN ('homepage', 'home')
                    ORDER BY crawled_at DESC LIMIT 1
                """), {'cid': competitor_id}).fetchone()

            if not result or not result[0]:
                return {'success': True, 'message': 'No cached HTML', 'blog_found': False}

            tracker = BlogTracker()
            blog_url = tracker.discover_blog(result[0], website_url)

            if not blog_url:
                return {'success': True, 'blog_found': False, 'posts_found': 0}

            # TODO: Fetch blog page and extract posts
            # For now, just record blog discovery
            return {
                'success': True,
                'blog_found': True,
                'blog_url': blog_url,
                'posts_found': 0,
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _run_keyword_gaps(self, competitor_id: int, domain: str) -> dict:
        """Run keyword gap analysis module."""
        try:
            # Get competitor's ranking keywords vs our company
            with self.db_manager.get_session() as session:
                # Get linked company
                result = session.execute(text("""
                    SELECT company_id FROM company_competitors
                    WHERE competitor_id = :cid LIMIT 1
                """), {'cid': competitor_id}).fetchone()

                if not result:
                    return {'success': True, 'message': 'No linked company', 'gaps_found': 0}

                company_id = result[0]

                # Find keywords where competitor ranks but we don't
                # This is simplified - full implementation would query SERP data
                gaps_query = session.execute(text("""
                    SELECT COUNT(*) FROM competitor_serp_positions csp
                    WHERE csp.competitor_id = :cid
                      AND csp.position <= 10
                      AND NOT EXISTS (
                          SELECT 1 FROM keyword_company_tracking kct
                          WHERE kct.company_id = :company_id
                            AND kct.keyword_text = csp.keyword
                      )
                """), {'cid': competitor_id, 'company_id': company_id}).fetchone()

            gaps_found = gaps_query[0] if gaps_query else 0

            return {
                'success': True,
                'gaps_found': gaps_found,
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _run_social_track(self, competitor_id: int, website_url: str) -> dict:
        """Run social media tracking module."""
        try:
            from competitor_intel.services.social_tracker import SocialTracker

            # Get cached HTML
            with self.db_manager.get_session() as session:
                result = session.execute(text("""
                    SELECT html_content FROM competitor_crawl_pages
                    WHERE competitor_id = :cid AND page_type IN ('homepage', 'home')
                    ORDER BY crawled_at DESC LIMIT 1
                """), {'cid': competitor_id}).fetchone()

            if not result or not result[0]:
                return {'success': True, 'message': 'No cached HTML', 'profiles_found': 0}

            tracker = SocialTracker()
            profiles = tracker.discover_profiles(result[0], website_url)

            if profiles:
                discovery_result = tracker.save_profiles(competitor_id, profiles)
                return {
                    'success': True,
                    'profiles_found': len(profiles),
                    'new_profiles': discovery_result.profiles_new,
                    'updated_profiles': discovery_result.profiles_updated,
                }

            return {'success': True, 'profiles_found': 0}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _run_ad_detect(self, competitor_id: int, domain: str) -> dict:
        """Run ad detection module."""
        try:
            from competitor_intel.services.ad_detector import AdDetector

            # Get any cached SERP results for this competitor
            # Try competitor_serp_cache first, fall back to noting no cache
            try:
                with self.db_manager.get_session() as session:
                    result = session.execute(text("""
                        SELECT serp_html, keyword FROM competitor_serp_cache
                        WHERE competitor_id = :cid
                        ORDER BY captured_at DESC LIMIT 5
                    """), {'cid': competitor_id}).fetchall()
            except Exception:
                # Table doesn't exist yet - skip ad detection
                return {'success': True, 'message': 'No SERP cache table', 'ads_found': 0}

            if not result:
                return {'success': True, 'message': 'No SERP cache', 'ads_found': 0}

            detector = AdDetector()
            total_ads = []

            for serp_html, keyword in result:
                if serp_html:
                    ads = detector.detect_google_ads(serp_html, domain)
                    total_ads.extend(ads)

            if total_ads:
                detector.save_ads(competitor_id, total_ads)

            return {
                'success': True,
                'ads_found': len(total_ads),
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _run_review_deep_scrape(self, competitor_id: int, domain: str) -> dict:
        """Run deep review scraping module."""
        try:
            # Deep review scraping requires individual review extraction
            # This would use browser automation to get individual reviews
            # For now, return success with note about implementation
            return {
                'success': True,
                'message': 'Deep scrape deferred to review_aggregate',
                'reviews_scraped': 0,
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _run_review_analysis(self, competitor_id: int) -> dict:
        """Run review analysis module (sentiment + anomaly detection)."""
        try:
            from competitor_intel.services.sentiment_analyzer import SentimentAnalyzer
            from competitor_intel.services.review_anomaly_detector import ReviewAnomalyDetector
            from competitor_intel.services.response_tracker import ResponseTracker

            # Analyze sentiment
            with self.db_manager.get_session() as session:
                result = session.execute(text("""
                    SELECT id, review_text FROM competitor_reviews
                    WHERE competitor_id = :cid AND sentiment_score IS NULL
                    LIMIT 100
                """), {'cid': competitor_id}).fetchall()

            analyzer = SentimentAnalyzer()
            analyzed_count = 0

            for review_id, text in result:
                if text:
                    sentiment = analyzer.analyze(text)
                    with self.db_manager.get_session() as session:
                        session.execute(text("""
                            UPDATE competitor_reviews SET
                                sentiment_score = :score,
                                sentiment_label = :label,
                                complaint_categories = :complaints,
                                praise_categories = :praise
                            WHERE id = :id
                        """), {
                            'id': review_id,
                            'score': sentiment.score,
                            'label': sentiment.label,
                            'complaints': ','.join(sentiment.complaint_categories),
                            'praise': ','.join(sentiment.praise_categories),
                        })
                        session.commit()
                    analyzed_count += 1

            # Detect anomalies
            detector = ReviewAnomalyDetector()
            anomaly_report = detector.analyze_competitor(competitor_id)

            # Track responses
            response_tracker = ResponseTracker()
            response_metrics = response_tracker.analyze_responses(competitor_id)
            response_tracker.save_metrics(response_metrics)

            return {
                'success': True,
                'reviews_analyzed': analyzed_count,
                'anomalies_found': len(anomaly_report.anomalies),
                'suspicious_count': anomaly_report.suspicious_count,
                'response_rate': response_metrics.response_rate,
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _run_pricing_intel(self, competitor_id: int, website_url: str) -> dict:
        """Run pricing intelligence module."""
        try:
            from competitor_intel.services.price_tracker import PriceTracker

            # Get services with prices for this competitor
            with self.db_manager.get_session() as session:
                result = session.execute(text("""
                    SELECT id, price_min, price_max, price_unit, pricing_model
                    FROM competitor_services
                    WHERE competitor_id = :cid AND price_min IS NOT NULL
                """), {'cid': competitor_id}).fetchall()

            if not result:
                return {'success': True, 'message': 'No services with prices', 'snapshots': 0}

            tracker = PriceTracker()
            snapshots = 0
            changes = 0

            for service_id, price_min, price_max, unit, model in result:
                change = tracker.record_snapshot(
                    competitor_id=competitor_id,
                    service_id=service_id,
                    price_min=float(price_min) if price_min else 0,
                    price_max=float(price_max) if price_max else 0,
                    price_unit=unit,
                    pricing_model=model,
                    source_url=website_url,
                )
                snapshots += 1
                if change:
                    changes += 1

            return {
                'success': True,
                'snapshots': snapshots,
                'price_changes': changes,
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _run_marketing_monitor(self, competitor_id: int) -> dict:
        """Run marketing activity monitoring module."""
        try:
            from competitor_intel.services.marketing_monitor import MarketingMonitor

            monitor = MarketingMonitor()
            snapshot = monitor.create_snapshot(competitor_id)
            alerts = monitor.generate_alerts(competitor_id, snapshot)

            # Save snapshot
            monitor.save_snapshot(snapshot)

            # Save alerts
            if alerts:
                with self.db_manager.get_session() as session:
                    for alert in alerts:
                        session.execute(text("""
                            INSERT INTO competitor_alerts
                                (competitor_id, alert_type, severity, title, description)
                            VALUES
                                (:cid, :type, :severity, :title, :description)
                        """), {
                            'cid': competitor_id,
                            'type': alert.alert_type,
                            'severity': alert.severity,
                            'title': alert.title,
                            'description': alert.description,
                        })
                    session.commit()

            return {
                'success': True,
                'activity_level': snapshot.activity_level.value,
                'activity_score': snapshot.activity_score,
                'alerts_generated': len(alerts),
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _run_intel_synthesis(self, competitor_id: int) -> dict:
        """Run intelligence synthesis module."""
        try:
            # Get competitor domain
            with self.db_manager.get_session() as session:
                result = session.execute(
                    text("SELECT domain FROM competitors WHERE competitor_id = :id"),
                    {'id': competitor_id}
                ).fetchone()
                domain = result[0] if result else None

            if not domain:
                return {'success': False, 'error': 'Competitor domain not found'}

            # Get linked company for context
            with self.db_manager.get_session() as session:
                result = session.execute(text("""
                    SELECT company_id FROM company_competitors
                    WHERE competitor_id = :cid
                    LIMIT 1
                """), {'cid': competitor_id}).fetchone()
                company_id = result[0] if result else None

            synthesis_results = {}

            # 1. Calculate threat score
            try:
                from competitor_intel.services.threat_scorer import calculate_threat_for_competitor
                if company_id:
                    threat_result = calculate_threat_for_competitor(company_id, competitor_id, domain)
                    synthesis_results['threat'] = threat_result
            except Exception as e:
                logger.debug(f"Threat scoring failed: {e}")

            # 2. Check for alerts
            try:
                from competitor_intel.services.alert_manager import check_competitor_alerts
                alert_result = check_competitor_alerts(competitor_id, domain, company_id)
                synthesis_results['alerts'] = alert_result
            except Exception as e:
                logger.debug(f"Alert checking failed: {e}")

            # 3. SOV calculation (if we have a market segment)
            try:
                from competitor_intel.services.sov_calculator import calculate_market_sov
                if company_id:
                    # Use a default market segment based on competitor location
                    with self.db_manager.get_session() as session:
                        result = session.execute(text("""
                            SELECT city, state, primary_service_category
                            FROM companies WHERE id = :id
                        """), {'id': company_id}).fetchone()

                        if result and result[0] and result[2]:
                            segment = f"{result[2]}_{result[0]}_{result[1]}".lower().replace(' ', '_')
                            sov_result = calculate_market_sov(company_id, segment)
                            synthesis_results['sov'] = sov_result
            except Exception as e:
                logger.debug(f"SOV calculation failed: {e}")

            return {
                'success': True,
                'threat_level': synthesis_results.get('threat', {}).get('threat_level'),
                'alerts_generated': synthesis_results.get('alerts', {}).get('alerts_generated', 0),
                'sov_calculated': 'sov' in synthesis_results,
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _log_job_start(self, competitor_id: int, module: str, run_type: str) -> int:
        """Log job start in tracking table."""
        try:
            with self.db_manager.get_session() as session:
                result = session.execute(text("""
                    INSERT INTO competitor_job_tracking
                        (competitor_id, module_name, run_type, status, started_at)
                    VALUES (:competitor_id, :module, :run_type, 'running', NOW())
                    RETURNING id
                """), {
                    'competitor_id': competitor_id,
                    'module': module,
                    'run_type': run_type,
                })
                session.commit()
                return result.fetchone()[0]
        except Exception as e:
            logger.error(f"Failed to log job start: {e}")
            return 0

    def _log_job_complete(self, job_id: int, duration: float, result: dict):
        """Log job completion."""
        try:
            with self.db_manager.get_session() as session:
                session.execute(text("""
                    UPDATE competitor_job_tracking SET
                        status = 'completed',
                        completed_at = NOW(),
                        duration_seconds = :duration,
                        records_created = :created,
                        records_updated = :updated,
                        metadata = :metadata
                    WHERE id = :job_id
                """), {
                    'job_id': job_id,
                    'duration': int(duration),
                    'created': result.get('records_created', 0),
                    'updated': result.get('records_updated', 0),
                    'metadata': '{}',
                })
                session.commit()
        except Exception as e:
            logger.error(f"Failed to log job complete: {e}")

    def _log_job_failure(self, competitor_id: int, module: str, run_type: str,
                         error: str, job_id: int = None):
        """Log job failure."""
        try:
            with self.db_manager.get_session() as session:
                if job_id:
                    session.execute(text("""
                        UPDATE competitor_job_tracking SET
                            status = 'failed',
                            completed_at = NOW(),
                            error_message = :error,
                            retry_count = retry_count + 1
                        WHERE id = :job_id
                    """), {'job_id': job_id, 'error': error[:500]})
                else:
                    session.execute(text("""
                        INSERT INTO competitor_job_tracking
                            (competitor_id, module_name, run_type, status, error_message, completed_at)
                        VALUES (:competitor_id, :module, :run_type, 'failed', :error, NOW())
                    """), {
                        'competitor_id': competitor_id,
                        'module': module,
                        'run_type': run_type,
                        'error': error[:500],
                    })
                session.commit()
        except Exception as e:
            logger.error(f"Failed to log job failure: {e}")

    def _update_module_flag(self, competitor_id: int, module: str, done: bool):
        """Update module completion flag on competitor."""
        flag_map = {
            'site_crawl': 'intel_site_crawl_done',
            'content_archive': 'intel_content_done',
            'blog_track': 'intel_blog_done',
            'serp_track': 'intel_serp_done',
            'keyword_gaps': 'intel_keywords_done',
            'social_track': 'intel_social_done',
            'ad_detect': 'intel_ads_done',
            'citation_check': 'intel_citations_done',
            'review_aggregate': 'intel_reviews_done',
            'review_deep_scrape': 'intel_reviews_deep_done',
            'review_analysis': 'intel_review_analysis_done',
            'technical_audit': 'intel_technical_done',
            'service_extract': 'intel_services_done',
            'pricing_intel': 'intel_pricing_done',
            'marketing_monitor': 'intel_marketing_done',
            'intel_synthesis': 'intel_synthesis_done',
        }

        flag = flag_map.get(module)
        if not flag:
            return

        try:
            with self.db_manager.get_session() as session:
                session.execute(
                    text(f"UPDATE competitors SET {flag} = :done WHERE competitor_id = :id"),
                    {'id': competitor_id, 'done': done}
                )
                session.commit()
        except Exception as e:
            logger.error(f"Failed to update module flag: {e}")

    def _mark_competitor_complete(self, competitor_id: int, run_type: str):
        """Mark competitor as complete and schedule next refresh."""
        try:
            with self.db_manager.get_session() as session:
                # Get priority tier for refresh interval
                result = session.execute(
                    text("SELECT priority_tier FROM competitors WHERE competitor_id = :id"),
                    {'id': competitor_id}
                ).fetchone()

                tier = result[0] if result else DEFAULT_PRIORITY_TIER
                refresh_interval = REFRESH_INTERVALS.get(tier, REFRESH_INTERVALS[2])
                next_refresh = datetime.now() + refresh_interval

                session.execute(text("""
                    UPDATE competitors SET
                        intel_initial_complete = true,
                        intel_last_full_crawl = NOW(),
                        intel_next_refresh_due = :next_refresh
                    WHERE competitor_id = :id
                """), {
                    'id': competitor_id,
                    'next_refresh': next_refresh,
                })
                session.commit()

                logger.info(f"Competitor {competitor_id} complete, next refresh: {next_refresh}")
        except Exception as e:
            logger.error(f"Failed to mark competitor complete: {e}")


def main():
    parser = argparse.ArgumentParser(description="Competitor Intelligence Orchestrator")
    parser.add_argument('--worker-name', default='competitor_worker_1')
    parser.add_argument('--test-mode', action='store_true')
    parser.add_argument('--single-competitor', type=int)
    args = parser.parse_args()

    orchestrator = CompetitorJobOrchestrator(worker_name=args.worker_name)

    if args.single_competitor:
        orchestrator.run_single_competitor(args.single_competitor)
    else:
        orchestrator.run(test_mode=args.test_mode)


if __name__ == '__main__':
    main()
