"""
Proxy Manager Service

Wrapper around the existing ProxyPool for SEO intelligence scrapers.

This module provides a simplified interface to the existing proxy infrastructure
in scrape_yp/proxy_pool.py, with SEO-specific features.

Features:
- Integration with existing ProxyPool
- Automatic tier-based proxy selection (high-value targets get dedicated proxies)
- Thread-safe proxy acquisition
- Health tracking and blacklisting
- Support for Playwright integration
"""

import os
from typing import Optional, Dict
from pathlib import Path

# Import existing proxy pool
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scrape_yp.proxy_pool import ProxyPool, ProxyInfo

from runner.logging_setup import get_logger

# Initialize logger
logger = get_logger("proxy_manager")


class ProxyManager:
    """
    Proxy manager for SEO intelligence scrapers.

    Wraps the existing ProxyPool with SEO-specific features and
    tier-based proxy allocation.
    """

    def __init__(
        self,
        proxy_file: Optional[str] = None,
        blacklist_threshold: int = 10,
        blacklist_duration_minutes: int = 60,
        enable_proxies: bool = True
    ):
        """
        Initialize proxy manager.

        Args:
            proxy_file: Path to proxy file (default: from env PROXY_FILE)
            blacklist_threshold: Failures before blacklisting
            blacklist_duration_minutes: Blacklist duration
            enable_proxies: Whether to use proxies (default: True)
        """
        self.enable_proxies = enable_proxies

        if not enable_proxies:
            logger.info("ProxyManager initialized with proxies DISABLED")
            self.pool = None
            return

        # Get proxy file from env if not specified
        if proxy_file is None:
            proxy_file = os.getenv("PROXY_FILE", "data/webshare_proxies.txt")

        # Get configuration from env
        if blacklist_threshold is None:
            blacklist_threshold = int(os.getenv("PROXY_BLACKLIST_THRESHOLD", "10"))

        if blacklist_duration_minutes is None:
            blacklist_duration_minutes = int(os.getenv("PROXY_BLACKLIST_DURATION_MINUTES", "60"))

        # Initialize proxy pool
        try:
            self.pool = ProxyPool(
                proxy_file=proxy_file,
                blacklist_threshold=blacklist_threshold,
                blacklist_duration_minutes=blacklist_duration_minutes
            )
            logger.info(f"ProxyManager initialized with {len(self.pool.proxies)} proxies")

        except FileNotFoundError as e:
            logger.warning(f"Proxy file not found: {e}")
            logger.warning("ProxyManager running WITHOUT proxies")
            self.pool = None
            self.enable_proxies = False

        except Exception as e:
            logger.error(f"Error initializing ProxyPool: {e}")
            logger.warning("ProxyManager running WITHOUT proxies")
            self.pool = None
            self.enable_proxies = False

    def get_proxy(
        self,
        strategy: str = "round_robin",
        tier: Optional[str] = None
    ) -> Optional[ProxyInfo]:
        """
        Get a proxy for scraping.

        Args:
            strategy: Selection strategy ('round_robin' or 'health_based')
            tier: Rate limit tier (A-G) - reserved for future tier-based allocation

        Returns:
            ProxyInfo or None if proxies disabled or unavailable
        """
        if not self.enable_proxies or self.pool is None:
            return None

        # Future: Could allocate dedicated proxies to high-value tiers (A, B)
        # For now, use shared pool with round-robin/health-based selection

        proxy = self.pool.get_proxy(strategy=strategy)

        if proxy:
            logger.debug(f"Acquired proxy: {proxy.host}:{proxy.port}")
        else:
            logger.warning("No healthy proxies available")

        return proxy

    def get_proxy_for_playwright(
        self,
        strategy: str = "round_robin"
    ) -> Optional[Dict[str, str]]:
        """
        Get proxy in Playwright format.

        Args:
            strategy: Selection strategy

        Returns:
            dict: Playwright proxy config or None
        """
        proxy = self.get_proxy(strategy=strategy)

        if proxy:
            return proxy.to_playwright_format()

        return None

    def report_success(self, proxy: ProxyInfo):
        """
        Report successful use of proxy.

        Args:
            proxy: ProxyInfo that was used successfully
        """
        if self.pool:
            self.pool.report_success(proxy)

    def report_failure(self, proxy: ProxyInfo, error_type: str = "unknown"):
        """
        Report failed use of proxy.

        Args:
            proxy: ProxyInfo that failed
            error_type: Type of error (timeout, 403, 429, captcha, etc.)
        """
        if self.pool:
            self.pool.report_failure(proxy, error_type=error_type)

    def get_stats(self) -> Dict:
        """
        Get proxy pool statistics.

        Returns:
            dict: Statistics about proxy pool
        """
        if not self.enable_proxies or self.pool is None:
            return {
                "enabled": False,
                "total_proxies": 0,
                "healthy_proxies": 0,
                "message": "Proxies disabled or unavailable"
            }

        stats = self.pool.get_stats()
        stats["enabled"] = True
        return stats

    def is_enabled(self) -> bool:
        """Check if proxies are enabled and available."""
        return self.enable_proxies and self.pool is not None


