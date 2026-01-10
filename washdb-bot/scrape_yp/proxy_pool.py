"""
Proxy Pool Management for Yellow Pages Scraper.

This module provides:
- Loading proxies from Webshare format (host:port:username:password)
- Health tracking and automatic rotation
- Thread-safe proxy acquisition
- Blacklisting of bad proxies
"""

import os
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from pathlib import Path

from runner.logging_setup import get_logger


logger = get_logger("proxy_pool")


@dataclass
class ProxyInfo:
    """Information about a single proxy."""
    host: str
    port: int
    username: str
    password: str

    # Health tracking
    success_count: int = 0
    failure_count: int = 0
    last_used: Optional[datetime] = None
    blacklisted: bool = False
    blacklist_until: Optional[datetime] = None

    @property
    def success_rate(self) -> float:
        """Calculate success rate (0.0 to 1.0)."""
        total = self.success_count + self.failure_count
        if total == 0:
            return 1.0  # Optimistic for new proxies
        return self.success_count / total

    @property
    def is_healthy(self) -> bool:
        """Check if proxy is healthy and not blacklisted."""
        # Check if blacklist expired
        if self.blacklisted and self.blacklist_until:
            if datetime.now() > self.blacklist_until:
                self.blacklisted = False
                self.blacklist_until = None
                logger.info(f"Proxy {self.host}:{self.port} blacklist expired, re-enabled")

        if self.blacklisted:
            return False

        # Require at least 50% success rate after 10 attempts
        total = self.success_count + self.failure_count
        if total >= 10 and self.success_rate < 0.5:
            return False

        return True

    def to_playwright_format(self) -> Dict[str, str]:
        """Convert to Playwright proxy format."""
        return {
            "server": f"http://{self.host}:{self.port}",
            "username": self.username,
            "password": self.password
        }

    def __str__(self) -> str:
        """String representation."""
        status = "BLACKLISTED" if self.blacklisted else "HEALTHY" if self.is_healthy else "UNHEALTHY"
        return f"{self.host}:{self.port} [{status}] (success: {self.success_count}, fail: {self.failure_count}, rate: {self.success_rate:.1%})"


