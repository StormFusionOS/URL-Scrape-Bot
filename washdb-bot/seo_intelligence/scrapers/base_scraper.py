"""
Base Scraper Class

Provides shared functionality for all SEO intelligence scrapers.

Features:
- Playwright browser management
- Integration with Phase 2 services (rate limiter, robots checker, etc.)
- Common page interaction methods
- Error handling and retries
- Task logging integration

All scrapers (SERP, competitor, backlinks, citations) inherit from this class.
"""

import os
import time
import random
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from contextlib import contextmanager
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeout

from seo_intelligence.services import (
    get_rate_limiter,
    get_robots_checker,
    get_user_agent_rotator,
    get_proxy_manager,
    get_task_logger,
    get_content_hasher,
)
from runner.logging_setup import get_logger


class BaseScraper(ABC):
    """
    Abstract base class for all SEO intelligence scrapers.

    Provides:
    - Browser lifecycle management
    - Rate limiting integration
    - Robots.txt compliance
    - User agent rotation
    - Proxy support
    - Error handling with retries
    """

    def __init__(
        self,
        name: str,
        tier: str = "C",
        headless: bool = True,
        respect_robots: bool = True,
        use_proxy: bool = True,
        max_retries: int = 3,
        page_timeout: int = 30000,
    ):
        """
        Initialize base scraper.

        Args:
            name: Scraper name for logging
            tier: Rate limit tier (A-G, default: C)
            headless: Run browser in headless mode
            respect_robots: Check robots.txt before crawling
            use_proxy: Use proxy pool
            max_retries: Maximum retry attempts on failure
            page_timeout: Page load timeout in milliseconds
        """
        self.name = name
        self.tier = tier
        self.headless = headless
        self.respect_robots = respect_robots
        self.use_proxy = use_proxy
        self.max_retries = max_retries
        self.page_timeout = page_timeout

        # Initialize logger
        self.logger = get_logger(name)

        # Initialize services
        self.rate_limiter = get_rate_limiter()
        self.robots_checker = get_robots_checker()
        self.ua_rotator = get_user_agent_rotator()
        self.proxy_manager = get_proxy_manager()
        self.task_logger = get_task_logger()
        self.content_hasher = get_content_hasher()

        # Browser state
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

        # Statistics
        self.stats = {
            "pages_crawled": 0,
            "pages_skipped": 0,
            "pages_failed": 0,
            "robots_blocked": 0,
            "rate_limited": 0,
        }

        self.logger.info(f"{name} initialized (tier={tier}, headless={headless})")

    def _get_random_delay(self) -> float:
        """Get randomized delay based on tier configuration."""
        from seo_intelligence.services.rate_limiter import TIER_CONFIGS

        config = TIER_CONFIGS.get(self.tier, TIER_CONFIGS["C"])
        delay = random.uniform(config.min_delay_seconds, config.max_delay_seconds)
        return delay

    def _check_robots(self, url: str) -> bool:
        """
        Check if URL is allowed by robots.txt.

        Args:
            url: URL to check

        Returns:
            bool: True if allowed (or robots check disabled), False otherwise
        """
        if not self.respect_robots:
            return True

        allowed = self.robots_checker.is_allowed(url)

        if not allowed:
            self.logger.warning(f"URL blocked by robots.txt: {url}")
            self.stats["robots_blocked"] += 1

        return allowed

    def _acquire_rate_limit(self, domain: str) -> bool:
        """
        Acquire rate limit token for domain.

        Args:
            domain: Domain to acquire token for

        Returns:
            bool: True if acquired, False if failed
        """
        # Set tier for domain if not already set
        self.rate_limiter.set_domain_tier(domain, self.tier)

        # Try to acquire with reasonable max wait
        acquired = self.rate_limiter.acquire(domain, wait=True, max_wait=60.0)

        if not acquired:
            self.logger.warning(f"Rate limit timeout for {domain}")
            self.stats["rate_limited"] += 1

        return acquired

    @contextmanager
    def browser_session(self):
        """
        Context manager for browser session.

        Usage:
            with scraper.browser_session() as (browser, context, page):
                page.goto("https://example.com")
                # ... scrape content ...
        """
        playwright = None
        browser = None
        context = None
        page = None

        try:
            # Start Playwright
            playwright = sync_playwright().start()

            # Get proxy if enabled
            proxy_config = None
            if self.use_proxy:
                proxy_config = self.proxy_manager.get_proxy_for_playwright()

            # Get random user agent
            user_agent = self.ua_rotator.get_random()

            # Launch browser
            browser = playwright.chromium.launch(
                headless=self.headless,
            )

            # Create context with user agent and optional proxy
            context_options = {
                "user_agent": user_agent,
                "viewport": {"width": 1920, "height": 1080},
            }

            if proxy_config:
                context_options["proxy"] = proxy_config
                self.logger.debug(f"Using proxy: {proxy_config.get('server', 'N/A')}")

            context = browser.new_context(**context_options)
            context.set_default_timeout(self.page_timeout)

            # Create page
            page = context.new_page()

            self.logger.debug(f"Browser session started (UA: {user_agent[:50]}...)")

            yield browser, context, page

        except Exception as e:
            self.logger.error(f"Browser session error: {e}", exc_info=True)
            raise

        finally:
            # Cleanup
            if page:
                try:
                    page.close()
                except Exception:
                    pass

            if context:
                try:
                    context.close()
                except Exception:
                    pass

            if browser:
                try:
                    browser.close()
                except Exception:
                    pass

            if playwright:
                try:
                    playwright.stop()
                except Exception:
                    pass

            self.logger.debug("Browser session closed")

    def fetch_page(
        self,
        url: str,
        page: Page,
        wait_for: str = "domcontentloaded",
        extra_wait: float = 0,
    ) -> Optional[str]:
        """
        Fetch a page with all checks and rate limiting.

        Args:
            url: URL to fetch
            page: Playwright Page object
            wait_for: Wait condition ('domcontentloaded', 'load', 'networkidle')
            extra_wait: Additional wait time in seconds after page load

        Returns:
            str: Page HTML content, or None if failed
        """
        domain = urlparse(url).netloc

        # Check robots.txt
        if not self._check_robots(url):
            self.stats["pages_skipped"] += 1
            return None

        # Acquire rate limit token
        if not self._acquire_rate_limit(domain):
            self.stats["pages_skipped"] += 1
            return None

        # Fetch page with retries
        for attempt in range(self.max_retries):
            try:
                self.logger.debug(f"Fetching {url} (attempt {attempt + 1}/{self.max_retries})")

                response = page.goto(url, wait_until=wait_for)

                if response is None:
                    self.logger.warning(f"No response from {url}")
                    continue

                if response.status >= 400:
                    self.logger.warning(f"HTTP {response.status} from {url}")

                    if response.status == 429:
                        # Rate limited - wait and retry
                        wait_time = self._get_random_delay() * 2
                        self.logger.info(f"Rate limited, waiting {wait_time:.1f}s...")
                        time.sleep(wait_time)
                        continue

                    if response.status >= 500:
                        # Server error - retry
                        continue

                    # Client error - don't retry
                    self.stats["pages_failed"] += 1
                    return None

                # Extra wait for JavaScript rendering
                if extra_wait > 0:
                    time.sleep(extra_wait)

                # Get page content
                content = page.content()

                self.stats["pages_crawled"] += 1
                self.logger.debug(f"Fetched {url} ({len(content)} chars)")

                # Add random delay before next request
                delay = self._get_random_delay()
                time.sleep(delay)

                return content

            except PlaywrightTimeout as e:
                self.logger.warning(f"Timeout fetching {url}: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self._get_random_delay())
                continue

            except Exception as e:
                self.logger.error(f"Error fetching {url}: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self._get_random_delay())
                continue

        # All retries failed
        self.stats["pages_failed"] += 1
        self.logger.error(f"Failed to fetch {url} after {self.max_retries} attempts")
        return None

    def get_stats(self) -> Dict[str, int]:
        """Get scraper statistics."""
        return self.stats.copy()

    def reset_stats(self):
        """Reset scraper statistics."""
        self.stats = {
            "pages_crawled": 0,
            "pages_skipped": 0,
            "pages_failed": 0,
            "robots_blocked": 0,
            "rate_limited": 0,
        }

    @abstractmethod
    def run(self, *args, **kwargs) -> Dict[str, Any]:
        """
        Run the scraper.

        Subclasses must implement this method.

        Returns:
            dict: Results of the scraping operation
        """
        pass