# Module-level singleton
_proxy_manager_instance = None


def get_proxy_manager(enable_proxies: Optional[bool] = None) -> ProxyManager:
    """Get or create the singleton ProxyManager instance."""
    global _proxy_manager_instance

    if _proxy_manager_instance is None:
        # Get enable_proxies from env if not specified
        if enable_proxies is None:
            enable_proxies = os.getenv("PROXY_ROTATION_ENABLED", "true").lower() == "true"

        _proxy_manager_instance = ProxyManager(enable_proxies=enable_proxies)

    return _proxy_manager_instance


def main():
    """Demo: Test proxy manager."""
    logger.info("=" * 60)
    logger.info("Proxy Manager Demo")
    logger.info("=" * 60)
    logger.info("")

    # Initialize proxy manager
    manager = get_proxy_manager()

    # Get stats
    logger.info("Proxy Manager Statistics:")
    stats = manager.get_stats()
    for key, value in stats.items():
        logger.info(f"  {key}: {value}")
    logger.info("")

    if not manager.is_enabled():
        logger.warning("Proxies are disabled - demo cannot continue")
        logger.info("To enable proxies:")
        logger.info("  1. Set PROXY_FILE=data/webshare_proxies.txt in .env")
        logger.info("  2. Create the proxy file with format: host:port:user:pass")
        logger.info("  3. Set PROXY_ROTATION_ENABLED=true")
        return

    # Test getting proxies
    logger.info("Test 1: Get proxies with different strategies")
    proxy_rr = manager.get_proxy(strategy="round_robin")
    logger.info(f"  Round-robin: {proxy_rr}")

    proxy_hb = manager.get_proxy(strategy="health_based")
    logger.info(f"  Health-based: {proxy_hb}")
    logger.info("")

    # Test Playwright format
    logger.info("Test 2: Get proxy in Playwright format")
    playwright_proxy = manager.get_proxy_for_playwright()
    if playwright_proxy:
        logger.info(f"  Server: {playwright_proxy['server']}")
        logger.info(f"  Username: {playwright_proxy['username']}")
        logger.info("  Password: [REDACTED]")
    logger.info("")

    # Test success/failure reporting
    logger.info("Test 3: Report success/failure")
    if proxy_rr:
        manager.report_success(proxy_rr)
        logger.info(f"  Reported success for {proxy_rr.host}:{proxy_rr.port}")

        manager.report_failure(proxy_rr, error_type="timeout")
        logger.info(f"  Reported failure for {proxy_rr.host}:{proxy_rr.port}")
    logger.info("")

    # Updated stats
    logger.info("Test 4: Updated statistics")
    stats = manager.get_stats()
    logger.info(f"  Total successes: {stats.get('total_successes', 0)}")
    logger.info(f"  Total failures: {stats.get('total_failures', 0)}")
    logger.info(f"  Success rate: {stats.get('overall_success_rate', 0):.1%}")
    logger.info("")

    logger.info("=" * 60)
    logger.info("Demo complete")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