class ProxyPool:
    """
    Thread-safe proxy pool with health tracking and automatic rotation.

    Features:
    - Load proxies from Webshare format file
    - Round-robin or health-based selection
    - Automatic blacklisting of bad proxies
    - Success/failure tracking
    - Thread-safe acquisition
    """

    def __init__(self, proxy_file: str, blacklist_threshold: int = 10, blacklist_duration_minutes: int = 60):
        """
        Initialize proxy pool.

        Args:
            proxy_file: Path to proxy file (Webshare format: host:port:user:pass)
            blacklist_threshold: Number of consecutive failures before blacklisting
            blacklist_duration_minutes: How long to blacklist a proxy
        """
        self.proxy_file = proxy_file
        self.blacklist_threshold = blacklist_threshold
        self.blacklist_duration = timedelta(minutes=blacklist_duration_minutes)

        self.proxies: List[ProxyInfo] = []
        self.current_index = 0
        self.lock = threading.Lock()

        self._load_proxies()

    def _load_proxies(self) -> None:
        """Load proxies from file."""
        proxy_path = Path(self.proxy_file)

        if not proxy_path.exists():
            raise FileNotFoundError(f"Proxy file not found: {self.proxy_file}")

        logger.info(f"Loading proxies from {self.proxy_file}...")

        with open(proxy_path, 'r') as f:
            lines = f.readlines()

        for line_num, line in enumerate(lines, 1):
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue

            # Parse Webshare format: host:port:username:password
            parts = line.split(':')
            if len(parts) != 4:
                logger.warning(f"Line {line_num}: Invalid format, expected host:port:user:pass")
                continue

            host, port, username, password = parts

            try:
                port_int = int(port)
                proxy = ProxyInfo(
                    host=host,
                    port=port_int,
                    username=username,
                    password=password
                )
                self.proxies.append(proxy)
            except ValueError:
                logger.warning(f"Line {line_num}: Invalid port number: {port}")
                continue

        if not self.proxies:
            raise ValueError(f"No valid proxies found in {self.proxy_file}")

        logger.info(f"Loaded {len(self.proxies)} proxies")

    def get_proxy(self, strategy: str = "round_robin") -> Optional[ProxyInfo]:
        """
        Get next healthy proxy.

        Args:
            strategy: Selection strategy ('round_robin' or 'health_based')

        Returns:
            ProxyInfo object or None if no healthy proxies available
        """
        with self.lock:
            if strategy == "round_robin":
                return self._get_proxy_round_robin()
            elif strategy == "health_based":
                return self._get_proxy_health_based()
            else:
                raise ValueError(f"Unknown strategy: {strategy}")

    def _get_proxy_round_robin(self) -> Optional[ProxyInfo]:
        """Get next proxy in round-robin fashion (skips unhealthy)."""
        attempts = 0
        max_attempts = len(self.proxies)

        while attempts < max_attempts:
            proxy = self.proxies[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.proxies)
            attempts += 1

            if proxy.is_healthy:
                proxy.last_used = datetime.now()
                return proxy

        # No healthy proxies found
        logger.error("No healthy proxies available!")
        return None

    def _get_proxy_health_based(self) -> Optional[ProxyInfo]:
        """Get proxy with best success rate."""
        healthy_proxies = [p for p in self.proxies if p.is_healthy]

        if not healthy_proxies:
            logger.error("No healthy proxies available!")
            return None

        # Sort by success rate (descending), then by least recently used
        healthy_proxies.sort(key=lambda p: (p.success_rate, -(p.last_used.timestamp() if p.last_used else 0)), reverse=True)

        proxy = healthy_proxies[0]
        proxy.last_used = datetime.now()
        return proxy

    def report_success(self, proxy: ProxyInfo) -> None:
        """Report successful use of proxy."""
        with self.lock:
            proxy.success_count += 1

            # Log milestone successes
            if proxy.success_count in [1, 10, 50, 100, 500, 1000]:
                logger.info(f"Proxy {proxy.host}:{proxy.port} reached {proxy.success_count} successes (rate: {proxy.success_rate:.1%})")

    def report_failure(self, proxy: ProxyInfo, error_type: str = "unknown") -> None:
        """
        Report failed use of proxy.

        Args:
            proxy: ProxyInfo object
            error_type: Type of error (timeout, 403, 429, captcha, etc.)
        """
        with self.lock:
            proxy.failure_count += 1

            logger.warning(f"Proxy {proxy.host}:{proxy.port} failure ({error_type}): {proxy.failure_count} total failures (rate: {proxy.success_rate:.1%})")

            # Check if should blacklist
            recent_failures = proxy.failure_count - proxy.success_count
            if recent_failures >= self.blacklist_threshold:
                proxy.blacklisted = True
                proxy.blacklist_until = datetime.now() + self.blacklist_duration
                logger.error(
                    f"Proxy {proxy.host}:{proxy.port} BLACKLISTED for {self.blacklist_duration.total_seconds()/60:.0f} minutes "
                    f"(threshold: {self.blacklist_threshold} consecutive failures)"
                )

    def get_stats(self) -> Dict:
        """Get pool statistics."""
        with self.lock:
            total = len(self.proxies)
            healthy = sum(1 for p in self.proxies if p.is_healthy)
            blacklisted = sum(1 for p in self.proxies if p.blacklisted)

            total_success = sum(p.success_count for p in self.proxies)
            total_failure = sum(p.failure_count for p in self.proxies)
            overall_rate = total_success / (total_success + total_failure) if (total_success + total_failure) > 0 else 0.0

            return {
                "total_proxies": total,
                "healthy_proxies": healthy,
                "blacklisted_proxies": blacklisted,
                "total_successes": total_success,
                "total_failures": total_failure,
                "overall_success_rate": overall_rate
            }

    def get_proxy_list(self, include_unhealthy: bool = False) -> List[ProxyInfo]:
        """
        Get list of proxies.

        Args:
            include_unhealthy: If True, include unhealthy/blacklisted proxies

        Returns:
            List of ProxyInfo objects
        """
        with self.lock:
            if include_unhealthy:
                return self.proxies.copy()
            else:
                return [p for p in self.proxies if p.is_healthy]

    def reset_proxy(self, proxy: ProxyInfo) -> None:
        """Reset proxy stats (for manual intervention)."""
        with self.lock:
            proxy.success_count = 0
            proxy.failure_count = 0
            proxy.blacklisted = False
            proxy.blacklist_until = None
            logger.info(f"Reset proxy {proxy.host}:{proxy.port}")

    def test_proxy(self, proxy: ProxyInfo, test_url: str = "https://www.yellowpages.com") -> bool:
        """
        Test if a proxy is working.

        Args:
            proxy: ProxyInfo to test
            test_url: URL to test against

        Returns:
            True if proxy works, False otherwise
        """
        from playwright.sync_api import sync_playwright

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(proxy=proxy.to_playwright_format())
                page = context.new_page()

                # Try to load test URL
                response = page.goto(test_url, timeout=30000, wait_until='domcontentloaded')

                success = response and response.status == 200

                page.close()
                context.close()
                browser.close()

                return success
        except Exception as e:
            logger.warning(f"Proxy test failed for {proxy.host}:{proxy.port}: {e}")
            return False

    def test_all_proxies(self, max_concurrent: int = 5) -> Dict[str, int]:
        """
        Test all proxies (use before starting workers).

        Args:
            max_concurrent: Maximum concurrent tests

        Returns:
            Dict with passed/failed counts
        """
        logger.info(f"Testing {len(self.proxies)} proxies...")

        passed = 0
        failed = 0

        for idx, proxy in enumerate(self.proxies, 1):
            logger.info(f"Testing proxy {idx}/{len(self.proxies)}: {proxy.host}:{proxy.port}")

            if self.test_proxy(proxy):
                passed += 1
                logger.info(f"  ✓ PASSED")
            else:
                failed += 1
                logger.warning(f"  ✗ FAILED")
                # Mark as unhealthy but don't blacklist yet
                proxy.failure_count = 5

        logger.info(f"Proxy test complete: {passed} passed, {failed} failed")

        return {"passed": passed, "failed": failed}


