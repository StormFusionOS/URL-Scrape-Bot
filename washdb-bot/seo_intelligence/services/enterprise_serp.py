"""
Enterprise SERP API

This is the main interface to the enterprise SERP scraping system.
It provides a simple API that works like Serper.dev but runs on your own infrastructure.

Usage:
    from seo_intelligence.services.enterprise_serp import EnterpriseSERP

    # Initialize (do once at startup)
    serp = EnterpriseSERP()
    serp.start()

    # Synchronous search (waits for result)
    results = serp.search("pressure washing near me", location="Boston, MA")

    # Async search (returns job ID, result comes later)
    job_id = serp.search_async("roof cleaning services", priority="normal")
    # ... later ...
    results = serp.get_result(job_id)

    # Batch search (queue multiple, process over time)
    job_ids = serp.search_batch([
        {"query": "pressure washing", "location": "Boston, MA"},
        {"query": "window cleaning", "location": "Boston, MA"},
    ])
"""

import os
import time
import threading
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
from dataclasses import dataclass

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from runner.logging_setup import get_logger
from seo_intelligence.services.serp_session_pool import (
    SerpSessionPool,
    SerpResultCache,
    get_serp_session_pool,
    shutdown_serp_session_pool,
)
from seo_intelligence.services.serp_query_scheduler import (
    SerpQueryScheduler,
    SchedulerConfig,
    get_serp_scheduler,
    start_serp_scheduler,
    stop_serp_scheduler,
)

load_dotenv()

logger = get_logger("enterprise_serp")


@dataclass
class EnterpriseSerpConfig:
    """Configuration for Enterprise SERP system."""

    # Session pool settings (1 session to avoid Playwright asyncio conflicts)
    num_sessions: int = 1
    proxy_list: List[str] = None

    # Rate limiting
    max_queries_per_hour: int = 20
    min_delay_between_queries_sec: int = 180  # 3 minutes
    max_delay_between_queries_sec: int = 600  # 10 minutes

    # Cache settings
    cache_ttl_hours: int = 24

    # Timeouts
    sync_search_timeout_sec: int = 1800  # 30 minutes for sync search


