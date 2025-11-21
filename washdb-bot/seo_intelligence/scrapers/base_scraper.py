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
from typing import Optional, Dict, Any, List, Tuple
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
    get_domain_quarantine,
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
        self.domain_quarantine = get_domain_quarantine()

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
        """
        Get randomized delay based on tier configuration with ±20% jitter.

        Per SCRAPING_NOTES.md §3: "Per-request base delay: 3-6s with ±20% jitter"
        """
        from seo_intelligence.services.rate_limiter import TIER_CONFIGS

        config = TIER_CONFIGS.get(self.tier, TIER_CONFIGS["C"])
        delay = random.uniform(config.min_delay_seconds, config.max_delay_seconds)

        # Add ±20% jitter per spec
        jitter = delay * random.uniform(-0.20, 0.20)
        final_delay = max(0.1, delay + jitter)  # Ensure minimum 0.1s delay

        self.logger.debug(f"Delay: {delay:.2f}s + jitter {jitter:.2f}s = {final_delay:.2f}s")
        return final_delay

    def _apply_base_delay(self):
        """
        Apply base delay (3-6s with ±20% jitter) before each request.

        Per SCRAPING_NOTES.md §3: "Per-request base delay: 3-6s with ±20% jitter"
        This is in addition to tier-specific rate limiting.
        """
        base_delay = random.uniform(3.0, 6.0)
        jitter = base_delay * random.uniform(-0.20, 0.20)
        final_delay = max(0.5, base_delay + jitter)  # Ensure minimum 0.5s

        self.logger.debug(f"Base delay: {base_delay:.2f}s + jitter {jitter:.2f}s = {final_delay:.2f}s")
        time.sleep(final_delay)

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

    @contextmanager
    def _rate_limit_and_concurrency(self, domain: str):
        """
        Context manager for rate limiting and concurrency control.

        Enforces per SCRAPING_NOTES.md §3:
        - Global max concurrency: 5
        - Per-domain max concurrency: 1
        - Per-request base delay: 3-6s with ±20% jitter
        - Tier-specific rate limits

        Usage:
            with self._rate_limit_and_concurrency(domain):
                # Make request to domain
                pass

        Args:
            domain: Domain to rate limit
        """
        # Set tier for domain if not already set
        self.rate_limiter.set_domain_tier(domain, self.tier)

        # Acquire concurrency permits (global + per-domain)
        if not self.rate_limiter.acquire_concurrency(domain, timeout=60.0):
            self.logger.warning(f"Concurrency timeout for {domain}")
            self.stats["rate_limited"] += 1
            raise RuntimeError(f"Failed to acquire concurrency permits for {domain}")

        try:
            # Acquire rate limit token
            if not self.rate_limiter.acquire(domain, wait=True, max_wait=60.0):
                self.logger.warning(f"Rate limit timeout for {domain}")
                self.stats["rate_limited"] += 1
                raise RuntimeError(f"Failed to acquire rate limit token for {domain}")

            # Apply base delay with jitter (3-6s ±20%)
            self._apply_base_delay()

            # Yield control to caller
            yield

        finally:
            # Always release concurrency permits
            self.rate_limiter.release_concurrency(domain)

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

    def _validate_html_response(
        self,
        html: str,
        url: str,
        content_type: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate HTML response for sanity checks.

        Detects:
        - Non-HTML MIME types
        - CAPTCHA pages
        - Bot detection pages
        - Missing essential HTML elements

        Args:
            html: HTML content
            url: URL being validated
            content_type: Content-Type header value

        Returns:
            Tuple of (is_valid, reason_code)
            - is_valid: True if HTML passes sanity checks
            - reason_code: None if valid, otherwise error code
        """
        if not html or len(html.strip()) < 100:
            return False, "EMPTY_RESPONSE"

        # Check Content-Type if provided
        if content_type:
            if not any(ct in content_type.lower() for ct in ['text/html', 'application/xhtml']):
                self.logger.warning(f"Non-HTML content type: {content_type} for {url}")
                return False, "NON_HTML_MIME"

        html_lower = html.lower()

        # Check for CAPTCHA indicators
        captcha_indicators = [
            'captcha',
            'recaptcha',
            'g-recaptcha',
            'hcaptcha',
            'cf-challenge',  # Cloudflare challenge
            'please verify you are human',
            'security check',
            'unusual traffic',
        ]

        for indicator in captcha_indicators:
            if indicator in html_lower:
                self.logger.warning(f"CAPTCHA detected on {url}: {indicator}")
                return False, "CAPTCHA_DETECTED"

        # Check for bot detection / anti-scraping
        bot_detection_indicators = [
            'access denied',
            'blocked',
            'forbidden',
            'your access to this site has been limited',
            'enable javascript',
            'javascript is disabled',
            'please enable cookies',
        ]

        for indicator in bot_detection_indicators:
            if indicator in html_lower:
                self.logger.warning(f"Bot detection page on {url}: {indicator}")
                return False, "BOT_DETECTED"

        # Check for essential HTML elements
        if '<title>' not in html_lower and '<title ' not in html_lower:
            self.logger.warning(f"Missing <title> tag on {url}")
            return False, "NO_TITLE_TAG"

        # Check for minimal HTML structure
        if '<html' not in html_lower and '<!doctype html' not in html_lower:
            self.logger.warning(f"Invalid HTML structure on {url}")
            return False, "INVALID_HTML"

        # Passed all checks
        return True, None

    def fetch_page(
        self,
        url: str,
        page: Page,
        wait_for: str = "domcontentloaded",
        extra_wait: float = 0,
    ) -> Optional[str]:
        """
        Fetch a page with all checks and rate limiting.

        Integrates Phase 2 enhancements:
        - Domain quarantine checks
        - Exponential backoff on errors
        - Automatic quarantine on 403, repeated 429, CAPTCHA
        - Retry-After header respect

        Args:
            url: URL to fetch
            page: Playwright Page object
            wait_for: Wait condition ('domcontentloaded', 'load', 'networkidle')
            extra_wait: Additional wait time in seconds after page load

        Returns:
            str: Page HTML content, or None if failed
        """
        domain = urlparse(url).netloc

        # Check if domain is quarantined (Task 11: Ethical Crawling)
        if self.domain_quarantine.is_quarantined(domain):
            quarantine_end = self.domain_quarantine.get_quarantine_end(domain)
            self.logger.warning(
                f"Domain {domain} is quarantined until {quarantine_end}, skipping"
            )
            self.stats["pages_skipped"] += 1
            return None

        # Check robots.txt
        if not self._check_robots(url):
            self.stats["pages_skipped"] += 1
            return None

        # Fetch page with retries and exponential backoff
        for attempt in range(self.max_retries):
            # Apply exponential backoff delay (Task 11)
            retry_attempt = self.domain_quarantine.get_retry_attempt(domain)
            backoff_delay = self.domain_quarantine.get_backoff_delay(retry_attempt)

            if backoff_delay > 0:
                self.logger.info(
                    f"Exponential backoff for {domain}: waiting {backoff_delay}s "
                    f"(retry attempt {retry_attempt})"
                )
                time.sleep(backoff_delay)

            try:
                self.logger.debug(f"Fetching {url} (attempt {attempt + 1}/{self.max_retries})")

                response = page.goto(url, wait_until=wait_for)

                if response is None:
                    self.logger.warning(f"No response from {url}")
                    continue

                # Handle HTTP errors
                if response.status >= 400:
                    self.logger.warning(f"HTTP {response.status} from {url}")

                    # 403 Forbidden - Quarantine domain immediately (Task 11)
                    if response.status == 403:
                        self.logger.error(f"403 Forbidden from {domain} - quarantining")
                        self.domain_quarantine.quarantine_domain(
                            domain=domain,
                            reason="403_FORBIDDEN",
                            metadata={"url": url, "attempt": attempt}
                        )
                        self.stats["pages_failed"] += 1
                        return None

                    # 429 Rate Limited - Record event (auto-quarantines after 3) (Task 11)
                    if response.status == 429:
                        self.domain_quarantine.record_error_event(domain, "429")

                        # Check for Retry-After header
                        retry_after = response.headers.get('retry-after')
                        retry_after_seconds = None

                        if retry_after:
                            try:
                                retry_after_seconds = int(retry_after)
                                self.logger.info(
                                    f"Rate limited, Retry-After: {retry_after_seconds}s"
                                )
                            except ValueError:
                                # Retry-After might be a date, ignore for now
                                pass

                        # Use exponential backoff if no Retry-After
                        wait_time = retry_after_seconds if retry_after_seconds else (
                            self._get_random_delay() * 2
                        )

                        self.logger.info(f"Rate limited, waiting {wait_time:.1f}s...")
                        time.sleep(wait_time)
                        continue

                    # 5xx Server Errors - Record event (auto-quarantines after 3) (Task 11)
                    if response.status >= 500:
                        self.domain_quarantine.record_error_event(
                            domain,
                            f"{response.status}"
                        )
                        self.logger.warning(
                            f"Server error {response.status}, retrying with backoff..."
                        )
                        continue

                    # Other client errors - don't retry
                    self.stats["pages_failed"] += 1
                    return None

                # Extra wait for JavaScript rendering
                if extra_wait > 0:
                    time.sleep(extra_wait)

                # Get page content
                content = page.content()

                # Validate HTML response
                content_type = response.headers.get('content-type')
                is_valid, reason_code = self._validate_html_response(content, url, content_type)

                if not is_valid:
                    self.logger.warning(f"HTML validation failed for {url}: {reason_code}")

                    # Quarantine domain on CAPTCHA or bot detection (Task 11)
                    if reason_code in ("CAPTCHA_DETECTED", "BOT_DETECTED"):
                        self.logger.error(
                            f"{reason_code} on {domain} - quarantining for 60 minutes"
                        )
                        self.domain_quarantine.quarantine_domain(
                            domain=domain,
                            reason=reason_code,
                            duration_minutes=60,
                            metadata={"url": url, "validation_failure": reason_code}
                        )

                    self.stats["pages_failed"] += 1
                    return None

                # SUCCESS - Reset retry attempts (Task 11)
                self.domain_quarantine.reset_retry_attempts(domain)

                self.stats["pages_crawled"] += 1
                self.logger.debug(f"Fetched {url} ({len(content)} chars) - validation passed")

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