class WorkerProxyPool:
    """
    Worker-specific proxy pool for state-partitioned workers.

    Each worker gets a dedicated subset of proxies and rotates through them
    on every request (not just on browser restart).

    Features:
    - Load only assigned proxies by index
    - Per-request rotation (faster failover)
    - Same health tracking and blacklisting as ProxyPool
    - Thread-safe for worker's internal use
    """

    def __init__(
        self,
        proxy_file: str,
        proxy_indices: List[int],
        worker_id: int,
        blacklist_threshold: int = 10,
        blacklist_duration_minutes: int = 60
    ):
        """
        Initialize worker-specific proxy pool.

        Args:
            proxy_file: Path to proxy file (Webshare format: host:port:user:pass)
            proxy_indices: List of proxy indices this worker should use (e.g., [0, 1, 2, 3, 4])
            worker_id: Worker ID for logging
            blacklist_threshold: Number of consecutive failures before blacklisting
            blacklist_duration_minutes: How long to blacklist a proxy
        """
        self.proxy_file = proxy_file
        self.proxy_indices = proxy_indices
        self.worker_id = worker_id
        self.blacklist_threshold = blacklist_threshold
        self.blacklist_duration = timedelta(minutes=blacklist_duration_minutes)

        self.proxies: List[ProxyInfo] = []
        self.current_index = 0
        self.lock = threading.Lock()

        self._load_proxies()

    def _load_proxies(self) -> None:
        """Load only assigned proxies from file."""
        proxy_path = Path(self.proxy_file)

        if not proxy_path.exists():
            raise FileNotFoundError(f"Proxy file not found: {self.proxy_file}")

        logger.info(f"Worker {self.worker_id}: Loading proxies from {self.proxy_file}...")

        with open(proxy_path, 'r') as f:
            lines = [line.strip() for line in f.readlines() if line.strip() and not line.startswith('#')]

        # Load only assigned proxies
        for idx in self.proxy_indices:
            if idx >= len(lines):
                logger.warning(f"Worker {self.worker_id}: Proxy index {idx} out of range (only {len(lines)} proxies in file)")
                continue

            line = lines[idx]

            # Parse Webshare format: host:port:username:password
            parts = line.split(':')
            if len(parts) != 4:
                logger.warning(f"Worker {self.worker_id}: Invalid format at index {idx}, expected host:port:user:pass")
                continue

            host, port, username, password = parts

            try:
                port_int = int(port)
                proxy = ProxyInfo(
                    host=host,
                    port=port_int,
                    username=username,
                    password=password
                )
                self.proxies.append(proxy)
                logger.info(f"Worker {self.worker_id}: Loaded proxy {len(self.proxies)}: {host}:{port}")
            except ValueError:
                logger.warning(f"Worker {self.worker_id}: Invalid port number at index {idx}: {port}")
                continue

        if not self.proxies:
            raise ValueError(f"Worker {self.worker_id}: No valid proxies found for indices {self.proxy_indices}")

        logger.info(f"Worker {self.worker_id}: Loaded {len(self.proxies)} proxies (indices: {self.proxy_indices})")

    def get_proxy_for_request(self) -> Optional[ProxyInfo]:
        """
        Get next healthy proxy for a single request.

        This rotates through proxies on EVERY call, not just browser restart.
        This provides faster failover and better load distribution.

        Returns:
            ProxyInfo object or None if no healthy proxies available
        """
        with self.lock:
            attempts = 0
            max_attempts = len(self.proxies)

            while attempts < max_attempts:
                proxy = self.proxies[self.current_index]
                self.current_index = (self.current_index + 1) % len(self.proxies)
                attempts += 1

                if proxy.is_healthy:
                    proxy.last_used = datetime.now()
                    return proxy

            # No healthy proxies found
            logger.error(f"Worker {self.worker_id}: No healthy proxies available!")
            return None

    def report_success(self, proxy: ProxyInfo) -> None:
        """Report successful use of proxy."""
        with self.lock:
            proxy.success_count += 1

            # Log milestone successes
            if proxy.success_count in [1, 10, 50, 100, 500, 1000]:
                logger.info(
                    f"Worker {self.worker_id}: Proxy {proxy.host}:{proxy.port} "
                    f"reached {proxy.success_count} successes (rate: {proxy.success_rate:.1%})"
                )

    def report_failure(self, proxy: ProxyInfo, error_type: str = "unknown") -> None:
        """
        Report failed use of proxy.

        Args:
            proxy: ProxyInfo object
            error_type: Type of error (timeout, 403, 429, captcha, etc.)
        """
        with self.lock:
            proxy.failure_count += 1

            logger.warning(
                f"Worker {self.worker_id}: Proxy {proxy.host}:{proxy.port} failure ({error_type}): "
                f"{proxy.failure_count} total failures (rate: {proxy.success_rate:.1%})"
            )

            # Check if should blacklist
            recent_failures = proxy.failure_count - proxy.success_count
            if recent_failures >= self.blacklist_threshold:
                proxy.blacklisted = True
                proxy.blacklist_until = datetime.now() + self.blacklist_duration
                logger.error(
                    f"Worker {self.worker_id}: Proxy {proxy.host}:{proxy.port} BLACKLISTED "
                    f"for {self.blacklist_duration.total_seconds()/60:.0f} minutes "
                    f"(threshold: {self.blacklist_threshold} consecutive failures)"
                )

    def get_stats(self) -> Dict:
        """Get pool statistics."""
        with self.lock:
            total = len(self.proxies)
            healthy = sum(1 for p in self.proxies if p.is_healthy)
            blacklisted = sum(1 for p in self.proxies if p.blacklisted)

            total_success = sum(p.success_count for p in self.proxies)
            total_failure = sum(p.failure_count for p in self.proxies)
            overall_rate = total_success / (total_success + total_failure) if (total_success + total_failure) > 0 else 0.0

            return {
                "worker_id": self.worker_id,
                "total_proxies": total,
                "healthy_proxies": healthy,
                "blacklisted_proxies": blacklisted,
                "total_successes": total_success,
                "total_failures": total_failure,
                "overall_success_rate": overall_rate
            }

    def get_proxy_list(self, include_unhealthy: bool = False) -> List[ProxyInfo]:
        """
        Get list of proxies.

        Args:
            include_unhealthy: If True, include unhealthy/blacklisted proxies

        Returns:
            List of ProxyInfo objects
        """
        with self.lock:
            if include_unhealthy:
                return self.proxies.copy()
            else:
                return [p for p in self.proxies if p.is_healthy]