class EnterpriseSERP:
    """
    Enterprise-grade SERP scraping system.

    Designed to run 24/7 and provide reliable SERP data without paid APIs.
    """

    def __init__(self, config: EnterpriseSerpConfig = None):
        self.config = config or EnterpriseSerpConfig()
        self._scheduler: Optional[SerpQueryScheduler] = None
        self._pool: Optional[SerpSessionPool] = None
        self._cache: Optional[SerpResultCache] = None
        self._started = False
        self._lock = threading.Lock()

    def start(self, proxy_list: List[str] = None):
        """
        Start the enterprise SERP system.

        Args:
            proxy_list: List of proxy URLs to use (optional)
        """
        with self._lock:
            if self._started:
                logger.warning("Enterprise SERP already started")
                return

            logger.info("Starting Enterprise SERP system...")

            # Get proxies from config or environment
            proxies = proxy_list or self.config.proxy_list
            if not proxies:
                # Try to get from Webshare integration
                proxies = self._get_residential_proxies()

            # Initialize cache
            self._cache = SerpResultCache(ttl_hours=self.config.cache_ttl_hours)

            # Configure and start scheduler
            scheduler_config = SchedulerConfig(
                max_queries_per_hour=self.config.max_queries_per_hour,
                min_delay_between_queries_sec=self.config.min_delay_between_queries_sec,
                max_delay_between_queries_sec=self.config.max_delay_between_queries_sec,
            )
            self._scheduler = get_serp_scheduler(scheduler_config)
            self._scheduler.start(proxy_list=proxies)

            self._pool = get_serp_session_pool()
            self._started = True

            logger.info("Enterprise SERP system started")

    def stop(self):
        """Stop the enterprise SERP system gracefully."""
        with self._lock:
            if not self._started:
                return

            logger.info("Stopping Enterprise SERP system...")

            stop_serp_scheduler()
            shutdown_serp_session_pool()

            self._scheduler = None
            self._pool = None
            self._started = False

            logger.info("Enterprise SERP system stopped")

    def _get_residential_proxies(self) -> List[str]:
        """Get residential proxies from Webshare integration."""
        try:
            from seo_intelligence.services.residential_proxy_manager import (
                get_residential_proxy_manager
            )
            manager = get_residential_proxy_manager()
            proxies = []

            # Get several proxies for the pool
            for _ in range(self.config.num_sessions):
                proxy = manager.get_proxy()
                if proxy:
                    # Format: http://user:pass@host:port
                    proxy_url = f"http://{proxy.username}:{proxy.password}@{proxy.host}:{proxy.port}"
                    proxies.append(proxy_url)

            if proxies:
                logger.info(f"Got {len(proxies)} residential proxies from Webshare")
                return proxies

        except Exception as e:
            logger.warning(f"Could not get residential proxies: {e}")

        return []

    def search(
        self,
        query: str,
        location: str = None,
        timeout: int = None,
        use_cache: bool = True,
    ) -> Optional[dict]:
        """
        Perform a synchronous SERP search.

        This blocks until results are available or timeout is reached.
        Use search_async() for non-blocking searches.

        Args:
            query: Search query
            location: Geographic location for local results
            timeout: Maximum seconds to wait (default from config)
            use_cache: Whether to use/check cache

        Returns:
            SERP results dict or None if failed
        """
        if not self._started:
            raise RuntimeError("Enterprise SERP not started. Call start() first.")

        timeout = timeout or self.config.sync_search_timeout_sec

        # Check cache first
        if use_cache and self._cache:
            cached = self._cache.get(query, location)
            if cached:
                logger.info(f"Cache hit for '{query[:30]}...'")
                return cached

        # Queue and wait for result
        job_id = self._scheduler.queue_query(
            query=query,
            location=location,
            priority="high",  # Sync searches get high priority
        )

        logger.info(f"Waiting for SERP result for '{query[:30]}...' (job: {job_id})")

        result = self._scheduler.wait_for_result(job_id, timeout=timeout)

        if result:
            logger.info(f"Got result for '{query[:30]}...' - {len(result.get('organic_results', []))} results")
        else:
            logger.warning(f"No result for '{query[:30]}...' within {timeout}s timeout")

        return result

    def search_async(
        self,
        query: str,
        location: str = None,
        priority: str = "normal",
        callback: Callable = None,
        company_id: int = None,
    ) -> str:
        """
        Queue a SERP search for async processing.

        The search will be executed when a session is available.
        Use get_result() or the callback to get results.

        Args:
            query: Search query
            location: Geographic location
            priority: Priority level (urgent, high, normal, low, background)
            callback: Function to call when result is ready: callback(job_id, result)
            company_id: Associated company ID for tracking

        Returns:
            Job ID for tracking
        """
        if not self._started:
            raise RuntimeError("Enterprise SERP not started. Call start() first.")

        job_id = self._scheduler.queue_query(
            query=query,
            location=location,
            priority=priority,
            callback=callback,
            company_id=company_id,
        )

        logger.debug(f"Queued async search for '{query[:30]}...' (job: {job_id})")
        return job_id

    def search_batch(
        self,
        queries: List[dict],
        priority: str = "normal",
        callback: Callable = None,
    ) -> List[str]:
        """
        Queue multiple SERP searches.

        Args:
            queries: List of query dicts with 'query' and optional 'location', 'company_id'
            priority: Priority level for all queries
            callback: Function to call for each result

        Returns:
            List of job IDs
        """
        if not self._started:
            raise RuntimeError("Enterprise SERP not started. Call start() first.")

        job_ids = []
        for q in queries:
            job_id = self._scheduler.queue_query(
                query=q["query"],
                location=q.get("location"),
                priority=priority,
                callback=callback,
                company_id=q.get("company_id"),
            )
            job_ids.append(job_id)

        logger.info(f"Queued batch of {len(job_ids)} searches (priority: {priority})")
        return job_ids

    def get_result(self, job_id: str, wait: bool = False, timeout: int = 60) -> Optional[dict]:
        """
        Get the result of an async search.

        Args:
            job_id: Job ID from search_async()
            wait: If True, block until result is ready
            timeout: Max seconds to wait if wait=True

        Returns:
            SERP results or None if not ready/failed
        """
        if wait:
            return self._scheduler.wait_for_result(job_id, timeout=timeout)
        return self._scheduler.get_job_result(job_id)

    def get_job_status(self, job_id: str) -> Optional[dict]:
        """Get status of a queued/processing job."""
        return self._scheduler.get_job_status(job_id)

    def get_stats(self) -> dict:
        """Get system statistics."""
        stats = {
            "started": self._started,
            "timestamp": datetime.now().isoformat(),
        }

        if self._scheduler:
            stats["queue"] = self._scheduler.get_queue_stats()

        if self._pool:
            stats["sessions"] = self._pool.get_pool_stats()

        return stats

    def clear_cache(self):
        """Clear the result cache."""
        if self._cache:
            self._cache.cleanup_expired()
            logger.info("Cache cleared")


# Singleton instance
_enterprise_serp: Optional[EnterpriseSERP] = None
_enterprise_lock = threading.Lock()


def get_enterprise_serp(config: EnterpriseSerpConfig = None) -> EnterpriseSERP:
    """Get or create the global Enterprise SERP instance."""
    global _enterprise_serp

    with _enterprise_lock:
        if _enterprise_serp is None:
            _enterprise_serp = EnterpriseSERP(config)
        return _enterprise_serp


def start_enterprise_serp(proxy_list: List[str] = None) -> EnterpriseSERP:
    """Start the global Enterprise SERP instance."""
    serp = get_enterprise_serp()
    serp.start(proxy_list)
    return serp


def stop_enterprise_serp():
    """Stop the global Enterprise SERP instance."""
    global _enterprise_serp

    with _enterprise_lock:
        if _enterprise_serp:
            _enterprise_serp.stop()
            _enterprise_serp = None


# Convenience function for drop-in replacement
def serp_search(
    query: str,
    location: str = None,
    timeout: int = 1800,
    use_cache: bool = True,
) -> Optional[dict]:
    """
    Simple SERP search function.

    This is a drop-in replacement for API-based SERP services.

    Usage:
        from seo_intelligence.services.enterprise_serp import serp_search

        results = serp_search("pressure washing near me", location="Boston, MA")
    """
    serp = get_enterprise_serp()

    if not serp._started:
        serp.start()

    return serp.search(query, location, timeout, use_cache)