def main():
    """Demo: Test proxy pool."""
    logger.info("=" * 60)
    logger.info("Proxy Pool Demo")
    logger.info("=" * 60)

    # Check if proxy file exists
    proxy_file = "/home/rivercityscrape/Downloads/Webshare 50 proxies.txt"

    if not os.path.exists(proxy_file):
        logger.error(f"Proxy file not found: {proxy_file}")
        logger.info("Please download your proxies from Webshare and save to:")
        logger.info(f"  {proxy_file}")
        return

    # Load proxies
    pool = ProxyPool(proxy_file, blacklist_threshold=5, blacklist_duration_minutes=30)

    # Show stats
    stats = pool.get_stats()
    logger.info("")
    logger.info("Pool Statistics:")
    logger.info(f"  Total proxies: {stats['total_proxies']}")
    logger.info(f"  Healthy proxies: {stats['healthy_proxies']}")
    logger.info(f"  Blacklisted: {stats['blacklisted_proxies']}")

    # Test getting proxies
    logger.info("")
    logger.info("Testing proxy acquisition (round-robin):")
    for i in range(5):
        proxy = pool.get_proxy(strategy="round_robin")
        if proxy:
            logger.info(f"  {i+1}. {proxy}")

    # Simulate some successes and failures
    logger.info("")
    logger.info("Simulating usage...")

    proxy1 = pool.get_proxy()
    pool.report_success(proxy1)
    pool.report_success(proxy1)
    pool.report_success(proxy1)

    proxy2 = pool.get_proxy()
    pool.report_failure(proxy2, "timeout")
    pool.report_failure(proxy2, "403")
    pool.report_failure(proxy2, "429")

    # Show updated stats
    logger.info("")
    logger.info("After simulated usage:")
    for proxy in pool.proxies[:3]:
        logger.info(f"  {proxy}")

    logger.info("")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
